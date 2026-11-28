"""Záložka Správa dat (#132): hromadné úpravy skladu a databáze, běžně skrytá – zapíná se v Nastavení.

Funkce:
- Sloučit díly (#130): návrh skupin, sloučení jedné skupiny a hromadně ze seznamu CSV.
- Import do skladu (#134, #137): seznam dílů od dodavatele do (nového) katalogu, staré karty se napárují a sloučí.
- Díly (#136): tabulka s filtrem a řazením, export a hromadné akce s náhledem, zálohou a zápisem do deníku –
  ceny (#138), přesun / kopie (#139), vyřadit / obnovit / smazat (#140), kódy a názvy (#142).
- Sklady (#140): přehled skladů a smazání celého skladu. Kontroly (#141), Přehledy (#143), Deník úprav (#136).
"""
from urllib.parse import quote

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, Response

from app.services import (ChybaValidace, NenalezenoError, cisty_text, hromadne, import_skladu, katalogy, kontroly,
                          nastaveni, slouceni, sprava, zalohy)
from app.web.spolecne import DB, _presmeruj, _stranka

VYPNUTO = "Záložka Správa dat je vypnutá. Zapnete ji v Nastavení (Správa dat)."


def _zapnuto(db: DB) -> None:
    if not nastaveni.nacti(db).sprava_dat:
        raise NenalezenoError(VYPNUTO)


router = APIRouter(prefix="/sprava-dat", dependencies=[Depends(_zapnuto)])
SLOUCENI = "/sprava-dat/slouceni-dilu"
IMPORT = "/sprava-dat/import-skladu"
NOVY_KATALOG = "Nový sklad"

# rozcestník: (adresa, název, popis) – sem přibývají další importy a hromadné úpravy
DILY = "/sprava-dat/dily"
SKLADY = "/sprava-dat/sklady"
FUNKCE = [
    (DILY, "Díly a hromadné úpravy",
     "Filtr a řazení dílů napříč sklady, export do Excelu, hromadná změna cen, přesun a kopie mezi sklady, "
     "vyřazení a mazání, úprava kódů a názvů."),
    (SKLADY, "Sklady", "Přehled skladů s počty dílů a smazání celého skladu (použité díly se přesunou)."),
    (SLOUCENI, "Sloučit díly",
     "Stejný díl vedený v ceníku pod více kódy sloučí do jednoho kódu – i ve starých zakázkách, ceny zůstanou."),
    (IMPORT, "Import do skladu",
     "Seznam dílů od dodavatele (např. UFI) nahraje do nového nebo zvoleného skladu a napojí k němu staré díly "
     "se stejným číslem."),
    ("/sprava-dat/kontroly", "Kontroly ceníku",
     "Duplicity, prodej pod nákupní cenou, nulové ceny, podezřelé kódy a řádky zakázek bez vazby na ceník."),
    ("/sprava-dat/prehledy", "Přehledy", "Nejpoužívanější díly, díly bez pohybu a marže podle skladu a výrobce."),
    ("/sprava-dat/denik", "Deník úprav", "Kdy a co se hromadně změnilo a ze které zálohy jde stav vrátit."),
]


@router.get("", response_class=HTMLResponse)
def rozcestnik(request: Request, db: DB):
    return _stranka(request, "sprava_dat.html", aktivni="sprava", funkce=FUNKCE)


# ---------------------------------------------------------------- Sloučit díly (#130)

def _zpet(q: str | None) -> str:
    q = cisty_text(q)
    return SLOUCENI + (f"?q={quote(q)}" if q else "")


def _zaloha() -> str:
    """Záloha databáze před sloučením; když nejde udělat, nic se neslučuje."""
    try:
        return zalohy.pred_sloucenim().name
    except zalohy.ChybaZalohy as e:
        raise ChybaValidace(f"Úprava neproběhla, protože se nepodařilo zálohovat databázi. {e}") from e


def _str(request, db, q="", plany=None, chyba=None):
    return _stranka(request, "sprava_slouceni.html", 400 if chyba else 200, aktivni="sprava", q=q,
                    skupiny=[] if plany is not None else slouceni.navrhy(db, q),
                    nalezene=[] if plany is not None else slouceni.karty_podle_hledani(db, q),
                    plany=plany, data_planu=slouceni.do_json(plany) if plany else "",
                    nast=nastaveni.nacti(db), chyba=chyba)


@router.get("/slouceni-dilu", response_class=HTMLResponse)
def slouceni_stranka(request: Request, db: DB, q: str = ""):
    return _str(request, db, q)


@router.post("/slouceni-dilu")
async def sluc(request: Request, db: DB):
    form = await request.form()
    q = form.get("q") or ""
    try:
        cil = cisty_text(form.get("cil"))
        if not cil or not cil.isdigit():
            raise ChybaValidace("Vyberte kartu, která zůstane (Ponechat).")
        ids = [int(v) for v in form.getlist("karty") if str(v).isdigit()]
        if len(set(ids) | {int(cil)}) < 2:
            raise ChybaValidace("Vyberte aspoň dvě karty ke sloučení.")
        zaloha = _zaloha()
        vysledek = slouceni.sluc(db, int(cil), ids, form.get("kod"), form.get("nazev"), form.get("cena"))
    except ChybaValidace as e:
        db.rollback()
        return _presmeruj(_zpet(q), str(e), chyba=True)
    sprava.zapis(db, "Sloučit díly", vysledek.text, vysledek.karet + 1, zaloha)
    return _presmeruj(_zpet(q), f"{vysledek.text} Záloha: {zaloha}")


@router.get("/slouceni-dilu/navrh.csv")
def navrh_csv(db: DB, q: str = ""):
    return Response(slouceni.navrh_csv(db, q), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="slouceni-dilu.csv"'})


@router.post("/slouceni-dilu/nahled", response_class=HTMLResponse)
async def nahled(request: Request, db: DB):
    form = await request.form()
    soubor = form.get("soubor")
    try:
        plany = slouceni.nacti_csv(db, await soubor.read() if hasattr(soubor, "read") else b"")
        if not plany:
            raise ChybaValidace("V seznamu není žádná skupina ke sloučení (sloupec Sloučit = ano).")
    except ChybaValidace as e:
        return _str(request, db, chyba=e)
    return _str(request, db, plany=plany)


@router.post("/slouceni-dilu/seznam")
async def sluc_seznam(request: Request, db: DB):
    form = await request.form()
    try:
        plany = slouceni.z_json(str(form.get("data_planu") or ""))
        vybrane = set(form.getlist("vybrano"))
        plany = [p for p in plany if p.skupina in vybrane]
        if not any(not p.chyba for p in plany):
            raise ChybaValidace("Není vybraná žádná skupina bez chyby.")
        zaloha = _zaloha()
    except ChybaValidace as e:
        return _presmeruj(SLOUCENI, str(e), chyba=True)
    souhrn = slouceni.sluc_seznam(db, plany)
    sprava.zapis(db, "Sloučit díly ze seznamu", souhrn.text + (" " + " ".join(souhrn.chyby) if souhrn.chyby else ""),
                 sum(v.karet for v in souhrn.slouceno), zaloha)
    zprava = f"{souhrn.text} Záloha: {zaloha}"
    if souhrn.chyby:
        zprava += " " + " ".join(souhrn.chyby[:3])
    return _presmeruj(SLOUCENI, zprava, chyba=bool(souhrn.chyby) and not souhrn.slouceno)


# ---------------------------------------------------------------- Import do skladu (#134)

def _str_importu(request, db, navrh=None, katalog="", novy_nazev=NOVY_KATALOG, chyba=None, rezim="obe",
                 parovani="cislo", chybejici=()):
    return _stranka(request, "sprava_import.html", 400 if chyba else 200, aktivni="sprava",
                    katalogy=katalogy.seznam(db), katalog=katalog, novy_nazev=novy_nazev, navrh=navrh,
                    data_navrhu=import_skladu.do_json(navrh) if navrh else "", nast=nastaveni.nacti(db), chyba=chyba,
                    rezim=rezim, parovani=parovani, rezimy=import_skladu.REZIMY, parovani_volby=import_skladu.PAROVANI,
                    chybejici=list(chybejici))


def _volba(hodnota, volby: dict) -> str:
    hodnota = str(hodnota or "")
    return hodnota if hodnota in volby else next(iter(volby))


def _cilovy_katalog(db, katalog: str, novy_nazev: str, zalozit: bool = False) -> int | None:
    """`katalog` = id existujícího, nebo „novy“ (založí se až při importu – v náhledu je None)."""
    if katalog == "novy":
        if not zalozit:
            katalogy._over_nazev(db, novy_nazev)
            return None
        return katalogy.vytvor(db, novy_nazev).id
    if not katalog.isdigit():
        raise ChybaValidace("Vyberte sklad (katalog), do kterého se má importovat.")
    return katalogy.ziskej(db, int(katalog)).id


@router.get("/import-skladu", response_class=HTMLResponse)
def import_stranka(request: Request, db: DB):
    return _str_importu(request, db, katalog="novy")


@router.post("/import-skladu/nahled", response_class=HTMLResponse)
async def import_nahled(request: Request, db: DB):
    form = await request.form()
    soubor, katalog = form.get("soubor"), str(form.get("katalog") or "")
    novy_nazev = cisty_text(form.get("novy_nazev")) or NOVY_KATALOG
    rezim, parovani = _volba(form.get("rezim"), import_skladu.REZIMY), _volba(form.get("parovani"), import_skladu.PAROVANI)
    try:
        katalog_id = _cilovy_katalog(db, katalog, novy_nazev)
        radky = import_skladu.nacti(await soubor.read() if hasattr(soubor, "read") else b"")
        navrh = import_skladu.navrh(db, radky, katalog_id, rezim, parovani)
    except ChybaValidace as e:
        return _str_importu(request, db, katalog=katalog, novy_nazev=novy_nazev, chyba=e, rezim=rezim, parovani=parovani)
    return _str_importu(request, db, navrh=navrh, katalog=katalog, novy_nazev=novy_nazev, rezim=rezim,
                        parovani=parovani, chybejici=import_skladu.chybejici(db, radky, katalog_id))


@router.post("/import-skladu")
async def import_uloz(request: Request, db: DB):
    form = await request.form()
    katalog = str(form.get("katalog") or "")
    novy_nazev = cisty_text(form.get("novy_nazev")) or NOVY_KATALOG
    try:
        navrh = import_skladu.z_json(str(form.get("data_navrhu") or ""))
        vybrane = {int(v) for v in form.getlist("vybrano") if str(v).isdigit()}
        radky = [r for r in navrh if r.index in vybrane and not r.chyba]
        vyradit = bool(form.get("vyradit_chybejici")) and katalog != "novy"
        if not radky and not vyradit:
            raise ChybaValidace("Není vybraný žádný díl k importu.")
        stare, nenalezene = {}, []
        for r in radky:
            ids = [int(v) for v in form.getlist(f"stare_{r.index}") if str(v).isdigit()]
            dalsi, chybi = import_skladu.najdi_stare_kody(db, form.get(f"dalsi_{r.index}"))
            nenalezene += chybi
            stare[r.index] = list(dict.fromkeys(ids + dalsi))
        if nenalezene:
            raise ChybaValidace(f"Ručně dopsané staré kódy nejsou v ceníku: {', '.join(nenalezene[:10])}. "
                                "Opravte je a nahrajte soubor znovu.")
        zaloha = _zaloha()
        katalog_id = _cilovy_katalog(db, katalog, novy_nazev, zalozit=True)
    except ChybaValidace as e:
        db.rollback()
        return _presmeruj(IMPORT, str(e), chyba=True)
    souhrn = import_skladu.importuj(db, radky, katalog_id, stare)
    vyrazeno = 0
    if vyradit:   # díly skladu, které v souboru nejsou (porovnává se s celým souborem, ne jen s vybranými řádky)
        ids = [p.id for p in import_skladu.chybejici(db, navrh, katalog_id)]
        if ids:
            vyrazeno = hromadne.proved(db, hromadne.planuj(db, "vyradit", ids, {}))
    text = souhrn.text + (f" Vyřazeno dílů chybějících v souboru: {vyrazeno}." if vyradit else "")
    sprava.zapis(db, "Import do skladu", text + (" " + " ".join(souhrn.chyby) if souhrn.chyby else ""),
                 souhrn.zalozeno + souhrn.aktualizovano + vyrazeno, zaloha)
    zprava = f"{text} Záloha: {zaloha}"
    if souhrn.chyby:
        zprava += " " + " ".join(souhrn.chyby[:3])
    return _presmeruj(IMPORT, zprava, chyba=bool(souhrn.chyby) and not (souhrn.zalozeno or souhrn.aktualizovano))


# ---------------------------------------------------------------- Díly a hromadné úpravy (#136, #138–#140, #142)

STRANKA_DILU = 200
PARAMETRY_AKCI = ["cil", "zpusob", "hodnota", "zaokrouhleni", "katalog_cil", "kolize", "operace", "predpona_kodu",
                  "pole", "hledat", "nahradit", "vzor"]


def _adresa_dilu(filtr: sprava.Filtr, **dalsi) -> str:
    from urllib.parse import urlencode
    parametry = filtr.parametry() | {k: v for k, v in dalsi.items() if v}
    return DILY + ("?" + urlencode(parametry) if parametry else "")


def _parametry_akce(form) -> dict:
    """Pole formuláře akce → parametry pro `hromadne.planuj` (cílový sklad a předpona mají ve formuláři
    vlastní jména, aby se nepletly s filtrem)."""
    par = {k: str(form.get(k) or "") for k in PARAMETRY_AKCI}
    par["katalog"], par["predpona"] = par.pop("katalog_cil"), par.pop("predpona_kodu")
    return par


@router.get("/dily", response_class=HTMLResponse)
def dily(request: Request, db: DB, vse: str = ""):
    filtr = sprava.Filtr.z_dat(request.query_params)
    try:
        radky = sprava.vyber(db, filtr)
        chyba = None
    except ChybaValidace as e:
        radky, chyba = [], e
    return _stranka(request, "sprava_dily.html", 400 if chyba else 200, aktivni="sprava", filtr=filtr,
                    radky=radky if vse else radky[:STRANKA_DILU], celkem=len(radky), vse=bool(vse),
                    katalogy=katalogy.seznam(db), predpony=sprava.predpony(db), nast=nastaveni.nacti(db),
                    akce_seznam=hromadne.AKCE, zaokrouhleni=hromadne.ZAOKROUHLENI, kolize=hromadne.KOLIZE,
                    sloupce=sprava.SLOUPCE_EXPORTU, vychozi_sloupce=sprava.VYCHOZI_SLOUPCE,
                    stavy=sprava.STAVY, pouziti=sprava.POUZITI, problemy=sprava.PROBLEMY, razeni=sprava.RAZENI,
                    adresa=lambda **kw: _adresa_dilu(filtr, **kw), chyba=chyba)


def _csv(obsah: bytes, nazev: str) -> Response:
    return Response(obsah, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{nazev}"'})


@router.get("/dily/export.csv")
def dily_export(request: Request, db: DB):
    filtr = sprava.Filtr.z_dat(request.query_params)
    return _csv(sprava.export_csv(sprava.vyber(db, filtr), request.query_params.getlist("sloupce")), "sklad.csv")


@router.post("/dily/nahled", response_class=HTMLResponse)
async def dily_nahled(request: Request, db: DB):
    form = await request.form()
    filtr = sprava.Filtr.z_dat(form)
    akce = str(form.get("akce") or "")
    try:
        ids = sprava.ids_z_vyberu(db, filtr, str(form.get("rozsah") or ""), form.getlist("id"))
        if akce == "export":
            vybrane = set(ids)
            radky = [r for r in sprava.vyber(db, filtr) if r.karta.id in vybrane]
            if len(radky) < len(vybrane):  # zaškrtnuté díly mimo aktuální filtr
                radky = [r for r in sprava.vyber(db, sprava.Filtr(stav="vse")) if r.karta.id in vybrane]
            return _csv(sprava.export_csv(radky, form.getlist("sloupce")), "sklad.csv")
        par = _parametry_akce(form)
        plan = hromadne.planuj(db, akce, ids, par)
    except ChybaValidace as e:
        return _presmeruj(_adresa_dilu(filtr), str(e), chyba=True)
    return _stranka(request, "sprava_nahled.html", aktivni="sprava", plan=plan, nazev_akce=hromadne.AKCE[akce],
                    kod_akce=akce, ids=",".join(map(str, ids)), par=par, filtr=filtr, zpet=_adresa_dilu(filtr),
                    cil="/sprava-dat/dily/provest")


def _ids(text) -> list[int]:
    return [int(i) for i in str(text or "").split(",") if i.strip().isdigit()]


@router.post("/dily/provest")
async def dily_provest(request: Request, db: DB):
    form = await request.form()
    filtr = sprava.Filtr.z_dat(form)
    akce = str(form.get("akce") or "")
    # parametry akce mají v náhledu předponu p_ (filtr má vlastní pole „katalog“)
    par = {k: str(form.get("p_" + k) or "") for k in ("cil", "zpusob", "hodnota", "zaokrouhleni", "katalog", "kolize",
                                                      "operace", "predpona", "pole", "hledat", "nahradit", "vzor")}
    try:
        plan = hromadne.planuj(db, akce, _ids(form.get("ids")), par)
        if not plan.provede_se:
            raise ChybaValidace("Není co změnit – všechny vybrané díly by se přeskočily.")
        zaloha = _zaloha()
        pocet = hromadne.proved(db, plan)
    except ChybaValidace as e:
        db.rollback()
        return _presmeruj(_adresa_dilu(filtr), str(e), chyba=True)
    text = f"{hromadne.AKCE[akce]}: {plan.popis}. Změněno dílů {pocet}"
    if plan.preskoci_se:
        text += f", přeskočeno {len(plan.preskoci_se)}"
    sprava.zapis(db, hromadne.AKCE[akce], text, pocet, zaloha)
    return _presmeruj(_adresa_dilu(filtr), f"{text}. Záloha: {zaloha}")


# ---------------------------------------------------------------- Sklady (#140)

@router.get("/sklady", response_class=HTMLResponse)
def sklady(request: Request, db: DB):
    vsechny = sprava.vyber(db, sprava.Filtr(stav="vse"))
    prehled = []
    for k in katalogy.seznam(db):
        radky = [r for r in vsechny if r.karta.katalog_id == k.id]
        prehled.append({"katalog": k, "dilu": len(radky), "aktivnich": sum(r.karta.aktivni for r in radky),
                        "pouzitych": sum(1 for r in radky if r.pouzito)})
    return _stranka(request, "sprava_sklady.html", aktivni="sprava", prehled=prehled, katalogy=katalogy.seznam(db))


@router.post("/sklady/{katalog_id}/nahled", response_class=HTMLResponse)
async def sklad_smazat_nahled(request: Request, db: DB, katalog_id: int):
    form = await request.form()
    par = {"katalog": str(form.get("katalog_cil") or ""), "vyradit": "1" if form.get("vyradit") else ""}
    try:
        plan = hromadne.planuj_smazani_skladu(db, katalog_id, par["katalog"], bool(par["vyradit"]))
    except ChybaValidace as e:
        return _presmeruj(SKLADY, str(e), chyba=True)
    return _stranka(request, "sprava_nahled.html", aktivni="sprava", plan=plan, nazev_akce="Smazat sklad",
                    kod_akce="smazat_sklad", ids="", par=par, filtr=None, zpet=SKLADY,
                    cil=f"/sprava-dat/sklady/{katalog_id}/smazat")


@router.post("/sklady/{katalog_id}/smazat")
async def sklad_smazat(request: Request, db: DB, katalog_id: int):
    form = await request.form()
    try:
        plan = hromadne.planuj_smazani_skladu(db, katalog_id, str(form.get("p_katalog") or ""),
                                              bool(form.get("p_vyradit")))
        if plan.preskoci_se:
            raise ChybaValidace("Některé díly nejde přesunout – sklad se nesmazal.")
        zaloha = _zaloha()
        pocet = hromadne.proved(db, plan)
        hromadne.smaz_sklad(db, katalog_id)
    except ChybaValidace as e:
        db.rollback()
        return _presmeruj(SKLADY, str(e), chyba=True)
    text = f"{plan.popis[0].upper()}{plan.popis[1:]}. Dílů {pocet}"
    sprava.zapis(db, "Smazat sklad", text, pocet, zaloha)
    return _presmeruj(SKLADY, f"{text}. Záloha: {zaloha}")


# ---------------------------------------------------------------- Deník úprav (#136)

@router.get("/denik", response_class=HTMLResponse)
def denik(request: Request, db: DB):
    return _stranka(request, "sprava_denik.html", aktivni="sprava", zaznamy=sprava.denik(db))


# ---------------------------------------------------------------- Kontroly (#141) a přehledy (#143)

@router.get("/kontroly", response_class=HTMLResponse)
def kontroly_stranka(request: Request, db: DB):
    return _stranka(request, "sprava_kontroly.html", aktivni="sprava", kontroly=kontroly.prehled_kontrol(db))


@router.get("/kontroly/bez-vazby", response_class=HTMLResponse)
def bez_vazby_stranka(request: Request, db: DB):
    return _stranka(request, "sprava_bez_vazby.html", aktivni="sprava", skupiny=kontroly.bez_vazby(db))


@router.post("/kontroly/bez-vazby")
async def bez_vazby_napoj(request: Request, db: DB):
    form = await request.form()
    kody = [str(k) for k in form.getlist("kod")]
    try:
        if not kody:
            raise ChybaValidace("Zaškrtněte kódy, které se mají napojit.")
        zaloha = _zaloha()
    except ChybaValidace as e:
        return _presmeruj("/sprava-dat/kontroly/bez-vazby", str(e), chyba=True)
    pocet = kontroly.napoj(db, kody)
    text = f"Napojeno řádků zakázek na ceník: {pocet} (kódů {len(kody)})."
    sprava.zapis(db, "Napojit řádky bez vazby", text, pocet, zaloha)
    return _presmeruj("/sprava-dat/kontroly/bez-vazby", f"{text} Záloha: {zaloha}")


@router.get("/prehledy", response_class=HTMLResponse)
def prehledy_stranka(request: Request, db: DB):
    return _stranka(request, "sprava_prehledy.html", aktivni="sprava", **kontroly.prehledy(db))
