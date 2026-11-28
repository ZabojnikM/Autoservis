"""#228 Databáze pro souběžné zápisy: režim WAL, čekání na zámek, zálohy jako jeden soubor."""
import sqlite3
import threading
import time

from sqlalchemy import text
from sqlmodel import Session

from app import db as databaze
from app.models import Zakaznik
from app.services import aktualizace, zalohy
from tests.test_zalohy import aplikacni_db, _zakaznici  # noqa: F401 – fixtura a pomůcka


def test_souborova_db_ve_wal_s_cekanim(aplikacni_db):  # noqa: F811
    with aplikacni_db["eng"].connect() as c:
        assert c.execute(text("PRAGMA journal_mode")).scalar() == "wal"
        assert c.execute(text("PRAGMA busy_timeout")).scalar() == databaze.CEKANI_NA_ZAMEK_MS
        assert c.execute(text("PRAGMA foreign_keys")).scalar() == 1


def test_db_v_pameti_bez_wal(engine):
    with engine.connect() as c:
        assert c.execute(text("PRAGMA journal_mode")).scalar() == "memory"


def test_zaloha_je_jeden_soubor_v_beznem_rezimu(aplikacni_db):  # noqa: F811
    for soubor in (zalohy.rucni(aplikacni_db["db"], aplikacni_db["server"]),
                   aktualizace.zalohuj_db(aplikacni_db["db"], aplikacni_db["server"], "test")):
        assert open(soubor, "rb").read(100)[18:20] == b"\x01\x01"  # hlavička: běžný režim, ne WAL
        c = sqlite3.connect(f"file:{soubor}?mode=ro", uri=True)
        assert c.execute("select count(*) from zakaznik").fetchone()[0] == 1
        c.close()
        assert not soubor.with_name(soubor.name + "-wal").exists()
        assert not soubor.with_name(soubor.name + "-shm").exists()


def test_soubezny_zapis_pocka_misto_chyby(aplikacni_db):  # noqa: F811
    """Jiné spojení drží zápis 1 s; uložení mezitím počká a projde (nespadne na „database is locked“)."""
    drzi, chyby = threading.Event(), []

    def dlouhy_zapis():
        try:
            with Session(aplikacni_db["eng"]) as s:
                s.add(Zakaznik(nazev="TEST Vlákno"))
                s.flush()  # zápis drží zámek až do commitu
                drzi.set()
                time.sleep(1)
                s.commit()
        except Exception as e:  # noqa: BLE001
            chyby.append(e)
            drzi.set()

    t = threading.Thread(target=dlouhy_zapis)
    t.start()
    assert drzi.wait(10)
    assert _zakaznici(aplikacni_db["eng"]) == ["TEST Původní"]  # čtení neblokuje
    with Session(aplikacni_db["eng"]) as s:
        s.add(Zakaznik(nazev="TEST Hlavní"))
        s.commit()  # počká na konec zápisu vlákna
    t.join(10)
    assert not chyby and not t.is_alive()
    assert _zakaznici(aplikacni_db["eng"]) == ["TEST Hlavní", "TEST Původní", "TEST Vlákno"]


def test_zaloha_behem_zapisu_a_obnova_ve_wal(aplikacni_db):  # noqa: F811
    zaloha = zalohy.rucni(aplikacni_db["db"], aplikacni_db["server"])
    with Session(aplikacni_db["eng"]) as s:
        s.add(Zakaznik(nazev="TEST Později"))
        s.commit()
    zalohy.obnov(zaloha, aplikacni_db["db"], aplikacni_db["server"], aplikacni_db["eng"])
    assert _zakaznici(aplikacni_db["eng"]) == ["TEST Původní"]
    with aplikacni_db["eng"].connect() as c:
        assert c.execute(text("PRAGMA journal_mode")).scalar() == "wal"
        assert c.execute(text("PRAGMA integrity_check")).scalar() == "ok"
