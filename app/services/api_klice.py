"""Klíče pro API a MCP (#145): vytvoření, zrušení, ověření a oprávnění.

API je ve výchozím stavu vypnuté (Nastavení → API pro boty). Klíč má tvar `as_<náhodný text>`, v databázi je jen
jeho otisk SHA-256 – kdo klíč ztratí, vytvoří nový a starý zruší.
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime

from sqlmodel import Session, select

from app.models import ApiKlic, Nastaveni
from app.services import ChybaValidace, NenalezenoError, cisty_text

OPRAVNENI = {"sklad": "Sklad (ceník, hromadné úpravy)", "zakazky": "Zakázky a jejich řádky",
             "vozidla": "Vozidla, zákazníci a příjem zakázky"}
KLIC_ZAPNUTO = "api_zapnuto"


class ChybaPristupu(Exception):
    """Chybějící / neplatný klíč (401) nebo chybějící oprávnění (403)."""

    def __init__(self, zprava: str, kod: int = 401):
        super().__init__(zprava)
        self.kod = kod


def zapnuto(session: Session) -> bool:
    zaznam = session.get(Nastaveni, KLIC_ZAPNUTO)
    return bool(zaznam and zaznam.hodnota == "1")


def nastav_zapnuto(session: Session, zapnout: bool) -> None:
    zaznam = session.get(Nastaveni, KLIC_ZAPNUTO) or Nastaveni(klic=KLIC_ZAPNUTO)
    zaznam.hodnota = "1" if zapnout else "0"
    session.add(zaznam)
    session.commit()


def _otisk(klic: str) -> str:
    return hashlib.sha256(klic.encode()).hexdigest()


def seznam(session: Session) -> list[ApiKlic]:
    return list(session.exec(select(ApiKlic).order_by(ApiKlic.aktivni.desc(), ApiKlic.id)))


def vytvor(session: Session, nazev, opravneni) -> tuple[ApiKlic, str]:
    """Nový klíč → (záznam, klíč v čitelné podobě – ukáže se jen teď)."""
    nazev = cisty_text(nazev)
    if not nazev:
        raise ChybaValidace("Vyplňte název klíče (např. Skladník).", "nazev")
    opravneni = [o for o in opravneni if o in OPRAVNENI]
    if not opravneni:
        raise ChybaValidace("Zaškrtněte aspoň jedno oprávnění.")
    klic = "as_" + secrets.token_urlsafe(32)
    zaznam = ApiKlic(nazev=nazev, otisk=_otisk(klic), zacatek=klic[:7], opravneni=",".join(opravneni))
    session.add(zaznam)
    session.commit()
    session.refresh(zaznam)
    return zaznam, klic


def zrus(session: Session, klic_id: int) -> None:
    zaznam = session.get(ApiKlic, klic_id)
    if zaznam is None:
        raise NenalezenoError("Klíč neexistuje.")
    zaznam.aktivni = False
    session.add(zaznam)
    session.commit()


def over(session: Session, hlavicka: str | None, opravneni: str | None = None) -> ApiKlic:
    """Hlavička `Authorization: Bearer <klíč>` → aktivní klíč s požadovaným oprávněním, jinak ChybaPristupu."""
    if not zapnuto(session):
        raise ChybaPristupu("API je vypnuté. Zapnete ho v Nastavení → API pro boty.", 403)
    hlavicka = (hlavicka or "").strip()
    klic = hlavicka[7:].strip() if hlavicka.lower().startswith("bearer ") else hlavicka
    if not klic:
        raise ChybaPristupu("Chybí klíč (hlavička Authorization: Bearer …).")
    zaznam = session.exec(select(ApiKlic).where(ApiKlic.otisk == _otisk(klic))).first()
    if zaznam is None or not zaznam.aktivni:
        raise ChybaPristupu("Neplatný nebo zrušený klíč.")
    if opravneni and opravneni not in zaznam.seznam_opravneni:
        raise ChybaPristupu(f"Klíč „{zaznam.nazev}“ nemá oprávnění „{OPRAVNENI.get(opravneni, opravneni)}“.", 403)
    zaznam.naposledy = datetime.now()
    session.add(zaznam)
    session.commit()
    return zaznam
