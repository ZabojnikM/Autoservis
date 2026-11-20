"""Více katalogů materiálu (#62)."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlmodel import Session, create_engine

from app.db import init_db
from app.main import app
from app.models import TypPolozky
from app.services import ChybaValidace, cenik, import_lkq, katalogy, polozky, zakazky


def _zakazka(session, spz="1KT1111"):
    return zakazky.prijem(session, zakazka={"pozadavek": "x"}, vozidlo={"spz": spz})


def test_vychozi_katalog_a_stejny_kod_v_jinem_katalogu(session):
    hlavni = katalogy.vychozi(session)
    assert hlavni.nazev == "Hlavní katalog" and hlavni.nadpis == "Hlavní katalog"
    lkq = katalogy.vytvor(session, "LKQ")
    assert lkq.nadpis == "Katalog LKQ"

    a = cenik.vytvor(session, {"kod": "ABC 1", "nazev": "Filtr hlavní", "cena": "100"})
    b = cenik.vytvor(session, {"kod": "ABC 1", "nazev": "Filtr LKQ", "cena": "80", "katalog_id": lkq.id})
    assert (a.katalog_id, b.katalog_id) == (hlavni.id, lkq.id)
    with pytest.raises(ChybaValidace, match="v tomto katalogu"):
        cenik.vytvor(session, {"kod": "ABC 1", "nazev": "Duplicita", "cena": "1", "katalog_id": lkq.id})
    session.rollback()

    # seznam a hledání jen v příslušném katalogu
    assert [p.nazev for p in cenik.seznam(session, "abc", typ="material", katalog_id=lkq.id)] == ["Filtr LKQ"]
    assert [p.nazev for p in cenik.seznam(session, "abc", typ="material", katalog_id=hlavni.id)] == ["Filtr hlavní"]


def test_prace_patri_do_spolecneho_katalogu(session):
    lkq = katalogy.vytvor(session, "LKQ")
    prace = cenik.vytvor(session, {"nazev": "Výměna oleje", "typ": TypPolozky.PRACE, "cena": "500",
                                   "katalog_id": lkq.id})
    assert prace.katalog_id == katalogy.vychozi(session).id
    # okno Přidat z ceníku (oba typy) nabízí práce v každém katalogu
    assert [p.nazev for p in cenik.seznam(session, katalog_id=lkq.id)] == ["Výměna oleje"]


def test_zakazka_dva_radky_se_stejnym_kodem_a_zdrojem(session):
    lkq = katalogy.vytvor(session, "LKQ")
    a = cenik.vytvor(session, {"kod": "X1", "nazev": "Díl", "cena": "100"})
    b = cenik.vytvor(session, {"kod": "X1", "nazev": "Díl", "cena": "80", "katalog_id": lkq.id})
    z = _zakazka(session)
    radky = polozky.vloz_z_ceniku(session, z.id, [(a.id, "1"), (b.id, "1")])
    assert [(r.kod, r.cena, r.katalog.nazev) for r in radky] == [("X1", 100, "Hlavní katalog"), ("X1", 80, "LKQ")]
    # pozdější změna ceny v katalogu vložený řádek nezmění
    cenik.uprav(session, b.id, {"cena": "90"})
    session.refresh(radky[1])
    assert radky[1].cena == 80 and radky[1].katalog_id == lkq.id


def test_rucni_polozka_do_ceniku_vybraneho_katalogu(session):
    lkq = katalogy.vytvor(session, "LKQ")
    cenik.vytvor(session, {"kod": "R1", "nazev": "V hlavním", "cena": "1"})
    z = _zakazka(session)
    radek = polozky.pridej_rucne(session, z.id, {"typ": "material", "kod": "R1", "nazev": "Ruční", "cena": "5",
                                                 "mnozstvi": "1", "ulozit_do_ceniku": "1", "katalog_id": str(lkq.id)})
    assert radek.katalog_id == lkq.id and cenik.ziskej(session, radek.polozka_ceniku_id).katalog_id == lkq.id


def test_import_lkq_do_zvoleneho_katalogu(session):
    from tests.test_import_lkq import _list
    lkq = katalogy.vytvor(session, "LKQ")
    souhrn = import_lkq.importuj(session, _list(), [0], katalog_id=lkq.id)
    assert souhrn.zalozeno == 1
    dil = _list().dily[0]
    assert import_lkq.najdi_v_ceniku(session, dil.kod, lkq.id) is not None
    assert import_lkq.najdi_v_ceniku(session, dil.kod) is None  # výchozí katalog netknutý


def test_smazani_katalogu(session):
    lkq = katalogy.vytvor(session, "LKQ")
    with pytest.raises(ChybaValidace):
        katalogy.smaz(session, katalogy.vychozi(session).id)
    p = cenik.vytvor(session, {"nazev": "Díl", "cena": "1", "katalog_id": lkq.id})
    with pytest.raises(ChybaValidace, match="obsahuje díly"):
        katalogy.smaz(session, lkq.id)
    cenik.smaz(session, p.id)
    katalogy.smaz(session, lkq.id)
    assert [k.nazev for k in katalogy.seznam(session)] == ["Hlavní katalog"]
    with pytest.raises(ChybaValidace, match="už existuje"):
        katalogy.vytvor(session, "hlavní katalog")


def test_migrace_ze_stareho_schematu(tmp_path):
    """Databáze z doby jednoho ceníku: jedinečný index na kódu, bez katalogů."""
    eng = create_engine(f"sqlite:///{tmp_path / 'stara.db'}")
    with eng.begin() as c:
        c.execute(text("CREATE TABLE polozkaceniku (id INTEGER NOT NULL, kod VARCHAR, nazev VARCHAR NOT NULL,"
                       " typ VARCHAR NOT NULL, jednotka VARCHAR NOT NULL, cena VARCHAR NOT NULL,"
                       " sazba_dph VARCHAR NOT NULL, poznamka VARCHAR, aktivni BOOLEAN NOT NULL, PRIMARY KEY (id))"))
        c.execute(text("CREATE UNIQUE INDEX ix_polozkaceniku_kod ON polozkaceniku (kod)"))
        c.execute(text("INSERT INTO polozkaceniku VALUES (1, 'K1', 'Díl', 'material', 'ks', '10', '21', NULL, 1),"
                       " (2, 'P1', 'Práce', 'prace', 'hod', '500', '21', NULL, 1)"))
    init_db(eng)
    init_db(eng)  # podruhé nic nemění
    with eng.connect() as c:
        assert c.execute(text("SELECT id, nazev, vychozi FROM katalog")).all() == [(1, "Hlavní katalog", 1)]
        assert c.execute(text("SELECT katalog_id FROM polozkaceniku ORDER BY id")).scalars().all() == [1, 1]
        indexy = {r[1]: r[2] for r in c.execute(text("PRAGMA index_list(polozkaceniku)"))}
    assert indexy["ix_polozkaceniku_kod"] == 0 and indexy["ux_polozkaceniku_katalog_kod"] == 1
    with Session(eng) as s:
        lkq = katalogy.vytvor(s, "LKQ")
        cenik.vytvor(s, {"kod": "K1", "nazev": "Díl LKQ", "cena": "9", "katalog_id": lkq.id})
    eng.dispose()


def test_web_prepinac_a_formular(session):
    klient = TestClient(app)
    lkq = katalogy.vytvor(session, "LKQ")
    cenik.vytvor(session, {"kod": "W1", "nazev": "Díl hlavní", "cena": "1"})
    cenik.vytvor(session, {"kod": "W2", "nazev": "Díl z LKQ", "cena": "1", "katalog_id": lkq.id})

    r = klient.get("/cenik")
    assert "Díl hlavní" in r.text and "Díl z LKQ" not in r.text and "prepinac-katalogu" in r.text
    r = klient.get(f"/cenik?katalog={lkq.id}", follow_redirects=False)
    assert r.status_code == 303 and katalogy.KLIC_COOKIE in r.headers["set-cookie"]
    klient.cookies.set(katalogy.KLIC_COOKIE, str(lkq.id))
    r = klient.get("/cenik")
    assert "Díl z LKQ" in r.text and "Díl hlavní" not in r.text

    # #70: nový materiál vždy předvybere hlavní katalog, i když je naposledy prohlížený jiný
    hlavni = katalogy.vychozi(session)
    r = klient.get("/cenik/nova", params={"okno": "1"})
    assert f'<option value="{hlavni.id}" selected>' in r.text and f'<option value="{lkq.id}" >' in r.text

    z = _zakazka(session, "2KT2222")
    r = klient.get(f"/zakazky/{z.id}/cenik", params={"typ": "material", "okno": "1"})
    assert "Katalog LKQ" in r.text and "Díl z LKQ" in r.text and "Díl hlavní" not in r.text
    assert z.cislo not in r.text.split("</h1>")[0]


def test_novy_material_do_hlavniho_nebo_zvoleneho_katalogu(session):
    """#70: bez volby jde nový materiál do hlavního katalogu (ne do naposledy prohlíženého), volba platí."""
    klient = TestClient(app)
    lkq = katalogy.vytvor(session, "LKQ")
    hlavni = katalogy.vychozi(session)
    klient.cookies.set(katalogy.KLIC_COOKIE, str(lkq.id))
    klient.post("/cenik/nova", data={"nazev": "Bez volby", "cena": "1", "typ": "material"})
    klient.post("/cenik/nova", data={"nazev": "Do LKQ", "cena": "1", "typ": "material", "katalog_id": str(lkq.id)})
    assert [p.katalog_id for p in cenik.seznam(session, "Bez volby")] == [hlavni.id]
    assert [p.katalog_id for p in cenik.seznam(session, "Do LKQ")] == [lkq.id]

    z = _zakazka(session, "3KT3333")
    r = klient.get(f"/zakazky/{z.id}/polozky/nova", params={"typ": "material", "okno": "1"})
    assert f'<option value="{hlavni.id}" selected>' in r.text
    klient.post(f"/zakazky/{z.id}/polozky", data={"typ": "material", "nazev": "Ruční", "cena": "5", "mnozstvi": "1",
                                                   "ulozit_do_ceniku": "1"})
    assert [p.katalog_id for p in cenik.seznam(session, "Ruční")] == [hlavni.id]


def test_okno_ceniku_novy_a_prepinac(session):
    """#68: tlačítko Nový v okně Přidat z ceníku, předvyplněný kód; #69: přepínač katalogů si výběr pamatuje."""
    klient = TestClient(app)
    lkq = katalogy.vytvor(session, "LKQ")
    cenik.vytvor(session, {"kod": "P1", "nazev": "Díl z LKQ", "cena": "1", "katalog_id": lkq.id})
    z = _zakazka(session, "4KT4444")
    for typ in ("material", "prace"):
        r = klient.get(f"/zakazky/{z.id}/cenik", params={"typ": typ, "okno": "1"})
        assert f'/zakazky/{z.id}/polozky/nova?typ={typ}' in r.text
    r = klient.get(f"/zakazky/{z.id}/cenik", params={"typ": "material", "okno": "1"})
    assert 'data-s-hledanim="kod"' in r.text and "Z historie" in r.text and "Díl z LKQ" not in r.text
    r = klient.get(f"/zakazky/{z.id}/cenik", params={"typ": "material", "okno": "1", "katalog": str(lkq.id)})
    assert "Díl z LKQ" in r.text and katalogy.KLIC_COOKIE in r.headers["set-cookie"]
    r = klient.get(f"/zakazky/{z.id}/polozky/nova", params={"typ": "material", "okno": "1", "kod": "ABC 12"})
    assert 'name="kod" value="ABC 12"' in r.text


def test_material_z_historie_vozidla(session):
    """#69: materiál ze starších zakázek vozidla – jeden řádek na díl, cena aktuální z ceníku."""
    klient = TestClient(app)
    dil = cenik.vytvor(session, {"kod": "H1", "nazev": "Filtr", "cena": "100"})
    stara1, stara2 = _zakazka(session, "5KT5555"), _zakazka(session, "5KT5555")
    polozky.pridej_z_ceniku(session, stara1.id, dil.id, "1")
    polozky.pridej_z_ceniku(session, stara2.id, dil.id, "2")
    rucni = polozky.pridej_rucne(session, stara2.id, {"typ": "material", "nazev": "Těsnění", "cena": "30",
                                                       "mnozstvi": "1"})
    polozky.pridej_rucne(session, stara2.id, {"typ": "prace", "nazev": "Výměna", "cena": "500", "mnozstvi": "1"})
    cizi = _zakazka(session, "6KT6666")
    polozky.pridej_rucne(session, cizi.id, {"typ": "material", "nazev": "Cizí díl", "cena": "1", "mnozstvi": "1"})
    cenik.uprav(session, dil.id, {"cena": "120"})
    nova = _zakazka(session, "5KT5555")

    historie = polozky.historie_vozidla(session, nova)
    assert sorted((h.radek.nazev, h.pocet, h.cena) for h in historie) == [("Filtr", 2, 120), ("Těsnění", 1, 30)]
    assert [h.radek.nazev for h in polozky.historie_vozidla(session, nova, "těs")] == ["Těsnění"]

    r = klient.get(f"/zakazky/{nova.id}/cenik", params={"typ": "material", "okno": "1", "zdroj": "historie"})
    assert "Filtr" in r.text and "Těsnění" in r.text and "Cizí díl" not in r.text and "Výměna" not in r.text
    klient.post(f"/zakazky/{nova.id}/polozky", data={"z_historie": str(rucni.id), "mnozstvi": "3", "okno": "1"})
    filtr = next(h for h in historie if h.radek.nazev == "Filtr")
    klient.post(f"/zakazky/{nova.id}/polozky", data={"z_historie": str(filtr.radek.id), "mnozstvi": "1", "okno": "1"})
    session.refresh(nova)
    assert sorted((r.nazev, r.mnozstvi, r.cena, r.polozka_ceniku_id) for r in nova.polozky) ==         [("Filtr", 1, 120, dil.id), ("Těsnění", 3, 30, None)]
    # cizí vozidlo z historie vložit nejde
    with pytest.raises(ChybaValidace):
        polozky.pridej_z_historie(session, nova.id, cizi.polozky[0].id)

    bez = zakazky.prijem(session, zakazka={"pozadavek": "x"})
    r = klient.get(f"/zakazky/{bez.id}/cenik", params={"typ": "material", "okno": "1", "zdroj": "historie"})
    assert "nemá přiřazené vozidlo" in r.text
    r = klient.get("/cenik/vyber", params={"zakazka_id": cizi.id, "typ": "material", "zdroj": "historie"})
    assert "zatím nebyl" in r.text
