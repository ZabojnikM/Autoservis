"""Položky zakázky (práce a materiál) a součty s DPH."""
from dataclasses import dataclass, field
from decimal import Decimal

from sqlmodel import Session

from app.models import PolozkaZakazky, TypPolozky, Zakazka, zaokrouhli
from app.services import ChybaValidace, NenalezenoError, cisty_text, desetinne_nebo_none
from app.services import cenik as cenik_sluzba
from app.services import nastaveni as nastaveni_sluzba
from app.services import zakazky as zakazky_sluzba


def _otevrena_zakazka(session: Session, zakazka_id: int) -> Zakazka:
    zakazka = zakazky_sluzba.ziskej(session, zakazka_id)
    if not zakazka.je_otevrena:
        raise ChybaValidace("Uzavřenou zakázku nelze měnit – nejdřív změňte stav.")
    return zakazka


def _kladne_mnozstvi(hodnota) -> Decimal:
    mnozstvi = desetinne_nebo_none(hodnota, "Množství", "mnozstvi")
    if mnozstvi is None:
        mnozstvi = Decimal("1")
    if mnozstvi == 0:
        raise ChybaValidace("Množství nesmí být 0.", "mnozstvi")
    return mnozstvi


def _je(hodnota) -> bool:
    return hodnota in (True, "1", "on", "true")


def pridej_z_ceniku(
    session: Session, zakazka_id: int, polozka_ceniku_id: int, mnozstvi="1", cena=None, commit: bool = True
) -> PolozkaZakazky:
    """Přidá položku z ceníku (cena z ceníku, nebo `cena`, je-li zadaná)."""
    zakazka = _otevrena_zakazka(session, zakazka_id)
    vzor = cenik_sluzba.ziskej(session, polozka_ceniku_id)
    nast = nastaveni_sluzba.nacti(session)
    mnozstvi = _kladne_mnozstvi(mnozstvi)

    radek = PolozkaZakazky(
        zakazka_id=zakazka.id, polozka_ceniku_id=vzor.id, typ=vzor.typ, kod=vzor.kod,
        nazev=vzor.nazev, jednotka=vzor.jednotka, mnozstvi=mnozstvi, cena=vzor.cena,
        sazba_dph=vzor.sazba_dph if nast.platce_dph else Decimal("0"),
    )
    vlastni_cena = desetinne_nebo_none(cena, "Cena")
    if vlastni_cena is not None:
        radek.cena = vlastni_cena
    session.add(radek)
    if commit:
        session.commit()
        session.refresh(radek)
    return radek


def vloz_z_ceniku(session: Session, zakazka_id: int, vyber: list[tuple]) -> list[PolozkaZakazky]:
    """Okno Přidat z ceníku → Vložit: všechny vybrané položky (id ceníku, množství) najednou.
    Buď se vloží všechny, nebo (při chybě) žádná."""
    if not vyber:
        raise ChybaValidace("Není vybraná žádná položka.")
    try:
        radky = [pridej_z_ceniku(session, zakazka_id, int(pid), mnozstvi=mnozstvi, commit=False)
                 for pid, mnozstvi in vyber]
        session.commit()
    except (ValueError, NenalezenoError) as e:
        session.rollback()
        raise ChybaValidace(f"Položku ceníku se nepodařilo vložit ({e}).") from e
    except Exception:
        session.rollback()
        raise
    for radek in radky:
        session.refresh(radek)
    return radky


def pridej_rucne(session: Session, zakazka_id: int, data: dict) -> PolozkaZakazky:
    """Ruční položka. `ulozit_do_ceniku` ji zároveň založí v ceníku."""
    zakazka = _otevrena_zakazka(session, zakazka_id)
    nast = nastaveni_sluzba.nacti(session)
    radek = PolozkaZakazky(zakazka_id=zakazka.id, nazev="")
    try:
        _nastav_radek(radek, data, nast, novy=True)
        if _je(data.get("ulozit_do_ceniku")):
            v_ceniku = cenik_sluzba.vytvor(session, {
                "nazev": radek.nazev, "kod": radek.kod, "typ": radek.typ, "jednotka": radek.jednotka,
                "cena": radek.cena, "sazba_dph": radek.sazba_dph if nast.platce_dph else nast.vychozi_dph,
            }, commit=False)
            radek.polozka_ceniku_id = v_ceniku.id
        session.add(radek)
        session.commit()
    except Exception:
        session.rollback()
        raise
    session.refresh(radek)
    return radek


def _nastav_radek(radek: PolozkaZakazky, data: dict, nast, novy: bool = False) -> None:
    if "typ" in data or novy:
        typ = data.get("typ") or TypPolozky.MATERIAL
        if typ not in TypPolozky.VSECHNY:
            raise ChybaValidace("Typ musí být práce, nebo materiál.")
        radek.typ = typ
    if "nazev" in data or novy:
        radek.nazev = cisty_text(data.get("nazev")) or ""
        if not radek.nazev:
            raise ChybaValidace("Vyplňte název položky.", "nazev")
    if "kod" in data:
        radek.kod = cisty_text(data["kod"])
    if "jednotka" in data or novy:
        radek.jednotka = cisty_text(data.get("jednotka")) or ("hod" if radek.typ == TypPolozky.PRACE else "ks")
    if "mnozstvi" in data or novy:
        radek.mnozstvi = _kladne_mnozstvi(data.get("mnozstvi"))
    if not nast.platce_dph:
        radek.sazba_dph = Decimal("0")
    elif "sazba_dph" in data or novy:
        sazba = desetinne_nebo_none(data.get("sazba_dph"), "Sazba DPH", "sazba_dph")
        radek.sazba_dph = nast.vychozi_dph if sazba is None else sazba
        if not 0 <= radek.sazba_dph < 100:
            raise ChybaValidace("Sazba DPH musí být 0–99 %.", "sazba_dph")
    if "cena" in data or novy:
        cena = desetinne_nebo_none(data.get("cena"), "Cena", "cena")
        if cena is None:
            raise ChybaValidace("Vyplňte cenu za jednotku.", "cena")
        radek.cena = cenik_sluzba.cena_bez_dph(cena, radek.sazba_dph, _je(data.get("cena_s_dph")))


def uprav(session: Session, polozka_id: int, data: dict) -> PolozkaZakazky:
    radek = ziskej(session, polozka_id)
    _otevrena_zakazka(session, radek.zakazka_id)
    _nastav_radek(radek, data, nastaveni_sluzba.nacti(session))
    session.add(radek)
    session.commit()
    session.refresh(radek)
    return radek


def prevezmi_z_ceniku(session: Session, polozka_id: int) -> PolozkaZakazky:
    """Po úpravě karty ceníku z detailu zakázky: řádek převezme typ, kód, název, jednotku, cenu a DPH
    z (upravené) položky ceníku. Množství zůstane."""
    radek = ziskej(session, polozka_id)
    _otevrena_zakazka(session, radek.zakazka_id)
    if radek.zakazka.platna_faktura:
        raise ChybaValidace("Zakázka je vyúčtovaná – řádek nejde změnit.")
    if radek.polozka_ceniku_id is None:
        raise ChybaValidace("Položka není z ceníku.")
    vzor = cenik_sluzba.ziskej(session, radek.polozka_ceniku_id)
    nast = nastaveni_sluzba.nacti(session)
    radek.typ, radek.kod, radek.nazev, radek.jednotka, radek.cena = \
        vzor.typ, vzor.kod, vzor.nazev, vzor.jednotka, vzor.cena
    radek.sazba_dph = vzor.sazba_dph if nast.platce_dph else Decimal("0")
    session.add(radek)
    session.commit()
    session.refresh(radek)
    return radek


def ziskej(session: Session, polozka_id: int) -> PolozkaZakazky:
    radek = session.get(PolozkaZakazky, polozka_id)
    if radek is None:
        raise NenalezenoError(f"Položka {polozka_id} neexistuje.")
    return radek


def smaz(session: Session, polozka_id: int) -> int:
    """Smaže řádek a vrátí id zakázky."""
    radek = ziskej(session, polozka_id)
    zakazka_id = radek.zakazka_id
    _otevrena_zakazka(session, zakazka_id)
    session.delete(radek)
    session.commit()
    return zakazka_id


@dataclass
class Rekapitulace:
    prace: Decimal = Decimal("0")
    material: Decimal = Decimal("0")
    zaklady: dict[Decimal, Decimal] = field(default_factory=dict)  # sazba → základ
    dane: dict[Decimal, Decimal] = field(default_factory=dict)     # sazba → DPH

    @property
    def bez_dph(self) -> Decimal:
        return self.prace + self.material

    @property
    def dph(self) -> Decimal:
        return sum(self.dane.values(), Decimal("0"))

    @property
    def celkem(self) -> Decimal:
        return self.bez_dph + self.dph


def rekapitulace(zakazka: Zakazka) -> Rekapitulace:
    return rekapitulace_radku(zakazka.polozky)


def rekapitulace_radku(radky) -> Rekapitulace:
    """Součty řádků (zakázky i faktury). DPH se počítá ze součtu základů pro každou sazbu."""
    rek = Rekapitulace()
    for radek in radky:
        if radek.typ == TypPolozky.PRACE:
            rek.prace += radek.zaklad
        else:
            rek.material += radek.zaklad
        sazba = radek.sazba_dph.normalize() if radek.sazba_dph else Decimal("0")
        rek.zaklady[sazba] = rek.zaklady.get(sazba, Decimal("0")) + radek.zaklad
    for sazba, zaklad in sorted(rek.zaklady.items(), reverse=True):
        rek.dane[sazba] = zaokrouhli(zaklad * sazba / 100)
    return rek
