"""API pro boty: klíče, sklad, zakázky, vozidla (#145, #146, #147)."""
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlmodel import select

from app.main import app
from app.models import PolozkaZakazky, StavZakazky, UpravaDat
from app.services import api_klice, cenik, polozky, zakazky, zalohy


@pytest.fixture
def klient(session, monkeypatch):
    monkeypatch.setattr(zalohy, "pred_sloucenim", lambda: Path("pred-sloucenim-test.db"))
    api_klice.nastav_zapnuto(session, True)
    return TestClient(app)


def _klic(session, *opravneni, nazev="Skladník"):
    _, klic = api_klice.vytvor(session, nazev, list(opravneni))
    return {"Authorization": f"Bearer {klic}"}


@pytest.fixture
def data(session):
    stary = cenik.vytvor(session, {"kod": "25.011.00", "nazev": "Olejový filtr", "cena": "177", "nakupni_cena": "90"})
    novy = cenik.vytvor(session, {"kod": "UFI 25.011.00", "nazev": "Olejový filtr UFI", "cena": "199"})
    z = zakazky.prijem(session, zakazka={"pozadavek": "servis"}, vozidlo={"spz": "1AB2345", "znacka": "Škoda"})
    r = polozky.pridej_z_ceniku(session, z.id, stary.id)
    rucni = polozky.pridej_rucne(session, z.id, {"typ": "material", "kod": "2501100", "nazev": "Filtr", "mnozstvi": "1",
                                                 "cena": "150"})
    return {"stary": stary, "novy": novy, "zakazka": z, "radek": r, "rucni": rucni}


def test_klice_a_opravneni(session, klient):
    assert klient.get("/api/v1/ja").status_code == 401
    assert klient.get("/api/v1/ja", headers={"Authorization": "Bearer spatny"}).status_code == 401
    h = _klic(session, "sklad")
    assert klient.get("/api/v1/ja", headers=h).json() == {"nazev": "Skladník", "opravneni": ["sklad"]}
    odpoved = klient.get("/api/v1/vozidla", headers=h)
    assert odpoved.status_code == 403 and "oprávnění" in odpoved.json()["chyba"]
    api_klice.nastav_zapnuto(session, False)
    assert klient.get("/api/v1/ja", headers=h).status_code == 403
    api_klice.nastav_zapnuto(session, True)
    zaznam = api_klice.seznam(session)[0]
    assert zaznam.naposledy is not None and zaznam.zacatek.startswith("as_")
    api_klice.zrus(session, zaznam.id)
    assert klient.get("/api/v1/ja", headers=h).status_code == 401
    with pytest.raises(Exception, match="oprávnění"):
        api_klice.vytvor(session, "X", ["neco"])


def test_sklad_cteni(session, klient, data):
    h = _klic(session, "sklad")
    dily = klient.get("/api/v1/sklad/dily", params={"q": "2501100"}, headers=h).json()
    assert dily["celkem"] == 2 and {d["kod"] for d in dily["dily"]} == {"25.011.00", "UFI 25.011.00"}
    regex = klient.get("/api/v1/sklad/dily", params={"kod_regex": r"^\d{2}\.\d{3}\.\d{2}$"}, headers=h).json()
    assert [d["kod"] for d in regex["dily"]] == ["25.011.00"]
    assert klient.get("/api/v1/sklad/dily", params={"kod_regex": "("}, headers=h).status_code == 422
    assert klient.get(f"/api/v1/sklad/dily/{data['stary'].id}", headers=h).json()["marze"] == "49.2"
    assert klient.get("/api/v1/sklad/dily/99999", headers=h).status_code == 404
    assert klient.get("/api/v1/sklad/duplicity", headers=h).json()["celkem"] == 1
    assert klient.get("/api/v1/sklad/sklady", headers=h).json()[0]["dilu"] == 2
    assert any(k["nazev"] == "Bez nákupní ceny" for k in klient.get("/api/v1/sklad/kontroly", headers=h).json())
    assert klient.get("/api/v1/sklad/prehledy", headers=h).json()["aktivnich_dilu"] == 2


def test_sklad_akce_nahled_a_provedeni(session, klient, data):
    h = _klic(session, "sklad")
    telo = {"akce": "kody", "filtr": {"kod_regex": r"^\d{2}\.\d{3}\.\d{2}$"},
            "parametry": {"operace": "vzor", "vzor": "UFI ##.###.##"}}
    nahled = klient.post("/api/v1/sklad/akce/nahled", json=telo, headers=h).json()
    assert nahled["zmeni_se"] == 0 and nahled["preskocene"][0]["duvod"].startswith("kód UFI 25.011.00 už ve skladu")
    # cena: bez otisku nebo se špatným otiskem nic
    telo = {"akce": "ceny", "ids": [data["stary"].id], "parametry": {"cil": "prodej", "hodnota": "10", "zaokrouhleni": "koruny"}}
    nahled = klient.post("/api/v1/sklad/akce/nahled", json=telo, headers=h).json()
    assert nahled["zmeny"][0]["nove"] == "195,00"
    assert klient.post("/api/v1/sklad/akce/provest", json=telo, headers=h).status_code == 422
    assert klient.post("/api/v1/sklad/akce/provest", json=telo | {"otisk": "x"}, headers=h).status_code == 422
    vysledek = klient.post("/api/v1/sklad/akce/provest", json=telo | {"ids": nahled["ids"], "otisk": nahled["otisk"]},
                           headers=h).json()
    assert vysledek["zmeneno"] == 1 and vysledek["zaloha"] == "pred-sloucenim-test.db"
    session.refresh(data["stary"])
    assert data["stary"].cena == Decimal("195")
    assert session.exec(select(UpravaDat)).one().akce == "API Skladník: Změna cen"


def test_sklad_slouceni(session, klient, data):
    h = _klic(session, "sklad")
    telo = {"ponechat_id": data["novy"].id, "ids": [data["stary"].id]}
    nahled = klient.post("/api/v1/sklad/sloucit/nahled", json=telo, headers=h).json()
    assert nahled["radku_zakazek_napojenych"] == 1 and nahled["vyradit"][0]["kod"] == "25.011.00"
    vysledek = klient.post("/api/v1/sklad/sloucit/provest", json=telo | {"otisk": nahled["otisk"]}, headers=h).json()
    assert vysledek["prepsano_radku"] == 1
    session.refresh(data["radek"])
    assert data["radek"].kod == "UFI 25.011.00" and data["radek"].cena == Decimal("177")


def test_zakazky_radky_v_uzavrene_zakazce(session, klient, data):
    h = _klic(session, "zakazky")
    zakazky.zmen_stav(session, data["zakazka"].id, StavZakazky.PREDANO, bez_dokladu=True)
    seznam = klient.get("/api/v1/zakazky", params={"q": "1AB2345"}, headers=h).json()
    assert seznam["pocet"] == 1 and seznam["zakazky"][0]["otevrena"] is False
    detail = klient.get(f"/api/v1/zakazky/{data['zakazka'].id}", headers=h).json()
    assert len(detail["polozky"]) == 2 and detail["celkem_bez_dph"] == "327.00"
    radky = klient.get("/api/v1/zakazky/radky", params={"kod": "25.011.00"}, headers=h).json()
    assert radky["celkem"] == 2   # 25.011.00 i 2501100 (bez oddělovačů)
    bez = klient.get("/api/v1/zakazky/radky", params={"bez_vazby": True}, headers=h).json()
    assert [r["kod"] for r in bez["radky"]] == ["2501100"]
    # napojit ruční řádek na kartu UFI (kód se převezme z karty) a zkusit změnit cenu
    telo = {"ids": [data["rucni"].id], "zmena": {"karta_ceniku_id": data["novy"].id, "cena_bez_dph": "1"}}
    nahled = klient.post("/api/v1/zakazky/radky/nahled", json=telo, headers=h).json()
    assert nahled["zmeni_se"] == 0 and "otevřené zakázce" in nahled["preskocene"][0]["duvod"]
    telo = {"ids": [data["rucni"].id], "zmena": {"karta_ceniku_id": data["novy"].id}}
    nahled = klient.post("/api/v1/zakazky/radky/nahled", json=telo, headers=h).json()
    assert nahled["zmeny"][0]["zmena"].startswith("kód 2501100 → UFI 25.011.00; napojit na kartu")
    assert klient.post("/api/v1/zakazky/radky/provest", json=telo | {"otisk": nahled["otisk"]}, headers=h).status_code == 200
    session.refresh(data["rucni"])
    assert (data["rucni"].kod, data["rucni"].polozka_ceniku_id, data["rucni"].cena) == \
        ("UFI 25.011.00", data["novy"].id, Decimal("150"))


def test_zakazky_pridat_dil(session, klient, data):
    h = _klic(session, "zakazky")
    odpoved = klient.post(f"/api/v1/zakazky/{data['zakazka'].id}/polozky",
                          json={"karta_ceniku_id": data["novy"].id, "mnozstvi": "2"}, headers=h)
    assert odpoved.status_code == 200 and odpoved.json()["mnozstvi"] == "2"
    zakazky.zmen_stav(session, data["zakazka"].id, StavZakazky.PREDANO, bez_dokladu=True)
    odpoved = klient.post(f"/api/v1/zakazky/{data['zakazka'].id}/polozky",
                          json={"karta_ceniku_id": data["novy"].id}, headers=h)
    assert odpoved.status_code == 422


def test_vozidla_zakaznici_prijem(session, klient, data):
    h = _klic(session, "vozidla", nazev="Přijímací technik")
    assert klient.get("/api/v1/vozidla", params={"q": "1AB"}, headers=h).json()["vozidla"][0]["spz"] == "1AB2345"
    vuz = klient.post("/api/v1/vozidla", json={"spz": "2ab 3456", "znacka": "Ford", "vin": "WF0XXXGCDX1234567"},
                      headers=h).json()
    assert vuz["spz"] == "2AB3456"
    assert klient.post("/api/v1/vozidla", json={"spz": "2AB3456"}, headers=h).status_code == 422   # duplicita
    assert klient.post("/api/v1/vozidla", json={"spz": "X", "barva_auta": "modrá"}, headers=h).status_code == 422
    assert klient.patch(f"/api/v1/vozidla/{vuz['id']}", json={"model": "Focus"}, headers=h).json()["popis"] == "Ford Focus"
    zak = klient.post("/api/v1/zakaznici", json={"nazev": "Jan Test", "telefon": "777 000 000"}, headers=h).json()
    assert klient.get("/api/v1/zakaznici", params={"q": "Jan"}, headers=h).json()["pocet"] == 1
    prijem = klient.post("/api/v1/prijem", json={"zakazka": {"pozadavek": "výměna oleje", "tachometr": "120000"},
                                                "vozidlo": {"spz": "2AB3456"}, "zakaznik": {"id": zak["id"]}}, headers=h).json()
    assert prijem["spz"] == "2AB3456" and prijem["zakaznik"] == "Jan Test" and prijem["otevrena"] is True
    detail = klient.get(f"/api/v1/vozidla/{vuz['id']}", headers=h).json()
    assert detail["zakaznik"] == "Jan Test" and detail["zakazky"][0]["pozadavek"] == "výměna oleje"
    assert len(klient.get(f"/api/v1/zakaznici/{zak['id']}", headers=h).json()["vozidla"]) == 1
    nove = klient.post("/api/v1/prijem", json={"zakazka": {"pozadavek": "STK"}, "vozidlo": {"spz": "3AB0001"},
                                              "zakaznik": {"nazev": "Nová Firma"}}, headers=h).json()
    assert nove["zakaznik"] == "Nová Firma" and nove["spz"] == "3AB0001"


def test_nastaveni_api_stranka(session):
    klient = TestClient(app)
    assert "API pro boty" in klient.get("/nastaveni").text
    klient.post("/nastaveni/api/zapnout", data={"zapnuto": "1"})
    assert api_klice.zapnuto(session)
    odpoved = klient.post("/nastaveni/api/klice", data={"nazev": "Skladník", "opravneni": ["sklad", "zakazky"]})
    assert "Zkopírujte si ho teď" in odpoved.text
    import re
    klic = re.search(r'value="(as_[^"]+)"', odpoved.text).group(1)
    assert klient.get("/api/v1/ja", headers={"Authorization": f"Bearer {klic}"}).json()["opravneni"] == ["sklad", "zakazky"]
    assert klic not in klient.get("/nastaveni/api").text   # podruhé se už neukáže


def test_api_dily_kod_vzor(session, klient, data):
    """#151: vzor kódu se zástupnými znaky i v API."""
    h = _klic(session, "sklad")
    r = klient.get("/api/v1/sklad/dily", params={"kod_vzor": "UFI ##.###.##"}, headers=h).json()
    assert [d["kod"] for d in r["dily"]] == ["UFI 25.011.00"]
    r = klient.get("/api/v1/sklad/dily", params={"kod_vzor": "##.###.##"}, headers=h).json()
    assert [d["kod"] for d in r["dily"]] == ["25.011.00"]
