"""Nastavení → API pro boty (#145): zapnutí API a MCP, klíče s oprávněními."""
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.services import ChybaValidace, api_klice
from app.web.spolecne import DB, _presmeruj, _stranka

router = APIRouter(prefix="/nastaveni/api")


def _str(request, db, novy_klic: str = "", novy_nazev: str = "", chyba=None):
    return _stranka(request, "nastaveni_api.html", 422 if chyba else 200, aktivni="nastaveni",
                    zapnuto=api_klice.zapnuto(db), klice=api_klice.seznam(db), opravneni=api_klice.OPRAVNENI,
                    novy_klic=novy_klic, novy_nazev=novy_nazev, adresa=str(request.base_url).rstrip("/"), chyba=chyba)


@router.get("", response_class=HTMLResponse)
def stranka(request: Request, db: DB):
    return _str(request, db)


@router.post("/zapnout")
async def zapnout(request: Request, db: DB):
    form = await request.form()
    api_klice.nastav_zapnuto(db, bool(form.get("zapnuto")))
    return _presmeruj("/nastaveni/api", "API je zapnuté." if form.get("zapnuto") else "API je vypnuté.")


@router.post("/klice", response_class=HTMLResponse)
async def novy(request: Request, db: DB):
    form = await request.form()
    try:
        zaznam, klic = api_klice.vytvor(db, form.get("nazev"), form.getlist("opravneni"))
    except ChybaValidace as e:
        return _str(request, db, chyba=e)
    # klíč se ukáže jen teď – stránka se nepřesměruje, ať ho jde zkopírovat
    return _str(request, db, novy_klic=klic, novy_nazev=zaznam.nazev)


@router.post("/klice/{klic_id}/zrusit")
def zrusit(db: DB, klic_id: int):
    api_klice.zrus(db, klic_id)
    return _presmeruj("/nastaveni/api", "Klíč je zrušený.")
