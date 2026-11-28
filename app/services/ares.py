"""Načtení údajů firmy z ARES (Administrativní registr ekonomických subjektů, Ministerstvo financí) podle IČO.

Veřejné REST API bez klíče: GET https://ares.gov.cz/ekonomicke-subjekty-v-be/rest/ekonomicke-subjekty/{ico}
Posílá se jen IČO. Vrací se název, adresa sídla a DIČ (jen když je firma plátce DPH / má DIČ přidělené).
"""
import json
import re
import urllib.error
import urllib.request

from app.services import ChybaValidace
from app.zaznam import log

API_URL = "https://ares.gov.cz/ekonomicke-subjekty-v-be/rest/ekonomicke-subjekty/"
TIMEOUT = 15  # s


class ChybaAres(ChybaValidace):
    """ARES nejde použít (neplatné IČO, subjekt nenalezen, výpadek)."""


def normalizuj_ico(ico: str | None) -> str:
    """'123 45 678' → '12345678'; kratší IČO se doplní nulami zleva na 8 číslic."""
    cisla = "".join(z for z in (ico or "") if not z.isspace())
    if not cisla.isdigit() or len(cisla) > 8:
        raise ChybaAres("IČO musí mít nejvýš 8 číslic.", "ico")
    return cisla.zfill(8)


def je_platne_ico(ico: str) -> bool:
    """Kontrolní číslice IČO (vážený součet mod 11)."""
    soucet = sum(int(c) * vaha for c, vaha in zip(ico[:7], range(8, 1, -1)))
    kontrola = (11 - soucet % 11) % 10
    return kontrola == int(ico[7])


def _stahni(ico: str) -> dict:
    pozadavek = urllib.request.Request(API_URL + ico, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(pozadavek, timeout=TIMEOUT) as odpoved:
            telo = odpoved.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise ChybaAres(f"IČO {ico} v ARES nenalezeno.", "ico") from e
        if e.code == 400:
            raise ChybaAres(f"ARES odmítl IČO {ico} jako neplatné.", "ico") from e
        raise ChybaAres(f"ARES vrátil chybu {e.code}.") from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise ChybaAres("ARES neodpovídá – zkontrolujte připojení k internetu.") from e
    try:
        return json.loads(telo)
    except ValueError as e:
        raise ChybaAres("ARES vrátil nečitelnou odpověď.") from e


def nacti(ico: str | None) -> dict:
    """Surová data subjektu z ARES."""
    ico = normalizuj_ico(ico)
    if ico == "00000000":
        raise ChybaAres("Nejdřív zadejte IČO.", "ico")
    if not je_platne_ico(ico):
        raise ChybaAres(f"IČO {ico} není platné (nesedí kontrolní číslice).", "ico")
    try:
        return _stahni(ico)
    except ChybaAres as e:  # #225: do záznamu bez IČO
        log.warning("ARES: %s", re.sub(r"\d{6,}", "…", str(e)))
        raise


def _ulice(sidlo: dict) -> str | None:
    """'Letenská 525/15'; bez ulice (obec bez ulic) část obce + číslo popisné ('Provodov 48')."""
    cislo = str(sidlo.get("cisloDomovni") or "")
    if sidlo.get("typCisloDomovni") == 2 and cislo:  # číslo evidenční
        cislo = "ev. č. " + cislo
    if sidlo.get("cisloOrientacni"):
        cislo += f"/{sidlo['cisloOrientacni']}{sidlo.get('cisloOrientacniPismeno') or ''}"
    nazev = sidlo.get("nazevUlice") or sidlo.get("nazevCastiObce") or sidlo.get("nazevObce")
    text = " ".join(x for x in (nazev, cislo) if x)
    return text or None


def na_pole_zakaznika(data: dict) -> dict:
    """Pole formuláře zákazníka (bez předpony): nazev, ulice, psc, mesto, ico, dic."""
    sidlo = data.get("sidlo") or {}
    psc = str(sidlo.get("psc") or "")
    pole = {
        "nazev": data.get("obchodniJmeno"),
        "ulice": _ulice(sidlo),
        "psc": psc.zfill(5) if psc else None,
        "mesto": sidlo.get("nazevObce"),
        "ico": data.get("ico"),
        "dic": data.get("dic"),
    }
    return {k: v for k, v in pole.items() if v}
