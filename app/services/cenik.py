"""Ceník – práce a materiál (zatím bez skladových zásob)."""
from decimal import Decimal

from sqlalchemy import Float, cast, or_
from sqlmodel import Session, col, func, select

from app.models import PolozkaCeniku, PolozkaZakazky, TypPolozky, zaokrouhli
from app.services import ChybaValidace, NenalezenoError, cisty_text, desetinne_nebo_none
from app.services import katalogy
from app.services import nastaveni as nastaveni_sluzba
from app.services.strankovani import VELIKOST_STRANKY, Stranka, strankuj_dotaz


def cena_bez_dph(cena: Decimal, sazba_dph: Decimal, je_s_dph: bool) -> Decimal:
    """Zadaná cena s DPH → bez DPH (jako F12 ve starém systému)."""
    if not je_s_dph:
        return cena
    return (cena * 100 / (100 + sazba_dph)).quantize(Decimal("0.0001"))


def cena_z_dvojice(data: dict, klic: str, nazev: str, sazba_dph: Decimal) -> tuple[bool, Decimal | None]:
    """Cena z dvojice polí formuláře: `klic` (bez DPH) a `klic_s` (s DPH).

    `klic_zdroj` = „s“ říká, že uživatel naposledy psal do pole s DPH – pak se cena bez DPH
    spočítá přesně z ceny s DPH (na 4 desetinná místa, aby 385 s DPH zůstalo 385). Vrací (zadáno, cena)."""
    if data.get(f"{klic}_zdroj") == "s" and f"{klic}_s" in data:
        cena = desetinne_nebo_none(data[f"{klic}_s"], nazev, klic)
        return True, None if cena is None else cena_bez_dph(cena, sazba_dph, True)
    if klic in data:
        return True, desetinne_nebo_none(data[klic], nazev, klic)
    return False, None


def _nastav(session: Session, polozka: PolozkaCeniku, data: dict) -> None:
    if "nazev" in data:
        polozka.nazev = cisty_text(data["nazev"]) or ""
    if not polozka.nazev:
        raise ChybaValidace("Vyplňte název položky.", "nazev")
    if "kod" in data:
        polozka.kod = cisty_text(data["kod"])
    if "typ" in data:
        if data["typ"] not in TypPolozky.VSECHNY:
            raise ChybaValidace("Typ musí být práce, nebo materiál.")
        polozka.typ = data["typ"]
    if "jednotka" in data:
        polozka.jednotka = cisty_text(data["jednotka"]) or ("hod" if polozka.typ == TypPolozky.PRACE else "ks")
    if "sazba_dph" in data:
        sazba = desetinne_nebo_none(data["sazba_dph"], "Sazba DPH", "sazba_dph")
        polozka.sazba_dph = sazba if sazba is not None else nastaveni_sluzba.nacti(session).vychozi_dph
    if not 0 <= polozka.sazba_dph < 100:
        raise ChybaValidace("Sazba DPH musí být 0–99 %.", "sazba_dph")
    zadano, cena = cena_z_dvojice(data, "cena", "Cena", polozka.sazba_dph)
    if zadano:
        if cena is None:
            raise ChybaValidace("Vyplňte cenu.", "cena")
        # starší tvar formuláře: zaškrtnutí „zadaná cena je s DPH“
        je_s_dph = data.get("cena_zdroj") != "s" and data.get("cena_s_dph") in (True, "1", "on", "true")
        polozka.cena = cena_bez_dph(cena, polozka.sazba_dph, je_s_dph)
    if polozka.cena < 0:
        raise ChybaValidace("Cena nemůže být záporná.", "cena")
    zadano, nakupni = cena_z_dvojice(data, "nakupni_cena", "Nákupní cena", polozka.sazba_dph)
    if zadano:
        if nakupni is not None and nakupni < 0:
            raise ChybaValidace("Nákupní cena nemůže být záporná.", "nakupni_cena")
        polozka.nakupni_cena = nakupni
    if "zamenitelny_dil" in data:
        polozka.zamenitelny_dil = cisty_text(data["zamenitelny_dil"])
    if "poznamka" in data:
        polozka.poznamka = cisty_text(data["poznamka"])
    if "aktivni" in data:
        polozka.aktivni = data["aktivni"] in (True, "1", "on", "true")

    if "katalog_id" in data:
        # práce mají jeden společný katalog (výchozí), materiál patří do zvoleného (#62)
        polozka.katalog_id = (katalogy.vychozi(session).id if polozka.typ == TypPolozky.PRACE
                              else katalogy.podle_id(session, data["katalog_id"]).id)
    elif polozka.katalog_id is None or polozka.typ == TypPolozky.PRACE:
        polozka.katalog_id = katalogy.vychozi(session).id

    if polozka.kod:
        jina = najdi_podle_kodu(session, polozka.kod, polozka.katalog_id)
        if jina and jina.id != polozka.id:
            raise ChybaValidace(f"Kód {polozka.kod} už v tomto katalogu má položka „{jina.nazev}“.", "kod")


def vytvor(session: Session, data: dict, commit: bool = True) -> PolozkaCeniku:
    polozka = PolozkaCeniku(nazev="")
    data = dict(data)
    data.setdefault("typ", TypPolozky.MATERIAL)
    data.setdefault("jednotka", "")
    data.setdefault("sazba_dph", "")
    data.setdefault("cena", "")
    _nastav(session, polozka, data)
    session.add(polozka)
    if commit:
        session.commit()
        session.refresh(polozka)
    else:
        session.flush()
    return polozka


def uprav(session: Session, polozka_id: int, data: dict) -> PolozkaCeniku:
    polozka = ziskej(session, polozka_id)
    # #124: bez průběžného zápisu – rozpracovaná změna kódu / katalogu by jinak narazila na unikátní index
    # dřív, než kontrola ukáže srozumitelnou hlášku
    with session.no_autoflush:
        _nastav(session, polozka, data)
    session.add(polozka)
    session.commit()
    session.refresh(polozka)
    return polozka


def najdi_podle_kodu(session: Session, kod: str | None, katalog_id: int | None) -> PolozkaCeniku | None:
    """Položka s kódem v daném katalogu (stejný kód v jiném katalogu je jiný díl, #62)."""
    kod = cisty_text(kod)
    if not kod:
        return None
    with session.no_autoflush:
        return session.exec(select(PolozkaCeniku).where(PolozkaCeniku.kod == kod,
                                                        PolozkaCeniku.katalog_id == katalog_id)).first()


def ziskej(session: Session, polozka_id: int) -> PolozkaCeniku:
    polozka = session.get(PolozkaCeniku, polozka_id)
    if polozka is None:
        raise NenalezenoError(f"Položka ceníku {polozka_id} neexistuje.")
    return polozka


def _bez_oddelovacu(vyraz):
    """Kód dílu bez mezer, teček, pomlček a lomítek – „GAT 6PK-1018“ najde i „gat6pk1018“."""
    for znak in (" ", ".", "-", "/"):
        vyraz = func.replace(vyraz, znak, "")
    return func.upper(vyraz)


def _dotaz_seznamu(hledat: str | None, typ: str | None, jen_aktivni: bool, katalog_id: int | None = None):
    """`katalog_id` omezí materiál na jeden katalog; práce (společný katalog) zůstávají."""
    dotaz = select(PolozkaCeniku)
    if katalog_id is not None:
        dotaz = dotaz.where(or_(PolozkaCeniku.typ == TypPolozky.PRACE, PolozkaCeniku.katalog_id == katalog_id))
    hledat = cisty_text(hledat)
    if hledat:
        vzor = f"%{hledat}%"
        kod = "".join(z for z in hledat.upper() if z not in " .-/")
        podminky = [PolozkaCeniku.nazev.ilike(vzor), PolozkaCeniku.kod.ilike(vzor),
                    PolozkaCeniku.zamenitelny_dil.ilike(vzor)]
        if kod:  # hlavní klíč je kód – hledá se i bez ohledu na mezery a oddělovače
            podminky += [_bez_oddelovacu(PolozkaCeniku.kod).like(f"%{kod}%"),
                         _bez_oddelovacu(PolozkaCeniku.zamenitelny_dil).like(f"%{kod}%")]
        dotaz = dotaz.where(or_(*podminky))
    if typ:
        dotaz = dotaz.where(PolozkaCeniku.typ == typ)
    if jen_aktivni:
        dotaz = dotaz.where(col(PolozkaCeniku.aktivni).is_(True))
    return dotaz


def seznam(
    session: Session,
    hledat: str | None = None,
    typ: str | None = None,
    jen_aktivni: bool = False,
    limit: int = 500,
    podle_kodu: bool = False,
    katalog_id: int | None = None,
) -> list[PolozkaCeniku]:
    """`podle_kodu` = řadit podle kódu (položky bez kódu na konec), jinak práce před materiálem a podle názvu."""
    dotaz = _dotaz_seznamu(hledat, typ, jen_aktivni, katalog_id)
    if podle_kodu:
        poradi = (PolozkaCeniku.kod.is_(None), PolozkaCeniku.kod.collate("cs"), PolozkaCeniku.nazev.collate("cs"))
    else:
        poradi = (PolozkaCeniku.typ.desc(), func.lower(PolozkaCeniku.nazev))
    return list(session.exec(dotaz.order_by(*poradi).limit(limit)))


NEJPOUZIVANEJSI = 30  # #102: tolik nejčastěji použitých dílů ukáže okno Přidat materiál bez hledání
CASTO_POUZIVANY = 3  # #113: od tolika použití je díl „často používaný“ (podbarvený, nad oddělovací čarou)


def vyber_pro_zakazku(session: Session, hledat: str | None, typ: str, katalog_id: int | None,
                      limit: int) -> tuple[list[PolozkaCeniku], dict[int, tuple[int, object]], bool]:
    """Okno Přidat materiál (#102): díly i s počtem použití na zakázkách (počítá se z řádků zakázek,
    které si pamatují svou kartu ceníku).

    Bez hledání: NEJPOUZIVANEJSI nejčastěji použitých dílů katalogu (od nejčastějšího); když se zatím nic
    nepoužilo, začátek ceníku podle kódu. S hledáním: přesná shoda kódu (bez mezer a oddělovačů) nahoře,
    pak podle počtu použití, pak nepoužité podle kódu.
    Vrací (díly, {id: (počet, naposledy)}, jen_nejpouzivanejsi)."""
    pouziti = (select(PolozkaZakazky.polozka_ceniku_id.label("pid"), func.count().label("pocet"),
                      func.max(PolozkaZakazky.vytvoreno).label("naposledy"))
               .where(col(PolozkaZakazky.polozka_ceniku_id).is_not(None))
               .group_by(PolozkaZakazky.polozka_ceniku_id).subquery())
    pocet = func.coalesce(pouziti.c.pocet, 0)
    dotaz = (_dotaz_seznamu(hledat, typ, True, katalog_id)
             .add_columns(pocet, pouziti.c.naposledy)
             .outerjoin(pouziti, pouziti.c.pid == PolozkaCeniku.id))
    hledat = cisty_text(hledat)
    poradi_kodu = (PolozkaCeniku.kod.is_(None), PolozkaCeniku.kod.collate("cs"), PolozkaCeniku.nazev.collate("cs"))
    nejpouzivanejsi = False
    if hledat:
        kod = "".join(z for z in hledat.upper() if z not in " .-/")
        presne = _bez_oddelovacu(PolozkaCeniku.kod) == kod if kod else False
        radky = session.execute(dotaz.order_by(presne.desc() if kod else pocet.desc(), pocet.desc(), *poradi_kodu)
                             .limit(limit)).all()
    else:
        radky = session.execute(dotaz.where(pouziti.c.pocet > 0).order_by(pocet.desc(), *poradi_kodu)
                             .limit(NEJPOUZIVANEJSI)).all()
        nejpouzivanejsi = bool(radky)
        if not radky:
            radky = session.execute(dotaz.order_by(*poradi_kodu).limit(limit)).all()
    return [r[0] for r in radky], {r[0].id: (r[1], r[2]) for r in radky if r[1]}, nejpouzivanejsi


def pocty_podle_typu(session: Session, hledat: str | None = None, jen_aktivni: bool = False,
                     katalog_id: int | None = None) -> dict[str, int]:
    """Počty položek pro záložky Vše / Práce / Materiál (se stejným hledáním jako seznam)."""
    filtr = _dotaz_seznamu(hledat, None, jen_aktivni, katalog_id).whereclause
    dotaz = select(PolozkaCeniku.typ, func.count()).group_by(PolozkaCeniku.typ)
    if filtr is not None:
        dotaz = dotaz.where(filtr)
    pocty = {t: 0 for t in TypPolozky.VSECHNY}
    pocty.update({typ: pocet for typ, pocet in session.exec(dotaz).all()})
    return pocty


# cena je v DB text → pro řazení číslo
RAZENI = {
    "kod": [PolozkaCeniku.kod.collate("cs"), PolozkaCeniku.nazev.collate("cs")],
    "nazev": [PolozkaCeniku.nazev.collate("cs")],
    "typ": [PolozkaCeniku.typ, PolozkaCeniku.nazev.collate("cs")],
    "cena": [cast(PolozkaCeniku.cena, Float)],
    "dph": [cast(PolozkaCeniku.sazba_dph, Float)],
    "nakup": [cast(PolozkaCeniku.nakupni_cena, Float)],
    "zamenitelny": [PolozkaCeniku.zamenitelny_dil.collate("cs")],
    "jednotka": [PolozkaCeniku.jednotka, PolozkaCeniku.nazev.collate("cs")],
    # #122: počet použití na zakázkách (stejný výpočet jako okno Přidat materiál, #102)
    "pouzito": [select(func.count()).where(PolozkaZakazky.polozka_ceniku_id == PolozkaCeniku.id)
                .correlate(PolozkaCeniku).scalar_subquery()],
}


def pocty_pouziti(session: Session, ids) -> dict[int, int]:
    """#122: počet řádků zakázek, které použily dané karty ceníku (karty bez použití ve výsledku nejsou)."""
    ids = list(ids)
    if not ids:
        return {}
    dotaz = (select(PolozkaZakazky.polozka_ceniku_id, func.count())
             .where(col(PolozkaZakazky.polozka_ceniku_id).in_(ids)).group_by(PolozkaZakazky.polozka_ceniku_id))
    return {pid: pocet for pid, pocet in session.execute(dotaz).all()}


def stranka(session: Session, hledat: str | None = None, typ: str | None = None, jen_aktivni: bool = False,
            razeni: str | None = None, od=0, limit: int = VELIKOST_STRANKY, katalog_id: int | None = None) -> Stranka:
    # výchozí řazení podle kódu (hlavní klíč ceníku); položky bez kódu jsou na konci
    return strankuj_dotaz(session, _dotaz_seznamu(hledat, typ, jen_aktivni, katalog_id), RAZENI, razeni, "kod",
                          od, limit, doplnkove=[PolozkaCeniku.id])


def hodnoty_ceny_pro_formular(cena: Decimal | None, sazba_dph: Decimal | None, platce_dph: bool) -> dict:
    """Cena pro pole formuláře (úprava ceníku i položky zakázky).

    Cena zadaná s DPH se uloží přepočtená na víc desetinných míst (150 s DPH → 123,9669 bez DPH).
    Takovou cenu ukážeme zase s DPH a zaškrtnutou volbou „cena je s DPH“, ostatní ceny bez DPH
    s desetinnou čárkou. Uložení beze změny tak cenu nezmění.
    """
    if cena is None:
        return {"cena": "", "cena_s_dph": ""}
    cena = Decimal(cena)
    sazba = Decimal(sazba_dph or 0)
    if platce_dph and sazba and cena != cena.quantize(Decimal("0.01")):
        s_dph = zaokrouhli(cena * (100 + sazba) / 100)
        if cena_bez_dph(s_dph, sazba, True) == cena:
            return {"cena": _carka(s_dph), "cena_s_dph": "1"}
    return {"cena": _carka(cena), "cena_s_dph": ""}


def hodnoty_dvojice_cen(klic: str, cena: Decimal | None, sazba_dph: Decimal | None) -> dict:
    """Pole formuláře ceníku pro cenu bez DPH a s DPH (`klic`, `klic_s`, `klic_zdroj`).

    Cena uložená z ceny s DPH (víc desetinných míst, 150 s DPH → 123,9669) má zdroj „s“,
    takže uložení beze změny ji nezmění."""
    if cena is None:
        return {klic: "", f"{klic}_s": "", f"{klic}_zdroj": ""}
    cena = Decimal(cena)
    sazba = Decimal(sazba_dph or 0)
    s_dph = zaokrouhli(cena * (100 + sazba) / 100)
    ze_s_dph = cena != cena.quantize(Decimal("0.01")) and cena_bez_dph(s_dph, sazba, True) == cena
    return {klic: _carka(zaokrouhli(cena) if ze_s_dph else cena), f"{klic}_s": _carka(s_dph),
            f"{klic}_zdroj": "s" if ze_s_dph else ""}


def _carka(cislo: Decimal) -> str:
    text = f"{cislo:f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text.replace(".", ",")


def najdi(session: Session, polozka_id: int) -> PolozkaCeniku | None:
    """Položka ceníku, nebo None (např. mezitím smazaná)."""
    return session.get(PolozkaCeniku, polozka_id)


def smaz(session: Session, polozka_id: int) -> None:
    """Zakázky mají vlastní kopii údajů, takže smazání ceníku je nerozbije."""
    session.delete(ziskej(session, polozka_id))
    session.commit()
