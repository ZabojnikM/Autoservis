"""Nastavení servisu (DPH, údaje servisu, číselné řady…)."""
from dataclasses import dataclass, fields
from decimal import Decimal

from sqlmodel import Session

from app.models import Nastaveni
from app.services import ChybaValidace, cislo_nebo_none, desetinne_nebo_none

TEXTOVA_POLE = [
    "mena", "nazev_servisu", "ulice", "mesto", "psc", "ico", "dic", "telefon", "email", "web",
    "cislo_uctu", "iban", "ucet_vyuctovani", "vystavil", "rada_faktura", "rada_vyuctovani", "text_pod_fakturou",
    "api_klic_registr", "nazev_v_liste",
]
RADY = ["rada_faktura", "rada_vyuctovani"]
ANO_NE_POLE = ["platce_dph", "zaokrouhlit_hotovost", "sprava_dat", "statistiky"]


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
    # účet jen pro QR platbu na vyúčtování (#55) – může být jiný než účet pro faktury; číslo účtu nebo IBAN
    ucet_vyuctovani: str = ""
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
    # horní lišta aplikace: název firmy uprostřed (prázdné = název servisu) a logo (data URI, uložené v DB)
    nazev_v_liste: str = ""
    logo: str = ""
    # záložka Správa dat (#132) – hromadné úpravy skladu a databáze, běžně skrytá
    sprava_dat: bool = False
    # záložka Statistiky (#160) – výkon servisu po měsících a za rok, běžně skrytá
    statistiky: bool = False

    @property
    def nazev_do_listy(self) -> str:
        return self.nazev_v_liste or self.nazev_servisu or "Autoservis"

    @property
    def udaje_vyplneny(self) -> bool:
        return not self.chybejici_udaje

    @property
    def chybejici_udaje(self) -> list[str]:
        """Pole (název pole formuláře, popisek) údajů servisu, bez kterých nejde vystavit fakturu.
        Plátce DPH musí mít na daňovém dokladu i DIČ."""
        chybi = []
        if not self.nazev_servisu:
            chybi.append(("nazev_servisu", "název"))
        if not self.ico:
            chybi.append(("ico", "IČO"))
        if not (self.ulice or self.mesto):
            chybi.append(("ulice", "adresa"))
        if self.platce_dph and not self.dic:
            chybi.append(("dic", "DIČ (nebo zrušte „plátce DPH“, pokud nejste plátce)"))
        return chybi

    @property
    def chybejici_udaje_text(self) -> str:
        return ", ".join(popisek for _, popisek in self.chybejici_udaje)


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
    if nove.get("ucet_vyuctovani"):
        from app.services.faktury import iban_z_uctu
        if not iban_z_uctu(nove["ucet_vyuctovani"]):
            raise ChybaValidace("Účet pro QR platbu na vyúčtování: zadejte číslo účtu (např. 123456789/0800) "
                                "nebo IBAN (CZ…).", "ucet_vyuctovani")

    for klic, hodnota in nove.items():
        zaznam = session.get(Nastaveni, klic) or Nastaveni(klic=klic)
        zaznam.hodnota = hodnota
        session.add(zaznam)
    session.commit()
    return nacti(session)


LOGO_TYPY = {"image/png": "png", "image/jpeg": "jpg", "image/svg+xml": "svg", "image/webp": "webp"}
LOGO_MAX = 500 * 1024


def uloz_logo(session: Session, obsah: bytes | None, typ: str | None) -> NastaveniServisu:
    """Logo do horní lišty – uloží se do nastavení jako data URI (zálohuje se s databází).
    Prázdný `obsah` logo smaže."""
    import base64
    if not obsah:
        hodnota = ""
    else:
        if typ not in LOGO_TYPY:
            raise ChybaValidace("Logo musí být obrázek PNG, JPG, SVG nebo WebP.", "logo_soubor")
        if len(obsah) > LOGO_MAX:
            raise ChybaValidace("Logo je moc velké – nejvýš 500 kB.", "logo_soubor")
        hodnota = f"data:{typ};base64," + base64.b64encode(obsah).decode("ascii")
    zaznam = session.get(Nastaveni, "logo") or Nastaveni(klic="logo")
    zaznam.hodnota = hodnota
    session.add(zaznam)
    session.commit()
    return nacti(session)
