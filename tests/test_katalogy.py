"""Více katalogů materiálu (#62)."""
import re
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
    assert 'data-s-hledanim="kod"' in r.text and "Díl z LKQ" not in r.text
    assert "zdroj=historie" not in r.text   # #188: Z historie má vlastní okno, v okně ceníku už není
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


def test_historie_razeni_podle_poctu_a_presneho_kodu(session):
    """#115: Z historie – přesná shoda kódu nahoře, pak podle počtu použití na vozidle, při shodě novější výš."""
    from datetime import datetime, timedelta
    from app.models import PolozkaZakazky, Vozidlo, Zakazka
    v = Vozidlo(spz="9HR0115")
    session.add(v); session.flush()
    zakazky = []
    for i in range(3):
        z = Zakazka(cislo=f"T115-{i}", vozidlo_id=v.id, datum_prijeti=datetime(2026, 1, 1) + timedelta(days=i))
        session.add(z); session.flush(); zakazky.append(z)
    def radek(z, kod, nazev):
        session.add(PolozkaZakazky(zakazka_id=z.id, typ="material", kod=kod, nazev=nazev, mnozstvi="1", cena="10"))
    radek(zakazky[0], "OF 12", "Olejový filtr větší")
    radek(zakazky[1], "OF 12", "Olejový filtr větší")
    radek(zakazky[0], "SV 2", "Svíčka")
    radek(zakazky[1], "OF 1", "Olejový filtr")
    session.commit()
    nova = Zakazka(cislo="T115-N", vozidlo_id=v.id, datum_prijeti=datetime(2026, 2, 1))
    session.add(nova); session.commit()
    # OF 12 použit 2×; OF 1 a SV 2 po 1×, OF 1 novější
    assert [h.radek.kod for h in polozky.historie_vozidla(session, nova)] == ["OF 12", "OF 1", "SV 2"]
    # přesný kód nahoře i před častěji použitým dílem
    assert [h.radek.kod for h in polozky.historie_vozidla(session, nova, "of 1")] == ["OF 1", "OF 12"]


def test_uprava_materialu_volba_katalogu_a_presun(session):
    """#124: okno Upravit materiál má volbu katalogu (předvybraný současný); změna díl přesune,
    stejný kód v cílovém katalogu se odmítne."""
    klient = TestClient(app)
    lkq = katalogy.vytvor(session, "LKQ")
    hlavni = katalogy.vychozi(session)
    dil = cenik.vytvor(session, {"kod": "K124", "nazev": "Díl 124", "cena": "10"})
    cenik.vytvor(session, {"kod": "DUP124", "nazev": "Duplicita v LKQ", "cena": "10", "katalog_id": lkq.id})
    form = klient.get(f"/cenik/{dil.id}/upravit").text
    assert '<select name="katalog_id">' in form and ">Katalog" in form
    assert f'<option value="{hlavni.id}" selected>' in form
    r = klient.post(f"/cenik/{dil.id}/upravit", data={"typ": "material", "kod": "K124", "nazev": "Díl 124", "cena": "10",
                                                       "katalog_id": str(lkq.id), "aktivni": "1"})
    assert r.status_code in (200, 303), re.findall(r"class=\"chyba\"[^>]*>([^<]*)", r.text)
    session.expire_all()
    assert cenik.ziskej(session, dil.id).katalog_id == lkq.id
    r = klient.post(f"/cenik/{dil.id}/upravit", data={"typ": "material", "kod": "DUP124", "nazev": "Díl 124", "cena": "10",
                                                       "katalog_id": str(lkq.id), "aktivni": "1"})
    assert "už v tomto katalogu má položka" in r.text



def test_okno_z_historie_hromadne_vlozeni(session):
    """#188: tlačítko Z historie v zakázce, okno se zaškrtávátky, Vložit vloží všechno označené za aktuální ceny."""
    klient = TestClient(app)
    dil = cenik.vytvor(session, {"kod": "UFI 25.011.00", "nazev": "Olejový filtr", "cena": "150"})
    stara = _zakazka(session, "7KT7777")
    r_dil = polozky.pridej_z_ceniku(session, stara.id, dil.id, "1")
    r_rucni = polozky.pridej_rucne(session, stara.id, {"typ": "material", "kod": "X9", "nazev": "Těsnění",
                                                       "cena": "30", "mnozstvi": "1"})
    cenik.uprav(session, dil.id, {"cena": "199"})
    nova = _zakazka(session, "7KT7777")

    detail = klient.get(f"/zakazky/{nova.id}").text
    i_cenik, i_hist, i_novy = (detail.index(t) for t in (f"/zakazky/{nova.id}/cenik?typ=material",
                                                         f"/zakazky/{nova.id}/historie",
                                                         f"/zakazky/{nova.id}/polozky/nova?typ=material"))
    assert i_cenik < i_hist < i_novy   # mezi Ceník a Nový
    okno = klient.get(f"/zakazky/{nova.id}/historie", params={"okno": "1"}).text
    assert 'name="vybrano"' in okno and "vlozit-radek" not in okno and 'form="vlozit-historii"' in okno
    assert 'data-kopirovat="UFI 25.011.00"' in okno and "(mimo ceník)" in okno
    hledani = klient.get(f"/zakazky/{nova.id}/historie", params={"q": "těs", "vysledky": "1", "okno": "1"}).text
    assert "Těsnění" in hledani and "Olejový filtr" not in hledani and "<header" not in hledani

    # nic neoznačeno → chyba v okně, nic se nevloží
    r = klient.post(f"/zakazky/{nova.id}/historie/vlozit", data={"okno": "1"})
    assert "Zaškrtněte díly" in r.text
    r = klient.post(f"/zakazky/{nova.id}/historie/vlozit",
                    data={"okno": "1", "vybrano": [str(r_dil.id), str(r_rucni.id)],
                          f"mnozstvi_{r_dil.id}": "2", f"mnozstvi_{r_rucni.id}": "1"})
    assert r.status_code == 204
    session.refresh(nova)
    assert sorted((p.kod, p.mnozstvi, p.cena) for p in nova.polozky) == [("UFI 25.011.00", 2, 199), ("X9", 1, 30)]


def test_kopirovani_kodu_v_okne_ceniku(session):
    klient = TestClient(app)
    cenik.vytvor(session, {"kod": "BO 123", "nazev": "Svíčka", "cena": "80"})
    z = _zakazka(session, "8KT8888")
    r = klient.get(f"/zakazky/{z.id}/cenik", params={"typ": "material", "okno": "1"})
    assert 'data-kopirovat="BO 123"' in r.text


def test_vlozeni_z_historie_je_atomicke(session):
    dil = cenik.vytvor(session, {"kod": "A1", "nazev": "Díl", "cena": "10"})
    stara = _zakazka(session, "9KT9999")
    r1 = polozky.pridej_z_ceniku(session, stara.id, dil.id, "1")
    cizi = _zakazka(session, "9KT0000")
    r_cizi = polozky.pridej_z_ceniku(session, cizi.id, dil.id, "1")
    nova = _zakazka(session, "9KT9999")
    with pytest.raises(ChybaValidace):
        polozky.vloz_z_historie(session, nova.id, [(r1.id, "1"), (r_cizi.id, "1")])
    session.refresh(nova)
    assert nova.polozky == []
