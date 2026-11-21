"""MCP server Autoservisu (#148): nástroje nad API, klíč a oprávnění, volání přes HTTP."""
import asyncio
import json
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from mcp.server.mcpserver.exceptions import ToolError

import app.main as hlavni
from app.mcp_server import server
from app.services import api_klice, cenik, polozky, zakazky, zalohy


@pytest.fixture
def klic(session, monkeypatch):
    monkeypatch.setattr(zalohy, "pred_sloucenim", lambda: Path("pred-sloucenim-test.db"))
    api_klice.nastav_zapnuto(session, True)
    _, k = api_klice.vytvor(session, "Skladník", ["sklad", "zakazky"])
    return k


def _volej(klic, nazev, **argumenty):
    token = server._hlavicka.set(f"Bearer {klic}")
    try:
        vysledek = asyncio.run(server.mcp.call_tool(nazev, argumenty))
    finally:
        server._hlavicka.reset(token)
    return json.loads(vysledek.content[0].text)


@pytest.fixture
def dily(session):
    a = cenik.vytvor(session, {"kod": "25.011.00", "nazev": "Olejový filtr", "cena": "177"})
    b = cenik.vytvor(session, {"kod": "2502300", "nazev": "Olejový filtr", "cena": "198"})
    z = zakazky.prijem(session, zakazka={"pozadavek": "x"}, vozidlo={"spz": "1AB2345"})
    r = polozky.pridej_z_ceniku(session, z.id, a.id)
    return a, b, r


def test_nastroje_a_pokyny():
    nazvy = {t.name for t in asyncio.run(server.mcp.list_tools())}
    assert {"hledej_dily", "nahled_hromadne_akce", "proved_hromadnou_akci", "hledej_radky_zakazek",
            "nahled_upravy_radku", "prijem_zakazky", "hledej_vozidla"} <= nazvy
    assert "náhled" in server.POKYNY


def test_sjednoceni_ufi_pres_mcp(session, klic, dily):
    a, b, r = dily
    assert _volej(klic, "kdo_jsem") == {"nazev": "Skladník", "opravneni": ["sklad", "zakazky"]}
    nalez = _volej(klic, "hledej_dily", q="filtr", kod_regex=r"^\d")
    assert nalez["celkem"] == 2
    nahled = _volej(klic, "nahled_hromadne_akce", akce="kody", ids=[a.id, b.id],
                    parametry={"operace": "vzor", "vzor": "UFI ##.###.##"})
    assert [z["nove"] for z in nahled["zmeny"]] == ["UFI 25.011.00", "UFI 25.023.00"]
    vysledek = _volej(klic, "proved_hromadnou_akci", akce="kody", ids=nahled["ids"], parametry=nahled["parametry"],
                      otisk=nahled["otisk"])
    assert vysledek["zmeneno"] == 2
    session.refresh(r)
    assert r.kod == "UFI 25.011.00" and r.cena == Decimal("177")


def test_chyby_jako_toolerror(session, klic, dily):
    with pytest.raises(ToolError, match="oprávnění"):
        _volej(klic, "hledej_vozidla", q="1AB")
    with pytest.raises(ToolError, match="otisk"):
        _volej(klic, "proved_hromadnou_akci", akce="vyradit", ids=[dily[0].id], parametry={}, otisk="")
    with pytest.raises(ToolError, match="Chybí klíč"):
        asyncio.run(server.mcp.call_tool("kdo_jsem", {}))


def test_radky_zakazek_pres_mcp(session, klic, dily):
    a, b, r = dily
    radky = _volej(klic, "hledej_radky_zakazek", kod="2501100")
    assert [x["id"] for x in radky["radky"]] == [r.id]
    nahled = _volej(klic, "nahled_upravy_radku", ids=[r.id], zmena={"kod": "UFI 25.011.00"})
    _volej(klic, "proved_upravu_radku", ids=[r.id], zmena={"kod": "UFI 25.011.00"}, otisk=nahled["otisk"])
    session.refresh(r)
    assert r.kod == "UFI 25.011.00"


def test_mcp_pres_http(session, klic, dily, monkeypatch):
    """Celá cesta jako z OpenBotu: POST /mcp/ s klíčem v hlavičce (stateless, JSON odpovědi)."""
    monkeypatch.setattr(hlavni, "init_db", lambda: None)   # lifespan nesmí sahat na skutečnou databázi
    h = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json",
         "Authorization": f"Bearer {klic}", "mcp-protocol-version": "2025-06-18"}
    with TestClient(hlavni.app) as klient:
        init = klient.post("/mcp/", headers=h, json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "test", "version": "1"}}})
        assert init.status_code == 200 and init.json()["result"]["serverInfo"]["name"] == "Autoservis"
        volani = klient.post("/mcp/", headers=h, json={"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                                                       "params": {"name": "hledej_dily", "arguments": {"q": "2502300"}}})
        vysledek = volani.json()["result"]
        assert not vysledek["isError"] and json.loads(vysledek["content"][0]["text"])["celkem"] == 1
        bez_klice = klient.post("/mcp/", headers={k: v for k, v in h.items() if k != "Authorization"},
                                json={"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                                      "params": {"name": "kdo_jsem", "arguments": {}}})
        assert bez_klice.json()["result"]["isError"]
