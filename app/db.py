"""Připojení k databázi SQLite."""
import re
import sqlite3
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

from sqlalchemy import event, inspect, text
from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, create_engine

from app import config
from app import models  # noqa: F401  – registrace tabulek


def cesky_klic(text: str | None) -> tuple:
    """Klíč pro řazení podle české abecedy: bez ohledu na velikost písmen, á = a, ale č za c,
    ř za r, š za s, ž za z a ch za h (Čermák až za Cibulka, Chalupa za Hruška)."""
    if not text:
        return ()
    zaklad = {"á": "a", "ä": "a", "é": "e", "ě": "e", "ë": "e", "í": "i", "ó": "o", "ö": "o", "ô": "o",
              "ú": "u", "ů": "u", "ü": "u", "ý": "y", "ď": "d", "ť": "t", "ň": "n", "ĺ": "l", "ľ": "l", "ŕ": "r"}
    hacky = {"č": "c", "ř": "r", "š": "s", "ž": "z"}
    s = text.lower()
    klic, i = [], 0
    while i < len(s):
        if s.startswith("ch", i):  # ch je samostatné písmeno za h
            klic.append(("h", 2, 0))
            i += 2
            continue
        z = s[i]
        if z in hacky:
            klic.append((hacky[z], 1, 0))
        else:
            klic.append((zaklad.get(z, z), 0, 1 if z in zaklad else 0))  # čárka rozhoduje až při shodě
        i += 1
    # primárně písmena bez čárek (á = a), čárky až jako poslední rozlišení
    return tuple((p, h) for p, h, _ in klic), tuple(c for _, _, c in klic)


def _porovnej_cesky(a: str, b: str) -> int:
    ka, kb = cesky_klic(a), cesky_klic(b)
    return (ka > kb) - (ka < kb)


@event.listens_for(Engine, "connect")
def _zapni_cizi_klice(dbapi_conn, _record):
    """SQLite má kontrolu cizích klíčů ve výchozím stavu vypnutou.
    Zároveň registruje řazení „cs“ (česká abeceda) pro řazení seznamů: `sloupec.collate("cs")`."""
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()
    if hasattr(dbapi_conn, "create_collation"):
        dbapi_conn.create_collation("cs", _porovnej_cesky)


def vytvor_engine(url: str = config.DATABASE_URL) -> Engine:
    return create_engine(url, connect_args={"check_same_thread": False})


engine = vytvor_engine()


def init_db(eng: Engine | None = None) -> None:
    eng = eng or engine
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    SQLModel.metadata.create_all(eng)
    doplnit_sloupce(eng)
    uvolnit_povinne_sloupce(eng)


def doplnit_sloupce(eng: Engine) -> list[str]:
    """Jednoduchá migrace: přidá do existujících tabulek nové sloupce z modelů.

    `create_all` umí jen nové tabulky. Nové sloupce musí být v modelu nepovinné
    (nebo mít jednoduchou výchozí hodnotu) – SQLite je přidá přes ALTER TABLE ADD COLUMN.
    Vrací seznam přidaných sloupců „tabulka.sloupec“.
    """
    pridane = []
    existujici = inspect(eng)
    with eng.begin() as conn:
        for tabulka in SQLModel.metadata.sorted_tables:
            if not existujici.has_table(tabulka.name):
                continue
            sloupce = {s["name"] for s in existujici.get_columns(tabulka.name)}
            for sloupec in tabulka.columns:
                if sloupec.name in sloupce:
                    continue
                typ = sloupec.type.compile(dialect=eng.dialect)
                vychozi = ""
                if not sloupec.nullable:
                    default = getattr(sloupec.default, "arg", None)
                    if isinstance(default, bool):
                        default = int(default)
                    if not isinstance(default, (int, float, str)):
                        raise RuntimeError(f"Nový povinný sloupec {tabulka.name}.{sloupec.name} nemá výchozí hodnotu.")
                    vychozi = f" NOT NULL DEFAULT {default!r}"
                conn.execute(text(f'ALTER TABLE "{tabulka.name}" ADD COLUMN "{sloupec.name}" {typ}{vychozi}'))
                pridane.append(f"{tabulka.name}.{sloupec.name}")
    return pridane


def _zaloha_pred_migraci(eng: Engine) -> Path | None:
    """Kopie souborové databáze do data/backups/ (SQLite backup – bezpečné i za běhu)."""
    soubor = eng.url.database
    if not soubor or soubor == ":memory:" or not Path(soubor).exists():
        return None
    zalohy = Path(soubor).resolve().parent / "backups"
    zalohy.mkdir(parents=True, exist_ok=True)
    cil = zalohy / f"pred-migraci-{datetime.now():%Y%m%d-%H%M%S}.db"
    zdroj, kopie = sqlite3.connect(soubor), sqlite3.connect(cil)
    try:
        zdroj.backup(kopie)
    finally:
        kopie.close()
        zdroj.close()
    return cil


def uvolnit_povinne_sloupce(eng: Engine) -> list[str]:
    """Migrace: sloupec, který je v modelu nepovinný, ale v databázi NOT NULL (např. `zakazka.vozidlo_id`
    po povolení zakázky bez vozidla, #50), se uvolní. SQLite neumí ALTER COLUMN – tabulka se přestaví
    podle postupu z dokumentace SQLite (nová tabulka, kopie dat, výměna, indexy). Předtím záloha DB.
    Vrací seznam uvolněných sloupců „tabulka.sloupec“."""
    existujici = inspect(eng)
    zmeny: dict[str, list[str]] = {}
    for tabulka in SQLModel.metadata.sorted_tables:
        if not existujici.has_table(tabulka.name):
            continue
        v_db = {s["name"]: s for s in existujici.get_columns(tabulka.name)}
        for sloupec in tabulka.columns:
            if (sloupec.nullable and not sloupec.primary_key and sloupec.name in v_db
                    and not v_db[sloupec.name]["nullable"]):
                zmeny.setdefault(tabulka.name, []).append(sloupec.name)
    if not zmeny:
        return []
    _zaloha_pred_migraci(eng)
    hotovo = []
    surove = eng.raw_connection()
    try:
        con = surove.driver_connection
        puvodni_izolace = con.isolation_level
        con.isolation_level = None  # transakce řídíme ručně (PRAGMA foreign_keys jen mimo transakci)
        cur = con.cursor()
        cur.execute("PRAGMA foreign_keys=OFF")
        try:
            cur.execute("BEGIN")
            for nazev, sloupce in zmeny.items():
                sql = cur.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (nazev,)).fetchone()[0]
                for s in sloupce:
                    nove = re.sub(rf'("?{s}"?\s+[A-Z]+(?:\(\d+\))?)\s+NOT NULL', r"\1", sql, count=1)
                    if nove == sql:
                        raise RuntimeError(f"Migrace: v definici {nazev} se nenašlo {s} NOT NULL.")
                    sql = nove
                    hotovo.append(f"{nazev}.{s}")
                docasna = f"{nazev}__nova"
                sql = re.sub(rf'^CREATE TABLE\s+"?{nazev}"?', f'CREATE TABLE "{docasna}"', sql, count=1)
                indexy = [r[0] for r in cur.execute(
                    "SELECT sql FROM sqlite_master WHERE type='index' AND tbl_name=? AND sql IS NOT NULL", (nazev,))]
                cur.execute(sql)
                cur.execute(f'INSERT INTO "{docasna}" SELECT * FROM "{nazev}"')
                cur.execute(f'DROP TABLE "{nazev}"')
                cur.execute(f'ALTER TABLE "{docasna}" RENAME TO "{nazev}"')
                for index in indexy:
                    cur.execute(index)
            chyby = cur.execute("PRAGMA foreign_key_check").fetchall()
            if chyby:
                raise RuntimeError(f"Migrace: porušené cizí klíče {chyby[:3]}")
            cur.execute("COMMIT")
        except Exception:
            cur.execute("ROLLBACK")
            raise
        finally:
            cur.execute("PRAGMA foreign_keys=ON")
            con.isolation_level = puvodni_izolace
    finally:
        surove.close()
    return hotovo


def get_session() -> Iterator[Session]:
    with Session(engine) as session:
        yield session
