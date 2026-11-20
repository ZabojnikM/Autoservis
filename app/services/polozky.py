"""Položky zakázky (práce a materiál) a součty s DPH."""
from dataclasses import dataclass, field
from decimal import Decimal

from sqlmodel import Session, select

from app.models import PolozkaZakazky, TypPolozky, Zakazka, zaokrouhli
from app.services import ChybaValidace, NenalezenoError, cisty_text, desetinne_nebo_none
from app.services import cenik as cenik_sluzba
from app.services import katalogy
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
    if mnozstvi <= 0:  # záporné množství (vratky) se nepoužívá – zakázáno (#33)
        raise ChybaValidace("Množství musí být větší než 0.", "mnozstvi")
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
        katalog_id=_katalog_radku(vzor),
    )
    vlastni_cena = desetinne_nebo_none(cena, "Cena")
    if vlastni_cena is not None:
        radek.cena = vlastni_cena
    session.add(radek)
    if commit:
        session.commit()
        session.refresh(radek)
    return radek


def _katalog_radku(vzor) -> int | None:
    """Zdrojový katalog řádku – jen u materiálu (práce mají jeden společný katalog)."""
    return vzor.katalog_id if vzor.typ == TypPolozky.MATERIAL else None


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


class KodUzVCeniku(ChybaValidace):
    """Ruční položka se má uložit do ceníku, ale její kód už v ceníku je – nabídne se použít existující."""

    def __init__(self, polozka):
        super().__init__(f"Kód {polozka.kod} už v ceníku má „{polozka.nazev}“ – použijte ji z ceníku, "
                         "nebo zrušte „uložit i do ceníku“.", "kod")
        self.polozka = polozka


def _do_ceniku(session: Session, data: dict, typ: str):
    """Založí položku ceníku z polí ruční položky (stejná pole jako karta Materiál / Práce).
    Materiál jde do katalogu `katalog_id` (vybraný v prohlížeči), práce do společného (#62)."""
    katalog = (katalogy.vychozi(session) if typ == TypPolozky.PRACE
               else katalogy.podle_id(session, data.get("katalog_id")))
    existujici = cenik_sluzba.najdi_podle_kodu(session, data.get("kod"), katalog.id)
    if existujici:
        raise KodUzVCeniku(existujici)
    pole = {k: v for k, v in data.items() if k not in ("mnozstvi", "ulozit_do_ceniku", "okno", "cena_s_dph")}
    return cenik_sluzba.vytvor(session, pole | {"typ": typ, "katalog_id": katalog.id}, commit=False)


def pridej_rucne(session: Session, zakazka_id: int, data: dict) -> PolozkaZakazky:
    """Ruční položka (pole jako karta Materiál / Práce + množství).

    `ulozit_do_ceniku` ji nejdřív založí v ceníku a řádek pak vznikne z ní (jako z okna Přidat z ceníku),
    takže úprava řádku z detailu zakázky pak upraví i ceník. Kód, který už v ceníku je → KodUzVCeniku."""
    zakazka = _otevrena_zakazka(session, zakazka_id)
    nast = nastaveni_sluzba.nacti(session)
    radek = PolozkaZakazky(zakazka_id=zakazka.id, nazev="")
    try:
        _nastav_radek(radek, data, nast, novy=True)  # kontrola polí a množství i při ukládání do ceníku
        if _je(data.get("ulozit_do_ceniku")):
            v_ceniku = _do_ceniku(session, data, radek.typ)
            radek = pridej_z_ceniku(session, zakazka.id, v_ceniku.id, mnozstvi=data.get("mnozstvi"), commit=False)
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
    # cena jako na kartě ceníku: dvojice bez DPH / s DPH (cena, cena_s, cena_zdroj), starší tvar zaškrtnutím
    zadano, cena = cenik_sluzba.cena_z_dvojice(data, "cena", "Cena", radek.sazba_dph)
    if zadano or novy:
        if cena is None:
            raise ChybaValidace("Vyplňte cenu za jednotku.", "cena")
        s_dph = data.get("cena_zdroj") != "s" and _je(data.get("cena_s_dph"))
        radek.cena = cenik_sluzba.cena_bez_dph(cena, radek.sazba_dph, s_dph)
        if radek.cena < 0:
            raise ChybaValidace("Cena nemůže být záporná.", "cena")


def uprav(session: Session, polozka_id: int, data: dict) -> PolozkaZakazky:
    """Úprava řádku. Ruční řádek (bez ceníku) s `ulozit_do_ceniku` se zároveň založí v ceníku a propojí."""
    radek = ziskej(session, polozka_id)
    _otevrena_zakazka(session, radek.zakazka_id)
    try:
        _nastav_radek(radek, data, nastaveni_sluzba.nacti(session))
        if _je(data.get("ulozit_do_ceniku")) and radek.polozka_ceniku_id is None:
            vzor = _do_ceniku(session, data, radek.typ)
            radek.polozka_ceniku_id, radek.katalog_id = vzor.id, _katalog_radku(vzor)
        session.add(radek)
        session.commit()
    except Exception:
        session.rollback()
        raise
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
    radek.katalog_id = _katalog_radku(vzor)
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


# ---------------------------------------------------------------- materiál z historie vozidla (#69)

@dataclass
class RadekHistorie:
    """Díl dříve vydaný na vozidlo – jeden řádek na díl (nejnovější výskyt a počet použití)."""
    radek: PolozkaZakazky          # nejnovější výskyt ve starší zakázce
    zakazka: Zakazka               # zakázka nejnovějšího výskytu
    vzor: object | None            # aktuální karta ceníku (je-li díl v ceníku), jinak None
    pocet: int = 1                 # v kolika řádcích starších zakázek se díl objevil

    @property
    def cena(self) -> Decimal:
        """Cena pro vložení: aktuální z ceníku, jinak ze starší zakázky."""
        return self.vzor.cena if self.vzor else self.radek.cena

    @property
    def sazba_dph(self) -> Decimal:
        return self.vzor.sazba_dph if self.vzor else self.radek.sazba_dph


def _klic_historie(radek: PolozkaZakazky):
    if radek.polozka_ceniku_id:
        return ("cenik", radek.polozka_ceniku_id)
    return ("rucne", (radek.kod or "").casefold(), radek.nazev.casefold())


def _odpovida(radek: PolozkaZakazky, hledat: str) -> bool:
    text = hledat.casefold()
    kod = "".join(z for z in text if z not in " .-/")
    kod_radku = "".join(z for z in (radek.kod or "").casefold() if z not in " .-/")
    return text in radek.nazev.casefold() or text in (radek.kod or "").casefold() or bool(kod and kod in kod_radku)


def historie_vozidla(session: Session, zakazka: Zakazka, hledat: str | None = None) -> list[RadekHistorie]:
    """Materiál ze starších zakázek vozidla aktuální zakázky (bez ní samé).
    Řazení (#115): přesná shoda kódu s hledáním nahoře, pak podle počtu použití na vozidle,
    při stejném počtu novější výš."""
    if not zakazka.vozidlo_id:
        return []
    dotaz = (select(PolozkaZakazky, Zakazka).join(Zakazka, PolozkaZakazky.zakazka_id == Zakazka.id)
             .where(Zakazka.vozidlo_id == zakazka.vozidlo_id, Zakazka.id != zakazka.id,
                    PolozkaZakazky.typ == TypPolozky.MATERIAL)
             .order_by(Zakazka.datum_prijeti.desc(), Zakazka.id.desc(), PolozkaZakazky.id.desc()))
    hledat = cisty_text(hledat)
    vysledek: dict = {}
    for radek, z in session.exec(dotaz):
        if hledat and not _odpovida(radek, hledat):
            continue
        klic = _klic_historie(radek)
        if klic in vysledek:
            vysledek[klic].pocet += 1
        else:
            vzor = cenik_sluzba.najdi(session, radek.polozka_ceniku_id) if radek.polozka_ceniku_id else None
            vysledek[klic] = RadekHistorie(radek, z, vzor)
    hledany_kod = "".join(z for z in (hledat or "").casefold() if z not in " .-/")

    def presne(h: RadekHistorie) -> bool:
        return bool(hledany_kod) and "".join(z for z in (h.radek.kod or "").casefold() if z not in " .-/") == hledany_kod

    # řádky jsou od nejnovějšího – stabilní řazení zachová novější výš při stejném počtu
    return sorted(vysledek.values(), key=lambda h: (not presne(h), -h.pocet))


def pridej_z_historie(session: Session, zakazka_id: int, radek_id: int, mnozstvi="1") -> PolozkaZakazky:
    """Vloží díl ze starší zakázky: je-li v ceníku, jako z ceníku (aktuální cena),
    jinak kopie starého řádku (jeho cena) se zadaným množstvím."""
    zakazka = _otevrena_zakazka(session, zakazka_id)
    puvodni = ziskej(session, radek_id)
    if puvodni.zakazka.vozidlo_id is None or puvodni.zakazka.vozidlo_id != zakazka.vozidlo_id:
        raise ChybaValidace("Položka nepatří do historie vozidla této zakázky.")
    vzor = cenik_sluzba.najdi(session, puvodni.polozka_ceniku_id) if puvodni.polozka_ceniku_id else None
    if vzor:
        return pridej_z_ceniku(session, zakazka_id, vzor.id, mnozstvi=mnozstvi)
    nast = nastaveni_sluzba.nacti(session)
    radek = PolozkaZakazky(
        zakazka_id=zakazka.id, typ=puvodni.typ, kod=puvodni.kod, nazev=puvodni.nazev, jednotka=puvodni.jednotka,
        mnozstvi=_kladne_mnozstvi(mnozstvi), cena=puvodni.cena,
        sazba_dph=puvodni.sazba_dph if nast.platce_dph else Decimal("0"), katalog_id=puvodni.katalog_id,
    )
    session.add(radek)
    session.commit()
    session.refresh(radek)
    return radek
