"""#94: datum jako obyčejné textové pole 20.11.2026 – bez kalendáře prohlížeče, se zkráceným zápisem."""
import re
from datetime import date, datetime

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import ChybaValidace, cti_datum
from app.services.zakazky import parsuj_datum, parsuj_datum_cas
from app.web.sablony import _datum_pole

client = TestClient(app)
DNES = date(2026, 11, 20)


@pytest.mark.parametrize("text", ["20.11.2026", "20. 11. 2026", "20.11.26", "20.11.", "20112026", "201126",
                                  "2026-11-20", " 20.11.2026 "])
def test_cti_datum_zkracene_zapisy(text):
    assert cti_datum(text, dnes=DNES) == DNES


@pytest.mark.parametrize("text", ["32.11.2026", "29.2.2026", "20/11/2026", "abc", "2011"])
def test_neplatne_datum_odmitne(text):
    with pytest.raises(ChybaValidace):
        parsuj_datum(text)


def test_datum_a_cas():
    assert parsuj_datum_cas("20.11.2026 14:30") == datetime(2026, 11, 20, 14, 30)
    assert parsuj_datum_cas("20.11.2026 8.05") == datetime(2026, 11, 20, 8, 5)
    assert parsuj_datum_cas("2026-11-20T14:30") == datetime(2026, 11, 20, 14, 30)
    assert parsuj_datum_cas("20.11.2026") == datetime(2026, 11, 20, 0, 0)
    with pytest.raises(ChybaValidace):
        parsuj_datum_cas("20.11.2026 25:00")


def test_hodnota_pole():
    assert _datum_pole(DNES) == "20.11.2026"
    assert _datum_pole("2026-11-20") == "20.11.2026"
    assert _datum_pole("2026-11-20T14:30", cas=True) == "20.11.2026 14:30"
    assert _datum_pole("20.11.") == "20.11."  # co uživatel napsal, zůstane (např. po chybě formuláře)
    assert _datum_pole(None) == ""


def test_formulare_nemaji_kalendar():
    for url in ["/zakazky/nova", "/vozidla/nove"]:
        html = client.get(url).text
        assert 'type="date"' not in html and 'type="datetime-local"' not in html, url
        assert 'class="vstup-datum' in html, url
    prijem = client.get("/zakazky/nova").text
    assert re.search(r'name="datum_prijeti" value="\d{2}\.\d{2}\.\d{4} \d{2}:\d{2}"', prijem)


def test_vozidlo_ulozi_datum_v_ceskem_tvaru(session):
    r = client.post("/vozidla/nove", data={"spz": "9DT0001", "zakaznik_id": "bez",
                                           "termin_stk": "24.3.27", "datum_registrace": "01052015"},
                    follow_redirects=True)
    assert r.status_code == 200
    assert "24.03.2027" in r.text and "01.05.2015" in r.text
    r = client.post("/vozidla/nove", data={"spz": "9DT0002", "zakaznik_id": "bez", "termin_stk": "31.2.2027"})
    assert "neplatné datum" in r.text
