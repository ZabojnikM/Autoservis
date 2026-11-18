"""Export vzorku dat ze starého systému (602SQL) do JSON – POUZE ČTENÍ (SELECT).

Spouští se 32bitovým Pythonem z projektu Autoservis-MCP (kvůli ODBC ovladači 602SQL):

    C:\\Autoservis-MCP\\.venv\\Scripts\\python.exe nastroje\\stary_system_export.py data\\stary-system-export\\vzorek.json --zakazek 50

DSN se bere z proměnné AUTOSERVIS_DSN (výchozí AutoservisTest). Do starého systému se nic nezapisuje.
"""
import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.environ.get("STARY_SYSTEM_MCP_SRC", r"C:\Autoservis-MCP\src"))
import db  # noqa: E402  – ODBC čtečka z Autoservis-MCP

SLOUPCE = {
    "ZAKAZKY": "ID, JEPLAN, OZNACENIE, ID_ODBER, ID_VOZIDLA, MENO1, MENO2, MENO3, ULICA, MESTO, PSC, ICO, DIC, "
               "TELEFON, EMAIL, POPIS, POPVYKPRAC, POPINTERNY, D_PRIJATIA, C_PRIJATIA, D_UKONCPLAN, D_UKONCENIA, "
               "C_UKONCENIA, UZAVRETA, SPZ, SPZ_P, TYPAUTA, VYROBENE, PALIVO, TACHOMETER, CKAROSERIE",
    "VOZIDLA": "ID, ID_ODBER, SPZ, SPZ_P, TYPAUTA, VYROBENE, CKAROSERIE, CMOTORA, KODTYPUMOT, OBJEMMOT, VYKONMOT, "
               "PALIVODRUH, FARBA, OLEJ, DOPLNKY, POZNAMKA, TERMINSTK, TERMINEK, POPIS",
    "PARTNERI": "ID, MENO1, MENO2, MENO3, ULICA, MESTO, PSC, ICO, DIC, ICDPH, TELEFON, EMAIL, POZNAMKA, JEDOD, JEODB",
    "FAKTURY": "ID, OZNACENIE, ID_ZAKAZKY, ID_ODBER, MENO1, MENO2, MENO3, ULICA, MESTO, PSC, ICO, DIC, ICDPH, "
               "FORM_UHR, D_VYSTAV, D_DODANIA, D_SPLATN, D_ZAPLAT, SPLATENA, BEZ_DPH, S_DPH, DPH, ZAOKRUH, VYUCTOV, "
               "MENAEURO, TEXTKONIEC",
    "VYKPRACE": "ID, ID_ZAKAZKY, ID_FAKTURY, KOD, NAZOV, JEDNOTKA, JEDCENA, MNOZSTVO, SADZBADPH, DATUM, ZLAVA, FAKTUROVAT",
    "POHYBY": "ID, DRUH, ID_SKLKARTY, ID_ZAKAZKY, ID_FAKTURY, DATUM, MNOZSTVO, JEDCENA, FAKCENA, SADZBADPH, POPIS, "
              "ZLAVA, FAKTUROVAT",
    "ZLAVY": "ID, ID_FAKTURY, DRUHZLAVY, ZLAVAPERCENT, NAZOV, JEDNOTKA, JEDCENA, MNOZSTVO, SADZBADPH",
    "SKLKARTY": "ID, OZNACENIE, CISLO, NAZOV, JEDNOTKA, CENA, CENAPR1, CENAPR2, CENAPR3, SADZBADPH, MNOZSTVO, VYRADENY",
    "PRACE": "ID, KOD, NAZOV, JEDNOTKA, JEDCENA, MNOZSTVO, SADZBADPH",
}


def _in(ids) -> str:
    cisla = sorted({int(i) for i in ids if i not in (None, "")})
    return ",".join(str(i) for i in cisla) if cisla else "NULL"


def _vyber(conn, tabulka, kde, limit=100000):
    return conn.query(f"SELECT {SLOUPCE[tabulka]} FROM {tabulka} WHERE {kde}", limit=limit)


def exportuj(conn, pocet_zakazek: int) -> dict:
    zakazky = conn.query(f"SELECT {SLOUPCE['ZAKAZKY']} FROM ZAKAZKY ORDER BY ID DESC", limit=pocet_zakazek)
    zak_ids = _in(z["ID"] for z in zakazky)
    vozidla = _vyber(conn, "VOZIDLA", f"ID IN ({_in(z['ID_VOZIDLA'] for z in zakazky)})")
    faktury = _vyber(conn, "FAKTURY", f"ID_ZAKAZKY IN ({zak_ids})")
    fak_ids = _in(f["ID"] for f in faktury)
    # Položky podle zakázky i podle dokladu (některé doklady mají položky vedené mimo zakázku).
    prace = _vyber(conn, "VYKPRACE", f"ID_ZAKAZKY IN ({zak_ids}) OR ID_FAKTURY IN ({fak_ids})")
    pohyby = _vyber(conn, "POHYBY", f"DRUH=-1 AND (ID_ZAKAZKY IN ({zak_ids}) OR ID_FAKTURY IN ({fak_ids}))")
    zlavy = _vyber(conn, "ZLAVY", f"ID_FAKTURY IN ({fak_ids})")
    karty = _vyber(conn, "SKLKARTY", f"ID IN ({_in(p['ID_SKLKARTY'] for p in pohyby)})")
    partneri_ids = [z["ID_ODBER"] for z in zakazky] + [v["ID_ODBER"] for v in vozidla] + [f["ID_ODBER"] for f in faktury]
    partneri = _vyber(conn, "PARTNERI", f"ID IN ({_in(partneri_ids)})")
    # Předvolených prací je málo a kódy mohou mít diakritiku – načteme všechny a vybereme v Pythonu.
    kody = {p["KOD"] for p in prace if p["KOD"]}
    predvolene = [p for p in conn.query(f"SELECT {SLOUPCE['PRACE']} FROM PRACE", limit=10000) if p["KOD"] in kody]
    return {
        "meta": {"zdroj": os.environ.get("AUTOSERVIS_DSN", "AutoservisTest"),
                 "exportovano": datetime.now().isoformat(timespec="seconds"),
                 "pocet_zakazek": pocet_zakazek},
        "ZAKAZKY": zakazky, "VOZIDLA": vozidla, "PARTNERI": partneri, "FAKTURY": faktury,
        "VYKPRACE": prace, "POHYBY": pohyby, "ZLAVY": zlavy, "SKLKARTY": karty, "PRACE": predvolene,
    }


def main():
    parser = argparse.ArgumentParser(description="Export vzorku ze starého systému (jen čtení)")
    parser.add_argument("vystup", type=Path)
    parser.add_argument("--zakazek", type=int, default=50)
    args = parser.parse_args()
    with db.Database(diagnostic_watchdog=True) as conn:
        data = exportuj(conn, args.zakazek)
    args.vystup.parent.mkdir(parents=True, exist_ok=True)
    args.vystup.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    print("Exportováno:", {k: len(v) for k, v in data.items() if k != "meta"})


if __name__ == "__main__":
    main()
