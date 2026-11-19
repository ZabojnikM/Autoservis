"""#50: zakázka bez vozidla (i bez zákazníka), vyúčtování bez obou, faktura jen se zákazníkem,
migrace sloupce zakazka.vozidlo_id na nepovinný."""
import re
import sqlite3

import pytest
from sqlalchemy import inspect

from app import db as dbm
from app.services import ChybaValidace, faktury, polozky, zakazky
from tests.test_web import client

PRAZDNE_VOZIDLO = {"spz": "", "v_znacka": "", "v_model": ""}


def _prijem_bez(**navic):
    data = {"zakaznik_vyber": "", "k_nazev": "", "k_telefon": "", "pozadavek": "Prodej oleje", "tachometr": "",
            "stav_paliva": ""} | PRAZDNE_VOZIDLO | navic
    return client.post("/zakazky/nova", data=data, follow_redirects=False)


def test_zakazka_bez_vozidla_a_zakaznika_web():
    r = _prijem_bez()
    assert r.status_code == 303, r.text[:500]
    loc = r.headers["location"].split("?")[0]
    detail = client.get(loc).text
    assert "Bez vozidla" in detail and f'href="{loc}/upravit" data-okno>Doplnit</a>' in detail
    # seznam zakázek i hledání ji ukážou (outer join), sloupec Vozidlo „bez vozidla“
    cislo = re.search(r"<h1>Zakázka ([^ <]+)", detail).group(1)
    seznam = client.get("/zakazky").text
    assert cislo in seznam and "bez vozidla" in seznam
    assert cislo in client.get("/zakazky", params={"razeni": "vozidlo"}).text
    assert cislo in client.get("/hledat", params={"q": "Prodej oleje"}).text
    # vyúčtování bez vozidla i bez zákazníka: vystavit a vytisknout
    client.post(f"{loc}/polozky", data={"typ": "material", "nazev": "Olej 5W30", "mnozstvi": "1", "cena": "300"})
    assert "Bez vozidla" in client.get(f"{loc}/tisk").text or "neuvedeno" in client.get(f"{loc}/tisk").text
    assert client.get(f"{loc}/vystavit", params={"typ": "vyuctovani"}).status_code == 200
    r = client.post(f"{loc}/vystavit", data={"typ": "vyuctovani", "odb_nazev": "", "forma_uhrady": "hotove"},
                    follow_redirects=False)
    assert r.status_code == 303, r.text[:500]
    doklad = r.headers["location"].split("?")[0]
    tisk = client.get(f"{doklad}/tisk")
    assert tisk.status_code == 200 and "Olej 5W30" in tisk.text and "<dt>Vozidlo</dt>" not in tisk.text


def test_panel_vozidla_bez_spz_s_udaji_chyba():
    r = _prijem_bez(v_znacka="Škoda")
    assert r.status_code == 422 and "panel vozidla vyprázdněte" in r.text


def test_sluzby_bez_vozidla_a_faktura(session):
    z = zakazky.prijem_z_formulare(session, {"pozadavek": "Drobnost"}, {"spz": ""}, {})
    assert z.vozidlo_id is None and z.zakaznik_id is None
    polozky.pridej_rucne(session, z.id, {"typ": "prace", "nazev": "Kontrola", "cena": "200"})
    with pytest.raises(ChybaValidace, match="Faktura vyžaduje zákazníka"):
        faktury.vystav(session, z.id, {"typ": "faktura", "odb_nazev": "X"})
    # se zákazníkem a bez vozidla faktura jde (vozidlo není povinné)
    s_zakaznikem = zakazky.prijem_z_formulare(session, {"pozadavek": "Díl"}, {"spz": ""}, {"nazev": "Firma s.r.o."})
    polozky.pridej_rucne(session, s_zakaznikem.id, {"typ": "material", "nazev": "Žárovka", "cena": "50"})
    from app.services import nastaveni
    nastaveni.uloz(session, {"nazev_servisu": "Servis", "ico": "12345678", "dic": "CZ12345678", "mesto": "Brno",
                             "platce_dph": "1", "vychozi_dph": "21"})
    f = faktury.vystav(session, s_zakaznikem.id, {"typ": "faktura", "odb_nazev": "Firma s.r.o.",
                                                  "forma_uhrady": "hotove"})
    assert f.spz is None and f.odb_nazev == "Firma s.r.o."
    # vozidlo jde doplnit a zase odebrat v úpravě zakázky (bez dokladu)
    z = zakazky.uprav_z_formulare(session, z.id, {}, {"spz": "1AB2345"}, {})
    assert z.vozidlo and z.vozidlo.spz == "1AB2345"
    z = zakazky.uprav_z_formulare(session, z.id, {}, {"spz": ""}, {})
    assert z.vozidlo_id is None


def test_migrace_uvolni_vozidlo_id(tmp_path):
    soubor = tmp_path / "stara.db"
    c = sqlite3.connect(soubor)
    c.executescript("""
        CREATE TABLE vozidlo (id INTEGER NOT NULL, spz VARCHAR NOT NULL, PRIMARY KEY (id));
        CREATE TABLE zakazka (id INTEGER NOT NULL, cislo VARCHAR NOT NULL, vozidlo_id INTEGER NOT NULL,
            PRIMARY KEY (id), FOREIGN KEY(vozidlo_id) REFERENCES vozidlo (id));
        CREATE INDEX ix_zakazka_vozidlo_id ON zakazka (vozidlo_id);
        CREATE TABLE polozkazakazky (id INTEGER NOT NULL, zakazka_id INTEGER NOT NULL, PRIMARY KEY (id),
            FOREIGN KEY(zakazka_id) REFERENCES zakazka (id) ON DELETE CASCADE);
        INSERT INTO vozidlo VALUES (1, '1AB2345');
        INSERT INTO zakazka VALUES (1, '2026-0001', 1);
        INSERT INTO polozkazakazky VALUES (1, 1);
    """)
    c.close()
    eng = dbm.vytvor_engine(f"sqlite:///{soubor.as_posix()}")
    assert dbm.uvolnit_povinne_sloupce(eng) == ["zakazka.vozidlo_id"]
    sloupce = {s["name"]: s for s in inspect(eng).get_columns("zakazka")}
    assert sloupce["vozidlo_id"]["nullable"]
    c = sqlite3.connect(soubor)
    assert c.execute("SELECT cislo, vozidlo_id FROM zakazka").fetchall() == [("2026-0001", 1)]
    assert c.execute("SELECT count(*) FROM polozkazakazky").fetchone()[0] == 1
    assert c.execute("SELECT name FROM sqlite_master WHERE name='ix_zakazka_vozidlo_id'").fetchone()
    assert c.execute("PRAGMA foreign_key_check").fetchall() == []
    c.close()
    assert list((tmp_path / "backups").glob("pred-migraci-*.db"))  # záloha před přestavbou
    assert dbm.uvolnit_povinne_sloupce(eng) == []  # podruhé už nic
    eng.dispose()
