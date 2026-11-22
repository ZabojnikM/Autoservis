"""Datové modely (tabulky databáze)."""
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

from pydantic import NaiveDatetime
from sqlalchemy import Index, String, TypeDecorator
from sqlmodel import Field, Relationship, SQLModel


class DesetinneCislo(TypeDecorator):
    """Přesné desetinné číslo (peníze, množství) uložené v SQLite jako text."""

    impl = String
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return None if value is None else str(Decimal(value))

    def process_result_value(self, value, dialect):
        return None if value is None else Decimal(value)


def zaokrouhli(castka: Decimal) -> Decimal:
    """Na haléře, obchodně (0,005 → 0,01)."""
    return Decimal(castka).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


class TypPolozky:
    PRACE = "prace"
    MATERIAL = "material"
    VSECHNY = [PRACE, MATERIAL]
    NAZVY = {PRACE: "Práce", MATERIAL: "Materiál"}


class StavZakazky:
    """Stavy zakázky v pořadí, jak jdou za sebou."""

    PRIJATO = "prijato"
    V_OPRAVE = "v_oprave"
    HOTOVO = "hotovo"
    PREDANO = "predano"

    VSECHNY = [PRIJATO, V_OPRAVE, HOTOVO, PREDANO]
    OTEVRENE = [PRIJATO, V_OPRAVE, HOTOVO]
    # #166: seznam zakázek má jen Otevřené (bez dokladu, i předané) a Uzavřené (s dokladem / bez dokladu)
    ZALOZKA_OTEVRENE = [PRIJATO, V_OPRAVE, HOTOVO]
    ZALOZKY = [("predano", "Uzavřené")]
    NAZVY = {
        PRIJATO: "Přijato",
        V_OPRAVE: "V opravě",
        HOTOVO: "Předáno",   # vozidlo předané zákazníkovi, zatím bez dokladu
        PREDANO: "Uzavřeno",  # vystavený doklad (kód stavu zůstává „predano“ kvůli datům)
    }


STAVY_PALIVA = ["", "rezerva", "1/4", "1/2", "3/4", "plná"]


class Zakaznik(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    nazev: str = Field(index=True, description="Jméno a příjmení nebo název firmy")
    telefon: Optional[str] = None
    email: Optional[str] = None
    ulice: Optional[str] = None
    mesto: Optional[str] = None
    psc: Optional[str] = None
    ico: Optional[str] = Field(default=None, index=True)
    dic: Optional[str] = None
    poznamka: Optional[str] = None
    vytvoreno: NaiveDatetime = Field(default_factory=datetime.now)

    vozidla: list["Vozidlo"] = Relationship(back_populates="zakaznik")
    zakazky: list["Zakazka"] = Relationship(back_populates="zakaznik")


class Vozidlo(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    spz: str = Field(index=True, unique=True, description="SPZ bez mezer, velkými písmeny")
    vin: Optional[str] = Field(default=None, index=True, unique=True)
    znacka: Optional[str] = None
    model: Optional[str] = None
    rok_vyroby: Optional[int] = None
    datum_registrace: Optional[date] = Field(default=None, description="Datum 1. registrace (z TP)")
    palivo: Optional[str] = None
    motor: Optional[str] = Field(default=None, description="Starší volný popis motoru (nově rozepsán do polí níže)")
    kod_motoru: Optional[str] = None
    objem: Optional[str] = Field(default=None, description="Objem motoru, např. 1896 nebo 1.9 TDI")
    vykon: Optional[str] = Field(default=None, description="Výkon, např. 77 kW")
    cislo_motoru: Optional[str] = Field(default=None, description="Typ vozidla – typ / varianta / verze z TP (např. ACBXEX11 NAM6) – "
                                        "ze starého systému pole CMOTORA; název sloupce zůstal z dřívějška, "
                                        "v aplikaci se zobrazuje jako „Typ vozidla“")
    olej: Optional[str] = None
    barva: Optional[str] = None
    termin_stk: Optional[date] = None
    # #126: stav vozidla v Registru silničních vozidel (StatusNazev, např. PROVOZOVANÉ) a kdy se naposledy načetl
    stav_registru: Optional[str] = None
    registr_nacteno: Optional[NaiveDatetime] = None
    # termin_ek zrušen (EK se nepoužívá) – sloupec v databázi zůstal, aplikace ho nečte
    poznamka: Optional[str] = None
    zakaznik_id: Optional[int] = Field(default=None, foreign_key="zakaznik.id", index=True)
    vytvoreno: NaiveDatetime = Field(default_factory=datetime.now)

    zakaznik: Optional[Zakaznik] = Relationship(back_populates="vozidla")
    zakazky: list["Zakazka"] = Relationship(back_populates="vozidlo")

    @property
    def popis(self) -> str:
        return " ".join(x for x in [self.znacka, self.model] if x) or "—"


class Zakazka(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    cislo: str = Field(index=True, unique=True)
    # zakázka může být i bez vozidla (#50) – stejně jako bez zákazníka
    vozidlo_id: Optional[int] = Field(default=None, foreign_key="vozidlo.id", index=True)
    zakaznik_id: Optional[int] = Field(default=None, foreign_key="zakaznik.id", index=True)
    datum_prijeti: NaiveDatetime = Field(default_factory=datetime.now)
    tachometr: Optional[int] = None
    stav_paliva: Optional[str] = None
    pozadavek: str = Field(default="", description="Požadavek zákazníka / popis závady")
    stav: str = Field(default=StavZakazky.PRIJATO, index=True)
    termin_dokonceni: Optional[date] = None
    poznamka: Optional[str] = None
    uzavreno: Optional[NaiveDatetime] = None

    vozidlo: Optional[Vozidlo] = Relationship(back_populates="zakazky")
    zakaznik: Optional[Zakaznik] = Relationship(back_populates="zakazky")
    polozky: list["PolozkaZakazky"] = Relationship(
        back_populates="zakazka",
        sa_relationship_kwargs={"cascade": "all, delete-orphan", "order_by": "PolozkaZakazky.id"},
    )
    faktury: list["Faktura"] = Relationship(back_populates="zakazka")

    @property
    def platna_faktura(self) -> Optional["Faktura"]:
        """Nestornovaný doklad (faktura / vyúčtování) vystavený k zakázce."""
        return next((f for f in self.faktury if not f.stornovano), None)

    @property
    def uzavrena_bez_dokladu(self) -> bool:
        """Uzavřená ručně bez faktury / vyúčtování (např. záruka) – v seznamech se označí."""
        return self.stav == StavZakazky.PREDANO and self.platna_faktura is None

    @property
    def nazev_stavu(self) -> str:
        return StavZakazky.NAZVY.get(self.stav, self.stav)

    @property
    def je_otevrena(self) -> bool:
        return self.stav in StavZakazky.OTEVRENE

    @property
    def po_terminu(self) -> bool:
        return bool(self.je_otevrena and self.termin_dokonceni and self.termin_dokonceni < date.today())


class Katalog(SQLModel, table=True):
    """Pojmenovaný katalog materiálu (Hlavní katalog, LKQ, …) s vlastními díly a cenami (#62).
    Práce mají jeden společný katalog – patří do výchozího."""

    id: Optional[int] = Field(default=None, primary_key=True)
    nazev: str = Field(unique=True)
    vychozi: bool = Field(default=False)
    poradi: int = Field(default=0)
    # #150: skrytý sklad se nenabízí v zakázkách ani na kartě Materiál; historie i Správa dat ho vidí dál
    skryty: bool = Field(default=False)

    @property
    def nadpis(self) -> str:
        """„LKQ“ → „Katalog LKQ“; název, který slovo katalog už má („Hlavní katalog“), zůstane."""
        return self.nazev if "katalog" in self.nazev.lower() else f"Katalog {self.nazev}"


class PolozkaCeniku(SQLModel, table=True):
    """Položka ceníku – práce (úkon) nebo materiál. Ceny jsou bez DPH.
    Neprázdný kód je jedinečný jen uvnitř svého katalogu (#62)."""

    __table_args__ = (Index("ux_polozkaceniku_katalog_kod", "katalog_id", "kod", unique=True),)

    id: Optional[int] = Field(default=None, primary_key=True)
    katalog_id: Optional[int] = Field(default=None, foreign_key="katalog.id", index=True)
    kod: Optional[str] = Field(default=None, index=True)
    nazev: str = Field(index=True)
    typ: str = Field(default=TypPolozky.MATERIAL, index=True)
    jednotka: str = Field(default="ks")
    cena: Decimal = Field(default=Decimal("0"), sa_type=DesetinneCislo, description="Prodejní cena bez DPH za jednotku")
    # cas_nh (časová norma / normohodiny) zrušeno – sloupec v databázi zůstal, aplikace ho nečte
    sazba_dph: Decimal = Field(default=Decimal("21"), sa_type=DesetinneCislo)
    nakupni_cena: Optional[Decimal] = Field(default=None, sa_type=DesetinneCislo,
                                            description="Nákupní (skladová) cena bez DPH za jednotku")
    zamenitelny_dil: Optional[str] = Field(default=None, description="Kód / číslo zaměnitelného (náhradního) dílu")
    poznamka: Optional[str] = None
    aktivni: bool = Field(default=True, index=True)

    @property
    def nazev_typu(self) -> str:
        return TypPolozky.NAZVY.get(self.typ, self.typ)


class CenaRadku:
    """Výpočty pro řádek dokladu (zakázka, faktura). Potřebuje mnozstvi, cena, sazba_dph, typ."""

    @property
    def nazev_typu(self) -> str:
        return TypPolozky.NAZVY.get(self.typ, self.typ)

    @property
    def zaklad(self) -> Decimal:
        """Cena řádku bez DPH."""
        return zaokrouhli(self.mnozstvi * self.cena)

    @property
    def dph(self) -> Decimal:
        return zaokrouhli(self.zaklad * self.sazba_dph / 100)

    @property
    def celkem(self) -> Decimal:
        return self.zaklad + self.dph


class PolozkaZakazky(CenaRadku, SQLModel, table=True):
    """Řádek zakázky. Údaje se kopírují z ceníku – pozdější změna ceníku zakázku nezmění."""

    id: Optional[int] = Field(default=None, primary_key=True)
    zakazka_id: int = Field(foreign_key="zakazka.id", index=True, ondelete="CASCADE")
    polozka_ceniku_id: Optional[int] = Field(
        default=None, foreign_key="polozkaceniku.id", index=True, ondelete="SET NULL"
    )
    # zdrojový katalog materiálu (#62) – zůstává i po změně vybraného katalogu nebo smazání dílu
    katalog_id: Optional[int] = Field(default=None, foreign_key="katalog.id", ondelete="SET NULL")
    typ: str = Field(default=TypPolozky.MATERIAL)
    kod: Optional[str] = None
    nazev: str
    jednotka: str = Field(default="ks")
    mnozstvi: Decimal = Field(default=Decimal("1"), sa_type=DesetinneCislo)
    cena: Decimal = Field(default=Decimal("0"), sa_type=DesetinneCislo, description="Cena za jednotku bez DPH")
    sazba_dph: Decimal = Field(default=Decimal("21"), sa_type=DesetinneCislo)
    vytvoreno: NaiveDatetime = Field(default_factory=datetime.now)

    cislo_dodaciho_listu: Optional[str] = None

    zakazka: Optional[Zakazka] = Relationship(back_populates="polozky")
    katalog: Optional[Katalog] = Relationship()
    # #163: jen pro zobrazení rozdílu ceny řádku proti ceníku (cena řádku se z ceníku nepřepisuje)
    polozka_ceniku: Optional[PolozkaCeniku] = Relationship()

    @property
    def cena_ceniku_jina(self) -> Decimal | None:
        """Cena v ceníku, když se liší od ceny řádku (ručně upravená cena v zakázce), jinak None."""
        vzor = self.polozka_ceniku
        if vzor is None or vzor.cena == self.cena:
            return None
        return vzor.cena


class TypDokladu:
    FAKTURA = "faktura"
    VYUCTOVANI = "vyuctovani"
    VSECHNY = [FAKTURA, VYUCTOVANI]
    NAZVY = {FAKTURA: "Faktura", VYUCTOVANI: "Vyúčtování"}
    NADPISY = {FAKTURA: "Faktura – daňový doklad", VYUCTOVANI: "Vyúčtování zakázky"}


class FormaUhrady:
    PREVOD = "prevod"
    HOTOVE = "hotove"
    VSECHNY = [PREVOD, HOTOVE]
    NAZVY = {PREVOD: "Převodem", HOTOVE: "Hotově"}


class Faktura(SQLModel, table=True):
    """Vystavený doklad (faktura / vyúčtování). Po vystavení se už nemění – jen úhrady; jde smazat (#15)."""

    id: Optional[int] = Field(default=None, primary_key=True)
    cislo: str = Field(index=True, unique=True)
    typ: str = Field(default=TypDokladu.FAKTURA, index=True)
    zakazka_id: Optional[int] = Field(default=None, foreign_key="zakazka.id", index=True)
    zakaznik_id: Optional[int] = Field(default=None, foreign_key="zakaznik.id", index=True)

    # odběratel – kopie v okamžiku vystavení
    odb_nazev: str = ""
    odb_ulice: Optional[str] = None
    odb_mesto: Optional[str] = None
    odb_psc: Optional[str] = None
    odb_ico: Optional[str] = None
    odb_dic: Optional[str] = None

    datum_vystaveni: date = Field(default_factory=date.today, index=True)
    duzp: date = Field(default_factory=date.today)
    datum_splatnosti: date = Field(default_factory=date.today, index=True)
    forma_uhrady: str = Field(default=FormaUhrady.PREVOD)
    variabilni_symbol: Optional[str] = None
    platce_dph: bool = True
    mena: str = "Kč"
    spz: Optional[str] = None
    vozidlo_popis: Optional[str] = None
    tachometr: Optional[int] = None
    cislo_zakazky: Optional[str] = None
    stav_zakazky_pred: Optional[str] = Field(
        default=None, description="Stav zakázky před vystavením dokladu – smazání dokladu ho vrátí")
    poznamka: Optional[str] = None
    zaokrouhleni: Decimal = Field(default=Decimal("0"), sa_type=DesetinneCislo)
    celkem: Decimal = Field(default=Decimal("0"), sa_type=DesetinneCislo, description="K úhradě vč. DPH a zaokrouhlení")
    # storno zrušeno (#15) – doklad se maže; sloupec zůstal kvůli starším databázím, nové doklady mají vždy False
    stornovano: bool = Field(default=False, index=True)
    # #167: stav tisku – potvrzuje uživatel (prohlížeč tisk neumí ověřit); doklady ze starého systému = vytištěné
    vytisteno: bool = Field(default=False)
    vytisteno_kdy: Optional[NaiveDatetime] = None
    vytvoreno: NaiveDatetime = Field(default_factory=datetime.now)

    polozky: list["PolozkaFaktury"] = Relationship(
        back_populates="faktura",
        sa_relationship_kwargs={"cascade": "all, delete-orphan", "order_by": "PolozkaFaktury.id"},
    )
    uhrady: list["Uhrada"] = Relationship(
        back_populates="faktura",
        sa_relationship_kwargs={"cascade": "all, delete-orphan", "order_by": "Uhrada.datum"},
    )
    zakazka: Optional[Zakazka] = Relationship(back_populates="faktury")

    @property
    def nazev_typu(self) -> str:
        return TypDokladu.NAZVY.get(self.typ, self.typ)

    @property
    def nadpis(self) -> str:
        if self.typ == TypDokladu.FAKTURA and not self.platce_dph:
            return "Faktura"
        return TypDokladu.NADPISY.get(self.typ, self.typ)

    @property
    def nazev_formy_uhrady(self) -> str:
        return FormaUhrady.NAZVY.get(self.forma_uhrady, self.forma_uhrady)

    @property
    def platne_uhrady(self) -> list["Uhrada"]:
        """Úhrady bez zrušených (zrušené zůstávají v historii přeškrtnuté)."""
        return [u for u in self.uhrady if not u.zruseno]

    @property
    def uhrazeno(self) -> Decimal:
        return sum((u.castka for u in self.platne_uhrady), Decimal("0"))

    @property
    def zbyva(self) -> Decimal:
        return Decimal("0") if self.stornovano else self.celkem - self.uhrazeno

    @property
    def je_uhrazena(self) -> bool:
        return self.zbyva <= 0

    @property
    def po_splatnosti(self) -> bool:
        # vyúčtování splatnost neuvádí (#58) – je jen Uhrazeno / Neuhrazeno
        return self.typ == TypDokladu.FAKTURA and not self.je_uhrazena and self.datum_splatnosti < date.today()

    @property
    def stav(self) -> str:
        if self.je_uhrazena:
            return "uhrazena"
        if self.po_splatnosti:
            return "po_splatnosti"
        return "castecne" if self.uhrazeno > 0 else "neuhrazena"

    @property
    def nazev_stavu(self) -> str:
        return {"uhrazena": "Uhrazeno", "po_splatnosti": "Po splatnosti",
                "castecne": "Částečně uhrazeno", "neuhrazena": "Neuhrazeno"}[self.stav]


class PolozkaFaktury(CenaRadku, SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    faktura_id: int = Field(foreign_key="faktura.id", index=True, ondelete="CASCADE")
    typ: str = Field(default=TypPolozky.MATERIAL)
    kod: Optional[str] = None
    nazev: str
    jednotka: str = Field(default="ks")
    mnozstvi: Decimal = Field(default=Decimal("1"), sa_type=DesetinneCislo)
    cena: Decimal = Field(default=Decimal("0"), sa_type=DesetinneCislo)
    sazba_dph: Decimal = Field(default=Decimal("21"), sa_type=DesetinneCislo)

    faktura: Optional[Faktura] = Relationship(back_populates="polozky")


class Uhrada(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    faktura_id: int = Field(foreign_key="faktura.id", index=True, ondelete="CASCADE")
    datum: date = Field(default_factory=date.today)
    castka: Decimal = Field(sa_type=DesetinneCislo, description="Záporná = vrácení")
    zpusob: str = Field(default=FormaUhrady.PREVOD)
    poznamka: Optional[str] = None
    vytvoreno: NaiveDatetime = Field(default_factory=datetime.now)
    zruseno: Optional[NaiveDatetime] = Field(
        default=None, description="Kdy byla úhrada zrušena – nemaže se, zůstane v historii přeškrtnutá")

    faktura: Optional[Faktura] = Relationship(back_populates="uhrady")

    @property
    def nazev_zpusobu(self) -> str:
        return FormaUhrady.NAZVY.get(self.zpusob, self.zpusob)


class SmazaneCislo(SQLModel, table=True):
    """Číslo smazaného dokladu (#15). V přehledu dokladů „Volné po smazání“, dokud se při vystavení ručně
    znovu nepoužije. Počítá se do číselné řady, aby se automaticky znovu nenabízelo."""
    id: Optional[int] = Field(default=None, primary_key=True)
    cislo: str = Field(index=True, unique=True)
    typ: str = Field(default=TypDokladu.FAKTURA, index=True)
    datum_vystaveni: date = Field(description="Datum vystavení smazaného dokladu – místo v přehledu")
    smazano: NaiveDatetime = Field(default_factory=datetime.now)


class ImportMapa(SQLModel, table=True):
    """Vazba importovaného záznamu na původní ID ve zdrojovém systému (např. starý systém).

    Díky ní jde import spustit znovu bez vzniku duplicit.
    """

    id: Optional[int] = Field(default=None, primary_key=True)
    zdroj: str = Field(index=True)
    tabulka: str = Field(index=True)
    puvodni_id: str = Field(index=True)
    nove_id: int
    importovano: NaiveDatetime = Field(default_factory=datetime.now)


class Nastaveni(SQLModel, table=True):
    """Nastavení aplikace jako dvojice klíč – hodnota."""

    klic: str = Field(primary_key=True)
    hodnota: str = ""


class UpravaDat(SQLModel, table=True):
    """Deník hromadných úprav ze záložky Správa dat (#136): co se kdy změnilo a ze které zálohy jde stav vrátit."""

    id: Optional[int] = Field(default=None, primary_key=True)
    cas: NaiveDatetime = Field(default_factory=datetime.now, index=True)
    akce: str
    popis: str = ""
    pocet: int = 0
    zaloha: str = ""


class ApiKlic(SQLModel, table=True):
    """Klíč pro API a MCP (#145) – pro boty v OpenBotu. Ukládá se jen otisk (SHA-256), klíč se ukáže jednou."""

    id: Optional[int] = Field(default=None, primary_key=True)
    nazev: str
    otisk: str = Field(index=True, unique=True)
    zacatek: str = ""            # prvních pár znaků klíče, ať jde v Nastavení poznat
    opravneni: str = ""          # čárkami: sklad,zakazky,vozidla
    aktivni: bool = Field(default=True)
    vytvoreno: NaiveDatetime = Field(default_factory=datetime.now)
    naposledy: Optional[NaiveDatetime] = None

    @property
    def seznam_opravneni(self) -> list[str]:
        return [o for o in self.opravneni.split(",") if o]
