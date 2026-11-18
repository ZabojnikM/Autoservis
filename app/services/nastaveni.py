"""Nastavení servisu (DPH, údaje servisu, číselné řady…)."""
from dataclasses import dataclass, fields
from decimal import Decimal

from sqlmodel import Session

from app.models import Nastaveni
from app.services import ChybaValidace, cislo_nebo_none, desetinne_nebo_none

TEXTOVA_POLE = [
    "mena", "nazev_servisu", "ulice", "mesto", "psc", "ico", "dic", "telefon", "email", "web",
    "cislo_uctu", "iban", "vystavil", "rada_faktura", "rada_vyuctovani", "text_pod_fakturou",
    "api_klic_registr",
]
RADY = ["rada_faktura", "rada_vyuctovani"]
ANO_NE_POLE = ["platce_dph", "zaokrouhlit_hotovost"]


@dataclass
class NastaveniServisu:
    # ceny
    platce_dph: bool = True
    vychozi_dph: Decimal = Decimal("21")
    mena: str = "Kč"
    # údaje servisu (dodavatel na faktuře)
    nazev_servisu: str = ""
    ulice: str = ""
    mesto: str = ""
    psc: str = ""
    ico: str = ""
    dic: str = ""
    telefon: str = ""
    email: str = ""
    web: str = ""
    cislo_uctu: str = ""
    iban: str = ""
    vystavil: str = ""
    # doklady
    splatnost_dni: int = 14
    rada_faktura: str = "FV{RRRR}"
    rada_vyuctovani: str = "VY{RRRR}"
    cifry_cisla: int = 4
    zaokrouhlit_hotovost: bool = True
    text_pod_fakturou: str = ""
    # Registr silničních vozidel (dataovozidlech.cz) – načtení údajů vozidla podle VIN
    api_klic_registr: str = ""

    @property
    def udaje_vyplneny(self) -> bool:
        return bool(self.nazev_servisu and self.ico and (self.ulice or self.mesto))


def nacti(session: Session) -> NastaveniServisu:
    vysledek = NastaveniServisu()
    for f in fields(NastaveniServisu):
        zaznam = session.get(Nastaveni, f.name)
        if zaznam is None:
            continue
        typ = f.type if isinstance(f.type, str) else f.type.__name__
        if typ == "Decimal":
            setattr(vysledek, f.name, Decimal(zaznam.hodnota))
        elif typ == "bool":
            setattr(vysledek, f.name, zaznam.hodnota == "1")
        elif typ == "int":
            setattr(vysledek, f.name, int(zaznam.hodnota))
        else:
            setattr(vysledek, f.name, zaznam.hodnota)
    return vysledek


def _ano(hodnota) -> bool:
    return hodnota in (True, "1", "on", "true")


def uloz(session: Session, data: dict) -> NastaveniServisu:
    nove: dict[str, str] = {}
    if "vychozi_dph" in data:
        dph = desetinne_nebo_none(data["vychozi_dph"], "Výchozí sazba DPH")
        if dph is None or not 0 <= dph < 100:
            raise ChybaValidace("Výchozí sazba DPH musí být 0–99 %.")
        nove["vychozi_dph"] = str(dph)
    if "splatnost_dni" in data:
        dni = cislo_nebo_none(data["splatnost_dni"], "Splatnost")
        if dni is None or not 0 <= dni <= 365:
            raise ChybaValidace("Splatnost musí být 0–365 dní.")
        nove["splatnost_dni"] = str(dni)
    if "cifry_cisla" in data:
        cifry = cislo_nebo_none(data["cifry_cisla"], "Počet číslic")
        if cifry is None or not 1 <= cifry <= 8:
            raise ChybaValidace("Počet číslic dokladu musí být 1–8.")
        nove["cifry_cisla"] = str(cifry)
    for pole in ANO_NE_POLE:
        if pole in data:
            nove[pole] = "1" if _ano(data[pole]) else "0"
    for pole in TEXTOVA_POLE:
        if pole in data:
            nove[pole] = (data[pole] or "").strip()
    if "mena" in nove and not nove["mena"]:
        nove["mena"] = "Kč"
    for pole in RADY:
        if pole in nove and not nove[pole]:
            raise ChybaValidace("Vyplňte předponu číselné řady (např. FV{RRRR}).")
    predpony = [nove.get(p) or getattr(nacti(session), p) for p in RADY]
    if len(set(predpony)) != len(predpony):
        raise ChybaValidace("Faktury a vyúčtování musí mít různé předpony číselné řady.")
    if "ico" in nove:
        nove["ico"] = nove["ico"].replace(" ", "")
    if nove.get("iban"):
        nove["iban"] = nove["iban"].replace(" ", "").upper()

    for klic, hodnota in nove.items():
        zaznam = session.get(Nastaveni, klic) or Nastaveni(klic=klic)
        zaznam.hodnota = hodnota
        session.add(zaznam)
    session.commit()
    return nacti(session)
