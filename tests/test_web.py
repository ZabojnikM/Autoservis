"""Testy webu – jednotné ovládání, klávesnice, seznamy a obecné stránky (rozděleno z test_web.py, #233)."""
import re
from datetime import date
from tests.web_pomucky import client, _se_skriptem, _prijem, _zakazka_s_polozkou
from tests.web_pomucky import ucet_pro_vyuctovani  # noqa: F401 – fixtury (autouse)


def test_vsechny_stranky_bez_dat():
    for url in ["/", "/zakazky", "/zakazky?vse=1", "/zakazky/nova", "/vozidla", "/zakaznici",
                "/vozidla/nove", "/zakaznici/novy", "/hledat?q=nic"]:
        r = client.get(url)
        assert r.status_code == 200, url


def test_neexistujici_zaznam_404():
    assert client.get("/zakazky/999").status_code == 404
    assert client.get("/vozidla/999").status_code == 404


# ---------------------------------------------------------------- jednotné drobnosti: hlášky, potvrzení, úhrada v okně

def test_hlaska_po_ulozeni_v_cookie():
    from urllib.parse import unquote
    r = client.post("/vozidla/nove", data={"spz": "3C33333", "zakaznik_id": "bez"}, follow_redirects=False)
    assert r.status_code == 303 and unquote(r.cookies.get("zprava")) == "Vozidlo 3C33333 založeno."
    loc = r.headers["location"]
    r = client.post(f"{loc}/upravit", data={"spz": "3C33333", "okno": "1", "zakaznik_id": "bez"})
    assert r.status_code == 204 and unquote(r.cookies.get("zprava")) == "Vozidlo uloženo."
    r = client.post(f"{loc}/smazat", follow_redirects=False)
    assert unquote(r.cookies.get("zprava")) == "Vozidlo smazáno."
    # chyba hlášku nenastaví
    r = client.post("/vozidla/nove", data={"spz": "", "zakaznik_id": "bez"}, follow_redirects=False)
    assert r.status_code == 422 and "zprava" not in r.cookies
    # stránka má místo pro hlášku a okno potvrzení
    stranka = client.get("/zakazky").text
    assert 'id="zprava"' in stranka and 'id="okno-potvrzeni"' in stranka


def test_mazani_s_potvrzenim_v_okne_aplikace():
    r = client.post("/vozidla/nove", data={"spz": "4C44444", "zakaznik_id": "bez"}, follow_redirects=False)
    detail = client.get(r.headers["location"]).text
    assert 'data-potvrdit="Opravdu smazat vozidlo 4C44444?' in detail and "confirm(" not in detail
    for url in ["/zakazky", "/vozidla", "/zakaznici", "/cenik", "/faktury", "/nastaveni"]:
        assert 'onsubmit="return confirm' not in client.get(url).text, url

def test_tlacitko_zpet_je_vsude_stejne():
    # jednotné „Zpět“ – žádné „Zpět na seznam“, „Zpět do ceníku“…
    from pathlib import Path
    sablony = Path(__file__).resolve().parent.parent / "app" / "web" / "templates"
    for soubor in sablony.glob("*.html"):
        assert not re.search(r">\s*Zpět \w", soubor.read_text(encoding="utf-8")), soubor.name


def test_kontrola_spz_a_prodej_pod_nakupem_v_sablonach():
    """#33: pole SPZ mají kontrolu tvaru (dotaz v prohlížeči), materiál má upozornění na prodej pod nákupní cenou."""
    assert "data-kontrola-spz" in client.get("/vozidla/nove").text
    assert "data-kontrola-spz" in client.get("/zakazky/nova").text
    assert "data-pod-nakupem" in client.get("/cenik/nova").text


def test_seznamy_jeden_klik_bez_uprav_v_radku():
    """Seznamy otevírají detail jedním klikem. Zakázka se upravuje z detailu."""
    loc = _prijem(spz="8S88888").headers["location"].split("?")[0]
    zid = loc.rsplit("/", 1)[1]
    for url in ["/zakazky", "/vozidla", "/zakaznici", "/cenik", "/prace", "/faktury"]:
        text = client.get(url).text
        akce = text.split('<aside class="akce')[1].split("</aside>")[0] if '<aside class="akce' in text else ""
        assert 'data-radek="otevrit"' not in akce and 'data-radek="upravit"' not in akce, url
    zakazky = client.get("/zakazky").text
    assert "klik-otevre" in zakazky and f'data-otevrit="{loc}"' in zakazky
    assert "upravit-radek" not in zakazky and "akce-radku" not in zakazky
    assert f'href="/zakazky/{zid}/upravit" role="button"' in client.get(loc).text
    # vozidla a zákazníci: Upravit v řádku není (upravuje se z detailu)
    for url in ["/vozidla", "/zakaznici"]:
        text = client.get(url).text
        assert "klik-otevre" in text and "upravit-radek" not in text, url


def test_audit_49_popisky_a_tlacitka():
    """#49: přístupné popisky Ceník / Nový, Načíst podle VIN / IČO, Nové vozidlo / Nový zákazník,
    v kartě ceníku Uložit a Uložit a další u sebe, Zpět oddělené; nápověda seznamů podle chování."""
    loc = _prijem(spz="4A44444").headers["location"].split("?")[0]
    detail = client.get(loc).text
    assert 'aria-label="Materiál z ceníku">Ceník</a>' in detail and 'aria-label="Nová práce">Nový</a>' in detail
    prijem = client.get("/zakazky/nova").text
    assert ">Nové vozidlo</button>" in prijem and ">Nový zákazník</button>" in prijem
    karta = client.get("/cenik/nova").text
    akce = karta.split('<aside class="akce')[1].split("</aside>")[0]
    assert akce.index(">Uložit</button>") < akce.index(">Uložit a další</button>") < akce.index('class="zpet oddelene"')
    assert "dvojklik" not in client.get("/zakazky").text.split('id="stav-seznamu"')[-1][:600]
    client.post("/cenik/nova", data={"typ": "material", "nazev": "Filtr 49", "cena": "10"})
    assert "klik na řádek otevře kartu materiálu" in client.get("/cenik").text


def test_jednotny_vzhled_seznamu():
    """#57: hlavní údaj td.hlavni, kódy td.kod, prázdné hodnoty pomlčkou, konečná částka polotučně."""
    client.post("/nastaveni", data={"platce_dph": "1", "rada_faktura": "FV{RRRR}", "rada_vyuctovani": "VY{RRRR}"})
    _prijem(spz="7JJ7777")
    client.post("/cenik/nova", data={"nazev": "Filtr vzhledu", "cena": "100", "kod": ""})
    client.post("/prace/nova", data={"nazev": "Práce vzhledu", "cena": "500"})
    for url in ("/zakazky", "/vozidla", "/zakaznici", "/cenik", "/prace"):
        text = client.get(url).text
        assert '<td class="hlavni' in text, url
    vozidla = client.get("/vozidla").text
    assert '<td class="kod vin">' in vozidla and '<span class="prazdne">—</span>' in vozidla
    cenik = client.get("/cenik").text
    assert 'class="cislo castka-hlavni"' in cenik and "<strong>" not in cenik.split("<tbody>")[1].split("</tbody>")[0]
    assert 'class="cislo castka-hlavni"' in client.get("/prace").text
    from app.web.sablony import _pomlcka
    assert str(_pomlcka("")) == '<span class="prazdne">—</span>' and str(_pomlcka("<b>")) == "&lt;b&gt;"
    assert str(_pomlcka(0)) == "0"


def test_seznamy_jeden_pokyn_ke_kliknuti():
    """#66: v každém seznamu je pokyn ke kliknutí na řádek právě jednou (u tabulky)."""
    _prijem(spz="6P66666")
    client.post("/cenik/nova", data={"typ": "material", "kod": "P66", "nazev": "Díl", "cena": "1"})
    client.post("/prace/nova", data={"kod": "PR66", "nazev": "Práce PR66", "cena": "400", "jednotka": "úkon"})
    for url in ["/zakazky", "/vozidla", "/zakaznici", "/cenik", "/prace"]:
        text = re.sub(r"<script.*?</script>", "", client.get(url).text, flags=re.S).lower()  # jen viditelný text
        assert text.count("klik na řádek") == 1, url


def test_kopirovat_vin_ikona_misto_napisu():
    """#154: tlačítko kopírování VIN je ikona (kopie + fajfka po zkopírování), bez nápisu Kopírovat."""
    from app.web.sablony import templates
    html = templates.env.from_string('{% from "_makra.html" import kopirovat %}{{ kopirovat("VIN123") }}').render()
    assert 'class="ik-kopie"' in html and 'class="ik-hotovo"' in html
    assert 'aria-label="Zkopírovat VIN do schránky"' in html
    assert re.sub(r"<[^>]+>", "", html).strip() == ""  # žádný viditelný text, jen ikony


def test_ikona_kopirovani_pred_vin_a_kodem_materialu():
    """#156: ikona kopírování je před VIN a před kódem materiálu (zakázka, ceník, Správa dat), u práce ne."""
    loc = _prijem(spz="1KO1560", v_vin="TMBKXPXE00000156A").headers["location"].split("?")[0]
    client.post(f"{loc}/polozky", data={"typ": "material", "kod": "OPT FAF10128", "nazev": "Vzduchový filtr",
                                        "mnozstvi": "1", "cena": "399"})
    client.post(f"{loc}/polozky", data={"typ": "prace", "kod": "MECH", "nazev": "Mechanická práce",
                                        "mnozstvi": "1", "cena": "450"})
    detail = client.get(loc).text
    # VIN: tlačítko před textem
    assert re.search(r'data-kopirovat="TMBKXPXE00000156A"[^>]*>.*?</button><span>TMBKXPXE00000156A</span>', detail, re.S)
    # kód materiálu s ikonou před kódem, práce bez ikony
    assert re.search(r'data-kopirovat="OPT FAF10128" title="Zkopírovat kód do schránky".*?</button>OPT FAF10128</td>', detail, re.S)
    assert 'data-kopirovat="MECH"' not in detail
    assert 'data-kopirovat="TMBKXPXE00000156A"' in client.get("/zakazky").text


def test_seznam_zakazek_filtr_otevrene_vsechny_a_rok():
    """Předaná zakázka zůstává otevřená, dokud není uzavřená s dokladem nebo ručně."""
    loc = _prijem(spz="1PR1660").headers["location"].split("?")[0]
    client.post(f"{loc}/stav", data={"stav": "hotovo"})
    seznam = client.get("/zakazky").text
    assert "1PR1660" in seznam
    assert 'value="" aria-pressed="true"' in seznam
    assert 'value="vse" aria-pressed="false"' in seznam
    assert ">Otevřené</button>" in seznam and ">Všechny</button>" in seznam
    assert '<select name="stav"' not in seznam
    assert "Zakázka zůstává otevřená, dokud není doklad." in client.get(loc).text
    # uzavřená bez dokladu → mezi uzavřenými
    client.post(f"{loc}/stav", data={"stav": "predano", "bez_dokladu": "1"})
    assert "1PR1660" not in client.get("/zakazky").text
    assert "1PR1660" in client.get("/zakazky", params={"stav": "predano"}).text
    vsechny = client.get("/zakazky", params={"stav": "vse", "rok": "vse"}).text
    assert 'value="vse" aria-pressed="true"' in vsechny
    assert 'type="hidden" name="stav" value="vse"' in vsechny
    assert "1PR1660" in vsechny

    _prijem(spz="1PR1661")
    for stav in ("", "vse"):
        for rok in (date.today().year - 1, date.today().year):
            seznam = client.get("/zakazky", params={"stav": stav, "rok": rok}).text
            assert ("1PR1661" in seznam) == (rok == date.today().year)
            assert ("1PR1660" in seznam) == (rok == date.today().year and stav == "vse")


def test_ovladani_sipkami_znacky_v_sablonach():
    """#185: Insert má v seznamech a v detailu zakázky svůj cíl (data-insert), stavový řádek ukazuje nápovědu kláves."""
    zakazky = _se_skriptem(client.get("/zakazky").text)
    for url in ("/vozidla", "/zakaznici", "/cenik", "/prace"):
        assert "data-insert" in client.get(url).text, url
    assert "data-insert" in zakazky
    loc = _zakazka_s_polozkou(spz="1KL1850")
    detail = _se_skriptem(client.get(loc).text)
    assert re.search(r'cenik\?typ=material" role="button" data-okno data-insert', detail)
    assert re.search(r'cenik\?typ=prace" role="button" data-okno data-insert', detail)
    assert "↑↓ výběr · Enter otevřít" in client.get("/vozidla").text
    assert "radkyKlavesnici" in detail  # obsluha kláves je v static/app.js (#233)
    # Nápověda v liště vlevo od ozubeného kola, okno není stránka menu.
    assert zakazky.index('aria-label="Nápověda"') < zakazky.index('aria-label="Nastavení"')
    assert 'id="okno-napoveda-klaves"' in zakazky and "PageDown" in zakazky and "polozkyNapovedy" in zakazky
    # #204: po zavření nápovědy výběr odejde z tlačítka, text okna se zalamuje, řádek po změně množství zůstane.
    assert 'activeElement?.id === "tlacitko-napoveda"' in zakazky
    assert "autoservis-vyber" in detail
    assert "mnozstvi-radku button.krok" in detail
    # #206: Esc na detailu = tlačítko Zpět na seznam
    assert 'e.key === "Escape"' in detail and ".akce a.zpet" in detail
    assert "zpět na seznam zakázek" in detail
    vid = re.search(r'href="/vozidla/(\d+)"', detail).group(1)
    karta = _se_skriptem(client.get(f"/vozidla/{vid}").text)
    assert 'href="/vozidla" role="button" class="zpet"' in karta
    assert "RADKY_NAPOVEDY.karta" in karta
    import pathlib
    css = (pathlib.Path(__file__).parent.parent / "app/web/static/app.css").read_text(encoding="utf-8")
    assert "dialog.napoveda-klaves td:nth-child(2) { white-space: normal; }" in css


def test_kopirovani_nahradne_pres_udalost_copy():
    """#195: náhradní kopírování (http) vkládá text přímo v události copy a fajfku ukáže jen při úspěchu."""
    stranka = _se_skriptem(client.get("/zakazky").text)
    assert "function kopirujNahradne(text)" in stranka
    assert 'ev.clipboardData.setData("text/plain", text)' in stranka
    assert "Kopírování se nepovedlo" in stranka
