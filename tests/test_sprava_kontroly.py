"""Správa dat – kontroly ceníku (#141) a přehledy (#143)."""
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import cenik, kontroly, nastaveni, polozky, zakazky, zalohy


@pytest.fixture
def data(session):
    a = cenik.vytvor(session, {"kod": "UFI 1.0", "nazev": "Filtr", "cena": "100", "nakupni_cena": "80"})
    b = cenik.vytvor(session, {"kod": "BO 2", "nazev": "Svíčka", "cena": "50", "nakupni_cena": "60"})
    cenik.vytvor(session, {"kod": "ufi 3", "nazev": "Nula", "cena": "0"})
    z = zakazky.prijem(session, zakazka={"pozadavek": "x"}, vozidlo={"spz": "1KT1111"})
    polozky.pridej_z_ceniku(session, z.id, a.id)
    rucni = polozky.pridej_rucne(session, z.id, {"typ": "material", "kod": "BO 2", "nazev": "Svíčka ručně",
                                                 "mnozstvi": "1", "cena": "45"})
    polozky.pridej_rucne(session, z.id, {"typ": "material", "kod": "NIKDE", "nazev": "Neznámý", "mnozstvi": "1", "cena": "1"})
    return {"a": a, "b": b, "rucni": rucni}


def test_prehled_kontrol(session, data):
    pocty = {k.nazev: k.pocet for k in kontroly.prehled_kontrol(session)}
    assert pocty["Prodej pod nákupní cenou"] == 1 and pocty["Nulová prodejní cena"] == 1
    assert pocty["Podezřelý zápis kódu"] == 1 and pocty["Bez nákupní ceny"] == 1
    assert pocty["Řádky zakázek bez vazby na ceník"] == 2


def test_napojeni_radku_bez_vazby(session, data):
    skupiny = {s.kod: s for s in kontroly.bez_vazby(session)}
    assert skupiny["BO 2"].karta.id == data["b"].id and skupiny["NIKDE"].karta is None
    assert kontroly.napoj(session, ["BO 2", "NIKDE"]) == 1
    session.refresh(data["rucni"])
    assert data["rucni"].polozka_ceniku_id == data["b"].id and data["rucni"].cena == Decimal("45")


def test_prehledy(session, data):
    p = kontroly.prehledy(session, dnes=date.today())
    assert [r.karta.kod for r in p["nejpouzivanejsi"]] == ["UFI 1.0"]
    assert p["nikdy"] == 2
    vyrobci = {s.nazev: s for s in p["podle_vyrobce"]}
    assert vyrobci["BO"].pod_nakupem == 1 and vyrobci["UFI"].prumer == Decimal("20.0")


def test_web_kontroly_a_prehledy(session, data, monkeypatch):
    nastaveni.uloz(session, {"sprava_dat": "1"})
    monkeypatch.setattr(zalohy, "pred_sloucenim", lambda: Path("pred-sloucenim-test.db"))
    klient = TestClient(app)
    assert "Prodej pod nákupní cenou" in klient.get("/sprava-dat/kontroly").text
    assert "Napojit zaškrtnuté" in klient.get("/sprava-dat/kontroly/bez-vazby").text
    assert klient.post("/sprava-dat/kontroly/bez-vazby", data={"kod": "BO 2"}, follow_redirects=False).status_code == 303
    session.refresh(data["rucni"])
    assert data["rucni"].polozka_ceniku_id == data["b"].id
    prehledy = klient.get("/sprava-dat/prehledy")
    assert prehledy.status_code == 200 and "Marže podle výrobce" in prehledy.text
    rozcestnik = klient.get("/sprava-dat").text
    for adresa in ("/sprava-dat/dily", "/sprava-dat/sklady", "/sprava-dat/kontroly", "/sprava-dat/prehledy", "/sprava-dat/denik"):
        assert f'href="{adresa}"' in rozcestnik
