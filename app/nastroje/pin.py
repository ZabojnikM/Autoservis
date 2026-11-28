"""Zrušení zapomenutého PINu pro Nastavení (#219).

Spuštění ve složce aplikace (jako účet služby): `.venv/bin/python -m app.nastroje.pin --zrusit`
(jiná databáze: proměnná AUTOSERVIS_DB). Aplikace pak při kliknutí na Nastavení vyzve k vytvoření nového PINu.
"""
import argparse

from sqlmodel import Session

from app.db import engine, init_db
from app.services import pin


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="PIN pro vstup do Nastavení Autoservisu")
    parser.add_argument("--zrusit", action="store_true", help="zrušit PIN (zapomenutý PIN)")
    args = parser.parse_args(argv)
    if not args.zrusit:
        parser.print_help()
        return 1
    init_db()
    with Session(engine) as session:
        byl = pin.zrus(session)
    print("PIN zrušen. Při kliknutí na Nastavení aplikace vyzve k vytvoření nového." if byl else "PIN nebyl nastavený.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
