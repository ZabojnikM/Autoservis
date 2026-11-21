"""Správa dat – výběr dílů materiálu s filtrem a řazením, deník úprav a export skladu (#136).

Ceník materiálu má jednotky tisíc karet, proto se filtruje a řadí v Pythonu nad přesnými čísly (Decimal);
ceny jsou v databázi uložené jako text a SQL by je neporovnal správně.
Marže = (prodej − nákup) / prodej × 100 (podíl zisku na prodejní ceně bez DPH).
"""
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, fields
from datetime import date, datetime
from decimal import Decimal

from sqlmodel import Session, col, func, select

from app.models import Katalog, PolozkaCeniku, PolozkaZakazky, TypPolozky, UpravaDat, Zakazka
from app.services import ChybaValidace, cisty_text, cti_datum, desetinne_nebo_none, slouceni

STAVY = {"aktivni": "Aktivní", "vyrazene": "Vyřazené", "vse": "Aktivní i vyřazené"}
POUZITI = {"": "Bez ohledu na použití", "nikdy": "Nikdy nepoužité", "pouzite": "Použité"}
PROBLEMY = {"": "—", "pod_nakupem": "Prodej pod nákupní cenou", "nulova_cena": "Nulová prodejní cena",
            "bez_nakupu": "Bez nákupní ceny", "kod_podezrely": "Podezřelý zápis kódu", "bez_kodu": "Bez kódu"}
RAZENI = {"kod": "Kód", "nazev": "Název", "katalog": "Sklad", "cena": "Prodej", "nakup": "Nákup", "marze": "Marže",
          "pouzito": "Použito", "posledni": "Naposledy"}


def vzor_kodu(vzor: str) -> "re.Pattern":
    """#151: vzor kódu se zástupnými znaky jako v Excelu / Accessu (operátor Like) → regulární výraz.
    * = libovolné znaky (i žádný), ? = jeden znak, # = jedna číslice, [abc] / [a-c] = jeden znak ze seznamu,
    [!abc] = jeden znak mimo seznam; ostatní znaky (tečka, mezera, pomlčka…) doslova. Platí na celý kód,
    velikost písmen nevadí."""
    vysledek, i = [], 0
    while i < len(vzor):
        z = vzor[i]
        if z == "*":
            vysledek.append(".*")
        elif z == "?":
            vysledek.append(".")
        elif z == "#":
            vysledek.append("[0-9]")
        elif z == "[":
            konec = vzor.find("]", i + 2 if vzor[i + 1:i + 2] == "!" else i + 1)
            if konec == -1:
                raise ChybaValidace(f"Vzor kódu „{vzor}“: chybí zavírací závorka ].")
            obsah = vzor[i + 1:konec]
            negace = obsah.startswith("!")
            obsah = obsah[1:] if negace else obsah
            if not obsah:
                raise ChybaValidace(f"Vzor kódu „{vzor}“: prázdný výběr [ ].")
            casti = "".join(re.escape(c) if c != "-" or j in (0, len(obsah) - 1) else "-" for j, c in enumerate(obsah))
            vysledek.append(f"[{'^' if negace else ''}{casti}]")
            i = konec
        else:
            vysledek.append(re.escape(z))
        i += 1
    try:
        return re.compile("".join(vysledek), re.IGNORECASE)
    except re.error:
        raise ChybaValidace(f"Vzor kódu „{vzor}“ nejde použít (např. rozsah [z-a]).") from None


@dataclass
class Filtr:
    katalog: str = ""        # id skladu, prázdné = všechny
    q: str = ""              # text v kódu / názvu / zaměnitelném dílu (kód i bez oddělovačů)
    predpona: str = ""       # předpona výrobce, např. UFI
    vzor: str = ""           # #151: vzor celého kódu se zástupnými znaky jako v Excelu / Accessu (* ? # [ ])
    stav: str = "aktivni"
    pouziti: str = ""
    pouzito_min: str = ""    # použito aspoň N×
    nepouzito_od: str = ""   # naposledy použité před datem (nebo nikdy)
    cena_od: str = ""
    cena_do: str = ""
    marze_pod: str = ""
    problem: str = ""
    razeni: str = "kod"      # klíč z RAZENI, „-“ na začátku = sestupně

    @classmethod
    def z_dat(cls, data) -> "Filtr":
        hodnoty = {f.name: str(data.get(f.name) or "").strip() for f in fields(cls) if data.get(f.name) is not None}
        filtr = cls(**hodnoty)
        if filtr.stav not in STAVY:
            filtr.stav = "aktivni"
        return filtr

    def parametry(self) -> dict:
        """Neprázdné hodnoty – do odkazů a skrytých polí formulářů."""
        vychozi = Filtr()
        return {f.name: getattr(self, f.name) for f in fields(self) if getattr(self, f.name) != getattr(vychozi, f.name)}

    @property
    def je_prazdny(self) -> bool:
        return not {k for k in self.parametry() if k != "razeni"}


@dataclass
class Radek:
    karta: PolozkaCeniku
    katalog: str
    pouzito: int
    posledni: date | None

    @property
    def marze(self) -> Decimal | None:
        p = self.karta
        if p.nakupni_cena is None or not p.cena:
            return None
        return ((p.cena - p.nakupni_cena) / p.cena * 100).quantize(Decimal("0.1"))


def pouziti(session: Session) -> dict[int, tuple[int, date | None]]:
    """{id karty: (počet řádků zakázek, datum příjmu poslední zakázky)}."""
    dotaz = (select(PolozkaZakazky.polozka_ceniku_id, func.count(), func.max(Zakazka.datum_prijeti))
             .join(Zakazka, Zakazka.id == PolozkaZakazky.zakazka_id)
             .where(col(PolozkaZakazky.polozka_ceniku_id).is_not(None))
             .group_by(PolozkaZakazky.polozka_ceniku_id))
    vysledek = {}
    for pid, pocet, posledni in session.exec(dotaz):
        if isinstance(posledni, str):  # SQLite vrací agregát jako text
            posledni = datetime.fromisoformat(posledni)
        vysledek[pid] = (pocet, posledni.date() if posledni else None)
    return vysledek


def _bez(text: str) -> str:
    return "".join(z for z in text.casefold() if z not in " .-/")


def je_podezrely_kod(kod: str | None) -> bool:
    if not kod:
        return False
    return kod != kod.strip() or "  " in kod or kod != kod.upper()


def _odpovida_problem(r: Radek, problem: str) -> bool:
    p = r.karta
    return {
        "pod_nakupem": p.nakupni_cena is not None and p.cena < p.nakupni_cena,
        "nulova_cena": not p.cena,
        "bez_nakupu": p.nakupni_cena is None,
        "kod_podezrely": je_podezrely_kod(p.kod),
        "bez_kodu": not cisty_text(p.kod),
    }.get(problem, True)


def _klic_razeni(klic: str):
    return {
        "kod": lambda r: ((r.karta.kod or "￿").casefold(), r.karta.id),
        "nazev": lambda r: (r.karta.nazev.casefold(), r.karta.id),
        "katalog": lambda r: (r.katalog.casefold(), (r.karta.kod or "").casefold()),
        "cena": lambda r: (r.karta.cena, r.karta.id),
        "nakup": lambda r: (r.karta.nakupni_cena if r.karta.nakupni_cena is not None else Decimal("-1"), r.karta.id),
        "marze": lambda r: (r.marze if r.marze is not None else Decimal("-1000"), r.karta.id),
        "pouzito": lambda r: (r.pouzito, r.karta.id),
        "posledni": lambda r: (r.posledni or date.min, r.karta.id),
    }[klic]


def vyber(session: Session, filtr: Filtr) -> list[Radek]:
    """Díly materiálu podle filtru, seřazené."""
    katalogy = {k.id: k.nazev for k in session.exec(select(Katalog))}
    pouzite = pouziti(session)
    dotaz = select(PolozkaCeniku).where(PolozkaCeniku.typ == TypPolozky.MATERIAL)
    if filtr.katalog.isdigit():
        dotaz = dotaz.where(PolozkaCeniku.katalog_id == int(filtr.katalog))
    if filtr.stav == "aktivni":
        dotaz = dotaz.where(PolozkaCeniku.aktivni == True)  # noqa: E712
    elif filtr.stav == "vyrazene":
        dotaz = dotaz.where(PolozkaCeniku.aktivni == False)  # noqa: E712
    pouzito_min = int(filtr.pouzito_min) if filtr.pouzito_min.isdigit() else None
    try:
        nepouzito_od = cti_datum(filtr.nepouzito_od) if filtr.nepouzito_od else None
    except ValueError:
        raise ChybaValidace(f"Nepoužité od: „{filtr.nepouzito_od}“ není datum, zadejte např. 1.1.2024.") from None
    cena_od = desetinne_nebo_none(filtr.cena_od, "Cena od")
    cena_do = desetinne_nebo_none(filtr.cena_do, "Cena do")
    marze_pod = desetinne_nebo_none(filtr.marze_pod, "Marže pod")
    text, text_bez = filtr.q.casefold(), _bez(filtr.q)
    predpona = filtr.predpona.strip().upper()
    vzor = vzor_kodu(filtr.vzor.strip()) if filtr.vzor.strip() else None
    vysledek = []
    for p in session.exec(dotaz):
        pocet, posledni = pouzite.get(p.id, (0, None))
        r = Radek(p, katalogy.get(p.katalog_id, ""), pocet, posledni)
        kod = p.kod or ""
        if text and not (text in kod.casefold() or text in p.nazev.casefold()
                         or text in (p.zamenitelny_dil or "").casefold() or (text_bez and text_bez in _bez(kod))):
            continue
        if predpona and not kod.strip().upper().startswith(predpona + " ") and kod.strip().upper() != predpona:
            continue
        if vzor and not vzor.fullmatch(kod.strip()):
            continue
        if filtr.pouziti == "nikdy" and pocet:
            continue
        if filtr.pouziti == "pouzite" and not pocet:
            continue
        if pouzito_min is not None and pocet < pouzito_min:
            continue
        if nepouzito_od and posledni and posledni >= nepouzito_od:
            continue
        if cena_od is not None and p.cena < cena_od:
            continue
        if cena_do is not None and p.cena > cena_do:
            continue
        if marze_pod is not None and (r.marze is None or r.marze >= marze_pod):
            continue
        if filtr.problem and not _odpovida_problem(r, filtr.problem):
            continue
        vysledek.append(r)
    klic = filtr.razeni.lstrip("-")
    if klic not in RAZENI:
        klic, filtr.razeni = "kod", "kod"
    vysledek.sort(key=_klic_razeni(klic), reverse=filtr.razeni.startswith("-"))
    return vysledek


def ids_z_vyberu(session: Session, filtr: Filtr, rozsah: str, vybrane) -> list[int]:
    """`rozsah` = „filtr“ (všechny díly podle filtru), jinak zaškrtnuté `vybrane` (jen materiál)."""
    if rozsah == "filtr":
        return [r.karta.id for r in vyber(session, filtr)]
    ids = sorted({int(v) for v in vybrane if str(v).isdigit()})
    if not ids:
        raise ChybaValidace("Zaškrtněte díly, nebo zvolte „všechny díly podle filtru“.")
    platne = set(session.exec(select(PolozkaCeniku.id).where(col(PolozkaCeniku.id).in_(ids),
                                                            PolozkaCeniku.typ == TypPolozky.MATERIAL)))
    return [i for i in ids if i in platne]


# ---------------------------------------------------------------- deník úprav

def zapis(session: Session, akce: str, popis: str, pocet: int, zaloha: str = "") -> UpravaDat:
    zaznam = UpravaDat(akce=akce, popis=popis[:2000], pocet=pocet, zaloha=zaloha)
    session.add(zaznam)
    session.commit()
    return zaznam


def denik(session: Session, limit: int = 200) -> list[UpravaDat]:
    return list(session.exec(select(UpravaDat).order_by(col(UpravaDat.cas).desc(), col(UpravaDat.id).desc()).limit(limit)))


# ---------------------------------------------------------------- export

SLOUPCE_EXPORTU = {
    "kod": "Kód", "nazev": "Název", "katalog": "Sklad", "jednotka": "MJ", "cena": "Prodej bez DPH",
    "nakup": "Nákup bez DPH", "dph": "DPH %", "marze": "Marže %", "zamenitelny": "Zaměnitelný díl",
    "poznamka": "Poznámka", "pouzito": "Použito", "posledni": "Naposledy", "aktivni": "Aktivní",
}
VYCHOZI_SLOUPCE = ["kod", "nazev", "katalog", "jednotka", "cena", "nakup", "dph", "marze", "pouzito", "posledni"]


def _cislo(hodnota) -> str:
    return "" if hodnota is None else f"{Decimal(hodnota):.2f}".replace(".", ",")


def _hodnota(r: Radek, sloupec: str) -> str:
    p = r.karta
    return {
        "kod": p.kod or "", "nazev": p.nazev, "katalog": r.katalog, "jednotka": p.jednotka,
        "cena": _cislo(p.cena), "nakup": _cislo(p.nakupni_cena), "dph": f"{p.sazba_dph.normalize():f}".replace(".", ","),
        "marze": "" if r.marze is None else str(r.marze).replace(".", ","), "zamenitelny": p.zamenitelny_dil or "",
        "poznamka": p.poznamka or "", "pouzito": str(r.pouzito),
        "posledni": r.posledni.strftime("%d.%m.%Y") if r.posledni else "", "aktivni": "ano" if p.aktivni else "ne",
    }[sloupec]


def export_csv(radky: list[Radek], sloupce=None) -> bytes:
    """CSV pro Excel (středník, desetinná čárka, UTF-8 s BOM); jde nahrát zpět Importem do skladu."""
    sloupce = [s for s in (sloupce or VYCHOZI_SLOUPCE) if s in SLOUPCE_EXPORTU] or VYCHOZI_SLOUPCE
    vystup = io.StringIO()
    zapis_ = csv.writer(vystup, delimiter=";", lineterminator="\r\n")
    zapis_.writerow([SLOUPCE_EXPORTU[s] for s in sloupce])
    for r in radky:
        zapis_.writerow([_hodnota(r, s) for s in sloupce])
    return ("﻿" + vystup.getvalue()).encode("utf-8")


def predpony(session: Session) -> list[tuple[str, int]]:
    """Předpony výrobců v kódech aktivních dílů (UFI, BO…) a počty – nabídka do filtru."""
    pocty: dict[str, int] = {}
    for kod in session.exec(select(PolozkaCeniku.kod).where(PolozkaCeniku.typ == TypPolozky.MATERIAL,
                                                            PolozkaCeniku.aktivni == True)):  # noqa: E712
        if kod and slouceni.ma_predponu(kod):
            pred = kod.strip().split()[0].upper()
            pocty[pred] = pocty.get(pred, 0) + 1
    return sorted(pocty.items(), key=lambda x: (-x[1], x[0]))
