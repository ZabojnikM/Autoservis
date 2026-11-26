"""#51, #216 Příjem vozidel – příjmy v databázi (zapisuje Přijímací technik přes MCP), anonymizovaná data."""
import asyncio
import json
import re
from datetime import datetime

import pytest
from mcp.server.mcpserver.exceptions import ToolError
from sqlmodel import select

from app.mcp_server import server
from app.models import PrijemVozidla, Vozidlo, Zakaznik, Zakazka
from app.services import ChybaValidace, api_klice, prijem_vozidel, registr_vozidel, vozidla, zakazky
from tests.test_web import client


def _navsteva(id_, created, spz="1AB2345", vin="TMBAA00000000001", km=120000, technicke=None, nejiste=None):
    return {"id": id_, "created_at": created, "updated_at": created, "revision": 1,
            "vehicle": {"spz": spz, "vin": vin, "odometer_km": km,
                        "technical_data": technicke if technicke is not None else
                        {"TovarniZnacka": "ŠKODA", "ObchodniOznaceni": "OCTAVIA", "Palivo": "NM"},
                        "uncertain_fields": nejiste or [], "sources": {"tajne": "x"}},
            "events": [{"tajne": "udalost"}], "photos": ["/fotky/1.jpg"]}


@pytest.fixture
def soubor(session):
    """Naplní tabulku příjmů (dřív visits.json) – časy založení podle `created_at`."""
    def zapis(visits):
        for r in session.exec(select(PrijemVozidla)):
            session.delete(r)
        for v in visits:
            voz = v["vehicle"]
            cas = datetime.fromisoformat(v["created_at"].replace("Z", "+00:00")).astimezone().replace(tzinfo=None)
            session.add(PrijemVozidla(id=v["id"], vytvoreno=cas, upraveno=cas, revize=v["revision"], spz=voz["spz"],
                                      vin=voz["vin"] or None, km=voz["odometer_km"],
                                      technicke=json.dumps(voz["technical_data"], ensure_ascii=False),
                                      nejiste=json.dumps(voz["uncertain_fields"])))
        session.commit()
    return zapis


def test_seznam_od_nejnovejsiho_a_dve_navstevy_stejneho_auta(soubor, session):
    soubor([_navsteva("a1", "2026-11-18T08:00:00Z"), _navsteva("a2", "2026-11-19T09:30:00Z", km=120500),
            _navsteva("b1", "2026-11-17T07:00:00Z", spz="9Z99999", vin="", km=None, technicke={})])
    prijmy = prijem_vozidel.nacti(session)
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


def test_prazdny_seznam(soubor):
    soubor([])
    assert "Zatím žádné příjmy" in client.get("/prijem").text
    assert "dočasně nedostupný" not in client.get("/prijem").text


def test_nova_navsteva_bez_restartu(soubor):
    soubor([_navsteva("a1", "2026-11-18T08:00:00Z")])
    assert "Příjmů: 1" in client.get("/prijem").text
    soubor([_navsteva("a1", "2026-11-18T08:00:00Z"), _navsteva("n1", "2026-11-19T11:00:00Z", spz="5N55555")])
    text = client.get("/prijem").text  # Obnovit = nové načtení z databáze
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
    prijmy = prijem_vozidel.nacti(session)
    s = {n.id: prijem_vozidel.sparuj(session, n) for n in prijmy.navstevy}
    assert s["spz"].stav == "v_databazi" and s["spz"].vozidlo.id == a.id and not s["spz"].upozorneni
    assert s["vin"].stav == "v_databazi" and s["vin"].podle_spz and s["vin"].podle_vin  # normalizace SPZ i VIN
    assert s["nova"].stav == "neni"
    assert s["konf"].stav == "konflikt" and "1AB2345" in s["konf"].upozorneni and "2BB2222" in s["konf"].upozorneni
    assert s["zmena"].stav == "v_databazi" and "jinou SPZ: 2BB2222" in s["zmena"].upozorneni  # nová SPZ
    assert s["jinyvin"].stav == "v_databazi" and "jiný VIN" in s["jinyvin"].upozorneni

    text = client.get("/prijem").text
    radek = _radek(text, "spz")
    assert 'data-otevrit="/prijem/spz"' in radek and "data-okno" not in radek.split(">")[0]  # #85: řádek = podrobnosti
    assert f'href="/zakazky/nova?vozidlo_id={a.id}&amp;tachometr=120000"' in radek
    assert ">Nová zakázka</a>" in radek and "Vozidlo je v databázi" in radek and "Podrobnosti" not in radek  # #72
    assert "TEST Novák" in radek  # #82: zákazník z naší databáze
    assert "akce-nova" in radek and radek.index("hlavni-akce") < radek.index("Vozidlo je v databázi") < radek.index("1AB2345")
    radek = _radek(text, "nova")
    assert 'data-otevrit="/prijem/nova"' in radek and 'href="/vozidla/nove?prijem=nova"' in radek
    assert ">Založit vozidlo</a>" in radek
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
    assert 'data-otevrit="/prijem/a1"' in radek and f'href="/zakazky/{zak.id}"' in radek
    assert ">Otevřít zakázku</a>" in radek
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


# ---------------------------------------------------------------- #216 zápis přes MCP, vyhodnocení v Autoservisu

REGISTR_FABIA = {"VIN": "TMBZZZ5J0A1234567", "TovarniZnacka": "ŠKODA", "ObchodniOznaceni": "FABIA"}


@pytest.fixture
def registr(monkeypatch, session):
    """Podstrčený Registr vozidel – skutečný se v testech nevolá. Vrací seznam volaných VIN."""
    from app.services import nastaveni
    nastaveni.uloz(session, {"api_klic_registr": "testovaci-klic"})
    volani = []

    def falesny(parametry, klic):
        volani.append(parametry["vin"])
        if parametry["vin"] == REGISTR_FABIA["VIN"]:
            return {"Data": REGISTR_FABIA}
        if parametry["vin"] == "TMBZZZ5J0A9999999":
            raise registr_vozidel.ChybaRegistru("Registr vozidel neodpovídá – zkontrolujte připojení k internetu.")
        return {"Data": None}
    monkeypatch.setattr(registr_vozidel, "_stahni", falesny)
    return volani


def test_oprava_vin():
    assert vozidla.oprav_vin(" tmb-zzz 5j oa1234567 ") == ("TMBZZZ5J0A1234567", ["O → 0 (pozice 9)"])
    assert vozidla.oprav_vin("TMBIZZ5JQA1234567")[0] == "TMB1ZZ5J0A1234567"
    assert vozidla.oprav_vin("") == (None, [])


def test_spz_v_databazi_doplni_vin_a_km(session, registr):
    vozidla.vytvor(session, {"spz": "1AB2345", "vin": "TMBAA000000000001"})
    v = prijem_vozidel.uloz(session, {"spz": "1ab 2345", "km": "156 000"})
    assert (v.stav, v.vin_z_databaze, v.spojeno) == ("hotovo", True, False)
    assert v.radek.vin == "TMBAA000000000001" and v.radek.km == 156000 and registr == []  # registr se nevolá


def test_chybi_vin_pak_doplneni_stejneho_auta(session, registr):
    vozidla.vytvor(session, {"spz": "2BB2222"})  # v databázi bez VIN
    v = prijem_vozidel.uloz(session, {"spz": "2BB2222", "km": 90000})
    assert v.stav == "chybi_vin" and "VIN" in v.dalsi_krok
    # VIN poslaný s id příjmu (technik se na něj ptal) – O se opraví na 0
    v2 = prijem_vozidel.uloz(session, {"id": v.radek.id, "vin": "WVWZZZ1KZOW123456"})
    assert v2.radek.id == v.radek.id and v2.radek.vin == "WVWZZZ1KZ0W123456" and v2.opravy_vin == ["O → 0 (pozice 10)"]
    assert v2.stav == "hotovo" and v2.radek.km == 90000
    # stejná SPZ znovu bez id = doplnění, ne druhý příjem
    v3 = prijem_vozidel.uloz(session, {"spz": "2BB 2222", "km": 90100})
    assert v3.spojeno and v3.radek.id == v.radek.id and len(prijem_vozidel.nacti(session).navstevy) == 1


def test_jina_spz_je_nove_auto(session, registr):
    v = prijem_vozidel.uloz(session, {"spz": "3CC3333", "km": 10})
    assert v.stav == "chybi_vin"
    with pytest.raises(ChybaValidace, match="jiné auto"):
        prijem_vozidel.uloz(session, {"id": v.radek.id, "spz": "4DD4444"})
    v2 = prijem_vozidel.uloz(session, {"spz": "4DD4444"})
    assert not v2.spojeno and v2.radek.id != v.radek.id
    assert [n.stav for n in prijem_vozidel.nacti(session).navstevy] == ["chybi_vin", "chybi_vin"]  # první zůstal


def test_nove_auto_z_registru_a_chyby_registru(session, registr):
    v = prijem_vozidel.uloz(session, {"spz": "5EE5555", "vin": "TMBZZZ5J0A1234567", "km": 1})
    assert v.stav == "nove_auto" and "Škoda Fabia" in v.zprava and registr == ["TMBZZZ5J0A1234567"]
    assert prijem_vozidel.najdi(session, v.radek.id).popis == "ŠKODA FABIA"
    prijem_vozidel.uloz(session, {"id": v.radek.id, "km": 2})
    assert registr == ["TMBZZZ5J0A1234567"]  # údaje už má, registr se znovu nevolá
    assert prijem_vozidel.uloz(session, {"spz": "6FF6666", "vin": "TMBZZZ5J0A0000000"}).stav == "vin_nenalezen"
    nedostupny = prijem_vozidel.uloz(session, {"spz": "7GG7777", "vin": "TMBZZZ5J0A9999999"})
    assert nedostupny.stav == "registr_nedostupny" and "neodpovídá" in nedostupny.zprava
    assert prijem_vozidel.uloz(session, {"id": nedostupny.radek.id, "km": 5}).stav == "registr_nedostupny"
    assert registr.count("TMBZZZ5J0A9999999") == 2  # při doplnění se registr zkusí znovu


def test_neplatny_vin_nesedi_a_konflikt(session, registr):
    a = vozidla.vytvor(session, {"spz": "1AB2345", "vin": "TMBAA000000000001"})
    vozidla.vytvor(session, {"spz": "2BB2222", "vin": "WVWZZZ00000000002"})
    v = prijem_vozidel.uloz(session, {"spz": "8HH8888", "vin": "TMB123"})
    assert v.stav == "vin_neplatny" and v.radek.vin is None and v.radek.spz == "8HH8888"
    with pytest.raises(ChybaValidace, match="není platný"):
        prijem_vozidel.uloz(session, {"vin": "TMB123"})  # bez SPZ a s neplatným VIN příjem nevznikne
    assert prijem_vozidel.uloz(session, {"spz": "1AB2345", "vin": "TMBAA000000000009"}).stav == "vin_nesedi"
    jina_spz = prijem_vozidel.uloz(session, {"spz": "9JJ9999", "vin": "WVWZZZ00000000002"})
    assert jina_spz.stav == "spz_nesedi" and "2BB2222" in jina_spz.zprava  # VIN z databáze, ale jiná SPZ
    vozidla.vytvor(session, {"spz": "3CC3333", "vin": "WVWZZZ00000000003"})
    jen_vin = prijem_vozidel.uloz(session, {"vin": "WVWZZZ00000000003", "km": 3})  # jen VIN, bez SPZ
    assert jen_vin.stav == "hotovo" and not jen_vin.spojeno
    k = prijem_vozidel.uloz(session, {"spz": "1AB2345", "vin": "WVWZZZ00000000002"})
    assert k.spojeno and k.stav == "konflikt"
    assert a.id


def test_limit_30_a_smazani(session, registr):
    prvni = prijem_vozidel.uloz(session, {"spz": "9Z99999"})
    with pytest.raises(ChybaValidace):
        prijem_vozidel.uloz(session, {"spz": "1AB2345", "km": "-1"})
    with pytest.raises(ChybaValidace):
        prijem_vozidel.uloz(session, {"spz": "1AB2345", "fotky": ["x.jpg"]})  # fotky sem nepatří
    with pytest.raises(ChybaValidace):
        prijem_vozidel.uloz(session, {"spz": "1AB2345", "technicke": {}})  # registr hledá Autoservis sám
    for i in range(35):
        prijem_vozidel.uloz(session, {"spz": f"9Z{i:05d}"})
    zbylo = prijem_vozidel.nacti(session).navstevy
    assert len(zbylo) == prijem_vozidel.LIMIT == 30
    assert zbylo[0].spz == "9Z00034" and prvni.radek.id not in {n.id for n in zbylo}  # nejstarší pryč
    prijem_vozidel.smaz(session, zbylo[0].id)
    assert len(prijem_vozidel.nacti(session).navstevy) == 29


@pytest.fixture
def technik(session):
    api_klice.nastav_zapnuto(session, True)
    _, k = api_klice.vytvor(session, "Přijímací technik", ["prijem"])
    return k


def _volej(klic, nazev, **argumenty):
    token = server._hlavicka.set(f"Bearer {klic}")
    try:
        vysledek = asyncio.run(server.mcp.call_tool(nazev, argumenty))
    finally:
        server._hlavicka.reset(token)
    return json.loads(vysledek.content[0].text)


def test_mcp_prijem_a_zalozka(session, technik, registr):
    a = vozidla.vytvor(session, {"spz": "1AB2345", "vin": "TMBAA000000000001", "znacka": "Škoda"})
    assert _volej(technik, "hledej_vozidla", q="1AB2345")["vozidla"][0]["vin"] == "TMBAA000000000001"
    assert _volej(technik, "vozidlo_detail", vozidlo_id=a.id)["spz"] == "1AB2345"
    hotovo = _volej(technik, "uloz_prijem", data={"spz": "1AB2345", "km": 91262})
    assert hotovo["stav"] == "hotovo" and hotovo["vin_z_databaze"] and hotovo["dalsi_krok"]
    assert hotovo["prijem"]["v_databazi"] == {"stav": "v_databazi", "vozidlo_id": a.id, "upozorneni": None}
    chybi = _volej(technik, "uloz_prijem", data={"spz": "7X77777", "km": 5000})
    assert chybi["stav"] == "chybi_vin"
    nove = _volej(technik, "uloz_prijem", data={"id": chybi["prijem"]["id"], "vin": "TMBZZZ5JOA1234567"})
    assert nove["stav"] == "nove_auto" and nove["opravy_vin"] == ["O → 0 (pozice 9)"]
    assert nove["prijem"]["popis"] == "ŠKODA FABIA" and nove["prijem"]["km"] == 5000
    _volej(technik, "uloz_prijem", data={"spz": "8Y88888"})
    seznam = _volej(technik, "prijmy")
    assert seznam["celkem"] == 3 and seznam["limit"] == 30
    text = client.get("/prijem").text  # záložka ukáže příjmy jako dřív + stav u chybějícího VIN
    assert "1AB2345" in text and "7X77777" in text and "ŠKODA FABIA" in text and "91 262" in text.replace("\xa0", " ")
    assert "Chybí VIN" in _radek(text, seznam["prijmy"][0]["id"]) and "Chybí VIN" not in _radek(text, nove["prijem"]["id"])
    detail = client.get(f"/prijem/{seznam['prijmy'][0]['id']}").text
    assert "<dt>Stav</dt>" in detail and "Chybí VIN" in detail
    assert _volej(technik, "smaz_prijem", prijem_id=nove["prijem"]["id"]) == {"smazano": nove["prijem"]["id"]}
    assert _volej(technik, "prijmy")["celkem"] == 2
    assert "registr_vozidla" not in {t.name for t in asyncio.run(server.mcp.list_tools())}


def test_mcp_prijem_nesmi_zapisovat_vozidla_zakazniky_ani_zakazky(session, technik):
    a = vozidla.vytvor(session, {"spz": "1AB2345"})
    pocty = (len(session.exec(select(Vozidlo)).all()), len(session.exec(select(Zakaznik)).all()),
             len(session.exec(select(Zakazka)).all()))
    for nazev, argumenty in [("zaloz_vozidlo", {"data": {"spz": "5N55555"}}),
                             ("uprav_vozidlo", {"vozidlo_id": a.id, "data": {"barva": "modrá"}}),
                             ("hledej_zakazniky", {"q": "x"}),
                             ("zaloz_zakaznika", {"data": {"nazev": "TEST"}}),
                             ("prijem_zakazky", {"zakazka": {"pozadavek": "x"}, "vozidlo": {"spz": "5N55555"}}),
                             ("hledej_dily", {"q": "x"}), ("hledej_zakazky", {"q": "x"})]:
        with pytest.raises(ToolError, match="nemá oprávnění"):
            _volej(technik, nazev, **argumenty)
    session.expire_all()
    assert pocty == (len(session.exec(select(Vozidlo)).all()), len(session.exec(select(Zakaznik)).all()),
                     len(session.exec(select(Zakazka)).all()))
    _, sklad = api_klice.vytvor(session, "Skladník", ["sklad"])
    with pytest.raises(ToolError, match="Příjem vozidel"):
        _volej(sklad, "uloz_prijem", data={"spz": "1AB2345"})
