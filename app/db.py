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


CEKANI_NA_ZAMEK_MS = 15000  # #228: souběžný zápis počká až 15 s, než ohlásí „database is locked“


@event.listens_for(Engine, "connect")
def _zapni_cizi_klice(dbapi_conn, _record):
    """SQLite má kontrolu cizích klíčů ve výchozím stavu vypnutou.
    Zároveň registruje řazení „cs“ (česká abeceda) pro řazení seznamů: `sloupec.collate("cs")`.

    #228: souborová databáze běží v režimu WAL (čtení a zápis se neblokují – zálohy, Statistiky a prohlížení
    nezdrží uložení), zápis počká na zámek až CEKANI_NA_ZAMEK_MS. Vedle databáze jsou soubory `-wal` a `-shm`."""
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.execute(f"PRAGMA busy_timeout={CEKANI_NA_ZAMEK_MS}")
    hlavni = next((r for r in cur.execute("PRAGMA database_list") if r[1] == "main"), None)
    if hlavni and hlavni[2]:  # souborová databáze (v paměti je cesta prázdná)
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA synchronous=NORMAL")
    cur.close()
    if hasattr(dbapi_conn, "create_collation"):
        dbapi_conn.create_collation("cs", _porovnej_cesky)


@event.listens_for(models.PolozkaCeniku, "before_insert")
def _vychozi_katalog(_mapper, connection, polozka):
    """Položka ceníku bez katalogu (práce, importy) patří do výchozího katalogu (#62)."""
    if polozka.katalog_id is None:
        polozka.katalog_id = connection.execute(
            text("SELECT id FROM katalog WHERE vychozi = 1 ORDER BY id")).scalar()


def kopie_databaze(zdroj: str | Path, cil: str | Path, jen_cteni: bool = False) -> None:
    """Konzistentní kopie běžící databáze přes SQLite backup API (#228).

    Kopie je jeden soubor v běžném režimu (bez `-wal`/`-shm`), i když zdroj běží ve WAL. Po kopii se zdroj zkusí
    „vyčistit“ (checkpoint), ať soubor `-wal` neroste; když to nejde (běží zápis), nevadí."""
    zdroj_spojeni = (sqlite3.connect(f"file:{zdroj}?mode=ro", uri=True, timeout=CEKANI_NA_ZAMEK_MS / 1000) if jen_cteni
                     else sqlite3.connect(zdroj, timeout=CEKANI_NA_ZAMEK_MS / 1000))
    kopie = sqlite3.connect(cil)
    try:
        zdroj_spojeni.backup(kopie)
        kopie.execute("PRAGMA journal_mode=DELETE")
    finally:
        kopie.close()
        zdroj_spojeni.close()
    try:
        spojeni = sqlite3.connect(zdroj, timeout=5)
        try:
            spojeni.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        finally:
            spojeni.close()
    except sqlite3.Error:
        pass


def vytvor_engine(url: str = config.DATABASE_URL) -> Engine:
    return create_engine(url, connect_args={"check_same_thread": False})


engine = vytvor_engine()


def init_db(eng: Engine | None = None) -> None:
    eng = eng or engine
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    SQLModel.metadata.create_all(eng)
    pridane = doplnit_sloupce(eng)
    if "faktura.vytisteno" in pridane:
        oznacit_stare_doklady_vytistene(eng)
    uvolnene = uvolnit_povinne_sloupce(eng)
    katalogy = zavest_katalogy(eng)
    if pridane or uvolnene or katalogy:  # #225: změny databáze při startu do záznamu událostí
        from app.zaznam import log
        log.info("Migrace databáze: přidané sloupce %s, uvolněné sloupce %s, katalogy %s",
                 ", ".join(pridane) or "–", ", ".join(uvolnene) or "–", "zavedeny" if katalogy else "beze změny")


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


def oznacit_stare_doklady_vytistene(eng: Engine) -> int:
    """#167: doklady převedené ze starého systému se tiskly tam – při zavedení stavu tisku je jednou
    označí jako vytištěné (bez data). Vrací počet označených."""
    with eng.begin() as conn:
        return conn.execute(text(
            "UPDATE faktura SET vytisteno = 1 WHERE poznamka LIKE '%Importováno ze starého systému%'")).rowcount


def _zaloha_pred_migraci(eng: Engine) -> Path | None:
    """Kopie souborové databáze do data/backups/ (SQLite backup – bezpečné i za běhu)."""
    soubor = eng.url.database
    if not soubor or soubor == ":memory:" or not Path(soubor).exists():
        return None
    zalohy = Path(soubor).resolve().parent / "backups"
    zalohy.mkdir(parents=True, exist_ok=True)
    cil = zalohy / f"pred-migraci-{datetime.now():%Y%m%d-%H%M%S}.db"
    kopie_databaze(soubor, cil)
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


VYCHOZI_KATALOG = "Hlavní katalog"


def zavest_katalogy(eng: Engine) -> bool:
    """Migrace #62 – více katalogů materiálu. Idempotentní, vrací True, když něco změnila.

    - založí výchozí katalog a přiřadí mu všechny položky ceníku bez katalogu (práce patří do výchozího),
    - řádkům zakázek z ceníku (materiál) při prvním zavedení doplní zdrojový katalog,
    - jedinečnost kódu: místo jedinečného indexu na `kod` jedinečná dvojice (katalog, kód)."""
    with eng.connect() as conn:
        indexy = {r[1]: r[2] for r in conn.execute(text("PRAGMA index_list(polozkaceniku)"))}
        bez_katalogu = conn.execute(text("SELECT count(*) FROM polozkaceniku WHERE katalog_id IS NULL")).scalar()
        vychozi = conn.execute(text("SELECT id FROM katalog WHERE vychozi = 1 ORDER BY id")).scalar()
    zmena_indexu = bool(indexy.get("ix_polozkaceniku_kod")) or "ux_polozkaceniku_katalog_kod" not in indexy
    if vychozi is not None and not bez_katalogu and not zmena_indexu:
        return False
    if bez_katalogu or zmena_indexu:
        _zaloha_pred_migraci(eng)
    with eng.begin() as conn:
        prvni = vychozi is None
        if prvni:
            jiny = conn.execute(text("SELECT id FROM katalog ORDER BY poradi, id")).scalar()
            if jiny is not None:  # katalogy existují, jen žádný není výchozí
                conn.execute(text("UPDATE katalog SET vychozi = 1 WHERE id = :id"), {"id": jiny})
                vychozi, prvni = jiny, False
            else:
                vychozi = conn.execute(text(
                    "INSERT INTO katalog (nazev, vychozi, poradi, skryty) VALUES (:n, 1, 0, 0) RETURNING id"),
                    {"n": VYCHOZI_KATALOG}).scalar()
        conn.execute(text("UPDATE polozkaceniku SET katalog_id = :k WHERE katalog_id IS NULL"), {"k": vychozi})
        if prvni:
            conn.execute(text(
                "UPDATE polozkazakazky SET katalog_id = (SELECT p.katalog_id FROM polozkaceniku p"
                " WHERE p.id = polozkazakazky.polozka_ceniku_id)"
                " WHERE katalog_id IS NULL AND typ = 'material' AND polozka_ceniku_id IS NOT NULL"))
        if indexy.get("ix_polozkaceniku_kod"):  # jedinečný index z doby jednoho ceníku
            conn.execute(text("DROP INDEX ix_polozkaceniku_kod"))
            conn.execute(text("CREATE INDEX ix_polozkaceniku_kod ON polozkaceniku (kod)"))
        conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ux_polozkaceniku_katalog_kod"
                          " ON polozkaceniku (katalog_id, kod)"))
    return True


def get_session() -> Iterator[Session]:
    with Session(engine) as session:
        yield session
