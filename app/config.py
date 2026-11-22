"""Nastavení aplikace."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
# AUTOSERVIS_DB umožní spustit aplikaci nad jinou databází (např. kopií s importem ze starého systému).
DB_PATH = Path(os.environ["AUTOSERVIS_DB"]).resolve() if os.environ.get("AUTOSERVIS_DB") else DATA_DIR / "autoservis.db"
DATABASE_URL = f"sqlite:///{DB_PATH}"

WEB_DIR = Path(__file__).resolve().parent / "web"
TEMPLATES_DIR = WEB_DIR / "templates"
STATIC_DIR = WEB_DIR / "static"

# Příjem vozidel (#51): JSON s návštěvami, které zpracoval Přijímací technik (OpenBot) – jen čtení.
# Na serveru se cesta nastavuje ve službě (AUTOSERVIS_PRIJEM_JSON), výchozí je umístění OpenBotu.
PRIJEM_JSON = os.environ.get(
    "AUTOSERVIS_PRIJEM_JSON", "/var/lib/openbot/OpenBot/Shared/autoservis-prototype/json-data/visits.json")

APP_NAME = "Autoservis"
APP_VERSION = "0.11.0"
