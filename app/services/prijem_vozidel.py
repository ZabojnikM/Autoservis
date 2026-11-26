"""Příjem vozidel (#51, #216) – příjmy, které zapisuje Přijímací technik (OpenBot) přes MCP.

Příjmy jsou ve vlastní tabulce `PrijemVozidla`; drží se posledních `LIMIT` (starší se při zápisu smažou).
Fotky sem nepatří – zůstávají u technika. Záložka Příjem vozidel jen čte a páruje příjem s databází vozidel.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from urllib.parse import quote

from sqlmodel import Session, col, select

from app.models import PrijemVozidla, Vozidlo, Zakazka
from app.services import ChybaValidace, NenalezenoError, cisty_text, vozidla

LIMIT = 30


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


def _navsteva(radek: PrijemVozidla) -> Navsteva:
    try:
        technicke = json.loads(radek.technicke or "{}")
    except ValueError:
        technicke = {}
    try:
        nejiste = json.loads(radek.nejiste or "[]")
    except ValueError:
        nejiste = []
    technicke = technicke if isinstance(technicke, dict) else {}
    return Navsteva(
        id=radek.id, created_at=radek.vytvoreno, updated_at=radek.upraveno, revision=str(radek.revize),
        spz=radek.spz, vin=radek.vin, km=radek.km, technicke=_ploche(technicke), nejiste=_nejiste(nejiste),
        registr=technicke,
    )


def nacti(session: Session) -> Prijmy:
    """Příjmy od nejnověji založeného."""
    radky = list(session.exec(select(PrijemVozidla).order_by(col(PrijemVozidla.vytvoreno).desc())))
    navstevy = [_navsteva(r) for r in radky]
    posledni = max((r.upraveno for r in radky), default=None)
    return Prijmy(version=None, updated_at=posledni, navstevy=navstevy)


def najdi(session: Session, prijem_id: str) -> Navsteva | None:
    radek = session.get(PrijemVozidla, prijem_id)
    return _navsteva(radek) if radek else None


# ---------------------------------------------------------------- zápis přes MCP (#216)

POLE = ("id", "spz", "vin", "km", "technicke", "nejiste")


def _km(hodnota) -> int | None:
    if hodnota in (None, ""):
        return None
    try:
        km = int(str(hodnota).replace(" ", ""))
    except ValueError:
        raise ChybaValidace("Stav tachometru (km) musí být celé číslo.", "km") from None
    if km < 0:
        raise ChybaValidace("Stav tachometru (km) nemůže být záporný.", "km")
    return km


def uloz(session: Session, data: dict | None) -> PrijemVozidla:
    """Nový příjem, nebo oprava existujícího podle `id` (mění jen zadaná pole). Pak se smažou příjmy nad limit."""
    data = dict(data or {})
    nezname = sorted(k for k in data if k not in POLE)
    if nezname:
        raise ChybaValidace(f"Neznámá pole: {', '.join(nezname)}. Povolená: {', '.join(POLE)}.")
    prijem_id = cisty_text(data.pop("id", None))
    radek = session.get(PrijemVozidla, prijem_id) if prijem_id else None
    if radek is None:
        radek = PrijemVozidla(id=prijem_id or str(uuid.uuid4()), revize=0)
    if "spz" in data:
        radek.spz = vozidla.normalizuj_spz(str(data["spz"] or "")) or None
    if "vin" in data:
        radek.vin = vozidla.normalizuj_vin(str(data["vin"] or "")) or None
    if "km" in data:
        radek.km = _km(data["km"])
    if "technicke" in data:
        if not isinstance(data["technicke"] or {}, dict):
            raise ChybaValidace("technicke musí být objekt (technické údaje ve formátu Registru vozidel).")
        radek.technicke = json.dumps(data["technicke"] or {}, ensure_ascii=False)
    if "nejiste" in data:
        nejiste = data["nejiste"] or []
        if not isinstance(nejiste, list) or not all(isinstance(x, str) for x in nejiste):
            raise ChybaValidace("nejiste musí být seznam názvů polí, např. [\"vin\", \"km\"].")
        radek.nejiste = json.dumps(nejiste, ensure_ascii=False)
    if not radek.spz and not radek.vin:
        raise ChybaValidace("Příjem potřebuje SPZ nebo VIN.", "spz")
    radek.revize += 1
    radek.upraveno = datetime.now()
    session.add(radek)
    session.commit()
    _orizni(session)
    session.refresh(radek)
    return radek


def _orizni(session: Session) -> int:
    """Smaže příjmy nad limit (nejstarší podle založení). Vrací počet smazaných."""
    stare = list(session.exec(select(PrijemVozidla).order_by(col(PrijemVozidla.vytvoreno).desc()).offset(LIMIT)))
    for radek in stare:
        session.delete(radek)
    if stare:
        session.commit()
    return len(stare)


def smaz(session: Session, prijem_id: str) -> None:
    radek = session.get(PrijemVozidla, prijem_id)
    if radek is None:
        raise NenalezenoError(f"Příjem {prijem_id} neexistuje.")
    session.delete(radek)
    session.commit()


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
