"""Webové stránky – prijem (rozděleno z routes.py, #233)."""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.services import prijem_vozidel
from app.web.spolecne import (
    DB, _stranka,
)

router = APIRouter()


# ---------------------------------------------------------------- zákazníci

# ---------------------------------------------------------------- příjem vozidel (#51, #216 – zapisuje technik přes MCP)

def _navsteva(db, navsteva_id: str):
    """(příjmy, návštěva) – návštěva None, když příjem v databázi není (mezitím smazán nebo nad limit)."""
    prijmy = prijem_vozidel.nacti(db)
    return prijmy, next((n for n in prijmy.navstevy if n.id == navsteva_id), None)


@router.get("/prijem", response_class=HTMLResponse)
def prijem_seznam(request: Request, db: DB):
    prijmy = prijem_vozidel.nacti(db)
    shody = {n.id: prijem_vozidel.sparuj(db, n) for n in prijmy.navstevy}
    return _stranka(request, "prijem_seznam.html", aktivni="prijem", prijmy=prijmy, shody=shody,
                    stavy_u_vin=prijem_vozidel.STAVY_U_VIN)


@router.get("/prijem/{navsteva_id}", response_class=HTMLResponse)
def prijem_detail(request: Request, db: DB, navsteva_id: str):
    prijmy, navsteva = _navsteva(db, navsteva_id)
    if navsteva is None:
        return _stranka(request, "prijem_detail.html", 404, aktivni="prijem", prijmy=prijmy, navsteva=None)
    shoda = prijem_vozidel.sparuj(db, navsteva) if navsteva else None
    return _stranka(request, "prijem_detail.html", aktivni="prijem", prijmy=prijmy, navsteva=navsteva, shoda=shoda,
                    stavy_u_vin=prijem_vozidel.STAVY_U_VIN)
