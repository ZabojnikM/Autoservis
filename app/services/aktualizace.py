"""Aktualizace aplikace z gitu (sekce Aktualizace v Nastavení).

Aplikace musí běžet z git klonu repozitáře. Instalace se zapíná proměnnou prostředí
AUTOSERVIS_AKTUALIZACE na serveru:
  vydani – poslední vydání (tag vX.Y.Z), pro ostrý provoz
  main   – poslední stav větve main, pro testovací server
Bez ní stránka jen ukáže verzi – na vývojovém počítači se tak nic nepřepne.

Instalace: git fetch → záloha databáze → git checkout --detach <cíl> → při změně
requirements.txt pip install (při chybě návrat na původní verzi) → záznam pro návrat
→ restart. Restart umí jen aplikace pod správcem služeb (systemd s Restart=always):
aplikace se ukončí a systemd ji spustí znovu už s novým kódem.
"""
from __future__ import annotations

import json
import os
import re
import signal
import sqlite3
import subprocess
import sys
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from app import config

KANALY = {"vydani": "poslední vydání (tag vX.Y.Z)", "main": "větev main"}
ZALOHY = config.DATA_DIR / "backups"
ZAZNAM = "aktualizace.json"  # v adresáři záloh (data/backups je mimo git)
_zamek = threading.Lock()


class ChybaAktualizace(Exception):
    """Aktualizaci nejde provést – text je pro uživatele."""


@dataclass
class Stav:
    kanal: str | None
    git: bool
    commit: str = ""          # zkrácený HEAD (kód na disku)
    popis: str = ""           # git describe, např. v0.2.0-5-gabc1234
    neulozene_zmeny: list[str] = field(default_factory=list)
    predchozi: dict | None = None   # záznam poslední aktualizace (pro návrat)
    zkontrolovano: bool = False
    cil: str = ""             # tag nebo origin/main
    cil_commit: str = ""
    nove_commity: list[tuple[str, str]] = field(default_factory=list)


def kanal() -> str | None:
    hodnota = os.environ.get("AUTOSERVIS_AKTUALIZACE", "").strip().lower()
    return hodnota if hodnota in KANALY else None


def _git(repo: Path, *args: str, timeout: int = 60) -> str:
    try:
        r = subprocess.run(
            ["git", *args], cwd=repo, capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout, env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
        )
    except FileNotFoundError:
        raise ChybaAktualizace("Na serveru není nainstalovaný git.") from None
    except subprocess.TimeoutExpired:
        raise ChybaAktualizace(f"git {args[0]}: vypršel časový limit (je server připojený k internetu?).") from None
    if r.returncode != 0:
        raise ChybaAktualizace(f"git {args[0]} selhal: {(r.stderr or r.stdout).strip()[-500:]}")
    return r.stdout.strip()


def je_git_klon(repo: Path) -> bool:
    return (repo / ".git").exists()


def spusteny_commit(repo: Path = config.BASE_DIR) -> str:
    """Commit, se kterým tento proces startoval (po instalaci se liší od HEAD až do restartu)."""
    return _SPUSTENY.get(str(repo), "")


def _zjisti_commit(repo: Path) -> str:
    try:
        return _git(repo, "rev-parse", "--short", "HEAD") if je_git_klon(repo) else ""
    except ChybaAktualizace:
        return ""


_SPUSTENY = {str(config.BASE_DIR): _zjisti_commit(config.BASE_DIR)}


def _cil(repo: Path, kanal_: str) -> str:
    if kanal_ == "main":
        return "origin/main"
    tagy = [t for t in _git(repo, "tag", "-l", "v*", "--sort=-v:refname").splitlines()
            if re.fullmatch(r"v\d+(\.\d+)*", t)]
    if not tagy:
        raise ChybaAktualizace("V repozitáři zatím není žádné vydání (tag vX.Y.Z).")
    return tagy[0]


def stav(repo: Path = config.BASE_DIR, zkontrolovat: bool = False, zalohy: Path = ZALOHY) -> Stav:
    """Stav kódu na disku; `zkontrolovat=True` navíc stáhne z GitHubu, co je nového (git fetch)."""
    s = Stav(kanal=kanal(), git=je_git_klon(repo))
    if not s.git:
        return s
    s.commit = _git(repo, "rev-parse", "--short", "HEAD")
    s.popis = _git(repo, "describe", "--tags", "--always")
    s.neulozene_zmeny = [r.strip() for r in _git(repo, "status", "--porcelain", "--untracked-files=no").splitlines()
                         if r.strip()]
    s.predchozi = nacti_zaznam(zalohy)
    if zkontrolovat:
        _git(repo, "fetch", "--tags", "--prune", "--force", "origin", timeout=120)
        s.cil = _cil(repo, s.kanal or "vydani")
        s.cil_commit = _git(repo, "rev-parse", "--short", f"{s.cil}^{{commit}}")
        log = _git(repo, "log", "--format=%h%x09%s", "-n", "50", f"HEAD..{s.cil}")
        s.nove_commity = [tuple(r.split("\t", 1)) for r in log.splitlines() if "\t" in r]
        s.zkontrolovano = True
    return s


def zalohuj_db(db_path: Path, zalohy: Path, oznaceni: str) -> Path | None:
    """Kopie databáze přes SQLite backup (bezpečné i za běhu aplikace)."""
    db_path = Path(db_path)
    if not db_path.exists():
        return None
    zalohy.mkdir(parents=True, exist_ok=True)
    cil = zalohy / f"pred-aktualizaci-{datetime.now():%Y%m%d-%H%M%S}-{oznaceni}.db"
    zdroj, kopie = sqlite3.connect(db_path), sqlite3.connect(cil)
    try:
        zdroj.backup(kopie)
    finally:
        kopie.close()
        zdroj.close()
    return cil


def nacti_zaznam(zalohy: Path = ZALOHY) -> dict | None:
    try:
        return json.loads((zalohy / ZAZNAM).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _uloz_zaznam(zalohy: Path, zaznam: dict | None) -> None:
    soubor = zalohy / ZAZNAM
    if zaznam is None:
        soubor.unlink(missing_ok=True)
        return
    zalohy.mkdir(parents=True, exist_ok=True)
    soubor.write_text(json.dumps(zaznam, ensure_ascii=False, indent=2), encoding="utf-8")


def pip_install(repo: Path) -> None:
    try:
        r = subprocess.run([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"], cwd=repo,
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900)
    except subprocess.TimeoutExpired:
        raise ChybaAktualizace("Instalace závislostí (pip) nestihla doběhnout.") from None
    if r.returncode != 0:
        raise ChybaAktualizace(f"Instalace závislostí (pip) selhala: {(r.stderr or r.stdout).strip()[-500:]}")


def _prepni(repo: Path, z: str, na: str, pip) -> bool:
    """Přepne kód z revize `z` na `na`; při změně requirements.txt spustí pip, a když selže, vrátí `z`.
    Vrací, jestli se instalovaly závislosti."""
    zavislosti = bool(_git(repo, "diff", "--name-only", z, na, "--", "requirements.txt"))
    _git(repo, "checkout", "--detach", "-q", na)
    if zavislosti:
        try:
            pip(repo)
        except ChybaAktualizace:
            _git(repo, "checkout", "--detach", "-q", z)
            raise
    return zavislosti


def _kontrola_pred_zmenou(s: Stav) -> None:
    if not s.kanal:
        raise ChybaAktualizace("Aktualizace z aplikace je vypnutá (proměnná AUTOSERVIS_AKTUALIZACE).")
    if not s.git:
        raise ChybaAktualizace("Aplikace neběží z git klonu.")
    if s.neulozene_zmeny:
        raise ChybaAktualizace("Soubory aplikace jsou na serveru ručně upravené a aktualizace by je přepsala: "
                               + ", ".join(s.neulozene_zmeny[:5]))


def nainstaluj(repo: Path = config.BASE_DIR, db_path: Path = config.DB_PATH, zalohy: Path = ZALOHY,
               pip=pip_install) -> dict:
    if not _zamek.acquire(blocking=False):
        raise ChybaAktualizace("Aktualizace už probíhá.")
    try:
        s = stav(repo, zkontrolovat=bool(kanal()), zalohy=zalohy)
        _kontrola_pred_zmenou(s)
        if not s.nove_commity:
            raise ChybaAktualizace("Aplikace je aktuální, není co instalovat.")
        stary = _git(repo, "rev-parse", "HEAD")
        novy = _git(repo, "rev-parse", f"{s.cil}^{{commit}}")
        zaloha = zalohuj_db(db_path, zalohy, stary[:7])
        zavislosti = _prepni(repo, stary, novy, pip)
        zaznam = {"predchozi": stary, "nova": novy, "cil": s.cil, "zavislosti": zavislosti,
                  "zaloha_db": str(zaloha or ""), "cas": datetime.now().isoformat(timespec="seconds")}
        _uloz_zaznam(zalohy, zaznam)
        return zaznam
    finally:
        _zamek.release()


def vrat(repo: Path = config.BASE_DIR, zalohy: Path = ZALOHY, pip=pip_install) -> dict:
    """Vrátí kód na verzi před poslední aktualizací. Databáze zůstává (záloha je v záznamu)."""
    if not _zamek.acquire(blocking=False):
        raise ChybaAktualizace("Aktualizace už probíhá.")
    try:
        s = stav(repo, zalohy=zalohy)
        _kontrola_pred_zmenou(s)
        if not s.predchozi:
            raise ChybaAktualizace("Není záznam o předchozí aktualizaci.")
        _prepni(repo, _git(repo, "rev-parse", "HEAD"), s.predchozi["predchozi"], pip)
        _uloz_zaznam(zalohy, None)
        return s.predchozi
    finally:
        _zamek.release()


def restart_mozny() -> bool:
    """Běží pod systemd (nastavuje INVOCATION_ID), nebo je restart povolen ručně (AUTOSERVIS_RESTART=1)."""
    return bool(os.environ.get("INVOCATION_ID")) or os.environ.get("AUTOSERVIS_RESTART") == "1"


def naplanuj_restart(za: float = 1.5) -> None:
    """Za chvíli ukončí aplikaci (odpověď prohlížeči ještě odejde); správce služeb ji spustí znovu."""
    threading.Timer(za, lambda: os.kill(os.getpid(), signal.SIGTERM)).start()
