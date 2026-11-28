"""PIN pro vstup do Nastavení (#219): okno pro PIN, odemčení, zamknutí, změna PINu a ochrana adres /nastaveni."""
from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from app.db import get_session
from app.services import ChybaValidace, pin
from app.web.spolecne import DB, _formular, _po_ulozeni, _presmeruj, _presmeruj_s_chybou, _stranka, _status_formulare

router = APIRouter()
CHRANENO = "/nastaveni"


def _cil(dalsi: str | None) -> str:
    """Kam po odemčení – jen do Nastavení (žádné přesměrování ven)."""
    dalsi = (dalsi or "").strip()
    return dalsi if dalsi.startswith(CHRANENO) and "//" not in dalsi else CHRANENO


def _nastav_cookie(odpoved: Response, hodnota: str) -> Response:
    odpoved.set_cookie(pin.COOKIE, hodnota, max_age=int(pin.PLATNOST.total_seconds()), httponly=True,
                       samesite="strict", path="/")
    return odpoved


def _okno_pinu(request: Request, db, dalsi: str, okno: bool, chyba=None):
    return _stranka(request, "pin.html", _status_formulare(okno, chyba), aktivni="nastaveni", okno=okno, chyba=chyba,
                    dalsi=_cil(dalsi), nastaven=pin.nastaven(db), blokace=pin.zablokovano_do(db),
                    max_pokusu=pin.MAX_POKUSU, min_delka=pin.MIN_DELKA, max_delka=pin.MAX_DELKA)


@router.get("/pin", response_class=HTMLResponse)
def pin_okno(request: Request, db: DB, dalsi: str = CHRANENO, okno: str = ""):
    return _okno_pinu(request, db, dalsi, bool(okno))


@router.post("/pin", response_class=HTMLResponse)
async def pin_odemknout(request: Request, db: DB):
    data = await _formular(request)
    okno, dalsi = bool(data.get("okno")), _cil(data.get("dalsi"))
    try:
        if pin.nastaven(db):
            if not pin.over(db, data.get("pin")):
                raise ChybaValidace("PIN není správný.", "pin")
        else:
            pin.nastav(db, data.get("pin_novy"), data.get("pin_znovu"))
    except ChybaValidace as e:
        return _okno_pinu(request, db, dalsi, okno, e)
    return _nastav_cookie(_po_ulozeni(okno, dalsi, dalsi), pin.token(db))


@router.post("/pin/zamknout")
def pin_zamknout():
    odpoved = _presmeruj("/zakazky", "Nastavení zamčeno.")
    odpoved.delete_cookie(pin.COOKIE, path="/")
    return odpoved


@router.post("/nastaveni/pin")
async def pin_zmenit(request: Request, db: DB):
    data = await _formular(request)
    try:
        pin.nastav(db, data.get("pin_novy"), data.get("pin_znovu"), data.get("pin_stary"))
    except ChybaValidace as e:
        return _presmeruj_s_chybou("/nastaveni#pin", e)
    # podpis odemčení obsahuje otisk PINu – po změně nové odemčení
    return _nastav_cookie(_presmeruj("/nastaveni#pin", "PIN změněn."), pin.token(db))


async def ochrana_nastaveni(request: Request, call_next):
    """Middleware: /nastaveni… jen po odemčení PINem; odemčení se s každou akcí v Nastavení prodlouží."""
    if not pin.ZAPNUTO or not request.url.path.startswith(CHRANENO):
        return await call_next(request)
    zdroj = request.app.dependency_overrides.get(get_session, get_session)
    gen = zdroj()
    try:
        odemceno = pin.odemceno(next(gen), request.cookies.get(pin.COOKIE))
    finally:
        gen.close()
    if not odemceno:
        dalsi = request.url.path + (f"?{request.url.query}" if request.url.query and request.method == "GET" else "")
        cil = f"/pin?dalsi={quote(_cil(dalsi) if request.method == 'GET' else CHRANENO)}"
        if request.headers.get("hx-request"):
            return Response(status_code=204, headers={"HX-Redirect": cil})
        return RedirectResponse(cil, status_code=303)
    odpoved = await call_next(request)
    if not any(c.startswith(pin.COOKIE + "=") for c in odpoved.headers.getlist("set-cookie")):  # změna PINu už nastavila nové
        gen = zdroj()
        try:
            _nastav_cookie(odpoved, pin.token(next(gen)))
        finally:
            gen.close()
    return odpoved
