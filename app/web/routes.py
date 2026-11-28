"""Webové stránky (HTML) – spojení routerů jednotlivých oblastí (#233). Jen tenká vrstva nad app.services.

Pořadí routerů odpovídá původnímu pořadí tras (u shodných adres rozhoduje první shoda).
Společné pomůcky (DB, _stranka, _presmeruj…) jsou v `app.web.spolecne`.
"""
from fastapi import APIRouter

from app.web import cenik, faktury, nastaveni, prijem, vozidla, zakaznici, zakazky

router = APIRouter()
for _oblast in (zakazky, vozidla, prijem, zakaznici, cenik, nastaveni, faktury):
    router.include_router(_oblast.router)
