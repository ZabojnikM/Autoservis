"""Import ze starého systému – vymyšlená data ve formátu exportu (hodnoty jako text, jak je vrací ODBC)."""
from copy import deepcopy
from datetime import date, datetime
from decimal import Decimal

from sqlmodel import select

from app.importers.stary_system import importuj, palivo, rok_vyroby, znacka_model
from app.models import Faktura, ImportMapa, PolozkaCeniku, StavZakazky, TypDokladu, Vozidlo, Zakazka, Zakaznik


def _partner(id_, jmeno, ico=None):
    return {"ID": id_, "MENO1": jmeno, "MENO2": None, "MENO3": None, "ULICA": "Hlavní 1", "MESTO": "Brno",
            "PSC": "60200", "ICO": ico, "DIC": None, "ICDPH": None, "TELEFON": "777000111", "EMAIL": None,
            "POZNAMKA": "", "JEDOD": "0", "JEODB": "1"}


def _vozidlo(id_, odber, spz, vin=None):
    return {"ID": id_, "ID_ODBER": odber, "SPZ": spz, "SPZ_P": spz, "TYPAUTA": "Škoda Octavia 1.9 TDI",
            "VYROBENE": "20080305", "CKAROSERIE": vin, "CMOTORA": None, "KODTYPUMOT": "BXE", "OBJEMMOT": "1896",
            "VYKONMOT": "77", "PALIVODRUH": "NM", "FARBA": "modrá", "DOPLNKY": "0", "POZNAMKA": "",
            "TERMINSTK": "2027-03-24", "TERMINEK": None, "POPIS": ""}


def _zakazka(id_, cislo, vozidlo, odber, uzavrena="1"):
    return {"ID": id_, "JEPLAN": "0", "OZNACENIE": cislo, "ID_ODBER": odber, "ID_VOZIDLA": vozidlo,
            "MENO1": None, "MENO2": None, "MENO3": None, "ULICA": None, "MESTO": None, "PSC": None, "ICO": None,
            "DIC": None, "TELEFON": None, "EMAIL": None, "POPIS": "Výměna oleje", "POPVYKPRAC": "", "POPINTERNY": "",
            "D_PRIJATIA": "2026-09-01", "C_PRIJATIA": "08:30:00.000", "D_UKONCPLAN": "2026-09-03",
            "D_UKONCENIA": "2026-09-02" if uzavrena == "1" else None, "C_UKONCENIA": None, "UZAVRETA": uzavrena,
            "SPZ": None, "SPZ_P": None, "TYPAUTA": None, "VYROBENE": None, "PALIVO": None,
            "TACHOMETER": "150000", "CKAROSERIE": None}


def _faktura(id_, cislo, zakazka, odber, s_dph, bez_dph, dph, vyuctovani="0", splatena="0"):
    return {"ID": id_, "OZNACENIE": cislo, "ID_ZAKAZKY": zakazka, "ID_ODBER": odber, "MENO1": "Jan Testovací",
            "MENO2": None, "MENO3": None, "ULICA": "Hlavní 1", "MESTO": "Brno", "PSC": "60200", "ICO": None,
            "DIC": None, "ICDPH": None, "FORM_UHR": None if vyuctovani == "1" else "PP", "D_VYSTAV": "2026-09-02",
            "D_DODANIA": "2026-09-02", "D_SPLATN": "2026-09-16", "D_ZAPLAT": None, "SPLATENA": splatena,
            "BEZ_DPH": bez_dph, "S_DPH": s_dph, "DPH": dph, "ZAOKRUH": "-3", "VYUCTOV": vyuctovani,
            "MENAEURO": "0", "TEXTKONIEC": ""}


DATA = {
    "meta": {"zdroj": "test"},
    "PARTNERI": [_partner("10", "Jan Testovací"), _partner("11", "Firma Test s.r.o.", ico="12345678")],
    "VOZIDLA": [_vozidlo("100", "10", "1AB2345", "TMBAAA00000000001"), _vozidlo("101", "11", None)],
    "ZAKAZKY": [_zakazka("500", "ZAK2026/0001", "100", "10"),
                _zakazka("501", "ZAK2026/0002", "101", "11", uzavrena="0"),
                _zakazka("502", "ZAK2026/0003", "0", "11")],
    "FAKTURY": [_faktura("900", "26020001", "500", "10", "2420.00", "2000.33", "419.67"),
                _faktura("901", "260001VYUC", "502", "11", "1210.00", "1000.00", "210.00", vyuctovani="1", splatena="1")],
    "VYKPRACE": [{"ID": "1", "ID_ZAKAZKY": "500", "ID_FAKTURY": "900", "KOD": "MECH", "NAZOV": "Mechanická práce",
                  "JEDNOTKA": "hod", "JEDCENA": "450.0000", "MNOZSTVO": "2.0000", "SADZBADPH": "21",
                  "DATUM": "2026-09-02", "ZLAVA": None, "FAKTUROVAT": "1"}],
    "POHYBY": [{"ID": "7", "DRUH": "-1", "ID_SKLKARTY": "55", "ID_ZAKAZKY": "500", "ID_FAKTURY": "900",
                "DATUM": "2026-09-02", "MNOZSTVO": "4.0000", "JEDCENA": "100.0000", "FAKCENA": "275.0000",
                "SADZBADPH": "21", "POPIS": "", "ZLAVA": None, "FAKTUROVAT": "1"},
               {"ID": "8", "DRUH": "-1", "ID_SKLKARTY": "55", "ID_ZAKAZKY": "501", "ID_FAKTURY": None,
                "DATUM": "2026-09-05", "MNOZSTVO": "1.0000", "JEDCENA": "100.0000", "FAKCENA": "275.0000",
                "SADZBADPH": "21", "POPIS": "", "ZLAVA": "10", "FAKTUROVAT": "1"}],
    "ZLAVY": [],
    "SKLKARTY": [{"ID": "55", "OZNACENIE": "SKL0055", "CISLO": "OL-5W30", "NAZOV": "Olej 5W-30", "JEDNOTKA": "l",
                  "CENA": "100.0000", "CENAPR1": "275.0000", "CENAPR2": None, "CENAPR3": None, "SADZBADPH": "21",
                  "MNOZSTVO": "12.0000", "VYRADENY": "0"}],
    "PRACE": [{"ID": "1", "KOD": "MECH", "NAZOV": "Mechanická práce", "JEDNOTKA": "hod", "JEDCENA": "450.0000",
               "MNOZSTVO": "1.0000", "SADZBADPH": "21"}],
}


def test_prevody_hodnot():
    assert rok_vyroby("2008") == 2008
    assert rok_vyroby("20080305") == 2008
    assert rok_vyroby("4,2005") is None and rok_vyroby("97") is None and rok_vyroby("20007") is None
    assert palivo("NM") == "nafta" and palivo("BA 95 B") == "benzín" and palivo("BA + LPG") == "LPG"
    assert palivo("EL + BA") == "hybrid" and palivo(None) is None
    assert znacka_model("Škoda Octavia 1.9 TDI") == ("Škoda", "Octavia 1.9 TDI")
    assert znacka_model("Tatra") == ("Tatra", None)


def test_import_zakazky_vozidla_zakaznici(session):
    protokol = importuj(session, deepcopy(DATA))
    assert protokol.pridano["ZAKAZKY"] == 3

    zakazka = session.exec(select(Zakazka).where(Zakazka.cislo == "ZAK2026/0001")).one()
    assert zakazka.stav == StavZakazky.PREDANO
    assert zakazka.datum_prijeti == datetime(2026, 9, 1, 8, 30)
    assert zakazka.uzavreno == datetime(2026, 9, 2, 0, 0)
    assert zakazka.vozidlo.spz == "1AB2345" and zakazka.vozidlo.vin == "TMBAAA00000000001"
    assert zakazka.vozidlo.znacka == "Škoda" and zakazka.vozidlo.rok_vyroby == 2008
    assert zakazka.vozidlo.palivo == "nafta" and zakazka.vozidlo.termin_stk == date(2027, 3, 24)
    assert (zakazka.vozidlo.kod_motoru, zakazka.vozidlo.objem, zakazka.vozidlo.vykon) == ("BXE", "1896", "77")
    assert zakazka.vozidlo.motor is None and "STK" not in zakazka.vozidlo.poznamka
    assert zakazka.zakaznik.nazev == "Jan Testovací" and zakazka.vozidlo.zakaznik_id == zakazka.zakaznik_id
    assert [(p.typ, p.kod, p.mnozstvi, p.cena) for p in zakazka.polozky] == [
        ("prace", "MECH", Decimal("2"), Decimal("450")), ("material", "OL-5W30", Decimal("4"), Decimal("275"))]
    assert str(zakazka.polozky[0].cena) == "450"  # bez zbytečných nul z ODBC
    assert all(p.polozka_ceniku_id for p in zakazka.polozky)

    otevrena = session.exec(select(Zakazka).where(Zakazka.cislo == "ZAK2026/0002")).one()
    assert otevrena.stav == StavZakazky.PRIJATO and otevrena.uzavreno is None
    assert otevrena.vozidlo.spz == "BEZSPZ-SS101"
    assert otevrena.polozky[0].cena == Decimal("247.50")  # sleva 10 %

    bez_vozidla = session.exec(select(Zakazka).where(Zakazka.cislo == "ZAK2026/0003")).one()
    assert bez_vozidla.vozidlo.spz == "BEZSPZ-SSZ502"
    # bez data ukončení → datum vystavení dokladu
    assert bez_vozidla.uzavreno is not None
    assert any("neměla ve starém systému vozidlo" in u for u in protokol.upozorneni)

    assert len(session.exec(select(Zakaznik)).all()) == 2
    assert len(session.exec(select(PolozkaCeniku)).all()) == 2  # olej + práce MECH


def test_import_dokladu_uhrazene_a_castka_ze_stareho_systemu(session):
    importuj(session, deepcopy(DATA))
    faktura = session.exec(select(Faktura).where(Faktura.cislo == "26020001")).one()
    assert faktura.typ == TypDokladu.FAKTURA and faktura.forma_uhrady == "prevod"
    assert faktura.celkem == Decimal("2420.00")
    # položky 2000 Kč + 21 % = 2420 → bez zaokrouhlení
    assert faktura.zaokrouhleni == Decimal("0")
    assert faktura.je_uhrazena and faktura.uhrady[0].castka == Decimal("2420.00")
    assert faktura.zakazka.cislo == "ZAK2026/0001" and faktura.spz == "1AB2345"

    vyuctovani = session.exec(select(Faktura).where(Faktura.cislo == "260001VYUC")).one()
    assert vyuctovani.typ == TypDokladu.VYUCTOVANI and vyuctovani.forma_uhrady == "hotove"
    assert [p.nazev for p in vyuctovani.polozky] == ["Doklad ze starého systému bez rozpisu položek"]
    assert vyuctovani.celkem == Decimal("1210.00") and vyuctovani.zaokrouhleni == Decimal("0")
    assert vyuctovani.uhrady[0].datum == date(2026, 9, 2)


def test_opakovany_import_nic_nezdvoji(session):
    importuj(session, deepcopy(DATA))
    protokol = importuj(session, deepcopy(DATA))
    assert protokol.pridano == {}
    assert protokol.preskoceno["ZAKAZKY"] == 3
    assert len(session.exec(select(Zakazka)).all()) == 3
    assert len(session.exec(select(Faktura)).all()) == 2
    assert len(session.exec(select(ImportMapa).where(ImportMapa.tabulka == "ZAKAZKY")).all()) == 3


def test_opakovany_import_doplni_rozepsana_pole_starych_vozidel(session):
    importuj(session, deepcopy(DATA))
    # stav po první verzi importu: motor a termíny jen jako text
    v = session.exec(select(Vozidlo).where(Vozidlo.spz == "1AB2345")).one()
    v.kod_motoru = v.objem = v.vykon = None
    v.termin_stk = None
    v.motor = "BXE, 1896 ccm, výkon 77"
    v.poznamka = "STK do 24.03.2027\nImportováno ze starého systému"
    session.add(v)
    session.commit()
    data = deepcopy(DATA)
    data["VOZIDLA"][0]["OLEJ"] = "5W-30"
    protokol = importuj(session, data)
    session.refresh(v)
    assert (v.kod_motoru, v.objem, v.vykon, v.olej) == ("BXE", "1896", "77", "5W-30")
    assert v.termin_stk == date(2027, 3, 24) and v.motor is None and v.poznamka == "Importováno ze starého systému"
    assert protokol.pridano.get("VOZIDLA_DOPLNENA_POLE") == 1


def test_existujici_vozidlo_a_zakaznik_se_spoji(session):
    firma = Zakaznik(nazev="Firma Test s.r.o.", ico="12345678")
    session.add(firma)
    session.add(Vozidlo(spz="1AB2345", znacka="Škoda"))
    session.add(Zakazka(cislo="ZAK2026/0001", vozidlo_id=1))
    session.commit()

    protokol = importuj(session, deepcopy(DATA))
    vozidla = session.exec(select(Vozidlo).where(Vozidlo.spz == "1AB2345")).all()
    assert len(vozidla) == 1 and vozidla[0].vin == "TMBAAA00000000001" and vozidla[0].model == "Octavia 1.9 TDI"
    assert len(session.exec(select(Zakaznik).where(Zakaznik.ico == "12345678")).all()) == 1
    assert session.exec(select(Zakazka).where(Zakazka.cislo == "ZAK2026/0001-SS500")).one()
    assert any("už existuje" in u for u in protokol.upozorneni)


def test_smazany_partner_se_zalozi_z_udaju_zakazky(session):
    data = deepcopy(DATA)
    data["ZAKAZKY"][2].update(ID_ODBER="77", MENO1="Smazaný Zákazník", TELEFON="600100200")
    data["FAKTURY"][1]["ID_ODBER"] = "77"
    importuj(session, data)
    zakazka = session.exec(select(Zakazka).where(Zakazka.cislo == "ZAK2026/0003")).one()
    assert zakazka.zakaznik.nazev == "Smazaný Zákazník" and zakazka.zakaznik.telefon == "600100200"
    doklad = session.exec(select(Faktura).where(Faktura.cislo == "260001VYUC")).one()
    assert doklad.zakaznik_id == zakazka.zakaznik_id
    assert len(session.exec(select(Zakaznik).where(Zakaznik.nazev == "Smazaný Zákazník")).all()) == 1


def test_anonymni_odberatel_je_bez_zakaznika(session):
    data = deepcopy(DATA)
    data["ZAKAZKY"][2].update(ID_ODBER="78", MENO1="_")
    data["FAKTURY"][1].update(ID_ODBER="78", MENO1="_")
    importuj(session, data)
    zakazka = session.exec(select(Zakazka).where(Zakazka.cislo == "ZAK2026/0003")).one()
    assert zakazka.zakaznik_id is None
    doklad = session.exec(select(Faktura).where(Faktura.cislo == "260001VYUC")).one()
    assert doklad.zakaznik_id is None and doklad.odb_nazev == ""


def test_chyba_neulozi_nic(session):
    data = deepcopy(DATA)
    data["ZAKAZKY"][1]["TACHOMETER"] = "nečíslo"
    try:
        importuj(session, data)
    except Exception:
        pass
    else:
        raise AssertionError("import měl selhat")
    assert session.exec(select(Zakazka)).all() == []
    assert session.exec(select(ImportMapa)).all() == []
