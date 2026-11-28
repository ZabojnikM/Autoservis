"""Webové stránky – zakaznici (rozděleno z routes.py, #233)."""
from decimal import Decimal

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.services import ares
from app.services import (
    ChybaValidace, cisty_text, faktury, nastaveni, polozky, zakaznici,
)
from app.web.spolecne import (
    DB, LIMIT_OKNA, POLE_ZAKAZNIKA, _davka, _formular, _po_ulozeni, _presmeruj, _presmeruj_s_chybou, _status_formulare, _stranka,
)

router = APIRouter()


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
    # cil=doklad (#208): Vložit nastaví odběratele v okně vystavení dokladu
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
