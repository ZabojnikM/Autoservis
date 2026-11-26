"""API příjmu vozidel (#216) – pro Přijímacího technika: příjmy a registr vozidel ke čtení.

Příjem je jen podklad pro zakázku (SPZ, VIN, km, technické údaje), proto se ukládá bez náhledu a nezapisuje se
do deníku úprav. Vozidla, zákazníky ani zakázky tudy nejde měnit.
"""
from __future__ import annotations

from sqlmodel import Session

from app.api.spolecne import hodnota
from app.services import nastaveni, prijem_vozidel, registr_vozidel


def _prijem(session: Session, n: prijem_vozidel.Navsteva) -> dict:
    shoda = prijem_vozidel.sparuj(session, n)
    return {"id": n.id, "spz": n.spz, "vin": n.vin, "km": n.km, "revize": int(n.revision or 0),
            "vytvoreno": hodnota(n.created_at), "upraveno": hodnota(n.updated_at), "technicke": n.registr,
            "nejiste": sorted(n.nejiste), "popis": n.popis,
            "v_databazi": {"stav": shoda.stav, "vozidlo_id": shoda.vozidlo.id if shoda.vozidlo else None,
                           "upozorneni": shoda.upozorneni}}


def prijmy(session: Session) -> dict:
    navstevy = prijem_vozidel.nacti(session).navstevy
    return {"celkem": len(navstevy), "limit": prijem_vozidel.LIMIT,
            "prijmy": [_prijem(session, n) for n in navstevy]}


def uloz(session: Session, data: dict) -> dict:
    radek = prijem_vozidel.uloz(session, data)
    return {"ulozeno": True, "prijem": _prijem(session, prijem_vozidel.najdi(session, radek.id))}


def smaz(session: Session, prijem_id: str) -> dict:
    prijem_vozidel.smaz(session, prijem_id)
    return {"smazano": prijem_id}


def registr(session: Session, vin: str) -> dict:
    data = registr_vozidel.nacti(nastaveni.nacti(session).api_klic_registr, vin=vin)
    return {"data": data, "vozidlo": registr_vozidel.na_pole_vozidla(data)}
