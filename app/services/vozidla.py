"""Vozidla."""
import re
from datetime import date, datetime

from sqlalchemy import or_
from sqlmodel import Session, col, func, select

from app.models import PolozkaZakazky, Vozidlo, Zakazka, Zakaznik
from app.services import ChybaValidace, NenalezenoError, cislo_nebo_none, cisty_text
from app.services.strankovani import VELIKOST_STRANKY, Stranka, strankuj_dotaz
from app.services import zakaznici

POLE_TEXT = ["znacka", "model", "palivo", "motor", "kod_motoru", "objem", "vykon", "cislo_motoru", "olej",
             "barva", "poznamka"]
POLE_DATUM = ["datum_registrace", "termin_stk"]
# všechna pole vozidla, která jdou zadat ve formulářích
POLE = ["spz", "vin", "znacka", "model", "rok_vyroby", "datum_registrace", "kod_motoru", "objem", "vykon", "palivo", "cislo_motoru",
        "olej", "barva", "termin_stk", "motor", "poznamka"]


def normalizuj_spz(spz: str | None) -> str:
    """'1ab 23-45' → '1AB2345'."""
    return re.sub(r"[\s\-]", "", spz or "").upper()


def normalizuj_vin(vin: str | None) -> str | None:
    vin = re.sub(r"\s", "", vin or "").upper()
    return vin or None


def _nastav(session: Session, vozidlo: Vozidlo, data: dict) -> None:
    if "spz" in data:
        vozidlo.spz = normalizuj_spz(data["spz"])
    if not vozidlo.spz:
        raise ChybaValidace("Vyplňte SPZ vozidla.", "spz")
    if "vin" in data:
        vozidlo.vin = normalizuj_vin(data["vin"])
    if vozidlo.vin and len(vozidlo.vin) != 17:
        raise ChybaValidace("VIN musí mít 17 znaků.", "vin")
    for pole in POLE_TEXT:
        if pole in data:
            setattr(vozidlo, pole, cisty_text(data[pole]))
    if "rok_vyroby" in data:
        vozidlo.rok_vyroby = cislo_nebo_none(data["rok_vyroby"], "Rok výroby", "rok_vyroby")
        if vozidlo.rok_vyroby is not None and not 1900 <= vozidlo.rok_vyroby <= date.today().year + 1:
            raise ChybaValidace(f"Rok výroby {vozidlo.rok_vyroby} není možný.", "rok_vyroby")
    for pole, nazev in (("datum_registrace", "Datum 1. registrace"), ("termin_stk", "Termín STK")):
        if pole in data:
            setattr(vozidlo, pole, _datum(data[pole], nazev, pole))

    with session.no_autoflush:
        jina = session.exec(select(Vozidlo).where(Vozidlo.spz == vozidlo.spz)).first()
        if jina and jina.id != vozidlo.id:
            raise ChybaValidace(f"Vozidlo se SPZ {vozidlo.spz} už v evidenci je.", "spz")
        if vozidlo.vin:
            jina = session.exec(select(Vozidlo).where(Vozidlo.vin == vozidlo.vin)).first()
            if jina and jina.id != vozidlo.id:
                raise ChybaValidace(f"Vozidlo s VIN {vozidlo.vin} už v evidenci je (SPZ {jina.spz}).", "vin")

    # zákazník až po kontrolách – založení nového zapisuje do databáze
    if "zakaznik_id" in data:
        # id / „novy“ (údaje v data["zakaznik_novy"]) / „bez“
        vozidlo.zakaznik_id = zakaznici.z_vyberu(session, data["zakaznik_id"], data.get("zakaznik_novy"))


def _datum(hodnota, nazev: str, pole: str | None = None) -> date | None:
    if isinstance(hodnota, date):
        return hodnota
    hodnota = cisty_text(hodnota)
    if hodnota is None:
        return None
    for fmt in ("%Y-%m-%d", "%d.%m.%Y"):
        try:
            return datetime.strptime(hodnota.replace(" ", ""), fmt).date()
        except ValueError:
            pass
    raise ChybaValidace(f"{nazev}: neplatné datum „{hodnota}“.", pole)


def vytvor(session: Session, data: dict, commit: bool = True) -> Vozidlo:
    vozidlo = Vozidlo(spz="")
    _nastav(session, vozidlo, data)
    session.add(vozidlo)
    if commit:
        session.commit()
        session.refresh(vozidlo)
    else:
        session.flush()
    return vozidlo


def uprav(session: Session, vozidlo_id: int, data: dict, commit: bool = True) -> Vozidlo:
    vozidlo = ziskej(session, vozidlo_id)
    _nastav(session, vozidlo, data)
    session.add(vozidlo)
    if commit:
        session.commit()
        session.refresh(vozidlo)
    else:
        session.flush()
    return vozidlo


def ziskej(session: Session, vozidlo_id: int) -> Vozidlo:
    vozidlo = session.get(Vozidlo, vozidlo_id)
    if vozidlo is None:
        raise NenalezenoError(f"Vozidlo {vozidlo_id} neexistuje.")
    return vozidlo


def najdi_podle_spz(session: Session, spz: str) -> Vozidlo | None:
    spz = normalizuj_spz(spz)
    if not spz:
        return None
    return session.exec(select(Vozidlo).where(Vozidlo.spz == spz)).first()


def _dotaz_seznamu(hledat: str | None):
    """Hledá podle SPZ, VIN, značky, modelu, kódu motoru i jména zákazníka."""
    dotaz = select(Vozidlo).outerjoin(Zakaznik, Zakaznik.id == Vozidlo.zakaznik_id)
    hledat = cisty_text(hledat)
    if hledat:
        vzor = f"%{hledat}%"
        vzor_kod = f"%{normalizuj_spz(hledat)}%"
        dotaz = dotaz.where(or_(
            Vozidlo.spz.ilike(vzor_kod),
            Vozidlo.vin.ilike(vzor_kod),
            Vozidlo.znacka.ilike(vzor),
            Vozidlo.model.ilike(vzor),
            Vozidlo.kod_motoru.ilike(vzor),
            Vozidlo.cislo_motoru.ilike(vzor),
            Zakaznik.nazev.ilike(vzor),
        ))
    return dotaz


RAZENI = {
    "spz": [Vozidlo.spz],
    "vozidlo": [Vozidlo.znacka.collate("cs"), Vozidlo.model.collate("cs")],
    "znacka": [Vozidlo.znacka.collate("cs"), Vozidlo.model.collate("cs")],
    "model": [Vozidlo.model.collate("cs"), Vozidlo.znacka.collate("cs")],
    "kod_motoru": [Vozidlo.kod_motoru.collate("cs")],
    "typ_vozidla": [Vozidlo.cislo_motoru.collate("cs")],
    "rok": [Vozidlo.rok_vyroby],
    "vin": [Vozidlo.vin],
    "zakaznik": [Zakaznik.nazev.collate("cs")],
}


def seznam(session: Session, hledat: str | None = None, limit: int = 200) -> list[Vozidlo]:
    return list(session.exec(_dotaz_seznamu(hledat).order_by(Vozidlo.spz).limit(limit)))


def stranka(session: Session, hledat: str | None = None, razeni: str | None = None, od=0,
            limit: int = VELIKOST_STRANKY) -> Stranka:
    return strankuj_dotaz(session, _dotaz_seznamu(hledat), RAZENI, razeni, "spz", od, limit,
                          doplnkove=[Vozidlo.id])


def historie(session: Session, vozidlo_id: int) -> list[Zakazka]:
    """Všechny zakázky vozidla, nejnovější první (při stejném čase přijetí později založená)."""
    return list(session.exec(
        select(Zakazka).where(Zakazka.vozidlo_id == vozidlo_id)
        .order_by(col(Zakazka.datum_prijeti).desc(), col(Zakazka.id).desc())
    ))


def historie_polozek(session: Session, vozidlo_id: int, typ: str | None = None) -> list[PolozkaZakazky]:
    """Materiál a práce ze všech zakázek vozidla (historie vozidla jako ve starém systému), nejnovější první."""
    dotaz = select(PolozkaZakazky).join(Zakazka, PolozkaZakazky.zakazka_id == Zakazka.id) \
        .where(Zakazka.vozidlo_id == vozidlo_id)
    if typ:
        dotaz = dotaz.where(PolozkaZakazky.typ == typ)
    return list(session.exec(dotaz.order_by(col(Zakazka.datum_prijeti).desc(), col(Zakazka.id).desc(),
                                            PolozkaZakazky.id)))


def smaz(session: Session, vozidlo_id: int) -> None:
    vozidlo = ziskej(session, vozidlo_id)
    if vozidlo.zakazky:
        raise ChybaValidace("Vozidlo nelze smazat – má zakázky (historie vozidla).")
    session.delete(vozidlo)
    session.commit()
