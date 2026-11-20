"""Automatické zálohy databáze (#76).

- **Denní záloha** na serveru do `data/backups` (`denni-…db`), uchovává se posledních `DENNICH` záloh.
- **Týdenní záloha** do složky zvolené v Nastavení (sdílený disk), uchovávají se poslední `TYDENNICH`.
- **Ruční záloha** tlačítkem „Zálohovat teď“ (`rucni-…db`), maže se jen ručně.

Záloha vzniká přes SQLite backup API (bezpečné i za běhu aplikace), nejdřív do dočasného souboru,
po kontrole `integrity_check` se přejmenuje. Uchovávání maže jen soubory s vlastní předponou a názvem
databáze, takže zálohy před aktualizací ani cizí soubory ve sdílené složce nikdy nesmaže.

Plánovač běží ve vlákně aplikace a každých `INTERVAL` sekund zkontroluje, jestli je záloha potřeba.
Vypíná se proměnnou prostředí `AUTOSERVIS_AUTOZALOHY=0`.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from sqlmodel import Session

from app import config
from app.models import Nastaveni
from app.services import ChybaValidace

ZALOHY = config.DATA_DIR / "backups"
STAV = "zalohy.json"           # v adresáři záloh
KLIC_SLOZKY = "zaloha_slozka"  # tabulka Nastaveni
DENNICH = 14
TYDENNICH = 3
DEN = timedelta(hours=24)
TYDEN = timedelta(days=7)
INTERVAL = 600
# Značka v cílové složce týdenních záloh. Bez ní se do složky nezapisuje – nepřipojený sdílený disk
# (prázdný přípojný bod na lokálním disku) tak záloha nikdy nezaplní místo lokálního disku.
ZNACKA = ".autoservis-cil-zaloh"
_zamek = threading.Lock()
_FORMAT_CASU = "%Y%m%d-%H%M%S"
_NAZEV = re.compile(r"^[A-Za-z0-9._-]+\.db$")


class ChybaZalohy(Exception):
    """Zálohu nejde provést – text je pro uživatele."""


@dataclass
class Soubor:
    nazev: str
    velikost: int
    cas: datetime
    druh: str  # denní / ruční / před aktualizací / týdenní / jiná

    @property
    def velikost_text(self) -> str:
        if self.velikost >= 1024 * 1024:
            return f"{self.velikost / 1024 / 1024:.1f} MB".replace(".", ",")
        return f"{max(1, round(self.velikost / 1024))} kB"


def zapnuto() -> bool:
    return os.environ.get("AUTOSERVIS_AUTOZALOHY", "1").strip().lower() not in ("0", "ne", "false", "vypnuto")


def _jmeno_db(db_path: Path) -> str:
    """Název databáze do jména zálohy – odliší zálohy různých instancí ve stejné sdílené složce."""
    return re.sub(r"[^A-Za-z0-9_-]+", "-", Path(db_path).stem) or "autoservis"


def _predpona(druh: str, db_path: Path) -> str:
    return f"{druh}-{_jmeno_db(db_path)}-" if druh != "tydenni" else f"autoservis-tydenni-{_jmeno_db(db_path)}-"


# --- samotná záloha ---------------------------------------------------------------------------

def _zkontroluj(soubor: Path) -> None:
    spojeni = sqlite3.connect(f"file:{soubor}?mode=ro", uri=True)
    try:
        vysledek = spojeni.execute("PRAGMA integrity_check").fetchone()
    finally:
        spojeni.close()
    if not vysledek or vysledek[0] != "ok":
        raise ChybaZalohy(f"Kontrola zálohy selhala: {vysledek[0] if vysledek else 'bez odpovědi'}.")


def vytvor(db_path: Path, slozka: Path, predpona: str, ted: datetime | None = None) -> Path:
    """Konzistentní kopie databáze `db_path` do `slozka/<predpona><čas>.db`."""
    db_path, slozka = Path(db_path), Path(slozka)
    if not db_path.exists():
        raise ChybaZalohy("Databáze neexistuje, není co zálohovat.")
    slozka.mkdir(parents=True, exist_ok=True)
    cil = slozka / f"{predpona}{(ted or datetime.now()).strftime(_FORMAT_CASU)}.db"
    docasny = cil.with_suffix(".db.tmp")
    try:
        zdroj = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        kopie = sqlite3.connect(docasny)
        try:
            zdroj.backup(kopie)
        finally:
            kopie.close()
            zdroj.close()
        _zkontroluj(docasny)
        os.chmod(docasny, 0o600)
        os.replace(docasny, cil)
    except sqlite3.Error as e:
        raise ChybaZalohy(f"Záloha databáze selhala: {e}") from e
    finally:
        docasny.unlink(missing_ok=True)
    return cil


def _zkopiruj_do(soubor: Path, slozka: Path, nazev: str) -> Path:
    """Kopie hotové zálohy do jiné složky (sdílený disk) – přes dočasný název, ať tam nezůstane půlka."""
    cil = slozka / nazev
    docasny = slozka / (nazev + ".tmp")
    try:
        shutil.copyfile(soubor, docasny)
        os.replace(docasny, cil)
    except OSError as e:
        docasny.unlink(missing_ok=True)
        raise ChybaZalohy(f"Zálohu se nepodařilo uložit do složky {slozka}: {e.strerror or e}") from e
    return cil


def _cas_ze_jmena(soubor: Path, predpona: str) -> datetime | None:
    try:
        return datetime.strptime(soubor.name[len(predpona):-3], _FORMAT_CASU)
    except ValueError:
        return None


def _zalohy_s_predponou(slozka: Path, predpona: str) -> list[Path]:
    """Zálohy se stejnou předponou od nejnovější."""
    try:
        soubory = [s for s in Path(slozka).glob(f"{predpona}*.db") if _cas_ze_jmena(s, predpona)]
    except OSError:
        return []
    return sorted(soubory, key=lambda s: _cas_ze_jmena(s, predpona), reverse=True)


def promaz(slozka: Path, predpona: str, ponechat: int) -> list[str]:
    smazane = []
    for stara in _zalohy_s_predponou(slozka, predpona)[ponechat:]:
        stara.unlink(missing_ok=True)
        smazane.append(stara.name)
    return smazane


# --- složka pro týdenní zálohy ----------------------------------------------------------------

def slozka(session: Session) -> str:
    zaznam = session.get(Nastaveni, KLIC_SLOZKY)
    return zaznam.hodnota if zaznam else ""


def over_slozku(cesta: str) -> Path:
    """Složka musí existovat a jít do ní zapisovat (zkušební soubor se hned smaže)."""
    text = (cesta or "").strip()
    if not text:
        raise ChybaValidace("Zadejte složku pro týdenní zálohy.", KLIC_SLOZKY)
    p = Path(text).expanduser()
    if not p.is_absolute():
        raise ChybaValidace("Zadejte celou cestu ke složce na serveru, např. /mnt/zalohy/autoservis.", KLIC_SLOZKY)
    if not p.is_dir():
        raise ChybaValidace(f"Složka {p} na serveru neexistuje (je sdílený disk připojený?).", KLIC_SLOZKY)
    if not (p / ZNACKA).is_file():
        raise ChybaValidace(f"Ve složce {p} chybí značka {ZNACKA} – sdílený disk není připojený, nebo složka "
                            "ještě není pro zálohy připravená (značku vytvoří správce serveru).", KLIC_SLOZKY)
    zkouska = p / ".autoservis-zkouska-zapisu"
    try:
        zkouska.write_bytes(b"ok")
        zkouska.unlink()
    except OSError as e:
        raise ChybaValidace(f"Do složky {p} nejde zapisovat: {e.strerror or e}.", KLIC_SLOZKY) from e
    return p


def uloz_slozku(session: Session, cesta: str) -> str:
    """Prázdná cesta týdenní zálohy vypne."""
    text = (cesta or "").strip()
    if text:
        text = str(over_slozku(text))
    zaznam = session.get(Nastaveni, KLIC_SLOZKY) or Nastaveni(klic=KLIC_SLOZKY)
    zaznam.hodnota = text
    session.add(zaznam)
    session.commit()
    return text


# --- záznam o posledních zálohách -------------------------------------------------------------

def nacti_stav(zalohy: Path | None = None) -> dict:
    zalohy = Path(zalohy or ZALOHY)
    try:
        return json.loads((Path(zalohy) / STAV).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _uloz_stav(zalohy: Path, druh: str, **udaje) -> None:
    zalohy = Path(zalohy)
    zalohy.mkdir(parents=True, exist_ok=True)
    stav = nacti_stav(zalohy)
    stav[druh] = {**stav.get(druh, {}), **udaje, "cas": datetime.now().isoformat(timespec="seconds")}
    soubor = zalohy / STAV
    docasny = soubor.with_suffix(".tmp")
    docasny.write_text(json.dumps(stav, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(docasny, soubor)


# --- denní, týdenní a ruční záloha ------------------------------------------------------------

def denni(db_path: Path = None, zalohy: Path | None = None, ted: datetime | None = None) -> Path:
    zalohy = Path(zalohy or ZALOHY)
    db_path = Path(db_path or config.DB_PATH)
    predpona = _predpona("denni", db_path)
    try:
        cil = vytvor(db_path, zalohy, predpona, ted)
        promaz(zalohy, predpona, DENNICH)
    except ChybaZalohy as e:
        _uloz_stav(zalohy, "denni", chyba=str(e))
        raise
    _uloz_stav(zalohy, "denni", soubor=cil.name, chyba="", uspech=(ted or datetime.now()).isoformat(timespec="seconds"))
    return cil


def tydenni(cilova_slozka: str, db_path: Path = None, zalohy: Path | None = None, ted: datetime | None = None) -> Path:
    """Záloha vznikne nejdřív na serveru (ověřená), pak se zkopíruje do zvolené složky."""
    zalohy = Path(zalohy or ZALOHY)
    db_path = Path(db_path or config.DB_PATH)
    predpona = _predpona("tydenni", db_path)
    try:
        if not cilova_slozka:
            raise ChybaZalohy("Složka pro týdenní zálohy není nastavená.")
        cil_slozka = Path(cilova_slozka)
        if not cil_slozka.is_dir():
            raise ChybaZalohy(f"Složka {cil_slozka} není dostupná (je sdílený disk připojený?).")
        if not (cil_slozka / ZNACKA).is_file():
            raise ChybaZalohy(f"Ve složce {cil_slozka} chybí značka {ZNACKA} – sdílený disk není připojený, "
                              "záloha se do složky neuložila.")
        docasne = Path(zalohy) / ".tydenni"
        mistni = vytvor(db_path, docasne, predpona, ted)
        try:
            cil = _zkopiruj_do(mistni, cil_slozka, mistni.name)
        finally:
            mistni.unlink(missing_ok=True)
        promaz(cil_slozka, predpona, TYDENNICH)
    except ChybaZalohy as e:
        _uloz_stav(zalohy, "tydenni", chyba=str(e))
        raise
    _uloz_stav(zalohy, "tydenni", soubor=str(cil), chyba="", uspech=(ted or datetime.now()).isoformat(timespec="seconds"))
    return cil


def rucni(db_path: Path = None, zalohy: Path | None = None) -> Path:
    zalohy = Path(zalohy or ZALOHY)
    db_path = Path(db_path or config.DB_PATH)
    with _zamek:
        cil = vytvor(db_path, zalohy, _predpona("rucni", db_path))
    _uloz_stav(zalohy, "rucni", soubor=cil.name, chyba="", uspech=datetime.now().isoformat(timespec="seconds"))
    return cil


def _posledni_uspech(zalohy: Path, druh: str) -> datetime | None:
    hodnota = nacti_stav(zalohy).get(druh, {}).get("uspech")
    try:
        return datetime.fromisoformat(hodnota) if hodnota else None
    except ValueError:
        return None


def naplanovane(cilova_slozka: str, db_path: Path = None, zalohy: Path | None = None,
                ted: datetime | None = None) -> list[str]:
    """Udělá denní / týdenní zálohu, pokud je načase. Chyby se zapíšou do stavu, nevyhazují se."""
    zalohy = Path(zalohy or ZALOHY)
    ted = ted or datetime.now()
    hotovo = []
    with _zamek:
        posledni = _posledni_uspech(zalohy, "denni")
        if posledni is None or ted - posledni >= DEN:
            try:
                hotovo.append(denni(db_path, zalohy, ted).name)
            except ChybaZalohy:
                pass
        if cilova_slozka:
            posledni = _posledni_uspech(zalohy, "tydenni")
            if posledni is None or ted - posledni >= TYDEN:
                try:
                    hotovo.append(tydenni(cilova_slozka, db_path, zalohy, ted).name)
                except ChybaZalohy:
                    pass
    return hotovo


def tydenni_ted(cilova_slozka: str, db_path: Path = None, zalohy: Path | None = None) -> Path:
    zalohy = Path(zalohy or ZALOHY)
    with _zamek:
        return tydenni(cilova_slozka, db_path, zalohy)


# --- přehled pro Nastavení a stažení ----------------------------------------------------------

def _druh(nazev: str) -> str:
    for predpona, druh in (("denni-", "denní"), ("rucni-", "ruční"), ("pred-aktualizaci-", "před aktualizací"),
                           ("autoservis-tydenni-", "týdenní")):
        if nazev.startswith(predpona):
            return druh
    return "jiná"


def seznam(slozka_: Path) -> list[Soubor]:
    """Soubory záloh (*.db) ve složce od nejnovější."""
    vysledek = []
    try:
        for s in Path(slozka_).glob("*.db"):
            if s.is_file():
                st = s.stat()
                vysledek.append(Soubor(s.name, st.st_size, datetime.fromtimestamp(st.st_mtime), _druh(s.name)))
    except OSError:
        return []
    return sorted(vysledek, key=lambda s: s.cas, reverse=True)


def soubor_ke_stazeni(nazev: str, zalohy: Path | None = None) -> Path:
    """Jen soubor přímo v adresáři záloh – žádné cesty ven."""
    zalohy = Path(zalohy or ZALOHY)
    if not _NAZEV.match(nazev or "") or nazev.startswith("."):
        raise ChybaZalohy("Neplatný název zálohy.")
    soubor = Path(zalohy) / nazev
    if not soubor.is_file():
        raise ChybaZalohy("Záloha neexistuje.")
    return soubor


# --- plánovač ---------------------------------------------------------------------------------

_stop = threading.Event()
_vlakno: threading.Thread | None = None


def _smycka(nacti_slozku, interval: float) -> None:
    while not _stop.is_set():
        try:
            naplanovane(nacti_slozku())
        except Exception:  # plánovač nesmí shodit aplikaci; chyby záloh jsou ve stavu
            pass
        _stop.wait(interval)


def spust_planovac(nacti_slozku, interval: float = INTERVAL) -> bool:
    global _vlakno
    if not zapnuto() or (_vlakno and _vlakno.is_alive()):
        return False
    _stop.clear()
    _vlakno = threading.Thread(target=_smycka, args=(nacti_slozku, interval), name="zalohy", daemon=True)
    _vlakno.start()
    return True


def zastav_planovac() -> None:
    _stop.set()
    if _vlakno:
        _vlakno.join(timeout=5)
