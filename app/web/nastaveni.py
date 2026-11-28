"""Webové stránky – nastaveni (rozděleno z routes.py, #233)."""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, Response

from app.services import zastupce
from app.services import (
    ChybaValidace, cisty_text, katalogy, nastaveni, registr_hromadne,
)
from app.web.spolecne import (
    DB, _formular, _presmeruj, _presmeruj_s_chybou, _stranka,
)

router = APIRouter()


# ---------------------------------------------------------------- nastavení

@router.get("/nastaveni", response_class=HTMLResponse)
def nastaveni_stranka(request: Request, db: DB, ulozeno: str = ""):
    return _stranka(request, "nastaveni.html", aktivni="nastaveni", nast=nastaveni.nacti(db), ulozeno=ulozeno,
                    adresa_serveru=str(request.base_url).rstrip("/"), **_kontext_katalogu(db),
                    beh=registr_hromadne.stav(), tempo=registr_hromadne.TEMPO_ZA_MINUTU)


# ---- #126: hromadné doplnění údajů vozidel z registru (běží na pozadí, průběh v Nastavení)

def _beh_registru(request, chyba=None):
    return _stranka(request, "_registr_beh.html", beh=registr_hromadne.stav(), chyba=chyba,
                    tempo=registr_hromadne.TEMPO_ZA_MINUTU)


@router.get("/nastaveni/registr/stav", response_class=HTMLResponse)
def registr_beh_stav(request: Request):
    return _beh_registru(request)


@router.post("/nastaveni/registr/doplnit", response_class=HTMLResponse)
async def registr_beh_spust(request: Request, db: DB):
    data = await _formular(request)
    klic = nastaveni.nacti(db).api_klic_registr
    if not cisty_text(klic):
        return _beh_registru(request, chyba="Nejdřív zadejte a uložte API klíč registru vozidel.")
    limit = int(data["limit"]) if str(data.get("limit", "")).isdigit() else None  # zkušební běh na pár vozidel
    if not registr_hromadne.spust(db.get_bind(), klic, limit=limit):
        return _beh_registru(request, chyba="Doplňování už běží.")
    return _beh_registru(request)


@router.post("/nastaveni/registr/zastavit", response_class=HTMLResponse)
def registr_beh_zastav(request: Request):
    registr_hromadne.zastav()
    return _beh_registru(request)


@router.get("/nastaveni/zastupce")
def nastaveni_zastupce(adresa: str = ""):
    """#71: stažení instalátoru zástupce pro Windows (.bat s vyplněnou adresou serveru)."""
    try:
        obsah = zastupce.bat(adresa)
    except ChybaValidace as e:
        return _presmeruj_s_chybou("/nastaveni#zastupce", e)
    return Response(obsah, media_type="application/octet-stream",
                    headers={"Content-Disposition": f'attachment; filename="{zastupce.NAZEV_SOUBORU}"'})


def _kontext_katalogu(db) -> dict:
    """Panel Katalogy materiálu v Nastavení: katalogy, počty dílů a proč nejde smazat."""
    seznam = katalogy.seznam(db)
    return {"katalogy": seznam, "pocty_katalogu": {k.id: katalogy.pocet_polozek(db, k.id) for k in seznam},
            "nesmazatelne": {k.id: katalogy.duvod_proc_nesmazat(db, k) for k in seznam}}


@router.post("/katalogy")
async def katalog_novy(request: Request, db: DB):
    data = await _formular(request)
    try:
        katalog = katalogy.vytvor(db, data.get("nazev"))
    except ChybaValidace as e:
        db.rollback()
        return _presmeruj_s_chybou("/nastaveni#katalogy", e)
    return _presmeruj("/nastaveni#katalogy", f"Katalog „{katalog.nazev}“ založen.")


@router.post("/katalogy/{katalog_id}/prejmenovat")
async def katalog_prejmenovat(request: Request, db: DB, katalog_id: int):
    data = await _formular(request)
    try:
        katalog = katalogy.prejmenuj(db, katalog_id, data.get("nazev"))
    except ChybaValidace as e:
        db.rollback()
        return _presmeruj_s_chybou("/nastaveni#katalogy", e)
    return _presmeruj("/nastaveni#katalogy", f"Katalog přejmenován na „{katalog.nazev}“.")


@router.post("/katalogy/{katalog_id}/skryt")
async def katalog_skryt(request: Request, db: DB, katalog_id: int):
    """#150: skrýt / znovu zobrazit sklad v běžných nabídkách."""
    data = await _formular(request)
    skryty = data.get("skryty") == "1"
    try:
        katalog = katalogy.nastav_skryti(db, katalog_id, skryty)
    except ChybaValidace as e:
        db.rollback()
        return _presmeruj_s_chybou("/nastaveni#katalogy", e)
    return _presmeruj("/nastaveni#katalogy",
                      f"Katalog „{katalog.nazev}“ {'skrytý' if skryty else 'znovu zobrazený'}.")


@router.post("/katalogy/{katalog_id}/smazat")
def katalog_smazat(db: DB, katalog_id: int):
    nazev = katalogy.ziskej(db, katalog_id).nazev
    try:
        katalogy.smaz(db, katalog_id)
    except ChybaValidace as e:
        db.rollback()
        return _presmeruj_s_chybou("/nastaveni#katalogy", e)
    return _presmeruj("/nastaveni#katalogy", f"Katalog „{nazev}“ smazán.")


@router.post("/nastaveni", response_class=HTMLResponse)
async def nastaveni_uloz(request: Request, db: DB):
    form = await request.form()
    soubor = form.get("logo_soubor")
    data = {k: str(v) for k, v in form.items() if k != "logo_soubor"}
    for zaskrtavatko in ("platce_dph", "zaokrouhlit_hotovost", "sprava_dat", "statistiky"):
        data.setdefault(zaskrtavatko, "")
    try:
        nastaveni.uloz(db, data)
        # logo do horní lišty: nahrané nahradí původní, „smazat logo“ ho odebere
        if getattr(soubor, "filename", None):
            nastaveni.uloz_logo(db, await soubor.read(), soubor.content_type)
        elif data.get("smazat_logo"):
            nastaveni.uloz_logo(db, None, None)
    except ChybaValidace as e:
        db.rollback()
        return _stranka(request, "nastaveni.html", 422, aktivni="nastaveni", nast=nastaveni.nacti(db),
                        chyba=e, **_kontext_katalogu(db))
    return _presmeruj("/nastaveni?ulozeno=1")
