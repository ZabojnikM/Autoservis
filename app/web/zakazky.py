"""Webové stránky – zakazky (rozděleno z routes.py, #233)."""
from datetime import datetime

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, Response

from app.models import StavZakazky, TypPolozky
from app.services import (
    ChybaValidace, cenik, cisty_text, hledani, katalogy, nastaveni, polozky, vozidla,
    zakaznici,
    zakazky,
)
from app.web.sablony import _mnozstvi
from app.web.spolecne import (
    DB, HISTORIE, PANEL_ZAKAZNIKA, POLE_ZAKAZKY, POLE_ZAKAZNIKA, _davka, _formular, _hodnoty_zakaznika, _iso, _karta_ceniku, _najdi, _nova_polozka_ceniku, _okno_ceniku, _po_ulozeni, _po_ulozeni_okna, _presmeruj, _presmeruj_s_chybou, _s_predponou, _status_formulare, _stranka, _vybrany_rok, _zapamatuj_katalog,
)

router = APIRouter()


# ---------------------------------------------------------------- úvodní stránka, hledání

@router.get("/")
def uvod():
    """Úvodní stránka = seznam zakázek (nástěnka byla zrušena)."""
    return _presmeruj("/zakazky")


@router.get("/hledat", response_class=HTMLResponse)
def hledat(request: Request, db: DB, q: str = ""):
    vysledek = hledani.hledej(db, q)
    presna = vozidla.najdi_podle_vin(db, q) if vozidla.je_vin(q) else vozidla.najdi_podle_spz(db, q)
    if presna:
        return _presmeruj(f"/vozidla/{presna.id}")
    # hledany_text = text v horním globálním hledání (filtry seznamů se do něj nepropisují)
    return _stranka(request, "hledat.html", vysledek=vysledek, q=q, hledany_text=q, hledany_vin=vozidla.je_vin(q))


@router.get("/zakazky", response_class=HTMLResponse)
def zakazky_seznam(request: Request, db: DB, stav: str = "", q: str = "", vse: str = "", rok: str = "",
                   razeni: str = "", od: str = "", vse_radky: str = ""):
    if stav == "vse":
        stav, vse = "", "1"
    filtr = stav or (None if vse else StavZakazky.ZALOZKA_OTEVRENE)
    rok_cislo, rok = _vybrany_rok(rok)
    st = zakazky.stranka(db, stav=filtr, hledat=q, razeni=razeni, od=od, limit=_davka(vse_radky), rok=rok_cislo)
    pocty = zakazky.pocty_podle_stavu(db, rok_cislo)
    return _stranka(
        request, "zakazky_seznam.html", aktivni="zakazky",
        zakazky=st.polozky, stranka=st, stav=stav, q=q, vse=vse, pocty=pocty, rok=rok, roky=zakazky.roky_prijeti(db),
        pocet_otevrenych=sum(pocty[s] for s in StavZakazky.ZALOZKA_OTEVRENE), pocet_vsech=sum(pocty.values()),
    )
PANEL_VOZIDLA = [p for p in vozidla.POLE if p not in ("spz", "motor", "poznamka")]
POLE_PRIJMU = POLE_ZAKAZKY + ["datum_prijeti"]


def _hodnoty_vozidla(vozidlo) -> dict:
    if not vozidlo:
        return {}
    return {"vozidlo_id": vozidlo.id, "spz": vozidlo.spz} | {
        f"v_{p}": _iso(getattr(vozidlo, p)) for p in PANEL_VOZIDLA}


def _otevrene_vozidla(db, vozidlo):
    if not vozidlo:
        return []
    return [z for z in vozidla.historie(db, vozidlo.id) if z.je_otevrena]


@router.get("/zakazky/nova", response_class=HTMLResponse)
def zakazka_nova(request: Request, db: DB, vozidlo_id: int | None = None, spz: str = "", vin: str = "",
                 zakaznik_id: int | None = None, okno: str = "", tachometr: str = ""):
    """Příjem vozidla – celá stránka, nebo s `okno=1` jen obsah okna (dialog nad seznamem).
    `spz` z hledání, které vypadá jako VIN (17 znaků), se bere jako VIN – nové vozidlo ho má v poli VIN."""
    if not vin and vozidla.je_vin(spz):
        vin, spz = spz, ""
    if vozidlo_id:
        vozidlo = vozidla.ziskej(db, vozidlo_id)
    else:
        vozidlo = vozidla.najdi_podle_vin(db, vin) if vin else vozidla.najdi_podle_spz(db, spz)
    zakaznik = zakaznici.ziskej(db, zakaznik_id) if zakaznik_id else (vozidlo.zakaznik if vozidlo else None)
    hodnoty = {"spz": vozidla.normalizuj_spz(spz), "v_vin": vozidla.normalizuj_vin(vin) or ""} \
        | _hodnoty_vozidla(vozidlo) | _hodnoty_zakaznika(zakaznik)
    hodnoty |= {"datum_prijeti": datetime.now().strftime("%Y-%m-%dT%H:%M")}
    if cisty_text(tachometr):  # stav km z Příjmu vozidel
        hodnoty["tachometr"] = cisty_text(tachometr)
    return _prijem(request, db, hodnoty, okno=bool(okno))


def _prijem(request, db, hodnoty, chyba=None, status_code=200, okno=False, zakazka=None):
    """Okno Zakázka – nová (příjem), nebo s `zakazka` úprava existující (stejné panely i ovládání)."""
    vozidlo = _najdi(db, vozidla, hodnoty.get("vozidlo_id"))
    otevrene = [z for z in _otevrene_vozidla(db, vozidlo) if not zakazka or z.id != zakazka.id]
    return _stranka(
        # v okně i chyba vrací 200 – HTMX jinak odpověď nezobrazí
        request, "zakazka_prijem.html", status_code=200 if okno else status_code, aktivni="zakazky",
        hodnoty=hodnoty, hz=hodnoty, vozidlo=vozidlo, zakaznik=_najdi(db, zakaznici, hodnoty.get("zakaznik_id")),
        otevrene=otevrene, cislo=zakazka.cislo if zakazka else zakazky.dalsi_cislo(db), chyba=chyba, okno=okno,
        zakazka=zakazka,
    )


def _data_panelu(data: dict) -> tuple[dict, dict, dict]:
    """Formulář okna Zakázka → (zakázka, vozidlo, zákazník) pro služby."""
    data_zakazky = {p: data[p] for p in POLE_PRIJMU if p in data}
    data_vozidla = {"vozidlo_id": data.get("vozidlo_id"), "spz": data.get("spz", "")} \
        | _s_predponou(data, "v_", PANEL_VOZIDLA)
    data_zakaznika = {"zakaznik_id": data.get("zakaznik_id"), "jako_novy": data.get("jako_novy")} \
        | _s_predponou(data, "k_", PANEL_ZAKAZNIKA)
    return data_zakazky, data_vozidla, data_zakaznika


@router.get("/zakazky/nova/vozidlo", response_class=HTMLResponse)
def zakazka_nova_vozidlo(request: Request, db: DB, spz: str = "", vybrat_id: int | None = None,
                         novy: str = ""):
    """HTMX: údaje vozidla v panelu příjmu.

    - po zadání SPZ: známé vozidlo se vyplní (a když panel zákazníka je prázdný, doplní se i jeho majitel),
      neznámé = nové vozidlo, rozepsané údaje zůstanou,
    - `vybrat_id`: vozidlo vložené z okna databáze vozidel (přepíše i pole SPZ),
    - `novy`: vyprázdní panel pro nové vozidlo.
    """
    parametry = dict(request.query_params)
    if novy:
        return _stranka(request, "_prijem_vozidlo.html", hodnoty={}, vozidlo=None, otevrene=[], prepsat_spz=True)
    vozidlo = vozidla.ziskej(db, vybrat_id) if vybrat_id else vozidla.najdi_podle_spz(db, spz)
    if vozidlo:
        hodnoty = _hodnoty_vozidla(vozidlo)
    else:  # nové vozidlo – necháme, co už je napsané (ale bez vazby na dříve vybrané vozidlo)
        hodnoty = {k: v for k, v in parametry.items() if k.startswith("v_")} | {"spz": vozidla.normalizuj_spz(spz)}
    panel_zakaznika_prazdny = not cisty_text(parametry.get("zakaznik_id")) and not any(
        cisty_text(parametry.get(f"k_{p}")) for p in PANEL_ZAKAZNIKA)
    majitel = vozidlo.zakaznik if vozidlo and panel_zakaznika_prazdny else None
    return _stranka(
        request, "_prijem_vozidlo.html", hodnoty=hodnoty, vozidlo=vozidlo,
        otevrene=_otevrene_vozidla(db, vozidlo), prepsat_spz=bool(vybrat_id),
        zakaznik_oob=bool(majitel), zakaznik=majitel, hz=_hodnoty_zakaznika(majitel),
    )


@router.get("/zakazky/nova/zakaznik", response_class=HTMLResponse)
def zakazka_nova_zakaznik(request: Request, db: DB, vybrat_id: int | None = None):
    """HTMX: panel zákazníka – vložený z okna databáze zákazníků, nebo prázdný (tlačítko Nový)."""
    zakaznik = zakaznici.ziskej(db, vybrat_id) if vybrat_id else None
    return _stranka(request, "_prijem_zakaznik.html", zakaznik=zakaznik, hz=_hodnoty_zakaznika(zakaznik))


@router.post("/zakazky/nova", response_class=HTMLResponse)
async def zakazka_nova_uloz(request: Request, db: DB):
    data = await _formular(request)
    try:
        nova = zakazky.prijem_z_formulare(db, *_data_panelu(data))
    except ChybaValidace as e:
        return _prijem(request, db, data, chyba=e, status_code=422, okno=bool(data.get("okno")))
    zprava = f"Zakázka {nova.cislo} založena."
    if data.get("okno"):
        return _po_ulozeni_okna(f"/zakazky/{nova.id}", zprava)
    return _presmeruj(f"/zakazky/{nova.id}", zprava)


@router.get("/zakazky/{zakazka_id}", response_class=HTMLResponse)
def zakazka_detail(request: Request, db: DB, zakazka_id: int):
    return _detail_zakazky(request, db, zakazka_id)


def _detail_zakazky(request, db, zakazka_id, chyba=None, hodnoty=None, status_code=200, **kontext):
    zakazka = zakazky.ziskej(db, zakazka_id)
    return _stranka(
        request, "zakazka_detail.html", status_code, aktivni="zakazky", zakazka=zakazka,
        rek=polozky.rekapitulace(zakazka), nast=nastaveni.nacti(db),
        nelze_smazat=zakazky.duvod_proc_nesmazat(zakazka),
        doklady=sorted(zakazka.faktury, key=lambda f: (f.datum_vystaveni, f.cislo)),
        vice_katalogu=len(katalogy.seznam(db)) > 1,
        chyba=chyba, hodnoty=hodnoty or {}, **kontext,
    )


@router.get("/zakazky/{zakazka_id}/cenik", response_class=HTMLResponse)
def zakazka_cenik(request: Request, db: DB, zakazka_id: int, q: str = "", okno: str = "", typ: str = "",
                  zdroj: str = "", katalog: str = ""):
    """`katalog` = přepnutí katalogu v okně (zapamatuje se), `zdroj=historie` = materiál z historie vozidla."""
    if zdroj == HISTORIE:  # #188: historie má vlastní okno Z historie
        return _okno_historie(request, db, zakazka_id, q, okno=bool(okno))
    if katalog:
        vybrany = katalogy.viditelny(db, katalog)
        return _zapamatuj_katalog(_okno_ceniku(request, db, zakazka_id, q, okno=bool(okno), typ=typ,
                                               katalog=vybrany), vybrany)
    return _okno_ceniku(request, db, zakazka_id, q, okno=bool(okno), typ=typ)


# ---------------------------------------------------------------- okno Z historie (#188)

def _okno_historie(request, db, zakazka_id, q="", okno=False, chyba=None, jen_vysledky=False):
    """Materiál dříve vydaný na vozidlo zakázky – zaškrtávátka, Vložit nahoře vloží všechno označené
    (díl z ceníku za aktuální cenu z ceníku)."""
    q = cisty_text(q) or ""
    zakazka = zakazky.ziskej(db, zakazka_id)
    return _stranka(request, "_historie_vysledky.html" if jen_vysledky else "zakazka_historie.html",
                    _status_formulare(okno, chyba), aktivni="zakazky", zakazka=zakazka, q=q, okno=okno,
                    radky_historie=polozky.historie_vozidla(db, zakazka, q), nast=nastaveni.nacti(db),
                    hlaseni_chyba=chyba)


@router.get("/zakazky/{zakazka_id}/historie", response_class=HTMLResponse)
def zakazka_historie(request: Request, db: DB, zakazka_id: int, q: str = "", okno: str = "", vysledky: str = ""):
    """`vysledky=1` = jen tabulka (HTMX hledání v okně)."""
    return _okno_historie(request, db, zakazka_id, q, okno=bool(okno), jen_vysledky=bool(vysledky))


@router.post("/zakazky/{zakazka_id}/historie/vlozit", response_class=HTMLResponse)
async def zakazka_historie_vlozit(request: Request, db: DB, zakazka_id: int):
    """Vložit z okna Z historie: zaškrtnuté řádky (vybrano[] = id řádku starší zakázky, mnozstvi_<id>)."""
    form = await request.form()
    okno = bool(form.get("okno"))
    vyber = [(v, form.get(f"mnozstvi_{v}") or "1") for v in form.getlist("vybrano") if str(v).isdigit()]
    try:
        radky = polozky.vloz_z_historie(db, zakazka_id, vyber)
    except ChybaValidace as e:
        db.rollback()
        return _okno_historie(request, db, zakazka_id, str(form.get("q") or ""), okno, chyba=str(e))
    zprava = f"Vloženo z historie: {len(radky)} " + ("díl" if len(radky) == 1 else "díly" if len(radky) < 5 else "dílů")
    if okno:
        return _po_ulozeni_okna(zprava=zprava)
    return _presmeruj(f"/zakazky/{zakazka_id}#polozky", zprava)


@router.post("/zakazky/{zakazka_id}/polozky/vlozit")
async def zakazka_vloz_polozky(request: Request, db: DB, zakazka_id: int):
    """Vložit z okna Přidat z ceníku: zapíše vybrané položky (polozka_ceniku_id[] + mnozstvi[]) najednou.
    Chyba = 422 s textem (okno zůstane otevřené), úspěch = obnovení stránky pod oknem."""
    form = await request.form()
    vyber = list(zip(form.getlist("polozka_ceniku_id"), form.getlist("mnozstvi")))
    try:
        radky = polozky.vloz_z_ceniku(db, zakazka_id, vyber)
    except ChybaValidace as e:
        return Response(str(e), status_code=422, media_type="text/plain; charset=utf-8")
    return _po_ulozeni_okna(zprava=f"Vloženo položek: {len(radky)}.")


def _formular_polozky(request, db, zakazka_id, hodnoty, okno=False, chyba=None, radek=None):
    """Okno ruční položky – stejná pole jako karta Materiál / Práce + množství (polozka_form.html).
    `radek` = úprava ručního řádku zakázky; chyba KodUzVCeniku nabídne existující položku ceníku."""
    return _stranka(request, "polozka_form.html", _status_formulare(okno, chyba), aktivni="zakazky",
                    zakazka=zakazky.ziskej(db, zakazka_id), hodnoty=hodnoty, nast=nastaveni.nacti(db),
                    okno=okno, chyba=chyba, radek=radek, katalogy=katalogy.viditelne(db),
                    existujici=chyba.polozka if isinstance(chyba, polozky.KodUzVCeniku) else None)


@router.get("/zakazky/{zakazka_id}/polozky/nova", response_class=HTMLResponse)
def zakazka_nova_polozka(request: Request, db: DB, zakazka_id: int, okno: str = "", typ: str = "", kod: str = ""):
    """`kod` = předvyplněný kód (tlačítko Nový v okně Přidat materiál převezme text hledání, #68)."""
    typ = typ if typ in TypPolozky.VSECHNY else TypPolozky.MATERIAL
    # nový materiál / nová práce: výchozí „i do ceníku“ (úprava ručního řádku zůstává „jen do zakázky“)
    hodnoty = _nova_polozka_ceniku(db, typ) | {"mnozstvi": "1", "ulozit_do_ceniku": "1"}
    if typ == TypPolozky.MATERIAL and cisty_text(kod):
        hodnoty["kod"] = cisty_text(kod)
    return _formular_polozky(request, db, zakazka_id, hodnoty, okno=bool(okno))


@router.get("/zakazky/{zakazka_id}/tisk", response_class=HTMLResponse)
def zakazka_tisk(request: Request, db: DB, zakazka_id: int):
    """Zakázkový list A4 (tisk / PDF přes prohlížeč)."""
    zakazka = zakazky.ziskej(db, zakazka_id)
    return _stranka(request, "zakazka_tisk.html", zakazka=zakazka, rek=polozky.rekapitulace(zakazka),
                    nast=nastaveni.nacti(db))


@router.post("/zakazky/{zakazka_id}/polozky", response_class=HTMLResponse)
async def zakazka_pridej_polozku(request: Request, db: DB, zakazka_id: int):
    """Přidání řádku – z ceníku (polozka_ceniku_id) nebo ručně.

    Z okna ceníku: okno zůstane otevřené s hláškou (lze přidávat dál); ruční položka z okna obnoví detail.
    """
    data = await _formular(request)
    okno = bool(data.pop("okno", ""))
    # „uložit i do ceníku“ → katalog zvolený ve formuláři, jinak hlavní (#70)
    data.setdefault("katalog_id", str(katalogy.vychozi(db).id))
    z_historie = cisty_text(data.get("z_historie"))
    z_ceniku = bool(cisty_text(data.get("polozka_ceniku_id")) or z_historie)
    try:
        if z_historie:
            radek = polozky.pridej_z_historie(db, zakazka_id, int(z_historie), mnozstvi=data.get("mnozstvi"))
        elif z_ceniku:
            radek = polozky.pridej_z_ceniku(db, zakazka_id, int(data["polozka_ceniku_id"]),
                                            mnozstvi=data.get("mnozstvi"))
        else:
            polozky.pridej_rucne(db, zakazka_id, data)
    except ChybaValidace as e:
        db.rollback()
        if z_ceniku:
            return _okno_ceniku(request, db, zakazka_id, data.get("q", ""), okno, chyba=str(e),
                                typ=data.get("typ_okna"), zdroj=HISTORIE if z_historie else None)
        return _formular_polozky(request, db, zakazka_id, data, okno, e)
    if z_ceniku and okno:  # Vložit v okně ceníku (#48): okno se zavře a detail zakázky obnoví s hláškou
        return _po_ulozeni_okna(zprava=f"Přidáno: {radek.nazev} ({_mnozstvi(radek.mnozstvi)} {radek.jednotka})")
    return _po_ulozeni(okno, f"/zakazky/{zakazka_id}#polozky", zprava="Položka přidána.")


@router.get("/polozky/{polozka_id}/upravit", response_class=HTMLResponse)
def polozka_upravit(request: Request, db: DB, polozka_id: int, okno: str = ""):
    """Úprava řádku zakázky: položka z ceníku se upravuje na své kartě (materiál / práce) – uloží se
    do ceníku i do řádku. Ruční položka (bez ceníku) má vlastní formulář. Množství se mění přímo v řádku."""
    radek = polozky.ziskej(db, polozka_id)
    vzor = cenik.najdi(db, radek.polozka_ceniku_id) if radek.polozka_ceniku_id else None
    if vzor:
        return _karta_ceniku(request, db, vzor, okno=bool(okno), radek=radek)
    nast = nastaveni.nacti(db)
    hodnoty = {"nazev": radek.nazev, "kod": radek.kod or "", "jednotka": radek.jednotka, "typ": radek.typ,
               "mnozstvi": _mnozstvi(radek.mnozstvi), "sazba_dph": _mnozstvi(radek.sazba_dph)} \
        | cenik.hodnoty_dvojice_cen("cena", radek.cena, radek.sazba_dph if nast.platce_dph else 0)
    return _formular_polozky(request, db, radek.zakazka_id, hodnoty, okno=bool(okno), radek=radek)


@router.post("/polozky/{polozka_id}/upravit", response_class=HTMLResponse)
async def polozka_upravit_uloz(request: Request, db: DB, polozka_id: int):
    data = await _formular(request)
    okno = bool(data.pop("okno", ""))
    data.setdefault("cena_s_dph", "")
    data.setdefault("katalog_id", str(katalogy.vychozi(db).id))
    try:
        radek = polozky.uprav(db, polozka_id, data)
    except ChybaValidace as e:
        db.rollback()
        radek = polozky.ziskej(db, polozka_id)
        return _formular_polozky(request, db, radek.zakazka_id, data, okno, e, radek=radek)
    return _po_ulozeni(okno, f"/zakazky/{radek.zakazka_id}#polozky", zprava=f"Položka „{radek.nazev}“ uložena.")


@router.post("/polozky/{polozka_id}/mnozstvi")
async def polozka_mnozstvi(request: Request, db: DB, polozka_id: int):
    """Změna množství přímo v řádku zakázky (pole v mřížce položek)."""
    data = await _formular(request)
    radek = polozky.ziskej(db, polozka_id)
    zpet = f"/zakazky/{radek.zakazka_id}#polozky"
    try:
        polozky.uprav(db, polozka_id, {"mnozstvi": data.get("mnozstvi", "")})
    except ChybaValidace as e:
        db.rollback()
        return _presmeruj_s_chybou(zpet, e)
    return _presmeruj(zpet)


@router.post("/polozky/{polozka_id}/cena")
async def polozka_cena(request: Request, db: DB, polozka_id: int):
    """#163: ruční cena za jednotku bez DPH přímo v řádku zakázky – uloží se jen do řádku, ceník se nemění."""
    data = await _formular(request)
    radek = polozky.ziskej(db, polozka_id)
    zpet = f"/zakazky/{radek.zakazka_id}#polozky"
    try:
        if radek.zakazka.platna_faktura:
            raise ChybaValidace("Zakázka je vyúčtovaná – řádek nejde změnit.")
        polozky.uprav(db, polozka_id, {"cena": data.get("cena", "")})
    except ChybaValidace as e:
        db.rollback()
        return _presmeruj_s_chybou(zpet, e)
    return _presmeruj(zpet)


@router.post("/polozky/{polozka_id}/smazat", response_class=HTMLResponse)
async def polozka_smazat(request: Request, db: DB, polozka_id: int):
    """Odebrání řádku – z detailu zakázky (přesměrování), nebo z okna Přidat z ceníku (okno zůstane)."""
    data = await _formular(request)
    radek = polozky.ziskej(db, polozka_id)
    nazev = radek.nazev
    try:
        zakazka_id = polozky.smaz(db, polozka_id)
    except ChybaValidace as e:
        if data.get("okno"):
            return _okno_ceniku(request, db, radek.zakazka_id, data.get("q", ""), True, chyba=str(e))
        return _presmeruj_s_chybou(f"/zakazky/{radek.zakazka_id}", e)
    if data.get("okno"):
        return _okno_ceniku(request, db, zakazka_id, data.get("q", ""), True, pridano=True,
                            zprava=f"Odebráno: {nazev}")
    return _presmeruj(f"/zakazky/{zakazka_id}#polozky", "Položka odebrána.")


@router.get("/zakazky/{zakazka_id}/upravit", response_class=HTMLResponse)
def zakazka_upravit(request: Request, db: DB, zakazka_id: int, okno: str = ""):
    """Úprava zakázky ve stejném okně jako příjem (Zákazník | Zakázka | Vozidlo) – jde změnit
    i vozidlo a datum přijetí. Celá stránka, nebo s `okno=1` jen obsah okna."""
    zakazka = zakazky.ziskej(db, zakazka_id)
    if zakazka.platna_faktura:
        doklad = f"/faktury/{zakazka.platna_faktura.id}"
        return _po_ulozeni(bool(okno), doklad, doklad)
    hodnoty = {p: _iso(getattr(zakazka, p)) for p in POLE_ZAKAZKY} \
        | {"datum_prijeti": zakazka.datum_prijeti.strftime("%Y-%m-%dT%H:%M")} \
        | _hodnoty_vozidla(zakazka.vozidlo) | _hodnoty_zakaznika(zakazka.zakaznik)
    if zakazka.tachometr is None:
        hodnoty["tachometr"] = ""
    return _prijem(request, db, hodnoty, okno=bool(okno), zakazka=zakazka)


@router.post("/zakazky/{zakazka_id}/upravit", response_class=HTMLResponse)
async def zakazka_upravit_uloz(request: Request, db: DB, zakazka_id: int):
    data = await _formular(request)
    okno = bool(data.get("okno"))
    try:
        if "spz" in data:  # okno Zakázka s panely (webové formuláře)
            zakazky.uprav_z_formulare(db, zakazka_id, *_data_panelu(data))
        else:  # jednoduchá úprava bez panelů (zákazník přes výběr id / „novy“ / „bez“)
            zmeny = {p: data.get(p, "") for p in POLE_ZAKAZKY}
            if "zakaznik_id" in data:
                zmeny["zakaznik_id"] = data["zakaznik_id"]
                zmeny["zakaznik_novy"] = _s_predponou(data, "k_", POLE_ZAKAZNIKA)
            zakazky.uprav(db, zakazka_id, zmeny)
    except ChybaValidace as e:
        db.rollback()
        return _prijem(request, db, data, chyba=e, status_code=422, okno=okno,
                       zakazka=zakazky.ziskej(db, zakazka_id))
    # z okna: zůstat na stránce, odkud se okno otevřelo
    return _po_ulozeni(okno, f"/zakazky/{zakazka_id}", zprava="Zakázka uložena.")


@router.post("/zakazky/{zakazka_id}/stav")
async def zakazka_stav(request: Request, db: DB, zakazka_id: int):
    data = await _formular(request)
    zpet = data.get("zpet") or f"/zakazky/{zakazka_id}"
    try:
        zakazka = zakazky.zmen_stav(db, zakazka_id, data.get("stav", ""), bez_dokladu=bool(data.get("bez_dokladu")))
    except ChybaValidace as e:
        return _presmeruj_s_chybou(zpet, e)
    zprava = f"Stav zakázky: {zakazka.nazev_stavu}."
    if zakazka.uzavrena_bez_dokladu:
        zprava = "Zakázka uzavřena bez dokladu."
    return _presmeruj(zpet, zprava)


@router.post("/zakazky/{zakazka_id}/smazat")
def zakazka_smazat(db: DB, zakazka_id: int):
    cislo = zakazky.ziskej(db, zakazka_id).cislo
    try:
        zakazky.smaz(db, zakazka_id)
    except ChybaValidace as e:
        return _presmeruj_s_chybou(f"/zakazky/{zakazka_id}", e)
    return _presmeruj("/zakazky", f"Zakázka {cislo} smazána.")
