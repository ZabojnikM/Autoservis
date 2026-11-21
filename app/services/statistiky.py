"""Statistiky výkonu servisu (#160): uzavřené zakázky po měsících a za rok.

Zdroj jsou uzavřené zakázky (datum uzavření), ne doklady – doklady jsou v aplikaci až od roku 2026,
zakázky i ze starého systému. Nákup materiálu je odhad: řádek zakázky nákupní cenu neukládá, bere se
dnešní nákupní cena dílu z ceníku. Řádky bez vazby na ceník nebo bez nákupní ceny se do výdělku
nepočítají a vrací se jejich počet.
"""
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from sqlmodel import Session, func, select

from app.models import PolozkaCeniku, PolozkaZakazky, TypPolozky, Zakazka, zaokrouhli

MESICE = ["leden", "únor", "březen", "duben", "květen", "červen",
          "červenec", "srpen", "září", "říjen", "listopad", "prosinec"]
JEDNOTKY_HODIN = {"hod", "h", "hodina", "hodiny", "hodin", "nh"}


@dataclass
class Souhrn:
    nazev: str = ""
    zakazek: int = 0
    material_prodej: Decimal = Decimal("0")
    material_nakup: Decimal = Decimal("0")        # jen řádky s nákupní cenou
    material_s_nakupem: Decimal = Decimal("0")    # prodej řádků, u kterých nákup známe
    prace: Decimal = Decimal("0")
    hodiny: Decimal = Decimal("0")
    bez_nakupu: int = 0                           # řádky materiálu bez nákupní ceny
    _zakazky: set = field(default_factory=set, repr=False)

    @property
    def material_vydelek(self) -> Decimal:
        return self.material_s_nakupem - self.material_nakup

    @property
    def celkem(self) -> Decimal:
        return self.material_prodej + self.prace

    @property
    def vydelek_celkem(self) -> Decimal:
        """Práce + výdělek na materiálu (odhad)."""
        return self.prace + self.material_vydelek

    def pridej(self, radek: PolozkaZakazky, nakupni_cena: Decimal | None) -> None:
        self._zakazky.add(radek.zakazka_id)
        self.zakazek = len(self._zakazky)
        zaklad = radek.zaklad
        if radek.typ == TypPolozky.PRACE:
            self.prace += zaklad
            if (radek.jednotka or "").strip().lower().rstrip(".") in JEDNOTKY_HODIN:
                self.hodiny += radek.mnozstvi
            return
        self.material_prodej += zaklad
        if nakupni_cena is None:
            self.bez_nakupu += 1
        else:
            self.material_nakup += zaokrouhli(radek.mnozstvi * nakupni_cena)
            self.material_s_nakupem += zaklad


@dataclass
class Rozdil:
    nazev: str
    letos: Decimal
    loni: Decimal

    @property
    def rozdil(self) -> Decimal:
        return self.letos - self.loni

    @property
    def procent(self) -> Decimal | None:
        if not self.loni:
            return None
        return (self.rozdil * 100 / self.loni).quantize(Decimal("0.1"))


@dataclass
class StatistikaRoku:
    rok: int
    mesice: list[Souhrn]
    rok_celkem: Souhrn
    loni: Souhrn
    srovnani: list[Rozdil]
    roky: list[int]
    do_mesice: int | None = None   # u běžného roku: srovnání s loňskem jen do tohoto měsíce


def roky_se_zakazkami(session: Session) -> list[int]:
    rok = func.substr(Zakazka.uzavreno, 1, 4)
    hodnoty = session.exec(select(rok).where(Zakazka.uzavreno.is_not(None)).distinct()).all()
    return sorted((int(r) for r in hodnoty if r and str(r).isdigit()), reverse=True)


def _radky_roku(session: Session, rok: int):
    od, do = datetime(rok, 1, 1), datetime(rok + 1, 1, 1)
    dotaz = (select(PolozkaZakazky, Zakazka.uzavreno, PolozkaCeniku.nakupni_cena)
             .join(Zakazka, PolozkaZakazky.zakazka_id == Zakazka.id)
             .outerjoin(PolozkaCeniku, PolozkaZakazky.polozka_ceniku_id == PolozkaCeniku.id)
             .where(Zakazka.uzavreno >= od, Zakazka.uzavreno < do))
    return session.exec(dotaz).all()


def _souhrn_roku(session: Session, rok: int, do_mesice: int | None = None) -> tuple[list[Souhrn], Souhrn]:
    mesice = [Souhrn(nazev=n) for n in MESICE]
    celkem = Souhrn(nazev=str(rok))
    for radek, uzavreno, nakupni in _radky_roku(session, rok):
        if do_mesice and uzavreno.month > do_mesice:
            continue
        mesice[uzavreno.month - 1].pridej(radek, nakupni)
        celkem.pridej(radek, nakupni)
    return mesice, celkem


def statistika(session: Session, rok: int | None = None, dnes: datetime | None = None) -> StatistikaRoku:
    dnes = dnes or datetime.now()
    roky = roky_se_zakazkami(session)
    rok = rok or (roky[0] if roky else dnes.year)
    mesice, rok_celkem = _souhrn_roku(session, rok)
    # běžný rok se srovná se stejným obdobím loni (leden až aktuální měsíc), jinak celé roky
    do_mesice = dnes.month if rok == dnes.year else None
    _, loni = _souhrn_roku(session, rok - 1, do_mesice)
    loni.nazev = str(rok - 1)
    letos = rok_celkem
    if do_mesice:
        letos = Souhrn(nazev=str(rok))
        for m in mesice[:do_mesice]:
            for pole in ("material_prodej", "material_nakup", "material_s_nakupem", "prace", "hodiny"):
                setattr(letos, pole, getattr(letos, pole) + getattr(m, pole))
            letos.zakazek += m.zakazek
    srovnani = [
        Rozdil("Zakázek", Decimal(letos.zakazek), Decimal(loni.zakazek)),
        Rozdil("Materiál prodej bez DPH", letos.material_prodej, loni.material_prodej),
        Rozdil("Výdělek na materiálu (odhad)", letos.material_vydelek, loni.material_vydelek),
        Rozdil("Práce bez DPH", letos.prace, loni.prace),
        Rozdil("Hodiny práce", letos.hodiny, loni.hodiny),
        Rozdil("Celkem bez DPH", letos.celkem, loni.celkem),
    ]
    return StatistikaRoku(rok=rok, mesice=mesice, rok_celkem=rok_celkem, loni=loni, srovnani=srovnani,
                          roky=roky, do_mesice=do_mesice)
