"""Import seznamu dílů do (nového) skladu s napárováním starých karet (#134).

Postup: `nacti` (soubor → řádky) → `navrh` (ke každému řádku staré karty se stejným číslem dílu)
→ náhled, kde uživatel párování upraví → `importuj`:

- v cílovém katalogu se založí karta s kódem, názvem a cenami ze seznamu (existující se stejným kódem
  dostane nové ceny),
- vybrané staré karty se do ní sloučí stejně jako ve Sloučit díly (#130): zakázky dostanou nový kód
  a vazbu, ceny v zakázkách a doklady se nemění, staré karty se vyřadí.

Čte dodací list z e-shopu LKQ (`import_lkq`) i obecnou tabulku CSV, kde pozná sloupce podle záhlaví
(kód, název, prodej / MOC / cena, nákup, DPH) – tedy i vlastní export skladu ze Správy dat.

Rozšíření (#137): režim (jen nové / jen aktualizace / obojí), párování (číslo dílu se sloučením starých karet,
nebo jen přesný kód) a díly cílového skladu, které v souboru chybí (volitelně se vyřadí).
"""
from __future__ import annotations

import csv
import io
import json
import unicodedata
from dataclasses import asdict, dataclass, field
from decimal import Decimal

from sqlmodel import Session, col, select

from app.models import PolozkaCeniku, TypPolozky
from app.services import ChybaValidace, cenik, cisty_text, desetinne_nebo_none, import_lkq, katalogy, slouceni

CHYBA_SOUBORU = ("Soubor se nepodařilo přečíst. Nahrajte dodací list LKQ (CSV) nebo tabulku CSV se záhlavím, "
                 "ve kterém jsou sloupce Kód, Název a Prodej (případně MOC nebo Cena) a nepovinně Nákup.")


@dataclass
class Radek:
    kod: str
    nazev: str
    cena: Decimal | None      # prodejní bez DPH
    nakup: Decimal | None = None
    dph: Decimal | None = None


def _bez_diakritiky(text: str) -> str:
    return "".join(z for z in unicodedata.normalize("NFD", text) if not unicodedata.combining(z)).lower().strip()


def _sloupec(zahlavi: list[str], *zacatky: str) -> int | None:
    for zacatek in zacatky:
        for i, nazev in enumerate(zahlavi):
            if nazev.startswith(zacatek):
                return i
    return None


def _tabulka(text: str) -> list[Radek]:
    radky = [r for r in text.splitlines() if r.strip()]
    if not radky:
        raise ChybaValidace(CHYBA_SOUBORU)
    oddelovac = ";" if ";" in radky[0] or "," not in radky[0] else ","
    ctecka = list(csv.reader(io.StringIO("\n".join(radky)), delimiter=oddelovac))
    zahlavi = [_bez_diakritiky(b) for b in ctecka[0]]
    i_kod = _sloupec(zahlavi, "kod", "cislo dilu", "katalogove cislo", "objednaci cislo")
    i_nazev = _sloupec(zahlavi, "nazev", "popis")
    i_cena = _sloupec(zahlavi, "prodej", "moc", "doporucena", "cena")
    i_nakup = _sloupec(zahlavi, "nakup", "cena/ks")
    i_dph = _sloupec(zahlavi, "dph", "sazba dph")
    if i_kod is None or i_nazev is None or i_cena is None:
        raise ChybaValidace(CHYBA_SOUBORU)
    vysledek = []
    for cislo, r in enumerate(ctecka[1:], start=2):
        bunka = lambda i: r[i].strip() if i is not None and i < len(r) else ""  # noqa: E731
        kod = bunka(i_kod)
        if not kod:
            continue
        vysledek.append(Radek(kod, bunka(i_nazev) or kod,
                              desetinne_nebo_none(bunka(i_cena), f"Řádek {cislo}: prodejní cena"),
                              desetinne_nebo_none(bunka(i_nakup), f"Řádek {cislo}: nákupní cena") if i_nakup != i_cena else None,
                              desetinne_nebo_none(bunka(i_dph), f"Řádek {cislo}: DPH")))
    return vysledek


def nacti(obsah: bytes) -> list[Radek]:
    """Soubor → řádky seznamu. Stejný kód vícekrát = poslední výskyt."""
    if not obsah:
        raise ChybaValidace("Vyberte soubor se seznamem dílů.")
    try:
        dodaci_list = import_lkq.nacti_csv(obsah)
        radky = [Radek(d.kod, d.nazev, d.moc, d.nakup, d.dph) for d in dodaci_list.dily]
    except ChybaValidace:
        radky = _tabulka(import_lkq._dekoduj(obsah))
    podle_kodu = {}
    for r in radky:
        podle_kodu[r.kod.strip()] = r
    if not podle_kodu:
        raise ChybaValidace("V seznamu nejsou žádné díly.")
    return list(podle_kodu.values())


# ---------------------------------------------------------------- návrh párování

@dataclass
class RadekNavrhu:
    index: int
    kod: str
    nazev: str
    cena: str            # text pro JSON a formulář („199.00“), prázdné = chybí
    nakup: str
    dph: str = ""
    existujici_id: int | None = None          # karta se stejným kódem v cílovém katalogu
    existujici_cena: str = ""
    stare: list[dict] = field(default_factory=list)   # id, kod, nazev, katalog, cena, pouzito
    chyba: str = ""


def _text(cislo: Decimal | None) -> str:
    return "" if cislo is None else str(cislo)


REZIMY = {"obe": "nové díly i aktualizace cen", "nove": "jen nové díly", "aktualizace": "jen aktualizace cen"}
PAROVANI = {"cislo": "podle čísla dílu (sloučit staré karty)", "kod": "jen podle přesného kódu"}


def navrh(session: Session, radky: list[Radek], katalog_id: int | None, rezim: str = "obe",
          parovani: str = "cislo") -> list[RadekNavrhu]:
    """Ke každému řádku staré aktivní karty materiálu se stejným číslem dílu (jiný kód nebo jiný katalog);
    při párování „kod“ se staré karty nehledají. Řádky mimo zvolený režim dostanou důvod v `chyba`."""
    nazvy_katalogu = {k.id: k.nazev for k in katalogy.seznam(session)}
    pouziti = slouceni._pocty_pouziti(session)
    podle_klice: dict[str, list[PolozkaCeniku]] = {}
    for p in session.exec(select(PolozkaCeniku).where(PolozkaCeniku.typ == TypPolozky.MATERIAL,
                                                      PolozkaCeniku.aktivni == True,  # noqa: E712
                                                      col(PolozkaCeniku.kod).is_not(None))):
        podle_klice.setdefault(slouceni.klic_kodu(p.kod), []).append(p)
    vysledek = []
    for i, r in enumerate(radky):
        klic = slouceni.klic_kodu(r.kod)
        radek = RadekNavrhu(i, r.kod, r.nazev, _text(r.cena), _text(r.nakup), _text(r.dph))
        existujici = cenik.najdi_podle_kodu(session, r.kod, katalog_id) if katalog_id else None
        if existujici is not None:
            radek.existujici_id, radek.existujici_cena = existujici.id, _text(existujici.cena)
        kandidati = podle_klice.get(klic, []) if parovani == "cislo" and len(klic) >= slouceni.NEJKRATSI_KLIC else []
        for p in kandidati:
            if p.id == radek.existujici_id:
                continue
            radek.stare.append({"id": p.id, "kod": p.kod, "nazev": p.nazev, "katalog": nazvy_katalogu.get(p.katalog_id, ""),
                                "cena": _text(p.cena), "pouzito": pouziti.get(p.id, 0)})
        if rezim == "nove" and radek.existujici_id:
            radek.chyba = "Už je ve skladu – režim „jen nové díly“."
        elif rezim == "aktualizace" and not radek.existujici_id:
            radek.chyba = "Ve skladu není – režim „jen aktualizace cen“."
        elif r.cena is None and radek.existujici_id is None:
            radek.chyba = "Chybí prodejní cena – nový díl nejde založit."
        vysledek.append(radek)
    # nahoru řádky se starými kartami (ty se slučují), pak nejpoužívanější
    return sorted(vysledek, key=lambda r: (bool(r.chyba), not r.stare, -sum(s["pouzito"] for s in r.stare), r.kod))


def chybejici(session: Session, radky: list[Radek] | list[RadekNavrhu], katalog_id: int | None) -> list[PolozkaCeniku]:
    """Aktivní díly cílového skladu, jejichž kód v souboru není (kandidáti na vyřazení)."""
    if not katalog_id:
        return []
    kody = {r.kod.strip() for r in radky}
    return [p for p in session.exec(select(PolozkaCeniku).where(PolozkaCeniku.katalog_id == katalog_id,
                                                                PolozkaCeniku.typ == TypPolozky.MATERIAL,
                                                                PolozkaCeniku.aktivni == True)  # noqa: E712
                                    .order_by(PolozkaCeniku.kod))
            if (p.kod or "").strip() not in kody]


def do_json(navrh_: list[RadekNavrhu]) -> str:
    return json.dumps([asdict(r) for r in navrh_], ensure_ascii=False)


def z_json(data: str) -> list[RadekNavrhu]:
    try:
        return [RadekNavrhu(**r) for r in json.loads(data)]
    except (ValueError, TypeError):
        raise ChybaValidace("Náhled importu se nepodařilo načíst – nahrajte soubor znovu.") from None


# ---------------------------------------------------------------- import

@dataclass
class Souhrn:
    zalozeno: int = 0
    aktualizovano: int = 0
    slouceno_karet: int = 0
    prepsano_radku: int = 0
    chyby: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        text = (f"Import: založeno dílů {self.zalozeno}, aktualizováno {self.aktualizovano}, "
                f"sloučeno starých karet {self.slouceno_karet}, přepsáno řádků zakázek {self.prepsano_radku}.")
        if self.chyby:
            text += f" Přeskočeno řádků {len(self.chyby)}."
        return text


def najdi_stare_kody(session: Session, text: str | None) -> tuple[list[int], list[str]]:
    """Ručně dopsané staré kódy (oddělené čárkou nebo středníkem) → (id aktivních karet materiálu, nenalezené)."""
    ids, chybi = [], []
    for kod in [k.strip() for k in (text or "").replace(";", ",").split(",") if k.strip()]:
        karty = session.exec(select(PolozkaCeniku.id).where(PolozkaCeniku.kod == kod,
                                                            PolozkaCeniku.typ == TypPolozky.MATERIAL,
                                                            PolozkaCeniku.aktivni == True)).all()  # noqa: E712
        ids.extend(karty) if karty else chybi.append(kod)
    return ids, chybi


def importuj(session: Session, radky: list[RadekNavrhu], katalog_id: int, stare: dict[int, list[int]]) -> Souhrn:
    """`radky` = vybrané řádky náhledu, `stare` = {index řádku: id starých karet ke sloučení}.
    Každý řádek se ukládá zvlášť; chybný se přeskočí a ostatní se uloží."""
    katalog = katalogy.ziskej(session, katalog_id)
    souhrn = Souhrn()
    for r in radky:
        if r.chyba:
            continue
        try:
            cena = desetinne_nebo_none(r.cena, "Prodejní cena")
            nakup = desetinne_nebo_none(r.nakup, "Nákupní cena")
            dph = desetinne_nebo_none(r.dph, "DPH")
            karta = cenik.najdi_podle_kodu(session, r.kod, katalog.id)
            if karta is not None:
                if not karta.aktivni:
                    karta.aktivni = True
                if cena is not None:
                    karta.cena = cena
                if nakup is not None:
                    karta.nakupni_cena = nakup
                if dph is not None:
                    karta.sazba_dph = dph
                session.add(karta)
                session.commit()
                souhrn.aktualizovano += 1
            else:
                if cena is None:
                    raise ChybaValidace("chybí prodejní cena")
                data = {"kod": r.kod, "nazev": r.nazev, "cena": str(cena), "katalog_id": str(katalog.id)}
                if nakup is not None:
                    data["nakupni_cena"] = str(nakup)
                if dph is not None:
                    data["sazba_dph"] = str(dph)
                karta = cenik.vytvor(session, data)
                souhrn.zalozeno += 1
            ids = [i for i in stare.get(r.index, []) if i != karta.id]
            if ids:
                v = slouceni.sluc(session, karta.id, ids)
                souhrn.slouceno_karet += v.karet
                souhrn.prepsano_radku += v.radku
        except ChybaValidace as e:
            session.rollback()
            souhrn.chyby.append(f"{r.kod}: {e}")
    return souhrn
