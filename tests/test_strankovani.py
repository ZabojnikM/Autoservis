"""Řazení a stránkování seznamů (datové mřížky)."""
import re

from fastapi.testclient import TestClient

from app.db import cesky_klic
from app.main import app
from app.services import cenik, vozidla, zakaznici
from app.services.strankovani import rozloz_razeni, strankuj_seznam

client = TestClient(app)


def test_rozloz_razeni():
    assert rozloz_razeni("-spz", {"spz": 1}, "spz") == ("spz", True)
    assert rozloz_razeni("spz", {"spz": 1}, "-spz") == ("spz", False)
    assert rozloz_razeni("nesmysl", {"spz": 1}, "-spz") == ("spz", True)
    assert rozloz_razeni(None, {"spz": 1}, "spz") == ("spz", False)


def test_strankuj_seznam_prazdne_hodnoty_na_konci():
    data = [{"x": 3}, {"x": None}, {"x": 1}, {"x": 2}]
    klice = {"x": lambda d: d["x"]}
    assert [d["x"] for d in strankuj_seznam(data, klice, "x", "x").polozky] == [1, 2, 3, None]
    assert [d["x"] for d in strankuj_seznam(data, klice, "-x", "x").polozky] == [3, 2, 1, None]
    st = strankuj_seznam(data, klice, "x", "x", od=2, limit=1)
    assert [d["x"] for d in st.polozky] == [3] and st.celkem == 4 and st.dalsi == 3
    assert strankuj_seznam(data, klice, "x", "x", od="abc").od == 0  # nesmyslný začátek = 0


def test_stranka_vozidel_v_davkach_a_razeni(session):
    for i in range(25):
        vozidla.vytvor(session, {"spz": f"1A{i:05d}", "znacka": "Škoda" if i % 2 else "Audi", "zakaznik_id": "bez"})
    st = vozidla.stranka(session, limit=10)
    assert st.celkem == 25 and len(st.polozky) == 10 and st.dalsi == 10 and st.razeni == "spz"
    assert st.polozky[0].spz == "1A00000"
    posledni = vozidla.stranka(session, od=20, limit=10)
    assert len(posledni.polozky) == 5 and posledni.dalsi is None
    sestupne = vozidla.stranka(session, razeni="-spz", limit=3)
    assert [v.spz for v in sestupne.polozky] == ["1A00024", "1A00023", "1A00022"]
    podle_znacky = vozidla.stranka(session, razeni="vozidlo", limit=30)
    assert podle_znacky.polozky[0].znacka == "Audi" and podle_znacky.polozky[-1].znacka == "Škoda"
    assert vozidla.stranka(session, hledat="1A0001", limit=100).celkem == 10  # 1A00010–1A00019


def test_ceske_razeni():
    jmena = ["Zeman", "Čermák", "Cibulka", "Chalupa", "Hruška", "Řezník", "Rybář", "adam", "Ábel", "Šimek", "Svoboda"]
    assert sorted(jmena, key=cesky_klic) == [
        "Ábel", "adam", "Cibulka", "Čermák", "Hruška", "Chalupa", "Rybář", "Řezník", "Svoboda", "Šimek", "Zeman"]


def test_stranka_zakazniku_a_ceniku(session):
    for nazev in ["Čermák", "adam", "Zeman", "Bílek", "Chalupa", "Hruška"]:
        zakaznici.vytvor(session, {"nazev": nazev})
    # česká abeceda v SQL (kolace „cs“): č za c, ch za h, bez ohledu na velikost písmen
    assert [z.nazev for z in zakaznici.stranka(session).polozky] == ["adam", "Bílek", "Čermák", "Hruška", "Chalupa", "Zeman"]
    for nazev, cena in [("Levný", "9"), ("Drahý", "100"), ("Střední", "20")]:
        cenik.vytvor(session, {"typ": "material", "nazev": nazev, "cena": cena})
    # cena je v DB text – řadit se musí jako číslo (9 < 20 < 100)
    assert [p.nazev for p in cenik.stranka(session, razeni="cena").polozky] == ["Levný", "Střední", "Drahý"]
    assert [p.nazev for p in cenik.stranka(session, razeni="-cena").polozky] == ["Drahý", "Střední", "Levný"]


def test_web_seznam_razeni_a_nacist_dalsi():
    for i in range(105):
        client.post("/zakaznici/novy", data={"nazev": f"Zákazník {i:03d}"})
    r = client.get("/zakaznici")
    assert r.status_code == 200 and 'id="seznam"' in r.text
    assert "Zobrazeno 100 z 105" in r.text and "Načíst další (5)" in r.text
    assert len(re.findall(r'<tr data-otevrit="/zakaznici/\d+"', r.text)) == 100
    # řaditelná hlavička: klik na aktivní sloupec otočí směr
    assert 'href="/zakaznici?razeni=-nazev"' in r.text and 'aria-sort="ascending"' in r.text
    r = client.get("/zakaznici", params={"razeni": "-nazev"})
    assert r.text.index("Zákazník 104") < r.text.index("Zákazník 103")
    # další dávka – jen zbývající řádky, stavový řádek bez tlačítka
    r = client.get("/zakaznici", params={"od": "100"})
    assert len(re.findall(r'<tr data-otevrit="/zakaznici/\d+"', r.text)) == 5
    assert "Zobrazeno 105 z 105" in r.text and "Načíst další" not in r.text
    r = client.get("/zakaznici", params={"vse_radky": "1"})
    assert "Zobrazeno 105 z 105" in r.text
    # hledání zachová řazení (skryté pole ve formuláři)
    r = client.get("/zakaznici", params={"razeni": "-nazev", "q": "10"})
    assert re.search(r'name="razeni" value="-nazev"\s*>', r.text) and "Zobrazeno" in r.text
    assert re.search(r'name="razeni" value=""\s+disabled', client.get("/zakaznici").text)


def test_web_vsechny_seznamy_s_razenim():
    for url in ["/zakazky?razeni=stav", "/zakazky?vse=1&razeni=-zakaznik", "/vozidla?razeni=-rok",
                "/cenik?razeni=cena", "/faktury?filtr=vse&razeni=zbyva", "/zakaznici?razeni=nesmysl&od=xyz"]:
        assert client.get(url).status_code == 200, url
