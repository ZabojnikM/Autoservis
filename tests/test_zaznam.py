"""#225 Záznam událostí: soubor s rotací, události, bez osobních údajů, stránka v Nastavení."""
import asyncio
import logging

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from app import zaznam
from app.main import app
from app.mcp_server import server
from app.services import api_klice, registr_vozidel, zakazky, zalohy
from app.zaznam import log


@pytest.fixture
def soubor(tmp_path):
    cil = zaznam.nastav(tmp_path / "logs" / "autoservis.log")
    yield cil
    zaznam.ukonci()


def _text(soubor):
    for h in log.handlers:
        h.flush()
    return soubor.read_text(encoding="utf-8")


def test_neosetrena_chyba_webu_s_vypisem(soubor, monkeypatch):
    def rozbite(*a, **k):
        raise RuntimeError("testovací porucha")
    monkeypatch.setattr(zakazky, "stranka", rozbite)
    r = TestClient(app, raise_server_exceptions=False).get("/zakazky?q=Novák")
    assert r.status_code == 500
    text = _text(soubor)
    assert "ERROR" in text and "Neošetřená chyba: GET /zakazky" in text and "RuntimeError: testovací porucha" in text
    assert "Novák" not in text  # parametry adresy se nezapisují


def test_parametry_sql_se_nezapisuji(soubor):
    hodnoty = tuple(["TEST " + "Tajný", "777" + "123456"])  # ve výpisu kódu se hodnoty neobjeví
    try:
        raise IntegrityError("INSERT INTO zakaznik (nazev, telefon) VALUES (?, ?)", hodnoty, Exception("x"))
    except IntegrityError:
        log.exception("Neošetřená chyba: POST /zakaznici/novy")
    text = _text(soubor)
    assert "INSERT INTO zakaznik" in text and "TEST Tajný" not in text and "777123456" not in text
    assert "[parameters: vynecháno]" in text


def test_api_a_mcp_jen_klic_a_nastroj(soubor, session):
    api_klice.nastav_zapnuto(session, True)
    _, klic = api_klice.vytvor(session, "TEST bot", ["vozidla"])
    TestClient(app).get("/api/v1/vozidla", params={"q": "1AB2345"}, headers={"Authorization": f"Bearer {klic}"})
    TestClient(app).get("/api/v1/vozidla")
    token = server._hlavicka.set(f"Bearer {klic}")
    try:
        asyncio.run(server.mcp.call_tool("hledej_vozidla", {"q": "1AB2345"}))
        with pytest.raises(Exception):
            asyncio.run(server.mcp.call_tool("hledej_dily", {"q": "x"}))  # klíč nemá oprávnění sklad
    finally:
        server._hlavicka.reset(token)
    text = _text(soubor)
    assert "API TEST bot: GET /api/v1/vozidla → 200" in text
    assert "API bez platného klíče: GET /api/v1/vozidla → 401" in text
    assert "MCP TEST bot: hledej_vozidla" in text and "hledej_dily – přístup odmítnut" in text
    assert "1AB2345" not in text


def test_zalohy_planovac_registr_a_pin(soubor, session, tmp_path, monkeypatch):
    zalohy._uloz_stav(tmp_path / "z", "tydenni", chyba="Složka /mnt/x není dostupná")
    zalohy._uloz_stav(tmp_path / "z", "denni", soubor="denni-autoservis-1.db", chyba="", uspech="2026-11-28T10:00:00")
    zalohy._stop.clear()
    def spadni(_):
        zalohy._stop.set()
        raise OSError("disk")
    monkeypatch.setattr(zalohy, "naplanovane", spadni)
    zalohy._smycka(lambda: "", 0)
    def odmitni(parametry, klic):
        raise registr_vozidel.ChybaRegistru("Registr vozidel neodpovídá – zkontrolujte připojení k internetu.")
    monkeypatch.setattr(registr_vozidel, "_stahni", odmitni)
    with pytest.raises(registr_vozidel.ChybaRegistru):
        registr_vozidel.nacti("klic", vin="TMBZZZ5J0A1234567")
    from app.services import pin
    pin.nastav(session, "1234", "1234")
    pin.over(session, "0000")
    text = _text(soubor)
    assert "Záloha (tydenni) selhala: Složka /mnt/x není dostupná" in text
    assert "Záloha (denni) v pořádku: denni-autoservis-1.db" in text
    assert "Plánovač záloh: neočekávaná chyba" in text and "OSError: disk" in text
    assert "Registr vozidel: Registr vozidel neodpovídá" in text and "TMBZZZ5J0A1234567" not in text
    assert "PIN: chybný pokus 1 z 5" in text and "0000" not in text and "1234" not in text


def test_rotace_souboru(tmp_path, monkeypatch):
    monkeypatch.setattr(zaznam, "VELIKOST", 2000)
    cil = zaznam.nastav(tmp_path / "logs" / "autoservis.log")
    try:
        for i in range(500):
            log.info("Událost číslo %s s trochou textu navíc, ať soubor roste", i)
    finally:
        zaznam.ukonci()
    soubory = sorted(cil.parent.iterdir())
    assert len(soubory) == zaznam.SOUBORU and all(s.stat().st_size <= 2200 for s in soubory)


def test_stranka_v_nastaveni_filtr_a_stazeni(soubor):
    log.info("Start Autoservis TEST")
    log.warning("Záloha (tydenni) selhala: test")
    k = TestClient(app)
    text = k.get("/nastaveni/zaznam").text
    assert "Záznam událostí" in text and "Start Autoservis TEST" in text and "selhala: test" in text
    assert text.index("selhala: test") < text.index("Start Autoservis TEST")  # nejnovější nahoře
    chyby = k.get("/nastaveni/zaznam", params={"jen_chyby": "1"}).text
    assert "selhala: test" in chyby and "Start Autoservis TEST" not in chyby
    r = k.get("/nastaveni/zaznam/stahnout")
    assert r.status_code == 200 and "Start Autoservis TEST" in r.text
    assert 'href="/nastaveni/zaznam"' in k.get("/nastaveni").text


@pytest.mark.pin
def test_zaznam_je_pod_pinem(soubor):
    r = TestClient(app).get("/nastaveni/zaznam/stahnout", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/pin")
    logging.getLogger("autoservis").info("konec")
