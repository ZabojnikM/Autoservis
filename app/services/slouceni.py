"""Sloučení duplicitních karet materiálu v ceníku (#130).

Stejný díl bývá v ceníku pod více kódy, které se liší jen zápisem („2501100“, „25.011.00“,
„UFI 25.011.00“). Sloučení:

- ponechá jednu kartu a nastaví jí nový kód, název a prodejní cenu,
- ostatní karty skupiny **nesmaže**, jen vyřadí (neaktivní) a do poznámky zapíše, kam byly sloučeny,
- v řádcích zakázek přepíše kód na nový a napojí je na ponechanou kartu – historie vozidla pak ukáže
  jeden díl s novým kódem a vložení z historie vezme novou cenu z ceníku,
- **ceny, množství a názvy v zakázkách nemění**, vystavené doklady (faktury, vyúčtování) nemění vůbec.

Návrh skupin vzniká automaticky podle čísla dílu bez mezer, teček, pomlček a bez předpony výrobce
(„UFI “, „BO “…). Hromadně jde sloučit seznam CSV: stáhne se návrh, v Excelu se upraví a nahraje zpět.
Zálohu databáze před sloučením dělá webová vrstva (`zalohy.pred_sloucenim`).
"""
from __future__ import annotations

import csv
import io
import json
import re
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import date
from decimal import Decimal

from sqlmodel import Session, col, func, or_, select

from app.models import Katalog, PolozkaCeniku, PolozkaZakazky, TypPolozky
from app.services import ChybaValidace, cisty_text, desetinne_nebo_none

# předpona výrobce / dodavatele před číslem dílu: „UFI 25.011.00“, „BO 0242235668“, „OE 6Y0821102“
_PREDPONA = re.compile(r"^[A-Z]{2,4}\s+(?=\S*\d)")
_ODDELOVACE = re.compile(r"[\s.\-/]")
NEJKRATSI_KLIC = 4  # kratší čísla („1“, „OL“) by spojovala nesouvisející díly
CHYBA_SOUBORU = "Soubor není seznam ke sloučení z Autoservisu (CSV se sloupci Skupina, ID, Ponechat, Sloučit…)."

SLOUPCE = ["Skupina", "ID", "Ponechat", "Sloučit", "Kód", "Název", "Katalog", "Prodej bez DPH", "Nákup bez DPH",
           "Použito", "Nový kód", "Nový název", "Nová cena bez DPH"]
_ANO = {"ano", "a", "x", "1", "yes", "y", "true"}


def klic_kodu(kod: str | None) -> str:
    """Číslo dílu pro porovnání: velká písmena, bez předpony výrobce a bez oddělovačů."""
    kod = (kod or "").strip().upper()
    return _ODDELOVACE.sub("", _PREDPONA.sub("", kod))


def ma_predponu(kod: str | None) -> bool:
    return bool(_PREDPONA.match((kod or "").strip().upper()))


@dataclass
class Karta:
    id: int
    kod: str
    nazev: str
    katalog: str
    cena: Decimal
    nakupni_cena: Decimal | None
    pouzito: int


@dataclass
class Skupina:
    klic: str
    karty: list[Karta]
    cil_id: int               # navržená karta k ponechání

    @property
    def cil(self) -> Karta:
        return next(k for k in self.karty if k.id == self.cil_id)

    @property
    def pouzito(self) -> int:
        return sum(k.pouzito for k in self.karty)


def _pocty_pouziti(session: Session) -> dict[int, int]:
    dotaz = (select(PolozkaZakazky.polozka_ceniku_id, func.count())
             .where(col(PolozkaZakazky.polozka_ceniku_id).is_not(None))
             .group_by(PolozkaZakazky.polozka_ceniku_id))
    return {pid: pocet for pid, pocet in session.exec(dotaz)}


def _karta(p: PolozkaCeniku, katalogy: dict, pouziti: dict) -> Karta:
    return Karta(p.id, p.kod or "", p.nazev, katalogy.get(p.katalog_id, ""), p.cena, p.nakupni_cena,
                 pouziti.get(p.id, 0))


def _navrhni_cil(karty: list[Karta]) -> int:
    """Ponechat kartu se zápisem s předponou výrobce (nové značení), jinak nejpoužívanější, pak nejnovější."""
    return max(karty, key=lambda k: (ma_predponu(k.kod), k.pouzito, k.id)).id


def navrhy(session: Session, hledat: str | None = None) -> list[Skupina]:
    """Skupiny aktivních karet materiálu se stejným číslem dílu, nejpoužívanější první.
    `hledat` omezí skupiny na ty, kde některá karta obsahuje text v kódu nebo názvu."""
    katalogy = {k.id: k.nazev for k in session.exec(select(Katalog))}
    pouziti = _pocty_pouziti(session)
    skupiny: dict[str, list[Karta]] = defaultdict(list)
    dotaz = select(PolozkaCeniku).where(PolozkaCeniku.typ == TypPolozky.MATERIAL, PolozkaCeniku.aktivni == True,  # noqa: E712
                                        col(PolozkaCeniku.kod).is_not(None))
    for p in session.exec(dotaz):
        klic = klic_kodu(p.kod)
        if len(klic) >= NEJKRATSI_KLIC:
            skupiny[klic].append(_karta(p, katalogy, pouziti))
    vysledek = [Skupina(klic, sorted(karty, key=lambda k: k.id), _navrhni_cil(karty))
                for klic, karty in skupiny.items() if len(karty) > 1]
    hledat = cisty_text(hledat)
    if hledat:
        text, klic = hledat.casefold(), klic_kodu(hledat)
        vysledek = [s for s in vysledek
                    if any(text in k.kod.casefold() or text in k.nazev.casefold() for k in s.karty)
                    or (klic and klic in s.klic)]
    return sorted(vysledek, key=lambda s: (-s.pouzito, s.klic))


def karty_podle_hledani(session: Session, hledat: str | None, limit: int = 30) -> list[Karta]:
    """Aktivní karty materiálu podle textu – pro ruční skupinu (díly s úplně jiným číslem)."""
    hledat = cisty_text(hledat)
    if not hledat:
        return []
    katalogy = {k.id: k.nazev for k in session.exec(select(Katalog))}
    pouziti = _pocty_pouziti(session)
    vzor = f"%{hledat}%"
    bez = "".join(z for z in hledat.upper() if z not in " .-/")
    kod_bez = func.upper(func.replace(func.replace(func.replace(func.replace(
        func.coalesce(PolozkaCeniku.kod, ""), " ", ""), ".", ""), "-", ""), "/", ""))
    podminky = [col(PolozkaCeniku.kod).ilike(vzor), col(PolozkaCeniku.nazev).ilike(vzor)]
    if bez:
        podminky.append(kod_bez.like(f"%{bez}%"))
    dotaz = (select(PolozkaCeniku).where(PolozkaCeniku.typ == TypPolozky.MATERIAL, PolozkaCeniku.aktivni == True,  # noqa: E712
                                         or_(*podminky))
             .order_by(PolozkaCeniku.kod).limit(limit))
    return [_karta(p, katalogy, pouziti) for p in session.exec(dotaz)]


# ---------------------------------------------------------------- samotné sloučení

@dataclass
class Vysledek:
    kod: str
    karet: int = 0       # vyřazených karet
    radku: int = 0       # přepsaných řádků zakázek

    @property
    def text(self) -> str:
        return f"Sloučeno do {self.kod}: vyřazeno karet {self.karet}, přepsáno řádků zakázek {self.radku}."


def sluc(session: Session, cil_id: int, ids, kod=None, nazev=None, cena=None, dnes: date | None = None) -> Vysledek:
    """Sloučí karty `ids` do karty `cil_id` (viz docstring modulu). Prázdný kód / název / cena = ponechat
    hodnotu ponechané karty."""
    ids = {int(i) for i in ids} | {int(cil_id)}
    if len(ids) < 2:
        raise ChybaValidace("Vyberte aspoň dvě karty ke sloučení.")
    karty = {p.id: p for p in session.exec(select(PolozkaCeniku).where(col(PolozkaCeniku.id).in_(ids)))}
    chybi = sorted(ids - karty.keys())
    if chybi:
        raise ChybaValidace(f"Karta ceníku {', '.join(map(str, chybi))} neexistuje.")
    cil = karty[int(cil_id)]
    if any(p.typ != cil.typ for p in karty.values()):
        raise ChybaValidace("Sloučit jde jen materiál s materiálem.")
    if not cil.aktivni:
        raise ChybaValidace(f"Karta {cil.kod or cil.nazev} je vyřazená – ponechat jde jen aktivní kartu.")
    novy_kod = cisty_text(kod) or cil.kod
    if not novy_kod:
        raise ChybaValidace("Zadejte nový kód.", "kod")
    novy_nazev = cisty_text(nazev) or cil.nazev
    nova_cena = desetinne_nebo_none(cena, "Nová cena", "cena")
    if nova_cena is not None and nova_cena < 0:
        raise ChybaValidace("Nová cena nesmí být záporná.", "cena")

    jiny = session.exec(select(PolozkaCeniku).where(PolozkaCeniku.kod == novy_kod,
                                                    PolozkaCeniku.katalog_id == cil.katalog_id,
                                                    PolozkaCeniku.id != cil.id)).first()
    if jiny is not None:
        if jiny.id in ids:
            raise ChybaValidace(f"Kód {novy_kod} už má jiná karta skupiny ve stejném katalogu – ponechte tu kartu.")
        raise ChybaValidace(f"Kód {novy_kod} už v katalogu má jiná karta ({jiny.nazev}) – přidejte ji do skupiny.")

    zdroje = [p for i, p in sorted(karty.items()) if i != cil.id]
    stare_kody = [p.kod for p in zdroje if p.kod] + ([cil.kod] if cil.kod and cil.kod != novy_kod else [])

    # karty: zdroje vyřadit s poznámkou, ponechané nastavit nový kód / název / cenu
    dnes = dnes or date.today()
    for p in zdroje:
        p.aktivni = False
        zaznam = f"Sloučeno do {novy_kod} ({dnes:%d.%m.%Y})."
        p.poznamka = f"{p.poznamka.rstrip()} {zaznam}" if cisty_text(p.poznamka) else zaznam
        session.add(p)
    session.flush()  # vyřazení dřív, než ponechaná karta převezme kód (unikátní kód v katalogu)
    cil.kod, cil.nazev = novy_kod, novy_nazev
    if nova_cena is not None:
        cil.cena = nova_cena
    # staré kódy s jiným číslem dílu do „Zaměnitelný díl“, ať je hledání v ceníku najde
    novy_klic = klic_kodu(novy_kod)
    zamenitelne = [z.strip() for z in (cil.zamenitelny_dil or "").split(",") if z.strip()]
    for stary in stare_kody:
        if klic_kodu(stary) != novy_klic and all(klic_kodu(z) != klic_kodu(stary) for z in zamenitelne):
            zamenitelne.append(stary)
    cil.zamenitelny_dil = ", ".join(zamenitelne) or None
    session.add(cil)

    # řádky zakázek: napojené na karty skupiny, i ručně zapsané se starým kódem bez vazby na ceník
    podminka = col(PolozkaZakazky.polozka_ceniku_id).in_(ids)
    if stare_kody:
        podminka = or_(podminka, (col(PolozkaZakazky.polozka_ceniku_id).is_(None)
                                  & (PolozkaZakazky.typ == cil.typ) & col(PolozkaZakazky.kod).in_(stare_kody)))
    radky = list(session.exec(select(PolozkaZakazky).where(podminka)))
    for r in radky:
        r.polozka_ceniku_id, r.kod, r.katalog_id = cil.id, novy_kod, cil.katalog_id
        session.add(r)
    session.commit()
    return Vysledek(novy_kod, len(zdroje), len(radky))


# ---------------------------------------------------------------- hromadně ze seznamu CSV

def _cislo_csv(hodnota) -> str:
    if hodnota is None:
        return ""
    return f"{Decimal(hodnota):.2f}".replace(".", ",")


def navrh_csv(session: Session, hledat: str | None = None) -> bytes:
    """Návrh skupin jako CSV pro Excel (středník, desetinná čárka, UTF-8 s BOM)."""
    vystup = io.StringIO()
    zapis = csv.writer(vystup, delimiter=";", lineterminator="\r\n")
    zapis.writerow(SLOUPCE)
    for cislo, s in enumerate(navrhy(session, hledat), start=1):
        for k in s.karty:
            je_cil = k.id == s.cil_id
            zapis.writerow([cislo, k.id, "ano" if je_cil else "", "ano", k.kod, k.nazev, k.katalog,
                            _cislo_csv(k.cena), _cislo_csv(k.nakupni_cena), k.pouzito,
                            k.kod if je_cil else "", k.nazev if je_cil else "", _cislo_csv(k.cena) if je_cil else ""])
    return ("﻿" + vystup.getvalue()).encode("utf-8")


@dataclass
class PlanSkupiny:
    """Jedna skupina ze seznamu CSV: co se sloučí a případná chyba (taková skupina se přeskočí)."""
    skupina: str
    cil_id: int | None
    ids: list[int]
    kod: str = ""
    nazev: str = ""
    cena: str = ""
    chyba: str = ""
    karty: list[dict] = field(default_factory=list)  # pro náhled: id, kod, nazev, katalog, pouzito


def _dekoduj(obsah: bytes) -> str:
    for kodovani in ("utf-8-sig", "cp1250"):
        try:
            return obsah.decode(kodovani)
        except UnicodeDecodeError:
            continue
    raise ChybaValidace(CHYBA_SOUBORU)


def nacti_csv(session: Session, obsah: bytes) -> list[PlanSkupiny]:
    """Seznam CSV → skupiny ke sloučení (zkontrolované proti databázi, nic se neukládá).
    Skupinu tvoří řádky se stejným číslem ve sloupci Skupina a „ano“ ve sloupci Sloučit."""
    if not obsah:
        raise ChybaValidace("Vyberte soubor se seznamem ke sloučení.")
    text = _dekoduj(obsah)
    prvni = text.splitlines()[0] if text.strip() else ""
    oddelovac = ";" if ";" in prvni or "," not in prvni else ","
    ctecka = csv.reader(io.StringIO(text), delimiter=oddelovac)
    zahlavi = [b.strip() for b in next(ctecka, [])]
    try:
        sl = {nazev: zahlavi.index(nazev) for nazev in ("Skupina", "ID", "Ponechat", "Sloučit", "Nový kód",
                                                        "Nový název", "Nová cena bez DPH")}
    except ValueError:
        raise ChybaValidace(CHYBA_SOUBORU) from None

    def bunka(radek, nazev):
        i = sl[nazev]
        return radek[i].strip() if i < len(radek) else ""

    radky: dict[str, list[list[str]]] = defaultdict(list)
    for radek in ctecka:
        if not any(b.strip() for b in radek):
            continue
        if bunka(radek, "Sloučit").casefold() in _ANO and bunka(radek, "Skupina"):
            radky[bunka(radek, "Skupina")].append(radek)

    karty = {p.id: p for p in session.exec(select(PolozkaCeniku).where(PolozkaCeniku.typ == TypPolozky.MATERIAL))}
    katalogy = {k.id: k.nazev for k in session.exec(select(Katalog))}
    pouziti = _pocty_pouziti(session)
    plany = []
    for skupina, rr in radky.items():
        plan = PlanSkupiny(skupina, None, [])
        for r in rr:
            hodnota = bunka(r, "ID")
            if not hodnota.isdigit() or int(hodnota) not in karty:
                plan.chyba = plan.chyba or f"Karta s ID „{hodnota}“ v ceníku není."
                continue
            p = karty[int(hodnota)]
            plan.ids.append(p.id)
            plan.karty.append({"id": p.id, "kod": p.kod or "", "nazev": p.nazev,
                               "katalog": katalogy.get(p.katalog_id, ""), "pouzito": pouziti.get(p.id, 0),
                               "aktivni": p.aktivni})
            if bunka(r, "Ponechat").casefold() in _ANO:
                if plan.cil_id is not None:
                    plan.chyba = plan.chyba or "Ponechat jde jen jednu kartu ze skupiny."
                plan.cil_id = p.id
                plan.kod, plan.nazev, plan.cena = bunka(r, "Nový kód"), bunka(r, "Nový název"), bunka(r, "Nová cena bez DPH")
        if not plan.chyba:
            plan.chyba = _chyba_planu(plan, karty)
        plany.append(plan)
    return sorted(plany, key=lambda p: (bool(p.chyba), _poradi(p.skupina)))


def _poradi(skupina: str):
    return (0, int(skupina), "") if skupina.isdigit() else (1, 0, skupina)


def _chyba_planu(plan: PlanSkupiny, karty: dict) -> str:
    if len(set(plan.ids)) < 2:
        return "Ve skupině je méně než dvě karty ke sloučení."
    if plan.cil_id is None:
        return "Chybí karta k ponechání (sloupec Ponechat = ano)."
    if not karty[plan.cil_id].aktivni:
        return "Ponechaná karta je vyřazená."
    try:
        desetinne_nebo_none(plan.cena, "Nová cena")
    except ChybaValidace as e:
        return str(e)
    return ""


def do_json(plany: list[PlanSkupiny]) -> str:
    return json.dumps([asdict(p) for p in plany], ensure_ascii=False)


def z_json(data: str) -> list[PlanSkupiny]:
    try:
        return [PlanSkupiny(**p) for p in json.loads(data)]
    except (ValueError, TypeError):
        raise ChybaValidace("Náhled seznamu se nepodařilo načíst – nahrajte soubor znovu.") from None


@dataclass
class Souhrn:
    slouceno: list[Vysledek] = field(default_factory=list)
    chyby: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        karet, radku = sum(v.karet for v in self.slouceno), sum(v.radku for v in self.slouceno)
        text = (f"Sloučeno skupin {len(self.slouceno)}: vyřazeno karet {karet}, "
                f"přepsáno řádků zakázek {radku}.")
        if self.chyby:
            text += f" Přeskočeno skupin {len(self.chyby)}."
        return text


def sluc_seznam(session: Session, plany: list[PlanSkupiny], dnes: date | None = None) -> Souhrn:
    """Sloučí skupiny bez chyby; každá skupina zvlášť, chybná se přeskočí a ostatní se uloží."""
    souhrn = Souhrn()
    for plan in plany:
        if plan.chyba:
            continue
        try:
            souhrn.slouceno.append(sluc(session, plan.cil_id, plan.ids, plan.kod, plan.nazev, plan.cena, dnes=dnes))
        except ChybaValidace as e:
            session.rollback()
            souhrn.chyby.append(f"Skupina {plan.skupina}: {e}")
    return souhrn
