"""Katalogy materiálu (#62) – Hlavní katalog, LKQ, … Každý má vlastní díly a ceny.

Práce mají jeden společný katalog: patří do výchozího a nabízejí se vždy.
Vybraný katalog si pamatuje prohlížeč (cookie `KLIC_COOKIE`), na serveru se nic neukládá."""
from sqlmodel import Session, func, select

from app.models import Katalog, PolozkaCeniku, PolozkaZakazky
from app.services import ChybaValidace, NenalezenoError, cisty_text

KLIC_COOKIE = "katalog"


def seznam(session: Session) -> list[Katalog]:
    return list(session.exec(select(Katalog).order_by(Katalog.poradi, Katalog.id)))


def viditelne(session: Session) -> list[Katalog]:
    """#150: katalogy pro běžné nabídky (karta Materiál, okno Přidat materiál, nový díl) – bez skrytých."""
    return [k for k in seznam(session) if not k.skryty]


def viditelny(session: Session, hodnota) -> Katalog:
    """Jako `podle_id`, ale skrytý katalog (např. zapamatovaný v prohlížeči) nahradí výchozím (#150)."""
    katalog = podle_id(session, hodnota)
    return vychozi(session) if katalog.skryty else katalog


def nastav_skryti(session: Session, katalog_id: int, skryty: bool) -> Katalog:
    """#150: skrýt / znovu zobrazit katalog. Výchozí (s pracemi) skrýt nejde. Díly ani zakázky se nemění."""
    katalog = ziskej(session, katalog_id)
    if skryty and katalog.vychozi:
        raise ChybaValidace("Výchozí katalog (s pracemi) nejde skrýt.")
    katalog.skryty = skryty
    session.add(katalog)
    session.commit()
    session.refresh(katalog)
    return katalog


def vychozi(session: Session) -> Katalog:
    katalog = session.exec(select(Katalog).where(Katalog.vychozi == True).order_by(Katalog.id)).first()  # noqa: E712
    if katalog is None:  # databáze bez migrace (nemělo by nastat) – založit
        katalog = Katalog(nazev="Hlavní katalog", vychozi=True)
        session.add(katalog)
        session.commit()
        session.refresh(katalog)
    return katalog


def ziskej(session: Session, katalog_id: int) -> Katalog:
    katalog = session.get(Katalog, katalog_id)
    if katalog is None:
        raise NenalezenoError(f"Katalog {katalog_id} neexistuje.")
    return katalog


def podle_id(session: Session, hodnota) -> Katalog:
    """Katalog podle id z prohlížeče (cookie / formulář); neplatné nebo smazané id = výchozí katalog."""
    text = str(hodnota or "").strip()
    katalog = session.get(Katalog, int(text)) if text.isdigit() else None
    return katalog or vychozi(session)


def _over_nazev(session: Session, nazev, katalog_id: int | None = None) -> str:
    nazev = cisty_text(nazev)
    if not nazev:
        raise ChybaValidace("Vyplňte název katalogu.", "nazev")
    jiny = session.exec(select(Katalog).where(func.lower(Katalog.nazev) == nazev.lower())).first()
    if jiny and jiny.id != katalog_id:
        raise ChybaValidace(f"Katalog „{jiny.nazev}“ už existuje.", "nazev")
    return nazev


def vytvor(session: Session, nazev) -> Katalog:
    nazev = _over_nazev(session, nazev)
    poradi = session.exec(select(func.max(Katalog.poradi))).one() or 0
    katalog = Katalog(nazev=nazev, poradi=poradi + 1)
    session.add(katalog)
    session.commit()
    session.refresh(katalog)
    return katalog


def prejmenuj(session: Session, katalog_id: int, nazev) -> Katalog:
    katalog = ziskej(session, katalog_id)
    katalog.nazev = _over_nazev(session, nazev, katalog_id)
    session.add(katalog)
    session.commit()
    session.refresh(katalog)
    return katalog


def pocet_polozek(session: Session, katalog_id: int) -> int:
    return session.exec(select(func.count()).select_from(PolozkaCeniku)
                        .where(PolozkaCeniku.katalog_id == katalog_id)).one()


def duvod_proc_nesmazat(session: Session, katalog: Katalog) -> str | None:
    if katalog.vychozi:
        return "Výchozí katalog (s pracemi) nejde smazat."
    if pocet_polozek(session, katalog.id):
        return "Katalog obsahuje díly."
    return None


def smaz(session: Session, katalog_id: int) -> None:
    """Smazat jde jen prázdný katalog. Řádky zakázek si cenu nechají, jen ztratí název zdroje."""
    katalog = ziskej(session, katalog_id)
    duvod = duvod_proc_nesmazat(session, katalog)
    if duvod:
        raise ChybaValidace(duvod)
    for radek in session.exec(select(PolozkaZakazky).where(PolozkaZakazky.katalog_id == katalog_id)):
        radek.katalog_id = None
        session.add(radek)
    session.delete(katalog)
    session.commit()
