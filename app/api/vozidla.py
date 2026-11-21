"""API vozidel, zákazníků a příjmu zakázky (#147) – připraveno pro Přijímacího technika.

Zápis jde přes stejné služby jako formuláře aplikace (stejné kontroly SPZ, VIN, duplicit). Každý zápis se
zapíše do deníku úprav s názvem klíče.
"""
from __future__ import annotations

from sqlmodel import Session

from app.api.spolecne import denik, hodnota
from app.api.zakazky import _zakazka
from app.models import ApiKlic, Vozidlo, Zakaznik
from app.services import ChybaValidace, vozidla as vozidla_sluzba, zakaznici as zakaznici_sluzba, zakazky as zakazky_sluzba

POLE_VOZIDLA = vozidla_sluzba.POLE + ["zakaznik_id"]
POLE_ZAKAZNIKA = zakaznici_sluzba.POLE
POLE_ZAKAZKY = ["pozadavek", "tachometr", "poznamka", "termin_dokonceni", "vozidlo_id", "zakaznik_id"]


def _vozidlo(v: Vozidlo) -> dict:
    return {"id": v.id, "spz": v.spz, "vin": v.vin, "znacka": v.znacka, "model": v.model, "popis": v.popis,
            "rok_vyroby": v.rok_vyroby, "datum_registrace": hodnota(v.datum_registrace), "palivo": v.palivo,
            "kod_motoru": v.kod_motoru, "objem": v.objem, "vykon": v.vykon, "cislo_motoru": v.cislo_motoru,
            "olej": v.olej, "barva": v.barva, "termin_stk": hodnota(v.termin_stk), "motor": v.motor,
            "poznamka": v.poznamka, "zakaznik_id": v.zakaznik_id, "zakaznik": v.zakaznik.nazev if v.zakaznik else None}


def _zakaznik(z: Zakaznik) -> dict:
    return {"id": z.id} | {p: getattr(z, p) for p in POLE_ZAKAZNIKA}


def _data(data: dict | None, pole: list[str]) -> dict:
    data = data or {}
    nezname = sorted(k for k in data if k not in pole)
    if nezname:
        raise ChybaValidace(f"Neznámá pole: {', '.join(nezname)}. Povolená: {', '.join(pole)}.")
    return {k: ("" if v is None else str(v)) for k, v in data.items()}


def vozidla(session: Session, q: str | None = None, limit: int = 50) -> dict:
    """Hledání podle SPZ, VIN, značky, modelu nebo zákazníka."""
    vysledek = vozidla_sluzba.seznam(session, q, limit=max(1, min(int(limit or 50), 500)))
    return {"pocet": len(vysledek), "vozidla": [_vozidlo(v) for v in vysledek]}


def vozidlo(session: Session, vozidlo_id: int) -> dict:
    v = vozidla_sluzba.ziskej(session, vozidlo_id)
    return _vozidlo(v) | {"zakazky": [_zakazka(z) for z in vozidla_sluzba.historie(session, v.id)]}


def vytvor_vozidlo(session: Session, klic: ApiKlic | None, data: dict) -> dict:
    v = vozidla_sluzba.vytvor(session, _data(data, POLE_VOZIDLA))
    denik(session, klic, "Nové vozidlo", f"{v.spz} {v.popis}", 1)
    return _vozidlo(v)


def uprav_vozidlo(session: Session, klic: ApiKlic | None, vozidlo_id: int, data: dict) -> dict:
    v = vozidla_sluzba.uprav(session, vozidlo_id, _data(data, POLE_VOZIDLA))
    denik(session, klic, "Úprava vozidla", f"{v.spz}: {', '.join(sorted(data))}", 1)
    return _vozidlo(v)


def zakaznici(session: Session, q: str | None = None, limit: int = 50) -> dict:
    vysledek = zakaznici_sluzba.seznam(session, q, limit=max(1, min(int(limit or 50), 500)))
    return {"pocet": len(vysledek), "zakaznici": [_zakaznik(z) for z in vysledek]}


def zakaznik(session: Session, zakaznik_id: int) -> dict:
    z = zakaznici_sluzba.ziskej(session, zakaznik_id)
    return _zakaznik(z) | {"vozidla": [_vozidlo(v) for v in z.vozidla],
                           "zakazky": [_zakazka(x) for x in sorted(z.zakazky, key=lambda x: x.datum_prijeti, reverse=True)[:50]]}


def vytvor_zakaznika(session: Session, klic: ApiKlic | None, data: dict) -> dict:
    z = zakaznici_sluzba.vytvor(session, _data(data, POLE_ZAKAZNIKA))
    denik(session, klic, "Nový zákazník", z.nazev, 1)
    return _zakaznik(z)


def uprav_zakaznika(session: Session, klic: ApiKlic | None, zakaznik_id: int, data: dict) -> dict:
    z = zakaznici_sluzba.uprav(session, zakaznik_id, _data(data, POLE_ZAKAZNIKA))
    denik(session, klic, "Úprava zákazníka", f"{z.nazev}: {', '.join(sorted(data))}", 1)
    return _zakaznik(z)


def prijem(session: Session, klic: ApiKlic | None, zakazka: dict, vozidlo: dict | None = None,
           zakaznik: dict | None = None) -> dict:
    """Příjem nové zakázky. Vozidlo: `zakazka.vozidlo_id`, nebo SPZ ve `vozidlo` (neexistující se založí).
    Zákazník: `zakaznik.id` existující, `zakaznik.nazev` nový, `zakaznik.vyber = "bez"` bez zákazníka,
    nic = zákazník vozidla."""
    zakaznik = dict(zakaznik or {})
    zid = zakaznik.pop("id", None)
    vyber = zakaznik.pop("vyber", None)
    data_zakaznika = _data(zakaznik, POLE_ZAKAZNIKA)
    if zid:
        data_zakaznika["vyber"] = str(zid)
    elif vyber == "bez":
        data_zakaznika["vyber"] = "bez"
    elif data_zakaznika.get("nazev"):
        data_zakaznika["vyber"] = "novy"
    z = zakazky_sluzba.prijem(session, zakazka=_data(zakazka, POLE_ZAKAZKY),
                              vozidlo=_data(vozidlo, vozidla_sluzba.POLE), zakaznik=data_zakaznika)
    denik(session, klic, "Příjem zakázky", f"{z.cislo} {z.vozidlo.spz if z.vozidlo else 'bez vozidla'}", 1)
    return _zakazka(z)
