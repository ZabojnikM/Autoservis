"""Správa dat: import do (nového) skladu s napárováním starých karet (#134)."""
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlmodel import select

from app.main import app
from app.models import Katalog, PolozkaCeniku
from app.services import ChybaValidace, cenik, import_skladu, katalogy, nastaveni, polozky, zakazky, zalohy

SEZNAM = ("Kód;Název;Nákup bez DPH;Prodej bez DPH\n"
          "UFI 25.011.00;Olejový filtr UFI;95,50;199,00\n"
          "UFI 30.779.00;Vzduchový filtr UFI;250;449\n"
          "UFI 99.999.00;Bez prodejní ceny;10;\n")


def _zakazka(session):
    return zakazky.prijem(session, zakazka={"pozadavek": "x"}, vozidlo={"spz": "1KT1111"})


@pytest.fixture
def stare(session):
    a = cenik.vytvor(session, {"kod": "2501100", "nazev": "Olejový filtr", "cena": "161,16"})
    b = cenik.vytvor(session, {"kod": "25.011.00", "nazev": "Olejový filtr", "cena": "177"})
    z = _zakazka(session)
    ra = polozky.pridej_z_ceniku(session, z.id, a.id)
    rb = polozky.pridej_z_ceniku(session, z.id, b.id)
    return a, b, ra, rb


def test_nacte_tabulku_s_ceskym_zahlavim():
    radky = import_skladu.nacti(SEZNAM.encode("cp1250"))
    assert [(r.kod, r.cena, r.nakup) for r in radky] == [
        ("UFI 25.011.00", Decimal("199.00"), Decimal("95.50")), ("UFI 30.779.00", Decimal("449"), Decimal("250")),
        ("UFI 99.999.00", None, Decimal("10"))]
    carky = import_skladu.nacti(b"kod,nazev,cena\nUFI 1.2.3,Filtr,10\n")
    assert [(r.kod, r.cena, r.nakup) for r in carky] == [("UFI 1.2.3", Decimal("10"), None)]
    with pytest.raises(ChybaValidace, match="Kód, Název a Prodej"):
        import_skladu.nacti(b"neco;jineho\n1;2\n")


def test_nacte_dodaci_list_lkq():
    dodaci = ("Dodaci list;123\nCislo;Kod;Nazev;Mnozstvi;Cena/ks;MOC bez DPH/ks;DPH (%)\n"
              "1;UFI 25.011.00;Olejovy filtr;1;95.5;199;21\nSazba DPH 21\n")
    radky = import_skladu.nacti(dodaci.encode())
    assert [(r.kod, r.cena, r.nakup) for r in radky] == [("UFI 25.011.00", Decimal("199"), Decimal("95.5"))]


def test_navrh_najde_stare_karty_podle_cisla(session, stare):
    a, b, *_ = stare
    navrh = import_skladu.navrh(session, import_skladu.nacti(SEZNAM.encode()), None)
    prvni = navrh[0]
    assert prvni.kod == "UFI 25.011.00" and {s["id"] for s in prvni.stare} == {a.id, b.id}
    bez_shody = next(r for r in navrh if r.kod == "UFI 30.779.00")
    assert bez_shody.stare == [] and not bez_shody.chyba
    assert navrh[-1].chyba.startswith("Chybí prodejní cena")


def test_import_do_noveho_skladu_slouci_stare_karty(session, stare):
    a, b, ra, rb = stare
    novy = katalogy.vytvor(session, "Nový sklad")
    navrh = import_skladu.navrh(session, import_skladu.nacti(SEZNAM.encode()), novy.id)
    radky = [r for r in navrh if not r.chyba]
    filtr = next(r for r in radky if r.kod == "UFI 25.011.00")
    souhrn = import_skladu.importuj(session, radky, novy.id, {filtr.index: [a.id, b.id]})
    assert (souhrn.zalozeno, souhrn.aktualizovano, souhrn.slouceno_karet, souhrn.prepsano_radku) == (2, 0, 2, 2)
    karta = cenik.najdi_podle_kodu(session, "UFI 25.011.00", novy.id)
    assert (karta.cena, karta.nakupni_cena, karta.aktivni) == (Decimal("199.00"), Decimal("95.50"), True)
    for r, cena in ((ra, Decimal("161.16")), (rb, Decimal("177"))):
        session.refresh(r)
        assert (r.kod, r.polozka_ceniku_id, r.katalog_id, r.cena) == ("UFI 25.011.00", karta.id, novy.id, cena)
    session.refresh(a), session.refresh(b)
    assert not a.aktivni and not b.aktivni


def test_opakovany_import_jen_aktualizuje_ceny(session, stare):
    novy = katalogy.vytvor(session, "Nový sklad")
    radky = [r for r in import_skladu.navrh(session, import_skladu.nacti(SEZNAM.encode()), novy.id) if not r.chyba]
    import_skladu.importuj(session, radky, novy.id, {})
    zdrazeni = SEZNAM.replace("199,00", "209,00").encode()
    navrh = import_skladu.navrh(session, import_skladu.nacti(zdrazeni), novy.id)
    filtr = next(r for r in navrh if r.kod == "UFI 25.011.00")
    assert filtr.existujici_id and filtr.existujici_cena == "199.00"
    souhrn = import_skladu.importuj(session, [r for r in navrh if not r.chyba], novy.id, {})
    assert (souhrn.zalozeno, souhrn.aktualizovano) == (0, 2)
    assert cenik.najdi_podle_kodu(session, "UFI 25.011.00", novy.id).cena == Decimal("209.00")


def test_rucne_dopsany_stary_kod(session):
    mann = cenik.vytvor(session, {"kod": "W 712/75", "nazev": "Olejový filtr MANN", "cena": "150"})
    assert import_skladu.najdi_stare_kody(session, "W 712/75; NEEXISTUJE") == ([mann.id], ["NEEXISTUJE"])


# ---------------------------------------------------------------- web

@pytest.fixture
def web(session, monkeypatch):
    nastaveni.uloz(session, {"sprava_dat": "1"})
    zalohy_ = []
    monkeypatch.setattr(zalohy, "pred_sloucenim", lambda: zalohy_.append(1) or Path("pred-sloucenim-test.db"))
    return TestClient(app), zalohy_


def test_web_import_do_noveho_skladu(session, stare, web):
    klient, zalohy_ = web
    a, b, ra, _ = stare
    assert "/sprava-dat/import-skladu" in klient.get("/sprava-dat").text
    assert "založit nový sklad" in klient.get("/sprava-dat/import-skladu").text
    nahled = klient.post("/sprava-dat/import-skladu/nahled", data={"katalog": "novy", "novy_nazev": "Nový sklad"},
                         files={"soubor": ("ufi.csv", SEZNAM.encode(), "text/csv")})
    assert nahled.status_code == 200 and "Importovat vybrané" in nahled.text and "2501100" in nahled.text
    assert session.exec(select(Katalog).where(Katalog.nazev == "Nový sklad")).first() is None  # náhled nic nezaloží
    navrh = import_skladu.navrh(session, import_skladu.nacti(SEZNAM.encode()), None)
    filtr = next(r for r in navrh if r.kod == "UFI 25.011.00")
    vzduch = next(r for r in navrh if r.kod == "UFI 30.779.00")
    odpoved = klient.post("/sprava-dat/import-skladu", follow_redirects=False, data={
        "data_navrhu": import_skladu.do_json(navrh), "katalog": "novy", "novy_nazev": "Nový sklad",
        "vybrano": [str(filtr.index), str(vzduch.index)], f"stare_{filtr.index}": [str(a.id)]})  # b odškrtnuto
    assert odpoved.status_code == 303 and zalohy_ == [1]
    sklad = session.exec(select(Katalog).where(Katalog.nazev == "Nový sklad")).one()
    karta = cenik.najdi_podle_kodu(session, "UFI 25.011.00", sklad.id)
    session.refresh(ra), session.refresh(b)
    assert ra.polozka_ceniku_id == karta.id and b.aktivni


def test_web_nenalezeny_rucni_kod_nic_neulozi(session, stare, web):
    klient, zalohy_ = web
    navrh = import_skladu.navrh(session, import_skladu.nacti(SEZNAM.encode()), None)
    odpoved = klient.post("/sprava-dat/import-skladu", follow_redirects=False, data={
        "data_navrhu": import_skladu.do_json(navrh), "katalog": "novy", "novy_nazev": "Nový sklad",
        "vybrano": [str(navrh[0].index)], f"dalsi_{navrh[0].index}": "XYZ 1"})
    assert odpoved.status_code == 303 and zalohy_ == []
    assert session.exec(select(Katalog).where(Katalog.nazev == "Nový sklad")).first() is None
    assert len(session.exec(select(PolozkaCeniku)).all()) == 2


def test_web_import_skryty_bez_prepinace(session):
    assert TestClient(app).get("/sprava-dat/import-skladu").status_code == 404


# ---------------------------------------------------------------- režimy, párování, chybějící díly (#137)

def test_rezimy_a_parovani(session, stare):
    a, b, *_ = stare
    sklad = katalogy.vychozi(session)
    radky = import_skladu.nacti(b"Kod;Nazev;Prodej;DPH %\n25.011.00;Filtr;180;12\nNOVY 1;Novy dil;50;21\n")
    obe = import_skladu.navrh(session, radky, sklad.id)
    filtr = next(r for r in obe if r.kod == "25.011.00")
    assert filtr.existujici_id == b.id and [s["id"] for s in filtr.stare] == [a.id] and filtr.dph == "12"
    jen_kod = import_skladu.navrh(session, radky, sklad.id, parovani="kod")
    assert all(r.stare == [] for r in jen_kod)
    nove = {r.kod: r.chyba for r in import_skladu.navrh(session, radky, sklad.id, rezim="nove")}
    assert nove["25.011.00"].startswith("Už je ve skladu") and nove["NOVY 1"] == ""
    aktualizace = {r.kod: r.chyba for r in import_skladu.navrh(session, radky, sklad.id, rezim="aktualizace")}
    assert aktualizace["25.011.00"] == "" and aktualizace["NOVY 1"].startswith("Ve skladu není")
    import_skladu.importuj(session, [r for r in jen_kod if r.kod == "25.011.00"], sklad.id, {})
    session.refresh(b)
    assert (b.cena, b.sazba_dph) == (Decimal("180"), Decimal("12"))
    assert [p.id for p in import_skladu.chybejici(session, radky, sklad.id)] == [a.id]


def test_web_import_vyradi_chybejici(session, stare, web):
    klient, _ = web
    a, b, *_ = stare
    sklad = katalogy.vychozi(session)
    soubor = b"Kod;Nazev;Prodej\n25.011.00;Filtr;180\n"
    nahled = klient.post("/sprava-dat/import-skladu/nahled",
                         data={"katalog": str(sklad.id), "rezim": "aktualizace", "parovani": "kod"},
                         files={"soubor": ("s.csv", soubor, "text/csv")})
    assert "vyřadit díly skladu, které v souboru nejsou" in nahled.text and "jen aktualizace cen" in nahled.text
    navrh = import_skladu.navrh(session, import_skladu.nacti(soubor), sklad.id, "aktualizace", "kod")
    odpoved = klient.post("/sprava-dat/import-skladu", follow_redirects=False, data={
        "data_navrhu": import_skladu.do_json(navrh), "katalog": str(sklad.id), "vybrano": "0",
        "vyradit_chybejici": "1"})
    assert odpoved.status_code == 303
    session.refresh(a), session.refresh(b)
    assert not a.aktivni and b.aktivni and b.cena == Decimal("180")
