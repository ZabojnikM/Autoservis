"""PIN pro vstup do Nastavení (#219).

- PIN se ukládá jen jako otisk (scrypt se solí) v tabulce `nastaveni`, nikdy v čitelné podobě.
- Odemčení platí `PLATNOST` od poslední akce v Nastavení (posuvně) a drží ho podepsaná cookie: čas konce platnosti
  a HMAC tajným klíčem aplikace (vytvoří se při prvním použití). Podpis zahrnuje otisk PINu, takže změna nebo zrušení
  PINu všechna odemčení zneplatní.
- Po `MAX_POKUSU` chybných pokusech se zadávání na `BLOKACE` zablokuje (pro celou aplikaci). Chybné pokusy
  a zablokování se zapisují do Deníku úprav.
- Zapomenutý PIN zruší Vývojář na serveru: `python -m app.nastroje.pin --zrusit`.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta

from sqlmodel import Session

from app.models import Nastaveni
from app.services import ChybaValidace, sprava

ZAPNUTO = True               # v testech mimo testy PINu vypnuto (conftest)
COOKIE = "odemceno"
PLATNOST = timedelta(minutes=30)
MAX_POKUSU = 5
BLOKACE = timedelta(minutes=5)
MIN_DELKA = 4
MAX_DELKA = 12

K_OTISK = "pin_otisk"
K_TAJNY = "pin_tajny"
K_POKUSY = "pin_pokusy"
K_BLOKACE = "pin_blokace_do"


def _cti(session: Session, klic: str) -> str:
    zaznam = session.get(Nastaveni, klic)
    return zaznam.hodnota if zaznam else ""


def _zapis(session: Session, klic: str, hodnota: str) -> None:
    zaznam = session.get(Nastaveni, klic) or Nastaveni(klic=klic)
    zaznam.hodnota = hodnota
    session.add(zaznam)


def _otisk(pin: str, sul: bytes) -> str:
    return hashlib.scrypt(pin.encode(), salt=sul, n=2 ** 14, r=8, p=1, dklen=32).hex()


def nastaven(session: Session) -> bool:
    return bool(_cti(session, K_OTISK))


def _kontrola_tvaru(pin: str | None) -> str:
    pin = (pin or "").strip()
    if not pin.isdigit() or not MIN_DELKA <= len(pin) <= MAX_DELKA:
        raise ChybaValidace(f"PIN musí mít {MIN_DELKA} až {MAX_DELKA} číslic.", "pin_novy")
    return pin


def nastav(session: Session, novy: str | None, znovu: str | None, stary: str | None = None) -> None:
    """Nastaví nový PIN (2× zadaný). Když už PIN existuje, je potřeba zadat ten současný."""
    if nastaven(session):
        if not over(session, stary):
            raise ChybaValidace("Současný PIN není správně.", "pin_stary")
    novy = _kontrola_tvaru(novy)
    if novy != (znovu or "").strip():
        raise ChybaValidace("Nový PIN a jeho zopakování se neshodují.", "pin_znovu")
    sul = secrets.token_bytes(16)
    _zapis(session, K_OTISK, f"scrypt${sul.hex()}${_otisk(novy, sul)}")
    _zapis(session, K_POKUSY, "0")
    session.commit()
    sprava.zapis(session, "PIN", "Nastaven nový PIN pro vstup do Nastavení.", 0)


def zrus(session: Session) -> bool:
    """Zruší PIN (zapomenutý PIN – příkaz na serveru). Vrací, jestli nějaký byl."""
    byl = nastaven(session)
    for klic in (K_OTISK, K_POKUSY, K_BLOKACE):
        zaznam = session.get(Nastaveni, klic)
        if zaznam:
            session.delete(zaznam)
    session.commit()
    if byl:
        sprava.zapis(session, "PIN", "PIN zrušen na serveru (zapomenutý PIN).", 0)
    return byl


def zablokovano_do(session: Session, ted: datetime | None = None) -> datetime | None:
    hodnota = _cti(session, K_BLOKACE)
    try:
        do = datetime.fromisoformat(hodnota) if hodnota else None
    except ValueError:
        return None
    return do if do and do > (ted or datetime.now()) else None


def over(session: Session, pin: str | None, ted: datetime | None = None) -> bool:
    """Správný PIN? Počítá chybné pokusy a po MAX_POKUSU zablokuje zadávání na BLOKACE (ChybaValidace)."""
    ted = ted or datetime.now()
    do = zablokovano_do(session, ted)
    if do:
        raise ChybaValidace(f"Po {MAX_POKUSU} chybných pokusech je zadávání PINu zablokované do {do:%H:%M}.", "pin")
    ulozeny = _cti(session, K_OTISK)
    try:
        _, sul, otisk = ulozeny.split("$")
        spravne = hmac.compare_digest(_otisk((pin or "").strip(), bytes.fromhex(sul)), otisk)
    except ValueError:
        spravne = False
    if spravne:
        _zapis(session, K_POKUSY, "0")
        session.commit()
        return True
    pokusy = int(_cti(session, K_POKUSY) or 0) + 1
    if pokusy >= MAX_POKUSU:
        konec = ted + BLOKACE
        _zapis(session, K_BLOKACE, konec.isoformat(timespec="seconds"))
        _zapis(session, K_POKUSY, "0")
        session.commit()
        sprava.zapis(session, "PIN", f"{MAX_POKUSU}× chybný PIN – zadávání zablokované do {konec:%H:%M}.", pokusy)
    else:
        _zapis(session, K_POKUSY, str(pokusy))
        session.commit()
        sprava.zapis(session, "PIN", f"Chybný PIN (pokus {pokusy} z {MAX_POKUSU}).", pokusy)
    return False


def _tajny(session: Session) -> bytes:
    tajny = _cti(session, K_TAJNY)
    if not tajny:
        tajny = secrets.token_hex(32)
        _zapis(session, K_TAJNY, tajny)
        session.commit()
    return bytes.fromhex(tajny)


def _podpis(session: Session, konec: int) -> str:
    zprava = f"{konec}.{_cti(session, K_OTISK)}".encode()
    return hmac.new(_tajny(session), zprava, hashlib.sha256).hexdigest()


def token(session: Session, ted: datetime | None = None) -> str:
    """Hodnota cookie odemčení s platností PLATNOST od teď."""
    konec = int(((ted or datetime.now()) + PLATNOST).timestamp())
    return f"{konec}.{_podpis(session, konec)}"


def odemceno(session: Session, hodnota: str | None, ted: datetime | None = None) -> bool:
    if not hodnota or not nastaven(session):
        return False
    try:
        konec_text, podpis = hodnota.split(".", 1)
        konec = int(konec_text)
    except ValueError:
        return False
    if konec < (ted or datetime.now()).timestamp():
        return False
    return hmac.compare_digest(podpis, _podpis(session, konec))
