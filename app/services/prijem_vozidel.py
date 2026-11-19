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
from urllib.parse import quote

from sqlmodel import Session

from app import config
from app.models import Vozidlo, Zakazka
from app.services import vozidla

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
    registr: dict = field(default_factory=dict)  # technical_data tak, jak přišla (formát Registru vozidel)

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
        registr=technicke if isinstance(technicke, dict) else {},
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


# ---------------------------------------------------------------- návštěva × naše databáze vozidel

@dataclass
class Shoda:
    """Je vozidlo z příjmu v databázi?

    stav: „v_databazi“ (našlo se podle SPZ nebo VIN), „neni“, „konflikt“ (SPZ patří jednomu vozidlu
    a VIN jinému – chyba v databázi nebo v příjmu, nic se nenabízí automaticky).
    `upozorneni` = nesoulad u nalezeného vozidla (jiný VIN / jiná SPZ v databázi), akce zůstává.
    """
    navsteva: Navsteva
    stav: str
    vozidlo: Vozidlo | None = None
    podle_spz: Vozidlo | None = None
    podle_vin: Vozidlo | None = None
    otevrena: Zakazka | None = None
    upozorneni: str | None = None

    @property
    def akce(self) -> tuple[str, str, bool] | None:
        """(text tlačítka, adresa, otevřít v okně) – hlavní akce řádku; konflikt = žádná."""
        if self.stav == "neni":
            return "Založit vozidlo", f"/vozidla/nove?prijem={quote(self.navsteva.id, safe='')}", True
        if self.stav != "v_databazi":
            return None
        if self.otevrena:
            return "Otevřít zakázku", f"/zakazky/{self.otevrena.id}", False
        km = f"&tachometr={self.navsteva.km}" if self.navsteva.km is not None else ""
        return "Nová zakázka", f"/zakazky/nova?vozidlo_id={self.vozidlo.id}{km}", True


def _oznaceni(vozidlo: Vozidlo) -> str:
    return " ".join(x for x in (vozidlo.spz, vozidlo.popis if (vozidlo.znacka or vozidlo.model) else "") if x)


def sparuj(session: Session, navsteva: Navsteva) -> Shoda:
    """Najde vozidlo návštěvy v databázi podle SPZ i VIN a zkontroluje, že obojí ukazuje na stejné vozidlo."""
    spz = vozidla.normalizuj_spz(navsteva.spz)
    vin = vozidla.normalizuj_vin(navsteva.vin)
    podle_spz = vozidla.najdi_podle_spz(session, spz) if spz else None
    podle_vin = vozidla.najdi_podle_vin(session, vin) if vin else None
    if podle_spz and podle_vin and podle_spz.id != podle_vin.id:
        return Shoda(navsteva, "konflikt", podle_spz=podle_spz, podle_vin=podle_vin, upozorneni=(
            f"SPZ patří v databázi vozidlu {_oznaceni(podle_spz)}, VIN vozidlu {_oznaceni(podle_vin)}. "
            "Ověřte údaje a opravte záznam v databázi."))
    vozidlo = podle_spz or podle_vin
    if vozidlo is None:
        return Shoda(navsteva, "neni")
    upozorneni = None
    if not podle_vin and vin and vozidlo.vin and vozidla.normalizuj_vin(vozidlo.vin) != vin:
        upozorneni = f"Nalezeno podle SPZ, ale v databázi má vozidlo jiný VIN: {vozidlo.vin}."
    elif not podle_spz and spz and vozidlo.spz != spz:
        upozorneni = f"Nalezeno podle VIN, ale v databázi má vozidlo jinou SPZ: {vozidlo.spz}."
    otevrena = next((z for z in vozidla.historie(session, vozidlo.id) if z.je_otevrena), None)
    return Shoda(navsteva, "v_databazi", vozidlo=vozidlo, podle_spz=podle_spz, podle_vin=podle_vin,
                 otevrena=otevrena, upozorneni=upozorneni)
