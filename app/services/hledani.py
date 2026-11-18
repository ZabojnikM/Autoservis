"""Globální hledání (horní lišta)."""
from dataclasses import dataclass, field

from sqlmodel import Session

from app.models import Vozidlo, Zakaznik, Zakazka
from app.services import cisty_text, vozidla, zakaznici, zakazky


@dataclass
class VysledekHledani:
    dotaz: str
    vozidla: list[Vozidlo] = field(default_factory=list)
    zakaznici: list[Zakaznik] = field(default_factory=list)
    zakazky: list[Zakazka] = field(default_factory=list)

    @property
    def prazdny(self) -> bool:
        return not (self.vozidla or self.zakaznici or self.zakazky)


def hledej(session: Session, dotaz: str, limit: int = 30) -> VysledekHledani:
    dotaz = cisty_text(dotaz) or ""
    vysledek = VysledekHledani(dotaz=dotaz)
    if not dotaz:
        return vysledek
    vysledek.vozidla = vozidla.seznam(session, dotaz, limit=limit)
    vysledek.zakaznici = zakaznici.seznam(session, dotaz, limit=limit)
    vysledek.zakazky = zakazky.seznam(session, hledat=dotaz, limit=limit)
    return vysledek
