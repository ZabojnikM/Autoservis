"""Záložka Správa dat (#132): hromadné úpravy skladu a databáze, běžně skrytá – zapíná se v Nastavení.

Funkce:
- Sloučit díly (#130): návrh skupin, sloučení jedné skupiny a hromadně ze seznamu CSV.
"""
from urllib.parse import quote

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, Response

from app.services import ChybaValidace, NenalezenoError, cisty_text, nastaveni, slouceni, zalohy
from app.web.routes import DB, _presmeruj, _stranka

VYPNUTO = "Záložka Správa dat je vypnutá. Zapnete ji v Nastavení (Správa dat)."


def _zapnuto(db: DB) -> None:
    if not nastaveni.nacti(db).sprava_dat:
        raise NenalezenoError(VYPNUTO)


router = APIRouter(prefix="/sprava-dat", dependencies=[Depends(_zapnuto)])
SLOUCENI = "/sprava-dat/slouceni-dilu"

# rozcestník: (adresa, název, popis) – sem přibývají další importy a hromadné úpravy
FUNKCE = [
    (SLOUCENI, "Sloučit díly",
     "Stejný díl vedený v ceníku pod více kódy sloučí do jednoho kódu – i ve starých zakázkách, ceny zůstanou."),
]


@router.get("", response_class=HTMLResponse)
def rozcestnik(request: Request, db: DB):
    return _stranka(request, "sprava_dat.html", aktivni="sprava", funkce=FUNKCE)


# ---------------------------------------------------------------- Sloučit díly (#130)

def _zpet(q: str | None) -> str:
    q = cisty_text(q)
    return SLOUCENI + (f"?q={quote(q)}" if q else "")


def _zaloha() -> str:
    """Záloha databáze před sloučením; když nejde udělat, nic se neslučuje."""
    try:
        return zalohy.pred_sloucenim().name
    except zalohy.ChybaZalohy as e:
        raise ChybaValidace(f"Sloučení neproběhlo, protože se nepodařilo zálohovat databázi. {e}") from e


def _str(request, db, q="", plany=None, chyba=None):
    return _stranka(request, "sprava_slouceni.html", 400 if chyba else 200, aktivni="sprava", q=q,
                    skupiny=[] if plany is not None else slouceni.navrhy(db, q),
                    nalezene=[] if plany is not None else slouceni.karty_podle_hledani(db, q),
                    plany=plany, data_planu=slouceni.do_json(plany) if plany else "",
                    nast=nastaveni.nacti(db), chyba=chyba)


@router.get("/slouceni-dilu", response_class=HTMLResponse)
def slouceni_stranka(request: Request, db: DB, q: str = ""):
    return _str(request, db, q)


@router.post("/slouceni-dilu")
async def sluc(request: Request, db: DB):
    form = await request.form()
    q = form.get("q") or ""
    try:
        cil = cisty_text(form.get("cil"))
        if not cil or not cil.isdigit():
            raise ChybaValidace("Vyberte kartu, která zůstane (Ponechat).")
        ids = [int(v) for v in form.getlist("karty") if str(v).isdigit()]
        if len(set(ids) | {int(cil)}) < 2:
            raise ChybaValidace("Vyberte aspoň dvě karty ke sloučení.")
        zaloha = _zaloha()
        vysledek = slouceni.sluc(db, int(cil), ids, form.get("kod"), form.get("nazev"), form.get("cena"))
    except ChybaValidace as e:
        db.rollback()
        return _presmeruj(_zpet(q), str(e), chyba=True)
    return _presmeruj(_zpet(q), f"{vysledek.text} Záloha: {zaloha}")


@router.get("/slouceni-dilu/navrh.csv")
def navrh_csv(db: DB, q: str = ""):
    return Response(slouceni.navrh_csv(db, q), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="slouceni-dilu.csv"'})


@router.post("/slouceni-dilu/nahled", response_class=HTMLResponse)
async def nahled(request: Request, db: DB):
    form = await request.form()
    soubor = form.get("soubor")
    try:
        plany = slouceni.nacti_csv(db, await soubor.read() if hasattr(soubor, "read") else b"")
        if not plany:
            raise ChybaValidace("V seznamu není žádná skupina ke sloučení (sloupec Sloučit = ano).")
    except ChybaValidace as e:
        return _str(request, db, chyba=e)
    return _str(request, db, plany=plany)


@router.post("/slouceni-dilu/seznam")
async def sluc_seznam(request: Request, db: DB):
    form = await request.form()
    try:
        plany = slouceni.z_json(str(form.get("data_planu") or ""))
        vybrane = set(form.getlist("vybrano"))
        plany = [p for p in plany if p.skupina in vybrane]
        if not any(not p.chyba for p in plany):
            raise ChybaValidace("Není vybraná žádná skupina bez chyby.")
        zaloha = _zaloha()
    except ChybaValidace as e:
        return _presmeruj(SLOUCENI, str(e), chyba=True)
    souhrn = slouceni.sluc_seznam(db, plany)
    zprava = f"{souhrn.text} Záloha: {zaloha}"
    if souhrn.chyby:
        zprava += " " + " ".join(souhrn.chyby[:3])
    return _presmeruj(SLOUCENI, zprava, chyba=bool(souhrn.chyby) and not souhrn.slouceno)
