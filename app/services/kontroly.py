"""Správa dat – kontroly kvality ceníku (#141) a přehledy skladu (#143)."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from sqlmodel import Session, col, func, select

from app.models import PolozkaCeniku, PolozkaZakazky, TypPolozky
from app.services import slouceni, sprava


@dataclass
class Kontrola:
    nazev: str
    pocet: int
    odkaz: str
    popis: str


def prehled_kontrol(session: Session) -> list[Kontrola]:
    """Počty problémů s odkazem na opravu (filtr v Díly, Sloučit díly, napojení řádků)."""
    vsechny = sprava.vyber(session, sprava.Filtr())
    pocet = lambda problem: sum(1 for r in vsechny if sprava._odpovida_problem(r, problem))  # noqa: E731
    bez_vazby = session.exec(select(func.count()).select_from(PolozkaZakazky).where(
        col(PolozkaZakazky.polozka_ceniku_id).is_(None), PolozkaZakazky.typ == TypPolozky.MATERIAL)).one()
    return [
        Kontrola("Stejný díl pod více kódy", len(slouceni.navrhy(session)), "/sprava-dat/slouceni-dilu",
                 "Skupiny aktivních dílů se stejným číslem dílu – sloučit do jednoho kódu."),
        Kontrola("Prodej pod nákupní cenou", pocet("pod_nakupem"), "/sprava-dat/dily?problem=pod_nakupem",
                 "Prodejní cena je nižší než nákupní – opravit hromadnou změnou cen (podle marže)."),
        Kontrola("Nulová prodejní cena", pocet("nulova_cena"), "/sprava-dat/dily?problem=nulova_cena",
                 "Díl by se do zakázky vložil zadarmo."),
        Kontrola("Bez nákupní ceny", pocet("bez_nakupu"), "/sprava-dat/dily?problem=bez_nakupu",
                 "Nejde spočítat marži ani nastavit cenu podle marže."),
        Kontrola("Podezřelý zápis kódu", pocet("kod_podezrely"), "/sprava-dat/dily?problem=kod_podezrely",
                 "Mezery navíc nebo malá písmena – sjednotit v Úpravě kódů."),
        Kontrola("Díl bez kódu", pocet("bez_kodu"), "/sprava-dat/dily?problem=bez_kodu",
                 "Díl nejde najít podle čísla ani spárovat při importu."),
        Kontrola("Řádky zakázek bez vazby na ceník", bez_vazby, "/sprava-dat/kontroly/bez-vazby",
                 "Materiál v zakázkách, který nepatří k žádné kartě – historie a vložení z historie ho neznají."),
    ]


# ---------------------------------------------------------------- řádky zakázek bez vazby na ceník

@dataclass
class SkupinaBezVazby:
    kod: str
    nazev: str
    radku: int
    karty: list = field(default_factory=list)   # aktivní karty se stejným kódem

    @property
    def karta(self):
        """Napojit jde jen na jedinou aktivní kartu se stejným kódem."""
        return self.karty[0] if len(self.karty) == 1 else None


def bez_vazby(session: Session) -> list[SkupinaBezVazby]:
    """Řádky materiálu bez karty seskupené podle kódu, s kartami, na které jde řádky napojit."""
    skupiny: dict[str, SkupinaBezVazby] = {}
    for r in session.exec(select(PolozkaZakazky).where(col(PolozkaZakazky.polozka_ceniku_id).is_(None),
                                                       PolozkaZakazky.typ == TypPolozky.MATERIAL)):
        kod = (r.kod or "").strip()
        s = skupiny.setdefault(kod, SkupinaBezVazby(kod, r.nazev, 0))
        s.radku += 1
    karty = defaultdict(list)
    for p in session.exec(select(PolozkaCeniku).where(PolozkaCeniku.typ == TypPolozky.MATERIAL,
                                                      PolozkaCeniku.aktivni == True)):  # noqa: E712
        if p.kod:
            karty[p.kod.strip()].append(p)
    for s in skupiny.values():
        s.karty = karty.get(s.kod, []) if s.kod else []
    return sorted(skupiny.values(), key=lambda s: (s.karta is None, -s.radku, s.kod))


def napoj(session: Session, kody: list[str]) -> int:
    """Napojí řádky bez vazby se zadanými kódy na jedinou aktivní kartu se stejným kódem. Ceny se nemění."""
    mapa = {s.kod: s.karta for s in bez_vazby(session) if s.karta is not None and s.kod in set(kody)}
    pocet = 0
    for r in session.exec(select(PolozkaZakazky).where(col(PolozkaZakazky.polozka_ceniku_id).is_(None),
                                                       PolozkaZakazky.typ == TypPolozky.MATERIAL)):
        karta = mapa.get((r.kod or "").strip())
        if karta is not None:
            r.polozka_ceniku_id, r.katalog_id = karta.id, karta.katalog_id
            session.add(r)
            pocet += 1
    session.commit()
    return pocet


# ---------------------------------------------------------------- přehledy (#143)

@dataclass
class MarzeSkupiny:
    nazev: str
    dilu: int = 0
    s_nakupem: int = 0
    pod_nakupem: int = 0
    soucet_marzi: Decimal = Decimal("0")

    @property
    def prumer(self) -> Decimal | None:
        return (self.soucet_marzi / self.s_nakupem).quantize(Decimal("0.1")) if self.s_nakupem else None


def _pridej(skupina: MarzeSkupiny, r: sprava.Radek) -> None:
    skupina.dilu += 1
    if r.marze is not None:
        skupina.s_nakupem += 1
        skupina.soucet_marzi += r.marze
        if r.marze < 0:
            skupina.pod_nakupem += 1


def prehledy(session: Session, dnes: date | None = None) -> dict:
    dnes = dnes or date.today()
    aktivni = sprava.vyber(session, sprava.Filtr(razeni="-pouzito"))
    nikdy = sum(1 for r in aktivni if not r.pouzito)
    bez_pohybu = []
    for let in (1, 2, 5):
        hranice = dnes.replace(year=dnes.year - let)
        bez_pohybu.append((f"nepoužité {let} {'rok' if let == 1 else 'roky' if let < 5 else 'let'}",
                           sum(1 for r in aktivni if not r.posledni or r.posledni < hranice),
                           f"/sprava-dat/dily?nepouzito_od={hranice:%d.%m.%Y}"))
    podle_skladu: dict[str, MarzeSkupiny] = {}
    podle_vyrobce: dict[str, MarzeSkupiny] = {}
    for r in aktivni:
        _pridej(podle_skladu.setdefault(r.katalog, MarzeSkupiny(r.katalog)), r)
        kod = r.karta.kod or ""
        vyrobce = kod.strip().split()[0].upper() if slouceni.ma_predponu(kod) else "bez předpony"
        _pridej(podle_vyrobce.setdefault(vyrobce, MarzeSkupiny(vyrobce)), r)
    return {
        "nejpouzivanejsi": [r for r in aktivni if r.pouzito][:30],
        "aktivnich": len(aktivni),
        "nikdy": nikdy,
        "bez_pohybu": bez_pohybu,
        "podle_skladu": sorted(podle_skladu.values(), key=lambda s: -s.dilu),
        "podle_vyrobce": sorted(podle_vyrobce.values(), key=lambda s: -s.dilu)[:25],
    }
