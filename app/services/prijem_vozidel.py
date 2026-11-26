"""Příjem vozidel (#51, #216) – příjmy, které zapisuje Přijímací technik (OpenBot) přes MCP.

Příjmy jsou ve vlastní tabulce `PrijemVozidla`; drží se posledních `LIMIT` (starší se při zápisu smažou).
Fotky sem nepatří – zůstávají u technika. Záložka Příjem vozidel jen čte a páruje příjem s databází vozidel.

Technik posílá jen to, co přečetl (SPZ, VIN, km). Zbytek dělá Autoservis při uložení: opraví VIN (O/Q → 0, I → 1),
spojí příjem se stejnou SPZ / VIN z posledních 24 hodin, najde vozidlo v databázi (doplní z ní VIN), u nového auta
načte údaje z Registru vozidel a vrátí stav s dalším krokem pro technika.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from urllib.parse import quote

from sqlmodel import Session, col, select

from app.models import PrijemVozidla, Vozidlo, Zakazka
from app.services import ChybaValidace, NenalezenoError, cisty_text, nastaveni, registr_vozidel, vozidla

LIMIT = 30
SPOJIT_DO = timedelta(hours=24)  # příjem se stejnou SPZ / VIN mladší než tohle se doplní, nový se nezaloží

# stavy, které záložka ukáže u VIN (čeká se na doplnění)
STAVY_U_VIN = ("chybi_vin", "vin_neplatny", "vin_nenalezen", "registr_nedostupny")
# stav → (název pro záložku, další krok pro technika)
STAVY = {
    "hotovo": ("Hotovo", "Příjem je kompletní. Napiš uživateli, že je hotovo (a odkud je VIN)."),
    "nove_auto": ("Nové auto", "Vozidlo v databázi není, údaje jsou z registru. Napiš značku a model; vozidlo "
                               "založí uživatel v Autoservisu."),
    "chybi_vin": ("Chybí VIN", "Zeptej se uživatele na VIN nebo fotku technického průkazu a pošli VIN s id tohoto příjmu."),
    "vin_neplatny": ("Neplatný VIN", "Přečtený VIN neplatí (17 znaků, bez I, O, Q). Požádej o čitelnější fotku nebo VIN "
                                     "v textu. Nejisté znaky nehádej."),
    "vin_nenalezen": ("VIN není v registru", "VIN v registru není – nejspíš je přečtený špatně. Napiš, které znaky jsou "
                                             "nejisté (8/B, 5/S, 2/Z, 6/G, 0/D), a požádej o čitelnější fotku nebo VIN v textu."),
    "vin_nesedi": ("VIN nesedí", "VIN se liší od VIN vozidla v databázi. Oznam rozpor uživateli, nic dalšího nedělej."),
    "spz_nesedi": ("SPZ nesedí", "VIN patří vozidlu z databáze, které tam má jinou SPZ. Oznam rozpor uživateli "
                                 "(nová SPZ, nebo špatně přečtený VIN), nic dalšího nedělej."),
    "konflikt": ("Konflikt SPZ / VIN", "SPZ a VIN patří v databázi různým vozidlům. Oznam rozpor, nic dalšího nedělej."),
    "registr_nedostupny": ("Registr nedostupný", "Příjem je uložený bez údajů z registru; Autoservis to zkusí znovu "
                                                 "při dalším doplnění. Řekni to uživateli."),
}


def _text(hodnota) -> str | None:
    if hodnota is None:
        return None
    text = str(hodnota).strip()
    return text or None


def _ploche(data: dict, predpona: str = "") -> list[tuple[str, str]]:
    """Technické údaje jako dvojice (název, hodnota); vnořené slovníky jako „Motor.Vykon“."""
    vysledek = []
    for klic, hodnota in data.items():
        nazev = f"{predpona}{klic}"
        if isinstance(hodnota, dict):
            vysledek += _ploche(hodnota, nazev + ".")
        elif isinstance(hodnota, list):
            text = ", ".join(str(x) for x in hodnota if _text(x))
            vysledek.append((nazev, text))
        else:
            vysledek.append((nazev, _text(hodnota) or ""))
    return vysledek


def _nejiste(pole) -> set[str]:
    """`uncertain_fields` → množina názvů bez předpon („vehicle.vin“ i „vin“ → „vin“)."""
    vysledek = set()
    for nazev in pole if isinstance(pole, list) else []:
        if not isinstance(nazev, str):
            continue
        nazev = nazev.strip()
        for predpona in ("vehicle.", "technical_data."):
            if nazev.startswith(predpona):
                nazev = nazev[len(predpona):]
        vysledek.add(nazev.lower())
    return vysledek


@dataclass
class Navsteva:
    id: str
    created_at: datetime | None
    updated_at: datetime | None
    revision: str | None
    spz: str | None
    vin: str | None
    km: int | None
    technicke: list[tuple[str, str]] = field(default_factory=list)
    nejiste: set[str] = field(default_factory=set)
    registr: dict = field(default_factory=dict)  # technical_data tak, jak přišla (formát Registru vozidel)
    stav: str = ""
    zprava: str = ""

    @property
    def nazev_stavu(self) -> str:
        return STAVY.get(self.stav, ("", ""))[0]

    def _technicky(self, *nazvy: str) -> str | None:
        for nazev, hodnota in self.technicke:
            if nazev in nazvy and hodnota:
                return hodnota
        return None

    @property
    def znacka(self) -> str | None:
        return self._technicky("TovarniZnacka", "Znacka")

    @property
    def model(self) -> str | None:
        return self._technicky("ObchodniOznaceni", "Model", "Typ")

    @property
    def popis(self) -> str | None:
        return " ".join(x for x in (self.znacka, self.model) if x) or None

    def je_nejiste(self, nazev: str) -> bool:
        return nazev.lower() in self.nejiste


@dataclass
class Prijmy:
    version: str | None
    updated_at: datetime | None
    navstevy: list[Navsteva]


def _navsteva(radek: PrijemVozidla) -> Navsteva:
    try:
        technicke = json.loads(radek.technicke or "{}")
    except ValueError:
        technicke = {}
    try:
        nejiste = json.loads(radek.nejiste or "[]")
    except ValueError:
        nejiste = []
    technicke = technicke if isinstance(technicke, dict) else {}
    return Navsteva(
        id=radek.id, created_at=radek.vytvoreno, updated_at=radek.upraveno, revision=str(radek.revize),
        spz=radek.spz, vin=radek.vin, km=radek.km, technicke=_ploche(technicke), nejiste=_nejiste(nejiste),
        registr=technicke, stav=radek.stav or "", zprava=radek.zprava or "",
    )


def nacti(session: Session) -> Prijmy:
    """Příjmy od nejnověji založeného."""
    radky = list(session.exec(select(PrijemVozidla).order_by(col(PrijemVozidla.vytvoreno).desc())))
    navstevy = [_navsteva(r) for r in radky]
    posledni = max((r.upraveno for r in radky), default=None)
    return Prijmy(version=None, updated_at=posledni, navstevy=navstevy)


def najdi(session: Session, prijem_id: str) -> Navsteva | None:
    radek = session.get(PrijemVozidla, prijem_id)
    return _navsteva(radek) if radek else None


# ---------------------------------------------------------------- zápis přes MCP (#216)

POLE = ("id", "spz", "vin", "km", "nejiste")  # technické údaje doplňuje Autoservis z registru sám


def _km(hodnota) -> int | None:
    if hodnota in (None, ""):
        return None
    try:
        km = int(str(hodnota).replace(" ", ""))
    except ValueError:
        raise ChybaValidace("Stav tachometru (km) musí být celé číslo.", "km") from None
    if km < 0:
        raise ChybaValidace("Stav tachometru (km) nemůže být záporný.", "km")
    return km


@dataclass
class Vysledek:
    radek: PrijemVozidla
    stav: str
    zprava: str
    spojeno: bool = False            # doplněn existující příjem (stejná SPZ / VIN), nový nevznikl
    opravy_vin: list[str] = field(default_factory=list)
    vin_z_databaze: bool = False

    @property
    def dalsi_krok(self) -> str:
        return STAVY[self.stav][1]


def _k_doplneni(session: Session, spz: str | None, vin: str | None) -> PrijemVozidla | None:
    """Nedávný příjem stejného auta (mladší než SPOJIT_DO). Jiná SPZ je vždy jiné auto:
    se SPZ se hledá podle SPZ, podle VIN jen příjem bez SPZ; bez SPZ podle VIN."""
    nedavne = select(PrijemVozidla).where(PrijemVozidla.vytvoreno >= datetime.now() - SPOJIT_DO) \
        .order_by(col(PrijemVozidla.vytvoreno).desc())
    if spz:
        radek = session.exec(nedavne.where(PrijemVozidla.spz == spz)).first()
        if radek or not vin:
            return radek
        return session.exec(nedavne.where(PrijemVozidla.vin == vin).where(col(PrijemVozidla.spz).is_(None))).first()
    return session.exec(nedavne.where(PrijemVozidla.vin == vin)).first() if vin else None


def uloz(session: Session, data: dict | None, nacti_registr=None) -> Vysledek:
    """Uloží, co technik přečetl, a vyhodnotí to (viz popis modulu).

    Bez `id`: doplní nedávný příjem stejného auta, jinak založí nový. S `id`: doplní ten příjem (jen zadaná pole);
    jiná SPZ než u příjmu = jiné auto → odmítne. Pak se smažou příjmy nad limit."""
    data = dict(data or {})
    nezname = sorted(k for k in data if k not in POLE)
    if nezname:
        raise ChybaValidace(f"Neznámá pole: {', '.join(nezname)}. Povolená: {', '.join(POLE)}.")
    prijem_id = cisty_text(data.pop("id", None))
    spz = vozidla.normalizuj_spz(str(data["spz"] or "")) or None if "spz" in data else None
    vin, opravy = vozidla.oprav_vin(str(data["vin"] or "")) if "vin" in data else (None, [])
    vin_neplatny = vin if vin and not vozidla.je_vin(vin) else None
    if vin_neplatny:
        vin = None  # neplatný VIN se neukládá, příjem (SPZ, km) ano
    spojeno = False
    if prijem_id:
        radek = session.get(PrijemVozidla, prijem_id)
        if radek is None:
            raise NenalezenoError(f"Příjem {prijem_id} neexistuje (mezitím smazán?). Pošli údaje bez id jako nový příjem.")
        if spz and radek.spz and spz != radek.spz:
            raise ChybaValidace(f"Příjem {prijem_id} má SPZ {radek.spz}, ne {spz} – jiná SPZ je jiné auto. "
                                "Pošli údaje bez id.", "spz")
    else:
        radek = _k_doplneni(session, spz, vin)
        spojeno = radek is not None
        if radek is None:
            if not spz and not vin:
                raise ChybaValidace(f"VIN {vin_neplatny} není platný (17 znaků, bez I, O, Q) a SPZ chybí – "
                                    "příjem nejde založit." if vin_neplatny else "Příjem potřebuje SPZ nebo VIN.", "spz")
            radek = PrijemVozidla(id=str(uuid.uuid4()), revize=0)
    if spz:
        radek.spz = spz
    elif "spz" in data and prijem_id:
        radek.spz = None
    if vin and vin != radek.vin:
        radek.vin = vin
        radek.technicke = "{}"  # údaje z registru patřily k jinému VIN
    if "km" in data:
        radek.km = _km(data["km"])
    if "nejiste" in data:
        nejiste = data["nejiste"] or []
        if not isinstance(nejiste, list) or not all(isinstance(x, str) for x in nejiste):
            raise ChybaValidace("nejiste musí být seznam názvů polí, např. [\"vin\", \"km\"].")
        radek.nejiste = json.dumps(nejiste, ensure_ascii=False)
    if not radek.spz and not radek.vin:
        raise ChybaValidace("Příjem potřebuje SPZ nebo VIN.", "spz")
    stav, zprava, z_databaze = _vyhodnot(session, radek, nacti_registr or registr_vozidel.nacti)
    if vin_neplatny:
        stav, zprava = "vin_neplatny", f"VIN {vin_neplatny} není platný: musí mít 17 znaků a nesmí obsahovat I, O ani Q."
    radek.stav, radek.zprava = stav, zprava
    radek.revize += 1
    radek.upraveno = datetime.now()
    session.add(radek)
    session.commit()
    _orizni(session)
    session.refresh(radek)
    return Vysledek(radek, stav, zprava, spojeno, opravy, z_databaze)


def _vyhodnot(session: Session, radek: PrijemVozidla, nacti_registr) -> tuple[str, str, bool]:
    """(stav, zpráva, VIN doplněn z databáze) – porovná příjem s databází, u nového auta načte registr."""
    shoda = sparuj(session, _navsteva(radek))
    if shoda.stav == "konflikt":
        return "konflikt", shoda.upozorneni or "", False
    if shoda.stav == "v_databazi":
        vuz = shoda.vozidlo
        vin_db = vozidla.normalizuj_vin(vuz.vin)
        if not radek.vin and vin_db and vozidla.je_vin(vin_db):
            radek.vin = vin_db
            return "hotovo", f"Vozidlo je v databázi ({vuz.spz}), VIN doplněn z databáze.", True
        if shoda.podle_vin and not shoda.podle_spz and radek.spz and vozidla.normalizuj_spz(vuz.spz) != radek.spz:
            return "spz_nesedi", shoda.upozorneni or f"V databázi má vozidlo SPZ {vuz.spz}.", False
        if radek.vin and vin_db and radek.vin != vin_db:
            return "vin_nesedi", shoda.upozorneni or f"V databázi má vozidlo VIN {vuz.vin}.", False
        if not radek.vin:
            return "chybi_vin", f"Vozidlo je v databázi ({vuz.spz}), ale nemá VIN.", False
        return "hotovo", f"Vozidlo je v databázi ({vuz.spz}).", False
    if not radek.vin:
        return "chybi_vin", "Vozidlo podle SPZ v databázi není a VIN chybí.", False
    if radek.technicke not in ("", "{}"):
        return "nove_auto", "Vozidlo v databázi není, údaje z registru jsou načtené.", False
    try:
        data = nacti_registr(nastaveni.nacti(session).api_klic_registr, vin=radek.vin)
    except registr_vozidel.ChybaRegistru as e:
        text = str(e)
        if "nenalezeno" in text or "víc vozidel" in text:
            return "vin_nenalezen", f"VIN {radek.vin} v registru vozidel není.", False
        return "registr_nedostupny", text, False
    radek.technicke = json.dumps(data, ensure_ascii=False)
    pole = registr_vozidel.na_pole_vozidla(data)
    popis = " ".join(x for x in (pole.get("znacka"), pole.get("model")) if x)
    return "nove_auto", f"Vozidlo v databázi není, z registru: {popis or 'údaje načtené'}.", False


def _orizni(session: Session) -> int:
    """Smaže příjmy nad limit (nejstarší podle založení). Vrací počet smazaných."""
    stare = list(session.exec(select(PrijemVozidla).order_by(col(PrijemVozidla.vytvoreno).desc()).offset(LIMIT)))
    for radek in stare:
        session.delete(radek)
    if stare:
        session.commit()
    return len(stare)


def smaz(session: Session, prijem_id: str) -> None:
    radek = session.get(PrijemVozidla, prijem_id)
    if radek is None:
        raise NenalezenoError(f"Příjem {prijem_id} neexistuje.")
    session.delete(radek)
    session.commit()


# ---------------------------------------------------------------- návštěva × naše databáze vozidel

@dataclass
class Shoda:
    """Je vozidlo z příjmu v databázi?

    stav: „v_databazi“ (našlo se podle SPZ nebo VIN), „neni“, „konflikt“ (SPZ patří jednomu vozidlu
    a VIN jinému – chyba v databázi nebo v příjmu, nic se nenabízí automaticky).
    `upozorneni` = nesoulad u nalezeného vozidla (jiný VIN / jiná SPZ v databázi), akce zůstává.
    """
    navsteva: Navsteva
    stav: str
    vozidlo: Vozidlo | None = None
    podle_spz: Vozidlo | None = None
    podle_vin: Vozidlo | None = None
    otevrena: Zakazka | None = None
    upozorneni: str | None = None

    @property
    def akce(self) -> tuple[str, str, bool] | None:
        """(text tlačítka, adresa, otevřít v okně) – hlavní akce řádku; konflikt = žádná."""
        if self.stav == "neni":
            return "Založit vozidlo", f"/vozidla/nove?prijem={quote(self.navsteva.id, safe='')}", True
        if self.stav != "v_databazi":
            return None
        if self.otevrena:
            return "Otevřít zakázku", f"/zakazky/{self.otevrena.id}", False
        km = f"&tachometr={self.navsteva.km}" if self.navsteva.km is not None else ""
        return "Nová zakázka", f"/zakazky/nova?vozidlo_id={self.vozidlo.id}{km}", True


def _oznaceni(vozidlo: Vozidlo) -> str:
    return " ".join(x for x in (vozidlo.spz, vozidlo.popis if (vozidlo.znacka or vozidlo.model) else "") if x)


def sparuj(session: Session, navsteva: Navsteva) -> Shoda:
    """Najde vozidlo návštěvy v databázi podle SPZ i VIN a zkontroluje, že obojí ukazuje na stejné vozidlo."""
    spz = vozidla.normalizuj_spz(navsteva.spz)
    vin = vozidla.normalizuj_vin(navsteva.vin)
    podle_spz = vozidla.najdi_podle_spz(session, spz) if spz else None
    podle_vin = vozidla.najdi_podle_vin(session, vin) if vin else None
    if podle_spz and podle_vin and podle_spz.id != podle_vin.id:
        return Shoda(navsteva, "konflikt", podle_spz=podle_spz, podle_vin=podle_vin, upozorneni=(
            f"SPZ patří v databázi vozidlu {_oznaceni(podle_spz)}, VIN vozidlu {_oznaceni(podle_vin)}. "
            "Ověřte údaje a opravte záznam v databázi."))
    vozidlo = podle_spz or podle_vin
    if vozidlo is None:
        return Shoda(navsteva, "neni")
    upozorneni = None
    if not podle_vin and vin and vozidlo.vin and vozidla.normalizuj_vin(vozidlo.vin) != vin:
        upozorneni = f"Nalezeno podle SPZ, ale v databázi má vozidlo jiný VIN: {vozidlo.vin}."
    elif not podle_spz and spz and vozidlo.spz != spz:
        upozorneni = f"Nalezeno podle VIN, ale v databázi má vozidlo jinou SPZ: {vozidlo.spz}."
    otevrena = next((z for z in vozidla.historie(session, vozidlo.id) if z.je_otevrena), None)
    return Shoda(navsteva, "v_databazi", vozidlo=vozidlo, podle_spz=podle_spz, podle_vin=podle_vin,
                 otevrena=otevrena, upozorneni=upozorneni)
