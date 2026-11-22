"""Import dat ze starého systému (export JSON z `nastroje/stary_system_export.py`).

Import je opakovatelný: každý převedený záznam se zapíše do `ImportMapa` a při dalším běhu se přeskočí.
Vše proběhne v jedné transakci – při chybě se neuloží nic.

Spuštění (nad kopií databáze):

    .venv\\Scripts\\python -m app.importers.stary_system data\\stary-system-export\\vzorek.json --db data\\autoservis-import.db --z-kopie data\\autoservis.db
"""
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation

from sqlmodel import Session, select

from app.models import (
    Faktura, FormaUhrady, ImportMapa, PolozkaCeniku, PolozkaFaktury, PolozkaZakazky, StavZakazky,
    TypDokladu, TypPolozky, Uhrada, Vozidlo, Zakazka, Zakaznik, zaokrouhli,
)
from app.services import polozky as polozky_sluzba
from app.services.faktury import variabilni_symbol
from app.services.vozidla import normalizuj_spz, normalizuj_vin

ZDROJ = "stary_system"
POZNAMKA_IMPORTU = "Importováno ze starého systému"

PALIVA = [  # (začátek normalizovaného textu, náš název) – pořadí je důležité
    ("EL+BA", "hybrid"), ("BA+LPG", "LPG"), ("LPG", "LPG"), ("CNG", "CNG"),
    ("BA", "benzín"), ("NM", "nafta"), ("NA", "nafta"), ("N", "nafta"), ("EL", "elektro"),
]


@dataclass
class Protokol:
    pridano: dict = field(default_factory=dict)
    preskoceno: dict = field(default_factory=dict)
    upozorneni: list = field(default_factory=list)

    def pridej(self, tabulka: str):
        self.pridano[tabulka] = self.pridano.get(tabulka, 0) + 1

    def preskoc(self, tabulka: str):
        self.preskoceno[tabulka] = self.preskoceno.get(tabulka, 0) + 1

    def varuj(self, text: str):
        if text not in self.upozorneni:
            self.upozorneni.append(text)

    def jako_markdown(self, meta: dict | None = None) -> str:
        radky = ["# Protokol importu ze starého systému", ""]
        if meta:
            radky += [f"- Zdroj: `{meta.get('zdroj')}`, export {meta.get('exportovano')}",
                      f"- Import: {datetime.now():%d.%m.%Y %H:%M}", ""]
        radky += ["| Tabulka | Přidáno | Již importováno (přeskočeno) |", "|---|---:|---:|"]
        for t in sorted(set(self.pridano) | set(self.preskoceno)):
            radky.append(f"| {t} | {self.pridano.get(t, 0)} | {self.preskoceno.get(t, 0)} |")
        radky += ["", f"## Upozornění ({len(self.upozorneni)})", ""]
        radky += [f"- {u}" for u in self.upozorneni] or ["- žádná"]
        return "\n".join(radky) + "\n"


# ---------------------------------------------------------------- převody hodnot


def _text(hodnota) -> str | None:
    if hodnota is None:
        return None
    hodnota = str(hodnota).strip()
    return hodnota or None


def _cislo(hodnota, vychozi="0") -> Decimal:
    """ODBC vrací '450.0000' – zbytečné nuly zkrátíme (450.0000 → 450.00, 2.0000 → 2), přesnost zůstává."""
    try:
        cislo = Decimal(_text(hodnota) or vychozi)
    except InvalidOperation:
        cislo = Decimal(vychozi)
    for presnost in (Decimal("1"), Decimal("0.01")):
        if cislo == cislo.quantize(presnost):
            return cislo.quantize(presnost)
    return cislo


def _id(hodnota) -> str | None:
    """Starý systém používá 0 i NULL jako „bez vazby“."""
    hodnota = _text(hodnota)
    return None if hodnota in (None, "0") else hodnota


def _datum(hodnota) -> date | None:
    hodnota = _text(hodnota)
    return date.fromisoformat(hodnota[:10]) if hodnota else None


def _cas(hodnota) -> time:
    hodnota = _text(hodnota)
    try:
        return time.fromisoformat(hodnota[:8]) if hodnota else time(0, 0)
    except ValueError:
        return time(0, 0)


def _datum_cas(d, c) -> datetime | None:
    den = _datum(d)
    return datetime.combine(den, _cas(c)) if den else None


def rok_vyroby(hodnota) -> int | None:
    """'2008', '20080305' → 2008; nejasné zápisy ('97', '4,2005', '20007') → None."""
    hodnota = _text(hodnota)
    if not hodnota or not re.fullmatch(r"\d{4}|\d{8}", hodnota):
        return None
    rok = int(hodnota[:4])
    return rok if 1900 <= rok <= date.today().year + 1 else None


def palivo(hodnota) -> str | None:
    hodnota = _text(hodnota)
    if not hodnota:
        return None
    zkratka = re.sub(r"\s", "", hodnota.upper())
    for zacatek, nazev in PALIVA:
        if zkratka.startswith(zacatek):
            return nazev
    return hodnota


def znacka_model(typ_auta) -> tuple[str | None, str | None]:
    """'Škoda Octavia 1.9 TDI' → ('Škoda', 'Octavia 1.9 TDI')."""
    typ_auta = _text(typ_auta)
    if not typ_auta:
        return None, None
    casti = typ_auta.split(maxsplit=1)
    return casti[0], (casti[1] if len(casti) > 1 else None)


def _jmeno(r: dict) -> str | None:
    """MENO1–3 spojené; zástupné jméno bez písmen a číslic (např. '_') = anonymní odběratel → None."""
    casti = [c for c in (_text(r.get(k)) for k in ("MENO1", "MENO2", "MENO3")) if c and re.search(r"\w", c.replace("_", ""))]
    return ", ".join(casti) or None


def _spoj(*casti, oddelovac="\n") -> str | None:
    vysledek = oddelovac.join(c for c in (_text(x) for x in casti) if c)
    return vysledek or None


# ---------------------------------------------------------------- importér


class ImporterStarySystem:
    def __init__(self, session: Session, data: dict):
        self.s = session
        self.data = data
        self.p = Protokol()
        self.partneri = {r["ID"]: r for r in data.get("PARTNERI", [])}
        self.karty = {r["ID"]: r for r in data.get("SKLKARTY", [])}

    # --- mapa původních ID
    def _nove_id(self, tabulka: str, puvodni_id) -> int | None:
        if puvodni_id is None:
            return None
        return self.s.exec(select(ImportMapa.nove_id).where(
            ImportMapa.zdroj == ZDROJ, ImportMapa.tabulka == tabulka,
            ImportMapa.puvodni_id == str(puvodni_id))).first()

    def _zapis_mapu(self, tabulka: str, puvodni_id, objekt) -> None:
        self.s.add(objekt)
        self.s.flush()
        self.s.add(ImportMapa(zdroj=ZDROJ, tabulka=tabulka, puvodni_id=str(puvodni_id), nove_id=objekt.id))
        self.p.pridej(tabulka)

    # --- zákazníci
    def zakaznik(self, partner_id, zaloha: dict | None = None) -> int | None:
        """`zaloha` = zakázka/doklad s kopií údajů odběratele – použije se, když partner ve starém systému už neexistuje."""
        partner_id = _id(partner_id)
        if partner_id is None:
            return None
        nove = self._nove_id("PARTNERI", partner_id)
        if nove:
            return nove
        r = self.partneri.get(partner_id)
        if r is not None and _jmeno(r) is None or r is None and zaloha and _jmeno(zaloha) is None:
            self.p.varuj(f"Partner {partner_id} je bez jména (anonymní odběratel) – zakázka/doklad bez zákazníka.")
            return None
        if r is None:
            if not zaloha or not _text(zaloha.get("MENO1")):
                self.p.varuj(f"Partner {partner_id} ve starém systému neexistuje – zákazník nepřiřazen.")
                return None
            r = zaloha
            self.p.varuj(f"Partner {partner_id} byl ve starém systému smazán – zákazník „{_text(r.get('MENO1'))}“ "
                         "založen z údajů na zakázce/dokladu.")
        nazev = _jmeno(r)
        ico, telefon = _text(r.get("ICO")), _text(r.get("TELEFON"))
        existujici = None
        if ico:
            existujici = self.s.exec(select(Zakaznik).where(Zakaznik.ico == ico)).first()
        if existujici is None and telefon:
            existujici = self.s.exec(select(Zakaznik).where(Zakaznik.nazev == nazev, Zakaznik.telefon == telefon)).first()
        if existujici is not None:
            self.s.add(ImportMapa(zdroj=ZDROJ, tabulka="PARTNERI", puvodni_id=partner_id, nove_id=existujici.id))
            self.p.varuj(f"Zákazník „{nazev}“ už v aplikaci byl – spojen s existujícím (id {existujici.id}).")
            self.p.preskoc("PARTNERI")
            return existujici.id
        ic_dph, dic = _text(r.get("ICDPH")), _text(r.get("DIC"))
        zakaznik = Zakaznik(
            nazev=nazev, telefon=telefon, email=_text(r.get("EMAIL")), ulice=_text(r.get("ULICA")),
            mesto=_text(r.get("MESTO")), psc=_text(r.get("PSC")), ico=ico, dic=dic or ic_dph,
            poznamka=_spoj(r.get("POZNAMKA"), f"IČ DPH: {ic_dph}" if ic_dph and dic else None, POZNAMKA_IMPORTU),
        )
        self._zapis_mapu("PARTNERI", partner_id, zakaznik)
        return zakaznik.id

    # --- vozidla
    def _volna_spz(self, spz: str, puvodni_id: str) -> str:
        if not self.s.exec(select(Vozidlo.id).where(Vozidlo.spz == spz)).first():
            return spz
        nova = f"{spz}-SS{puvodni_id}"
        self.p.varuj(f"SPZ {spz} už patří jinému vozidlu – vozidlo ze starého systému {puvodni_id} dostalo SPZ {nova}.")
        return nova

    def _vin_volny(self, vin: str | None, puvodni_id: str) -> str | None:
        if vin and self.s.exec(select(Vozidlo.id).where(Vozidlo.vin == vin)).first():
            self.p.varuj(f"VIN {vin} už má jiné vozidlo – u vozidla ze starého systému {puvodni_id} přesunut do poznámky.")
            return None
        return vin

    @staticmethod
    def _udaje_vozidla(r: dict) -> dict:
        """Pole vozidla, která starý systém vede samostatně (motor, olej, STK). Termín EK se nepřebírá (nepoužívá se)."""
        return {"kod_motoru": _text(r.get("KODTYPUMOT")), "objem": _text(r.get("OBJEMMOT")),
                "vykon": _text(r.get("VYKONMOT")), "cislo_motoru": _text(r.get("CMOTORA")),
                "olej": _text(r.get("OLEJ")), "termin_stk": _datum(r.get("TERMINSTK"))}

    def _dopln_rozepsana_pole(self, v: Vozidlo, r: dict) -> bool:
        """U vozidla z dřívějšího importu doplní nová samostatná pole a uklidí jejich text z motoru a poznámky."""
        zmena = False
        for pole, hodnota in self._udaje_vozidla(r).items():
            if hodnota is not None and getattr(v, pole) in (None, ""):
                setattr(v, pole, hodnota)
                zmena = True
        if zmena:
            if v.motor and v.motor == self._stary_popis_motoru(r):
                v.motor = None
            if v.poznamka:
                radky = [x for x in v.poznamka.splitlines()
                         if not x.startswith(("STK do ", "EK do ", "Č. motoru: "))]
                v.poznamka = "\n".join(radky) or None
            self.s.add(v)
            self.p.pridej("VOZIDLA_DOPLNENA_POLE")
        return zmena

    @staticmethod
    def _stary_popis_motoru(r: dict) -> str | None:
        """Text, který do pole motor ukládala první verze importu."""
        objem, vykon = _text(r.get("OBJEMMOT")), _text(r.get("VYKONMOT"))
        if objem and objem.isdigit():
            objem += " ccm"
        return _spoj(r.get("KODTYPUMOT"), objem, f"výkon {vykon}" if vykon else None, oddelovac=", ")

    def vozidlo(self, r: dict) -> int:
        puvodni_id = r["ID"]
        nove = self._nove_id("VOZIDLA", puvodni_id)
        if nove:
            existujici = self.s.get(Vozidlo, nove)
            if existujici is not None:
                self._dopln_rozepsana_pole(existujici, r)
            return nove
        spz = normalizuj_spz(r["SPZ_P"] or r["SPZ"])
        vin = normalizuj_vin(r["CKAROSERIE"])
        zakaznik_id = self.zakaznik(r["ID_ODBER"])
        if spz:
            existujici = self.s.exec(select(Vozidlo).where(Vozidlo.spz == spz)).first()
            if existujici is not None and (not vin or not existujici.vin or existujici.vin == vin):
                # stejné auto už v aplikaci je – jen doplníme prázdné údaje
                self._dopln_vozidlo(existujici, r, vin, zakaznik_id)
                self.s.add(ImportMapa(zdroj=ZDROJ, tabulka="VOZIDLA", puvodni_id=puvodni_id, nove_id=existujici.id))
                self.p.varuj(f"Vozidlo {spz} už v aplikaci bylo – spojeno, doplněny jen prázdné údaje.")
                self.p.preskoc("VOZIDLA")
                return existujici.id
        else:
            spz = f"BEZSPZ-SS{puvodni_id}"
            self.p.varuj(f"Vozidlo ze starého systému {puvodni_id} nemá SPZ – uloženo jako {spz}.")
        spz = self._volna_spz(spz, puvodni_id)
        vin_ulozeny = self._vin_volny(vin, puvodni_id)
        znacka, model = znacka_model(r["TYPAUTA"])
        rok = rok_vyroby(r["VYROBENE"])
        vozidlo = Vozidlo(
            spz=spz, vin=vin_ulozeny, znacka=znacka, model=model, rok_vyroby=rok,
            palivo=palivo(r["PALIVODRUH"]), barva=_text(r["FARBA"]), zakaznik_id=zakaznik_id,
            poznamka=self._poznamka_vozidla(r, vin if vin != vin_ulozeny else None, rok),
            **self._udaje_vozidla(r),
        )
        self._zapis_mapu("VOZIDLA", puvodni_id, vozidlo)
        return vozidlo.id

    def _poznamka_vozidla(self, r: dict, presunuty_vin: str | None, rok: int | None) -> str | None:
        vyrobeno = _text(r.get("VYROBENE"))
        return _spoj(
            r.get("POZNAMKA"), r.get("POPIS"),
            f"Vyrobeno (starý systém): {vyrobeno}" if vyrobeno and rok is None else None,
            f"VIN (duplicitní): {presunuty_vin}" if presunuty_vin else None,
            POZNAMKA_IMPORTU,
        )

    def _dopln_vozidlo(self, v: Vozidlo, r: dict, vin, zakaznik_id) -> None:
        znacka, model = znacka_model(r["TYPAUTA"])
        hodnoty = {"vin": self._vin_volny(vin, r["ID"]) if not v.vin else None, "znacka": znacka, "model": model,
                   "rok_vyroby": rok_vyroby(r["VYROBENE"]), "palivo": palivo(r["PALIVODRUH"]),
                   "barva": _text(r["FARBA"]), "zakaznik_id": zakaznik_id} | self._udaje_vozidla(r)
        for pole, hodnota in hodnoty.items():
            if hodnota is not None and getattr(v, pole) in (None, ""):
                setattr(v, pole, hodnota)
        self.s.add(v)

    def vozidlo_ze_zakazky(self, z: dict) -> int:
        """Zakázka bez vazby na vozidlo – použijeme údaje uložené přímo na zakázce."""
        self.zakaznik(z["ID_ODBER"], z)  # aby se smazaný partner založil z údajů zakázky
        spz = normalizuj_spz(z["SPZ_P"] or z["SPZ"])
        if spz:
            existujici = self.s.exec(select(Vozidlo.id).where(Vozidlo.spz == spz)).first()
            if existujici:
                return existujici
        r = {"ID": f"Z{z['ID']}", "SPZ": spz, "SPZ_P": spz, "CKAROSERIE": z["CKAROSERIE"], "TYPAUTA": z["TYPAUTA"],
             "VYROBENE": z["VYROBENE"], "ID_ODBER": z["ID_ODBER"], "PALIVODRUH": z.get("PALIVO"), "OBJEMMOT": None,
             "VYKONMOT": None, "KODTYPUMOT": None, "FARBA": None}
        self.p.varuj(f"Zakázka {z['OZNACENIE']} neměla ve starém systému vozidlo – vozidlo založeno z údajů zakázky.")
        return self.vozidlo(r)

    # --- ceník
    def _volny_kod(self, kod: str | None, zaloha: str | None) -> str | None:
        for kandidat in (kod, zaloha):
            if kandidat and not self.s.exec(select(PolozkaCeniku.id).where(PolozkaCeniku.kod == kandidat)).first():
                return kandidat
        if kod or zaloha:
            self.p.varuj(f"Kód {kod or zaloha} už v ceníku je – položka uložena bez kódu.")
        return None

    def karta(self, karta_id) -> PolozkaCeniku | None:
        karta_id = _id(karta_id)
        if karta_id is None:
            return None
        nove = self._nove_id("SKLKARTY", karta_id)
        if nove:
            return self.s.get(PolozkaCeniku, nove)
        r = self.karty.get(karta_id)
        if r is None:
            self.p.varuj(f"Skladová karta {karta_id} chybí v exportu.")
            return None
        stav = _cislo(r["MNOZSTVO"]).normalize()
        polozka = PolozkaCeniku(
            kod=self._volny_kod(_text(r["CISLO"]), _text(r["OZNACENIE"])), nazev=_text(r["NAZOV"]) or "(bez názvu)",
            typ=TypPolozky.MATERIAL, jednotka=_text(r["JEDNOTKA"]) or "ks", cena=_cislo(r["CENAPR1"]),
            sazba_dph=_cislo(r["SADZBADPH"], "21"), aktivni=_text(r["VYRADENY"]) != "1",
            nakupni_cena=_cislo(r["CENA"]) if _text(r["CENA"]) else None,
            poznamka=_spoj(f"Skladová karta ze starého systému {_text(r['OZNACENIE'])}",
                           f"Skladová cena {_cislo(r['CENA']):.2f}, stav ve starém systému {stav} {_text(r['JEDNOTKA']) or ''}".strip(),
                           POZNAMKA_IMPORTU),
        )
        self._zapis_mapu("SKLKARTY", karta_id, polozka)
        return polozka

    def predvolene_prace(self) -> dict[str, PolozkaCeniku]:
        vysledek = {}
        for r in self.data.get("PRACE", []):
            nove = self._nove_id("PRACE", r["ID"])
            if nove:
                self.p.preskoc("PRACE")
                polozka = self.s.get(PolozkaCeniku, nove)
            else:
                polozka = PolozkaCeniku(
                    kod=self._volny_kod(_text(r["KOD"]), None), nazev=_text(r["NAZOV"]) or "(bez názvu)",
                    typ=TypPolozky.PRACE, jednotka=_text(r["JEDNOTKA"]) or "ks", cena=_cislo(r["JEDCENA"]),
                    sazba_dph=_cislo(r["SADZBADPH"], "21"), poznamka=POZNAMKA_IMPORTU,
                )
                self._zapis_mapu("PRACE", r["ID"], polozka)
            if _text(r["KOD"]):
                vysledek[r["KOD"]] = polozka
        return vysledek

    # --- řádky (zakázka i doklad)
    def _radky(self, klic: str, hodnota: str, prace_ceniku: dict) -> list[dict]:
        radky = []
        for r in self.data.get("VYKPRACE", []):
            if r[klic] == hodnota:
                cenik = prace_ceniku.get(r["KOD"])
                radky.append({"typ": TypPolozky.PRACE, "kod": _text(r["KOD"]), "nazev": _text(r["NAZOV"]) or "Práce",
                              "jednotka": _text(r["JEDNOTKA"]) or "ks", "mnozstvi": _cislo(r["MNOZSTVO"], "1"),
                              "cena": self._po_sleve(r["JEDCENA"], r["ZLAVA"]), "sazba_dph": _cislo(r["SADZBADPH"], "21"),
                              "cenik_id": cenik.id if cenik else None, "_poradi": int(r["ID"])})
        for r in self.data.get("POHYBY", []):
            if r[klic] == hodnota:
                karta = self.karta(r["ID_SKLKARTY"])
                zdroj = self.karty.get(_id(r["ID_SKLKARTY"]) or "", {})
                radky.append({"typ": TypPolozky.MATERIAL, "kod": karta.kod if karta else None,
                              "nazev": _text(r["POPIS"]) or _text(zdroj.get("NAZOV")) or "Materiál",
                              "jednotka": _text(zdroj.get("JEDNOTKA")) or "ks", "mnozstvi": _cislo(r["MNOZSTVO"], "1"),
                              "cena": self._po_sleve(r["FAKCENA"], r["ZLAVA"]), "sazba_dph": _cislo(r["SADZBADPH"], "21"),
                              "cenik_id": karta.id if karta else None, "_poradi": int(r["ID"])})
        # nejdřív práce, pak materiál, uvnitř v pořadí zadání ve starém systému
        return sorted(radky, key=lambda r: (r["typ"] != TypPolozky.PRACE, r["_poradi"]))

    @staticmethod
    def _po_sleve(cena, sleva) -> Decimal:
        cena, sleva = _cislo(cena), _cislo(sleva)
        return zaokrouhli(cena * (100 - sleva) / 100) if sleva else cena

    # --- zakázky
    def zakazky(self, prace_ceniku: dict) -> None:
        vozidla = {r["ID"]: r for r in self.data.get("VOZIDLA", [])}
        for z in sorted(self.data.get("ZAKAZKY", []), key=lambda r: int(r["ID"])):
            if self._nove_id("ZAKAZKY", z["ID"]):
                self.p.preskoc("ZAKAZKY")
                if _id(z["ID_VOZIDLA"]) in vozidla:  # u už převedeného vozidla doplnit nová pole
                    self.vozidlo(vozidla[_id(z["ID_VOZIDLA"])])
                continue
            vid = _id(z["ID_VOZIDLA"])
            vozidlo_id = self.vozidlo(vozidla[vid]) if vid in vozidla else self.vozidlo_ze_zakazky(z)
            cislo = _text(z["OZNACENIE"]) or f"SS-{z['ID']}"
            if self.s.exec(select(Zakazka.id).where(Zakazka.cislo == cislo)).first():
                novy = f"{cislo}-SS{z['ID']}"
                self.p.varuj(f"Číslo zakázky {cislo} už existuje – uloženo jako {novy}.")
                cislo = novy
            uzavrena = _text(z["UZAVRETA"]) == "1"
            planovana = _text(z["JEPLAN"]) == "1"
            prijeti = _datum_cas(z["D_PRIJATIA"], z["C_PRIJATIA"]) or datetime.now()
            tachometr = _text(z["TACHOMETER"])
            zakazka = Zakazka(
                cislo=cislo, vozidlo_id=vozidlo_id, zakaznik_id=self.zakaznik(z["ID_ODBER"], z),
                datum_prijeti=prijeti, tachometr=int(Decimal(tachometr)) if tachometr else None,
                pozadavek=_text(z["POPIS"]) or "",
                stav=StavZakazky.PREDANO if uzavrena else StavZakazky.PRIJATO,
                termin_dokonceni=_datum(z["D_UKONCPLAN"]),
                poznamka=_spoj(f"Vykonané práce: {_text(z['POPVYKPRAC'])}" if _text(z["POPVYKPRAC"]) else None,
                               f"Interní: {_text(z['POPINTERNY'])}" if _text(z["POPINTERNY"]) else None,
                               "Plánovaná zakázka (starý systém)" if planovana else None, POZNAMKA_IMPORTU),
                uzavreno=(_datum_cas(z["D_UKONCENIA"], z["C_UKONCENIA"]) or self._datum_dokladu(z["ID"]) or prijeti)
                if uzavrena else None,
            )
            for radek in self._radky("ID_ZAKAZKY", z["ID"], prace_ceniku):
                zakazka.polozky.append(PolozkaZakazky(
                    polozka_ceniku_id=radek["cenik_id"], typ=radek["typ"], kod=radek["kod"], nazev=radek["nazev"],
                    jednotka=radek["jednotka"], mnozstvi=radek["mnozstvi"], cena=radek["cena"],
                    sazba_dph=radek["sazba_dph"], vytvoreno=prijeti))
            self._zapis_mapu("ZAKAZKY", z["ID"], zakazka)
            self.p.pridano["POLOZKY_ZAKAZEK"] = self.p.pridano.get("POLOZKY_ZAKAZEK", 0) + len(zakazka.polozky)
            self.faktury_zakazky(z["ID"], zakazka, prace_ceniku)

    # --- doklady
    def _datum_dokladu(self, zakazka_puvodni_id: str) -> datetime | None:
        """Nejpozdější vystavení dokladu k zakázce – náhrada chybějícího data ukončení."""
        data = [_datum(f["D_VYSTAV"]) for f in self.data.get("FAKTURY", []) if f["ID_ZAKAZKY"] == zakazka_puvodni_id]
        data = [d for d in data if d]
        return datetime.combine(max(data), time(12, 0)) if data else None

    def faktury_zakazky(self, zakazka_puvodni_id: str, zakazka: Zakazka, prace_ceniku: dict) -> None:
        vozidlo = self.s.get(Vozidlo, zakazka.vozidlo_id)
        for f in self.data.get("FAKTURY", []):
            if f["ID_ZAKAZKY"] != zakazka_puvodni_id or self._nove_id("FAKTURY", f["ID"]):
                continue
            if _text(f["MENAEURO"]) == "1":
                self.p.varuj(f"Doklad {f['OZNACENIE']} je v eurech – nepřeveden.")
                continue
            cislo = _text(f["OZNACENIE"]) or f"SS-F{f['ID']}"
            if self.s.exec(select(Faktura.id).where(Faktura.cislo == cislo)).first():
                novy = f"{cislo}-SS{f['ID']}"
                self.p.varuj(f"Číslo dokladu {cislo} už existuje – uloženo jako {novy}.")
                cislo = novy
            vystaveno = _datum(f["D_VYSTAV"]) or zakazka.datum_prijeti.date()
            forma = FormaUhrady.PREVOD if _text(f["FORM_UHR"]) == "PP" else FormaUhrady.HOTOVE
            faktura = Faktura(
                vytisteno=True,  # #167: tiskl se ve starém systému
                cislo=cislo, typ=TypDokladu.VYUCTOVANI if _text(f["VYUCTOV"]) == "1" else TypDokladu.FAKTURA,
                zakazka_id=zakazka.id, zakaznik_id=self.zakaznik(f["ID_ODBER"], f),
                odb_nazev=_jmeno(f) or "",
                odb_ulice=_text(f["ULICA"]), odb_mesto=_text(f["MESTO"]), odb_psc=_text(f["PSC"]),
                odb_ico=_text(f["ICO"]), odb_dic=_text(f["DIC"]) or _text(f["ICDPH"]),
                datum_vystaveni=vystaveno, duzp=_datum(f["D_DODANIA"]) or vystaveno,
                datum_splatnosti=_datum(f["D_SPLATN"]) or vystaveno, forma_uhrady=forma,
                variabilni_symbol=variabilni_symbol(cislo) or None, platce_dph=True,
                spz=vozidlo.spz if vozidlo else None, vozidlo_popis=vozidlo.popis if vozidlo else None,
                tachometr=zakazka.tachometr, cislo_zakazky=zakazka.cislo,
                poznamka=_spoj(f["TEXTKONIEC"], POZNAMKA_IMPORTU), vytvoreno=datetime.combine(vystaveno, time(12, 0)),
            )
            radky = self._radky("ID_FAKTURY", f["ID"], prace_ceniku)
            for r in self.data.get("ZLAVY", []):
                if r["ID_FAKTURY"] == f["ID"]:
                    radky.append({"typ": TypPolozky.MATERIAL, "kod": None, "nazev": _text(r["NAZOV"]) or "Sleva",
                                  "jednotka": _text(r["JEDNOTKA"]) or "ks", "mnozstvi": _cislo(r["MNOZSTVO"], "1"),
                                  "cena": _cislo(r["JEDCENA"]), "sazba_dph": _cislo(r["SADZBADPH"], "21")})
            bez_dph, s_dph, dph = _cislo(f["BEZ_DPH"]), _cislo(f["S_DPH"]), _cislo(f["DPH"])
            if not radky:
                sazba = (dph * 100 / bez_dph).quantize(Decimal("1")) if bez_dph else Decimal("21")
                radky.append({"typ": TypPolozky.MATERIAL, "kod": None, "nazev": "Doklad ze starého systému bez rozpisu položek",
                              "jednotka": "ks", "mnozstvi": Decimal("1"), "cena": bez_dph, "sazba_dph": sazba})
                self.p.varuj(f"Doklad {cislo} nemá ve starém systému položky – vložen jeden souhrnný řádek.")
            for r in radky:
                faktura.polozky.append(PolozkaFaktury(typ=r["typ"], kod=r["kod"], nazev=r["nazev"], jednotka=r["jednotka"],
                                                      mnozstvi=r["mnozstvi"], cena=r["cena"], sazba_dph=r["sazba_dph"]))
            # Částka k úhradě se přebírá ze starého systému; rozdíl proti položkám jde do zaokrouhlení.
            spocteno = polozky_sluzba.rekapitulace_radku(faktura.polozky).celkem
            faktura.zaokrouhleni = s_dph - spocteno
            faktura.celkem = s_dph
            if abs(faktura.zaokrouhleni) >= 1:
                self.p.varuj(f"Doklad {cislo}: položky dávají {spocteno} Kč, starý systém {s_dph} Kč – rozdíl "
                             f"{faktura.zaokrouhleni} Kč veden jako zaokrouhlení.")
            # Etapa 1: všechny importované doklady jako uhrazené (rozhodnutí uživatele).
            splaceno = _text(f["SPLATENA"]) == "1"
            faktura.uhrady.append(Uhrada(
                datum=_datum(f["D_ZAPLAT"]) or vystaveno, castka=s_dph, zpusob=forma,
                poznamka="Import ze starého systému" if splaceno else "Import ze starého systému – úhrada ve starém systému neevidována",
                vytvoreno=datetime.combine(vystaveno, time(12, 0))))
            self._zapis_mapu("FAKTURY", f["ID"], faktura)

    def spust(self) -> Protokol:
        prace_ceniku = self.predvolene_prace()
        self.zakazky(prace_ceniku)
        return self.p


def importuj(session: Session, data: dict) -> Protokol:
    """Naimportuje data a provede commit. Při chybě se neuloží nic."""
    try:
        protokol = ImporterStarySystem(session, data).spust()
        session.commit()
        return protokol
    except Exception:
        session.rollback()
        raise


def main():
    import argparse
    import json
    import shutil
    from pathlib import Path

    from app.db import init_db, vytvor_engine

    parser = argparse.ArgumentParser(description="Import exportu starého systému do databáze Autoservisu")
    parser.add_argument("export", type=Path, help="JSON z nastroje/stary_system_export.py")
    parser.add_argument("--db", type=Path, required=True, help="cílová databáze (doporučeno kopie)")
    parser.add_argument("--z-kopie", type=Path, help="nejdřív zkopírovat tuto databázi do --db (jen když --db neexistuje)")
    args = parser.parse_args()
    if args.z_kopie:
        if args.db.exists():
            parser.error(f"{args.db} už existuje – nepřepisuji. Smažte ji, nebo spusťte bez --z-kopie.")
        shutil.copy2(args.z_kopie, args.db)
    data = json.loads(args.export.read_text(encoding="utf-8"))
    engine = vytvor_engine(f"sqlite:///{args.db.resolve()}")
    init_db(engine)
    with Session(engine) as session:
        protokol = importuj(session, data)
    vystup = args.export.with_name(f"{args.export.stem}-protokol-{datetime.now():%Y%m%d-%H%M%S}.md")
    vystup.write_text(protokol.jako_markdown(data.get("meta")), encoding="utf-8")
    print("Přidáno:", protokol.pridano)
    print("Přeskočeno:", protokol.preskoceno)
    print(f"Upozornění: {len(protokol.upozorneni)} – podrobnosti v {vystup}")


if __name__ == "__main__":
    main()
