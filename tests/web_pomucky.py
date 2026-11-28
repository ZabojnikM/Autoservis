"""Společné pomůcky testů webu: klient, fixtury a pomocné funkce (rozděleno z test_web.py, #233)."""
import pytest
from fastapi.testclient import TestClient
from app.services import nastaveni
from app.main import app

client = TestClient(app)


def _se_skriptem(stranka: str) -> str:
    """Stránka + JavaScript aplikace (#233: skript je v /static/app.js, ne v base.html)."""
    assert '<script src="/static/app.js?v=' in stranka
    return stranka + client.get("/static/app.js").text


@pytest.fixture(autouse=True)
def ucet_pro_vyuctovani(session):
    """#55: vyúčtování bez účtu pro QR platbu vystavit nejde – v testech je účet nastavený předem."""
    nastaveni.uloz(session, {"ucet_vyuctovani": "2001234567/2010"})


def _prijem(spz="1AB2345", **navic):
    data = {
        "spz": spz, "v_znacka": "Škoda", "v_model": "Fabia",
        "zakaznik_vyber": "", "k_nazev": "Jana Dvořáková", "k_telefon": "603 000 000",
        "pozadavek": "Nejde startovat", "tachometr": "98000", "stav_paliva": "1/4",
    }
    data.update(navic)
    return client.post("/zakazky/nova", data=data, follow_redirects=False)


def _zakazka_s_polozkou(**navic):
    loc = _prijem(**navic).headers["location"].split("?")[0]
    client.post(f"{loc}/polozky", data={"typ": "prace", "nazev": "Diagnostika", "mnozstvi": "1", "cena": "1000"})
    return loc


# ---------------------------------------------------------------- ostatní formuláře jako okna

def _je_okno(r, akce):
    """Odpověď je jen obsah okna (bez celé stránky) s HTMX odesláním a tlačítkem Zrušit."""
    assert r.status_code == 200, r.text[:300]
    assert "<html" not in r.text and f'hx-post="{akce}"' in r.text and "data-zavrit-okno" in r.text
