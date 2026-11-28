"""Společné pomůcky webových stránek: spojení s databází, stránka, přesměrování, formuláře (rozděleno z routes.py, #233)."""
from datetime import date
from typing import Annotated
from urllib.parse import quote

from fastapi import Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlmodel import Session

from app.db import get_session
from app.models import TypPolozky
from app.services import (
    cenik, cisty_text, katalogy, nastaveni, polozky, vozidla,
    zakaznici,
    zakazky,
)
from app.services.strankovani import VELIKOST_STRANKY
from app.web.sablony import _mnozstvi, templates

DB = Annotated[Session, Depends(get_session)]

POLE_ZAKAZNIKA = zakaznici.POLE
POLE_VOZIDLA = vozidla.POLE
# plánované ukončení a stav paliva se už nezadávají (sloupce v databázi zůstaly kvůli importu ze starého systému)
POLE_ZAKAZKY = ["tachometr", "pozadavek", "poznamka"]


def _udaje_listy(request: Request) -> dict:
    """Název firmy a logo do horní lišty (z Nastavení). Bere stejné spojení s databází jako stránka
    (v testech přesměrované na testovací databázi)."""
    zdroj = request.app.dependency_overrides.get(get_session, get_session)
    gen = zdroj()
    try:
        nast = nastaveni.nacti(next(gen))
        return {"nazev": nast.nazev_do_listy, "logo": nast.logo, "sprava_dat": nast.sprava_dat,
                "statistiky": nast.statistiky}
    except Exception:  # lišta nesmí shodit stránku
        return {"nazev": "Autoservis", "logo": "", "sprava_dat": False, "statistiky": False}
    finally:
        gen.close()


def _stranka(request: Request, sablona: str, status_code: int = 200, **kontext) -> HTMLResponse:
    kontext.setdefault("lista", _udaje_listy(request))
    return templates.TemplateResponse(request, sablona, kontext, status_code=status_code)


def _se_zpravou(odpoved: Response, zprava: str | None, chyba: bool = False) -> Response:
    """Krátká hláška („Uloženo…“), kterou další stránka ukáže vpravo nahoře (base.html, cookie `zprava`).
    `chyba=True` → červená hláška (cookie začíná „!“)."""
    if zprava:
        odpoved.set_cookie("zprava", quote(("!" if chyba else "") + zprava), max_age=60, path="/", samesite="lax")
    return odpoved


def _presmeruj(url: str, zprava: str | None = None, chyba: bool = False) -> RedirectResponse:
    return _se_zpravou(RedirectResponse(url, status_code=303), zprava, chyba)


def _presmeruj_s_chybou(url: str, e: Exception) -> RedirectResponse:
    """Chyba akce bez formuláře (smazání): zpět na stránku s červenou hláškou.
    Stránka tak nezůstane na adrese POST požadavku (F5 by akci odeslal znovu)."""
    return _presmeruj(url, str(e), chyba=True)


def _po_ulozeni_okna(url: str | None = None, zprava: str | None = None) -> Response:
    """Formulář uložený z okna (HTMX): přejdi na `url`, nebo jen obnov stránku pod oknem."""
    hlavicka = {"HX-Redirect": url} if url else {"HX-Refresh": "true"}
    return _se_zpravou(Response(status_code=204, headers=hlavicka), zprava)


def _status_formulare(okno: bool, chyba) -> int:
    """Chyba ve formuláři = 422; v okně ale 200, jinak by ji HTMX do okna nevložilo."""
    return 422 if chyba and not okno else 200


def _po_ulozeni(okno: bool, stranka: str, z_okna: str | None = None, zprava: str | None = None) -> Response:
    """Po uložení formuláře: celá stránka → přesměrovat na `stranka`;
    z okna → přejít na `z_okna`, nebo (None) zůstat a obnovit stránku pod oknem. `zprava` = krátká hláška."""
    return _po_ulozeni_okna(z_okna, zprava) if okno else _presmeruj(stranka, zprava)


async def _formular(request: Request) -> dict[str, str]:
    form = await request.form()
    return {k: str(v) for k, v in form.items()}


def _s_predponou(data: dict, predpona: str, pole: list[str]) -> dict:
    """{'v_znacka': 'Škoda'} → {'znacka': 'Škoda'} jen pro zadaná pole."""
    return {p: data[predpona + p] for p in pole if predpona + p in data}


# ---------------------------------------------------------------- zakázky

def _davka(vse_radky: str) -> int:
    """Kolik řádků seznamu načíst najednou („Načíst vše“ = bez omezení)."""
    return 1_000_000 if vse_radky else VELIKOST_STRANKY


def _vybrany_rok(rok: str) -> tuple[int | None, str]:
    """Rok filtru a hodnota do výběru. Prázdné = aktuální rok, „vse“ = bez omezení (#91)."""
    if rok == "vse":
        return None, ""
    if len(rok) == 4 and rok.isascii() and rok.isdecimal():
        return int(rok), rok
    return date.today().year, str(date.today().year)


# --- příjem (nová zakázka) jako okno Zakázka ve starém systému: vlevo zákazník, uprostřed zakázka, vpravo vozidlo.
# Panely zákazníka a vozidla jsou přímo upravitelné; OK uloží zakázku i změny zákazníka a vozidla.

PANEL_ZAKAZNIKA = ["nazev", "ulice", "psc", "mesto", "telefon", "email", "ico", "dic"]


def _iso(hodnota) -> str:
    return hodnota.isoformat() if hasattr(hodnota, "isoformat") else ("" if hodnota is None else str(hodnota))


def _hodnoty_zakaznika(zakaznik) -> dict:
    if not zakaznik:
        return {}
    return {"zakaznik_id": zakaznik.id} | {f"k_{p}": getattr(zakaznik, p) or "" for p in PANEL_ZAKAZNIKA}


def _najdi(db, sluzba, hodnota):
    """Záznam podle id z formuláře, nebo None."""
    try:
        return sluzba.ziskej(db, int(cisty_text(hodnota) or ""))
    except (ValueError, LookupError):
        return None


LIMIT_CENIKU = 100


def _katalog(request: Request, db):
    """Katalog materiálu vybraný na kartě Materiál (cookie prohlížeče, #62); jinak výchozí."""
    return katalogy.viditelny(db, request.cookies.get(katalogy.KLIC_COOKIE))  # #150: skrytý → výchozí


def _typ_ceniku(typ) -> str | None:
    """Typ okna Přidat z ceníku: materiál / práce (z tlačítka mřížky), jinak oba ceníky."""
    return typ if typ in TypPolozky.VSECHNY else None


HISTORIE = "historie"  # zdroj okna Přidat materiál: místo katalogu materiál ze starších zakázek vozidla (#69)


def _okno_ceniku(request, db, zakazka_id, q="", okno=False, chyba=None, zprava=None, pridano=False, typ=None,
                 zdroj=None, katalog=None):
    """Okno „Přidat z ceníku“ (jako F9 ve starém systému) – hledání v ceníku a výběr položek.

    V okně se položky jen vybírají do seznamu vpravo (drží ho prohlížeč); do zakázky je zapíše až
    Vložit (POST /zakazky/{id}/polozky/vlozit). Storno okno zavře a zakázky se nedotkne.
    Celá stránka (bez okna) přidává rovnou do zakázky.
    `typ` = materiál / práce: okno nabízí jen tento ceník (se sloupci jako karta Materiál / Práce).
    `zdroj` = HISTORIE: materiál dříve vydaný na vozidlo zakázky (#69); `katalog` = právě zvolený katalog."""
    q = cisty_text(q) or ""
    typ = _typ_ceniku(typ)
    zakazka = zakazky.ziskej(db, zakazka_id)
    db.refresh(zakazka)
    katalog = katalog or _katalog(request, db)
    historie = typ == TypPolozky.MATERIAL and zdroj == HISTORIE
    return _stranka(request, "zakazka_cenik.html", _status_formulare(okno, chyba), aktivni="zakazky",
                    zakazka=zakazka, zakazka_id=zakazka_id, q=q, okno=okno, typ_okna=typ, katalog=katalog,
                    katalogy=katalogy.viditelne(db) if typ == TypPolozky.MATERIAL else [], historie=historie,
                    **_vysledky_okna(db, zakazka, q, typ, katalog, historie),
                    nast=nastaveni.nacti(db), hlaseni_chyba=chyba, hlaseni=zprava, pridano=pridano)


def _vysledky_okna(db, zakazka, q, typ, katalog, historie) -> dict:
    if historie:
        return {"radky_historie": polozky.historie_vozidla(db, zakazka, q), "nalezene": [], "limit": LIMIT_CENIKU}
    if typ == TypPolozky.MATERIAL:  # #102: nejpoužívanější díly a řazení podle počtu použití
        nalezene, pouziti, nejpouzivanejsi = cenik.vyber_pro_zakazku(db, q, typ, katalog.id, LIMIT_CENIKU)
        return {"nalezene": nalezene, "pouziti": pouziti, "nejpouzivanejsi": nejpouzivanejsi, "limit": LIMIT_CENIKU,
                "casto": cenik.CASTO_POUZIVANY}
    return {"nalezene": cenik.seznam(db, q, typ=typ, jen_aktivni=True, limit=LIMIT_CENIKU, podle_kodu=True,
                                     katalog_id=katalog.id), "limit": LIMIT_CENIKU}


def _zapamatuj_katalog(odpoved: Response, katalog) -> Response:
    """Vybraný katalog si pamatuje prohlížeč (cookie) – karta Materiál i okno Přidat materiál (#62, #70)."""
    odpoved.set_cookie(katalogy.KLIC_COOKIE, str(katalog.id), max_age=10 * ROK_SEKUND, path="/", samesite="lax")
    return odpoved


LIMIT_OKNA = 200


# ---------------------------------------------------------------- ceník

POLE_CENIKU = ["kod", "nazev", "typ", "jednotka", "cena", "sazba_dph", "zamenitelny_dil", "poznamka"]


# Dva oddělené ceníky: materiál (/cenik) a práce (/prace) – vlastní seznam, sloupce i okno.
# V databázi je to dál jedna tabulka PolozkaCeniku rozlišená typem (zakázky z ní berou obojí).

def _adresa_ceniku(typ: str) -> str:
    return "/prace" if typ == TypPolozky.PRACE else "/cenik"


ROK_SEKUND = 365 * 24 * 3600


def _formular_ceniku(request, db, polozka, hodnoty, okno=False, chyba=None, zprava=None, z_ceniku=None, q="",
                     radek=None):
    """`radek` = řádek zakázky, jehož úpravou se karta otevřela (z detailu zakázky) – po uložení
    se změny propíšou i do něj."""
    typ = polozka.typ if polozka else hodnoty.get("typ") or TypPolozky.MATERIAL
    prace = typ == TypPolozky.PRACE
    if prace:
        katalog = None
    elif polozka:
        katalog = katalogy.podle_id(db, polozka.katalog_id)
    else:  # nový materiál: hlavní katalog, ve formuláři jde přepnout (hodnota jde dál ve formuláři, #70)
        katalog = katalogy.podle_id(db, hodnoty.get("katalog_id"))
    return _stranka(request, "prace_form.html" if prace else "cenik_form.html", _status_formulare(okno, chyba),
                    aktivni="zakazky" if radek else "prace" if prace else "cenik", polozka=polozka, hodnoty=hodnoty,
                    # #150: nový díl jen do viditelných skladů; úprava existujícího vidí i jeho (skrytý) sklad
                    katalog=katalog, katalogy=(katalogy.seznam(db) if polozka else katalogy.viditelne(db)) if not prace else [],
                    nast=nastaveni.nacti(db), okno=okno, chyba=chyba, zprava=zprava,
                    adresa_ceniku=_adresa_ceniku(typ), z_ceniku=z_ceniku if okno else None, q_ceniku=q or "",
                    radek_zakazky=radek)


def _karta_ceniku(request, db, p, okno=False, z_ceniku=None, q="", radek=None):
    nast = nastaveni.nacti(db)
    hodnoty = {pole: getattr(p, pole) if getattr(p, pole) is not None else "" for pole in POLE_CENIKU}
    hodnoty |= {"sazba_dph": _mnozstvi(p.sazba_dph), "aktivni": p.aktivni}
    sazba = p.sazba_dph if nast.platce_dph else 0
    hodnoty |= cenik.hodnoty_dvojice_cen("cena", p.cena, sazba)
    hodnoty |= cenik.hodnoty_dvojice_cen("nakupni_cena", p.nakupni_cena, sazba)
    return _formular_ceniku(request, db, p, hodnoty, okno=okno, z_ceniku=z_ceniku, q=q, radek=radek)


def _nova_polozka_ceniku(db, typ: str) -> dict:
    return {"typ": typ, "sazba_dph": nastaveni.nacti(db).vychozi_dph,
            "jednotka": "hod" if typ == "prace" else "ks"}
