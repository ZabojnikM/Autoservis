"""Webové stránky – vozidla (rozděleno z routes.py, #233)."""
from decimal import Decimal

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.models import TypPolozky
from app.services import prijem_vozidel
from app.services import (
    ChybaValidace, cisty_text, nastaveni, polozky, registr_vozidel,
    vozidla,
    zakaznici,
    zakazky,
)
from app.web.spolecne import (
    DB, LIMIT_OKNA, PANEL_ZAKAZNIKA, POLE_VOZIDLA, POLE_ZAKAZNIKA, _davka, _formular, _hodnoty_zakaznika, _iso, _najdi, _po_ulozeni, _presmeruj, _presmeruj_s_chybou, _s_predponou, _status_formulare, _stranka,
)

router = APIRouter()


# ---------------------------------------------------------------- vozidla

@router.get("/vozidla", response_class=HTMLResponse)
def vozidla_seznam(request: Request, db: DB, q: str = "", razeni: str = "", od: str = "", vse_radky: str = ""):
    st = vozidla.stranka(db, q, razeni=razeni, od=od, limit=_davka(vse_radky))
    return _stranka(request, "vozidla_seznam.html", aktivni="vozidla", vozidla=st.polozky, stranka=st, q=q)


@router.get("/vozidla/okno", response_class=HTMLResponse)
def vozidla_okno(request: Request, db: DB, q: str = "", zakaznik_id: str = "", vse: str = "", cil: str = ""):
    """HTMX: okno „Databáze vozidel“ při příjmu – seznam s filtrem a tlačítkem Vložit.

    Je-li na příjmu vybraný zákazník (a nic se nehledá), ukáže nejdřív jeho vozidla.
    cil=doklad (#208): vždy všechna vozidla, vozidla odběratele nahoře; Vložit nastaví vozidlo dokladu.
    """
    q = cisty_text(q) or ""
    zakaznik = None if (q or vse) else _najdi(db, zakaznici, zakaznik_id)
    nalezena = sorted(zakaznik.vozidla, key=lambda v: v.spz) if zakaznik else []
    if cil == "doklad":
        jeho = {v.id for v in nalezena}
        nalezena += [v for v in vozidla.seznam(db, q, limit=LIMIT_OKNA) if v.id not in jeho]
        if not jeho:
            zakaznik = None
    elif not nalezena:
        zakaznik = None
        nalezena = vozidla.seznam(db, q, limit=LIMIT_OKNA)
    return _stranka(request, "_okno_vozidla.html", vozidla=nalezena, zakaznik=zakaznik, q=q, limit=LIMIT_OKNA,
                    cil=cil, pocet_jeho=len(zakaznik.vozidla) if zakaznik else 0)


def _formular_vozidla(request, vozidlo, hodnoty, zakaznik, okno=False, chyba=None):
    """Formulář vozidla – stejné pořadí polí jako panel Vozidlo na příjmu a stejný panel Zákazník
    (Firma + Vybrat / Nový). `hodnoty` mají pole vozidla bez předpony a pole zákazníka k_*."""
    if zakaznik and not any(k.startswith("k_") for k in hodnoty):
        hodnoty = dict(hodnoty) | _hodnoty_zakaznika(zakaznik)
    return _stranka(request, "vozidlo_form.html", _status_formulare(okno, chyba), aktivni="vozidla",
                    vozidlo=vozidlo, hodnoty=hodnoty, hz=hodnoty, zakaznik=zakaznik, okno=okno, chyba=chyba)


@router.get("/vozidla/nove", response_class=HTMLResponse)
def vozidlo_nove(request: Request, db: DB, zakaznik_id: int | None = None, okno: str = "", prijem: str = ""):
    """Nové vozidlo; s `prijem` (id návštěvy z Příjmu vozidel) předvyplněné SPZ, VIN a údaji z registru."""
    zakaznik = zakaznici.ziskej(db, zakaznik_id) if zakaznik_id else None
    hodnoty = {}
    navsteva = prijem_vozidel.najdi(db, prijem) if prijem else None
    if navsteva:
        hodnoty = {k: v for k, v in registr_vozidel.na_pole_vozidla(navsteva.registr).items() if k in POLE_VOZIDLA}
        hodnoty |= {"spz": vozidla.normalizuj_spz(navsteva.spz), "z_prijmu": "1"}
        if navsteva.vin:
            hodnoty["vin"] = vozidla.normalizuj_vin(navsteva.vin)
    return _formular_vozidla(request, None, hodnoty, zakaznik, okno=bool(okno))


@router.post("/vozidla/nove", response_class=HTMLResponse)
async def vozidlo_nove_uloz(request: Request, db: DB):
    data = await _formular(request)
    okno = bool(data.get("okno"))
    try:
        vozidlo = vozidla.vytvor(db, _data_vozidla(db, data))
    except ChybaValidace as e:
        db.rollback()
        return _formular_vozidla(request, None, data, _zakaznik_z_formulare(db, data), okno, e)
    zprava = f"Vozidlo {vozidlo.spz} založeno."
    if data.get("z_prijmu"):  # založeno z Příjmu vozidel → zpět na seznam příjmů (řádek už ukáže „V databázi“)
        return _po_ulozeni(okno, "/prijem", None, zprava)
    return _po_ulozeni(okno, f"/vozidla/{vozidlo.id}", f"/vozidla/{vozidlo.id}", zprava)


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
