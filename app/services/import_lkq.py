"""Import dodacího listu LKQ (CSV, od #199 i PDF) do ceníku materiálu a volitelně do zakázky (#8).

Postup: `nacti_csv` → náhled (`nahled` spáruje díly s ceníkem podle kódu) → `importuj` vybrané díly.
Ceny vždy z LKQ: nákupní = „Cena/ks“, prodejní = „MOC bez DPH/ks“, sazba DPH z listu. U existující
položky se mění jen ceny. Opakovaný import stejného listu nic nezdvojí – díly se jen spárují.
"""
import io
import json
import re
from dataclasses import asdict, dataclass, field
from decimal import Decimal, InvalidOperation

from sqlmodel import Session, func, select

from app.zaznam import log
from app.models import PolozkaCeniku, TypPolozky, zaokrouhli
from app.services import ChybaValidace
from app.services import katalogy
from app.services import polozky as polozky_sluzba

ZAHLAVI_POLOZEK = "Cislo;Kod;Nazev"
SLOUPCE = {"kod": "Kod", "nazev": "Nazev", "mnozstvi": "Mnozstvi", "moc": "MOC bez DPH/ks",
           "dph": "DPH (%)", "nakup": "Cena/ks"}
CHYBA_SOUBORU = "Soubor není dodací list LKQ (CSV). Stáhněte dodací list z e-shopu LKQ ve formátu CSV a zkuste to znovu."
CHYBA_PDF = ("PDF není čitelný dodací list LKQ (chybí tabulka dodaného zboží – např. sken bez textu). "
             "Použijte PDF nebo CSV dodacího listu z e-shopu LKQ.")
DPH_PDF = Decimal("21")  # v PDF je sloupec sazby u dodaného zboží prázdný


@dataclass
class DilListu:
    kod: str
    nazev: str
    mnozstvi: Decimal
    nakup: Decimal   # Cena/ks – nákupní cena bez DPH po slevě
    moc: Decimal     # MOC bez DPH/ks – doporučená prodejní cena
    dph: Decimal


@dataclass
class DodaciList:
    cislo: str = ""
    datum: str = ""
    dodavatel: str = ""
    bez_dph: Decimal | None = None
    s_dph: Decimal | None = None
    dily: list[DilListu] = field(default_factory=list)


def _dekoduj(obsah: bytes) -> str:
    for kodovani in ("utf-8-sig", "cp1250"):
        try:
            return obsah.decode(kodovani)
        except UnicodeDecodeError:
            continue
    raise ChybaValidace(CHYBA_SOUBORU)


def _cislo(text: str, nazev: str, radek: int) -> Decimal:
    try:
        return Decimal((text or "").strip().replace(" ", "").replace(",", "."))
    except InvalidOperation:
        raise ChybaValidace(f"Dodací list, řádek {radek}: {nazev} „{text}“ není číslo.") from None


def nacti_csv(obsah: bytes) -> DodaciList:
    """CSV dodacího listu LKQ → DodaciList. Neplatný soubor → ChybaValidace."""
    if not obsah:
        raise ChybaValidace("Vyberte soubor dodacího listu.")
    radky = _dekoduj(obsah).splitlines()
    vysledek = DodaciList()
    sloupce = None
    for i, radek in enumerate(radky, start=1):
        bunky = [b.strip() for b in radek.split(";")]
        prvni = bunky[0] if bunky else ""
        if sloupce is None:
            if radek.startswith(ZAHLAVI_POLOZEK):
                try:
                    sloupce = {klic: bunky.index(nazev) for klic, nazev in SLOUPCE.items()}
                except ValueError:
                    raise ChybaValidace(CHYBA_SOUBORU) from None
            elif "dodaci list" in prvni.lower() and len(bunky) > 1:
                vysledek.cislo = bunky[1]
            elif prvni == "Datum vystaveni" and len(bunky) > 1:
                vysledek.datum = bunky[1]
            elif prvni == "Dodavatel" and len(bunky) > 1:
                vysledek.dodavatel = bunky[1]
            continue
        if prvni.startswith("Sazba DPH"):  # za díly následuje rekapitulace DPH
            break
        if not prvni:
            continue
        if len(bunky) <= max(sloupce.values()):
            raise ChybaValidace(f"Dodací list, řádek {i}: chybí některé údaje dílu.")
        kod, nazev = bunky[sloupce["kod"]], bunky[sloupce["nazev"]]
        if not kod or not nazev:
            raise ChybaValidace(f"Dodací list, řádek {i}: díl nemá kód nebo název.")
        vysledek.dily.append(DilListu(
            kod=kod, nazev=nazev,
            mnozstvi=_cislo(bunky[sloupce["mnozstvi"]], "množství", i),
            nakup=_cislo(bunky[sloupce["nakup"]], "cena/ks", i),
            moc=_cislo(bunky[sloupce["moc"]], "MOC", i),
            dph=_cislo(bunky[sloupce["dph"]], "DPH", i),
        ))
    if sloupce is None:
        raise ChybaValidace(CHYBA_SOUBORU)
    if not vysledek.dily:
        raise ChybaValidace("Dodací list neobsahuje žádné díly.")
    for radek in radky:  # „Celkem;bez DPH;DPH;s DPH“
        bunky = [b.strip() for b in radek.split(";")]
        if bunky[0] == "Celkem" and len(bunky) >= 4:
            try:
                vysledek.bez_dph, vysledek.s_dph = Decimal(bunky[1]), Decimal(bunky[3])
            except InvalidOperation:
                pass
    return vysledek


# ---------------------------------------------------------------- PDF dodací list (#199)

_CASTKA = r"\d{1,3}(?: \d{3})*,\d{2}"
_RADEK_PDF = re.compile(rf"^(?P<vodni>.+?) (?P<mn>\d+(?:,\d+)?) (?P<mj>\S+) (?P<nakup>{_CASTKA}) (?P<nakup_s>{_CASTKA}) "
                        rf"(?P<celkem>{_CASTKA}) (?P<moc>{_CASTKA}) (?P<moc_s>{_CASTKA})(?: \S+)?$")


def _castka_pdf(text: str) -> Decimal:
    return Decimal(text.replace(" ", "").replace(",", "."))


def _kody_ze_sloupcu(text_rozvrzeni: str) -> list[str]:
    """Kódy dílů z rozvrženého textu: první sloupec řádku tabulky (sloupce dělí víc mezer). Kód je bez diakritiky,
    takže mu nevadí, že rozvržený text u některých písmen posouvá háčky – název se bere z běžného textu."""
    kody = []
    for radek in text_rozvrzeni.splitlines():
        casti = re.split(r"\s{2,}", radek.strip())
        if len(casti) >= 7 and re.fullmatch(r"\d+(?:,\d+)? \S+", casti[2]):
            kody.append(casti[0])
    return kody


def _dily_stranky(text: str, kody: list[str]) -> list[tuple[DilListu, Decimal]]:
    """Díly stránky a k nim cena celkem s DPH (množství × „Vaše cena/ks s DPH“)."""
    dily, v_tabulce = [], False
    for radek in text.splitlines():
        radek = radek.strip()
        if radek.startswith("Objednací kód Název Množství"):
            v_tabulce = True
            continue
        if not v_tabulce:
            continue
        if radek.startswith(("Výše uvedené", "Celkem bez DPH", "Zatím nedodané")):
            break
        shoda = _RADEK_PDF.match(radek)
        if not shoda:
            continue
        vodni = shoda["vodni"]
        kod = next((k for k in kody if vodni.startswith(k + " ")), None) or " ".join(vodni.split()[:2])
        nazev = vodni[len(kod):].strip()
        if not nazev:
            continue
        mnozstvi = _castka_pdf(shoda["mn"])
        dily.append((DilListu(kod=kod, nazev=nazev, mnozstvi=mnozstvi, nakup=_castka_pdf(shoda["nakup"]),
                              moc=_castka_pdf(shoda["moc"]), dph=DPH_PDF),
                     mnozstvi * _castka_pdf(shoda["nakup_s"])))
    return dily


def nacti_pdf(obsah: bytes) -> DodaciList:
    """PDF dodacího listu LKQ (tisk z e-shopu) → DodaciList. Jen dodané zboží; „Zatím nedodané zboží“ se přeskočí.
    Nákup = „Vaše cena/ks bez DPH“, prodej = „Běžná cena/ks bez DPH“ (jako MOC u CSV), DPH 21 %."""
    try:
        from pypdf import PdfReader
        stranky = PdfReader(io.BytesIO(obsah)).pages
        texty = [(s.extract_text() or "", s.extract_text(extraction_mode="layout") or "") for s in stranky]
    except Exception:  # poškozené nebo zašifrované PDF
        log.warning("Import LKQ: PDF dodacího listu nejde přečíst (poškozené nebo zašifrované)")
        raise ChybaValidace(CHYBA_PDF) from None
    vysledek = DodaciList()
    s_dph = Decimal("0")
    for text, rozvrzeni in texty:
        for dil, celkem_s_dph in _dily_stranky(text, _kody_ze_sloupcu(rozvrzeni)):
            vysledek.dily.append(dil)
            s_dph += celkem_s_dph
    if not vysledek.dily:
        raise ChybaValidace(CHYBA_PDF)
    vysledek.s_dph = zaokrouhli(s_dph)  # PDF celkovou částku s DPH neuvádí
    vse = "\n".join(t for t, _ in texty)
    if m := re.search(r"Dodací list č\.\s*(\d+)", vse):
        vysledek.cislo = m[1]
    if m := re.search(r"Datum vystavení dokladu:\s*(\d{2}\.\d{2}\.\d{4})", vse):
        vysledek.datum = m[1]
    if m := re.search(r"^(LKQ CZ [^,\n]+),", vse, re.M):
        vysledek.dodavatel = m[1].strip()
    if m := re.search(rf"Celkem bez DPH:\s*({_CASTKA})", vse):
        vysledek.bez_dph = _castka_pdf(m[1])
    return vysledek


def nacti_soubor(obsah: bytes) -> DodaciList:
    """Dodací list LKQ jako CSV nebo PDF (#199) – podle obsahu souboru."""
    if obsah[:5] == b"%PDF-":
        return nacti_pdf(obsah)
    return nacti_csv(obsah)


# ---------------------------------------------------------------- párování s ceníkem

def normalizuj_kod(kod: str | None) -> str:
    """Kód pro párování: bez mezer, velká písmena („opt 06-s383“ = „OPT 06-S383“)."""
    return re.sub(r"\s", "", kod or "").upper()


def najdi_v_ceniku(session: Session, kod: str, katalog_id: int | None = None) -> PolozkaCeniku | None:
    """Díl s kódem v katalogu, do kterého se importuje (#62); bez `katalog_id` ve výchozím."""
    norm = normalizuj_kod(kod)
    if not norm:
        return None
    if katalog_id is None:
        katalog_id = katalogy.vychozi(session).id
    return session.exec(select(PolozkaCeniku).where(
        PolozkaCeniku.katalog_id == katalog_id,
        func.upper(func.replace(PolozkaCeniku.kod, " ", "")) == norm)).first()


@dataclass
class RadekNahledu:
    index: int
    dil: DilListu
    polozka: PolozkaCeniku | None

    @property
    def je_novy(self) -> bool:
        return self.polozka is None

    @property
    def zmena_cen(self) -> bool:
        p = self.polozka
        return p is not None and (p.nakupni_cena != self.dil.nakup or p.cena != self.dil.moc or p.sazba_dph != self.dil.dph)


def nahled(session: Session, dodaci_list: DodaciList, katalog_id: int | None = None) -> list[RadekNahledu]:
    katalog_id = katalogy.podle_id(session, katalog_id).id
    return [RadekNahledu(i, d, najdi_v_ceniku(session, d.kod, katalog_id)) for i, d in enumerate(dodaci_list.dily)]


# ---------------------------------------------------------------- přenos mezi náhledem a importem

def do_json(dodaci_list: DodaciList) -> str:
    return json.dumps(asdict(dodaci_list), default=str, ensure_ascii=False)


def z_json(text: str) -> DodaciList:
    try:
        data = json.loads(text or "")
        dily = [DilListu(**{k: (Decimal(v) if k in ("mnozstvi", "nakup", "moc", "dph") else v) for k, v in d.items()})
                for d in data.pop("dily")]
        return DodaciList(**{k: (Decimal(v) if k in ("bez_dph", "s_dph") and v is not None else v)
                             for k, v in data.items()}, dily=dily)
    except (ValueError, TypeError, KeyError, InvalidOperation):
        raise ChybaValidace("Náhled dodacího listu se nepodařilo přečíst – načtěte soubor znovu.") from None


# ---------------------------------------------------------------- import

@dataclass
class Souhrn:
    aktualizovano: int = 0
    zalozeno: int = 0
    vlozeno: int = 0

    @property
    def text(self) -> str:
        casti = [f"aktualizováno {self.aktualizovano}", f"založeno {self.zalozeno}"]
        if self.vlozeno:
            casti.append(f"vloženo do zakázky {self.vlozeno}")
        return "Import LKQ: " + ", ".join(casti) + "."


def importuj(session: Session, dodaci_list: DodaciList, vybrane: list[int], zakazka_id: int | None = None,
             katalog_id: int | None = None) -> Souhrn:
    """Zapíše vybrané díly (indexy) do katalogu `katalog_id` (výchozí, není-li zadán) a s `zakazka_id`
    je vloží i do zakázky.
    Vše najednou – při chybě se neuloží nic."""
    dily = [dodaci_list.dily[i] for i in sorted(set(vybrane)) if 0 <= i < len(dodaci_list.dily)]
    if not dily:
        raise ChybaValidace("Není vybraný žádný díl.")
    souhrn = Souhrn()
    katalog_id = katalogy.podle_id(session, katalog_id).id
    try:
        for dil in dily:
            polozka = najdi_v_ceniku(session, dil.kod, katalog_id)
            if polozka is None:
                polozka = PolozkaCeniku(kod=dil.kod, nazev=dil.nazev, typ=TypPolozky.MATERIAL, jednotka="ks",
                                        katalog_id=katalog_id)
                souhrn.zalozeno += 1
            else:
                souhrn.aktualizovano += 1
            polozka.nakupni_cena = zaokrouhli(dil.nakup)
            polozka.cena = zaokrouhli(dil.moc)
            polozka.sazba_dph = dil.dph
            session.add(polozka)
            session.flush()
            if zakazka_id:
                radek = polozky_sluzba.pridej_z_ceniku(
                    session, zakazka_id, polozka.id, mnozstvi=dil.mnozstvi, commit=False
                )
                radek.cislo_dodaciho_listu = dodaci_list.cislo or None
                souhrn.vlozeno += 1
        session.commit()
    except Exception:
        session.rollback()
        raise
    return souhrn
