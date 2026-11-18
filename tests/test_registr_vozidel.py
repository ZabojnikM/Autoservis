"""Napojení na Registr silničních vozidel (dataovozidlech.cz) – bez skutečného volání API."""
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import nastaveni, registr_vozidel
from app.services.registr_vozidel import ChybaRegistru

client = TestClient(app)

# příklad odpovědi z dokumentace API (RSV_Verejna_API_DK_v1_0.pdf), zkráceno
ODPOVED = {
    "Status": 1,
    "Data": {
        "DatumPrvniRegistrace": "1997-03-21T00:00:00",
        "DatumPrvniRegistraceVCr": "1997-03-21T00:00:00",
        "TovarniZnacka": "ŠKODA",
        "Typ": "ŠKODA FELICIA COMBI GLXI TMBEFF654 / EFF654",
        "Varianta": "GLXI",
        "Verze": "",
        "VIN": "TMBEFF654V7529422",
        "ObchodniOznaceni": "FELICIA COMBI",
        "MotorTyp": "781.136 M",
        "MotorMaxVykon": "50 / 5000",
        "Palivo": "BA 95 B",
        "MotorZdvihObjem": 1289,
        "VozidloElektricke": "NE",
        "VozidloKaroserieBarva": "ČERVENÁ-TMAVÁ",
        "PravidelnaTechnickaProhlidkaDo": "2013-12-06T00:00:00",
        "StatusNazev": "PROVOZOVANÉ",
        "PocetVlastniku": 1,
        "PocetProvozovatelu": 4,
    },
}


@pytest.fixture
def api(monkeypatch):
    """Podvržené API: zapamatuje si dotazy a vrátí `odpoved` (nebo vyhodí `chyba`)."""
    stav = {"odpoved": ODPOVED, "chyba": None, "dotazy": []}

    def _stahni(parametry, api_klic):
        stav["dotazy"].append((parametry, api_klic))
        if stav["chyba"]:
            raise stav["chyba"]
        return stav["odpoved"]

    monkeypatch.setattr(registr_vozidel, "_stahni", _stahni)
    return stav


def test_prevod_na_pole_vozidla():
    pole = registr_vozidel.na_pole_vozidla(ODPOVED["Data"])
    assert pole == {
        "vin": "TMBEFF654V7529422",
        "znacka": "Škoda",
        "model": "Felicia Combi",
        "datum_registrace": "1997-03-21",
        "rok_vyroby": "1997",
        "kod_motoru": "781.136 M",
        "objem": "1289",
        "vykon": "50 / 5000",
        "palivo": "benzín",
        "barva": "Červená-tmavá",
        "cislo_motoru": "GLXI",
        "termin_stk": "2013-12-06",
    }
    assert registr_vozidel.souhrn(ODPOVED["Data"]) == "stav: provozované, vlastníků: 1, provozovatelů: 4"


@pytest.mark.parametrize("vstup, vystup", [
    ("NM", "nafta"), ("NM D", "nafta"), ("BA 95 B", "benzín"), ("BA 95 B + LPG", "benzín + LPG"),
    ("ELEKTŘINA", "elektro"), ("VODÍK", "vodík"),
])
def test_palivo(vstup, vystup):
    assert registr_vozidel._palivo(vstup) == vystup


def test_objem_bez_desetinne_tecky():
    # skutečné API vrací objem jako 1289.0
    assert registr_vozidel.na_pole_vozidla({"MotorZdvihObjem": 1289.0})["objem"] == "1289"


def test_znacka_zkratky_zustanou_velkymi():
    assert registr_vozidel._znacka("BMW") == "BMW"
    assert registr_vozidel._znacka("MERCEDES-BENZ") == "Mercedes-benz"


def test_bez_klice_chyba(api):
    with pytest.raises(ChybaRegistru, match="Nastavení"):
        registr_vozidel.nacti("", vin="TMBEFF654V7529422")
    assert api["dotazy"] == []


def test_nenalezeno(api):
    api["odpoved"] = {"Status": 0, "Data": None}
    with pytest.raises(ChybaRegistru, match="nenalezeno"):
        registr_vozidel.nacti("klic", vin="X")


def test_vin_se_normalizuje(api):
    registr_vozidel.nacti(" klic ", vin=" tmbeff654 v7529422 ")
    assert api["dotazy"] == [({"vin": "TMBEFF654V7529422"}, "klic")]


def test_web_bez_klice(api):
    odpoved = client.get("/vozidla/registr", params={"vin": "TMBEFF654V7529422"})
    assert odpoved.status_code == 200
    assert "API klíč" in odpoved.json()["chyba"]


def test_web_s_klicem(api, session):
    nastaveni.uloz(session, {"api_klic_registr": "tajny-klic"})
    odpoved = client.get("/vozidla/registr", params={"vin": "TMBEFF654V7529422"}).json()
    assert odpoved["pole"]["znacka"] == "Škoda"
    assert odpoved["jen_prazdne"] == ["rok_vyroby"]
    assert api["dotazy"][0][1] == "tajny-klic"


def test_web_chyba_registru(api, session):
    nastaveni.uloz(session, {"api_klic_registr": "k"})
    api["chyba"] = ChybaRegistru("Registr vozidel neodpovídá – zkontrolujte připojení k internetu.")
    assert "neodpovídá" in client.get("/vozidla/registr", params={"vin": "X"}).json()["chyba"]


def test_formulare_maji_tlacitko_nacti(session):
    assert "nactiZRegistru(this, '')" in client.get("/vozidla/nove").text
    assert "nactiZRegistru(this, 'v_')" in client.get("/zakazky/nova").text
    assert 'name="api_klic_registr"' in client.get("/nastaveni").text
