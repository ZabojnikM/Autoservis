"""Webové stránky – cenik (rozděleno z routes.py, #233)."""
from urllib.parse import quote

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.models import TypPolozky
from app.services import import_lkq
from app.services import (
    ChybaValidace, cenik, cisty_text, katalogy, nastaveni, polozky, zakazky,
)
from app.web.spolecne import (
    DB, HISTORIE, POLE_CENIKU, _adresa_ceniku, _davka, _formular, _formular_ceniku, _karta_ceniku, _katalog, _nova_polozka_ceniku, _okno_ceniku, _po_ulozeni, _presmeruj, _status_formulare, _stranka, _typ_ceniku, _vysledky_okna, _zapamatuj_katalog,
)

router = APIRouter()


# ceny jako dvojice polí bez DPH / s DPH (+ které pole uživatel psal naposledy)
POLE_CEN = ["cena_s", "cena_zdroj", "cena_s_dph", "nakupni_cena", "nakupni_cena_s", "nakupni_cena_zdroj"]


def _data_ceniku(data: dict) -> dict:
    vysledek = {p: data.get(p, "") for p in POLE_CENIKU + POLE_CEN if p in data or p in POLE_CENIKU}
    if cisty_text(data.get("katalog_id")):  # katalog z formuláře – nový materiál i přesun při úpravě (#124)
        vysledek["katalog_id"] = data["katalog_id"]
    return vysledek


def _seznam_ceniku(request, db, typ, q, neaktivni, razeni, od, vse_radky, zvyraznit):
    material = typ == TypPolozky.MATERIAL
    katalog = _katalog(request, db) if material else None
    st = cenik.stranka(db, q, typ=typ, jen_aktivni=not neaktivni, razeni=razeni, od=od, limit=_davka(vse_radky),
                       katalog_id=katalog.id if katalog else None)
    sablona = "cenik_seznam.html" if material else "prace_seznam.html"
    return _stranka(request, sablona, aktivni="cenik" if material else "prace", q=q, typ=typ,
                    neaktivni=neaktivni, polozky=st.polozky, stranka=st, nast=nastaveni.nacti(db), zvyraznit=zvyraznit,
                    katalog=katalog, katalogy=katalogy.viditelne(db) if material else [],
                    pouziti=cenik.pocty_pouziti(db, (p.id for p in st.polozky)) if material else {})


@router.get("/cenik", response_class=HTMLResponse)
def cenik_seznam(request: Request, db: DB, q: str = "", typ: str = "", neaktivni: str = "",
                 razeni: str = "", od: str = "", vse_radky: str = "", zvyraznit: str = "", katalog: str = ""):
    if typ == TypPolozky.PRACE:  # starší odkazy na záložku Práce
        return RedirectResponse(f"/prace?{request.url.query}", status_code=303)
    if katalog:  # přepínač katalogů: výběr si zapamatuje prohlížeč (cookie), pak seznam bez parametru
        vybrany = katalogy.viditelny(db, katalog)
        return _zapamatuj_katalog(RedirectResponse("/cenik" + (f"?q={quote(q)}" if q else ""), status_code=303),
                                  vybrany)
    return _seznam_ceniku(request, db, TypPolozky.MATERIAL, q, neaktivni, razeni, od, vse_radky, zvyraznit)


@router.get("/prace", response_class=HTMLResponse)
def prace_seznam(request: Request, db: DB, q: str = "", neaktivni: str = "",
                 razeni: str = "", od: str = "", vse_radky: str = "", zvyraznit: str = ""):
    return _seznam_ceniku(request, db, TypPolozky.PRACE, q, neaktivni, razeni, od, vse_radky, zvyraznit)


# ---------------------------------------------------------------- import dodacího listu LKQ (#8)

def _okno_importu(request, db, okno=False, zakazka_id=None, dodaci_list=None, chyba=None, katalog_id=None):
    """Okno importu: bez `dodaci_list` výběr souboru, s ním náhled spárovaný s katalogem.
    Importuje se do katalogu vybraného při otevření okna (`katalog_id` jde dál ve formuláři, #62)."""
    zakazka = zakazky.ziskej(db, zakazka_id) if zakazka_id else None
    katalog = katalogy.podle_id(db, katalog_id) if katalog_id else _katalog(request, db)
    return _stranka(request, "import_lkq.html", _status_formulare(okno, chyba), aktivni="zakazky" if zakazka else "cenik",
                    okno=okno, zakazka=zakazka, dodaci_list=dodaci_list, chyba=chyba, nast=nastaveni.nacti(db),
                    katalog=katalog,
                    radky=import_lkq.nahled(db, dodaci_list, katalog.id) if dodaci_list else [],
                    data_listu=import_lkq.do_json(dodaci_list) if dodaci_list else "")


def _id_zakazky(hodnota) -> int | None:
    hodnota = cisty_text(str(hodnota or ""))
    return int(hodnota) if hodnota and hodnota.isdigit() else None


@router.get("/cenik/import", response_class=HTMLResponse)
def import_lkq_okno(request: Request, db: DB, okno: str = "", zakazka_id: str = ""):
    return _okno_importu(request, db, bool(okno), _id_zakazky(zakazka_id))


@router.post("/cenik/import/nahled", response_class=HTMLResponse)
async def import_lkq_nahled(request: Request, db: DB):
    form = await request.form()
    okno, zakazka_id = bool(form.get("okno")), _id_zakazky(form.get("zakazka_id"))
    soubor, katalog_id = form.get("soubor"), form.get("katalog_id")
    try:
        dodaci_list = import_lkq.nacti_soubor(await soubor.read() if hasattr(soubor, "read") else b"")
    except ChybaValidace as e:
        return _okno_importu(request, db, okno, zakazka_id, chyba=e, katalog_id=katalog_id)
    return _okno_importu(request, db, okno, zakazka_id, dodaci_list, katalog_id=katalog_id)


@router.post("/cenik/import", response_class=HTMLResponse)
async def import_lkq_uloz(request: Request, db: DB):
    form = await request.form()
    okno, zakazka_id = bool(form.get("okno")), _id_zakazky(form.get("zakazka_id"))
    katalog = katalogy.podle_id(db, form.get("katalog_id")) if form.get("katalog_id") else _katalog(request, db)
    try:
        dodaci_list = import_lkq.z_json(str(form.get("data_listu") or ""))
    except ChybaValidace as e:
        return _okno_importu(request, db, okno, zakazka_id, chyba=e, katalog_id=katalog.id)
    vybrane = [int(v) for v in form.getlist("vybrano") if str(v).isdigit()]
    try:
        souhrn = import_lkq.importuj(db, dodaci_list, vybrane, zakazka_id, katalog_id=katalog.id)
    except ChybaValidace as e:
        return _okno_importu(request, db, okno, zakazka_id, dodaci_list, chyba=e, katalog_id=katalog.id)
    cil = f"/zakazky/{zakazka_id}" if zakazka_id else "/cenik"
    # z okna: obnovit stránku pod oknem (zakázka / ceník) a ukázat souhrn
    return _po_ulozeni(okno, cil, None, zprava=souhrn.text)


@router.get("/cenik/vyber", response_class=HTMLResponse)
def cenik_vyber(request: Request, db: DB, q: str = "", zakazka_id: int = 0, okno: str = "", typ: str = "",
                zdroj: str = ""):
    """HTMX: hledání v okně Přidat z ceníku (prázdné hledání = začátek ceníku / celá historie vozidla)."""
    q = cisty_text(q) or ""
    typ = _typ_ceniku(typ)
    historie = typ == TypPolozky.MATERIAL and zdroj == HISTORIE
    zakazka = zakazky.ziskej(db, zakazka_id) if historie else None
    return _stranka(request, "_cenik_vyber_vysledky.html", q=q, zakazka_id=zakazka_id, okno=bool(okno), typ_okna=typ,
                    zakazka=zakazka, historie=historie,
                    **_vysledky_okna(db, zakazka, q, typ, _katalog(request, db), historie),
                    nast=nastaveni.nacti(db))


def _z_ceniku(hodnota) -> int | None:
    """Id zakázky, z jejíhož okna Přidat z ceníku se karta položky otevřela (tlačítko Upravit)."""
    hodnota = cisty_text(hodnota)
    return int(hodnota) if hodnota and hodnota.isdigit() else None


@router.get("/cenik/nova", response_class=HTMLResponse)
def cenik_nova(request: Request, db: DB, typ: str = "material", okno: str = ""):
    typ = typ if typ in TypPolozky.VSECHNY else TypPolozky.MATERIAL
    return _formular_ceniku(request, db, None, _nova_polozka_ceniku(db, typ), okno=bool(okno))


@router.get("/prace/nova", response_class=HTMLResponse)
def prace_nova(request: Request, db: DB, okno: str = ""):
    return _formular_ceniku(request, db, None, _nova_polozka_ceniku(db, TypPolozky.PRACE), okno=bool(okno))


@router.post("/cenik/nova", response_class=HTMLResponse)
@router.post("/prace/nova", response_class=HTMLResponse)
async def cenik_nova_uloz(request: Request, db: DB):
    data = await _formular(request)
    if request.url.path.startswith("/prace"):
        data["typ"] = TypPolozky.PRACE
    elif not data.get("typ"):
        data["typ"] = TypPolozky.MATERIAL
    okno = bool(data.get("okno"))
    try:
        nova = cenik.vytvor(db, _data_ceniku(data))
    except ChybaValidace as e:
        db.rollback()
        return _formular_ceniku(request, db, None, data, okno, e)
    typ = data.get("typ", "material")
    if data.get("dalsi") and okno:  # okno zůstane otevřené s prázdným formulářem (ve stejném katalogu)
        return _formular_ceniku(request, db, None, _nova_polozka_ceniku(db, typ)
                                | {"katalog_id": str(nova.katalog_id or "")}, okno,
                                zprava=f"Uloženo: {nova.nazev}")
    adresa = _adresa_ceniku(nova.typ)
    if data.get("dalsi"):
        return _presmeruj(f"{adresa}/nova", f"Uloženo: {nova.nazev}")
    # nová položka: seznam vyfiltrovaný na ni a řádek zvýrazněný (jinak by byla někde v abecedě)
    seznam = f"{adresa}?q={quote(nova.nazev)}&zvyraznit={nova.id}"
    return _po_ulozeni(okno, seznam, seznam, zprava=f"Položka ceníku „{nova.nazev}“ uložena.")


@router.get("/cenik/{polozka_id}/upravit", response_class=HTMLResponse)
@router.get("/prace/{polozka_id}/upravit", response_class=HTMLResponse)
def cenik_upravit(request: Request, db: DB, polozka_id: int, okno: str = "", z_ceniku: str = "", q: str = ""):
    """Karta položky ceníku. `z_ceniku` = id zakázky, když se otevřela tlačítkem Upravit v okně Přidat z ceníku
    (po uložení / Zpět se okno ceníku vrátí s hledáním `q`)."""
    return _karta_ceniku(request, db, cenik.ziskej(db, polozka_id), okno=bool(okno), z_ceniku=_z_ceniku(z_ceniku), q=q)


@router.post("/cenik/{polozka_id}/upravit", response_class=HTMLResponse)
@router.post("/prace/{polozka_id}/upravit", response_class=HTMLResponse)
async def cenik_upravit_uloz(request: Request, db: DB, polozka_id: int):
    data = await _formular(request)
    okno = bool(data.get("okno"))
    z_ceniku, q = _z_ceniku(data.get("z_ceniku")), data.get("q", "")
    radek = polozky.ziskej(db, int(data["radek"])) if cisty_text(data.get("radek", "")) else None
    try:
        polozka = cenik.uprav(db, polozka_id, _data_ceniku(data) | {"aktivni": data.get("aktivni", "")})
    except ChybaValidace as e:
        db.rollback()
        return _formular_ceniku(request, db, cenik.ziskej(db, polozka_id), data, okno, e, z_ceniku=z_ceniku, q=q,
                                radek=radek)
    if radek:  # karta otevřená úpravou řádku zakázky → změny i do řádku, pak zpět na zakázku
        zpet = f"/zakazky/{radek.zakazka_id}#polozky"
        try:
            polozky.prevezmi_z_ceniku(db, radek.id)
        except ChybaValidace as e:
            db.rollback()
            return _po_ulozeni(okno, zpet, zprava=f"Karta uložena, ale řádek zakázky ne: {e}")
        return _po_ulozeni(okno, zpet, zprava=f"Položka „{polozka.nazev}“ uložena v ceníku i na zakázce.")
    if okno and z_ceniku:  # karta otevřená z okna Přidat z ceníku → zpět do něj
        return _okno_ceniku(request, db, z_ceniku, q, okno=True, zprava=f"Karta uložena: {polozka.nazev}",
                            typ=polozka.typ)
    return _po_ulozeni(okno, _adresa_ceniku(cenik.ziskej(db, polozka_id).typ), zprava="Položka ceníku uložena.")


@router.post("/cenik/{polozka_id}/smazat")
@router.post("/prace/{polozka_id}/smazat")
async def cenik_smazat(request: Request, db: DB, polozka_id: int):
    """Smazání z ceníku; `zpet` = adresa seznamu, odkud se okno otevřelo (zachová hledání a filtr)."""
    data = await _formular(request)
    polozka = cenik.ziskej(db, polozka_id)
    nazev, adresa = polozka.nazev, _adresa_ceniku(polozka.typ)
    cenik.smaz(db, polozka_id)
    zpet = data.get("zpet") or ""
    return _presmeruj(zpet if zpet.startswith(("/cenik", "/prace")) else adresa, f"Položka ceníku „{nazev}“ smazána.")
