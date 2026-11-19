from decimal import Decimal

import pytest

from app.models import PolozkaZakazky, TypPolozky
from app.services import ChybaValidace, cenik, nastaveni, polozky, zakazky


@pytest.fixture
def zakazka(session):
    return zakazky.prijem(
        session, zakazka={"pozadavek": "Servis"},
        vozidlo={"spz": "1AB2345"}, zakaznik={"nazev": "Jan Novák"},
    )


def test_vychozi_a_ulozene_nastaveni(session):
    n = nastaveni.nacti(session)
    assert n.platce_dph and n.vychozi_dph == 21
    assert not hasattr(n, "sazba_normohodiny")  # normohodiny zrušeny
    n = nastaveni.uloz(session, {"platce_dph": "0"})
    assert not n.platce_dph
    with pytest.raises(ChybaValidace):
        nastaveni.uloz(session, {"vychozi_dph": "150"})


def test_cenik_vytvoreni_a_validace(session):
    olej = cenik.vytvor(session, {"nazev": "Olej 5W-30", "kod": "OL530", "cena": "1 234,50", "jednotka": "l"})
    assert olej.cena == Decimal("1234.50") and olej.typ == TypPolozky.MATERIAL and olej.sazba_dph == 21
    with pytest.raises(ChybaValidace):
        cenik.vytvor(session, {"nazev": "Jiný", "kod": "OL530", "cena": "1"})
    with pytest.raises(ChybaValidace):
        cenik.vytvor(session, {"nazev": "Bez ceny"})
    with pytest.raises(ChybaValidace):
        cenik.vytvor(session, {"nazev": "X", "cena": "abc"})


def test_cena_zadana_s_dph(session):
    p = cenik.vytvor(session, {"nazev": "Stěrač", "cena": "121", "cena_s_dph": "on"})
    assert p.cena == Decimal("100.0000")


def test_hledani_a_filtr(session):
    cenik.vytvor(session, {"nazev": "Výměna oleje", "typ": "prace", "cena": "400", "jednotka": "úkon"})
    cenik.vytvor(session, {"nazev": "Olejový filtr", "cena": "250"})
    assert len(cenik.seznam(session, "olej")) == 2
    assert [p.nazev for p in cenik.seznam(session, typ="prace")] == ["Výměna oleje"]
    # práce bez ceny už nejde (časová norma / normohodiny zrušeny)
    with pytest.raises(ChybaValidace):
        cenik.vytvor(session, {"nazev": "Diagnostika", "typ": "prace"})


def test_pridani_materialu_a_prace(session, zakazka):
    filtr = cenik.vytvor(session, {"nazev": "Olejový filtr", "cena": "250"})
    vymena = cenik.vytvor(session, {"nazev": "Výměna oleje", "typ": "prace", "cena": "800"})
    polozky.pridej_z_ceniku(session, zakazka.id, filtr.id, mnozstvi="2")
    r = polozky.pridej_z_ceniku(session, zakazka.id, vymena.id, mnozstvi="0,5")
    assert r.jednotka == "hod" and r.mnozstvi == Decimal("0.5") and r.cena == 800
    assert r.zaklad == Decimal("400.00")

    session.refresh(zakazka)
    rek = polozky.rekapitulace(zakazka)
    assert rek.material == Decimal("500.00") and rek.prace == Decimal("400.00")
    assert rek.dph == Decimal("189.00") and rek.celkem == Decimal("1089.00")


def test_zmena_ceniku_nezmeni_zakazku(session, zakazka):
    filtr = cenik.vytvor(session, {"nazev": "Filtr", "cena": "250"})
    r = polozky.pridej_z_ceniku(session, zakazka.id, filtr.id)
    cenik.uprav(session, filtr.id, {"cena": "999"})
    cenik.smaz(session, filtr.id)
    r = polozky.ziskej(session, r.id)
    assert r.cena == 250 and r.nazev == "Filtr"


def test_rucni_polozka_a_ulozeni_do_ceniku(session, zakazka):
    r = polozky.pridej_rucne(session, zakazka.id, {
        "typ": "material", "nazev": "Žárovka H7", "mnozstvi": "2", "cena": "89,90", "ulozit_do_ceniku": "on",
    })
    assert r.polozka_ceniku_id is not None
    assert cenik.ziskej(session, r.polozka_ceniku_id).cena == Decimal("89.90")
    hodiny = polozky.pridej_rucne(session, zakazka.id, {"typ": "prace", "nazev": "Diagnostika", "mnozstvi": "1,5",
                                                        "cena": "600"})
    assert hodiny.jednotka == "hod" and hodiny.cena == 600
    # práce v hodinách bez ceny už nedostane sazbu normohodiny
    with pytest.raises(ChybaValidace):
        polozky.pridej_rucne(session, zakazka.id, {"typ": "prace", "nazev": "Diagnostika", "mnozstvi": "1"})


def test_rucni_polozka_chyba_nic_neulozi(session, zakazka):
    with pytest.raises(ChybaValidace):
        polozky.pridej_rucne(session, zakazka.id, {"nazev": "Kus", "ulozit_do_ceniku": "on"})
    assert cenik.seznam(session) == []


def test_neplatce_dph(session, zakazka):
    nastaveni.uloz(session, {"platce_dph": "0"})
    p = cenik.vytvor(session, {"nazev": "Filtr", "cena": "100"})
    polozky.pridej_z_ceniku(session, zakazka.id, p.id)
    session.refresh(zakazka)
    rek = polozky.rekapitulace(zakazka)
    assert rek.dph == 0 and rek.celkem == 100


def test_predanou_zakazku_nelze_menit(session, zakazka):
    p = cenik.vytvor(session, {"nazev": "Filtr", "cena": "100"})
    r = polozky.pridej_z_ceniku(session, zakazka.id, p.id)
    zakazky.zmen_stav(session, zakazka.id, "predano", bez_dokladu=True)
    with pytest.raises(ChybaValidace):
        polozky.pridej_z_ceniku(session, zakazka.id, p.id)
    with pytest.raises(ChybaValidace):
        polozky.smaz(session, r.id)


def test_uprava_a_smazani_radku(session, zakazka):
    p = cenik.vytvor(session, {"nazev": "Filtr", "cena": "100"})
    r = polozky.pridej_z_ceniku(session, zakazka.id, p.id)
    r = polozky.uprav(session, r.id, {"mnozstvi": "3", "cena": "90"})
    assert r.zaklad == Decimal("270.00")
    with pytest.raises(ChybaValidace):
        polozky.uprav(session, r.id, {"mnozstvi": "0"})
    session.rollback()
    assert polozky.smaz(session, r.id) == zakazka.id
    session.refresh(zakazka)
    assert zakazka.polozky == []


def test_dph_ze_souctu_zakladu(session, zakazka):
    # 3 × 0,33 Kč: DPH ze součtu (0,99 × 21 % = 0,21), ne součet zaokrouhlených řádků (3 × 0,07)
    for _ in range(3):
        polozky.pridej_rucne(session, zakazka.id, {"nazev": "Drobnost", "cena": "0,33"})
    session.refresh(zakazka)
    assert polozky.rekapitulace(zakazka).dph == Decimal("0.21")


def test_vloz_z_ceniku_vse_nebo_nic(session):
    z = zakazky.prijem(session, zakazka={}, vozidlo={"spz": "1AA0001"}, zakaznik={"nazev": "A"})
    a = cenik.vytvor(session, {"typ": "material", "nazev": "Olej", "cena": "200", "jednotka": "l"})
    b = cenik.vytvor(session, {"typ": "material", "nazev": "Filtr", "cena": "150"})
    radky = polozky.vloz_z_ceniku(session, z.id, [(a.id, "4,5"), (b.id, "1")])
    assert [(r.nazev, r.mnozstvi) for r in radky] == [("Olej", Decimal("4.5")), ("Filtr", Decimal("1"))]
    for chybny in ([(a.id, "1"), (b.id, "0")], [(a.id, "1"), (12345, "1")], []):
        with pytest.raises(ChybaValidace):
            polozky.vloz_z_ceniku(session, z.id, chybny)
    session.refresh(z)
    assert len(z.polozky) == 2  # chybný výběr nevložil nic
    zakazky.zmen_stav(session, z.id, "predano", bez_dokladu=True)
    with pytest.raises(ChybaValidace):
        polozky.vloz_z_ceniku(session, z.id, [(a.id, "1")])

def test_smazani_zakazky_s_materialem_a_praci(session, zakazka):
    """#24: otevřenou zakázku jde smazat i s položkami – smažou se s ní; ceník zůstane."""
    p = cenik.vytvor(session, {"nazev": "Filtr", "cena": "100"})
    r = polozky.pridej_z_ceniku(session, zakazka.id, p.id)
    polozky.pridej_rucne(session, zakazka.id, {"typ": "prace", "nazev": "Výměna", "cena": "300"})
    assert zakazky.duvod_proc_nesmazat(zakazka) is None
    zakazky.smaz(session, zakazka.id)
    assert session.get(PolozkaZakazky, r.id) is None
    assert cenik.ziskej(session, p.id).nazev == "Filtr"
