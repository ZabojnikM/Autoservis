"""Doklady: faktura (daňový doklad) a vyúčtování zakázky.

Doklad se vystavuje ze zakázky a zakázku uzavře. Po vystavení se nemění – jen úhrady. Chybný doklad se smaže
(#15): jeho číslo zůstane v přehledu jako „Volné po smazání“ a jde ho ručně použít při dalším vystavení.
Úhrada převodem nebo hotově (hotovost volitelně zaokrouhlená na koruny).
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
    Faktura, FormaUhrady, PolozkaFaktury, SmazaneCislo, StavZakazky, TypDokladu, Uhrada, zaokrouhli,
)
from app.services import ChybaValidace, NenalezenoError, cisty_text, desetinne_nebo_none
from app.services import nastaveni as nastaveni_sluzba
from app.services import polozky as polozky_sluzba
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
    # převodem jen když je kam platit (číslo účtu v Nastavení)
    forma = FormaUhrady.PREVOD if je_faktura and iban_servisu(nast) else FormaUhrady.HOTOVE
    return {
        "typ": typ,
        "datum_vystaveni": dnes,
        "duzp": dnes,
        # hotovost se platí hned → splatnost = den vystavení
        "datum_splatnosti": dnes + timedelta(days=nast.splatnost_dni) if forma == FormaUhrady.PREVOD else dnes,
        "forma_uhrady": forma,
        "odb_nazev": k.nazev if k else "",
        "odb_ulice": (k.ulice or "") if k else "",
        "odb_mesto": (k.mesto or "") if k else "",
        "odb_psc": (k.psc or "") if k else "",
        "odb_ico": (k.ico or "") if k else "",
        "odb_dic": (k.dic or "") if k else "",
        "poznamka": "",
        "uhrazeno_ihned": "" if je_faktura else "1",
    }


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
        if not zakazka.zakaznik_id:
            raise ChybaValidace("Faktura vyžaduje zákazníka – doplňte ho na zakázce (Upravit), "
                                "nebo vystavte vyúčtování.")
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
    vuz = zakazka.vozidlo
    faktura = Faktura(
        cislo=cislo, typ=typ, zakazka_id=zakazka.id, zakaznik_id=zakazka.zakaznik_id,
        odb_nazev=odb_nazev,
        **{p: cisty_text(data.get(p)) for p in POLE_ODBERATELE if p != "odb_nazev"},
        datum_vystaveni=vystaveni, duzp=duzp, datum_splatnosti=splatnost, forma_uhrady=forma,
        variabilni_symbol=_jedinecny_vs(session, variabilni_symbol(cislo, typ)), platce_dph=nast.platce_dph, mena=nast.mena,
        spz=vuz.spz if vuz else None, vozidlo_popis=vuz.popis if vuz and (vuz.znacka or vuz.model) else None,
        tachometr=zakazka.tachometr, cislo_zakazky=zakazka.cislo, poznamka=cisty_text(data.get("poznamka")),
    )
    for r in zakazka.polozky:
        faktura.polozky.append(PolozkaFaktury(
            typ=r.typ, kod=r.kod, nazev=r.nazev, jednotka=r.jednotka, mnozstvi=r.mnozstvi,
            cena=r.cena, sazba_dph=r.sazba_dph if nast.platce_dph else Decimal("0"),
        ))
    celkem = polozky_sluzba.rekapitulace_radku(faktura.polozky).celkem
    if forma == FormaUhrady.HOTOVE and nast.zaokrouhlit_hotovost:
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


# ---------------------------------------------------------------- přehled

# záložky přehledu dokladů
FILTRY = {
    "vyuctovani": "Vyúčtování",
    "faktury": "Faktury",
    "vse": "Všechny",
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
VYCHOZI_FILTR = "vse"


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


def iban_servisu(nast) -> str | None:
    return nast.iban or iban_z_cisla_uctu(nast.cislo_uctu)


def spayd(faktura: Faktura, nast) -> str | None:
    """Řetězec pro QR platbu (formát SPAYD). Bez účtu nebo když není co platit → None."""
    iban = iban_servisu(nast)
    if not iban or faktura.zbyva <= 0:
        return None
    mena = KODY_MEN.get(faktura.mena.upper(), "CZK")
    zprava = re.sub(r"[*]", "", f"{faktura.nazev_typu} {faktura.cislo}")[:60]
    casti = [
        "SPD*1.0", f"ACC:{iban}", f"AM:{faktura.zbyva:.2f}", f"CC:{mena}",
        f"DT:{faktura.datum_splatnosti:%Y%m%d}", f"MSG:{zprava}",
    ]
    if faktura.variabilni_symbol:
        casti.append(f"X-VS:{faktura.variabilni_symbol}")
    return "*".join(casti)


def qr_svg(text: str) -> str:
    import segno
    return segno.make(text, error="m").svg_inline(scale=3, border=2, dark="#000", light="#fff")
