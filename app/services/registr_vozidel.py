"""Načtení technických údajů vozidla z Registru silničních vozidel (Datová kostka, dataovozidlech.cz).

Veřejné API Ministerstva dopravy: GET https://api.dataovozidlech.cz/api/vehicletechnicaldata/v2?vin=…
(nebo ?tp=… / ?orv=…), klíč v hlavičce API_KEY. Klíč zdarma po registraci na
https://dataovozidlech.cz/registraceapi (jméno + e-mail). Limit 27 dotazů za minutu na klíč.
Dokumentace: https://dataovozidlech.cz/data/RSV_Verejna_API_DK_v1_0.pdf
"""
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

from app.services import ChybaValidace

API_URL = "https://api.dataovozidlech.cz/api/vehicletechnicaldata/v2"
REGISTRACE_URL = "https://dataovozidlech.cz/registraceapi"
TIMEOUT = 15  # s

# pole vozidla, která se z registru doplní jen do prázdného pole (registr je nemá přesně)
JEN_DO_PRAZDNEHO = {"rok_vyroby"}

# značky, které se píšou velkými písmeny (ostatní: ŠKODA → Škoda)
ZNACKY_VELKE = {"BMW", "DAF", "MAN", "MG", "KIA", "VW", "DS", "BYD", "GMC", "UAZ", "LDV", "IVECO"}


class ChybaRegistru(ChybaValidace):
    """Registr nejde použít (chybí klíč, vozidlo nenalezeno, limit dotazů, výpadek)."""


def _stahni(parametry: dict, api_klic: str) -> dict:
    url = f"{API_URL}?{urllib.parse.urlencode(parametry)}"
    pozadavek = urllib.request.Request(url, headers={"API_KEY": api_klic, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(pozadavek, timeout=TIMEOUT) as odpoved:
            telo = odpoved.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        text = e.read().decode("utf-8", errors="replace")
        if e.code in (401, 403):
            raise ChybaRegistru("Registr vozidel odmítl API klíč – zkontrolujte ho v Nastavení.") from e
        if e.code == 429 or "maximální počet" in text:
            raise ChybaRegistru("Registr vozidel: překročen limit dotazů (27 za minutu). Zkuste to za chvíli.") from e
        if e.code == 404:
            raise ChybaRegistru("Vozidlo v registru nenalezeno.") from e
        raise ChybaRegistru(f"Registr vozidel vrátil chybu {e.code}.") from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise ChybaRegistru("Registr vozidel neodpovídá – zkontrolujte připojení k internetu.") from e
    if "maximální počet" in telo:
        raise ChybaRegistru("Registr vozidel: překročen limit dotazů (27 za minutu). Zkuste to za chvíli.")
    try:
        return json.loads(telo)
    except ValueError as e:
        raise ChybaRegistru("Registr vozidel vrátil nečitelnou odpověď.") from e


def nacti(api_klic: str | None, vin: str | None = None, tp: str | None = None, orv: str | None = None) -> dict:
    """Surová data vozidla z registru (slovník „Data“ z odpovědi API)."""
    api_klic = (api_klic or "").strip()
    if not api_klic:
        raise ChybaRegistru("Chybí API klíč registru vozidel – zadejte ho v Nastavení "
                            f"(zdarma po registraci na {REGISTRACE_URL}).")
    parametry = {k: re.sub(r"\s", "", v).upper() for k, v in (("vin", vin), ("tp", tp), ("orv", orv)) if v and v.strip()}
    if not parametry:
        raise ChybaRegistru("Zadejte VIN vozidla.", "vin")
    odpoved = _stahni(parametry, api_klic)
    data = odpoved.get("Data") if isinstance(odpoved, dict) else None
    if isinstance(data, list):
        if len(data) > 1:
            raise ChybaRegistru("Registr našel víc vozidel – zadejte celý VIN.", "vin")
        data = data[0] if data else None
    if not data:
        raise ChybaRegistru("Vozidlo v registru nenalezeno.", "vin")
    return data


def _text(hodnota) -> str | None:
    if hodnota is None:
        return None
    hodnota = re.sub(r"\s+", " ", str(hodnota)).strip(" /.;")
    return hodnota or None


def _hezky(text: str | None) -> str | None:
    """ČERVENÁ-TMAVÁ → Červená-tmavá."""
    return text[:1].upper() + text[1:].lower() if text else None


def _znacka(text: str | None) -> str | None:
    if not text:
        return None
    return " ".join(s if s in ZNACKY_VELKE else s.capitalize() for s in text.split(" "))


def _model(text: str | None) -> str | None:
    # FELICIA COMBI → Felicia Combi; zkratky s číslicí (TDI, 1.9, A4) beze změny
    if not text:
        return None
    return " ".join(s if any(z.isdigit() for z in s) or len(s) <= 3 else s.capitalize() for s in text.split(" "))


def _palivo(text: str | None) -> str | None:
    if not text:
        return None
    t = text.upper()
    casti = []
    if t.startswith("NM") or "NAFTA" in t:
        casti.append("nafta")
    elif t.startswith("BA") or "BENZIN" in t:
        casti.append("benzín")
    if "LPG" in t:
        casti.append("LPG")
    if "CNG" in t or "ZEMNÍ PLYN" in t:
        casti.append("CNG")
    if "ELEKT" in t:
        casti.append("elektro")
    if "VODÍK" in t:
        casti.append("vodík")
    return " + ".join(casti) if casti else text.lower()


def _datum(hodnota) -> str | None:
    """'1997-03-21T00:00:00' → '1997-03-21' (formát pole typu date)."""
    if not hodnota:
        return None
    try:
        return datetime.fromisoformat(str(hodnota)[:19]).date().isoformat()
    except ValueError:
        return None


def na_pole_vozidla(data: dict) -> dict:
    """Údaje z registru převedené na pole vozidla (jako ve formuláři). Prázdné hodnoty vynechá."""
    palivo = _palivo(_text(data.get("Palivo")))
    if not palivo and data.get("VozidloElektricke") == "ANO":
        palivo = "elektro"
    objem = data.get("MotorZdvihObjem")
    datum_registrace = _datum(data.get("DatumPrvniRegistrace")) or _datum(data.get("DatumPrvniRegistraceVCr"))
    pole = {
        "vin": _text(data.get("VIN")),
        "znacka": _znacka(_text(data.get("TovarniZnacka"))),
        "model": _model(_text(data.get("ObchodniOznaceni"))),
        "datum_registrace": datum_registrace,
        "rok_vyroby": datum_registrace[:4] if datum_registrace else None,
        "kod_motoru": _text(data.get("MotorTyp")),
        "objem": f"{float(objem):g}" if objem else None,  # API vrací 1289.0 → „1289“
        "vykon": _text(data.get("MotorMaxVykon")),  # „kW / ot/min“, stejně jako ve starém systému
        "palivo": palivo,
        "barva": _hezky(_text(data.get("VozidloKaroserieBarva"))),
        # Typ vozidla (TP): varianta a verze typového schválení, jak je převzal starý systém
        "cislo_motoru": _text(" ".join(filter(None, (_text(data.get("Varianta")), _text(data.get("Verze")))))),
        "termin_stk": _datum(data.get("PravidelnaTechnickaProhlidkaDo")),
    }
    return {k: v for k, v in pole.items() if v}


def souhrn(data: dict) -> str:
    """Krátká informace pro uživatele: stav vozidla v registru, počet vlastníků."""
    casti = []
    if data.get("StatusNazev"):
        casti.append(f"stav: {str(data['StatusNazev']).lower()}")
    if data.get("PocetVlastniku") is not None:
        casti.append(f"vlastníků: {data['PocetVlastniku']}")
    if data.get("PocetProvozovatelu") is not None:
        casti.append(f"provozovatelů: {data['PocetProvozovatelu']}")
    return ", ".join(casti)
