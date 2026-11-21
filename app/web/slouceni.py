"""Stránka Sloučit díly v ceníku materiálu (#130): návrh skupin, sloučení jedné skupiny a hromadně ze seznamu CSV."""
from urllib.parse import quote

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, Response

from app.services import ChybaValidace, cisty_text, nastaveni, slouceni, zalohy
from app.web.routes import DB, _presmeruj, _stranka

router = APIRouter(prefix="/cenik/slouceni")
ADRESA = "/cenik/slouceni"


def _zpet(q: str | None) -> str:
    q = cisty_text(q)
    return ADRESA + (f"?q={quote(q)}" if q else "")


def _zaloha() -> str:
    """Záloha databáze před sloučením; když nejde udělat, nic se neslučuje."""
    try:
        return zalohy.pred_sloucenim().name
    except zalohy.ChybaZalohy as e:
        raise ChybaValidace(f"Sloučení neproběhlo, protože se nepodařilo zálohovat databázi. {e}") from e


def _str(request, db, q="", plany=None, chyba=None):
    return _stranka(request, "cenik_slouceni.html", 400 if chyba else 200, aktivni="cenik", q=q,
                    skupiny=[] if plany is not None else slouceni.navrhy(db, q),
                    nalezene=[] if plany is not None else slouceni.karty_podle_hledani(db, q),
                    plany=plany, data_planu=slouceni.do_json(plany) if plany else "",
                    nast=nastaveni.nacti(db), chyba=chyba)


@router.get("", response_class=HTMLResponse)
def stranka(request: Request, db: DB, q: str = ""):
    return _str(request, db, q)


@router.post("")
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


@router.get("/navrh.csv")
def navrh_csv(db: DB, q: str = ""):
    return Response(slouceni.navrh_csv(db, q), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="slouceni-dilu.csv"'})


@router.post("/nahled", response_class=HTMLResponse)
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


@router.post("/seznam")
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
        return _presmeruj(ADRESA, str(e), chyba=True)
    souhrn = slouceni.sluc_seznam(db, plany)
    zprava = f"{souhrn.text} Záloha: {zaloha}"
    if souhrn.chyby:
        zprava += " " + " ".join(souhrn.chyby[:3])
    return _presmeruj(ADRESA, zprava, chyba=bool(souhrn.chyby) and not souhrn.slouceni)
