"""Zakázky – příjem vozidla, stavy, číslování."""
from datetime import date, datetime

from sqlalchemy import case, extract, or_
from sqlmodel import Session, col, func, select

from app.models import Faktura, StavZakazky, STAVY_PALIVA, Vozidlo, Zakaznik, Zakazka
from app.services import ChybaValidace, NenalezenoError, cislo_nebo_none, cisty_text, id_nebo_none
from app.services.strankovani import VELIKOST_STRANKY, Stranka, strankuj_dotaz
from app.services import vozidla as vozidla_sluzba
from app.services import zakaznici as zakaznici_sluzba


def parsuj_datum(hodnota) -> date | None:
    """Přijme 'RRRR-MM-DD' (z formuláře) i 'DD.MM.RRRR'."""
    hodnota = cisty_text(hodnota)
    if hodnota is None:
        return None
    if isinstance(hodnota, date):
        return hodnota
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d.%m.%y"):
        try:
            return datetime.strptime(hodnota.replace(" ", ""), fmt).date()
        except ValueError:
            pass
    raise ChybaValidace(f"Neplatné datum: {hodnota}")


def parsuj_datum_cas(hodnota) -> datetime | None:
    """'RRRR-MM-DDTHH:MM' (pole datetime-local), 'RRRR-MM-DD HH:MM' nebo 'DD.MM.RRRR HH:MM'."""
    hodnota = cisty_text(hodnota)
    if hodnota is None:
        return None
    if isinstance(hodnota, datetime):
        return hodnota
    for fmt in ("%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M", "%d.%m.%Y %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(hodnota, fmt)
        except ValueError:
            pass
    raise ChybaValidace(f"Neplatné datum a čas: {hodnota}")


def dalsi_cislo(session: Session, rok: int | None = None) -> str:
    """Další číslo zakázky ve tvaru RRRR-0001 (řada začíná každý rok znovu).

    Počítá i s čísly zakázek, která zůstala jen na dokladech (zakázka smazaná dřív, než to šlo zakázat) –
    číslo uvedené na dokladu se nesmí přidělit jiné zakázce.
    """
    rok = rok or date.today().year
    predpona = f"{rok}-"
    pouzita = list(session.exec(select(Zakazka.cislo).where(col(Zakazka.cislo).startswith(predpona))))
    pouzita += [c for c in session.exec(select(Faktura.cislo_zakazky)
                                        .where(col(Faktura.cislo_zakazky).startswith(predpona))) if c]
    poradi = [int(c[len(predpona):]) for c in pouzita if c[len(predpona):].isdigit()]
    return f"{predpona}{(max(poradi) + 1) if poradi else 1:04d}"


def _nastav(zakazka: Zakazka, data: dict) -> None:
    if "tachometr" in data:
        zakazka.tachometr = cislo_nebo_none(data["tachometr"], "Stav tachometru", "tachometr")
        if zakazka.tachometr is not None and zakazka.tachometr < 0:
            raise ChybaValidace("Stav tachometru nemůže být záporný.", "tachometr")
    if "stav_paliva" in data:
        palivo = cisty_text(data["stav_paliva"])
        if palivo and palivo not in STAVY_PALIVA:
            raise ChybaValidace("Neplatný stav paliva.")
        zakazka.stav_paliva = palivo
    if "pozadavek" in data:
        zakazka.pozadavek = cisty_text(data["pozadavek"]) or ""
    if "termin_dokonceni" in data:
        zakazka.termin_dokonceni = parsuj_datum(data["termin_dokonceni"])
    if cisty_text(data.get("datum_prijeti")):
        zakazka.datum_prijeti = parsuj_datum_cas(data["datum_prijeti"])
    if "poznamka" in data:
        zakazka.poznamka = cisty_text(data["poznamka"])
    # popis zakázky (požadavek) je nepovinný – při příjmu ho často ještě neznáme


def prijem(
    session: Session,
    zakazka: dict,
    vozidlo: dict | None = None,
    zakaznik: dict | None = None,
) -> Zakazka:
    """Příjem vozidla do servisu – vytvoří zakázku.

    Vozidlo se určí podle `zakazka["vozidlo_id"]`, jinak podle SPZ v `vozidlo`;
    neexistuje-li, založí se z údajů `vozidlo`. Bez SPZ i bez `vozidlo_id` je zakázka bez vozidla (#50).

    Zákazník (`zakaznik`) je nepovinný:
      - `vyber="bez"` → zakázka bez zákazníka (lze doplnit později),
      - `vyber=<id>` nebo `id=<id>` → existující zákazník,
      - `vyber="novy"` nebo vyplněný `nazev` → nový zákazník z údajů `zakaznik`,
      - nic → převezme se zákazník vozidla (může být žádný).
    Vozidlu bez zákazníka se vybraný zákazník rovnou přiřadí. Vše v jedné transakci.
    """
    vozidlo = vozidlo or {}
    zakaznik = zakaznik or {}
    try:
        bez = zakaznik.get("vyber") == "bez"
        zakaznik_id = None if bez else _vyres_zakaznika(session, zakaznik)
        vuz = _urci_vozidlo(session, zakazka, vozidlo, zakaznik_id)
        if vuz is not None and zakaznik_id is not None and vuz.zakaznik_id is None:
            vuz.zakaznik_id = zakaznik_id
            session.add(vuz)
        if not bez and zakaznik_id is None:
            zakaznik_id = cislo_nebo_none(zakazka.get("zakaznik_id"), "Zákazník") or (vuz.zakaznik_id if vuz else None)
        if zakaznik_id is not None:
            zakaznici_sluzba.ziskej(session, zakaznik_id)

        nova = Zakazka(cislo=dalsi_cislo(session), vozidlo_id=vuz.id if vuz else None, zakaznik_id=zakaznik_id)
        _nastav(nova, zakazka)
        session.add(nova)
        session.commit()
    except Exception:
        session.rollback()
        raise
    session.refresh(nova)
    return nova


def prijem_z_formulare(session: Session, zakazka: dict, vozidlo: dict, zakaznik: dict) -> Zakazka:
    """Příjem jako ve starém systému – panely Zákazník a Vozidlo jsou přímo upravitelné.

    `zakaznik`: `zakaznik_id` (vybraný z databáze), pole zákazníka a `jako_novy`:
      - vybraný zákazník → změny v panelu se uloží k němu (s `jako_novy` vznikne nový zákazník),
      - nevybraný, ale vyplněný → nový zákazník (firma je pak povinná),
      - prázdný panel → zakázka bez zákazníka.
    `vozidlo`: `vozidlo_id` a pole vozidla. Vybrané vozidlo (nebo nalezené podle SPZ) se upraví,
    jinak se založí nové; prázdný panel → zakázka bez vozidla (#50). Vozidlu bez majitele se přiřadí
    zákazník zakázky. Vše v jedné transakci.
    """
    try:
        zakaznik_id = _zakaznik_z_panelu(session, zakaznik)
        vuz = _vozidlo_z_panelu(session, vozidlo)
        if vuz is not None and zakaznik_id is not None and vuz.zakaznik_id is None:
            vuz.zakaznik_id = zakaznik_id
            session.add(vuz)
        nova = Zakazka(cislo=dalsi_cislo(session), vozidlo_id=vuz.id if vuz else None, zakaznik_id=zakaznik_id)
        _nastav(nova, zakazka)
        session.add(nova)
        session.commit()
    except Exception:
        session.rollback()
        raise
    session.refresh(nova)
    return nova


def _zakaznik_z_panelu(session: Session, zakaznik: dict) -> int | None:
    data = {p: zakaznik[p] for p in zakaznici_sluzba.POLE if p in zakaznik}
    vybrany = id_nebo_none(zakaznik.get("zakaznik_id"), "Zákazník")
    jako_novy = zakaznik.get("jako_novy") in (True, "1", "on", "true")
    if vybrany is not None and not jako_novy:
        if not cisty_text(data.get("nazev")):
            raise ChybaValidace("Vyplňte firmu (příjmení a jméno), nebo zákazníka odeberte tlačítkem Nový.",
                                "k_nazev")
        return zakaznici_sluzba.uprav(session, vybrany, data, commit=False).id
    if not any(cisty_text(v) for v in data.values()):
        return None
    if not cisty_text(data.get("nazev")):
        raise ChybaValidace("Vyplňte firmu (příjmení a jméno) zákazníka, nebo panel zákazníka vyprázdněte.",
                            "k_nazev")
    return zakaznici_sluzba.vytvor(session, data, commit=False).id


zakaznik_z_panelu = _zakaznik_z_panelu  # i pro formulář vozidla (stejný panel Zákazník jako na příjmu)


def _vozidlo_z_panelu(session: Session, vozidlo: dict) -> Vozidlo | None:
    """Vozidlo z panelu příjmu / úpravy zakázky. Prázdný panel (bez SPZ a bez dalších údajů) = bez vozidla."""
    data = {p: vozidlo[p] for p in vozidla_sluzba.POLE if p in vozidlo}
    spz = vozidla_sluzba.normalizuj_spz(data.get("spz"))
    if not spz:
        if not any(cisty_text(v) for v in data.values()):
            return None  # zakázka bez vozidla (#50)
        raise ChybaValidace("Vyplňte SPZ vozidla, nebo panel vozidla vyprázdněte (tlačítko Nové vozidlo) – "
                            "zakázka pak bude bez vozidla.", "spz")
    vybrane = id_nebo_none(vozidlo.get("vozidlo_id"), "Vozidlo")
    if vybrane is not None and vozidla_sluzba.ziskej(session, vybrane).spz != spz:
        vybrane = None  # SPZ přepsaná na jinou → jde o jiné vozidlo (SPZ se mění v úpravě vozidla)
    if vybrane is None:
        nalezene = vozidla_sluzba.najdi_podle_spz(session, spz)
        vybrane = nalezene.id if nalezene else None
    if vybrane is not None:
        return vozidla_sluzba.uprav(session, vybrane, data, commit=False)
    return vozidla_sluzba.vytvor(session, data, commit=False)


def _vyres_zakaznika(session: Session, zakaznik: dict) -> int | None:
    """Vrátí id existujícího / nově založeného zákazníka, nebo None (neurčen)."""
    vyber = cisty_text(zakaznik.get("vyber"))
    if vyber is None:  # volání bez formuláře: vyplněné jméno = nový, jinak případné id
        vyber = "novy" if cisty_text(zakaznik.get("nazev")) else zakaznik.get("id")
    return zakaznici_sluzba.z_vyberu(session, vyber, zakaznik)


def _urci_vozidlo(session: Session, zakazka: dict, vozidlo: dict, zakaznik_id: int | None) -> Vozidlo | None:
    vozidlo_id = cislo_nebo_none(zakazka.get("vozidlo_id"), "Vozidlo")
    if vozidlo_id is not None:
        return vozidla_sluzba.ziskej(session, vozidlo_id)
    if not vozidla_sluzba.normalizuj_spz(vozidlo.get("spz")):
        return None  # bez vozidla (#50)

    existujici = vozidla_sluzba.najdi_podle_spz(session, vozidlo.get("spz", ""))
    if existujici:
        return existujici
    return vozidla_sluzba.vytvor(session, dict(vozidlo, zakaznik_id=zakaznik_id), commit=False)


def uprav(session: Session, zakazka_id: int, data: dict) -> Zakazka:
    """Úprava zakázky.

    `zakaznik_id` (id / „novy“ s údaji v `zakaznik_novy` / „bez“) změní zákazníka –
    vozidlu bez zákazníka se přiřadí taky.
    """
    zakazka = ziskej(session, zakazka_id)
    _nastav(zakazka, data)
    if "zakaznik_id" in data:
        vyber = data["zakaznik_id"]
        zmena = vyber == "novy" or id_nebo_none(vyber, "Zákazník") != zakazka.zakaznik_id
        if zmena:
            if zakazka.platna_faktura:
                raise ChybaValidace(f"Zakázka je vyúčtovaná dokladem {zakazka.platna_faktura.cislo} – "
                                    "zákazníka nelze změnit.")
            novy = zakaznici_sluzba.z_vyberu(session, vyber, data.get("zakaznik_novy"))
            if novy is not None:
                if zakazka.vozidlo and zakazka.vozidlo.zakaznik_id is None:
                    zakazka.vozidlo.zakaznik_id = novy
                    session.add(zakazka.vozidlo)
            zakazka.zakaznik_id = novy
    session.add(zakazka)
    session.commit()
    session.refresh(zakazka)
    return zakazka


def uprav_z_formulare(session: Session, zakazka_id: int, zakazka: dict, vozidlo: dict, zakaznik: dict) -> Zakazka:
    """Úprava zakázky ve stejném okně jako příjem (panely Zákazník | Zakázka | Vozidlo).

    Jde změnit i vozidlo (jiná SPZ / výběr z databáze) a datum přijetí. Změny v panelech zákazníka
    a vozidla se uloží k nim – stejně jako při příjmu. Vyúčtovanou zakázku měnit nejde.
    """
    zaznam = ziskej(session, zakazka_id)
    if zaznam.platna_faktura:
        raise ChybaValidace(f"Zakázka je vyúčtovaná dokladem {zaznam.platna_faktura.cislo} – "
                            "pro změny nejdřív doklad stornujte.")
    try:
        zakaznik_id = _zakaznik_z_panelu(session, zakaznik)
        vuz = _vozidlo_z_panelu(session, vozidlo)
        if vuz is not None and zakaznik_id is not None and vuz.zakaznik_id is None:
            vuz.zakaznik_id = zakaznik_id
            session.add(vuz)
        zaznam.vozidlo_id = vuz.id if vuz else None  # prázdný panel vozidla = zakázka bez vozidla
        zaznam.zakaznik_id = zakaznik_id
        _nastav(zaznam, zakazka)
        session.add(zaznam)
        session.commit()
    except Exception:
        session.rollback()
        raise
    session.refresh(zaznam)
    return zaznam


def zmen_stav(session: Session, zakazka_id: int, stav: str, bez_dokladu: bool = False) -> Zakazka:
    """Změna stavu. Uzavřít bez dokladu (např. záruka) jde jen s potvrzením `bez_dokladu`."""
    if stav not in StavZakazky.VSECHNY:
        raise ChybaValidace(f"Neznámý stav zakázky: {stav}")
    zakazka = ziskej(session, zakazka_id)
    if stav != StavZakazky.PREDANO and zakazka.platna_faktura:
        raise ChybaValidace(
            f"Zakázka je vyúčtovaná dokladem {zakazka.platna_faktura.cislo} – "
            "pro úpravy nejdřív doklad stornujte."
        )
    if stav == StavZakazky.PREDANO and not zakazka.platna_faktura and not bez_dokladu:
        raise ChybaValidace("Zakázka nemá doklad – uzavřít ji bez dokladu (např. záruka) je potřeba potvrdit, "
                            "jinak vystavte fakturu nebo vyúčtování.")
    zakazka.stav = stav
    zakazka.uzavreno = datetime.now() if stav == StavZakazky.PREDANO else None
    session.add(zakazka)
    session.commit()
    session.refresh(zakazka)
    return zakazka


def ziskej(session: Session, zakazka_id: int) -> Zakazka:
    zakazka = session.get(Zakazka, zakazka_id)
    if zakazka is None:
        raise NenalezenoError(f"Zakázka {zakazka_id} neexistuje.")
    return zakazka


def _dotaz_seznamu(stav: str | None, jen_otevrene: bool, hledat: str | None):
    # outer join: i zakázky bez vozidla (#50) zůstanou v seznamu, hledání i řazení
    dotaz = select(Zakazka).outerjoin(Vozidlo, Zakazka.vozidlo_id == Vozidlo.id) \
        .outerjoin(Zakaznik, Zakazka.zakaznik_id == Zakaznik.id)
    if isinstance(stav, (list, tuple)):
        dotaz = dotaz.where(col(Zakazka.stav).in_(stav))
    elif stav:
        dotaz = dotaz.where(Zakazka.stav == stav)
    elif jen_otevrene:
        dotaz = dotaz.where(col(Zakazka.stav).in_(StavZakazky.OTEVRENE))
    hledat = cisty_text(hledat)
    if hledat:
        vzor = f"%{hledat}%"
        dotaz = dotaz.where(or_(
            Zakazka.cislo.ilike(vzor),
            Zakazka.pozadavek.ilike(vzor),
            Vozidlo.spz.ilike(f"%{vozidla_sluzba.normalizuj_spz(hledat)}%"),
            Zakaznik.nazev.ilike(vzor),
        ))
    return dotaz


# sloupce, podle kterých jde seznam řadit (klíč v URL → výrazy ORDER BY)
RAZENI = {
    "cislo": [Zakazka.cislo],
    "prijato": [Zakazka.datum_prijeti],
    "vozidlo": [Vozidlo.spz],
    "zakaznik": [Zakaznik.nazev.collate("cs")],
    "pozadavek": [Zakazka.pozadavek.collate("cs")],
    "termin": [Zakazka.termin_dokonceni],
    # stav v pořadí práce (přijato → předáno), ne podle abecedy
    "stav": [case({s: i for i, s in enumerate(StavZakazky.VSECHNY)}, value=Zakazka.stav)],
}


def seznam(
    session: Session,
    stav: str | None = None,
    jen_otevrene: bool = False,
    hledat: str | None = None,
    limit: int = 300,
) -> list[Zakazka]:
    dotaz = _dotaz_seznamu(stav, jen_otevrene, hledat)
    return list(session.exec(dotaz.order_by(col(Zakazka.datum_prijeti).desc(), col(Zakazka.id).desc()).limit(limit)))


def stranka(session: Session, stav: str | list[str] | None = None, jen_otevrene: bool = False, hledat: str | None = None,
            razeni: str | None = None, od=0, limit: int = VELIKOST_STRANKY, rok: int | None = None) -> Stranka:
    """Seznam zakázek pro mřížku – řazení podle sloupce a načítání po dávkách.
    Výchozí řazení podle čísla od nejstarší (#56)."""
    dotaz = _dotaz_seznamu(stav, jen_otevrene, hledat)
    if rok is not None:
        dotaz = dotaz.where(extract("year", Zakazka.datum_prijeti) == rok)
    return strankuj_dotaz(session, dotaz, RAZENI, razeni, "cislo",
                          od, limit, doplnkove=[Zakazka.id])


def roky_prijeti(session: Session) -> list[int]:
    rok = extract("year", Zakazka.datum_prijeti)
    return list(session.exec(select(rok).distinct().order_by(rok.desc())))


def pocty_podle_stavu(session: Session) -> dict[str, int]:
    radky = session.exec(select(Zakazka.stav, func.count()).group_by(Zakazka.stav)).all()
    pocty = {s: 0 for s in StavZakazky.VSECHNY}
    pocty.update({stav: pocet for stav, pocet in radky})
    return pocty


def duvod_proc_nesmazat(zakazka: Zakazka) -> str | None:
    """Proč zakázku nejde smazat (None = smazat jde). Stejný text ukáže i zašedlé tlačítko."""
    if zakazka.faktury:
        return "Zakázka má vystavený doklad – její číslo je na dokladu, proto ji nejde smazat."
    if not zakazka.je_otevrena:
        return "Uzavřenou zakázku nelze smazat."
    return None


def smaz(session: Session, zakazka_id: int) -> None:
    """Smazat lze otevřenou zakázku bez dokladů – i s materiálem a prací (smažou se s ní).
    Web se před smazáním zeptá a napíše, kolik položek se smaže."""
    zakazka = ziskej(session, zakazka_id)
    duvod = duvod_proc_nesmazat(zakazka)
    if duvod:
        raise ChybaValidace(duvod)
    session.delete(zakazka)
    session.commit()
