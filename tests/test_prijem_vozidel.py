"""#51 Příjem vozidel – čtení visits.json z OpenBotu (anonymizovaná data)."""
import json
import os
import re

import pytest

from app import config
from app.services import prijem_vozidel
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
    assert ">Příjem vozidel</a>" in text and 'class="striped klik-otevre"' in text
    km = [t.replace(" ", " ") for t in re.findall(r"12\d.\d00", text)]
    assert text.count("1AB2345") == 2 and km[:2] == ["120 500", "120 000"]  # dvě návštěvy stejného auta
    assert "ŠKODA OCTAVIA" in text and "Neuvedeno" in text  # chybějící VIN / km / značka
    assert "tajne" not in text and "/fotky/" not in text  # sources, events, fotky se nezobrazují


def test_detail_nejisty_vin_a_chybejici_hodnoty(soubor):
    soubor([_navsteva("x 1", "2026-11-19T09:30:00Z", nejiste=["vehicle.vin"]),
            _navsteva("x2", "2026-11-19T08:00:00Z", spz=None, vin=None, km=None, technicke={})])
    detail = client.get("/prijem/x%201").text
    assert "1AB2345" in detail and "TMBAA00000000001" in detail
    vin = detail.split("<dt>VIN</dt>")[1].split("</dd>")[0]
    assert 'class="nejiste"' in vin  # nejistý VIN je označený
    assert "TovarniZnacka" in detail and "Palivo" in detail and "tajne" not in detail
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
