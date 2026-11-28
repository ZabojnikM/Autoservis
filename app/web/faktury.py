"""Webové stránky – faktury (rozděleno z routes.py, #233)."""
from datetime import date

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, Response

from app.models import FormaUhrady, TypDokladu, Uhrada
from app.services import pdf
from app.services import (
    ChybaValidace, cisty_text, faktury, nastaveni, polozky, vozidla,
    zakaznici,
    zakazky,
)
from app.web.sablony import templates
from app.web.spolecne import (
    DB, ROK_SEKUND, _davka, _formular, _najdi, _po_ulozeni, _presmeruj, _presmeruj_s_chybou, _status_formulare, _stranka, _udaje_listy, _vybrany_rok,
)

router = APIRouter()


# ---------------------------------------------------------------- faktury a vyúčtování

def _formular_vystaveni(request, db, zakazka, hodnoty, okno=False, chyba=None):
    """Formulář vystavení. Číslo dokladu (#15): předpona řady pevná, pořadové číslo předvyplněné dalším
    v řadě a přepisovatelné (i na volné číslo po smazaném dokladu)."""
    nast = nastaveni.nacti(db)
    typ = hodnoty.get("typ") or TypDokladu.FAKTURA
    vystaveni = zakazky.parsuj_datum(hodnoty.get("datum_vystaveni")) if isinstance(
        hodnoty.get("datum_vystaveni"), str) else hodnoty.get("datum_vystaveni")
    rok = (vystaveni or date.today()).year
    predpona = faktury.predpona_dokladu(db, typ, rok)
    if not cisty_text(hodnoty.get("poradi")):
        hodnoty = dict(hodnoty) | {"poradi": faktury.dalsi_cislo(db, typ, rok)[len(predpona):]}
    volna = [c.cislo for c in faktury.volna_cisla(db, typ, rok)]
    vozidlo, spz = _vozidlo_dokladu(db, hodnoty.get("vozidlo_id"), hodnoty.get("spz"))
    return _stranka(request, "faktura_vystavit.html", _status_formulare(okno, chyba), aktivni="faktury",
                    vozidlo=vozidlo, spz_dokladu=spz, ze_zakazky=bool(vozidlo and vozidlo.id == zakazka.vozidlo_id),
                    zakazka=zakazka, hodnoty=hodnoty, nast=nast,
                    rek=polozky.rekapitulace(zakazka), FormaUhrady=FormaUhrady, TypDokladu=TypDokladu,
                    okno=okno, chyba=chyba, predpona=predpona, volna=volna, predpona_volnych=len(predpona),
                    typ=typ, ucet_vyuctovani_ok=bool(faktury.iban_vyuctovani(nast)),
                    vzor_rady=nast.rada_faktura if typ == TypDokladu.FAKTURA else nast.rada_vyuctovani)


def _vozidlo_dokladu(db, vozidlo_id, spz):
    """#208: vozidlo v okně vystavení – podle vybraného id, jinak podle SPZ; SPZ mimo databázi zůstane textem."""
    vozidlo = _najdi(db, vozidla, vozidlo_id)
    if vozidlo is None and cisty_text(spz):
        vozidlo = vozidla.najdi_podle_spz(db, spz)
    return vozidlo, (vozidlo.spz if vozidlo else vozidla.normalizuj_spz(spz or "") or None)


@router.get("/doklad/odberatel", response_class=HTMLResponse)
def doklad_odberatel(request: Request, db: DB, vybrat_id: int | None = None, typ: str = TypDokladu.FAKTURA):
    """HTMX #208: panel Odběratel ve vystavení dokladu – vložený zákazník z databáze, nebo prázdný (Nový)."""
    hodnoty = {}
    if vybrat_id:
        k = zakaznici.ziskej(db, vybrat_id)
        hodnoty = {"zakaznik_id": k.id, "odb_nazev": k.nazev, "odb_ulice": k.ulice, "odb_mesto": k.mesto,
                   "odb_psc": k.psc, "odb_ico": k.ico, "odb_dic": k.dic}
    return _stranka(request, "_doklad_odberatel.html", hodnoty=hodnoty,
                    typ=typ if typ in TypDokladu.VSECHNY else TypDokladu.FAKTURA)


@router.get("/doklad/vozidlo", response_class=HTMLResponse)
def doklad_vozidlo(request: Request, db: DB, spz: str = "", vybrat_id: int | None = None, bez: str = "",
                   vozidlo_zakazky: str = ""):
    """HTMX #208: vozidlo dokladu – podle SPZ, vybrané z databáze (přepíše i pole SPZ), nebo Bez vozidla."""
    vozidlo, spz = (None, None) if bez else _vozidlo_dokladu(db, vybrat_id, spz)
    return _stranka(request, "_doklad_vozidlo_udaje.html", vozidlo=vozidlo, spz_dokladu=spz,
                    ze_zakazky=bool(vozidlo and str(vozidlo.id) == cisty_text(vozidlo_zakazky)),
                    prepsat_spz=bool(bez or vybrat_id))


@router.get("/zakazky/{zakazka_id}/vystavit", response_class=HTMLResponse)
def faktura_vystavit(request: Request, db: DB, zakazka_id: int, typ: str = TypDokladu.FAKTURA, okno: str = ""):
    zakazka = zakazky.ziskej(db, zakazka_id)
    if zakazka.platna_faktura:
        doklad = f"/faktury/{zakazka.platna_faktura.id}"
        return _po_ulozeni(bool(okno), doklad, doklad)
    return _formular_vystaveni(request, db, zakazka, faktury.vychozi_udaje(db, zakazka_id, typ), bool(okno))


@router.post("/zakazky/{zakazka_id}/vystavit", response_class=HTMLResponse)
async def faktura_vystavit_uloz(request: Request, db: DB, zakazka_id: int):
    data = await _formular(request)
    okno = bool(data.pop("okno", ""))
    try:
        faktura = faktury.vystav(db, zakazka_id, data)
    except ChybaValidace as e:
        db.rollback()
        return _formular_vystaveni(request, db, zakazky.ziskej(db, zakazka_id), data, okno, e)
    doklad = f"/faktury/{faktura.id}"
    return _po_ulozeni(okno, doklad, doklad,
                       zprava=f"Vystaven doklad {faktura.cislo} ({faktura.nazev_typu.lower()}), zakázka uzavřena.")


def _seznam_faktur(db, filtr, q, rok, typ):
    return faktury.seznam(db, filtr or faktury.VYCHOZI_FILTR, hledat=q, rok=rok, typ=typ or None)


KLIC_FILTRU_FAKTUR = "doklady"  # #183: poslední volba Vyúčtování / Faktury (cookie prohlížeče)


@router.get("/faktury", response_class=HTMLResponse)
def faktury_seznam(request: Request, db: DB, filtr: str = "", q: str = "", rok: str = "", typ: str = "",
                   razeni: str = "", od: str = "", vse_radky: str = ""):
    if not filtr:  # otevřeno z menu: naposledy zvolený typ dokladu, jinak výchozí
        ulozeny = request.cookies.get(KLIC_FILTRU_FAKTUR, "")
        filtr = ulozeny if ulozeny in faktury.FILTRY else faktury.VYCHOZI_FILTR
    rok_cislo, rok = _vybrany_rok(rok)
    seznam = _seznam_faktur(db, filtr, q, rok_cislo, typ)
    st = faktury.stranka(seznam, razeni=razeni, od=od, limit=_davka(vse_radky))
    odpoved = _stranka(request, "faktury_seznam.html", aktivni="faktury", faktury=st.polozky, stranka=st,
                       souhrn=faktury.souhrn(seznam), filtr=filtr, q=q, rok=rok, typ=typ,
                       filtry=faktury.FILTRY, TypDokladu=TypDokladu, nast=nastaveni.nacti(db),
                       roky=range(date.today().year, date.today().year - 6, -1))
    if filtr in faktury.FILTRY:
        odpoved.set_cookie(KLIC_FILTRU_FAKTUR, filtr, max_age=10 * ROK_SEKUND, path="/", samesite="lax")
    return odpoved


def _detail_faktury(request, db, faktura_id, chyba=None, status_code=200, **kontext):
    f = faktury.ziskej(db, faktura_id)
    nast = nastaveni.nacti(db)
    return _stranka(request, "faktura_detail.html", status_code, aktivni="faktury", f=f,
                    rek=faktury.rekapitulace(f), nast=nast, FormaUhrady=FormaUhrady,
                    qr=_qr(f, nast), chyba=chyba, dnes=date.today(), **kontext)


def _qr(f, nast):
    kod = faktury.spayd(f, nast)
    return faktury.qr_svg(kod) if kod else None


@router.get("/faktury/{faktura_id}", response_class=HTMLResponse)
def faktura_detail(request: Request, db: DB, faktura_id: int):
    return _detail_faktury(request, db, faktura_id)


def _kontext_tisku(db, faktura_id: int) -> dict:
    f = faktury.ziskej(db, faktura_id)
    nast = nastaveni.nacti(db)
    if f.typ == TypDokladu.VYUCTOVANI:  # #55: vlastní účet pro vyúčtování, nikdy účet pro faktury
        iban = faktury.iban_vyuctovani(nast)
        cislo_uctu = nast.ucet_vyuctovani if iban and "/" in nast.ucet_vyuctovani else ""
    else:
        iban, cislo_uctu = faktury.iban_servisu(nast), nast.cislo_uctu
    # VIN podle vozidla na dokladu (SPZ), ne podle zakázky – doklad může mít jiné vozidlo nebo žádné (#208)
    vuz = vozidla.najdi_podle_spz(db, f.spz) if f.spz else None
    return {"f": f, "rek": faktury.rekapitulace(f), "nast": nast, "iban": iban, "cislo_uctu": cislo_uctu,
            "qr": _qr(f, nast), "vin": vuz.vin if vuz else None}


@router.get("/faktury/{faktura_id}/tisk", response_class=HTMLResponse)
def faktura_tisk(request: Request, db: DB, faktura_id: int):
    return _stranka(request, "faktura_tisk.html", **_kontext_tisku(db, faktura_id))


@router.get("/faktury/{faktura_id}/pdf")
def faktura_pdf(request: Request, db: DB, faktura_id: int):
    """#189: doklad rovnou jako PDF (stejná šablona jako tisk); otevření se počítá jako vytištění (#167).

    #193: posílá se k zobrazení (inline), ne ke stažení – Chrome přes http stažení blokuje,
    zobrazení v nové záložce ne. Uložit jde z prohlížeče PDF; název souboru zůstává podle čísla dokladu."""
    kontext = _kontext_tisku(db, faktura_id)
    f = kontext["f"]
    if not pdf.dostupne():
        return _presmeruj(f"/faktury/{faktura_id}", pdf.NENI, chyba=True)
    html = templates.get_template("faktura_tisk.html").render(
        {"request": request, "lista": _udaje_listy(request), "pdf": True, **kontext})
    obsah = pdf.z_html(html)
    if not f.vytisteno:
        faktury.nastav_vytisteno(db, faktura_id, True)
    return Response(obsah, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{pdf.nazev_souboru(f.cislo)}"'})


@router.post("/faktury/{faktura_id}/vytisteno")
async def faktura_vytisteno(request: Request, db: DB, faktura_id: int):
    """#167: označit doklad jako vytištěný / nevytištěný (z detailu nebo z dotazu po tisku)."""
    data = await _formular(request)
    vytisteno = data.get("vytisteno") == "1"
    faktury.nastav_vytisteno(db, faktura_id, vytisteno)
    return _presmeruj(f"/faktury/{faktura_id}", "Označeno jako vytištěné." if vytisteno else "Označení tisku zrušeno.")


@router.post("/faktury/{faktura_id}/uhrazeno")
async def faktura_uhrazeno(request: Request, db: DB, faktura_id: int):
    """Vyúčtování: přepnout stav Uhrazeno ⇄ Neuhrazeno (#55)."""
    data = await _formular(request)
    uhrazeno = data.get("uhrazeno") == "1"
    try:
        faktury.nastav_uhrazeno(db, faktura_id, uhrazeno)
    except ChybaValidace as e:
        return _presmeruj_s_chybou(f"/faktury/{faktura_id}", e)
    return _presmeruj(f"/faktury/{faktura_id}", "Označeno jako uhrazené." if uhrazeno else "Označeno jako neuhrazené.")


def _formular_uhrady(request, db, faktura_id, hodnoty, okno=False, chyba=None):
    return _stranka(request, "uhrada_nova.html", _status_formulare(okno, chyba), aktivni="faktury",
                    f=faktury.ziskej(db, faktura_id), hodnoty=hodnoty, FormaUhrady=FormaUhrady, okno=okno,
                    chyba=chyba)


@router.get("/faktury/{faktura_id}/uhrady/nova", response_class=HTMLResponse)
def faktura_uhrada_nova(request: Request, db: DB, faktura_id: int, okno: str = ""):
    return _formular_uhrady(request, db, faktura_id, {}, okno=bool(okno))


@router.post("/faktury/{faktura_id}/uhrady", response_class=HTMLResponse)
async def faktura_uhrada(request: Request, db: DB, faktura_id: int):
    data = await _formular(request)
    okno = bool(data.pop("okno", ""))
    try:
        faktury.pridej_uhradu(db, faktura_id, data)
    except ChybaValidace as e:
        db.rollback()
        return _formular_uhrady(request, db, faktura_id, data, okno, e)
    return _po_ulozeni(okno, f"/faktury/{faktura_id}", zprava="Úhrada zapsána.")


@router.post("/uhrady/{uhrada_id}/smazat")
def uhrada_smazat(db: DB, uhrada_id: int):
    """Zrušení úhrady – zůstane v historii dokladu přeškrtnutá."""
    uhrada = db.get(Uhrada, uhrada_id)
    faktura_id = uhrada.faktura_id if uhrada else None
    try:
        faktura_id = faktury.zrus_uhradu(db, uhrada_id)
    except ChybaValidace as e:
        return _presmeruj_s_chybou(f"/faktury/{faktura_id}", e)
    return _presmeruj(f"/faktury/{faktura_id}", "Úhrada zrušena (zůstává v historii přeškrtnutá).")


@router.post("/faktury/{faktura_id}/smazat", response_class=HTMLResponse)
def faktura_smazat(request: Request, db: DB, faktura_id: int):
    """Smazání dokladu (#15): číslo zůstane v přehledu jako „Volné po smazání“, zakázka se znovu otevře."""
    doklad = faktury.ziskej(db, faktura_id)
    smazano = "smazána" if doklad.typ == TypDokladu.FAKTURA else "smazáno"
    nazev = doklad.nazev_typu
    cislo, zakazka_id = faktury.smaz(db, faktura_id)
    if zakazka_id:
        return _presmeruj(f"/zakazky/{zakazka_id}", f"{nazev} {cislo} {smazano}, zakázka je znovu otevřená.")
    return _presmeruj("/faktury", f"{nazev} {cislo} {smazano}.")
