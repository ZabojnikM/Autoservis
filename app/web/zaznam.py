"""Nastavení → Záznam událostí (#225): posledních 200 záznamů, filtr Jen chyby, stažení souboru. Pod PINem (#219)."""
from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse

from app import zaznam
from app.web.spolecne import _stranka

router = APIRouter(prefix="/nastaveni/zaznam")
POCET = 200


@router.get("", response_class=HTMLResponse)
def stranka(request: Request, jen_chyby: str = ""):
    zaznamy = zaznam.posledni(POCET, jen_chyby=bool(jen_chyby))
    return _stranka(request, "nastaveni_zaznam.html", aktivni="nastaveni", zaznamy=zaznamy, pocet=len(zaznamy),
                    jen_chyby=bool(jen_chyby), soubor_nazev=f"logs/{zaznam.aktualni_soubor().name}")


@router.get("/stahnout")
def stahnout():
    soubor = zaznam.aktualni_soubor()
    if not soubor.is_file():
        return PlainTextResponse("Záznam událostí je zatím prázdný.", status_code=404)
    return FileResponse(soubor, media_type="text/plain; charset=utf-8", filename="autoservis.log")
