"""Jinja2 šablony a filtry pro český formát."""
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from urllib.parse import urlencode

from fastapi.templating import Jinja2Templates

from app import config
from app.models import STAVY_PALIVA, FormaUhrady, StavZakazky, TypDokladu, TypPolozky

templates = Jinja2Templates(directory=config.TEMPLATES_DIR)


def _datum(hodnota) -> str:
    if not hodnota:
        return ""
    if isinstance(hodnota, (date, datetime)):
        return hodnota.strftime("%d.%m.%Y")
    return str(hodnota)


def _datumcas(hodnota) -> str:
    if not hodnota:
        return ""
    return hodnota.strftime("%d.%m.%Y %H:%M")


def _cislo(hodnota) -> str:
    if hodnota is None or hodnota == "":
        return ""
    return f"{int(hodnota):,}".replace(",", " ")


def _penize(hodnota) -> str:
    """Decimal('1234.5') → '1 234,50'"""
    if hodnota is None or hodnota == "":
        return ""
    try:
        hodnota = Decimal(hodnota)
    except (InvalidOperation, ValueError, TypeError):
        return str(hodnota)
    return f"{hodnota:,.2f}".replace(",", " ").replace(".", ",")


def _mnozstvi(hodnota) -> str:
    """Decimal('1.500') → '1,5'"""
    if hodnota is None or hodnota == "":
        return ""
    try:
        cislo = Decimal(hodnota)
    except (InvalidOperation, ValueError, TypeError):
        return str(hodnota)  # neplatný vstup z formuláře ukážeme, jak byl zadán
    text = f"{cislo:f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text.replace(".", ",")


def _psc(hodnota) -> str:
    """'11000' → '110 00' (jiný tvar nechá, jak je)."""
    text = (str(hodnota) if hodnota else "").replace(" ", "")
    return f"{text[:3]} {text[3:]}" if len(text) == 5 and text.isdigit() else (hodnota or "")


def _iso(hodnota) -> str:
    """Pro <input type=date>."""
    if isinstance(hodnota, (date, datetime)):
        return hodnota.strftime("%Y-%m-%d")
    return hodnota or ""


def _datum_pole(hodnota, cas: bool = False) -> str:
    """Hodnota textového pole s datem (#94): 20.11.2026, s časem 20.11.2026 14:30.
    Přijme date/datetime i ISO text; jiný text (co uživatel napsal) vrátí beze změny."""
    if hodnota is None or hodnota == "":
        return ""
    if isinstance(hodnota, str):
        try:
            hodnota = datetime.fromisoformat(hodnota) if cas or "T" in hodnota else date.fromisoformat(hodnota)
        except ValueError:
            return hodnota
    if isinstance(hodnota, datetime):
        return hodnota.strftime("%d.%m.%Y %H:%M" if cas else "%d.%m.%Y")
    return hodnota.strftime("%d.%m.%Y")


def _url_s(request, **zmeny) -> str:
    """Adresa aktuální stránky se změněnými parametry (None / '' parametr odebere).
    Např. url_s(request, razeni='-spz', od=None) – pro řazení a načítání dalších řádků seznamu."""
    parametry = dict(request.query_params)
    for klic, hodnota in zmeny.items():
        if hodnota is None or hodnota == "":
            parametry.pop(klic, None)
        else:
            parametry[klic] = str(hodnota)
    return request.url.path + ("?" + urlencode(parametry) if parametry else "")


def _material_prvni(radky) -> list:
    """Řádky zakázky / dokladu: nejdřív materiál, pak práce; uvnitř typu pořadí zadání."""
    return sorted(radky, key=lambda r: 0 if r.typ == TypPolozky.MATERIAL else 1)


templates.env.globals["url_s"] = _url_s
templates.env.filters["material_prvni"] = _material_prvni
templates.env.filters["datum"] = _datum
templates.env.filters["datumcas"] = _datumcas
templates.env.filters["cislo"] = _cislo
templates.env.filters["iso"] = _iso
templates.env.filters["datum_pole"] = _datum_pole
templates.env.filters["penize"] = _penize
templates.env.filters["mnozstvi"] = _mnozstvi
templates.env.filters["psc"] = _psc


def _polozek(pocet) -> str:
    """3 → '3 položky' (1 položka, 2–4 položky, 0 a 5+ položek)."""
    n = int(pocet or 0)
    return f"{n} " + ("položka" if n == 1 else "položky" if 2 <= n <= 4 else "položek")


templates.env.filters["polozek"] = _polozek


def _pomlcka(hodnota):
    """Prázdná hodnota v seznamu → jednotná tlumená pomlčka (#57); jinak hodnota (escapovaná)."""
    from markupsafe import Markup, escape
    if hodnota is None or (isinstance(hodnota, str) and not hodnota.strip()):
        return Markup('<span class="prazdne">—</span>')
    return escape(hodnota)


templates.env.filters["pomlcka"] = _pomlcka
templates.env.globals["StavZakazky"] = StavZakazky
templates.env.globals["TypPolozky"] = TypPolozky
templates.env.globals["TypDokladu"] = TypDokladu
templates.env.globals["FormaUhrady"] = FormaUhrady
templates.env.globals["dnes_rok"] = lambda: date.today().year
templates.env.globals["dnes"] = date.today
templates.env.globals["STAVY_PALIVA"] = STAVY_PALIVA
templates.env.globals["APP_VERSION"] = config.APP_VERSION
# při změně CSS se změní adresa → prohlížeč nepoužije starou verzi z cache
templates.env.globals["css_verze"] = lambda: int((config.STATIC_DIR / "app.css").stat().st_mtime)
