"""Servisní vrstva – veškerá logika aplikace.

Web, MCP server i importy volají jen funkce odsud, nikdy nesahají do databáze přímo.
"""
import re
from decimal import Decimal, InvalidOperation


class ChybaValidace(ValueError):
    """Chybná vstupní data – zprávu lze přímo ukázat uživateli.

    `pole` = název pole formuláře, kterého se chyba týká (formulář na něj přesune kurzor a zvýrazní ho).
    """

    def __init__(self, zprava: str, pole: str | None = None):
        super().__init__(zprava)
        self.pole = pole


class NenalezenoError(LookupError):
    """Záznam neexistuje."""


def cisty_text(hodnota) -> str | None:
    """Ořízne mezery; prázdný text převede na None."""
    if hodnota is None:
        return None
    hodnota = str(hodnota).strip()
    return hodnota or None


# jednotky, které uživatel často napíše za číslo („150 Kč“, „21 %“) – tiše je vynecháme
_JEDNOTKY_CISLA = re.compile(r"\s*(kč|czk|eur|€|%|,-|\.-)\s*$", re.IGNORECASE)


def desetinne_nebo_none(hodnota, nazev_pole: str, pole: str | None = None) -> Decimal | None:
    """Přijme '1 234,50', '1234.5', '1,5', '150 Kč', '21 %'… Prázdné → None."""
    if isinstance(hodnota, (Decimal, int)):
        return Decimal(hodnota)
    hodnota = cisty_text(hodnota)
    if hodnota is None:
        return None
    text = _JEDNOTKY_CISLA.sub("", hodnota).replace(" ", "").replace(" ", "").replace(",", ".")
    try:
        cislo = Decimal(text)
    except InvalidOperation:
        raise ChybaValidace(f"{nazev_pole}: „{hodnota}“ není číslo.", pole) from None
    if not cislo.is_finite():
        raise ChybaValidace(f"{nazev_pole}: „{hodnota}“ není číslo.", pole)
    return cislo


def id_nebo_none(hodnota, nazev_pole: str) -> int | None:
    """Id z výběru ve formuláři; „bez“, „novy“ a prázdno → None."""
    if hodnota in (None, "", "bez", "novy"):
        return None
    return cislo_nebo_none(hodnota, nazev_pole)


def cislo_nebo_none(hodnota, nazev_pole: str, pole: str | None = None) -> int | None:
    hodnota = cisty_text(hodnota)
    if hodnota is None:
        return None
    try:
        return int(hodnota.replace(" ", "").replace(" ", ""))
    except ValueError:
        raise ChybaValidace(f"{nazev_pole} musí být celé číslo.", pole) from None
