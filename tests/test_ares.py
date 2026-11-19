"""ARES – načtení firmy podle IČO (#11). Síť se v testech nevolá – _stahni je nahrazené."""
import pytest

from app.services import ChybaValidace, ares

MF = {"ico": "00006947", "obchodniJmeno": "Ministerstvo financí", "dic": "CZ00006947",
      "sidlo": {"nazevObce": "Praha", "nazevUlice": "Letenská", "cisloDomovni": 525, "cisloOrientacni": 15,
                "nazevCastiObce": "Malá Strana", "psc": 11800, "typCisloDomovni": 1}}


def test_ico_kontrola_a_normalizace():
    assert ares.normalizuj_ico(" 6947 ") == "00006947"
    assert ares.je_platne_ico("00006947") and ares.je_platne_ico("25596641")
    assert not ares.je_platne_ico("12345678")
    with pytest.raises(ChybaValidace, match="nesedí kontrolní"):
        ares.nacti("12345678")
    with pytest.raises(ChybaValidace, match="8 číslic"):
        ares.nacti("12a")


def test_pole_zakaznika_z_ares(monkeypatch):
    monkeypatch.setattr(ares, "_stahni", lambda ico: MF)
    pole = ares.na_pole_zakaznika(ares.nacti("6947"))
    assert pole == {"nazev": "Ministerstvo financí", "ulice": "Letenská 525/15", "psc": "11800", "mesto": "Praha",
                    "ico": "00006947", "dic": "CZ00006947"}
    # obec bez ulic: část obce + číslo popisné, bez DIČ
    vesnice = {"ico": "00275701", "obchodniJmeno": "Obec Provodov",
               "sidlo": {"nazevObce": "Provodov", "nazevCastiObce": "Provodov", "cisloDomovni": 48, "psc": 76345}}
    assert ares.na_pole_zakaznika(vesnice) == {"nazev": "Obec Provodov", "ulice": "Provodov 48", "psc": "76345",
                                                "mesto": "Provodov", "ico": "00275701"}


def test_web_ares(monkeypatch):
    from tests.test_web import client
    monkeypatch.setattr(ares, "_stahni", lambda ico: MF)
    r = client.get("/zakaznici/ares", params={"ico": "00006947"}).json()
    assert r["pole"]["nazev"] == "Ministerstvo financí" and r["pole"]["dic"] == "CZ00006947"
    assert "chyba" in client.get("/zakaznici/ares", params={"ico": "12345678"}).json()
    assert "nactiZAres(this, '')" in client.get("/zakaznici/novy").text
    assert "nactiZAres(this, 'k_')" in client.get("/zakazky/nova").text
