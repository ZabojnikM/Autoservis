"""Instalátor zástupce pro Windows ke stažení z Nastavení (#71, navazuje na #18).

Jeden soubor .bat: nahoře pár řádků pro cmd, které spustí PowerShell se skriptem uloženým v témže
souboru pod značkou (nastroje/zastupce-autoservis.ps1) a předají mu adresu serveru – nic se nemusí
rozbalovat ani psát. Zástupce otevře Autoservis ve vlastním okně Edge / Chrome."""
import re
from pathlib import Path

from app.services import ChybaValidace

SKRIPT = Path(__file__).resolve().parents[2] / "nastroje" / "zastupce-autoservis.ps1"
NAZEV_SOUBORU = "Autoservis-zastupce.bat"
ZNACKA = "#SKRIPT-AUTOSERVIS"

# jen znaky, které jsou bezpečné v příkazové řádce cmd i v řetězci PowerShellu (žádné uvozovky, %, &, …)
_ADRESA = re.compile(r"^https?://[A-Za-z0-9.\-]+(:\d{1,5})?(/[A-Za-z0-9._~/\-]*)?$")


def normalizuj_adresu(adresa) -> str:
    adresa = str(adresa or "").strip().rstrip("/")
    if adresa and not re.match(r"^https?://", adresa):
        adresa = "http://" + adresa
    if not _ADRESA.match(adresa):
        raise ChybaValidace("Zadejte adresu Autoservisu, např. http://server:8000.", "adresa")
    return adresa


def bat(adresa, skript: str | None = None) -> bytes:
    """Obsah .bat s vyplněnou adresou. `skript` = obsah PowerShell skriptu (výchozí z nastroje/)."""
    adresa = normalizuj_adresu(adresa)
    if skript is None:
        skript = SKRIPT.read_text(encoding="utf-8-sig")
    # značka se v příkazu skládá ze dvou částí, aby se nenašla už v řádku příkazu
    hlavicka = [
        "@echo off",
        "rem Autoservis - vytvori zastupce na plose a v nabidce Start (aplikace ve vlastnim okne).",
        "rem Nic neinstaluje, zastupce jde kdykoli smazat.",
        'powershell -NoProfile -ExecutionPolicy Bypass -Command "$t = [IO.File]::ReadAllText(\'%~f0\', '
        "[Text.Encoding]::UTF8); $t = $t.Substring($t.IndexOf('#SKRIPT' + '-AUTOSERVIS')); "
        f"& ([scriptblock]::Create($t)) -Adresa '{adresa}'\"",
        "pause",
        "exit /b",
        ZNACKA,
    ]
    return ("\r\n".join(hlavicka) + "\r\n" + skript.replace("\r\n", "\n").replace("\n", "\r\n")).encode("utf-8")
