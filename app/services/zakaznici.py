"""Zákazníci (partneři)."""
from sqlalchemy import or_
from sqlmodel import Session, func, select

from app.models import Faktura, Zakaznik
from app.services import ChybaValidace, NenalezenoError, cisty_text
from app.services.strankovani import VELIKOST_STRANKY, Stranka, strankuj_dotaz

POLE = ["nazev", "telefon", "email", "ulice", "mesto", "psc", "ico", "dic", "poznamka"]


def _nastav(zakaznik: Zakaznik, data: dict) -> None:
    for pole in POLE:
        if pole in data:
            setattr(zakaznik, pole, cisty_text(data[pole]))
    if zakaznik.ico:
        zakaznik.ico = zakaznik.ico.replace(" ", "")
    if not zakaznik.nazev:
        raise ChybaValidace("Vyplňte jméno nebo název firmy zákazníka.", "nazev")


def vytvor(session: Session, data: dict, commit: bool = True) -> Zakaznik:
    zakaznik = Zakaznik(nazev="")
    _nastav(zakaznik, data)
    session.add(zakaznik)
    if commit:
        session.commit()
        session.refresh(zakaznik)
    else:
        session.flush()
    return zakaznik


def uprav(session: Session, zakaznik_id: int, data: dict, commit: bool = True) -> Zakaznik:
    zakaznik = ziskej(session, zakaznik_id)
    _nastav(zakaznik, data)
    session.add(zakaznik)
    if commit:
        session.commit()
        session.refresh(zakaznik)
    else:
        session.flush()
    return zakaznik


def ziskej(session: Session, zakaznik_id: int) -> Zakaznik:
    zakaznik = session.get(Zakaznik, zakaznik_id)
    if zakaznik is None:
        raise NenalezenoError(f"Zákazník {zakaznik_id} neexistuje.")
    return zakaznik


def _dotaz_seznamu(hledat: str | None):
    dotaz = select(Zakaznik)
    hledat = cisty_text(hledat)
    if hledat:
        vzor = f"%{hledat}%"
        dotaz = dotaz.where(or_(
            Zakaznik.nazev.ilike(vzor),
            Zakaznik.telefon.ilike(vzor),
            Zakaznik.email.ilike(vzor),
            Zakaznik.ico.ilike(vzor),
            Zakaznik.mesto.ilike(vzor),
            Zakaznik.ulice.ilike(vzor),
        ))
    return dotaz


RAZENI = {
    "nazev": [Zakaznik.nazev.collate("cs")],
    "telefon": [Zakaznik.telefon],
    "mesto": [Zakaznik.mesto.collate("cs")],
    "adresa": [Zakaznik.mesto.collate("cs"), Zakaznik.ulice.collate("cs")],
    "ico": [Zakaznik.ico],
}


def seznam(session: Session, hledat: str | None = None, limit: int = 200) -> list[Zakaznik]:
    return list(session.exec(_dotaz_seznamu(hledat).order_by(func.lower(Zakaznik.nazev)).limit(limit)))


def stranka(session: Session, hledat: str | None = None, razeni: str | None = None, od=0,
            limit: int = VELIKOST_STRANKY) -> Stranka:
    return strankuj_dotaz(session, _dotaz_seznamu(hledat), RAZENI, razeni, "nazev", od, limit,
                          doplnkove=[Zakaznik.id])


def nejnovejsi(session: Session, limit: int = 10) -> list[Zakaznik]:
    """Naposledy přidaní zákazníci (pro procházení databáze ve výběru)."""
    return list(session.exec(select(Zakaznik).order_by(Zakaznik.id.desc()).limit(limit)))


def z_vyberu(session: Session, vyber, novy: dict | None = None) -> int | None:
    """Zákazník podle volby ve formuláři (bez commitu).

    `vyber`: id existujícího zákazníka, „novy“ (založí se z údajů `novy`), „bez“ / prázdno → None.
    """
    vyber = cisty_text(vyber)
    if vyber == "novy":
        if not cisty_text((novy or {}).get("nazev")):
            raise ChybaValidace("Vyplňte jméno nového zákazníka, nebo zvolte „Bez zákazníka“.")
        return vytvor(session, novy, commit=False).id
    if vyber in (None, "bez"):
        return None
    try:
        zakaznik_id = int(vyber)
    except ValueError:
        raise ChybaValidace("Neplatný výběr zákazníka.") from None
    ziskej(session, zakaznik_id)
    return zakaznik_id


def duvod_proc_nesmazat(session: Session, zakaznik: Zakaznik) -> str | None:
    """Proč zákazníka nejde smazat (None = smazat jde)."""
    if zakaznik.vozidla or zakaznik.zakazky:
        return "Zákazníka nelze smazat – má vozidla nebo zakázky."
    if session.exec(select(Faktura.id).where(Faktura.zakaznik_id == zakaznik.id)).first():
        return "Zákazníka nelze smazat – jsou na něj vystavené doklady."
    return None


def smaz(session: Session, zakaznik_id: int) -> None:
    zakaznik = ziskej(session, zakaznik_id)
    duvod = duvod_proc_nesmazat(session, zakaznik)
    if duvod:
        raise ChybaValidace(duvod)
    session.delete(zakaznik)
    session.commit()
