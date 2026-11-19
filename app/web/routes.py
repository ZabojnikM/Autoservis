"""Webové stránky (HTML). Jen tenká vrstva nad app.services."""
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlmodel import Session

from app.db import get_session
from app.models import FormaUhrady, StavZakazky, TypDokladu, TypPolozky, Uhrada
from app.services import ares, prijem_vozidel
from app.services import (
    ChybaValidace, cenik, cisty_text, faktury, hledani, nastaveni, polozky, registr_vozidel, vozidla, zakaznici,
    zakazky,
)
from app.services.strankovani import VELIKOST_STRANKY
from app.web.sablony import _mnozstvi, templates

router = APIRouter()
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
        return {"nazev": nast.nazev_do_listy, "logo": nast.logo}
    except Exception:  # lišta nesmí shodit stránku
        return {"nazev": "Autoservis", "logo": ""}
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
    """Chyba akce bez formuláře (smazání, storno): zpět na stránku s červenou hláškou.
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


# ---------------------------------------------------------------- úvodní stránka, hledání

@router.get("/")
def uvod():
    """Úvodní stránka = seznam zakázek (nástěnka byla zrušena)."""
    return _presmeruj("/zakazky")


@router.get("/hledat", response_class=HTMLResponse)
def hledat(request: Request, db: DB, q: str = ""):
    vysledek = hledani.hledej(db, q)
    presna = vozidla.najdi_podle_vin(db, q) if vozidla.je_vin(q) else vozidla.najdi_podle_spz(db, q)
    if presna:
        return _presmeruj(f"/vozidla/{presna.id}")
    # hledany_text = text v horním globálním hledání (filtry seznamů se do něj nepropisují)
    return _stranka(request, "hledat.html", vysledek=vysledek, q=q, hledany_text=q, hledany_vin=vozidla.je_vin(q))


# ---------------------------------------------------------------- zakázky

def _davka(vse_radky: str) -> int:
    """Kolik řádků seznamu načíst najednou („Načíst vše“ = bez omezení)."""
    return 1_000_000 if vse_radky else VELIKOST_STRANKY


@router.get("/zakazky", response_class=HTMLResponse)
def zakazky_seznam(request: Request, db: DB, stav: str = "", q: str = "", vse: str = "",
                   razeni: str = "", od: str = "", vse_radky: str = ""):
    filtr = stav or (None if vse else StavZakazky.ZALOZKA_OTEVRENE)
    st = zakazky.stranka(db, stav=filtr, hledat=q, razeni=razeni, od=od, limit=_davka(vse_radky))
    pocty = zakazky.pocty_podle_stavu(db)
    return _stranka(
        request, "zakazky_seznam.html", aktivni="zakazky",
        zakazky=st.polozky, stranka=st, stav=stav, q=q, vse=vse, pocty=pocty,
        pocet_otevrenych=sum(pocty[s] for s in StavZakazky.ZALOZKA_OTEVRENE), pocet_vsech=sum(pocty.values()),
    )


# --- příjem (nová zakázka) jako okno Zakázka ve starém systému: vlevo zákazník, uprostřed zakázka, vpravo vozidlo.
# Panely zákazníka a vozidla jsou přímo upravitelné; OK uloží zakázku i změny zákazníka a vozidla.

PANEL_ZAKAZNIKA = ["nazev", "ulice", "psc", "mesto", "telefon", "email", "ico", "dic"]
PANEL_VOZIDLA = [p for p in vozidla.POLE if p not in ("spz", "motor", "poznamka")]
POLE_PRIJMU = POLE_ZAKAZKY + ["datum_prijeti"]


def _iso(hodnota) -> str:
    return hodnota.isoformat() if hasattr(hodnota, "isoformat") else ("" if hodnota is None else str(hodnota))


def _hodnoty_zakaznika(zakaznik) -> dict:
    if not zakaznik:
        return {}
    return {"zakaznik_id": zakaznik.id} | {f"k_{p}": getattr(zakaznik, p) or "" for p in PANEL_ZAKAZNIKA}


def _hodnoty_vozidla(vozidlo) -> dict:
    if not vozidlo:
        return {}
    return {"vozidlo_id": vozidlo.id, "spz": vozidlo.spz} | {
        f"v_{p}": _iso(getattr(vozidlo, p)) for p in PANEL_VOZIDLA}


def _otevrene_vozidla(db, vozidlo):
    if not vozidlo:
        return []
    return [z for z in vozidla.historie(db, vozidlo.id) if z.je_otevrena]


def _najdi(db, sluzba, hodnota):
    """Záznam podle id z formuláře, nebo None."""
    try:
        return sluzba.ziskej(db, int(cisty_text(hodnota) or ""))
    except (ValueError, LookupError):
        return None


@router.get("/zakazky/nova", response_class=HTMLResponse)
def zakazka_nova(request: Request, db: DB, vozidlo_id: int | None = None, spz: str = "", vin: str = "",
                 zakaznik_id: int | None = None, okno: str = ""):
    """Příjem vozidla – celá stránka, nebo s `okno=1` jen obsah okna (dialog nad seznamem).
    `spz` z hledání, které vypadá jako VIN (17 znaků), se bere jako VIN – nové vozidlo ho má v poli VIN."""
    if not vin and vozidla.je_vin(spz):
        vin, spz = spz, ""
    if vozidlo_id:
        vozidlo = vozidla.ziskej(db, vozidlo_id)
    else:
        vozidlo = vozidla.najdi_podle_vin(db, vin) if vin else vozidla.najdi_podle_spz(db, spz)
    zakaznik = zakaznici.ziskej(db, zakaznik_id) if zakaznik_id else (vozidlo.zakaznik if vozidlo else None)
    hodnoty = {"spz": vozidla.normalizuj_spz(spz), "v_vin": vozidla.normalizuj_vin(vin) or ""} \
        | _hodnoty_vozidla(vozidlo) | _hodnoty_zakaznika(zakaznik)
    hodnoty |= {"datum_prijeti": datetime.now().strftime("%Y-%m-%dT%H:%M")}
    return _prijem(request, db, hodnoty, okno=bool(okno))


def _prijem(request, db, hodnoty, chyba=None, status_code=200, okno=False, zakazka=None):
    """Okno Zakázka – nová (příjem), nebo s `zakazka` úprava existující (stejné panely i ovládání)."""
    vozidlo = _najdi(db, vozidla, hodnoty.get("vozidlo_id"))
    otevrene = [z for z in _otevrene_vozidla(db, vozidlo) if not zakazka or z.id != zakazka.id]
    return _stranka(
        # v okně i chyba vrací 200 – HTMX jinak odpověď nezobrazí
        request, "zakazka_prijem.html", status_code=200 if okno else status_code, aktivni="zakazky",
        hodnoty=hodnoty, hz=hodnoty, vozidlo=vozidlo, zakaznik=_najdi(db, zakaznici, hodnoty.get("zakaznik_id")),
        otevrene=otevrene, cislo=zakazka.cislo if zakazka else zakazky.dalsi_cislo(db), chyba=chyba, okno=okno,
        zakazka=zakazka,
    )


def _data_panelu(data: dict) -> tuple[dict, dict, dict]:
    """Formulář okna Zakázka → (zakázka, vozidlo, zákazník) pro služby."""
    data_zakazky = {p: data[p] for p in POLE_PRIJMU if p in data}
    data_vozidla = {"vozidlo_id": data.get("vozidlo_id"), "spz": data.get("spz", "")} \
        | _s_predponou(data, "v_", PANEL_VOZIDLA)
    data_zakaznika = {"zakaznik_id": data.get("zakaznik_id"), "jako_novy": data.get("jako_novy")} \
        | _s_predponou(data, "k_", PANEL_ZAKAZNIKA)
    return data_zakazky, data_vozidla, data_zakaznika


@router.get("/zakazky/nova/vozidlo", response_class=HTMLResponse)
def zakazka_nova_vozidlo(request: Request, db: DB, spz: str = "", vybrat_id: int | None = None,
                         novy: str = ""):
    """HTMX: údaje vozidla v panelu příjmu.

    - po zadání SPZ: známé vozidlo se vyplní (a když panel zákazníka je prázdný, doplní se i jeho majitel),
      neznámé = nové vozidlo, rozepsané údaje zůstanou,
    - `vybrat_id`: vozidlo vložené z okna databáze vozidel (přepíše i pole SPZ),
    - `novy`: vyprázdní panel pro nové vozidlo.
    """
    parametry = dict(request.query_params)
    if novy:
        return _stranka(request, "_prijem_vozidlo.html", hodnoty={}, vozidlo=None, otevrene=[], prepsat_spz=True)
    vozidlo = vozidla.ziskej(db, vybrat_id) if vybrat_id else vozidla.najdi_podle_spz(db, spz)
    if vozidlo:
        hodnoty = _hodnoty_vozidla(vozidlo)
    else:  # nové vozidlo – necháme, co už je napsané (ale bez vazby na dříve vybrané vozidlo)
        hodnoty = {k: v for k, v in parametry.items() if k.startswith("v_")} | {"spz": vozidla.normalizuj_spz(spz)}
    panel_zakaznika_prazdny = not cisty_text(parametry.get("zakaznik_id")) and not any(
        cisty_text(parametry.get(f"k_{p}")) for p in PANEL_ZAKAZNIKA)
    majitel = vozidlo.zakaznik if vozidlo and panel_zakaznika_prazdny else None
    return _stranka(
        request, "_prijem_vozidlo.html", hodnoty=hodnoty, vozidlo=vozidlo,
        otevrene=_otevrene_vozidla(db, vozidlo), prepsat_spz=bool(vybrat_id),
        zakaznik_oob=bool(majitel), zakaznik=majitel, hz=_hodnoty_zakaznika(majitel),
    )


@router.get("/zakazky/nova/zakaznik", response_class=HTMLResponse)
def zakazka_nova_zakaznik(request: Request, db: DB, vybrat_id: int | None = None):
    """HTMX: panel zákazníka – vložený z okna databáze zákazníků, nebo prázdný (tlačítko Nový)."""
    zakaznik = zakaznici.ziskej(db, vybrat_id) if vybrat_id else None
    return _stranka(request, "_prijem_zakaznik.html", zakaznik=zakaznik, hz=_hodnoty_zakaznika(zakaznik))


@router.post("/zakazky/nova", response_class=HTMLResponse)
async def zakazka_nova_uloz(request: Request, db: DB):
    data = await _formular(request)
    try:
        nova = zakazky.prijem_z_formulare(db, *_data_panelu(data))
    except ChybaValidace as e:
        return _prijem(request, db, data, chyba=e, status_code=422, okno=bool(data.get("okno")))
    zprava = f"Zakázka {nova.cislo} založena."
    if data.get("okno"):
        return _po_ulozeni_okna(f"/zakazky/{nova.id}", zprava)
    return _presmeruj(f"/zakazky/{nova.id}", zprava)


@router.get("/zakazky/{zakazka_id}", response_class=HTMLResponse)
def zakazka_detail(request: Request, db: DB, zakazka_id: int):
    return _detail_zakazky(request, db, zakazka_id)


def _detail_zakazky(request, db, zakazka_id, chyba=None, hodnoty=None, status_code=200, **kontext):
    zakazka = zakazky.ziskej(db, zakazka_id)
    return _stranka(
        request, "zakazka_detail.html", status_code, aktivni="zakazky", zakazka=zakazka,
        rek=polozky.rekapitulace(zakazka), nast=nastaveni.nacti(db),
        nelze_smazat=zakazky.duvod_proc_nesmazat(zakazka),
        doklady=sorted(zakazka.faktury, key=lambda f: (f.datum_vystaveni, f.cislo)),
        chyba=chyba, hodnoty=hodnoty or {}, **kontext,
    )


LIMIT_CENIKU = 100


def _typ_ceniku(typ) -> str | None:
    """Typ okna Přidat z ceníku: materiál / práce (z tlačítka mřížky), jinak oba ceníky."""
    return typ if typ in TypPolozky.VSECHNY else None


def _okno_ceniku(request, db, zakazka_id, q="", okno=False, chyba=None, zprava=None, pridano=False, typ=None):
    """Okno „Přidat z ceníku“ (jako F9 ve starém systému) – hledání v ceníku a výběr položek.

    V okně se položky jen vybírají do seznamu vpravo (drží ho prohlížeč); do zakázky je zapíše až
    Vložit (POST /zakazky/{id}/polozky/vlozit). Storno okno zavře a zakázky se nedotkne.
    Celá stránka (bez okna) přidává rovnou do zakázky.
    `typ` = materiál / práce: okno nabízí jen tento ceník (se sloupci jako karta Materiál / Práce)."""
    q = cisty_text(q) or ""
    typ = _typ_ceniku(typ)
    zakazka = zakazky.ziskej(db, zakazka_id)
    db.refresh(zakazka)
    return _stranka(request, "zakazka_cenik.html", _status_formulare(okno, chyba), aktivni="zakazky",
                    zakazka=zakazka, zakazka_id=zakazka_id, q=q, okno=okno, typ_okna=typ,
                    nalezene=cenik.seznam(db, q, typ=typ, jen_aktivni=True, limit=LIMIT_CENIKU, podle_kodu=True), limit=LIMIT_CENIKU,
                    nast=nastaveni.nacti(db), hlaseni_chyba=chyba, hlaseni=zprava, pridano=pridano)


@router.get("/zakazky/{zakazka_id}/cenik", response_class=HTMLResponse)
def zakazka_cenik(request: Request, db: DB, zakazka_id: int, q: str = "", okno: str = "", typ: str = ""):
    return _okno_ceniku(request, db, zakazka_id, q, okno=bool(okno), typ=typ)


@router.post("/zakazky/{zakazka_id}/polozky/vlozit")
async def zakazka_vloz_polozky(request: Request, db: DB, zakazka_id: int):
    """Vložit z okna Přidat z ceníku: zapíše vybrané položky (polozka_ceniku_id[] + mnozstvi[]) najednou.
    Chyba = 422 s textem (okno zůstane otevřené), úspěch = obnovení stránky pod oknem."""
    form = await request.form()
    vyber = list(zip(form.getlist("polozka_ceniku_id"), form.getlist("mnozstvi")))
    try:
        radky = polozky.vloz_z_ceniku(db, zakazka_id, vyber)
    except ChybaValidace as e:
        return Response(str(e), status_code=422, media_type="text/plain; charset=utf-8")
    return _po_ulozeni_okna(zprava=f"Vloženo položek: {len(radky)}.")


def _formular_polozky(request, db, zakazka_id, hodnoty, okno=False, chyba=None, radek=None):
    """Okno ruční položky – stejná pole jako karta Materiál / Práce + množství (polozka_form.html).
    `radek` = úprava ručního řádku zakázky; chyba KodUzVCeniku nabídne existující položku ceníku."""
    return _stranka(request, "polozka_form.html", _status_formulare(okno, chyba), aktivni="zakazky",
                    zakazka=zakazky.ziskej(db, zakazka_id), hodnoty=hodnoty, nast=nastaveni.nacti(db),
                    okno=okno, chyba=chyba, radek=radek,
                    existujici=chyba.polozka if isinstance(chyba, polozky.KodUzVCeniku) else None)


@router.get("/zakazky/{zakazka_id}/polozky/nova", response_class=HTMLResponse)
def zakazka_nova_polozka(request: Request, db: DB, zakazka_id: int, okno: str = "", typ: str = ""):
    typ = typ if typ in TypPolozky.VSECHNY else TypPolozky.MATERIAL
    # nový materiál / nová práce: výchozí „i do ceníku“ (úprava ručního řádku zůstává „jen do zakázky“)
    hodnoty = _nova_polozka_ceniku(db, typ) | {"mnozstvi": "1", "ulozit_do_ceniku": "1"}
    return _formular_polozky(request, db, zakazka_id, hodnoty, okno=bool(okno))


@router.get("/zakazky/{zakazka_id}/tisk", response_class=HTMLResponse)
def zakazka_tisk(request: Request, db: DB, zakazka_id: int):
    """Zakázkový list A4 (tisk / PDF přes prohlížeč)."""
    zakazka = zakazky.ziskej(db, zakazka_id)
    return _stranka(request, "zakazka_tisk.html", zakazka=zakazka, rek=polozky.rekapitulace(zakazka),
                    nast=nastaveni.nacti(db))


@router.post("/zakazky/{zakazka_id}/polozky", response_class=HTMLResponse)
async def zakazka_pridej_polozku(request: Request, db: DB, zakazka_id: int):
    """Přidání řádku – z ceníku (polozka_ceniku_id) nebo ručně.

    Z okna ceníku: okno zůstane otevřené s hláškou (lze přidávat dál); ruční položka z okna obnoví detail.
    """
    data = await _formular(request)
    okno = bool(data.pop("okno", ""))
    z_ceniku = bool(cisty_text(data.get("polozka_ceniku_id")))
    try:
        if z_ceniku:
            radek = polozky.pridej_z_ceniku(db, zakazka_id, int(data["polozka_ceniku_id"]),
                                            mnozstvi=data.get("mnozstvi"))
        else:
            polozky.pridej_rucne(db, zakazka_id, data)
    except ChybaValidace as e:
        db.rollback()
        if z_ceniku:
            return _okno_ceniku(request, db, zakazka_id, data.get("q", ""), okno, chyba=str(e),
                                typ=data.get("typ_okna"))
        return _formular_polozky(request, db, zakazka_id, data, okno, e)
    if z_ceniku and okno:  # Vložit v okně ceníku (#48): okno se zavře a detail zakázky obnoví s hláškou
        return _po_ulozeni_okna(zprava=f"Přidáno: {radek.nazev} ({_mnozstvi(radek.mnozstvi)} {radek.jednotka})")
    return _po_ulozeni(okno, f"/zakazky/{zakazka_id}#polozky", zprava="Položka přidána.")


@router.get("/polozky/{polozka_id}/upravit", response_class=HTMLResponse)
def polozka_upravit(request: Request, db: DB, polozka_id: int, okno: str = ""):
    """Úprava řádku zakázky: položka z ceníku se upravuje na své kartě (materiál / práce) – uloží se
    do ceníku i do řádku. Ruční položka (bez ceníku) má vlastní formulář. Množství se mění přímo v řádku."""
    radek = polozky.ziskej(db, polozka_id)
    vzor = cenik.najdi(db, radek.polozka_ceniku_id) if radek.polozka_ceniku_id else None
    if vzor:
        return _karta_ceniku(request, db, vzor, okno=bool(okno), radek=radek)
    nast = nastaveni.nacti(db)
    hodnoty = {"nazev": radek.nazev, "kod": radek.kod or "", "jednotka": radek.jednotka, "typ": radek.typ,
               "mnozstvi": _mnozstvi(radek.mnozstvi), "sazba_dph": _mnozstvi(radek.sazba_dph)} \
        | cenik.hodnoty_dvojice_cen("cena", radek.cena, radek.sazba_dph if nast.platce_dph else 0)
    return _formular_polozky(request, db, radek.zakazka_id, hodnoty, okno=bool(okno), radek=radek)


@router.post("/polozky/{polozka_id}/upravit", response_class=HTMLResponse)
async def polozka_upravit_uloz(request: Request, db: DB, polozka_id: int):
    data = await _formular(request)
    okno = bool(data.pop("okno", ""))
    data.setdefault("cena_s_dph", "")
    try:
        radek = polozky.uprav(db, polozka_id, data)
    except ChybaValidace as e:
        db.rollback()
        radek = polozky.ziskej(db, polozka_id)
        return _formular_polozky(request, db, radek.zakazka_id, data, okno, e, radek=radek)
    return _po_ulozeni(okno, f"/zakazky/{radek.zakazka_id}#polozky", zprava=f"Položka „{radek.nazev}“ uložena.")


@router.post("/polozky/{polozka_id}/mnozstvi")
async def polozka_mnozstvi(request: Request, db: DB, polozka_id: int):
    """Změna množství přímo v řádku zakázky (pole v mřížce položek)."""
    data = await _formular(request)
    radek = polozky.ziskej(db, polozka_id)
    zpet = f"/zakazky/{radek.zakazka_id}#polozky"
    try:
        polozky.uprav(db, polozka_id, {"mnozstvi": data.get("mnozstvi", "")})
    except ChybaValidace as e:
        db.rollback()
        return _presmeruj_s_chybou(zpet, e)
    return _presmeruj(zpet)


@router.post("/polozky/{polozka_id}/smazat", response_class=HTMLResponse)
async def polozka_smazat(request: Request, db: DB, polozka_id: int):
    """Odebrání řádku – z detailu zakázky (přesměrování), nebo z okna Přidat z ceníku (okno zůstane)."""
    data = await _formular(request)
    radek = polozky.ziskej(db, polozka_id)
    nazev = radek.nazev
    try:
        zakazka_id = polozky.smaz(db, polozka_id)
    except ChybaValidace as e:
        if data.get("okno"):
            return _okno_ceniku(request, db, radek.zakazka_id, data.get("q", ""), True, chyba=str(e))
        return _presmeruj_s_chybou(f"/zakazky/{radek.zakazka_id}", e)
    if data.get("okno"):
        return _okno_ceniku(request, db, zakazka_id, data.get("q", ""), True, pridano=True,
                            zprava=f"Odebráno: {nazev}")
    return _presmeruj(f"/zakazky/{zakazka_id}#polozky", "Položka odebrána.")


@router.get("/zakazky/{zakazka_id}/upravit", response_class=HTMLResponse)
def zakazka_upravit(request: Request, db: DB, zakazka_id: int, okno: str = ""):
    """Úprava zakázky ve stejném okně jako příjem (Zákazník | Zakázka | Vozidlo) – jde změnit
    i vozidlo a datum přijetí. Celá stránka, nebo s `okno=1` jen obsah okna."""
    zakazka = zakazky.ziskej(db, zakazka_id)
    if zakazka.platna_faktura:
        doklad = f"/faktury/{zakazka.platna_faktura.id}"
        return _po_ulozeni(bool(okno), doklad, doklad)
    hodnoty = {p: _iso(getattr(zakazka, p)) for p in POLE_ZAKAZKY} \
        | {"datum_prijeti": zakazka.datum_prijeti.strftime("%Y-%m-%dT%H:%M")} \
        | _hodnoty_vozidla(zakazka.vozidlo) | _hodnoty_zakaznika(zakazka.zakaznik)
    if zakazka.tachometr is None:
        hodnoty["tachometr"] = ""
    return _prijem(request, db, hodnoty, okno=bool(okno), zakazka=zakazka)


@router.post("/zakazky/{zakazka_id}/upravit", response_class=HTMLResponse)
async def zakazka_upravit_uloz(request: Request, db: DB, zakazka_id: int):
    data = await _formular(request)
    okno = bool(data.get("okno"))
    try:
        if "spz" in data:  # okno Zakázka s panely (webové formuláře)
            zakazky.uprav_z_formulare(db, zakazka_id, *_data_panelu(data))
        else:  # jednoduchá úprava bez panelů (zákazník přes výběr id / „novy“ / „bez“)
            zmeny = {p: data.get(p, "") for p in POLE_ZAKAZKY}
            if "zakaznik_id" in data:
                zmeny["zakaznik_id"] = data["zakaznik_id"]
                zmeny["zakaznik_novy"] = _s_predponou(data, "k_", POLE_ZAKAZNIKA)
            zakazky.uprav(db, zakazka_id, zmeny)
    except ChybaValidace as e:
        db.rollback()
        return _prijem(request, db, data, chyba=e, status_code=422, okno=okno,
                       zakazka=zakazky.ziskej(db, zakazka_id))
    # z okna: zůstat na stránce, odkud se okno otevřelo
    return _po_ulozeni(okno, f"/zakazky/{zakazka_id}", zprava="Zakázka uložena.")


@router.post("/zakazky/{zakazka_id}/stav")
async def zakazka_stav(request: Request, db: DB, zakazka_id: int):
    data = await _formular(request)
    zpet = data.get("zpet") or f"/zakazky/{zakazka_id}"
    try:
        zakazka = zakazky.zmen_stav(db, zakazka_id, data.get("stav", ""), bez_dokladu=bool(data.get("bez_dokladu")))
    except ChybaValidace as e:
        return _presmeruj_s_chybou(zpet, e)
    zprava = f"Stav zakázky: {zakazka.nazev_stavu}."
    if zakazka.uzavrena_bez_dokladu:
        zprava = "Zakázka uzavřena bez dokladu."
    return _presmeruj(zpet, zprava)


@router.post("/zakazky/{zakazka_id}/smazat")
def zakazka_smazat(db: DB, zakazka_id: int):
    cislo = zakazky.ziskej(db, zakazka_id).cislo
    try:
        zakazky.smaz(db, zakazka_id)
    except ChybaValidace as e:
        return _presmeruj_s_chybou(f"/zakazky/{zakazka_id}", e)
    return _presmeruj("/zakazky", f"Zakázka {cislo} smazána.")


# ---------------------------------------------------------------- vozidla

@router.get("/vozidla", response_class=HTMLResponse)
def vozidla_seznam(request: Request, db: DB, q: str = "", razeni: str = "", od: str = "", vse_radky: str = ""):
    st = vozidla.stranka(db, q, razeni=razeni, od=od, limit=_davka(vse_radky))
    return _stranka(request, "vozidla_seznam.html", aktivni="vozidla", vozidla=st.polozky, stranka=st, q=q)


LIMIT_OKNA = 200


@router.get("/vozidla/okno", response_class=HTMLResponse)
def vozidla_okno(request: Request, db: DB, q: str = "", zakaznik_id: str = "", vse: str = ""):
    """HTMX: okno „Databáze vozidel“ při příjmu – seznam s filtrem a tlačítkem Vložit.

    Je-li na příjmu vybraný zákazník (a nic se nehledá), ukáže nejdřív jeho vozidla.
    """
    q = cisty_text(q) or ""
    zakaznik = None if (q or vse) else _najdi(db, zakaznici, zakaznik_id)
    nalezena = sorted(zakaznik.vozidla, key=lambda v: v.spz) if zakaznik else []
    if not nalezena:
        zakaznik = None
        nalezena = vozidla.seznam(db, q, limit=LIMIT_OKNA)
    return _stranka(request, "_okno_vozidla.html", vozidla=nalezena, zakaznik=zakaznik, q=q, limit=LIMIT_OKNA)


def _formular_vozidla(request, vozidlo, hodnoty, zakaznik, okno=False, chyba=None):
    """Formulář vozidla – stejné pořadí polí jako panel Vozidlo na příjmu a stejný panel Zákazník
    (Firma + Vybrat / Nový). `hodnoty` mají pole vozidla bez předpony a pole zákazníka k_*."""
    if zakaznik and not any(k.startswith("k_") for k in hodnoty):
        hodnoty = dict(hodnoty) | _hodnoty_zakaznika(zakaznik)
    return _stranka(request, "vozidlo_form.html", _status_formulare(okno, chyba), aktivni="vozidla",
                    vozidlo=vozidlo, hodnoty=hodnoty, hz=hodnoty, zakaznik=zakaznik, okno=okno, chyba=chyba)


@router.get("/vozidla/nove", response_class=HTMLResponse)
def vozidlo_nove(request: Request, db: DB, zakaznik_id: int | None = None, okno: str = ""):
    zakaznik = zakaznici.ziskej(db, zakaznik_id) if zakaznik_id else None
    return _formular_vozidla(request, None, {}, zakaznik, okno=bool(okno))


@router.post("/vozidla/nove", response_class=HTMLResponse)
async def vozidlo_nove_uloz(request: Request, db: DB):
    data = await _formular(request)
    okno = bool(data.get("okno"))
    try:
        vozidlo = vozidla.vytvor(db, _data_vozidla(db, data))
    except ChybaValidace as e:
        db.rollback()
        return _formular_vozidla(request, None, data, _zakaznik_z_formulare(db, data), okno, e)
    return _po_ulozeni(okno, f"/vozidla/{vozidlo.id}", f"/vozidla/{vozidlo.id}", f"Vozidlo {vozidlo.spz} založeno.")


def _data_vozidla(db, data: dict) -> dict:
    """Údaje vozidla z formuláře včetně zákazníka.

    Panel Zákazník jako na příjmu (`panel_zakaznika`): vybraný zákazník se upraví, vyplněný nový se založí,
    prázdný panel = bez zákazníka. Starší tvar: `zakaznik_id` = id / „novy“ (pole k_*) / „bez“."""
    vysledek = {p: data.get(p, "") for p in POLE_VOZIDLA + ["zakaznik_id"]}
    if data.get("panel_zakaznika"):
        zakaznik = {"zakaznik_id": data.get("zakaznik_id"), "jako_novy": data.get("jako_novy")} \
            | _s_predponou(data, "k_", PANEL_ZAKAZNIKA)
        zakaznik_id = zakazky.zakaznik_z_panelu(db, zakaznik)
        vysledek["zakaznik_id"] = str(zakaznik_id) if zakaznik_id else "bez"
    else:
        vysledek["zakaznik_novy"] = _s_predponou(data, "k_", POLE_ZAKAZNIKA)
    return vysledek


def _zakaznik_z_formulare(db, data):
    zid = cisty_text(data.get("zakaznik_id"))
    try:
        return zakaznici.ziskej(db, int(zid)) if zid else None
    except (ValueError, LookupError):
        return None


ZALOZKY_VOZIDLA = {"zakazky": None, "prace": TypPolozky.PRACE, "material": TypPolozky.MATERIAL}


def _detail_vozidla(request, db, vozidlo_id, zalozka="", chyba=None, status_code=200):
    """Detail vozidla: údaje v panelech + historie (záložky Zakázky / Práce / Materiál jako ve starém systému)."""
    vozidlo = vozidla.ziskej(db, vozidlo_id)
    zalozka = zalozka if zalozka in ZALOZKY_VOZIDLA else "zakazky"
    historie = vozidla.historie(db, vozidlo_id)
    soucty = {z.id: polozky.rekapitulace(z) for z in historie}
    radky = vozidla.historie_polozek(db, vozidlo_id, ZALOZKY_VOZIDLA[zalozka]) if zalozka != "zakazky" else []
    # vyfakturováno = jen platné (nestornované) doklady; otevřené zakázky se ukazují zvlášť
    vyfakturovano = sum((z.platna_faktura.celkem for z in historie if z.platna_faktura), Decimal("0"))
    rozpracovano = sum((soucty[z.id].celkem for z in historie if not z.platna_faktura and z.je_otevrena),
                       Decimal("0"))
    return _stranka(request, "vozidlo_detail.html", status_code, aktivni="vozidla", vozidlo=vozidlo,
                    historie=historie, soucty=soucty, zalozka=zalozka, radky=radky, chyba=chyba,
                    pocty={t: len(vozidla.historie_polozek(db, vozidlo_id, typ)) for t, typ in ZALOZKY_VOZIDLA.items()
                           if typ},
                    vyfakturovano=vyfakturovano, rozpracovano=rozpracovano, nast=nastaveni.nacti(db))


@router.get("/vozidla/registr")
def vozidlo_z_registru(db: DB, vin: str = ""):
    """Údaje vozidla z Registru silničních vozidel (dataovozidlech.cz) pro tlačítko Načti u VIN.
    Vrací JSON {pole: {...}, jen_prazdne: [...], souhrn} nebo {chyba, pole_chyby}; formulář se doplní v prohlížeči."""
    try:
        data = registr_vozidel.nacti(nastaveni.nacti(db).api_klic_registr, vin=vin)
    except ChybaValidace as e:
        return {"chyba": str(e), "pole_chyby": e.pole}
    return {"pole": registr_vozidel.na_pole_vozidla(data), "jen_prazdne": sorted(registr_vozidel.JEN_DO_PRAZDNEHO),
            "souhrn": registr_vozidel.souhrn(data)}


@router.get("/vozidla/{vozidlo_id}", response_class=HTMLResponse)
def vozidlo_detail(request: Request, db: DB, vozidlo_id: int, zalozka: str = ""):
    return _detail_vozidla(request, db, vozidlo_id, zalozka)


@router.get("/vozidla/{vozidlo_id}/upravit", response_class=HTMLResponse)
def vozidlo_upravit(request: Request, db: DB, vozidlo_id: int, okno: str = ""):
    vozidlo = vozidla.ziskej(db, vozidlo_id)
    hodnoty = {p: _iso(getattr(vozidlo, p)) if getattr(vozidlo, p) is not None else "" for p in POLE_VOZIDLA}
    return _formular_vozidla(request, vozidlo, hodnoty, vozidlo.zakaznik, okno=bool(okno))


@router.post("/vozidla/{vozidlo_id}/upravit", response_class=HTMLResponse)
async def vozidlo_upravit_uloz(request: Request, db: DB, vozidlo_id: int):
    data = await _formular(request)
    okno = bool(data.get("okno"))
    try:
        vozidla.uprav(db, vozidlo_id, _data_vozidla(db, data))
    except ChybaValidace as e:
        db.rollback()
        return _formular_vozidla(request, vozidla.ziskej(db, vozidlo_id), data,
                                 _zakaznik_z_formulare(db, data), okno, e)
    return _po_ulozeni(okno, f"/vozidla/{vozidlo_id}", zprava="Vozidlo uloženo.")


@router.post("/vozidla/{vozidlo_id}/smazat", response_class=HTMLResponse)
def vozidlo_smazat(request: Request, db: DB, vozidlo_id: int):
    try:
        vozidla.smaz(db, vozidlo_id)
    except ChybaValidace as e:
        return _presmeruj_s_chybou(f"/vozidla/{vozidlo_id}", e)
    return _presmeruj("/vozidla", "Vozidlo smazáno.")


# ---------------------------------------------------------------- zákazníci

# ---------------------------------------------------------------- příjem vozidel (#51, jen čtení)

def _prijmy():
    """Návštěvy z OpenBotu, nebo None, když soubor nejde přečíst (stránka ukáže „dočasně nedostupný“)."""
    try:
        return prijem_vozidel.nacti()
    except prijem_vozidel.PrijemNedostupny:
        return None


@router.get("/prijem", response_class=HTMLResponse)
def prijem_seznam(request: Request):
    return _stranka(request, "prijem_seznam.html", aktivni="prijem", prijmy=_prijmy())


@router.get("/prijem/{navsteva_id}", response_class=HTMLResponse)
def prijem_detail(request: Request, navsteva_id: str):
    prijmy = _prijmy()
    navsteva = next((n for n in prijmy.navstevy if n.id == navsteva_id), None) if prijmy else None
    if prijmy is not None and navsteva is None:
        return _stranka(request, "prijem_detail.html", 404, aktivni="prijem", prijmy=prijmy, navsteva=None)
    return _stranka(request, "prijem_detail.html", aktivni="prijem", prijmy=prijmy, navsteva=navsteva)


@router.get("/zakaznici", response_class=HTMLResponse)
def zakaznici_seznam(request: Request, db: DB, q: str = "", razeni: str = "", od: str = "", vse_radky: str = ""):
    st = zakaznici.stranka(db, q, razeni=razeni, od=od, limit=_davka(vse_radky))
    return _stranka(request, "zakaznici_seznam.html", aktivni="zakaznici", zakaznici=st.polozky, stranka=st, q=q)


@router.get("/zakaznici/vyber", response_class=HTMLResponse)
def zakaznici_vyber(request: Request, db: DB, q: str = "", pole: str = "zakaznik_id",
                    novy: str = "", bez: str = "", vychozi: str = "", vybrany: str = ""):
    """HTMX: výběr zákazníka (přepínače) při příjmu, u vozidla a u zakázky.

    Bez hledaného textu ukáže naposledy přidané zákazníky (procházení databáze).
    """
    q = cisty_text(q) or ""
    nalezeni = zakaznici.seznam(db, q, limit=15) if q else zakaznici.nejnovejsi(db, 10)
    return _stranka(request, "_vyber_zakaznika_vysledky.html", nalezeni=nalezeni, pole=pole,
                    novy=novy, bez=bez, vychozi=vychozi, vybrany=vybrany, q=q)


@router.get("/zakaznici/okno", response_class=HTMLResponse)
def zakaznici_okno(request: Request, db: DB, q: str = "", pole: str = "zakaznik_id", cil: str = ""):
    """HTMX: okno „Databáze zákazníků“ – seznam s filtrem.

    Vložit nastaví zákazníka do výběru `pole` (úprava vozidla/zakázky), nebo s `cil=prijem` do panelu příjmu.
    """
    return _stranka(request, "_okno_zakaznici.html", zakaznici=zakaznici.seznam(db, q, limit=LIMIT_OKNA),
                    q=cisty_text(q) or "", pole=pole, cil=cil, limit=LIMIT_OKNA)


@router.get("/zakaznici/vyber/blok", response_class=HTMLResponse)
def zakaznici_vyber_blok(request: Request, db: DB, vybrat_id: int, pole: str = "zakaznik_id"):
    """HTMX: blok výběru zákazníka s vloženým zákazníkem z okna databáze."""
    zakaznik = zakaznici.ziskej(db, vybrat_id)
    return _stranka(request, "_blok_zakaznika.html", pole=pole, hodnoty={}, vybrany=zakaznik,
                    vychozi="bez", zprava=None, chyba=None)


def _formular_zakaznika(request, zakaznik, hodnoty, okno=False, chyba=None):
    return _stranka(request, "zakaznik_form.html", _status_formulare(okno, chyba), aktivni="zakaznici",
                    zakaznik=zakaznik, hodnoty=hodnoty, okno=okno, chyba=chyba)


@router.get("/zakaznici/ares")
def zakaznik_z_ares(ico: str = ""):
    """Údaje firmy z ARES podle IČO pro tlačítko Načti (#11). JSON {pole: {...}} nebo {chyba, pole_chyby};
    formulář se doplní v prohlížeči (příjem zakázky s předponou k_, formulář zákazníka bez)."""
    try:
        return {"pole": ares.na_pole_zakaznika(ares.nacti(ico))}
    except ChybaValidace as e:
        return {"chyba": str(e), "pole_chyby": e.pole}


@router.get("/zakaznici/novy", response_class=HTMLResponse)
def zakaznik_novy(request: Request, okno: str = ""):
    return _formular_zakaznika(request, None, {}, okno=bool(okno))


@router.post("/zakaznici/novy", response_class=HTMLResponse)
async def zakaznik_novy_uloz(request: Request, db: DB):
    data = await _formular(request)
    okno = bool(data.get("okno"))
    try:
        zakaznik = zakaznici.vytvor(db, {p: data.get(p, "") for p in POLE_ZAKAZNIKA})
    except ChybaValidace as e:
        db.rollback()
        return _formular_zakaznika(request, None, data, okno, e)
    return _po_ulozeni(okno, f"/zakaznici/{zakaznik.id}", f"/zakaznici/{zakaznik.id}",
                       f"Zákazník {zakaznik.nazev} založen.")


ZALOZKY_ZAKAZNIKA = ("vozidla", "zakazky", "doklady")


def _detail_zakaznika(request, db, zakaznik_id, zalozka="", chyba=None, status_code=200):
    """Detail zákazníka: kontakt a souhrn v panelech + záložky Vozidla / Zakázky / Doklady (historie partnera)."""
    zakaznik = zakaznici.ziskej(db, zakaznik_id)
    zalozka = zalozka if zalozka in ZALOZKY_ZAKAZNIKA else "vozidla"
    seznam_zakazek = sorted(zakaznik.zakazky, key=lambda z: z.datum_prijeti, reverse=True)
    doklady = faktury.doklady_zakaznika(db, zakaznik_id)
    return _stranka(request, "zakaznik_detail.html", status_code, aktivni="zakaznici", zakaznik=zakaznik,
                    zakazky=seznam_zakazek, doklady=doklady, zalozka=zalozka, chyba=chyba,
                    soucty={z.id: polozky.rekapitulace(z) for z in seznam_zakazek},
                    vozidla_zakaznika=sorted(zakaznik.vozidla, key=lambda v: v.spz),
                    nelze_smazat=zakaznici.duvod_proc_nesmazat(db, zakaznik),
                    neuhrazeno=sum((f.zbyva for f in doklady), Decimal("0")), nast=nastaveni.nacti(db))


@router.get("/zakaznici/{zakaznik_id}", response_class=HTMLResponse)
def zakaznik_detail(request: Request, db: DB, zakaznik_id: int, zalozka: str = ""):
    return _detail_zakaznika(request, db, zakaznik_id, zalozka)


@router.get("/zakaznici/{zakaznik_id}/upravit", response_class=HTMLResponse)
def zakaznik_upravit(request: Request, db: DB, zakaznik_id: int, okno: str = ""):
    zakaznik = zakaznici.ziskej(db, zakaznik_id)
    hodnoty = {p: getattr(zakaznik, p) or "" for p in POLE_ZAKAZNIKA}
    return _formular_zakaznika(request, zakaznik, hodnoty, okno=bool(okno))


@router.post("/zakaznici/{zakaznik_id}/upravit", response_class=HTMLResponse)
async def zakaznik_upravit_uloz(request: Request, db: DB, zakaznik_id: int):
    data = await _formular(request)
    okno = bool(data.get("okno"))
    try:
        zakaznici.uprav(db, zakaznik_id, {p: data.get(p, "") for p in POLE_ZAKAZNIKA})
    except ChybaValidace as e:
        db.rollback()
        return _formular_zakaznika(request, zakaznici.ziskej(db, zakaznik_id), data, okno, e)
    return _po_ulozeni(okno, f"/zakaznici/{zakaznik_id}", zprava="Zákazník uložen.")


@router.post("/zakaznici/{zakaznik_id}/smazat", response_class=HTMLResponse)
def zakaznik_smazat(request: Request, db: DB, zakaznik_id: int):
    try:
        zakaznici.smaz(db, zakaznik_id)
    except ChybaValidace as e:
        return _presmeruj_s_chybou(f"/zakaznici/{zakaznik_id}", e)
    return _presmeruj("/zakaznici", "Zákazník smazán.")


# ---------------------------------------------------------------- ceník

POLE_CENIKU = ["kod", "nazev", "typ", "jednotka", "cena", "sazba_dph", "zamenitelny_dil", "poznamka"]
# ceny jako dvojice polí bez DPH / s DPH (+ které pole uživatel psal naposledy)
POLE_CEN = ["cena_s", "cena_zdroj", "cena_s_dph", "nakupni_cena", "nakupni_cena_s", "nakupni_cena_zdroj"]


def _data_ceniku(data: dict) -> dict:
    return {p: data.get(p, "") for p in POLE_CENIKU + POLE_CEN if p in data or p in POLE_CENIKU}


# Dva oddělené ceníky: materiál (/cenik) a práce (/prace) – vlastní seznam, sloupce i okno.
# V databázi je to dál jedna tabulka PolozkaCeniku rozlišená typem (zakázky z ní berou obojí).

def _adresa_ceniku(typ: str) -> str:
    return "/prace" if typ == TypPolozky.PRACE else "/cenik"


def _seznam_ceniku(request, db, typ, q, neaktivni, razeni, od, vse_radky, zvyraznit):
    st = cenik.stranka(db, q, typ=typ, jen_aktivni=not neaktivni, razeni=razeni, od=od, limit=_davka(vse_radky))
    sablona = "prace_seznam.html" if typ == TypPolozky.PRACE else "cenik_seznam.html"
    return _stranka(request, sablona, aktivni="prace" if typ == TypPolozky.PRACE else "cenik", q=q, typ=typ,
                    neaktivni=neaktivni, polozky=st.polozky, stranka=st, nast=nastaveni.nacti(db), zvyraznit=zvyraznit)


@router.get("/cenik", response_class=HTMLResponse)
def cenik_seznam(request: Request, db: DB, q: str = "", typ: str = "", neaktivni: str = "",
                 razeni: str = "", od: str = "", vse_radky: str = "", zvyraznit: str = ""):
    if typ == TypPolozky.PRACE:  # starší odkazy na záložku Práce
        return RedirectResponse(f"/prace?{request.url.query}", status_code=303)
    return _seznam_ceniku(request, db, TypPolozky.MATERIAL, q, neaktivni, razeni, od, vse_radky, zvyraznit)


@router.get("/prace", response_class=HTMLResponse)
def prace_seznam(request: Request, db: DB, q: str = "", neaktivni: str = "",
                 razeni: str = "", od: str = "", vse_radky: str = "", zvyraznit: str = ""):
    return _seznam_ceniku(request, db, TypPolozky.PRACE, q, neaktivni, razeni, od, vse_radky, zvyraznit)


@router.get("/cenik/vyber", response_class=HTMLResponse)
def cenik_vyber(request: Request, db: DB, q: str = "", zakazka_id: int = 0, okno: str = "", typ: str = ""):
    """HTMX: hledání v ceníku v okně Přidat z ceníku (prázdné hledání = začátek ceníku)."""
    q = cisty_text(q) or ""
    typ = _typ_ceniku(typ)
    return _stranka(request, "_cenik_vyber_vysledky.html", q=q, zakazka_id=zakazka_id, okno=bool(okno), typ_okna=typ,
                    nalezene=cenik.seznam(db, q, typ=typ, jen_aktivni=True, limit=LIMIT_CENIKU, podle_kodu=True), limit=LIMIT_CENIKU,
                    nast=nastaveni.nacti(db))


def _z_ceniku(hodnota) -> int | None:
    """Id zakázky, z jejíhož okna Přidat z ceníku se karta položky otevřela (tlačítko Upravit)."""
    hodnota = cisty_text(hodnota)
    return int(hodnota) if hodnota and hodnota.isdigit() else None


def _formular_ceniku(request, db, polozka, hodnoty, okno=False, chyba=None, zprava=None, z_ceniku=None, q="",
                     radek=None):
    """`radek` = řádek zakázky, jehož úpravou se karta otevřela (z detailu zakázky) – po uložení
    se změny propíšou i do něj."""
    typ = polozka.typ if polozka else hodnoty.get("typ") or TypPolozky.MATERIAL
    prace = typ == TypPolozky.PRACE
    return _stranka(request, "prace_form.html" if prace else "cenik_form.html", _status_formulare(okno, chyba),
                    aktivni="zakazky" if radek else "prace" if prace else "cenik", polozka=polozka, hodnoty=hodnoty,
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


@router.get("/cenik/nova", response_class=HTMLResponse)
def cenik_nova(request: Request, db: DB, typ: str = "material", okno: str = ""):
    typ = typ if typ in TypPolozky.VSECHNY else TypPolozky.MATERIAL
    return _formular_ceniku(request, db, None, _nova_polozka_ceniku(db, typ), okno=bool(okno))


@router.get("/prace/nova", response_class=HTMLResponse)
def prace_nova(request: Request, db: DB, okno: str = ""):
    return _formular_ceniku(request, db, None, _nova_polozka_ceniku(db, TypPolozky.PRACE), okno=bool(okno))


@router.post("/cenik/nova", response_class=HTMLResponse)
@router.post("/prace/nova", response_class=HTMLResponse)
async def cenik_nova_uloz(request: Request, db: DB):
    data = await _formular(request)
    if request.url.path.startswith("/prace"):
        data["typ"] = TypPolozky.PRACE
    elif not data.get("typ"):
        data["typ"] = TypPolozky.MATERIAL
    okno = bool(data.get("okno"))
    try:
        nova = cenik.vytvor(db, _data_ceniku(data))
    except ChybaValidace as e:
        db.rollback()
        return _formular_ceniku(request, db, None, data, okno, e)
    typ = data.get("typ", "material")
    if data.get("dalsi") and okno:  # okno zůstane otevřené s prázdným formulářem
        return _formular_ceniku(request, db, None, _nova_polozka_ceniku(db, typ), okno,
                                zprava=f"Uloženo: {nova.nazev}")
    adresa = _adresa_ceniku(nova.typ)
    if data.get("dalsi"):
        return _presmeruj(f"{adresa}/nova", f"Uloženo: {nova.nazev}")
    # nová položka: seznam vyfiltrovaný na ni a řádek zvýrazněný (jinak by byla někde v abecedě)
    seznam = f"{adresa}?q={quote(nova.nazev)}&zvyraznit={nova.id}"
    return _po_ulozeni(okno, seznam, seznam, zprava=f"Položka ceníku „{nova.nazev}“ uložena.")


@router.get("/cenik/{polozka_id}/upravit", response_class=HTMLResponse)
@router.get("/prace/{polozka_id}/upravit", response_class=HTMLResponse)
def cenik_upravit(request: Request, db: DB, polozka_id: int, okno: str = "", z_ceniku: str = "", q: str = ""):
    """Karta položky ceníku. `z_ceniku` = id zakázky, když se otevřela tlačítkem Upravit v okně Přidat z ceníku
    (po uložení / Zpět se okno ceníku vrátí s hledáním `q`)."""
    return _karta_ceniku(request, db, cenik.ziskej(db, polozka_id), okno=bool(okno), z_ceniku=_z_ceniku(z_ceniku), q=q)


@router.post("/cenik/{polozka_id}/upravit", response_class=HTMLResponse)
@router.post("/prace/{polozka_id}/upravit", response_class=HTMLResponse)
async def cenik_upravit_uloz(request: Request, db: DB, polozka_id: int):
    data = await _formular(request)
    okno = bool(data.get("okno"))
    z_ceniku, q = _z_ceniku(data.get("z_ceniku")), data.get("q", "")
    radek = polozky.ziskej(db, int(data["radek"])) if cisty_text(data.get("radek", "")) else None
    try:
        polozka = cenik.uprav(db, polozka_id, _data_ceniku(data) | {"aktivni": data.get("aktivni", "")})
    except ChybaValidace as e:
        db.rollback()
        return _formular_ceniku(request, db, cenik.ziskej(db, polozka_id), data, okno, e, z_ceniku=z_ceniku, q=q,
                                radek=radek)
    if radek:  # karta otevřená úpravou řádku zakázky → změny i do řádku, pak zpět na zakázku
        zpet = f"/zakazky/{radek.zakazka_id}#polozky"
        try:
            polozky.prevezmi_z_ceniku(db, radek.id)
        except ChybaValidace as e:
            db.rollback()
            return _po_ulozeni(okno, zpet, zprava=f"Karta uložena, ale řádek zakázky ne: {e}")
        return _po_ulozeni(okno, zpet, zprava=f"Položka „{polozka.nazev}“ uložena v ceníku i na zakázce.")
    if okno and z_ceniku:  # karta otevřená z okna Přidat z ceníku → zpět do něj
        return _okno_ceniku(request, db, z_ceniku, q, okno=True, zprava=f"Karta uložena: {polozka.nazev}",
                            typ=polozka.typ)
    return _po_ulozeni(okno, _adresa_ceniku(cenik.ziskej(db, polozka_id).typ), zprava="Položka ceníku uložena.")


@router.post("/cenik/{polozka_id}/smazat")
@router.post("/prace/{polozka_id}/smazat")
async def cenik_smazat(request: Request, db: DB, polozka_id: int):
    """Smazání z ceníku; `zpet` = adresa seznamu, odkud se okno otevřelo (zachová hledání a filtr)."""
    data = await _formular(request)
    polozka = cenik.ziskej(db, polozka_id)
    nazev, adresa = polozka.nazev, _adresa_ceniku(polozka.typ)
    cenik.smaz(db, polozka_id)
    zpet = data.get("zpet") or ""
    return _presmeruj(zpet if zpet.startswith(("/cenik", "/prace")) else adresa, f"Položka ceníku „{nazev}“ smazána.")


# ---------------------------------------------------------------- nastavení

@router.get("/nastaveni", response_class=HTMLResponse)
def nastaveni_stranka(request: Request, db: DB, ulozeno: str = ""):
    return _stranka(request, "nastaveni.html", aktivni="nastaveni", nast=nastaveni.nacti(db), ulozeno=ulozeno)


@router.post("/nastaveni", response_class=HTMLResponse)
async def nastaveni_uloz(request: Request, db: DB):
    form = await request.form()
    soubor = form.get("logo_soubor")
    data = {k: str(v) for k, v in form.items() if k != "logo_soubor"}
    for zaskrtavatko in ("platce_dph", "zaokrouhlit_hotovost"):
        data.setdefault(zaskrtavatko, "")
    try:
        nastaveni.uloz(db, data)
        # logo do horní lišty: nahrané nahradí původní, „smazat logo“ ho odebere
        if getattr(soubor, "filename", None):
            nastaveni.uloz_logo(db, await soubor.read(), soubor.content_type)
        elif data.get("smazat_logo"):
            nastaveni.uloz_logo(db, None, None)
    except ChybaValidace as e:
        db.rollback()
        return _stranka(request, "nastaveni.html", 422, aktivni="nastaveni", nast=nastaveni.nacti(db),
                        chyba=e)
    return _presmeruj("/nastaveni?ulozeno=1")


# ---------------------------------------------------------------- faktury a vyúčtování

def _formular_vystaveni(request, db, zakazka, hodnoty, okno=False, chyba=None):
    return _stranka(request, "faktura_vystavit.html", _status_formulare(okno, chyba), aktivni="faktury",
                    zakazka=zakazka, hodnoty=hodnoty, nast=nastaveni.nacti(db),
                    rek=polozky.rekapitulace(zakazka), FormaUhrady=FormaUhrady, TypDokladu=TypDokladu,
                    okno=okno, chyba=chyba)


@router.get("/zakazky/{zakazka_id}/vystavit", response_class=HTMLResponse)
def faktura_vystavit(request: Request, db: DB, zakazka_id: int, typ: str = TypDokladu.FAKTURA, okno: str = ""):
    zakazka = zakazky.ziskej(db, zakazka_id)
    if zakazka.platna_faktura:
        doklad = f"/faktury/{zakazka.platna_faktura.id}"
        return _po_ulozeni(bool(okno), doklad, doklad)
    return _formular_vystaveni(request, db, zakazka, faktury.vychozi_udaje(db, zakazka_id, typ), bool(okno))


@router.post("/zakazky/{zakazka_id}/vystavit", response_class=HTMLResponse)
async def faktura_vystavit_uloz(request: Request, db: DB, zakazka_id: int):
    data = await _formular(request)
    okno = bool(data.pop("okno", ""))
    try:
        faktura = faktury.vystav(db, zakazka_id, data)
    except ChybaValidace as e:
        db.rollback()
        return _formular_vystaveni(request, db, zakazky.ziskej(db, zakazka_id), data, okno, e)
    doklad = f"/faktury/{faktura.id}"
    return _po_ulozeni(okno, doklad, doklad,
                       zprava=f"Vystaven doklad {faktura.cislo} ({faktura.nazev_typu.lower()}), zakázka uzavřena.")


def _seznam_faktur(db, filtr, q, rok, typ):
    return faktury.seznam(db, filtr or faktury.VYCHOZI_FILTR, hledat=q, rok=int(rok) if rok.isdigit() else None,
                          typ=typ or None)


@router.get("/faktury", response_class=HTMLResponse)
def faktury_seznam(request: Request, db: DB, filtr: str = faktury.VYCHOZI_FILTR, q: str = "", rok: str = "", typ: str = "",
                   razeni: str = "", od: str = "", vse_radky: str = ""):
    seznam = _seznam_faktur(db, filtr, q, rok, typ)
    st = faktury.stranka(seznam, razeni=razeni, od=od, limit=_davka(vse_radky))
    return _stranka(request, "faktury_seznam.html", aktivni="faktury", faktury=st.polozky, stranka=st,
                    souhrn=faktury.souhrn(seznam), filtr=filtr, q=q, rok=rok, typ=typ,
                    filtry=faktury.FILTRY, TypDokladu=TypDokladu, nast=nastaveni.nacti(db),
                    roky=range(date.today().year, date.today().year - 6, -1))


def _detail_faktury(request, db, faktura_id, chyba=None, status_code=200, **kontext):
    f = faktury.ziskej(db, faktura_id)
    nast = nastaveni.nacti(db)
    return _stranka(request, "faktura_detail.html", status_code, aktivni="faktury", f=f,
                    rek=faktury.rekapitulace(f), nast=nast, FormaUhrady=FormaUhrady,
                    qr=_qr(f, nast), chyba=chyba, dnes=date.today(), **kontext)


def _qr(f, nast):
    kod = faktury.spayd(f, nast)
    return faktury.qr_svg(kod) if kod else None


@router.get("/faktury/{faktura_id}", response_class=HTMLResponse)
def faktura_detail(request: Request, db: DB, faktura_id: int):
    return _detail_faktury(request, db, faktura_id)


@router.get("/faktury/{faktura_id}/tisk", response_class=HTMLResponse)
def faktura_tisk(request: Request, db: DB, faktura_id: int):
    f = faktury.ziskej(db, faktura_id)
    nast = nastaveni.nacti(db)
    return _stranka(request, "faktura_tisk.html", f=f, rek=faktury.rekapitulace(f), nast=nast,
                    iban=faktury.iban_servisu(nast), qr=_qr(f, nast))


def _formular_uhrady(request, db, faktura_id, hodnoty, okno=False, chyba=None):
    return _stranka(request, "uhrada_nova.html", _status_formulare(okno, chyba), aktivni="faktury",
                    f=faktury.ziskej(db, faktura_id), hodnoty=hodnoty, FormaUhrady=FormaUhrady, okno=okno,
                    chyba=chyba)


@router.get("/faktury/{faktura_id}/uhrady/nova", response_class=HTMLResponse)
def faktura_uhrada_nova(request: Request, db: DB, faktura_id: int, okno: str = ""):
    return _formular_uhrady(request, db, faktura_id, {}, okno=bool(okno))


@router.post("/faktury/{faktura_id}/uhrady", response_class=HTMLResponse)
async def faktura_uhrada(request: Request, db: DB, faktura_id: int):
    data = await _formular(request)
    okno = bool(data.pop("okno", ""))
    try:
        faktury.pridej_uhradu(db, faktura_id, data)
    except ChybaValidace as e:
        db.rollback()
        return _formular_uhrady(request, db, faktura_id, data, okno, e)
    return _po_ulozeni(okno, f"/faktury/{faktura_id}", zprava="Úhrada zapsána.")


@router.post("/uhrady/{uhrada_id}/smazat")
def uhrada_smazat(db: DB, uhrada_id: int):
    """Zrušení úhrady – zůstane v historii dokladu přeškrtnutá."""
    uhrada = db.get(Uhrada, uhrada_id)
    faktura_id = uhrada.faktura_id if uhrada else None
    try:
        faktura_id = faktury.zrus_uhradu(db, uhrada_id)
    except ChybaValidace as e:
        return _presmeruj_s_chybou(f"/faktury/{faktura_id}", e)
    return _presmeruj(f"/faktury/{faktura_id}", "Úhrada zrušena (zůstává v historii přeškrtnutá).")


@router.post("/faktury/{faktura_id}/storno", response_class=HTMLResponse)
def faktura_storno(request: Request, db: DB, faktura_id: int):
    try:
        f = faktury.storno(db, faktura_id)
    except ChybaValidace as e:
        return _presmeruj_s_chybou(f"/faktury/{faktura_id}", e)
    zrusene = [u for u in f.uhrady if u.zruseno and "stornem" in (u.poznamka or "")]
    zprava = "Doklad stornován, zakázka je znovu otevřená (stav Předáno)."
    if zrusene:
        zprava += " Úhrady dokladu jsou zrušené – peníze vraťte, nebo je započtěte na nový doklad."
    return _presmeruj(f"/faktury/{faktura_id}", zprava)
