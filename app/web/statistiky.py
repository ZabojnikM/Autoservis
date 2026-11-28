"""Záložka Statistiky (#160): výkon servisu po měsících a za rok, běžně skrytá – zapíná se v Nastavení."""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from app.services import NenalezenoError, nastaveni, statistiky
from app.web.spolecne import DB, _stranka

VYPNUTO = "Záložka Statistiky je vypnutá. Zapnete ji v Nastavení (Statistiky)."


def _zapnuto(db: DB) -> None:
    if not nastaveni.nacti(db).statistiky:
        raise NenalezenoError(VYPNUTO)


router = APIRouter(prefix="/statistiky", dependencies=[Depends(_zapnuto)])


@router.get("", response_class=HTMLResponse)
def prehled(request: Request, db: DB, rok: str = ""):
    vybrany = int(rok) if rok.strip().isdigit() and 1990 <= int(rok) <= 2100 else None
    return _stranka(request, "statistiky.html", aktivni="statistiky", s=statistiky.statistika(db, vybrany))
