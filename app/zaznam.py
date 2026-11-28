"""Záznam událostí aplikace (#225) – soubor `logs/autoservis.log` vedle databáze, s rotací.

Zapisuje se start a vypnutí, neošetřené chyby (s výpisem), zálohy a obnova, aktualizace a vrácení verze, migrace
databáze, výpadky Registru vozidel / ARES / LKQ, volání REST API a MCP (název klíče a nástroj, ne data), chybný PIN
a odmítnuté podvržené požadavky. **Nezapisují se osobní údaje** (jména, adresy, telefony, e-maily, IČO, SPZ, VIN),
obsah dokladů, klíče ani PIN – zprávy proto nesmí obsahovat hodnoty z formulářů. Z výpisů chyb SQLAlchemy se
odstraňují hodnoty parametrů dotazu.

Použití v kódu: `from app.zaznam import log` → `log.info(...)`, `log.warning(...)`, `log.exception(...)`.
Soubor nastaví `nastav()` při startu aplikace; bez něj (testy, příkazy) jdou jen varování na konzoli.
"""
from __future__ import annotations

import logging
import logging.handlers
import re
from collections import deque
from pathlib import Path

from app import config

log = logging.getLogger("autoservis")
log.setLevel(logging.INFO)
VELIKOST = 1_000_000   # 1 MB na soubor
SOUBORU = 10           # aktuální + 9 starších ≈ 10 MB celkem
_handler: logging.Handler | None = None
_PARAMETRY = re.compile(r"\[parameters: .*?\]\s*(?=\n|\(Background|$)", re.S)


class _Formatovac(logging.Formatter):
    def formatException(self, ei) -> str:  # noqa: N802 – název z logging
        return _PARAMETRY.sub("[parameters: vynecháno]", super().formatException(ei))

    def format(self, record) -> str:
        return _PARAMETRY.sub("[parameters: vynecháno]", super().format(record))


def soubor() -> Path:
    return Path(config.DB_PATH).resolve().parent / "logs" / "autoservis.log"


def nastav(cil: Path | None = None) -> Path:
    """Zapisovat záznam do souboru `cil` (výchozí `logs/autoservis.log` vedle databáze)."""
    global _handler
    cil = Path(cil or soubor())
    cil.parent.mkdir(parents=True, exist_ok=True)
    ukonci()
    _handler = logging.handlers.RotatingFileHandler(cil, maxBytes=VELIKOST, backupCount=SOUBORU - 1, encoding="utf-8")
    _handler.setFormatter(_Formatovac("%(asctime)s %(levelname)-7s %(name)s: %(message)s", "%Y-%m-%d %H:%M:%S"))
    log.addHandler(_handler)
    return cil


def ukonci() -> None:
    global _handler
    if _handler:
        log.removeHandler(_handler)
        _handler.close()
        _handler = None


def aktualni_soubor() -> Path:
    return Path(_handler.baseFilename) if isinstance(_handler, logging.FileHandler) else soubor()


def posledni(pocet: int = 200, jen_chyby: bool = False) -> list[str]:
    """Posledních `pocet` záznamů (od nejnovějšího). Víceřádkový záznam (výpis chyby) zůstane pohromadě."""
    cesta = aktualni_soubor()
    soubory = [cesta.with_name(f"{cesta.name}.1"), cesta]  # i předchozí soubor po rotaci
    zaznamy: deque[str] = deque(maxlen=5000)
    for s in soubory:
        try:
            radky = s.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for radek in radky:
            if re.match(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} ", radek) or not zaznamy:
                zaznamy.append(radek)
            else:
                zaznamy[-1] += "\n" + radek
    vysledek = [z for z in zaznamy if not jen_chyby or z[20:27].strip() in ("WARNING", "ERROR", "CRITICAL")]
    return list(reversed(vysledek))[:pocet]
