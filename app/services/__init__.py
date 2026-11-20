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


def cti_datum(text: str, dnes=None):
    """Datum z textu pole (#94): 20.11.2026, 20.11.26, 20.11. (letošní rok), 20112026, 201126 i 2026-11-20.
    Neplatné datum → ValueError."""
    from datetime import date, datetime
    t = str(text).strip().replace(" ", "")
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", t):
        return datetime.strptime(t, "%Y-%m-%d").date()
    if re.fullmatch(r"\d{8}", t):
        t = f"{t[:2]}.{t[2:4]}.{t[4:]}"
    elif re.fullmatch(r"\d{6}", t):
        t = f"{t[:2]}.{t[2:4]}.{t[4:]}"
    m = re.fullmatch(r"(\d{1,2})\.(\d{1,2})\.(\d{2}|\d{4})?", t)
    if not m:
        raise ValueError(text)
    rok = m.group(3)
    if rok is None:
        rok = (dnes or date.today()).year
    elif len(rok) == 2:
        rok = 2000 + int(rok)
    return date(int(rok), int(m.group(2)), int(m.group(1)))


def cti_datum_cas(text: str, dnes=None):
    """Datum a čas z textu pole (#94): „20.11.2026 14:30“ (datum jako u cti_datum), ISO „2026-11-20T14:30“;
    bez času = 0:00. Neplatné → ValueError."""
    from datetime import datetime, time
    t = str(text).strip()
    for fmt in ("%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(t, fmt)
        except ValueError:
            pass
    m = re.fullmatch(r"(.+?)(?:\s+(\d{1,2})[:.](\d{2}))?", t)
    den = cti_datum(m.group(1), dnes)
    cas = time(int(m.group(2)), int(m.group(3))) if m.group(2) else time(0, 0)
    return datetime.combine(den, cas)


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
