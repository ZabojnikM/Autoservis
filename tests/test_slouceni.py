"""Sloučení duplicitních karet materiálu v ceníku (#130)."""
import sqlite3
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlmodel import select

from app.main import app
from app.models import PolozkaFaktury, PolozkaZakazky
from app.services import ChybaValidace, cenik, faktury, katalogy, nastaveni, polozky, slouceni, zakazky, zakaznici, zalohy

DNES = date(2026, 11, 21)


def _zakazka(session, spz="1KT1111"):
    return zakazky.prijem(session, zakazka={"pozadavek": "x"}, vozidlo={"spz": spz})


@pytest.fixture
def dva_filtry(session):
    """Stejný filtr pod dvěma kódy, oba použité ve starých zakázkách se starou cenou."""
    stary = cenik.vytvor(session, {"kod": "2501100", "nazev": "Olejový filtr", "cena": "161,16"})
    novejsi = cenik.vytvor(session, {"kod": "25.011.00", "nazev": "Olejový filtr", "cena": "177"})
    z1, z2 = _zakazka(session, "1KT1111"), _zakazka(session, "1KT1111")
    r1 = polozky.pridej_z_ceniku(session, z1.id, stary.id)
    r2 = polozky.pridej_z_ceniku(session, z2.id, novejsi.id)
    return stary, novejsi, r1, r2


def test_klic_kodu_bez_predpony_a_oddelovacu():
    assert slouceni.klic_kodu("UFI 25.011.00") == slouceni.klic_kodu("25.011.00") == slouceni.klic_kodu("2501100")
    assert slouceni.klic_kodu("0 242 235 668") == slouceni.klic_kodu("BO 0242235668") == "0242235668"
    assert slouceni.klic_kodu("T 2313101") == "T2313101"   # jednopísmenné „T“ je součást čísla
    assert slouceni.ma_predponu("UFI 25.011.00") and not slouceni.ma_predponu("25.011.00")


def test_navrh_najde_stejne_cislo_a_ponecha_kod_s_predponou(session, dva_filtry):
    stary, novejsi, *_ = dva_filtry
    ufi = cenik.vytvor(session, {"kod": "UFI 25.011.00", "nazev": "Olejový filtr UFI", "cena": "199"})
    cenik.vytvor(session, {"kod": "OC 90", "nazev": "Jiný filtr", "cena": "1"})
    skupiny = slouceni.navrhy(session)
    assert len(skupiny) == 1
    assert {k.id for k in skupiny[0].karty} == {stary.id, novejsi.id, ufi.id}
    assert skupiny[0].cil_id == ufi.id
    assert slouceni.navrhy(session, "25.011") and slouceni.navrhy(session, "2501100")
    assert slouceni.navrhy(session, "brzdy") == []


def test_navrh_bez_predpony_ponecha_nejpouzivanejsi(session, dva_filtry):
    stary, novejsi, r1, _ = dva_filtry
    polozky.pridej_z_ceniku(session, r1.zakazka_id, stary.id)
    assert slouceni.navrhy(session)[0].cil_id == stary.id


def test_slouceni_prepise_kod_v_zakazkach_a_necha_stare_ceny(session, dva_filtry):
    stary, novejsi, r1, r2 = dva_filtry
    v = slouceni.sluc(session, novejsi.id, [stary.id, novejsi.id], "UFI 25.011.00", "Olejový filtr UFI", "199,00",
                      dnes=DNES)
    assert (v.kod, v.karet, v.radku) == ("UFI 25.011.00", 1, 2)
    session.refresh(novejsi), session.refresh(stary), session.refresh(r1), session.refresh(r2)
    assert (novejsi.kod, novejsi.nazev, novejsi.cena, novejsi.aktivni) == ("UFI 25.011.00", "Olejový filtr UFI",
                                                                           Decimal("199"), True)
    assert not stary.aktivni and "Sloučeno do UFI 25.011.00 (21.11.2026)." in stary.poznamka
    assert stary.kod == "2501100"   # vyřazená karta se nemaže a kód si nechá
    for r, cena in ((r1, Decimal("161.16")), (r2, Decimal("177"))):
        assert (r.kod, r.polozka_ceniku_id, r.cena, r.nazev) == ("UFI 25.011.00", novejsi.id, cena, "Olejový filtr")
    # stejné číslo dílu do Zaměnitelný díl nepatří (hledání ho najde i tak)
    assert novejsi.zamenitelny_dil is None
    assert [p.id for p in cenik.seznam(session, "2501100", typ="material", jen_aktivni=True)] == [novejsi.id]


def test_historie_vozidla_ukaze_jeden_dil_s_novym_kodem_a_cenou(session, dva_filtry):
    stary, novejsi, r1, _ = dva_filtry
    slouceni.sluc(session, novejsi.id, [stary.id], "UFI 25.011.00", cena="199")
    nova = _zakazka(session, "1KT1111")
    historie = polozky.historie_vozidla(session, nova, "2501100")
    assert len(historie) == 1 and historie[0].pocet == 2
    assert historie[0].radek.kod == "UFI 25.011.00" and historie[0].cena == Decimal("199")
    vlozeny = polozky.pridej_z_historie(session, nova.id, r1.id)
    assert (vlozeny.kod, vlozeny.cena, vlozeny.polozka_ceniku_id) == ("UFI 25.011.00", Decimal("199"), novejsi.id)


def test_slouceni_nemeni_vystavene_doklady(session, dva_filtry):
    stary, novejsi, r1, _ = dva_filtry
    nastaveni.uloz(session, {"nazev_servisu": "Servis Test", "ico": "12345678", "dic": "CZ12345678", "mesto": "Brno",
                             "cislo_uctu": "19-2000145399/0800", "ucet_vyuctovani": "2001234567/2010"})
    z = zakazky.ziskej(session, r1.zakazka_id)
    zak = zakaznici.vytvor(session, {"nazev": "Jan Test", "ulice": "Hlavní 1", "mesto": "Brno", "psc": "60200"})
    z.zakaznik_id = zak.id
    session.add(z), session.commit()
    f = faktury.vystav(session, z.id, faktury.vychozi_udaje(session, z.id, "faktura"))
    slouceni.sluc(session, novejsi.id, [stary.id], "UFI 25.011.00", cena="199")
    radky = session.exec(select(PolozkaFaktury).where(PolozkaFaktury.faktura_id == f.id)).all()
    assert [(r.kod, r.cena) for r in radky] == [("2501100", Decimal("161.16"))]


def test_rucni_radek_se_starym_kodem_se_napoji(session, dva_filtry):
    stary, novejsi, r1, _ = dva_filtry
    rucni = polozky.pridej_rucne(session, r1.zakazka_id, {"typ": "material", "kod": "2501100", "nazev": "Filtr",
                                                          "mnozstvi": "1", "cena": "150"})
    slouceni.sluc(session, novejsi.id, [stary.id], "UFI 25.011.00")
    session.refresh(rucni)
    assert (rucni.kod, rucni.polozka_ceniku_id, rucni.cena) == ("UFI 25.011.00", novejsi.id, Decimal("150"))


def test_jine_cislo_dilu_pujde_do_zamenitelnych(session):
    mann = cenik.vytvor(session, {"kod": "W 712/75", "nazev": "Olejový filtr", "cena": "150"})
    ufi = cenik.vytvor(session, {"kod": "UFI 23.135.00", "nazev": "Olejový filtr UFI", "cena": "160",
                                 "zamenitelny_dil": "OC 205"})
    slouceni.sluc(session, ufi.id, [mann.id])
    session.refresh(ufi)
    assert ufi.zamenitelny_dil == "OC 205, W 712/75"


def test_chyby_slouceni(session, dva_filtry):
    stary, novejsi, *_ = dva_filtry
    jiny = cenik.vytvor(session, {"kod": "UFI 25.011.00", "nazev": "Už existuje", "cena": "1"})
    with pytest.raises(ChybaValidace, match="aspoň dvě"):
        slouceni.sluc(session, stary.id, [stary.id])
    with pytest.raises(ChybaValidace, match="přidejte ji do skupiny"):
        slouceni.sluc(session, novejsi.id, [stary.id], "UFI 25.011.00")
    session.rollback()
    with pytest.raises(ChybaValidace, match="ponechte tu kartu"):
        slouceni.sluc(session, novejsi.id, [stary.id, jiny.id], "UFI 25.011.00")
    session.rollback()
    with pytest.raises(ChybaValidace, match="není číslo"):
        slouceni.sluc(session, novejsi.id, [stary.id], cena="abc")
    session.rollback()
    prace = cenik.vytvor(session, {"nazev": "Práce", "typ": "prace", "cena": "1"})
    with pytest.raises(ChybaValidace, match="materiál s materiálem"):
        slouceni.sluc(session, novejsi.id, [prace.id])
    session.rollback()
    session.refresh(stary)
    assert stary.aktivni   # po chybě se nic neuložilo


def test_slouceni_napric_katalogy(session, dva_filtry):
    stary, novejsi, r1, _ = dva_filtry
    lkq = katalogy.vytvor(session, "LKQ")
    ufi = cenik.vytvor(session, {"kod": "UFI 25.011.00", "nazev": "Olejový filtr UFI", "cena": "199",
                                 "katalog_id": lkq.id})
    slouceni.sluc(session, ufi.id, [stary.id, novejsi.id])
    session.refresh(r1)
    assert (r1.polozka_ceniku_id, r1.katalog_id, r1.kod) == (ufi.id, lkq.id, "UFI 25.011.00")


def test_seznam_csv_tam_a_zpet(session, dva_filtry):
    stary, novejsi, *_ = dva_filtry
    obsah = slouceni.navrh_csv(session)
    assert obsah.startswith("﻿".encode())
    text = obsah.decode("utf-8-sig")
    assert text.splitlines()[0].startswith("Skupina;ID;Ponechat;Sloučit;Kód")
    # uživatel v Excelu doplní nový kód a cenu u ponechané karty
    radky = [r.split(";") for r in text.splitlines()]
    for r in radky[1:]:
        if r[2] == "ano":
            r[10], r[12] = "UFI 25.011.00", "199,00"
    upraveny = "\r\n".join(";".join(r) for r in radky).encode("cp1250")
    plany = slouceni.nacti_csv(session, upraveny)
    assert len(plany) == 1 and not plany[0].chyba and plany[0].kod == "UFI 25.011.00"
    plany = slouceni.z_json(slouceni.do_json(plany))
    souhrn = slouceni.sluc_seznam(session, plany)
    assert (len(souhrn.slouceno), souhrn.chyby) == (1, [])
    assert "Sloučeno skupin 1" in souhrn.text
    assert [p.kod for p in cenik.seznam(session, typ="material", jen_aktivni=True)] == ["UFI 25.011.00"]


def test_seznam_csv_chyby_skupin(session, dva_filtry):
    stary, novejsi, *_ = dva_filtry
    csv_text = ("Skupina;ID;Ponechat;Sloučit;Nový kód;Nový název;Nová cena bez DPH\n"
                f"1;{stary.id};;ano;;;\n1;{novejsi.id};;ano;;;\n"           # chybí Ponechat
                f"2;{stary.id};ano;ano;X;;\n2;99999;;ano;;;\n"              # neexistující karta
                f"3;{stary.id};ano;ano;X;;\n3;{novejsi.id};;ne;;;\n")       # jen jedna karta ke sloučení
    plany = slouceni.nacti_csv(session, csv_text.encode())
    assert [p.chyba for p in plany] == ["Chybí karta k ponechání (sloupec Ponechat = ano).",
                                        "Karta s ID „99999“ v ceníku není.",
                                        "Ve skupině je méně než dvě karty ke sloučení."]
    assert slouceni.sluc_seznam(session, plany).slouceno == []
    with pytest.raises(ChybaValidace, match="není seznam"):
        slouceni.nacti_csv(session, b"Kod;Nazev\n1;2\n")


def test_zaloha_pred_sloucenim(tmp_path):
    db = tmp_path / "autoservis.db"
    sqlite3.connect(db).execute("create table t (a)").connection.commit()
    for _ in range(2):
        cil = zalohy.pred_sloucenim(db, tmp_path / "backups")
    assert cil.name.startswith("pred-sloucenim-autoservis-") and cil.exists()
    assert zalohy._druh(cil.name) == "před sloučením"


# ---------------------------------------------------------------- web

@pytest.fixture
def zapnuta_sprava(session):
    nastaveni.uloz(session, {"sprava_dat": "1"})


@pytest.fixture
def zalohy_web(monkeypatch, zapnuta_sprava):
    vytvorene = []
    monkeypatch.setattr(zalohy, "pred_sloucenim", lambda: vytvorene.append(1) or Path("pred-sloucenim-test.db"))
    return vytvorene


def test_stranka_a_slouceni_pres_web(session, dva_filtry, zalohy_web):
    stary, novejsi, r1, _ = dva_filtry
    klient = TestClient(app)
    assert "/sprava-dat/slouceni-dilu" in klient.get("/sprava-dat").text
    stranka = klient.get("/sprava-dat/slouceni-dilu")
    assert stranka.status_code == 200 and "2501100" in stranka.text and "25.011.00" in stranka.text
    odpoved = klient.post("/sprava-dat/slouceni-dilu", data={"cil": str(novejsi.id), "karty": [str(stary.id), str(novejsi.id)],
                                                   "kod": "UFI 25.011.00", "nazev": "Olejový filtr", "cena": "199"},
                          follow_redirects=False)
    assert odpoved.status_code == 303 and zalohy_web == [1]
    session.refresh(r1)
    assert r1.kod == "UFI 25.011.00"
    assert "V ceníku nejsou díly" in klient.get("/sprava-dat/slouceni-dilu").text


def test_web_bez_zalohy_neslucuje(session, dva_filtry, monkeypatch, zapnuta_sprava):
    stary, novejsi, r1, _ = dva_filtry

    def selze():
        raise zalohy.ChybaZalohy("Disk je plný.")
    monkeypatch.setattr(zalohy, "pred_sloucenim", selze)
    odpoved = TestClient(app).post("/sprava-dat/slouceni-dilu", data={"cil": str(novejsi.id), "karty": [str(stary.id)],
                                                            "kod": "UFI 25.011.00"}, follow_redirects=False)
    assert odpoved.status_code == 303
    session.refresh(r1)
    assert r1.kod == "2501100"


def test_web_rucni_skupina_a_csv(session, dva_filtry, zalohy_web):
    stary, novejsi, *_ = dva_filtry
    klient = TestClient(app)
    assert "Ruční sloučení" in klient.get("/sprava-dat/slouceni-dilu?q=filtr").text
    csv_odpoved = klient.get("/sprava-dat/slouceni-dilu/navrh.csv")
    assert csv_odpoved.headers["content-type"].startswith("text/csv") and "25.011.00" in csv_odpoved.text
    nahled = klient.post("/sprava-dat/slouceni-dilu/nahled", files={"soubor": ("s.csv", csv_odpoved.content, "text/csv")})
    assert nahled.status_code == 200 and "Sloučit vybrané skupiny" in nahled.text
    data = slouceni.do_json(slouceni.nacti_csv(session, csv_odpoved.content))
    odpoved = klient.post("/sprava-dat/slouceni-dilu/seznam", data={"data_planu": data, "vybrano": "1"}, follow_redirects=False)
    assert odpoved.status_code == 303 and zalohy_web == [1]
    session.refresh(stary), session.refresh(novejsi)
    assert stary.aktivni != novejsi.aktivni


def test_sprava_dat_je_bez_prepinace_skryta(session, dva_filtry):
    klient = TestClient(app)
    assert nastaveni.nacti(session).sprava_dat is False
    assert ">Správa dat</a>" not in klient.get("/zakazky").text
    for adresa in ("/sprava-dat", "/sprava-dat/slouceni-dilu", "/sprava-dat/slouceni-dilu/navrh.csv"):
        assert klient.get(adresa).status_code == 404
    stary, novejsi, r1, _ = dva_filtry
    assert klient.post("/sprava-dat/slouceni-dilu", data={"cil": str(novejsi.id), "karty": [str(stary.id)],
                                                         "kod": "X"}).status_code == 404
    session.refresh(r1)
    assert r1.kod == "2501100"
    # Materiál zůstal bez tlačítka slučování
    assert "slouceni" not in klient.get("/cenik").text


def test_prepinac_v_nastaveni_zobrazi_zalozku(session):
    klient = TestClient(app)
    assert 'name="sprava_dat"' in klient.get("/nastaveni").text
    klient.post("/nastaveni", data={"sprava_dat": "1", "rada_faktura": "FV{RRRR}", "rada_vyuctovani": "VY{RRRR}"})
    assert nastaveni.nacti(session).sprava_dat is True
    stranka = klient.get("/zakazky").text
    assert ">Správa dat</a>" in stranka and 'href="/sprava-dat"' in stranka
    assert klient.get("/sprava-dat").status_code == 200
    # nezaškrtnuté políčko formulář nepošle → vypnuto
    klient.post("/nastaveni", data={"rada_faktura": "FV{RRRR}", "rada_vyuctovani": "VY{RRRR}"})
    session.expire_all()
    assert nastaveni.nacti(session).sprava_dat is False


def test_web_seznam_s_chybnou_skupinou_hlasi_chybu(session, dva_filtry, zalohy_web):
    stary, novejsi, *_ = dva_filtry
    plany = slouceni.nacti_csv(session, slouceni.navrh_csv(session))
    plany[0].kod = "UFI 25.011.00"
    cenik.vytvor(session, {"kod": "UFI 25.011.00", "nazev": "Už je", "cena": "1"})   # sloučení skupiny selže
    odpoved = TestClient(app).post("/sprava-dat/slouceni-dilu/seznam",
                                   data={"data_planu": slouceni.do_json(plany), "vybrano": "1"}, follow_redirects=False)
    assert odpoved.status_code == 303
    session.refresh(stary)
    assert stary.aktivni
