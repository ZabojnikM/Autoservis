"""Sekce Zálohy v Nastavení (HTMX blok #zalohy, #76)."""
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Form, Request
from fastapi.responses import FileResponse, PlainTextResponse

from app import config
from app.services import ChybaValidace, zalohy
from app.web.routes import DB
from app.web.sablony import templates

router = APIRouter(prefix="/nastaveni/zalohy")
ZOBRAZIT = 10  # nejnovějších záloh v přehledu


def _cas(hodnota: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(hodnota) if hodnota else None
    except ValueError:
        return None


def _blok(request: Request, db, chyba: str = "", hlaseni: str = "", slozka_hodnota: str | None = None):
    slozka = zalohy.slozka(db)
    stav = zalohy.nacti_stav(zalohy.ZALOHY)
    na_serveru = zalohy.seznam(zalohy.ZALOHY)
    ve_slozce = zalohy.seznam(Path(slozka)) if slozka else []
    return templates.TemplateResponse(request, "_zalohy.html", {
        "slozka": slozka if slozka_hodnota is None else slozka_hodnota,
        "ulozena_slozka": slozka,
        "slozka_dostupna": bool(slozka) and Path(slozka).is_dir(),
        "denni": stav.get("denni", {}), "tydenni": stav.get("tydenni", {}),
        "denni_uspech": _cas(stav.get("denni", {}).get("uspech")),
        "tydenni_uspech": _cas(stav.get("tydenni", {}).get("uspech")),
        "na_serveru": na_serveru[:ZOBRAZIT], "na_serveru_pocet": len(na_serveru),
        "ve_slozce": [s for s in ve_slozce if s.druh == "týdenní"],
        "zapnuto": zalohy.zapnuto(), "prazdna": zalohy.je_prazdna(config.DB_PATH), "slozka_serveru": str(zalohy.ZALOHY), "db": config.DB_PATH.name,
        "dennich": zalohy.DENNICH, "tydennich": zalohy.TYDENNICH,
        "obnova": stav.get("obnova", {}), "obnova_uspech": _cas(stav.get("obnova", {}).get("uspech")),
        "chyba": chyba, "hlaseni": hlaseni,
    })


@router.get("")
def blok(request: Request, db: DB):
    return _blok(request, db)


@router.post("/ted")
def zalohovat_ted(request: Request, db: DB):
    try:
        cil = zalohy.rucni()
    except zalohy.ChybaZalohy as e:
        return _blok(request, db, chyba=str(e))
    return _blok(request, db, hlaseni=f"Záloha {cil.name} je hotová a zkontrolovaná.")


@router.post("/slozka")
def ulozit_slozku(request: Request, db: DB, zaloha_slozka: str = Form("")):
    try:
        ulozeno = zalohy.uloz_slozku(db, zaloha_slozka)
    except ChybaValidace as e:
        return _blok(request, db, chyba=str(e), slozka_hodnota=zaloha_slozka)
    if not ulozeno:
        return _blok(request, db, hlaseni="Týdenní zálohy do složky jsou vypnuté.")
    return _blok(request, db, hlaseni=f"Složka {ulozeno} uložena. První týdenní záloha proběhne do 10 minut, "
                                      "nebo ji spusťte tlačítkem Zálohovat do složky teď.")


@router.post("/tydenni")
def tydenni_ted(request: Request, db: DB):
    try:
        cil = zalohy.tydenni_ted(zalohy.slozka(db))
    except zalohy.ChybaZalohy as e:
        return _blok(request, db, chyba=str(e))
    return _blok(request, db, hlaseni=f"Týdenní záloha {cil.name} je uložená ve složce.")


@router.post("/obnovit")
def obnovit(request: Request, db: DB, nazev: str = Form(""), zdroj: str = Form("server")):
    try:
        soubor = zalohy.soubor_zalohy(nazev, zdroj, zalohy.slozka(db))
        db.close()  # vlastní spojení požadavku pustit, ať obnova nečeká na zámek
        v = zalohy.obnov(soubor)
    except zalohy.ChybaZalohy as e:
        return _blok(request, db, chyba=str(e))
    p = v["pocty"]
    return _blok(request, db, hlaseni=(
        f"Obnoveno ze zálohy {v['soubor']}: {p['zakazka']} zakázek, {p['vozidlo']} vozidel, "
        f"{p['zakaznik']} zákazníků, {p['faktura']} dokladů. Stav před obnovou je uložený "
        f"v záloze {v['pred_obnovou']}. Otevřené stránky v jiných oknech obnovte (F5)."))


@router.get("/stahnout/{nazev}")
def stahnout(nazev: str):
    try:
        soubor = zalohy.soubor_ke_stazeni(nazev)
    except zalohy.ChybaZalohy as e:
        return PlainTextResponse(str(e), status_code=404)
    return FileResponse(soubor, media_type="application/octet-stream", filename=soubor.name)
