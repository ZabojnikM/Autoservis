from datetime import date

import pytest

from app.models import StavZakazky
from app.services import ChybaValidace, hledani, vozidla, zakaznici, zakazky


def _prijmi_nove(session, spz="1AB 2345", nazev="Jan Novák"):
    return zakazky.prijem(
        session,
        zakazka={"pozadavek": "Výměna oleje", "tachometr": "123 456", "stav_paliva": "1/2"},
        vozidlo={"spz": spz, "znacka": "Škoda", "model": "Octavia"},
        zakaznik={"nazev": nazev, "telefon": "777 111 222"},
    )


def test_normalizace_spz():
    assert vozidla.normalizuj_spz(" 1ab 23-45 ") == "1AB2345"


def test_prijem_noveho_vozidla_zalozi_zakaznika_i_vozidlo(session):
    z = _prijmi_nove(session)
    assert z.cislo == f"{date.today().year}-0001"
    assert z.vozidlo.spz == "1AB2345"
    assert z.zakaznik.nazev == "Jan Novák"
    assert z.vozidlo.zakaznik_id == z.zakaznik_id
    assert z.tachometr == 123456
    assert z.stav == StavZakazky.PRIJATO


def test_prijem_existujiciho_vozidla_podle_spz(session):
    prvni = _prijmi_nove(session)
    druha = zakazky.prijem(session, zakazka={"pozadavek": "Brzdy"}, vozidlo={"spz": "1ab2345"})
    assert druha.vozidlo_id == prvni.vozidlo_id
    assert druha.zakaznik_id == prvni.zakaznik_id
    assert druha.cislo.endswith("-0002")
    assert [z.id for z in vozidla.historie(session, prvni.vozidlo_id)] == [druha.id, prvni.id]


def test_prijem_s_existujicim_zakaznikem(session):
    zak = zakaznici.vytvor(session, {"nazev": "Firma s.r.o.", "ico": "123 45 678"})
    z = zakazky.prijem(
        session, zakazka={"pozadavek": "STK"}, vozidlo={"spz": "2BB0001"}, zakaznik={"id": zak.id}
    )
    assert z.zakaznik_id == zak.id
    assert zak.ico == "12345678"


def test_prijem_bez_zakaznika(session):
    z = zakazky.prijem(session, zakazka={"pozadavek": "x"}, vozidlo={"spz": "3CC0001"},
                       zakaznik={"vyber": "bez", "nazev": "ignoruje se"})
    assert z.zakaznik_id is None and z.vozidlo.zakaznik_id is None
    assert zakaznici.seznam(session) == []
    # bez jakýchkoli údajů o zákazníkovi taky projde
    z2 = zakazky.prijem(session, zakazka={"pozadavek": "y"}, vozidlo={"spz": "3CC0001"})
    assert z2.zakaznik_id is None


def test_prijem_novy_zakaznik_bez_jmena_selze(session):
    with pytest.raises(ChybaValidace):
        zakazky.prijem(session, zakazka={"pozadavek": "x"}, vozidlo={"spz": "3CC0001"},
                       zakaznik={"vyber": "novy", "nazev": ""})
    assert vozidla.seznam(session) == []


def test_zakaznika_lze_doplnit_pozdeji(session):
    z = zakazky.prijem(session, zakazka={"pozadavek": "x"}, vozidlo={"spz": "3CC0001"}, zakaznik={"vyber": "bez"})
    k = zakaznici.vytvor(session, {"nazev": "Doplněný"})
    z = zakazky.uprav(session, z.id, {"zakaznik_id": str(k.id)})
    assert z.zakaznik_id == k.id and z.vozidlo.zakaznik_id == k.id  # vozidlu bez zákazníka se přiřadí
    z = zakazky.uprav(session, z.id, {"zakaznik_id": "bez"})
    assert z.zakaznik_id is None and z.vozidlo.zakaznik_id == k.id  # vozidlo si zákazníka ponechá
    v = vozidla.uprav(session, z.vozidlo_id, {"zakaznik_id": "bez"})
    assert v.zakaznik_id is None


def test_prijem_zname_vozidlo_bez_zakaznika_mu_zakaznika_priradi(session):
    zakazky.prijem(session, zakazka={"pozadavek": "x"}, vozidlo={"spz": "3CC0001"}, zakaznik={"vyber": "bez"})
    z = zakazky.prijem(session, zakazka={"pozadavek": "y"}, vozidlo={"spz": "3CC0001"},
                       zakaznik={"vyber": "novy", "nazev": "Nový majitel"})
    assert z.zakaznik.nazev == "Nový majitel" and z.vozidlo.zakaznik_id == z.zakaznik_id


def test_chybny_prijem_selze_a_nezalozi_vozidlo(session):
    with pytest.raises(ChybaValidace):
        zakazky.prijem(session, zakazka={"tachometr": "-5"}, vozidlo={"spz": "3CC0001"}, zakaznik={"nazev": "A"})
    assert vozidla.seznam(session) == []
    assert zakaznici.seznam(session) == []


def test_prijem_bez_pozadavku_projde(session):
    """Popis zakázky (požadavek) je nepovinný."""
    z = zakazky.prijem(session, zakazka={}, vozidlo={"spz": "3CC0002"}, zakaznik={"nazev": "A"})
    assert z.id and z.pozadavek == ""


def test_duplicitni_spz_a_vin(session):
    zak = zakaznici.vytvor(session, {"nazev": "A"})
    vozidla.vytvor(session, {"spz": "1AA1111", "vin": "TMBJJ7NE0K0123456", "zakaznik_id": zak.id})
    with pytest.raises(ChybaValidace):
        vozidla.vytvor(session, {"spz": "1aa 1111"})
    with pytest.raises(ChybaValidace):
        vozidla.vytvor(session, {"spz": "9ZZ9999", "vin": "tmbjj7ne0k0123456"})
    with pytest.raises(ChybaValidace):
        vozidla.vytvor(session, {"spz": "9ZZ9999", "vin": "KRATKY"})


def test_uprava_vozidla_na_obsazenou_spz(session):
    a = vozidla.vytvor(session, {"spz": "1AA1111"})
    vozidla.vytvor(session, {"spz": "2BB2222"})
    with pytest.raises(ChybaValidace):
        vozidla.uprav(session, a.id, {"spz": "2BB2222"})
    session.rollback()
    assert vozidla.ziskej(session, a.id).spz == "1AA1111"


def test_zmena_stavu_a_uzavreni(session):
    z = _prijmi_nove(session)
    z = zakazky.zmen_stav(session, z.id, StavZakazky.PREDANO, bez_dokladu=True)
    assert z.uzavreno is not None and not z.je_otevrena
    z = zakazky.zmen_stav(session, z.id, StavZakazky.V_OPRAVE)
    assert z.uzavreno is None
    with pytest.raises(ChybaValidace):
        zakazky.zmen_stav(session, z.id, "neexistuje")


def test_seznam_a_pocty(session):
    a = _prijmi_nove(session)
    _prijmi_nove(session, spz="5EE5555", nazev="Petr Malý")
    zakazky.zmen_stav(session, a.id, StavZakazky.PREDANO, bez_dokladu=True)
    assert len(zakazky.seznam(session, jen_otevrene=True)) == 1
    assert len(zakazky.seznam(session, hledat="5ee 5555")) == 1
    assert len(zakazky.seznam(session, hledat="malý")) == 1
    pocty = zakazky.pocty_podle_stavu(session)
    assert pocty[StavZakazky.PRIJATO] == 1 and pocty[StavZakazky.PREDANO] == 1


def test_po_terminu(session):
    z = _prijmi_nove(session)
    z = zakazky.uprav(session, z.id, {"termin_dokonceni": "01.01.2020"})
    assert z.termin_dokonceni == date(2020, 1, 1)
    assert z.po_terminu


def test_cislovani_pokracuje_v_roce(session):
    _prijmi_nove(session)
    assert zakazky.dalsi_cislo(session) == f"{date.today().year}-0002"
    assert zakazky.dalsi_cislo(session, rok=1999) == "1999-0001"


def test_smazani_zakaznika_s_vozidlem_nejde(session):
    z = _prijmi_nove(session)
    with pytest.raises(ChybaValidace):
        zakaznici.smaz(session, z.zakaznik_id)


def test_globalni_hledani(session):
    _prijmi_nove(session)
    v = hledani.hledej(session, "1ab2345")
    assert len(v.vozidla) == 1 and len(v.zakazky) == 1
    assert hledani.hledej(session, "").prazdny
