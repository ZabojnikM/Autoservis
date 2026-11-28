"""#219 PIN pro vstup do Nastavení."""
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlmodel import select

from app.main import app
from app.models import UpravaDat
from app.nastroje import pin as pin_prikaz
from app.services import ChybaValidace, api_klice, pin

pytestmark = pytest.mark.pin


@pytest.fixture
def k():
    """Vlastní klient – cookie odemčení se nesmí přenést do jiných testů."""
    return TestClient(app)


def _odemkni(k, cislo="1234"):
    return k.post("/pin", data={"pin": cislo, "dalsi": "/nastaveni"}, follow_redirects=False)


def test_prvni_nastaveni_pinu(k, session):
    r = k.get("/nastaveni", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/pin?dalsi=/nastaveni"
    stranka = k.get("/zakazky").text
    assert 'href="/pin?dalsi=/nastaveni" data-okno' in stranka  # zamčené Nastavení otevře okno PINu
    okno = k.get("/pin", params={"okno": "1"}).text
    assert "Nastavte PIN" in okno and 'name="pin_novy"' in okno and 'hx-post="/pin"' in okno
    r = k.post("/pin", data={"pin_novy": "12a4", "pin_znovu": "12a4", "okno": "1"})
    assert "4 až 12 číslic" in r.text and not pin.nastaven(session)
    r = k.post("/pin", data={"pin_novy": "1234", "pin_znovu": "1235", "okno": "1"})
    assert "neshodují" in r.text
    r = k.post("/pin", data={"pin_novy": "1234", "pin_znovu": "1234", "okno": "1", "dalsi": "/nastaveni"})
    assert r.status_code == 204 and r.headers["HX-Redirect"] == "/nastaveni"
    assert "odemceno=" in r.headers["set-cookie"] and "HttpOnly" in r.headers["set-cookie"]
    assert "samesite=strict" in r.headers["set-cookie"].lower()
    session.expire_all()
    assert pin.nastaven(session) and "1234" not in pin._cti(session, pin.K_OTISK)  # jen otisk
    assert k.get("/nastaveni").status_code == 200
    assert 'href="/nastaveni"' in k.get("/zakazky").text  # odemčeno → rovnou do Nastavení


def test_chranene_adresy_a_volne_ostatni(k, session):
    pin.nastav(session, "1234", "1234")
    for adresa in ("/nastaveni", "/nastaveni/zalohy", "/nastaveni/aktualizace", "/nastaveni/api",
                   "/nastaveni/zalohy/stahnout/x.db"):
        r = k.get(adresa, follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"].startswith("/pin?dalsi="), adresa
    assert k.get("/nastaveni/zalohy", headers={"HX-Request": "true"}).headers["HX-Redirect"].startswith("/pin")
    r = k.post("/nastaveni/aktualizace/vratit", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/pin?dalsi=/nastaveni"  # akce se neprovede
    for adresa in ("/zakazky", "/vozidla", "/zakaznici", "/cenik", "/faktury", "/prijem", "/statistiky", "/sprava-dat"):
        assert k.get(adresa, follow_redirects=False).status_code in (200, 303, 404), adresa
        assert not k.get(adresa, follow_redirects=False).headers.get("location", "").startswith("/pin"), adresa
    assert k.get("/api/zdravi").status_code == 200


def test_odemceni_spatny_pin_a_zamknuti(k, session):
    pin.nastav(session, "1234", "1234")
    r = k.post("/pin", data={"pin": "9999", "okno": "1"})
    assert "PIN není správný" in r.text and r.status_code == 200
    r = _odemkni(k)
    assert r.status_code == 303 and r.headers["location"] == "/nastaveni"
    assert k.get("/nastaveni").status_code == 200
    r = k.post("/pin/zamknout", follow_redirects=False)
    assert r.status_code == 303 and 'odemceno=""' in r.headers["set-cookie"]
    assert k.get("/nastaveni", follow_redirects=False).status_code == 303


def test_presmerovani_jen_do_nastaveni(k, session):
    pin.nastav(session, "1234", "1234")
    r = k.post("/pin", data={"pin": "1234", "dalsi": "https://jinde.example/"}, follow_redirects=False)
    assert r.headers["location"] == "/nastaveni"
    r = k.post("/pin", data={"pin": "1234", "dalsi": "/nastaveni/zalohy"}, follow_redirects=False)
    assert r.headers["location"] == "/nastaveni/zalohy"


def test_platnost_30_minut_posuvne(session):
    pin.nastav(session, "1234", "1234")
    ted = datetime.now()
    t = pin.token(session, ted)
    assert pin.odemceno(session, t, ted + timedelta(minutes=29))
    assert not pin.odemceno(session, t, ted + timedelta(minutes=31))
    assert not pin.odemceno(session, t[:-1] + ("0" if t[-1] != "0" else "1"), ted)  # podvržený podpis
    assert not pin.odemceno(session, "nesmysl", ted)


def test_kazda_akce_v_nastaveni_prodlouzi_odemceni(k, session):
    pin.nastav(session, "1234", "1234")
    _odemkni(k)
    r = k.get("/nastaveni")
    assert r.status_code == 200 and "odemceno=" in r.headers.get("set-cookie", "")


def test_blokace_po_5_pokusech_a_denik(k, session):
    pin.nastav(session, "1234", "1234")
    for _ in range(pin.MAX_POKUSU):
        k.post("/pin", data={"pin": "0000", "okno": "1"})
    r = k.post("/pin", data={"pin": "1234", "okno": "1"})  # i správný PIN je teď zablokovaný
    assert "zablokované" in r.text and r.status_code == 200
    assert "zablokované do" in k.get("/pin", params={"okno": "1"}).text
    session.expire_all()
    popisy = [u.popis for u in session.exec(select(UpravaDat).where(UpravaDat.akce == "PIN"))]
    assert sum("Chybný PIN" in p for p in popisy) == pin.MAX_POKUSU - 1 and any("zablokované" in p for p in popisy)
    with pytest.raises(ChybaValidace):
        pin.over(session, "1234")
    assert pin.over(session, "1234", ted=datetime.now() + timedelta(minutes=6))  # po 5 minutách zase jde


def test_zmena_pinu(k, session):
    pin.nastav(session, "1234", "1234")
    _odemkni(k)
    r = k.post("/nastaveni/pin", data={"pin_stary": "0000", "pin_novy": "5678", "pin_znovu": "5678"},
               follow_redirects=False)
    assert r.headers["location"] == "/nastaveni#pin"
    assert pin.over(session, "1234")
    r = k.post("/nastaveni/pin", data={"pin_stary": "1234", "pin_novy": "5678", "pin_znovu": "5678"},
               follow_redirects=False)
    assert r.status_code == 303
    session.expire_all()
    assert pin.over(session, "5678") and not pin.over(session, "1234")
    assert k.get("/nastaveni").status_code == 200  # po změně zůstává odemčeno (nové odemčení)
    stary = TestClient(app)
    stary.cookies.set(pin.COOKIE, pin.token(session))
    assert stary.get("/nastaveni", follow_redirects=False).status_code == 200


def test_prikaz_zrusit_pin(session, monkeypatch, capsys):
    pin.nastav(session, "1234", "1234")
    monkeypatch.setattr(pin_prikaz, "init_db", lambda: None)
    monkeypatch.setattr(pin_prikaz, "Session", lambda _engine: session)
    assert pin_prikaz.main(["--zrusit"]) == 0
    assert "PIN zrušen" in capsys.readouterr().out
    session.expire_all()
    assert not pin.nastaven(session)
    assert pin_prikaz.main([]) == 1


def test_api_a_mcp_bez_pinu(session):
    pin.nastav(session, "1234", "1234")
    api_klice.nastav_zapnuto(session, True)
    _, klic = api_klice.vytvor(session, "TEST", ["vozidla"])
    r = TestClient(app).get("/api/v1/vozidla", headers={"Authorization": f"Bearer {klic}"})
    assert r.status_code == 200
