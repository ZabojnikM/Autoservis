"""API příjmu vozidel (#216) – pro Přijímacího technika.

Technik posílá, co přečetl z fotek a textu; databázi vozidel i Registr vozidel prohledá Autoservis a vrátí stav
s dalším krokem. Příjem je jen podklad pro zakázku, proto se ukládá bez náhledu a nezapisuje se do deníku úprav.
Vozidla, zákazníky ani zakázky tudy nejde měnit.
"""
from __future__ import annotations

from sqlmodel import Session

from app.api.spolecne import hodnota
from app.services import prijem_vozidel


def _prijem(session: Session, n: prijem_vozidel.Navsteva) -> dict:
    shoda = prijem_vozidel.sparuj(session, n)
    return {"id": n.id, "spz": n.spz, "vin": n.vin, "km": n.km, "revize": int(n.revision or 0),
            "vytvoreno": hodnota(n.created_at), "upraveno": hodnota(n.updated_at), "technicke": n.registr,
            "nejiste": sorted(n.nejiste), "popis": n.popis, "stav": n.stav, "zprava": n.zprava,
            "v_databazi": {"stav": shoda.stav, "vozidlo_id": shoda.vozidlo.id if shoda.vozidlo else None,
                           "upozorneni": shoda.upozorneni}}


def prijmy(session: Session) -> dict:
    navstevy = prijem_vozidel.nacti(session).navstevy
    return {"celkem": len(navstevy), "limit": prijem_vozidel.LIMIT,
            "prijmy": [_prijem(session, n) for n in navstevy]}


def uloz(session: Session, data: dict) -> dict:
    v = prijem_vozidel.uloz(session, data)
    return {"stav": v.stav, "zprava": v.zprava, "dalsi_krok": v.dalsi_krok, "spojeno_s_existujicim": v.spojeno,
            "opravy_vin": v.opravy_vin, "vin_z_databaze": v.vin_z_databaze,
            "prijem": _prijem(session, prijem_vozidel.najdi(session, v.radek.id))}


def smaz(session: Session, prijem_id: str) -> dict:
    prijem_vozidel.smaz(session, prijem_id)
    return {"smazano": prijem_id}
