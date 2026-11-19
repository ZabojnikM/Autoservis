"""Příjem vozidel – jen čtení návštěv, které zpracoval Přijímací technik (OpenBot), z jeho visits.json (#51).

Zdroj je JSON soubor formátu `autoservis.visits.v1` na stejném počítači (cesta v konfiguraci nasazení,
`AUTOSERVIS_PRIJEM_JSON`). OpenBot ho aktualizuje atomickým nahrazením, proto se soubor otevírá znovu
při každém načtení (nová návštěva je vidět po obnovení stránky, bez restartu). Nic se nezapisuje,
soubor se nevystavuje jako statický. `sources`, `events` a fotky se v první verzi nezobrazují.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from app import config

SCHEMA = "autoservis.visits.v1"


class PrijemNedostupny(Exception):
    """Soubor nejde přečíst nebo nemá očekávaný formát – stránka ukáže „dočasně nedostupný“."""


def _cas(hodnota) -> datetime | None:
    """ISO čas ze zdroje (např. 2026-11-19T08:15:00Z) → místní čas; neplatný / chybějící = None."""
    if not isinstance(hodnota, str) or not hodnota.strip():
        return None
    try:
        cas = datetime.fromisoformat(hodnota.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return cas.astimezone().replace(tzinfo=None) if cas.tzinfo else cas


def _text(hodnota) -> str | None:
    if hodnota is None:
        return None
    text = str(hodnota).strip()
    return text or None


def _ploche(data: dict, predpona: str = "") -> list[tuple[str, str]]:
    """Technické údaje jako dvojice (název, hodnota); vnořené slovníky jako „Motor.Vykon“."""
    vysledek = []
    for klic, hodnota in data.items():
        nazev = f"{predpona}{klic}"
        if isinstance(hodnota, dict):
            vysledek += _ploche(hodnota, nazev + ".")
        elif isinstance(hodnota, list):
            text = ", ".join(str(x) for x in hodnota if _text(x))
            vysledek.append((nazev, text))
        else:
            vysledek.append((nazev, _text(hodnota) or ""))
    return vysledek


def _nejiste(pole) -> set[str]:
    """`uncertain_fields` → množina názvů bez předpon („vehicle.vin“ i „vin“ → „vin“)."""
    vysledek = set()
    for nazev in pole if isinstance(pole, list) else []:
        if not isinstance(nazev, str):
            continue
        nazev = nazev.strip()
        for predpona in ("vehicle.", "technical_data."):
            if nazev.startswith(predpona):
                nazev = nazev[len(predpona):]
        vysledek.add(nazev.lower())
    return vysledek


@dataclass
class Navsteva:
    id: str
    created_at: datetime | None
    updated_at: datetime | None
    revision: str | None
    spz: str | None
    vin: str | None
    km: int | None
    technicke: list[tuple[str, str]] = field(default_factory=list)
    nejiste: set[str] = field(default_factory=set)

    def _technicky(self, *nazvy: str) -> str | None:
        for nazev, hodnota in self.technicke:
            if nazev in nazvy and hodnota:
                return hodnota
        return None

    @property
    def znacka(self) -> str | None:
        return self._technicky("TovarniZnacka", "Znacka")

    @property
    def model(self) -> str | None:
        return self._technicky("ObchodniOznaceni", "Model", "Typ")

    @property
    def popis(self) -> str | None:
        return " ".join(x for x in (self.znacka, self.model) if x) or None

    def je_nejiste(self, nazev: str) -> bool:
        return nazev.lower() in self.nejiste


@dataclass
class Prijmy:
    version: str | None
    updated_at: datetime | None
    navstevy: list[Navsteva]


def _navsteva(data) -> Navsteva:
    if not isinstance(data, dict) or not _text(data.get("id")):
        raise PrijemNedostupny("Návštěva bez id.")
    vozidlo = data.get("vehicle") if isinstance(data.get("vehicle"), dict) else {}
    km = vozidlo.get("odometer_km")
    try:
        km = int(km) if km not in (None, "") else None
    except (TypeError, ValueError):
        km = None
    technicke = vozidlo.get("technical_data")
    return Navsteva(
        id=_text(data["id"]), created_at=_cas(data.get("created_at")), updated_at=_cas(data.get("updated_at")),
        revision=_text(data.get("revision")), spz=_text(vozidlo.get("spz")), vin=_text(vozidlo.get("vin")), km=km,
        technicke=_ploche(technicke) if isinstance(technicke, dict) else [],
        nejiste=_nejiste(vozidlo.get("uncertain_fields")),
    )


def nacti(cesta: str | Path | None = None) -> Prijmy:
    """Načte a zkontroluje soubor (vždy znovu otevřený). Návštěvy od nejnověji založené."""
    cesta = Path(cesta or config.PRIJEM_JSON)
    try:
        with open(cesta, encoding="utf-8") as soubor:
            data = json.load(soubor)
    except (OSError, ValueError) as e:
        raise PrijemNedostupny(f"Soubor příjmů nejde přečíst: {e.__class__.__name__}") from e
    if not isinstance(data, dict) or data.get("schema") != SCHEMA or not isinstance(data.get("visits"), list):
        raise PrijemNedostupny("Neočekávaný formát souboru příjmů.")
    navstevy = [_navsteva(v) for v in data["visits"]]
    navstevy.sort(key=lambda n: n.created_at or datetime.min, reverse=True)
    return Prijmy(version=_text(data.get("version")), updated_at=_cas(data.get("updated_at")), navstevy=navstevy)
