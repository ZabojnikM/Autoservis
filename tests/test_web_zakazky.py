"""Testy webu – zakázky a příjem (rozděleno z test_web.py, #233)."""
import re
from datetime import date
from tests.web_pomucky import client, _prijem, _zakazka_s_polozkou, _je_okno
from tests.web_pomucky import ucet_pro_vyuctovani  # noqa: F401 – fixtury (autouse)


def test_prijem_a_detail():
    r = _prijem()
    assert r.status_code == 303
    detail = client.get(r.headers["location"])
    assert "Nejde startovat" in detail.text
    assert "Jana Dvořáková" in detail.text
    assert "1AB2345" in client.get("/").text


def test_prijem_a_uprava_v_okne():
    # okno=1: jen obsah okna (bez celé stránky), HTMX odeslání
    r = client.get("/zakazky/nova", params={"okno": "1"})
    assert r.status_code == 200 and "<html" not in r.text and 'hx-post="/zakazky/nova"' in r.text
    assert "data-zavrit-okno" in r.text
    # chyba v okně: 200 (HTMX zobrazí) a hodnoty zůstanou
    r = _prijem(tachometr="-5", okno="1")
    assert r.status_code == 200 and "nemůže být záporný" in r.text and "<html" not in r.text
    # uložení z okna: přesměrování přes HTMX hlavičku
    r = _prijem(okno="1")
    assert r.status_code == 204 and r.headers["HX-Redirect"].startswith("/zakazky/")
    loc = r.headers["HX-Redirect"].split("?")[0]
    r = client.get(f"{loc}/upravit", params={"okno": "1"})
    assert "<html" not in r.text and f'hx-post="{loc}/upravit"' in r.text
    r = client.post(f"{loc}/upravit", data={"pozadavek": "Z okna", "okno": "1", "zakaznik_id": "bez"})
    assert r.status_code == 204 and r.headers["HX-Refresh"] == "true"
    assert "Z okna" in client.get(loc).text


def test_prijem_chyba_zachova_hodnoty():
    r = _prijem(tachometr="-5")
    assert r.status_code == 422
    assert "nemůže být záporný" in r.text
    assert "Jana Dvořáková" in r.text


def test_prijem_bez_popisu_zakazky():
    """Popis zakázky (požadavek) je nepovinný."""
    r = _prijem(pozadavek="")
    assert r.status_code == 303
    assert client.get(r.headers["location"]).status_code == 200


def test_zmena_stavu():
    loc = _prijem().headers["location"].split("?")[0]
    otevrena = client.get(loc).text
    assert "Uzavřít bez dokladu" in otevrena  # #90: jiné znění než štítek zakázky s dokladem
    assert "Zakázka zůstává otevřená, dokud není doklad." in otevrena  # #166
    assert ">Uzavřeno</button>" not in otevrena
    r = client.post(f"{loc}/stav", data={"stav": "predano", "bez_dokladu": "1"}, follow_redirects=True)
    assert "Uzavřeno bez dokladu" in r.text
    assert "1AB2345" not in client.get("/").text  # uzavřená není mezi otevřenými zakázkami


def test_vyber_roku_je_letosni():
    """#91: zakázky i faktury se otevřou na aktuální rok, všechny roky jsou volba."""
    letos = str(date.today().year)
    for url in ("/zakazky", "/faktury"):
        text = client.get(url).text
        assert f'value="{letos}" selected' in text
        assert 'value="vse" selected' not in text
    vse = client.get("/zakazky", params={"rok": "vse"}).text
    assert 'value="vse" selected' in vse


def test_hledani_presne_spz_presmeruje():
    _prijem()
    r = client.get("/hledat", params={"q": "1ab2345"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/vozidla/")


def test_rucni_polozka_chyba_zachova_formular():
    loc = _prijem().headers["location"].split("?")[0]
    r = client.post(f"{loc}/polozky", data={"typ": "material", "nazev": "Kus bez ceny"})
    assert r.status_code == 422 and "Vyplňte cenu" in r.text and "Kus bez ceny" in r.text


# ---------------------------------------------------------------- příjem jako okno Zakázka ve starém systému

def test_prijem_tri_panely_a_vychozi_hodnoty():
    r = client.get("/zakazky/nova")
    for text in ['id="panel-zakaznik"', 'id="panel-vozidlo"', "Označení", 'name="datum_prijeti"',
                 'name="v_kod_motoru"', 'name="v_termin_stk"', 'name="v_datum_registrace"', 'hx-get="/vozidla/okno"',
                 'hx-get="/zakaznici/okno"', "Uložit zakázku", "Načíst podle VIN", "Načíst podle IČO"]:
        assert text in r.text, text
    # plánované ukončení a stav paliva se už nezadávají
    assert 'name="termin_dokonceni"' not in r.text and 'name="stav_paliva"' not in r.text
    assert "Uložit vozidlo do databáze" not in r.text and "Uložit zákazníka do databáze" not in r.text

# ---------------------------------------------------------------- detail zakázky jako pracovní okno

def test_detail_zakazky_mrizka_polozek():
    loc = _zakazka_s_polozkou()
    detail = client.get(loc).text
    assert 'class="hlavicka-zakazky"' in detail and 'class="soucty"' in detail
    pid = re.search(r'data-odebrat="/polozky/(\d+)/smazat"', detail).group(1)
    assert f'data-upravit="/polozky/{pid}/upravit"' in detail
    for akce in [f'href="/polozky/{pid}/upravit" role="button" class="maly upravit-radek" data-okno',
                 f'data-smazat-radek="/polozky/{pid}/smazat"',
                 f'href="{loc}/cenik?typ=material"', f'href="{loc}/polozky/nova?typ=material"',
                 f'href="{loc}/cenik?typ=prace"', f'href="{loc}/polozky/nova?typ=prace"']:
        assert akce in detail, akce
    # dvě mřížky: nahoře Materiál, pod ní Práce; Diagnostika (práce) je v mřížce Práce, materiál zatím žádný
    assert detail.index('id="polozky-material"') < detail.index('id="polozky-prace"') < detail.index("Diagnostika")
    assert "Zatím žádný materiál." in detail and "Zatím žádná práce." not in detail
    # #26: v titulku název, pak tlačítka, souhrn (počet a částka) až na konci vpravo
    titulek = detail.split('id="polozky-prace"')[1].split("</div>")[0]
    # #41: velký nadpis oddílu, krátká tlačítka Ceník · Nový (· Import zašedlý jen u materiálu), souhrn vpravo
    assert '<h2 class="nadpis-oddilu">Práce</h2>' in titulek
    assert titulek.index('<h2 class="nadpis-oddilu">Práce</h2>') < titulek.index(">Ceník</a>")         < titulek.index(">Nový</a>") < titulek.index('class="tlumene souhrn-mrizky">1 položka')
    assert ">Import</button>" not in titulek and 'class="misto-tlacitka"' in titulek
    material = detail.split('id="polozky-material"')[1].split('id="polozky-prace"')[0]
    assert '<h2 class="nadpis-oddilu">Materiál</h2>' in material  # #8: Import už funguje (dodací list LKQ)
    assert 'href="/cenik/import?zakazka_id=' in material and ">Import</a>" in material
    # tlačítka přidání už nejsou v levém sloupci
    assert 'role="button" data-okno>Přidat z ceníku</a>' not in detail and ">Ruční položka</a>" not in detail
    # Upravit / Odebrat položku už nejsou v levém sloupci (jsou přímo v řádku, Upravit vlevo od Smazat)
    assert 'data-radek="upravit" data-okno>' not in detail and 'data-radek="odebrat">' not in detail
    assert detail.index(f'href="/polozky/{pid}/upravit" role="button"') < detail.index(f'data-smazat-radek="/polozky/{pid}/smazat"')
    # prázdná zakázka: odkazy na přidání v mřížce, bez tlačítek pro řádky
    prazdna = _prijem(spz="9Z99999").headers["location"].split("?")[0]
    detail = client.get(prazdna).text
    assert "Zatím žádný materiál." in detail and "Zatím žádná práce." in detail and "upravit-radek" not in detail
    assert 'class="soucty"' not in detail


def test_rucni_polozka_v_okne():
    loc = _prijem().headers["location"].split("?")[0]
    _je_okno(client.get(f"{loc}/polozky/nova", params={"okno": "1"}), f"{loc}/polozky")
    r = client.post(f"{loc}/polozky", data={"typ": "material", "nazev": "Bez ceny", "okno": "1"})
    assert r.status_code == 200 and "Vyplňte cenu" in r.text and 'value="Bez ceny"' in r.text
    r = client.post(f"{loc}/polozky", data={"typ": "prace", "nazev": "Seřízení", "mnozstvi": "1", "cena": "500",
                                            "okno": "1"})
    assert r.status_code == 204 and r.headers["HX-Refresh"] == "true"
    assert "Seřízení" in client.get(loc).text


# ---------------------------------------------------------------- zakázkový list A4

def test_zakazkovy_list_a4():
    client.post("/nastaveni", data={"nazev_servisu": "Autoservis Test", "ico": "12345678", "dic": "CZ12345678", "mesto": "Brno",
                                    "platce_dph": "1", "vychozi_dph": "21",
                                    "rada_faktura": "FV{RRRR}", "rada_vyuctovani": "VY{RRRR}"})
    loc = _prijem(poznamka="Tajná interní poznámka").headers["location"].split("?")[0]
    detail = client.get(loc).text
    assert f'href="{loc}/tisk?tisk=1"' in detail and 'target="_blank"' in detail
    # při příjmu: bez položek – prázdné řádky pro ruční zápis, podpisy, údaje servisu i zákazníka
    r = client.get(f"{loc}/tisk")
    assert r.status_code == 200 and "Zakázkový list" in r.text and "Autoservis Test" in r.text
    assert "Jana Dvořáková" in r.text and "1AB2345" in r.text and "Nejde startovat" in r.text
    assert re.search(r"98\s000 km", r.text) and r.text.count('class="prazdny"') == 8
    assert "Podpis zákazníka" in r.text and "Předání opraveného vozidla" in r.text
    assert "Tajná interní poznámka" not in r.text  # interní poznámka se netiskne
    assert "window.print()" in r.text and 'addEventListener("load"' not in r.text
    primy_tisk = client.get(f"{loc}/tisk", params={"tisk": "1"}).text
    assert 'addEventListener("load"' in primy_tisk
    assert 'addEventListener("afterprint", () => window.close()' in primy_tisk
    assert primy_tisk.count("window.print()") == 1
    assert 'onclick="window.print()"' not in primy_tisk
    # s položkami: řádky a součty s DPH
    client.post(f"{loc}/polozky", data={"typ": "prace", "nazev": "Diagnostika", "mnozstvi": "1", "cena": "1000"})
    r = client.get(f"{loc}/tisk")
    assert "Diagnostika" in r.text and 'class="prazdny"' not in r.text and re.search(r"1\s210,00", r.text)
    # bez zákazníka
    bez = _prijem(spz="8X88888", zakaznik_id="", k_nazev="", k_telefon="").headers["location"].split("?")[0]
    assert "Neuveden" in client.get(f"{bez}/tisk").text
    assert client.get("/zakazky/99999/tisk").status_code == 404


def test_cislo_zakazky_z_dokladu_se_znovu_neprideli():
    from app.db import get_session
    from app.models import Faktura
    from app.services import zakazky as zakazky_sluzba
    session = next(client.app.dependency_overrides[get_session]())
    rok = __import__("datetime").date.today().year
    session.add(Faktura(cislo="X1", cislo_zakazky=f"{rok}-0007", odb_nazev="Někdo"))
    session.commit()
    assert zakazky_sluzba.dalsi_cislo(session) == f"{rok}-0008"


def test_termin_ek_zrusen():
    # EK se nepoužívá – není ve formuláři vozidla, na příjmu ani na kartě vozidla
    for url in ["/vozidla/nove", "/zakazky/nova"]:
        assert "Termín EK" not in client.get(url).text, url
    loc = _prijem().headers["location"].split("?")[0]
    vid = re.search(r'href="/vozidla/(\d+)"', client.get(loc).text).group(1)
    assert "<dt>EK</dt>" not in client.get(f"/vozidla/{vid}").text


def test_smazani_zakazky_s_polozkami_s_potvrzenim():
    loc = _zakazka_s_polozkou()  # 1 položka práce
    client.post(f"{loc}/polozky", data={"typ": "material", "nazev": "Těsnění", "cena": "50"})
    uprava = client.get(f"{loc}/upravit").text  # #165: smazání je v okně Upravit zakázku
    assert f'action="{loc}/smazat" data-potvrdit=' in uprava and "nejdřív odeberte" not in uprava
    assert "Smaže se i materiál a práce na zakázce (2 položky)." in uprava
    r = client.post(f"{loc}/smazat", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/zakazky")
    assert client.get(loc).status_code == 404


def test_zakazka_kopirovat_vin():
    """#45: v kartě Vozidlo na detailu zakázky jde VIN zkopírovat."""
    r = _prijem(spz="7K45454", v_vin="TMBJJ7NE8J0123456")
    detail = client.get(r.headers["location"].split("?")[0]).text
    assert 'data-kopirovat="TMBJJ7NE8J0123456"' in detail


def test_prazdny_pozadavek_a_interni_poznamka():
    """#40: prázdný požadavek ukáže „Nevyplněno · Doplnit“, interní poznámka je zvlášť."""
    loc = _prijem(spz="5P55555", pozadavek="", poznamka="Klíče na recepci").headers["location"].split("?")[0]
    detail = client.get(loc).text
    assert "Nevyplněno" in detail and f'href="{loc}/upravit" data-okno>Doplnit</a>' in detail
    assert 'class="interni-poznamka neni-tisk"' in detail and "Klíče na recepci" in detail


def test_zakazky_vychozi_razeni_od_nejnovejsi():
    """#210: bez zvoleného řazení podle čísla sestupně (nejnovější nahoře), ruční řazení zůstává."""
    for spz in ("1AA1111", "2BB2222", "3CC3333"):
        _prijem(spz=spz)
    text = client.get("/zakazky", params={"vse": "1"}).text
    cisla = re.findall(r"<strong>(\d{4}-\d{4})</strong>", text) or re.findall(r">(\d{4}-\d{4})<", text)
    assert len(cisla) >= 3 and cisla == sorted(cisla, reverse=True)
    vzestupne = re.findall(r">(\d{4}-\d{4})<", client.get("/zakazky", params={"vse": "1", "razeni": "cislo"}).text)
    assert vzestupne[:3] == sorted(set(vzestupne))[:3]


def test_seznamy_jeden_klik_stav_a_hledani_v_seznamu():
    """#89: zakázka se otevře jedním klikem i ve vyhledávání a bublina říká totéž co nápověda.
    #88: stav je hned za zákazníkem, požadavek až na konci. #86: hledání v seznamu má vlastní štítek."""
    assert _prijem(spz="9KL1234", pozadavek="Brzdy TEST").status_code == 303
    hledani = client.get("/hledat", params={"q": "Brzdy TEST"}).text
    assert re.search(r'<table class="[^"]*klik-otevre', hledani)
    seznam = client.get("/zakazky").text
    for html in (hledani, seznam):
        assert "Dvojklik otevře zakázku" not in html
        assert 'title="Klik otevře zakázku"' in html
        assert 'class="sl-stav"' in html
    assert "Hledat v seznamu" in seznam
    assert "Hledat v seznamu" in client.get("/vozidla").text


def test_radek_polozky_upravit_vlevo_smazat_vpravo():
    """#103: v řádku položky zakázky je Upravit v prvním sloupci a Smazat v posledním (pravý okraj)."""
    client.post("/cenik/nova", data={"typ": "material", "kod": "RD103", "nazev": "Díl TEST 103", "cena": "50"})
    loc = _prijem(spz="9RD0103").headers["location"].split("?")[0]
    zid = loc.rsplit("/", 1)[1]
    vyber = client.get("/cenik/vyber", params={"q": "RD103", "zakazka_id": zid})
    cid = re.search(r'name="polozka_ceniku_id" value="(\d+)"', vyber.text).group(1)
    client.post(f"{loc}/polozky", data={"polozka_ceniku_id": cid, "mnozstvi": "1"})
    detail = client.get(loc).text
    radek = re.search(r'<tr data-otevrit="/polozky/\d+/upravit".*?</tr>', detail, re.S).group(0)
    bunky = re.findall(r'<td class="([^"]*)"', radek)
    assert bunky[0].startswith("sl-upravit") and bunky[-1].startswith("sl-smazat")
    assert "upravit-radek" in radek.split("</td>")[0] and "smazat-radek" in radek.split("<td")[-1]
    hlavicka = re.findall(r'<th class="([^"]*)"', detail.split("mrizka-polozek")[1].split("</thead>")[0])
    assert hlavicka[0].startswith("sl-upravit") and hlavicka[-1].startswith("sl-smazat")


def test_detail_zakazky_tlacitko_nova_zakazka_nahore():
    """Detail zakázky: v levém sloupci akcí je úplně nahoře Nová zakázka (prázdná, otevře se v okně)."""
    loc = _prijem(spz="9NZ0001").headers["location"].split("?")[0]
    detail = client.get(loc).text
    akce = detail.split('<aside class="akce')[1]
    prvni = re.search(r'<a [^>]*role="button"[^>]*>([^<]+)</a>', akce)
    assert prvni.group(1) == "Nová zakázka" and 'href="/zakazky/nova"' in prvni.group(0)


def test_detail_zakazky_celkem_s_dph_a_smazani_v_uprave():
    """#162: hlavní částka je Celkem s DPH; #165: Smazat zakázku není v levém sloupci detailu, ale v okně úpravy;
    #164: po uložení nové zakázky se otevře její detail."""
    client.post("/nastaveni", data={"nazev_servisu": "Autoservis Test", "platce_dph": "1", "vychozi_dph": "21",
                                    "rada_faktura": "FV{RRRR}", "rada_vyuctovani": "VY{RRRR}"})
    r = _prijem(spz="1SM1650")
    loc = r.headers["location"].split("?")[0]
    assert re.fullmatch(r"/zakazky/\d+", loc)  # #164 – celá stránka
    r = client.post("/zakazky/nova", data={"spz": "1SM1651", "k_nazev": "TEST", "okno": "1"})
    assert re.fullmatch(r"/zakazky/\d+", r.headers["HX-Redirect"])  # #164 – z okna
    client.post(f"{loc}/polozky", data={"typ": "prace", "nazev": "Diagnostika", "mnozstvi": "1", "cena": "1000"})
    detail = client.get(loc).text
    assert '<span class="celkem">Celkem s DPH <strong>1 210,00' in detail.replace("\u00a0", " ")
    radek = re.sub(r"\s+", " ", detail.replace("\u00a0", " "))
    assert '<td class="cislo">1 000,00</td> <td class="cislo celkem-s-dph"><strong>1 210,00</strong></td>' in radek
    assert "Smazat zakázku" not in detail
    uprava = client.get(f"{loc}/upravit").text
    assert f'action="{loc}/smazat"' in uprava and "Smazání nejde vrátit." in uprava
    # s dokladem: v detailu zašedlé tlačítko s důvodem, úprava přejde na doklad
    client.post(f"{loc}/vystavit", data={"typ": "vyuctovani", "uhrazeno_ihned": "1"})
    detail = client.get(loc).text
    assert re.search(r'<button type="button" class="secondary outline" disabled[^>]*>Smazat zakázku</button>', detail)
    assert f'action="{loc}/smazat"' not in detail
