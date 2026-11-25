"""Doklady: faktura (daňový doklad) a vyúčtování zakázky.

Doklad se vystavuje ze zakázky a zakázku uzavře. Po vystavení se nemění – jen úhrady. Chybný doklad se smaže
(#15): jeho číslo zůstane v přehledu jako „Volné po smazání“ a jde ho ručně použít při dalším vystavení.
Faktura: úhrada převodem nebo hotově. Částka k úhradě se zaokrouhluje na celé koruny (vypnout jde v Nastavení).
Vyúčtování (#55): formu úhrady nemá, jen stav Uhrazeno / Neuhrazeno; QR platba z vlastního účtu v Nastavení.
"""
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload
from sqlmodel import Session, col, select

from app.models import (
    Faktura, FormaUhrady, PolozkaFaktury, SmazaneCislo, StavZakazky, TypDokladu, Uhrada, Vozidlo, Zakaznik,
    zaokrouhli,
)
from app.services import ChybaValidace, NenalezenoError, cisty_text, desetinne_nebo_none
from app.services import nastaveni as nastaveni_sluzba
from app.services import polozky as polozky_sluzba
from app.services import vozidla as vozidla_sluzba
from app.services import zakaznici as zakaznici_sluzba
from app.services import zakazky as zakazky_sluzba
from app.db import cesky_klic
from app.services.strankovani import VELIKOST_STRANKY, Stranka, strankuj_seznam
from app.services.zakazky import parsuj_datum

POLE_ODBERATELE = ["odb_nazev", "odb_ulice", "odb_mesto", "odb_psc", "odb_ico", "odb_dic"]

# ---------------------------------------------------------------- číselné řady


def predpona_rady(vzor: str, rok: int) -> str:
    """'FV{RRRR}' → 'FV2026', 'F{RR}-' → 'F26-'."""
    return vzor.replace("{RRRR}", str(rok)).replace("{RR}", f"{rok % 100:02d}")


def predpona_dokladu(session: Session, typ: str, rok: int | None = None) -> str:
    """Předpona řady daného typu dokladu pro rok (FV2026 / VY2026) – pevná část čísla."""
    nast = nastaveni_sluzba.nacti(session)
    vzor = nast.rada_faktura if typ == TypDokladu.FAKTURA else nast.rada_vyuctovani
    return predpona_rady(vzor, rok or date.today().year)


def dalsi_cislo(session: Session, typ: str, rok: int | None = None) -> str:
    """Další číslo řady = nejvyšší použité + 1. Počítají se i smazaná čísla (#15) – smazaný poslední
    doklad se tak automaticky znovu nenabídne a ruční doplnění starší mezery číslování nevrátí zpět."""
    predpona = predpona_dokladu(session, typ, rok)
    existujici = list(session.exec(select(Faktura.cislo).where(col(Faktura.cislo).startswith(predpona)))) \
        + list(session.exec(select(SmazaneCislo.cislo).where(col(SmazaneCislo.cislo).startswith(predpona))))
    poradi = [int(c[len(predpona):]) for c in existujici if c[len(predpona):].isdigit()]
    return f"{predpona}{(max(poradi) + 1) if poradi else 1:0{nastaveni_sluzba.nacti(session).cifry_cisla}d}"


def volna_cisla(session: Session, typ: str | None = None, rok: int | None = None) -> list[SmazaneCislo]:
    """Čísla smazaných dokladů, která se zatím znovu nepoužila (pro přehled a formulář vystavení)."""
    dotaz = select(SmazaneCislo)
    if typ:
        dotaz = dotaz.where(SmazaneCislo.typ == typ)
        if rok:
            dotaz = dotaz.where(col(SmazaneCislo.cislo).startswith(predpona_dokladu(session, typ, rok)))
    return list(session.exec(dotaz.order_by(col(SmazaneCislo.cislo))))


def cislo_z_poradi(session: Session, typ: str, rok: int, poradi: str) -> str:
    """Ručně zadané pořadové číslo (jen číslice za předponou řady) → celé číslo dokladu.
    Ověří tvar a že číslo ještě nemá jiný doklad."""
    nast = nastaveni_sluzba.nacti(session)
    poradi = re.sub(r"\s", "", poradi or "")
    if not re.fullmatch(r"\d+", poradi) or len(poradi) > nast.cifry_cisla or int(poradi) == 0:
        raise ChybaValidace(f"Číslo dokladu: zadejte pořadové číslo – nejvýš {nast.cifry_cisla} číslice "
                            f"(např. {1:0{nast.cifry_cisla}d}).", "poradi")
    cislo = f"{predpona_dokladu(session, typ, rok)}{int(poradi):0{nast.cifry_cisla}d}"
    if session.exec(select(Faktura.id).where(Faktura.cislo == cislo)).first():
        raise ChybaValidace(f"Číslo {cislo} už má jiný doklad – zvolte jiné.", "poradi")
    return cislo


def variabilni_symbol(cislo: str, typ: str = TypDokladu.FAKTURA) -> str:
    """Číslice z čísla dokladu, nejvýš 10. Vyúčtování má navíc na začátku 9,
    aby se nepotkalo s fakturou stejného pořadí (FV20260002 → 20260002, VY20260002 → 920260002)."""
    cislice = re.sub(r"\D", "", cislo)
    if typ == TypDokladu.VYUCTOVANI:
        return "9" + cislice[-9:]
    return cislice[-10:]


def _jedinecny_vs(session: Session, vs: str) -> str:
    """Variabilní symbol nesmí mít jiný doklad (jinak nejde spárovat platbu). Při shodě
    (např. starší doklady z importu) se před číslo přidá další číslice 8, 7…"""
    kandidat = vs
    for predpona in "87654321":
        if not session.exec(select(Faktura.id).where(Faktura.variabilni_symbol == kandidat)).first():
            return kandidat
        kandidat = (predpona + vs)[-10:]
    raise ChybaValidace(f"Variabilní symbol {vs} už má jiný doklad – změňte v Nastavení číselnou řadu.")


# ---------------------------------------------------------------- vystavení


def _ano(hodnota) -> bool:
    return hodnota in (True, "1", "on", "true")


def vychozi_udaje(session: Session, zakazka_id: int, typ: str = TypDokladu.FAKTURA) -> dict:
    """Předvyplnění formuláře pro vystavení dokladu."""
    zakazka = zakazky_sluzba.ziskej(session, zakazka_id)
    nast = nastaveni_sluzba.nacti(session)
    dnes = date.today()
    k = zakazka.zakaznik
    je_faktura = typ == TypDokladu.FAKTURA
    # převodem jen když je kam platit (číslo účtu v Nastavení); vyúčtování formu úhrady nemá (#55)
    forma = (FormaUhrady.PREVOD if iban_servisu(nast) else FormaUhrady.HOTOVE) if je_faktura else ""
    return {
        "typ": typ,
        "datum_vystaveni": dnes,
        "duzp": dnes,
        # hotovost se platí hned → splatnost = den vystavení
        "datum_splatnosti": dnes if forma == FormaUhrady.HOTOVE else dnes + timedelta(days=nast.splatnost_dni),
        "forma_uhrady": forma,
        # #208: zákazník a vozidlo dokladu – předvyplněné ze zakázky, v okně vystavení jdou změnit
        "zakaznik_id": k.id if k else "",
        "vozidlo_id": zakazka.vozidlo_id or "",
        "spz": zakazka.vozidlo.spz if zakazka.vozidlo else "",
        "odb_nazev": k.nazev if k else "",
        "odb_ulice": (k.ulice or "") if k else "",
        "odb_mesto": (k.mesto or "") if k else "",
        "odb_psc": (k.psc or "") if k else "",
        "odb_ico": (k.ico or "") if k else "",
        "odb_dic": (k.dic or "") if k else "",
        "poznamka": "",
        "uhrazeno_ihned": "" if je_faktura else "1",
    }


def _cislo_id(hodnota) -> int | None:
    text = cisty_text(str(hodnota)) if hodnota is not None else None
    if not text:
        return None
    if not text.isdigit():
        raise ChybaValidace("Neplatný výběr zákazníka nebo vozidla.")
    return int(text)


def _zakaznik_dokladu(session: Session, zakazka, data: dict):
    """#208: zákazník (plátce) dokladu. Bez klíče `zakaznik_id` ve formuláři zůstává zákazník zakázky.
    Ručně vyplněný odběratel, který v databázi není, se uloží jako nový zákazník (se stejným IČO se použije existující)."""
    if "zakaznik_id" not in data:
        return zakazka.zakaznik
    zakaznik_id = _cislo_id(data.get("zakaznik_id"))
    if zakaznik_id:
        zakaznik = session.get(Zakaznik, zakaznik_id)
        if zakaznik is None:
            raise ChybaValidace("Vybraný zákazník neexistuje – vyberte ho znovu.", "odb_nazev")
        return zakaznik
    nazev = cisty_text(data.get("odb_nazev"))
    if not nazev:
        return None
    ico = (cisty_text(data.get("odb_ico")) or "").replace(" ", "")
    if ico:
        existujici = session.exec(select(Zakaznik).where(Zakaznik.ico == ico)).first()
        if existujici:
            return existujici
    return zakaznici_sluzba.vytvor(session, {p.removeprefix("odb_"): data.get(p) for p in POLE_ODBERATELE},
                                   commit=False)


def _vozidlo_dokladu(session: Session, zakazka, data: dict):
    """#208: vozidlo dokladu → (vozidlo z databáze nebo None, SPZ). Bez klíče `vozidlo_id` zůstává vozidlo zakázky.
    SPZ, která v databázi není, se na doklad napíše jen jako text."""
    if "vozidlo_id" not in data:
        return zakazka.vozidlo, zakazka.vozidlo.spz if zakazka.vozidlo else None
    vozidlo_id = _cislo_id(data.get("vozidlo_id"))
    if vozidlo_id:
        vozidlo = session.get(Vozidlo, vozidlo_id)
        if vozidlo is None:
            raise ChybaValidace("Vybrané vozidlo neexistuje – vyberte ho znovu.", "spz")
        return vozidlo, vozidlo.spz
    spz = vozidla_sluzba.normalizuj_spz(data.get("spz") or "")
    if spz:
        vozidlo = vozidla_sluzba.najdi_podle_spz(session, spz)
        return vozidlo, vozidlo.spz if vozidlo else spz
    return None, None


def vystav(session: Session, zakazka_id: int, data: dict) -> Faktura:
    """Vystaví fakturu / vyúčtování ze zakázky a zakázku uzavře (stav Uzavřeno)."""
    zakazka = zakazky_sluzba.ziskej(session, zakazka_id)
    nast = nastaveni_sluzba.nacti(session)
    typ = data.get("typ") or TypDokladu.FAKTURA
    if typ not in TypDokladu.VSECHNY:
        raise ChybaValidace("Neznámý typ dokladu.")
    if zakazka.platna_faktura:
        raise ChybaValidace(f"K zakázce už je vystaven doklad {zakazka.platna_faktura.cislo}.")
    if not zakazka.polozky:
        raise ChybaValidace("Zakázka nemá žádné položky – není co fakturovat.")
    je_vyuctovani = typ == TypDokladu.VYUCTOVANI
    if je_vyuctovani:
        forma = ""  # #55: vyúčtování formu úhrady nemá – sleduje se jen stav
        if not iban_vyuctovani(nast):
            raise ChybaValidace("Vyúčtování nejde vystavit – v Nastavení chybí platný účet pro QR platbu na vyúčtování. "
                                "Doplňte ho v Nastavení (Bankovní účet).")
    else:
        forma = data.get("forma_uhrady") or FormaUhrady.PREVOD
        if forma not in FormaUhrady.VSECHNY:
            raise ChybaValidace("Forma úhrady musí být převodem, nebo hotově.")

    vystaveni = parsuj_datum(data.get("datum_vystaveni")) or date.today()
    duzp = parsuj_datum(data.get("duzp")) or vystaveni
    splatnost = parsuj_datum(data.get("datum_splatnosti")) or (vystaveni + timedelta(days=nast.splatnost_dni))
    if splatnost < vystaveni:
        raise ChybaValidace("Datum splatnosti nemůže být před datem vystavení.")
    odb_nazev = cisty_text(data.get("odb_nazev")) or ""
    if typ == TypDokladu.FAKTURA:
        if not odb_nazev:
            raise ChybaValidace("Vyplňte odběratele.", "odb_nazev")
        if not nast.udaje_vyplneny:
            raise ChybaValidace(f"Fakturu nejde vystavit – v Nastavení chybí údaje servisu: {nast.chybejici_udaje_text}. "
                                "Bez nich by nebyla platným daňovým dokladem.")
    if forma == FormaUhrady.PREVOD and typ == TypDokladu.FAKTURA and not iban_servisu(nast):
        raise ChybaValidace("Pro platbu převodem vyplňte v Nastavení číslo účtu (tiskne se na fakturu i do QR), "
                            "nebo zvolte platbu hotově.", "forma_uhrady")

    poradi = cisty_text(data.get("poradi"))
    cislo = cislo_z_poradi(session, typ, vystaveni.year, poradi) if poradi else dalsi_cislo(session, typ, vystaveni.year)
    vuz, spz = _vozidlo_dokladu(session, zakazka, data)
    zakaznik = _zakaznik_dokladu(session, zakazka, data)
    if typ == TypDokladu.FAKTURA and zakaznik is None:
        raise ChybaValidace("Faktura vyžaduje zákazníka – vyberte ho, nebo vyplňte odběratele.", "odb_nazev")
    # tachometr patří k vozidlu zakázky – u jiného vozidla na doklad nepatří
    tachometr = zakazka.tachometr if (vuz is not None and vuz.id == zakazka.vozidlo_id) else None
    faktura = Faktura(
        cislo=cislo, typ=typ, zakazka_id=zakazka.id, zakaznik_id=zakaznik.id if zakaznik else None,
        odb_nazev=odb_nazev,
        **{p: cisty_text(data.get(p)) for p in POLE_ODBERATELE if p != "odb_nazev"},
        datum_vystaveni=vystaveni, duzp=duzp, datum_splatnosti=splatnost, forma_uhrady=forma,
        variabilni_symbol=_jedinecny_vs(session, variabilni_symbol(cislo, typ)), platce_dph=nast.platce_dph, mena=nast.mena,
        spz=spz, vozidlo_popis=vuz.popis if vuz and (vuz.znacka or vuz.model) else None,
        tachometr=tachometr, cislo_zakazky=zakazka.cislo, poznamka=cisty_text(data.get("poznamka")),
    )
    for r in zakazka.polozky:
        faktura.polozky.append(PolozkaFaktury(
            typ=r.typ, kod=r.kod, nazev=r.nazev, jednotka=r.jednotka, mnozstvi=r.mnozstvi,
            cena=r.cena, sazba_dph=r.sazba_dph if nast.platce_dph else Decimal("0"),
        ))
    celkem = polozky_sluzba.rekapitulace_radku(faktura.polozky).celkem
    # všechny doklady (faktura převodem i hotově, vyúčtování) se zaokrouhlují na celé koruny; vypnout jde v Nastavení
    if nast.zaokrouhlit_hotovost:
        na_koruny = celkem.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        faktura.zaokrouhleni = na_koruny - celkem
        celkem = na_koruny
    faktura.celkem = zaokrouhli(celkem)

    if _ano(data.get("uhrazeno_ihned")):
        faktura.uhrady.append(Uhrada(datum=vystaveni, castka=faktura.celkem, zpusob=forma,
                                     poznamka="Uhrazeno při vystavení"))
    faktura.stav_zakazky_pred = zakazka.stav  # smazání dokladu ho vrátí
    zakazka.stav = StavZakazky.PREDANO
    zakazka.uzavreno = zakazka.uzavreno or datetime.now()
    # použité volné číslo po smazaném dokladu už není volné
    for volne in session.exec(select(SmazaneCislo).where(SmazaneCislo.cislo == cislo)):
        session.delete(volne)
    session.add(faktura)
    session.add(zakazka)
    try:
        session.commit()
    except IntegrityError as e:  # souběžné vystavení se stejným číslem (číslo je v databázi jedinečné)
        session.rollback()
        raise ChybaValidace(f"Číslo {cislo} mezitím dostal jiný doklad – zvolte jiné.", "poradi") from e
    except Exception:
        session.rollback()
        raise
    session.refresh(faktura)
    return faktura


def ziskej(session: Session, faktura_id: int) -> Faktura:
    faktura = session.get(Faktura, faktura_id)
    if faktura is None:
        raise NenalezenoError(f"Doklad {faktura_id} neexistuje.")
    return faktura


def rekapitulace(faktura: Faktura):
    return polozky_sluzba.rekapitulace_radku(faktura.polozky)


def smaz(session: Session, faktura_id: int) -> tuple[str, int | None]:
    """Smaže doklad i s položkami a úhradami (#15) a znovu otevře zakázku k úpravám.

    Číslo se zapíše mezi smazaná („Volné po smazání“) – ostatní doklady se nepřečíslují a mezera se
    automaticky nevyplní. Vrací (číslo, id zakázky).
    """
    faktura = ziskej(session, faktura_id)
    cislo, zakazka = faktura.cislo, faktura.zakazka
    if zakazka and zakazka.stav == StavZakazky.PREDANO and not any(
            f.id != faktura.id and not f.stornovano for f in zakazka.faktury):
        # zpět do stavu před vystavením (Přijato / V opravě / Hotovo); starší doklady stav neznají → V opravě
        pred = faktura.stav_zakazky_pred
        zakazka.stav = pred if pred in StavZakazky.OTEVRENE else StavZakazky.V_OPRAVE
        zakazka.uzavreno = None
        session.add(zakazka)
    if not session.exec(select(SmazaneCislo).where(SmazaneCislo.cislo == cislo)).first():
        session.add(SmazaneCislo(cislo=cislo, typ=faktura.typ, datum_vystaveni=faktura.datum_vystaveni))
    session.delete(faktura)
    session.commit()
    return cislo, zakazka.id if zakazka else None


# ---------------------------------------------------------------- úhrady


def pridej_uhradu(session: Session, faktura_id: int, data: dict) -> Uhrada:
    faktura = ziskej(session, faktura_id)
    if faktura.stornovano:
        raise ChybaValidace("Ke stornovanému dokladu nelze přidat úhradu.")
    castka = desetinne_nebo_none(data.get("castka"), "Částka", "castka")
    if castka is None or castka == 0:
        raise ChybaValidace("Vyplňte částku úhrady (záporná = vrácení).", "castka")
    castka = zaokrouhli(castka)
    if castka > 0 and castka > faktura.zbyva:
        zbyva = f"{faktura.zbyva:,.2f}".replace(",", " ").replace(".", ",")
        raise ChybaValidace(f"Úhrada je vyšší, než kolik zbývá uhradit ({zbyva} {faktura.mena}).", "castka")
    if castka < 0 and -castka > faktura.uhrazeno:
        raise ChybaValidace("Nelze vrátit víc, než bylo uhrazeno.", "castka")
    zpusob = data.get("zpusob") or FormaUhrady.PREVOD
    if zpusob not in FormaUhrady.VSECHNY:
        raise ChybaValidace("Způsob úhrady musí být převodem, nebo hotově.")
    uhrada = Uhrada(faktura_id=faktura.id, castka=castka, zpusob=zpusob,
                    datum=parsuj_datum(data.get("datum")) or date.today(),
                    poznamka=cisty_text(data.get("poznamka")))
    session.add(uhrada)
    session.commit()
    session.refresh(uhrada)
    return uhrada


def doklady_zakaznika(session: Session, zakaznik_id: int) -> list[Faktura]:
    """Všechny doklady zákazníka, nejnovější první – pro historii partnera."""
    return list(session.exec(
        select(Faktura).options(selectinload(Faktura.uhrady)).where(Faktura.zakaznik_id == zakaznik_id)
        .order_by(col(Faktura.datum_vystaveni).desc(), col(Faktura.cislo).desc())
    ))


def zrus_uhradu(session: Session, uhrada_id: int) -> int:
    """Zruší úhradu – nesmaže ji, zůstane v historii dokladu přeškrtnutá s časem zrušení. Vrátí id dokladu."""
    uhrada = session.get(Uhrada, uhrada_id)
    if uhrada is None:
        raise NenalezenoError(f"Úhrada {uhrada_id} neexistuje.")
    if uhrada.zruseno:
        raise ChybaValidace("Úhrada už je zrušená.")
    uhrada.zruseno = datetime.now()
    session.add(uhrada)
    session.commit()
    return uhrada.faktura_id


smaz_uhradu = zrus_uhradu  # starší název


def nastav_vytisteno(session: Session, faktura_id: int, vytisteno: bool) -> Faktura:
    """#167: ruční potvrzení tisku dokladu (prohlížeč neumí ověřit, že se opravdu tisklo)."""
    faktura = ziskej(session, faktura_id)
    faktura.vytisteno = vytisteno
    faktura.vytisteno_kdy = datetime.now() if vytisteno else None
    session.add(faktura)
    session.commit()
    session.refresh(faktura)
    return faktura


def nastav_uhrazeno(session: Session, faktura_id: int, uhrazeno: bool) -> Faktura:
    """Přepne stav vyúčtování Uhrazeno ⇄ Neuhrazeno (#55). Formu úhrady nepředpokládá a částku nemění.

    Uhrazeno = úhrada zbývající částky (jen když něco zbývá – opakované přepnutí nic nezdvojí).
    Neuhrazeno = zrušení platných úhrad (zůstanou v historii přeškrtnuté, nic se nemaže)."""
    faktura = ziskej(session, faktura_id)
    if faktura.typ != TypDokladu.VYUCTOVANI:
        raise ChybaValidace("Stav jde přepínat jen u vyúčtování – u faktury zapište nebo zrušte úhradu.")
    if uhrazeno:
        if faktura.zbyva > 0:
            session.add(Uhrada(faktura_id=faktura.id, datum=date.today(), castka=faktura.zbyva, zpusob="",
                               poznamka="Označeno jako uhrazené"))
    else:
        for u in faktura.platne_uhrady:
            u.zruseno = datetime.now()
            session.add(u)
    session.commit()
    session.refresh(faktura)
    return faktura


# ---------------------------------------------------------------- přehled

# záložky přehledu dokladů
# #175: přehled přepíná jen Vyúčtování / Faktury (tlačítka); „vse“ ze starších odkazů dál funguje
FILTRY = {
    "vyuctovani": "Vyúčtování",
    "faktury": "Faktury",
}


@dataclass
class VolneMisto:
    """Řádek přehledu na místě smazaného dokladu – „FV20260042 · Volné po smazání“ (#15)."""
    cislo: str
    typ: str
    datum_vystaveni: date
    je_volne_misto: bool = True
    datum_splatnosti = None
    odb_nazev = ""
    spz = None
    celkem = Decimal("0")
    zbyva = Decimal("0")
    stav = "volne"
    stornovano = False


def _volna_mista(session: Session, filtr: str, hledat: str | None, rok: int | None, typ: str | None) -> list:
    if filtr not in ("vyuctovani", "faktury", "vse"):
        return []
    typy = {"vyuctovani": TypDokladu.VYUCTOVANI, "faktury": TypDokladu.FAKTURA}
    vysledek = []
    for s in volna_cisla(session):
        if (filtr in typy and s.typ != typy[filtr]) or (typ and s.typ != typ) \
                or (rok and s.datum_vystaveni.year != rok) or (hledat and hledat.lower() not in s.cislo.lower()):
            continue
        vysledek.append(VolneMisto(s.cislo, s.typ, s.datum_vystaveni))
    return vysledek
VYCHOZI_FILTR = "vyuctovani"  # výchozí záložka přehledu dokladů


def seznam(
    session: Session, filtr: str = VYCHOZI_FILTR, hledat: str | None = None,
    rok: int | None = None, typ: str | None = None, limit: int | None = None,
) -> list[Faktura]:
    """Doklady podle filtru (bez limitu všechny – mřížka je pak zobrazuje po dávkách přes `stranka`)."""
    dotaz = select(Faktura).options(selectinload(Faktura.uhrady))
    hledat = cisty_text(hledat)
    if hledat:
        vzor = f"%{hledat}%"
        dotaz = dotaz.where(or_(
            Faktura.cislo.ilike(vzor), Faktura.odb_nazev.ilike(vzor), Faktura.odb_ico.ilike(vzor),
            Faktura.spz.ilike(f"%{hledat.replace(' ', '').upper()}%"), Faktura.cislo_zakazky.ilike(vzor),
        ))
    if rok:
        dotaz = dotaz.where(Faktura.datum_vystaveni >= date(rok, 1, 1), Faktura.datum_vystaveni <= date(rok, 12, 31))
    if typ:
        dotaz = dotaz.where(Faktura.typ == typ)
    dotaz = dotaz.order_by(col(Faktura.datum_vystaveni).desc(), col(Faktura.cislo).desc())
    if limit:
        dotaz = dotaz.limit(limit)
    vysledek = list(session.exec(dotaz))
    if filtr == "vyuctovani":
        vysledek = [f for f in vysledek if f.typ == TypDokladu.VYUCTOVANI and not f.stornovano]
    elif filtr == "faktury":
        vysledek = [f for f in vysledek if f.typ == TypDokladu.FAKTURA and not f.stornovano]
    # starší filtry (už nejsou v záložkách, staré odkazy dál fungují)
    elif filtr == "neuhrazene":
        vysledek = [f for f in vysledek if f.zbyva > 0]
    elif filtr == "po_splatnosti":
        vysledek = [f for f in vysledek if f.stav == "po_splatnosti"]
    elif filtr == "uhrazene":
        vysledek = [f for f in vysledek if f.stav == "uhrazena"]
    return vysledek + _volna_mista(session, filtr, hledat, rok, typ)


RAZENI = {
    "cislo": lambda f: f.cislo,
    "vystaveno": lambda f: (f.datum_vystaveni, f.cislo),
    "splatnost": lambda f: f.datum_splatnosti or f.datum_vystaveni,
    "odberatel": lambda f: cesky_klic(f.odb_nazev) or None,
    "vozidlo": lambda f: f.spz or None,
    "celkem": lambda f: f.celkem,
    "zbyva": lambda f: f.zbyva,
    "stav": lambda f: f.stav,
}


def stranka(seznam_dokladu: list[Faktura], razeni: str | None = None, od=0,
            limit: int = VELIKOST_STRANKY) -> Stranka:
    """Stránka z už vyfiltrovaného seznamu (stav a zbývá se počítají v Pythonu, proto ne v SQL)."""
    return strankuj_seznam(seznam_dokladu, RAZENI, razeni, "-vystaveno", od, limit)


@dataclass
class Souhrn:
    pocet: int
    celkem: Decimal
    zbyva: Decimal


def souhrn(faktury: list[Faktura]) -> Souhrn:
    platne = [f for f in faktury if not f.stornovano and not isinstance(f, VolneMisto)]
    return Souhrn(
        pocet=len(platne),
        celkem=sum((f.celkem for f in platne), Decimal("0")),
        zbyva=sum((f.zbyva for f in platne), Decimal("0")),
    )


# ---------------------------------------------------------------- QR platba

KODY_MEN = {"KČ": "CZK", "CZK": "CZK", "€": "EUR", "EUR": "EUR"}


def iban_z_cisla_uctu(ucet: str) -> str | None:
    """'19-2000145399/0800' → 'CZ6508000000192000145399'. Neplatný formát → None."""
    m = re.fullmatch(r"(?:(\d{1,6})-)?(\d{2,10})/(\d{4})", (ucet or "").replace(" ", ""))
    if not m:
        return None
    predcisli, cislo, banka = m.group(1) or "0", m.group(2), m.group(3)
    bban = f"{banka}{int(predcisli):06d}{int(cislo):010d}"
    kontrola = 98 - int(bban + "123500") % 97  # C=12, Z=35, 00
    return f"CZ{kontrola:02d}{bban}"


def iban_platny(iban: str) -> bool:
    """Kontrolní součet IBAN (mod 97)."""
    iban = (iban or "").replace(" ", "").upper()
    if not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]{10,30}", iban):
        return False
    prevedeno = "".join(str(int(z, 36)) for z in iban[4:] + iban[:4])
    return int(prevedeno) % 97 == 1


def iban_z_uctu(ucet: str) -> str | None:
    """Číslo účtu nebo IBAN → IBAN. Neplatné → None."""
    ucet = (ucet or "").replace(" ", "").upper()
    if re.match(r"[A-Z]{2}", ucet):
        return ucet if iban_platny(ucet) else None
    return iban_z_cisla_uctu(ucet)


def iban_servisu(nast) -> str | None:
    """Účet pro faktury."""
    return nast.iban or iban_z_cisla_uctu(nast.cislo_uctu)


def iban_vyuctovani(nast) -> str | None:
    """Účet pro QR platbu na vyúčtování (#55) – nikdy se nebere účet pro faktury."""
    return iban_z_uctu(nast.ucet_vyuctovani)


def spayd(faktura: Faktura, nast) -> str | None:
    """Řetězec pro QR platbu (formát SPAYD). Bez účtu nebo když není co platit → None.

    Faktura: jen převodem, na zbývající částku, účet pro faktury.
    Vyúčtování (#55): vždy na celkovou částku (bez ohledu na stav úhrady), účet pro vyúčtování."""
    if faktura.typ == TypDokladu.VYUCTOVANI:
        iban, castka = iban_vyuctovani(nast), faktura.celkem
    else:
        if faktura.forma_uhrady != FormaUhrady.PREVOD:
            return None
        iban, castka = iban_servisu(nast), faktura.zbyva
    if not iban or castka <= 0:
        return None
    mena = KODY_MEN.get(faktura.mena.upper(), "CZK")
    zprava = re.sub(r"[*]", "", f"{faktura.nazev_typu} {faktura.cislo}")[:60]
    casti = [
        "SPD*1.0", f"ACC:{iban}", f"AM:{castka:.2f}", f"CC:{mena}",
    ]
    if faktura.typ == TypDokladu.FAKTURA:  # vyúčtování splatnost neuvádí (#58)
        casti.append(f"DT:{faktura.datum_splatnosti:%Y%m%d}")
    casti.append(f"MSG:{zprava}")
    if faktura.variabilni_symbol:
        casti.append(f"X-VS:{faktura.variabilni_symbol}")
    return "*".join(casti)


def qr_svg(text: str) -> str:
    import segno
    # #59: viewBox místo pevné šířky/výšky – SVG se zmenší celé (bez oříznutí) na rozměr z CSS;
    # bílý okraj 4 moduly podle normy QR
    return segno.make(text, error="m").svg_inline(border=4, omitsize=True, dark="#000", light="#fff")
