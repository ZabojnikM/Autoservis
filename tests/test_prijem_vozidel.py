"""#51 Příjem vozidel – čtení visits.json z OpenBotu (anonymizovaná data)."""
import json
import os
import re

import pytest

from app import config
from app.models import Zakaznik
from app.services import prijem_vozidel, vozidla, zakazky
from tests.test_web import client


def _navsteva(id_, created, spz="1AB2345", vin="TMBAA00000000001", km=120000, technicke=None, nejiste=None):
    return {"id": id_, "created_at": created, "updated_at": created, "revision": 1,
            "vehicle": {"spz": spz, "vin": vin, "odometer_km": km,
                        "technical_data": technicke if technicke is not None else
                        {"TovarniZnacka": "ŠKODA", "ObchodniOznaceni": "OCTAVIA", "Palivo": "NM"},
                        "uncertain_fields": nejiste or [], "sources": {"tajne": "x"}},
            "events": [{"tajne": "udalost"}], "photos": ["/fotky/1.jpg"]}


@pytest.fixture
def soubor(tmp_path, monkeypatch):
    cesta = tmp_path / "visits.json"
    monkeypatch.setattr(config, "PRIJEM_JSON", str(cesta))

    def zapis(visits, **navic):
        data = {"schema": "autoservis.visits.v1", "version": 7, "updated_at": "2026-11-19T10:00:00Z",
                "visits": visits} | navic
        docasny = tmp_path / "visits.tmp"
        docasny.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        os.replace(docasny, cesta)  # atomické nahrazení jako v OpenBotu
    return zapis


def test_seznam_od_nejnovejsiho_a_dve_navstevy_stejneho_auta(soubor):
    soubor([_navsteva("a1", "2026-11-18T08:00:00Z"), _navsteva("a2", "2026-11-19T09:30:00Z", km=120500),
            _navsteva("b1", "2026-11-17T07:00:00Z", spz="9Z99999", vin="", km=None, technicke={})])
    prijmy = prijem_vozidel.nacti()
    assert [n.id for n in prijmy.navstevy] == ["a2", "a1", "b1"]  # od nejnovějšího
    text = client.get("/prijem").text
    assert ">Příjem vozidel</a>" in text and 'class="striped klik-otevre prijem-seznam"' in text
    km = [t.replace(" ", " ") for t in re.findall(r"12\d.\d00", text)]
    assert text.count("1AB2345") == 2 and km[:2] == ["120 500", "120 000"]  # dvě návštěvy stejného auta
    assert "<span>ŠKODA OCTAVIA</span>" in text  # #82: značka a model dohromady
    assert '<span class="prazdne">—</span>' in text and "Neuvedeno" not in text  # #57: chybějící VIN / km / značka = pomlčka
    # #82: [akce + stav] → SPZ → Vozidlo → Zákazník → VIN → Km → Přijato
    hlavicka = re.findall(r"<th[^>]*>([^<]*)</th>", text.split("<thead>")[1].split("</thead>")[0])
    assert hlavicka == ["", "SPZ", "Vozidlo", "Zákazník", "VIN", "Km", "Přijato"]
    assert 'data-kopirovat="TMBAA00000000001"' in _radek(text, "a1")  # kopírování VIN
    assert "tajne" not in text and "/fotky/" not in text  # sources, events, fotky se nezobrazují


def test_detail_nejisty_vin_a_chybejici_hodnoty(soubor):
    soubor([_navsteva("x 1", "2026-11-19T09:30:00Z", nejiste=["vehicle.vin"]),
            _navsteva("x2", "2026-11-19T08:00:00Z", spz=None, vin=None, km=None, technicke={})])
    detail = client.get("/prijem/x%201").text
    assert "1AB2345" in detail and "TMBAA00000000001" in detail
    vin = detail.split("<dt>VIN</dt>")[1].split("</dd>")[0]
    assert 'class="nejiste"' in vin  # nejistý VIN je označený
    assert "TovarniZnacka" in detail and "Palivo" in detail and "tajne" not in detail
    karty = re.findall(r'<h2 class="titulek-panelu">([^<]+)</h2>', detail)
    assert karty == ["Vozidlo", "V databázi", "Technické údaje z registru", "Příjem"]  # #53: prohozené
    prazdny = client.get("/prijem/x2").text
    assert prazdny.count("Neuvedeno") >= 4 and 'class="nejiste"' not in prazdny
    r = client.get("/prijem/neexistuje")
    assert r.status_code == 404 and "už v seznamu není" in r.text


def test_prazdny_neplatny_a_nedostupny_soubor(soubor, tmp_path, monkeypatch):
    soubor([])
    assert "Zatím žádné příjmy" in client.get("/prijem").text
    soubor([], schema="neco.jineho")
    assert "Příjem vozidel je dočasně nedostupný" in client.get("/prijem").text
    (tmp_path / "visits.json").write_text("{nedokončený json", encoding="utf-8")
    assert "Příjem vozidel je dočasně nedostupný" in client.get("/prijem").text
    monkeypatch.setattr(config, "PRIJEM_JSON", str(tmp_path / "neni.json"))
    assert "Příjem vozidel je dočasně nedostupný" in client.get("/prijem").text
    assert client.get("/zakazky").status_code == 200  # chyba příjmu neomezí zakázky


def test_nova_navsteva_bez_restartu(soubor):
    soubor([_navsteva("a1", "2026-11-18T08:00:00Z")])
    assert "Příjmů: 1" in client.get("/prijem").text
    soubor([_navsteva("a1", "2026-11-18T08:00:00Z"), _navsteva("n1", "2026-11-19T11:00:00Z", spz="5N55555")])
    text = client.get("/prijem").text  # Obnovit = nové načtení, soubor se otevře znovu
    assert "Příjmů: 2" in text and "5N55555" in text


# ---------------------------------------------------------------- je vozidlo v databázi?

def _radek(text, id_):
    return next(r for r in text.split("<tr ") if f'data-prijem="{id_}"' in r).split("</tr>")[0]


def test_v_databazi_podle_spz_nebo_vin_a_konflikt(soubor, session):
    a = vozidla.vytvor(session, {"spz": "1AB2345", "vin": "TMBAA000000000001", "znacka": "Škoda"})
    a.zakaznik = Zakaznik(nazev="TEST Novák")
    session.add(a)
    session.commit()
    b = vozidla.vytvor(session, {"spz": "2BB2222", "vin": "WVWZZZ00000000002"})
    soubor([_navsteva("spz", "2026-11-19T10:00:00Z", vin=""),
            _navsteva("vin", "2026-11-19T09:00:00Z", spz="1AB 2345", vin="tmbaa000000000001"),
            _navsteva("nova", "2026-11-19T08:00:00Z", spz="7X77777", vin="ZZZ00000000000007"),
            _navsteva("konf", "2026-11-19T07:00:00Z", spz="1AB2345", vin="WVWZZZ00000000002"),
            _navsteva("zmena", "2026-11-19T06:00:00Z", spz="3C33333", vin="WVWZZZ00000000002"),
            _navsteva("jinyvin", "2026-11-19T05:00:00Z", spz="2BB2222", vin="XXX00000000000009")])
    prijmy = prijem_vozidel.nacti()
    s = {n.id: prijem_vozidel.sparuj(session, n) for n in prijmy.navstevy}
    assert s["spz"].stav == "v_databazi" and s["spz"].vozidlo.id == a.id and not s["spz"].upozorneni
    assert s["vin"].stav == "v_databazi" and s["vin"].podle_spz and s["vin"].podle_vin  # normalizace SPZ i VIN
    assert s["nova"].stav == "neni"
    assert s["konf"].stav == "konflikt" and "1AB2345" in s["konf"].upozorneni and "2BB2222" in s["konf"].upozorneni
    assert s["zmena"].stav == "v_databazi" and "jinou SPZ: 2BB2222" in s["zmena"].upozorneni  # nová SPZ
    assert s["jinyvin"].stav == "v_databazi" and "jiný VIN" in s["jinyvin"].upozorneni

    text = client.get("/prijem").text
    radek = _radek(text, "spz")
    assert f'data-otevrit="/zakazky/nova?vozidlo_id={a.id}&amp;tachometr=120000" data-okno' in radek
    assert ">Nová zakázka</a>" in radek and "Vozidlo je v databázi" in radek and "Podrobnosti" not in radek  # #72
    assert "TEST Novák" in radek  # #82: zákazník z naší databáze
    assert "akce-nova" in radek and radek.index("hlavni-akce") < radek.index("Vozidlo je v databázi") < radek.index("1AB2345")
    radek = _radek(text, "nova")
    assert 'data-otevrit="/vozidla/nove?prijem=nova" data-okno' in radek and ">Založit vozidlo</a>" in radek
    assert "akce-zalozit" in radek
    assert "Vozidlo není v databázi" in radek
    radek = _radek(text, "konf")
    assert 'data-otevrit="/prijem/konf"' in radek and "Konflikt SPZ / VIN" in radek
    assert "Nová zakázka" not in radek and "Založit vozidlo" not in radek
    assert "nesoulad" in _radek(text, "zmena")

    detail = client.get("/prijem/konf").text
    assert f'href="/vozidla/{a.id}"' in detail and f'href="/vozidla/{b.id}"' in detail
    assert "Ověřte údaje" in detail


def test_otevrena_zakazka_a_zalozeni_vozidla_z_prijmu(soubor, session):
    a = vozidla.vytvor(session, {"spz": "1AB2345", "vin": "TMBAA000000000001"})
    zak = zakazky.prijem_z_formulare(session, {"pozadavek": "Servis"}, {"vozidlo_id": str(a.id), "spz": "1AB2345"},
                                     {})
    soubor([_navsteva("a1", "2026-11-19T10:00:00Z", vin="TMBAA000000000001"),
            _navsteva("n1", "2026-11-19T09:00:00Z", spz="7X77777", vin="ZZZ00000000000007",
                      technicke={"TovarniZnacka": "ŠKODA", "ObchodniOznaceni": "FABIA", "VIN": "ZZZ00000000000007"})])
    radek = _radek(client.get("/prijem").text, "a1")
    assert f'data-otevrit="/zakazky/{zak.id}"' in radek and ">Otevřít zakázku</a>" in radek
    assert "Zakázka už existuje" in radek  # #82
    assert "data-okno" not in radek.split(">")[0]  # existující zakázka = celá stránka
    # nová zakázka převezme stav km
    assert 'value="120000"' in client.get("/zakazky/nova", params={"vozidlo_id": a.id, "tachometr": "120000"}).text
    # založení vozidla: předvyplněné z příjmu, po uložení zpět na příjem
    form = client.get("/vozidla/nove", params={"prijem": "n1", "okno": "1"}).text
    assert 'value="7X77777"' in form and 'value="ZZZ00000000000007"' in form and 'name="z_prijmu"' in form
    assert "FABIA" in form.upper()
    r = client.post("/vozidla/nove", data={"spz": "7X77777", "vin": "ZZZ00000000000007", "z_prijmu": "1"},
                    follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/prijem")
    radek = _radek(client.get("/prijem").text, "n1")
    assert "Vozidlo je v databázi" in radek and ">Nová zakázka</a>" in radek
