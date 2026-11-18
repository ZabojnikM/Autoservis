"""Řazení a stránkování seznamů (datových mřížek).

Seznam vrací `Stranka` – jednu dávku řádků + celkový počet. Řazení je klíč sloupce,
s pomlčkou na začátku sestupně (např. "-prijato"). Neznámý klíč = výchozí řazení.
"""
from dataclasses import dataclass
from typing import Any, Callable

from sqlalchemy import func
from sqlmodel import Session, select

VELIKOST_STRANKY = 100


@dataclass
class Stranka:
    polozky: list
    celkem: int
    od: int
    razeni: str  # platné řazení, např. "spz" nebo "-prijato"

    @property
    def do(self) -> int:
        return self.od + len(self.polozky)

    @property
    def dalsi(self) -> int | None:
        """Začátek další dávky, nebo None, když už je načteno vše."""
        return self.do if self.do < self.celkem else None


def rozloz_razeni(razeni: str | None, povolene, vychozi: str) -> tuple[str, bool]:
    """'-spz' → ('spz', True). Neznámý klíč → výchozí řazení."""
    razeni = (razeni or "").strip()
    klic, sestupne = razeni.lstrip("-"), razeni.startswith("-")
    if klic not in povolene:
        klic, sestupne = vychozi.lstrip("-"), vychozi.startswith("-")
    return klic, sestupne


def _cislo_od(od) -> int:
    try:
        return max(int(od or 0), 0)
    except (TypeError, ValueError):
        return 0


def strankuj_dotaz(session: Session, dotaz, sloupce: dict[str, list], razeni: str | None, vychozi: str,
                   od=0, limit: int = VELIKOST_STRANKY, doplnkove=()) -> Stranka:
    """Stránka z SQL dotazu (filtry už použité, bez order_by). `sloupce`: klíč → výrazy pro ORDER BY.
    `doplnkove`: výrazy pro stabilní pořadí stejných hodnot (např. id)."""
    klic, sestupne = rozloz_razeni(razeni, sloupce, vychozi)
    od = _cislo_od(od)
    celkem = session.exec(select(func.count()).select_from(dotaz.order_by(None).subquery())).one()
    poradi = [(v.desc() if sestupne else v.asc()).nulls_last() for v in sloupce[klic]]
    poradi += [(v.desc() if sestupne else v.asc()) for v in doplnkove]
    polozky = list(session.exec(dotaz.order_by(*poradi).offset(od).limit(limit)))
    return Stranka(polozky, celkem, od, ("-" if sestupne else "") + klic)


def strankuj_seznam(seznam: list, klice: dict[str, Callable[[Any], Any]], razeni: str | None, vychozi: str,
                    od=0, limit: int = VELIKOST_STRANKY) -> Stranka:
    """Stránka z hotového seznamu (pro hodnoty počítané v Pythonu, např. zbývá uhradit).
    Prázdné hodnoty jsou vždy na konci."""
    klic, sestupne = rozloz_razeni(razeni, klice, vychozi)
    od = _cislo_od(od)
    funkce = klice[klic]
    s_hodnotou = [x for x in seznam if funkce(x) is not None]
    bez_hodnoty = [x for x in seznam if funkce(x) is None]
    serazeno = sorted(s_hodnotou, key=funkce, reverse=sestupne) + bez_hodnoty
    return Stranka(serazeno[od:od + limit], len(serazeno), od, ("-" if sestupne else "") + klic)
