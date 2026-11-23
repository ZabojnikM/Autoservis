import re
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.services import nastaveni

from app.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def ucet_pro_vyuctovani(session):
    """#55: vyúčtování bez účtu pro QR platbu vystavit nejde – v testech je účet nastavený předem."""
    nastaveni.uloz(session, {"ucet_vyuctovani": "2001234567/2010"})


def _prijem(spz="1AB2345", **navic):
    data = {
        "spz": spz, "v_znacka": "Škoda", "v_model": "Fabia",
        "zakaznik_vyber": "", "k_nazev": "Jana Dvořáková", "k_telefon": "603 000 000",
        "pozadavek": "Nejde startovat", "tachometr": "98000", "stav_paliva": "1/4",
    }
    data.update(navic)
    return client.post("/zakazky/nova", data=data, follow_redirects=False)


def test_vsechny_stranky_bez_dat():
    for url in ["/", "/zakazky", "/zakazky?vse=1", "/zakazky/nova", "/vozidla", "/zakaznici",
                "/vozidla/nove", "/zakaznici/novy", "/hledat?q=nic"]:
        r = client.get(url)
        assert r.status_code == 200, url


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


def test_htmx_nalezeni_vozidla():
    _prijem()
    r = client.get("/zakazky/nova/vozidlo", params={"spz": "1ab 2345"})
    assert "Vozidlo z databáze" in r.text and 'value="Fabia"' in r.text
    assert "otevřenou zakázku" in r.text
    # prázdný panel zákazníka → doplní se majitel vozidla (out-of-band)
    assert 'id="panel-zakaznik"' in r.text and 'value="Jana Dvořáková"' in r.text
    # vyplněný panel zákazníka se nepřepisuje
    r = client.get("/zakazky/nova/vozidlo", params={"spz": "1AB2345", "k_nazev": "Někdo jiný"})
    assert 'id="panel-zakaznik"' not in r.text
    r = client.get("/zakazky/nova/vozidlo", params={"spz": "9XX9999", "v_znacka": "Opel"})
    assert "Nové vozidlo" in r.text and 'value="Opel"' in r.text


def test_druha_zakazka_na_zname_vozidlo():
    loc = _prijem().headers["location"]
    vozidlo_id = re.search(r'href="/vozidla/(\d+)"', client.get("/vozidla").text).group(1)
    r = client.post("/zakazky/nova", data={"spz": "1AB2345", "vozidlo_id": vozidlo_id,
                                           "pozadavek": "Přezutí"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] != loc
    historie = client.get(f"/vozidla/{vozidlo_id}").text
    assert "Zakázky (2)" in historie


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


def test_vyber_zakaznika():
    _prijem()
    r = client.get("/zakaznici/vyber", params={"q": "dvoř", "pole": "zakaznik_vyber", "novy": "1"})
    assert "Jana Dvořáková" in r.text and "Nový zákazník" in r.text


def test_neexistujici_zaznam_404():
    assert client.get("/zakazky/999").status_code == 404
    assert client.get("/vozidla/999").status_code == 404


def test_novy_zakaznik_a_vozidlo():
    r = client.post("/zakaznici/novy", data={"nazev": "Auto Plus s.r.o.", "ico": "12345678"},
                    follow_redirects=False)
    zid = r.headers["location"].rsplit("/", 1)[1]
    r = client.post("/vozidla/nove", data={"spz": "2ab0001", "zakaznik_id": zid}, follow_redirects=True)
    assert "2AB0001" in r.text and "Auto Plus" in r.text
    r = client.post("/vozidla/nove", data={"spz": "2AB 0001"})
    assert r.status_code == 422 and "už v evidenci" in r.text


def test_cenik_stranky_a_pridani_do_zakazky():
    for url in ["/cenik", "/prace", "/prace/nova", "/cenik/nova", "/nastaveni", "/cenik?neaktivni=1",
                "/prace?razeni=cena", "/cenik?razeni=nakup"]:
        assert client.get(url).status_code == 200, url
    # starý odkaz na záložku Práce vede na samostatný ceník prací
    assert client.get("/cenik?typ=prace", follow_redirects=False).headers["location"].startswith("/prace")
    r = client.post("/cenik/nova", data={"typ": "material", "nazev": "Olejový filtr", "cena": "250"},
                    follow_redirects=True)
    assert "Olejový filtr" in r.text and "302,50" in r.text  # s DPH 21 %
    r = client.post("/prace/nova", data={"nazev": "Výměna oleje", "cena": ""})
    assert r.status_code == 422 and "Vyplňte cenu" in r.text  # bez ceny (normohodiny zrušeny) nejde
    assert "Časová norma" not in r.text and "normohodin" not in r.text
    r = client.post("/prace/nova", data={"nazev": "Výměna oleje", "cena": "400", "jednotka": "úkon"},
                    follow_redirects=True)
    assert "400,00" in r.text and "Ceník prací" in r.text and "Norma" not in r.text
    # ceníky jsou oddělené: materiál není v pracích a naopak
    assert "Výměna oleje" not in client.get("/cenik").text
    assert "Olejový filtr" not in client.get("/prace").text

    loc = _prijem().headers["location"].split("?")[0]
    zid = loc.rsplit("/", 1)[1]
    vyber = client.get("/cenik/vyber", params={"q": "olej", "zakazka_id": zid}).text
    cid = re.search(r'name="polozka_ceniku_id" value="(\d+)"', vyber).group(1)
    r = client.post(f"{loc}/polozky", data={"polozka_ceniku_id": cid, "mnozstvi": "2"}, follow_redirects=True)
    assert "Celkem s DPH" in r.text or "Celkem k úhradě" in r.text
    r = client.post(f"{loc}/polozky", data={"typ": "prace", "nazev": "Diagnostika", "mnozstvi": "1", "cena": "600"},
                    follow_redirects=True)
    assert "Diagnostika" in r.text

    pid = re.search(r'/polozky/(\d+)/upravit', r.text).group(1)
    assert client.get(f"/polozky/{pid}/upravit").status_code == 200
    r = client.post(f"/polozky/{pid}/upravit", data={"mnozstvi": "abc"})
    assert r.status_code == 422 and "není číslo" in r.text
    r = client.post(f"/polozky/{pid}/smazat", follow_redirects=True)
    assert r.status_code == 200


def test_rucni_polozka_chyba_zachova_formular():
    loc = _prijem().headers["location"].split("?")[0]
    r = client.post(f"{loc}/polozky", data={"typ": "material", "nazev": "Kus bez ceny"})
    assert r.status_code == 422 and "Vyplňte cenu" in r.text and "Kus bez ceny" in r.text


def test_nastaveni_ulozeni():
    r = client.post("/nastaveni", data={"vychozi_dph": "12", "mena": "Kč"}, follow_redirects=True)
    assert "Nastavení uloženo" in r.text
    assert not re.search(r'name="platce_dph" value="1"\s+checked', r.text)  # nezaškrtnuto → neplátce
    assert 'name="vychozi_dph" value="12"' in r.text
    assert "normohodin" not in r.text


def _zakazka_s_polozkou(**navic):
    loc = _prijem(**navic).headers["location"].split("?")[0]
    client.post(f"{loc}/polozky", data={"typ": "prace", "nazev": "Diagnostika", "mnozstvi": "1", "cena": "1000"})
    return loc


def test_faktura_cely_tok():
    client.post("/nastaveni", data={"nazev_servisu": "Autoservis Test", "ico": "12345678", "dic": "CZ12345678", "mesto": "Brno",
                                    "cislo_uctu": "19-2000145399/0800", "platce_dph": "1",
                                    "vychozi_dph": "21",
                                    "rada_faktura": "FV{RRRR}", "rada_vyuctovani": "VY{RRRR}"})
    loc = _zakazka_s_polozkou(spz="1FV6060", v_vin="TMBJJ7NE8J0606060")
    detail_zakazky = client.get(loc).text
    assert "Vystavit fakturu" in detail_zakazky
    # #61: přepínač stavu vlevo, bez popisku „Stav:“
    assert 'class="zmena-stavu neni-tisk" role="group" aria-label="Stav zakázky"' in detail_zakazky
    assert '<span class="tlumene">Stav:</span>' not in detail_zakazky
    formular = client.get(f"{loc}/vystavit?typ=faktura")
    assert formular.status_code == 200 and "Jana Dvořáková" in formular.text

    r = client.post(f"{loc}/vystavit", data={"typ": "faktura", "odb_nazev": "Jana Dvořáková",
                                             "forma_uhrady": "prevod"}, follow_redirects=False)
    assert r.status_code == 303
    detail = client.get(r.headers["location"])
    assert "1\u00a0210,00" in detail.text and "Neuhrazeno" in detail.text and "<svg" in detail.text  # QR
    fid = r.headers["location"].split("?")[0].rsplit("/", 1)[1]

    tisk = client.get(f"/faktury/{fid}/tisk").text
    assert "Faktura – daňový doklad" in tisk and "Autoservis Test" in tisk and "CZ6508000000192000145399" in tisk
    # #60: vozidlo po řádcích (SPZ + značka a model / VIN / km), číslo zakázky jen vpravo nahoře
    assert "<dt>Zakázka</dt>" not in tisk and 'class="cislo-zakazky">zakázka 20' in tisk
    assert re.search(r"<dt>Vozidlo</dt><dd>1FV6060 &nbsp;Škoda Fabia</dd>", tisk)
    assert '<dt>VIN</dt><dd class="vin">TMBJJ7NE8J0606060</dd>' in tisk
    assert re.search(r"<dt>Stav tachometru</dt><dd>98\W000 km</dd>", tisk)
    # #59: QR se škáluje přes viewBox (bez pevné šířky), takže se v tisku neořízne
    assert '<svg viewBox="0 0 ' in tisk and '<svg width=' not in tisk

    prehled = client.get("/faktury").text  # výchozí záložka Vyúčtování – faktura v ní není
    assert 'aria-current="true">Vyúčtování' in prehled and f"/faktury/{fid}" not in prehled
    vse = client.get("/faktury", params={"filtr": "vse"}).text
    assert f'<td class="hlavni doklad-faktura"><a href="/faktury/{fid}">FV' in vse  # faktura fialově (#57)
    zakazka = client.get(loc).text
    assert "Vystavit fakturu" not in zakazka and "vyúčtovaná" in zakazka

    r = client.post(f"/faktury/{fid}/uhrady", data={"castka": "5000"})
    assert r.status_code == 422 and "vyšší" in r.text
    r = client.post(f"/faktury/{fid}/uhrady", data={"castka": "1210", "zpusob": "prevod"}, follow_redirects=True)
    assert "Uhrazeno" in r.text
    assert f"/faktury/{fid}" in client.get("/faktury", params={"filtr": "vse"}).text  # Všechny ukazují i uhrazené
    assert f"/faktury/{fid}" in client.get("/faktury", params={"filtr": "faktury"}).text
    assert f"/faktury/{fid}" not in client.get("/faktury", params={"filtr": "vyuctovani"}).text

    # zrušená úhrada zůstane v historii přeškrtnutá
    uid = re.search(r"/uhrady/(\d+)/smazat", client.get(f"/faktury/{fid}").text).group(1)
    r = client.post(f"/uhrady/{uid}/smazat", follow_redirects=True)
    assert "zrusena-uhrada" in r.text and "Neuhrazeno" in r.text
    client.post(f"/faktury/{fid}/uhrady", data={"castka": "1210", "zpusob": "prevod"})
    # zakázka s dokladem nejde smazat a doklad je vidět v detailu zakázky
    detail = client.get(loc).text
    assert "Doklady" in detail and f"/faktury/{fid}" in detail and "nejde smazat" in detail
    r = client.post(f"{loc}/smazat", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == loc
    # zákazník s doklady nejde smazat – hláška, ne chyba 500
    zid = re.search(r'href="/zakaznici/(\d+)"', detail).group(1)
    r = client.post(f"/zakaznici/{zid}/smazat", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == f"/zakaznici/{zid}"
    # smazání dokladu s úhradou (#15): potvrzení na úhradu upozorní, zakázka se znovu otevře
    doklad = client.get(f"/faktury/{fid}").text
    assert "Smazat fakturu" in doklad and "úhrady se smažou s ním" in doklad and "Stornovat" not in doklad
    r = client.post(f"/faktury/{fid}/smazat", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == loc
    assert client.get(f"/faktury/{fid}").status_code == 404
    assert "Vystavit fakturu" in client.get(loc).text


def test_vystaveni_chyba_a_prazdna_zakazka():
    loc = _prijem().headers["location"].split("?")[0]
    r = client.post(f"{loc}/vystavit", data={"typ": "faktura", "odb_nazev": "X"})
    assert r.status_code == 422 and "není co fakturovat" in r.text
    loc = _zakazka_s_polozkou()
    r = client.post(f"{loc}/vystavit", data={"typ": "faktura", "odb_nazev": ""})
    assert r.status_code == 422 and "Vyplňte odběratele" in r.text



def test_filtry_a_odebrane_doklady():
    loc = _zakazka_s_polozkou()
    vystaveni = client.get(f"{loc}/vystavit?typ=faktura").text
    assert "Kartou" not in vystaveni and "Převodem" in vystaveni and "Hotově" in vystaveni
    assert "Další doklad" not in client.get(loc).text
    client.post(f"{loc}/vystavit", data={"typ": "vyuctovani", "odb_nazev": "Jana", "forma_uhrady": "hotove",
                                         "uhrazeno_ihned": "1"})
    for filtr in ["vyuctovani", "faktury", "stornovane", "vse", "neuhrazene"]:  # starší odkazy dál fungují
        assert client.get("/faktury", params={"filtr": filtr, "rok": "2026"}).status_code == 200
    # #175: jen tlačítka Vyúčtování / Faktury (bez Všechny), výchozí Vyúčtování; rok se při přepnutí drží
    client.cookies.delete("doklady")  # #183: bez zapamatované volby
    prehled = client.get("/faktury").text
    prepinac = prehled.split('aria-label="Typ dokladu"', 1)[1].split("</nav>", 1)[0]
    assert re.findall(r'filtr=(\w+)', prepinac) == ["vyuctovani", "faktury"] and "Všechny" not in prepinac
    assert re.search(r'class="katalog-tlacitko aktivni"\s+aria-current="true">Vyúčtování', prepinac)
    assert "<select name=\"filtr\"" not in prehled
    roky = client.get("/faktury", params={"filtr": "faktury", "rok": "2026", "q": "Jana"}).text
    assert "filtr=vyuctovani&amp;q=Jana&amp;rok=2026" in roky
    assert 'name="typ"' not in prehled and "faktury i vyúčtování" not in prehled
    assert "Neuhrazené" not in prehled and "Po splatnosti</a>" not in prehled
    assert "Export CSV" not in client.get("/faktury").text
    assert client.get("/faktury/export.csv").status_code in (404, 422)
    assert client.get("/dodaci-listy/fakturovat").status_code == 404


def test_prijem_bez_zakaznika_a_doplneni_web():
    r = client.post("/zakazky/nova", data={"spz": "4DD4444", "v_znacka": "VW", "k_nazev": "",
                                           "pozadavek": "Bez majitele"}, follow_redirects=False)
    assert r.status_code == 303
    loc = r.headers["location"].split("?")[0]
    detail = client.get(loc).text
    assert "Bez zákazníka" in detail and "Doplnit zákazníka" in detail
    form = client.get("/zakazky/nova", params={"spz": "4DD4444"}).text  # známé vozidlo bez zákazníka
    assert "Vozidlo z databáze" in form and "nebo nechte prázdné" in form

    # vyplněný zákazník bez firmy → chyba
    r = client.post("/zakazky/nova", data={"spz": "5DD5555", "k_nazev": "", "k_telefon": "777", "pozadavek": "x"})
    assert r.status_code == 422 and "Vyplňte firmu" in r.text and 'value="777"' in r.text

    # vyúčtování jde i bez zákazníka, faktura ne
    client.post(f"{loc}/polozky", data={"typ": "material", "nazev": "Díl", "mnozstvi": "1", "cena": "100"})
    assert "Faktura: doplnit zákazníka" in client.get(loc).text
    r = client.post(f"{loc}/vystavit", data={"typ": "faktura", "odb_nazev": "Někdo"})
    assert r.status_code == 422 and "vyžaduje zákazníka" in r.text
    assert "u vyúčtování nepovinné" in client.get(f"{loc}/vystavit?typ=vyuctovani").text

    # zákazníka lze doplnit na zakázce i u vozidla
    zid = client.post("/zakaznici/novy", data={"nazev": "Pozdější Majitel"},
                      follow_redirects=False).headers["location"].rsplit("/", 1)[1]
    r = client.post(f"{loc}/upravit", data={"pozadavek": "Bez majitele", "zakaznik_id": zid}, follow_redirects=True)
    assert "Pozdější Majitel" in r.text and "Vystavit fakturu" in r.text
    vid = re.search(r'href="/vozidla/(\d+)"', r.text).group(1)
    assert "Pozdější Majitel" in client.get(f"/vozidla/{vid}").text  # vozidlu se přiřadil taky
    r = client.post(f"/vozidla/{vid}/upravit", data={"spz": "4DD4444", "zakaznik_id": "bez"}, follow_redirects=True)
    assert "Bez majitele" in r.text
    r = client.post(f"{loc}/vystavit", data={"typ": "vyuctovani", "odb_nazev": "", "forma_uhrady": "hotove"},
                    follow_redirects=True)
    assert r.status_code == 200 and "VY" in r.text


def test_vozidlo_a_zakazka_novy_nebo_stavajici_zakaznik_web():
    # nové vozidlo bez zákazníka
    r = client.post("/vozidla/nove", data={"spz": "6FF6666", "zakaznik_id": "bez"}, follow_redirects=False)
    vid = r.headers["location"].rsplit("/", 1)[1]
    # formulář vozidla má stejný panel Zákazník jako příjem (Firma + Vybrat / Nový)
    form = client.get(f"/vozidla/{vid}/upravit").text
    assert 'id="panel-zakaznik"' in form and 'name="panel_zakaznika"' in form and "k_nazev" in form

    # úprava vozidla: nový zákazník přímo z formuláře
    r = client.post(f"/vozidla/{vid}/upravit", data={"spz": "6FF6666", "zakaznik_id": "novy"})
    assert r.status_code == 422 and "Vyplňte jméno nového zákazníka" in r.text
    r = client.post(f"/vozidla/{vid}/upravit", data={"spz": "6FF6666", "zakaznik_id": "novy",
                                                     "k_nazev": "Nový Majitel", "k_telefon": "700 000 001"},
                    follow_redirects=True)
    assert "Nový Majitel" in r.text
    assert "Nový Majitel" in client.get("/zakaznici").text

    # chyba ve vozidle (duplicitní SPZ) nezaloží zákazníka
    client.post("/vozidla/nove", data={"spz": "7GG7777", "zakaznik_id": "bez"})
    r = client.post(f"/vozidla/{vid}/upravit", data={"spz": "7GG7777", "zakaznik_id": "novy", "k_nazev": "Duch"})
    assert r.status_code == 422 and "Duch" not in client.get("/zakaznici").text

    # stávající zákazník a zpět bez
    zid = client.post("/zakaznici/novy", data={"nazev": "Stávající"},
                      follow_redirects=False).headers["location"].rsplit("/", 1)[1]
    r = client.post(f"/vozidla/{vid}/upravit", data={"spz": "6FF6666", "zakaznik_id": zid}, follow_redirects=True)
    assert "Stávající" in r.text
    r = client.post(f"/vozidla/{vid}/upravit", data={"spz": "6FF6666", "zakaznik_id": "bez"}, follow_redirects=True)
    assert "Bez majitele" in r.text

    # panel zákazníka u vozidla: vyplněný = nový zákazník, prázdný = bez zákazníka
    r = client.post(f"/vozidla/{vid}/upravit", data={"spz": "6FF6666", "panel_zakaznika": "1", "zakaznik_id": "",
                                                     "k_nazev": "Z panelu", "k_telefon": "700 1"},
                    follow_redirects=True)
    assert "Z panelu" in r.text
    r = client.post(f"/vozidla/{vid}/upravit", data={"spz": "6FF6666", "panel_zakaznika": "1", "zakaznik_id": "",
                                                     "k_nazev": ""}, follow_redirects=True)
    assert "Bez majitele" in r.text

    # úprava zakázky: nový zákazník přímo z formuláře
    loc = client.post("/zakazky/nova", data={"spz": "6FF6666", "vozidlo_id": vid, "zakaznik_id": "",
                                             "pozadavek": "x"}, follow_redirects=False).headers["location"].split("?")[0]
    form = client.get(f"{loc}/upravit").text
    assert 'id="panel-zakaznik"' in form and 'id="panel-vozidlo"' in form and 'name="datum_prijeti"' in form
    r = client.post(f"{loc}/upravit", data={"pozadavek": "x", "zakaznik_id": "novy", "k_nazev": "Ze zakázky"},
                    follow_redirects=True)
    assert "Ze zakázky" in r.text
    assert "Ze zakázky" in client.get(f"/vozidla/{vid}").text  # vozidlo bez zákazníka ho dostalo taky


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


def test_prijem_ulozi_zmeny_vybraneho_zakaznika_a_vozidla():
    _prijem()
    zid = re.search(r'href="/zakaznici/(\d+)"', client.get("/zakaznici").text).group(1)
    vid = re.search(r'href="/vozidla/(\d+)"', client.get("/vozidla").text).group(1)
    r = client.post("/zakazky/nova", data={
        "zakaznik_id": zid, "k_nazev": "Jana Dvořáková", "k_telefon": "777 999 000", "k_mesto": "Zlín",
        "vozidlo_id": vid, "spz": "1AB2345", "v_znacka": "Škoda", "v_model": "Fabia", "v_olej": "5W-30",
        "v_termin_stk": "2027-05-01", "v_datum_registrace": "2017-03-15", "datum_prijeti": "2026-11-10T08:15",
        "pozadavek": "Servis"},
        follow_redirects=True)
    assert r.status_code == 200 and "10.11.2026 08:15" in r.text
    zakaznik = client.get(f"/zakaznici/{zid}").text
    assert "777 999 000" in zakaznik and "Zlín" in zakaznik
    vozidlo = client.get(f"/vozidla/{vid}").text
    assert "5W-30" in vozidlo and "01.05.2027" in vozidlo and "15.03.2017" in vozidlo
    assert len(re.findall(r'href="/zakaznici/\d+"', client.get("/zakaznici").text)) == 1  # žádný nový zákazník


def test_prijem_jako_novy_zakaznik_a_nove_vozidlo():
    _prijem()
    zid = re.search(r'href="/zakaznici/(\d+)"', client.get("/zakaznici").text).group(1)
    r = client.post("/zakazky/nova", data={
        "zakaznik_id": zid, "jako_novy": "1", "k_nazev": "Jana Dvořáková ml.", "spz": "2ZZ0001",
        "v_znacka": "Kia", "v_kod_motoru": "G4FA", "pozadavek": "Brzdy"}, follow_redirects=True)
    assert "Jana Dvořáková ml." in r.text
    seznam = client.get("/zakaznici").text
    assert "Jana Dvořáková ml." in seznam and len(re.findall(r'href="/zakaznici/\d+"', seznam)) == 2
    assert "Jana Dvořáková</a>" in seznam  # původní zůstal beze změny
    vozidla_text = client.get("/vozidla", params={"q": "2ZZ0001"}).text
    vid = re.search(r'href="/vozidla/(\d+)"', vozidla_text).group(1)
    assert "G4FA" in client.get(f"/vozidla/{vid}").text


def test_prijem_prepsana_spz_neprejmenuje_vybrane_vozidlo():
    _prijem()
    vid = re.search(r'href="/vozidla/(\d+)"', client.get("/vozidla").text).group(1)
    client.post("/zakazky/nova", data={"vozidlo_id": vid, "spz": "9NN9999", "v_znacka": "Jiné",
                                       "pozadavek": "x"}, follow_redirects=False)
    assert "1AB2345" in client.get(f"/vozidla/{vid}").text  # původní SPZ zůstala
    assert "9NN9999" in client.get("/vozidla").text  # vzniklo nové vozidlo


def test_okno_vozidel_vlozi_vozidlo_i_zakaznika():
    _prijem()
    _prijem(spz="7Z12345", k_nazev="Petr Novák")
    r = client.get("/vozidla/okno")
    assert "Databáze vozidel" in r.text and "7Z12345" in r.text and "1AB2345" in r.text and "Vložit" in r.text
    assert 'hx-target="#vozidlo-udaje"' in r.text
    r = client.get("/vozidla/okno", params={"q": "novák"})
    assert "7Z12345" in r.text and "1AB2345" not in r.text
    assert "Nic nenalezeno" in client.get("/vozidla/okno", params={"q": "xyz"}).text
    vid = re.search(r'vybrat_id&#34;: &#34;(\d+)|vybrat_id": "(\d+)', r.text)
    vid = vid.group(1) or vid.group(2)
    r = client.get("/zakazky/nova/vozidlo", params={"vybrat_id": vid})
    assert 'id="spz"' in r.text and 'hx-swap-oob="true"' in r.text and 'value="7Z12345"' in r.text
    assert "Vozidlo z databáze" in r.text and 'value="Petr Novák"' in r.text
    # Nový = prázdný panel i SPZ
    r = client.get("/zakazky/nova/vozidlo", params={"novy": "1"})
    assert 'id="spz"' in r.text and 'name="vozidlo_id" value=""' in r.text


def test_okno_vozidel_ukaze_nejdriv_vozidla_vybraneho_zakaznika():
    _prijem()
    _prijem(spz="7Z12345", k_nazev="Petr Novák")
    zid = re.search(r'href="/zakaznici/(\d+)">Petr Novák', client.get("/zakaznici").text).group(1)
    r = client.get("/vozidla/okno", params={"zakaznik_id": zid})
    assert "Vozidla zákazníka" in r.text and "7Z12345" in r.text and "1AB2345" not in r.text
    r = client.get("/vozidla/okno", params={"zakaznik_id": zid, "vse": "1"})
    assert "7Z12345" in r.text and "1AB2345" in r.text


def test_okno_zakazniku_na_prijmu_a_jinde():
    _prijem()
    client.post("/zakaznici/novy", data={"nazev": "Firma Okno", "telefon": "777 888 999"})
    r = client.get("/zakaznici/okno", params={"cil": "prijem"})
    assert "Databáze zákazníků" in r.text and "Jana Dvořáková" in r.text and "Firma Okno" in r.text
    assert "1AB2345" in r.text and 'hx-target="#panel-zakaznik"' in r.text
    r = client.get("/zakaznici/okno", params={"cil": "prijem", "q": "okno"})
    assert "Firma Okno" in r.text and "Jana Dvořáková" not in r.text
    zid = re.search(r'vybrat_id&#34;: &#34;(\d+)|vybrat_id": "(\d+)', r.text)
    zid = zid.group(1) or zid.group(2)
    r = client.get("/zakazky/nova/zakaznik", params={"vybrat_id": zid})
    assert 'name="zakaznik_id" value="' + zid + '"' in r.text and 'value="777 888 999"' in r.text
    assert "Uložit jako nového zákazníka" in r.text
    r = client.get("/zakazky/nova/zakaznik")  # Nový = prázdný panel
    assert 'name="zakaznik_id" value=""' in r.text
    # úprava vozidla / zakázky: okno vkládá do výběru zákazníka
    r = client.get("/zakaznici/okno", params={"pole": "zakaznik_id"})
    assert 'hx-target="#blok-zakaznik_id"' in r.text
    r = client.get("/zakaznici/vyber/blok", params={"pole": "zakaznik_id", "vybrat_id": zid})
    assert re.search(rf'name="zakaznik_id" value="{zid}" checked', r.text)
    assert client.get("/zakaznici/vyber/blok", params={"vybrat_id": 999}).status_code == 404


def test_vyber_zakaznika_prochazeni():
    _prijem()
    r = client.get("/zakaznici/vyber", params={"pole": "zakaznik_id", "novy": "1", "bez": "1", "vychozi": "bez"})
    assert "Jana Dvořáková" in r.text
    assert re.search(r'value="\d+"\s+checked', r.text) is None
    assert re.search(r'value="bez"\s+checked', r.text)


# ---------------------------------------------------------------- ostatní formuláře jako okna

def _je_okno(r, akce):
    """Odpověď je jen obsah okna (bez celé stránky) s HTMX odesláním a tlačítkem Zrušit."""
    assert r.status_code == 200, r.text[:300]
    assert "<html" not in r.text and f'hx-post="{akce}"' in r.text and "data-zavrit-okno" in r.text


def test_vozidlo_v_okne():
    _je_okno(client.get("/vozidla/nove", params={"okno": "1"}), "/vozidla/nove")
    r = client.post("/vozidla/nove", data={"spz": "", "okno": "1", "zakaznik_id": "bez"})
    assert r.status_code == 200 and "<html" not in r.text and 'class="chyba"' in r.text
    r = client.post("/vozidla/nove", data={"spz": "2B33333", "znacka": "Opel", "okno": "1", "zakaznik_id": "bez"})
    assert r.status_code == 204 and r.headers["HX-Redirect"].startswith("/vozidla/")
    loc = r.headers["HX-Redirect"]
    _je_okno(client.get(f"{loc}/upravit", params={"okno": "1"}), f"{loc}/upravit")
    r = client.post(f"{loc}/upravit", data={"spz": "2B33333", "model": "Astra", "okno": "1", "zakaznik_id": "bez"})
    assert r.status_code == 204 and r.headers["HX-Refresh"] == "true"
    assert "Astra" in client.get(loc).text
    # celá stránka dál funguje postaru
    r = client.post(f"{loc}/upravit", data={"spz": "2B33333", "zakaznik_id": "bez"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == loc
    assert "<html" in client.get(f"{loc}/upravit").text


def test_zakaznik_v_okne():
    _je_okno(client.get("/zakaznici/novy", params={"okno": "1"}), "/zakaznici/novy")
    r = client.post("/zakaznici/novy", data={"nazev": "", "okno": "1"})
    assert r.status_code == 200 and 'class="chyba"' in r.text
    r = client.post("/zakaznici/novy", data={"nazev": "Okenní s.r.o.", "okno": "1"})
    assert r.status_code == 204
    loc = r.headers["HX-Redirect"]
    _je_okno(client.get(f"{loc}/upravit", params={"okno": "1"}), f"{loc}/upravit")
    r = client.post(f"{loc}/upravit", data={"nazev": "Okenní a syn", "okno": "1"})
    assert r.status_code == 204 and r.headers["HX-Refresh"] == "true"
    assert "Okenní a syn" in client.get(loc).text


def test_cenik_v_okne_a_ulozit_dalsi():
    _je_okno(client.get("/prace/nova", params={"okno": "1"}), "/prace/nova")
    _je_okno(client.get("/cenik/nova", params={"okno": "1"}), "/cenik/nova")
    r = client.post("/cenik/nova", data={"typ": "material", "nazev": "Olej 5W30", "cena": "200",
                                         "jednotka": "l", "okno": "1", "dalsi": "1"})
    # Uložit a další: okno zůstane s prázdným formulářem a hláškou
    assert r.status_code == 200 and "Uloženo: Olej 5W30" in r.text and 'value="Olej 5W30"' not in r.text
    r = client.post("/cenik/nova", data={"typ": "material", "nazev": "Filtr", "cena": "150 Kč", "cena_s_dph": "1",
                                         "okno": "1"})
    # po uložení seznam vyfiltrovaný na novou položku a zvýrazněný řádek
    assert r.status_code == 204 and r.headers["HX-Redirect"].startswith("/cenik?q=Filtr&zvyraznit=")
    seznam = client.get(r.headers["HX-Redirect"]).text
    assert "zvyrazneny" in seznam
    pid = re.search(r"/cenik/(\d+)/upravit", seznam).group(1)
    _je_okno(client.get(f"/cenik/{pid}/upravit", params={"okno": "1"}), f"/cenik/{pid}/upravit")
    # cena zadaná s DPH se v úpravě ukáže zase s DPH (ne 123.9669)
    form = client.get(f"/cenik/{pid}/upravit").text
    assert 'name="cena_s" value="150"' in form and 'name="cena" value="123,97"' in form
    assert 'name="cena_zdroj" value="s"' in form
    r = client.post(f"/cenik/{pid}/upravit", data={"typ": "material", "nazev": "", "okno": "1"})
    assert r.status_code == 200 and 'class="chyba"' in r.text and 'data-pole="nazev"' in r.text
    # smazání vrátí na seznam, odkud se okno otevřelo
    r = client.post(f"/cenik/{pid}/smazat", data={"zpet": "/cenik?q=Fil"}, follow_redirects=False)
    assert r.headers["location"] == "/cenik?q=Fil"


def test_cenik_nakupni_cena_dvojice_a_zamenitelny_dil():
    r = client.post("/cenik/nova", data={
        "typ": "material", "kod": "GAT 6PK1018-T", "zamenitelny_dil": "CONTI 6PK1015-T", "nazev": "Klínový řemen T",
        "jednotka": "ks", "sazba_dph": "21", "cena": "318,18", "cena_s": "385", "cena_zdroj": "s",
        "nakupni_cena": "219", "nakupni_cena_s": "264,99", "nakupni_cena_zdroj": ""}, follow_redirects=False)
    assert r.status_code == 303
    # hledání i podle zaměnitelného dílu
    seznam = client.get("/cenik", params={"q": "CONTI 6PK1015-T"}).text
    pid = re.search(r"/cenik/(\d+)/upravit", seznam).group(1)
    form = client.get(f"/cenik/{pid}/upravit").text
    assert 'name="cena_s" value="385"' in form and 'name="cena_zdroj" value="s"' in form
    assert 'name="nakupni_cena" value="219"' in form and 'name="nakupni_cena_s" value="264,99"' in form
    assert 'value="CONTI 6PK1015-T"' in form and "<select name=\"jednotka\">" in form
    # uložení beze změny ceny nezmění; nákupní cena zadaná s DPH se přepočítá
    client.post(f"/cenik/{pid}/upravit", data={
        "typ": "material", "nazev": "Klínový řemen T", "jednotka": "ks", "sazba_dph": "21",
        "cena": "318,18", "cena_s": "385", "cena_zdroj": "s", "nakupni_cena": "", "nakupni_cena_s": "121",
        "nakupni_cena_zdroj": "s", "aktivni": "1"})
    form = client.get(f"/cenik/{pid}/upravit").text
    assert 'name="cena_s" value="385"' in form and 'name="nakupni_cena" value="100"' in form
    client.post(f"/cenik/{pid}/smazat")


def test_cenik_radi_a_hleda_podle_kodu():
    for kod, nazev in [("ZZ 300", "Ařemen"), ("AA 100", "Žárovka"), ("", "Bez kódu")]:
        client.post("/cenik/nova", data={"kod": kod, "nazev": nazev, "cena": "10"})
    text = client.get("/cenik").text
    # výchozí řazení podle kódu, položky bez kódu na konci
    assert text.index("AA 100") < text.index("ZZ 300") < text.index("Bez kódu")
    # kód se najde i bez mezer a oddělovačů
    nalezeno = client.get("/cenik", params={"q": "aa-100"}).text
    assert "Žárovka" in nalezeno and "Ařemen" not in nalezeno


def test_polozka_a_vystaveni_v_okne():
    loc = _zakazka_s_polozkou()
    pid = re.search(r"/polozky/(\d+)/upravit", client.get(loc).text).group(1)
    _je_okno(client.get(f"/polozky/{pid}/upravit", params={"okno": "1"}), f"/polozky/{pid}/upravit")
    r = client.post(f"/polozky/{pid}/upravit", data={"typ": "prace", "nazev": "Diagnostika", "mnozstvi": "2",
                                                     "cena": "1000", "okno": "1"})
    assert r.status_code == 204 and r.headers["HX-Refresh"] == "true"

    _je_okno(client.get(f"{loc}/vystavit", params={"typ": "vyuctovani", "okno": "1"}), f"{loc}/vystavit")
    r = client.post(f"{loc}/vystavit", data={"typ": "faktura", "odb_nazev": "", "okno": "1"})
    assert r.status_code == 200 and 'class="chyba"' in r.text and "<html" not in r.text
    r = client.post(f"{loc}/vystavit", data={"typ": "vyuctovani", "forma_uhrady": "hotove", "okno": "1"})
    assert r.status_code == 204 and r.headers["HX-Redirect"].startswith("/faktury/")
    # vyúčtovaná zakázka: položky už nejdou měnit (žádné akce řádků ani přidávání)
    detail = client.get(loc).text
    assert "data-odebrat=" not in detail and f"{loc}/cenik" not in detail
    # zakázka už má doklad → okno vystavení rovnou přejde na doklad
    r = client.get(f"{loc}/vystavit", params={"okno": "1"}, follow_redirects=False)
    assert r.status_code == 204 and r.headers["HX-Redirect"].startswith("/faktury/")

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


def test_okno_cenik_vlozi_a_zavre():
    client.post("/cenik/nova", data={"typ": "material", "nazev": "Brzdová kapalina", "cena": "180", "jednotka": "l"})
    client.post("/cenik/nova", data={"typ": "material", "nazev": "Stěrač", "cena": "250"})
    loc = _prijem().headers["location"].split("?")[0]
    zid = loc.rsplit("/", 1)[1]
    r = client.get(f"{loc}/cenik", params={"okno": "1"})
    assert r.status_code == 200 and "<html" not in r.text
    assert "Brzdová kapalina" in r.text and "Stěrač" in r.text  # bez hledání ukáže začátek ceníku
    assert 'data-obnovit-po-zavreni' not in r.text
    r = client.get("/cenik/vyber", params={"q": "brzd", "zakazka_id": zid, "okno": "1"})
    # #46: Vložit na řádku zapíše položku rovnou do zakázky (HTMX do okna), košík „K vložení“ už není
    assert "Brzdová kapalina" in r.text and "Stěrač" not in r.text and "data-kosik" not in r.text
    assert f'hx-post="/zakazky/{zid}/polozky"' in r.text and ">Vložit</button>" in r.text
    cid = re.search(r'name="polozka_ceniku_id" value="(\d+)"', r.text).group(1)
    okno = client.get(f"{loc}/cenik", params={"okno": "1"}).text
    assert "K vložení" not in okno and "Na zakázce" not in okno
    r = client.post(f"{loc}/polozky", data={"polozka_ceniku_id": cid, "mnozstvi": "2", "okno": "1", "q": "brzd"})
    # #48: Vložit okno zavře a obnoví detail zakázky, hláška přijde v cookie
    from urllib.parse import unquote
    assert r.status_code == 204 and r.headers["HX-Refresh"] == "true"
    assert unquote(r.cookies.get("zprava")) == "Přidáno: Brzdová kapalina (2 l)"
    r = client.post(f"{loc}/polozky", data={"polozka_ceniku_id": cid, "mnozstvi": "0", "okno": "1"})
    assert "větší než 0" in r.text
    # Vložit zapíše výběr najednou
    r = client.post(f"{loc}/polozky/vlozit", data={"polozka_ceniku_id": [cid], "mnozstvi": ["2"]})
    assert r.status_code == 204 and r.headers["HX-Refresh"] == "true"
    assert "Brzdová kapalina" in client.get(loc).text
    r = client.post(f"{loc}/polozky/vlozit", data={"polozka_ceniku_id": [cid], "mnozstvi": ["0"]})
    assert r.status_code == 422 and "větší než 0" in r.text
    # bez okna (celá stránka) se přidání přesměruje na detail
    r = client.post(f"{loc}/polozky", data={"polozka_ceniku_id": cid, "mnozstvi": "1"}, follow_redirects=False)
    assert r.status_code == 303


def test_okno_cenik_radek_upravit_kartu():
    client.post("/cenik/nova", data={"typ": "material", "nazev": "Brzdová kapalina", "cena": "180", "jednotka": "l"})
    client.post("/prace/nova", data={"nazev": "Výměna kapaliny", "cena": "500"})
    loc = _prijem().headers["location"].split("?")[0]
    zid = loc.rsplit("/", 1)[1]
    r = client.get("/cenik/vyber", params={"q": "kapal", "zakazka_id": zid, "okno": "1"}).text
    # řádek: dvojklik / Enter přidá, množství předvyplněné 1; tlačítko Upravit v okně není (jen Vložit)
    assert r.count("data-pridat") == 2 and 'name="mnozstvi" value="1"' in r
    assert "upravit-kartu" not in r and ">Upravit<" not in r
    okno = client.get(f"{loc}/cenik", params={"okno": "1"}).text
    assert re.search(r'<input type="search"[^<]*>\s*(<nav|</div>)', okno)  # pole hledání uzavřené
    cid = re.findall(r'name="polozka_ceniku_id" value="(\d+)"', r)[0]  # Brzdová kapalina (řazení podle názvu je první)
    # karta otevřená z okna ceníku: Zpět (do okna ceníku) místo Zrušit, bez mazání
    karta = client.get(f"/cenik/{cid}/upravit", params={"okno": "1", "z_ceniku": zid, "q": "kapal"}).text
    assert re.search(rf'hx-get="/zakazky/{zid}/cenik"[^>]*>Zpět</button>', karta)
    assert "Smazat z ceníku" not in karta and f'name="z_ceniku" value="{zid}"' in karta
    # chyba nechá kartu otevřenou, uložení vrátí okno ceníku s hledáním
    r = client.post(f"/cenik/{cid}/upravit", data={"okno": "1", "z_ceniku": zid, "q": "kapal", "typ": "material",
                                                    "nazev": "Brzdová kapalina DOT4", "cena": "", "aktivni": "1"})
    assert "Vyplňte cenu" in r.text and f'hx-get="/zakazky/{zid}/cenik"' in r.text
    r = client.post(f"/cenik/{cid}/upravit", data={"okno": "1", "z_ceniku": zid, "q": "kapal", "typ": "material",
                                                    "nazev": "Brzdová kapalina DOT4", "cena": "190", "aktivni": "1"})
    assert r.status_code == 200 and "Karta uložena: Brzdová kapalina DOT4" in r.text
    # karta materiálu se vrátí do okna materiálu
    assert "Přidat materiál z ceníku" in r.text and 'value="kapal"' in r.text
    # bez okna se karta chová jako dřív
    assert "Smazat z ceníku" in client.get(f"/cenik/{cid}/upravit").text


def test_rucni_polozka_v_okne():
    loc = _prijem().headers["location"].split("?")[0]
    _je_okno(client.get(f"{loc}/polozky/nova", params={"okno": "1"}), f"{loc}/polozky")
    r = client.post(f"{loc}/polozky", data={"typ": "material", "nazev": "Bez ceny", "okno": "1"})
    assert r.status_code == 200 and "Vyplňte cenu" in r.text and 'value="Bez ceny"' in r.text
    r = client.post(f"{loc}/polozky", data={"typ": "prace", "nazev": "Seřízení", "mnozstvi": "1", "cena": "500",
                                            "okno": "1"})
    assert r.status_code == 204 and r.headers["HX-Refresh"] == "true"
    assert "Seřízení" in client.get(loc).text


# ---------------------------------------------------------------- detail vozidla a zákazníka (historie)

def test_detail_vozidla_zalozky_historie():
    loc = _zakazka_s_polozkou()  # práce Diagnostika 1000 Kč
    client.post(f"{loc}/polozky", data={"typ": "material", "nazev": "Žárovka H7", "mnozstvi": "2", "cena": "100"})
    vid = re.search(r'href="/vozidla/(\d+)"', client.get(loc).text).group(1)
    r = client.get(f"/vozidla/{vid}")
    assert r.status_code == 200 and 'class="karta-vozidla-panely"' in r.text
    # vlevo Vozidlo (i technické údaje), vpravo Majitel a pod ním Termíny a historie
    assert r.text.index(">Vozidlo<") < r.text.index(">Majitel<") < r.text.index(">Termíny a historie<")
    assert "Technické údaje" not in r.text
    # #47: karta jako panel Vozidlo v zakázce – SPZ + značka a model nahoře, pod tím „název: hodnota“,
    # prázdné údaje se nezobrazují (žádné „—“), motor sloučený; málo údajů → odkaz Doplnit
    karta = r.text.split('class="panel karta-vozidla"')[1].split("</section>")[0]
    assert 'class="hlavni-udaj hlavni-vozidla"' in karta and "<dl>" in karta
    assert "—" not in karta and "<dt>Barva</dt>" not in karta and "Doplnit údaje vozidla" in karta
    assert "Zakázky (1)" in r.text and "Práce (1)" in r.text and "Materiál (1)" in r.text
    assert "Jana Dvořáková" in r.text and "Nejde startovat" in r.text and f'data-otevrit="{loc}"' in r.text
    prace = client.get(f"/vozidla/{vid}", params={"zalozka": "prace"}).text
    assert "Diagnostika" in prace and "Žárovka H7" not in prace
    material = client.get(f"/vozidla/{vid}", params={"zalozka": "material"}).text
    assert "Žárovka H7" in material and "Diagnostika" not in material and "200,00" in material
    assert client.get(f"/vozidla/{vid}", params={"zalozka": "nesmysl"}).status_code == 200


def test_detail_zakaznika_zalozky_historie():
    loc = _zakazka_s_polozkou()
    zid = re.search(r'href="/zakaznici/(\d+)"', client.get(loc).text).group(1)
    r = client.get(f"/zakaznici/{zid}")
    assert "Vozidla (1)" in r.text and "Zakázky (1)" in r.text and "Doklady (0)" in r.text
    # Nová zakázka na zákazníka bez výběru vozidla, bez tlačítek „Otevřít …“, tabulky otevírají jedním klikem
    assert "1AB2345" in r.text and f'href="/zakazky/nova?zakaznik_id={zid}" role="button" data-okno>Nová zakázka</a>' in r.text
    assert 'data-radek="otevrit">' not in r.text and 'class="striped klik-otevre"' in r.text
    okno = client.get("/zakazky/nova", params={"zakaznik_id": zid, "okno": "1"}).text
    assert 'value="Jana Dvořáková"' in okno and re.search(r'name="spz" value=""', okno)
    zakazky_text = client.get(f"/zakaznici/{zid}", params={"zalozka": "zakazky"}).text
    assert "Nejde startovat" in zakazky_text and re.search(r"1\s(000|210),00", zakazky_text)  # podle plátcovství DPH
    client.post(f"{loc}/vystavit", data={"typ": "vyuctovani", "odb_nazev": "Jana Dvořáková", "forma_uhrady": "prevod"})
    doklady = client.get(f"/zakaznici/{zid}", params={"zalozka": "doklady"}).text
    assert "Doklady (1)" in doklady and "/faktury/" in doklady and "Neuhrazeno" in doklady


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


def test_uhrada_v_okne():
    loc = _zakazka_s_polozkou()
    client.post("/nastaveni", data={"nazev_servisu": "Autoservis Test", "ico": "12345678", "dic": "CZ12345678",
                                    "mesto": "Brno", "platce_dph": "1", "rada_faktura": "FV{RRRR}", "rada_vyuctovani": "VY{RRRR}"})
    # úhrady po částech jen u faktury – vyúčtování má přepínač stavu (#55)
    r = client.post(f"{loc}/vystavit", data={"typ": "faktura", "odb_nazev": "Jana Dvořáková", "forma_uhrady": "hotove"},
                    follow_redirects=False)
    fid = r.headers["location"].split("?")[0].rsplit("/", 1)[1]
    detail = client.get(f"/faktury/{fid}").text
    assert f'href="/faktury/{fid}/uhrady/nova" role="button" data-okno' in detail
    _je_okno(client.get(f"/faktury/{fid}/uhrady/nova", params={"okno": "1"}), f"/faktury/{fid}/uhrady")
    r = client.post(f"/faktury/{fid}/uhrady", data={"castka": "999999", "okno": "1"})
    assert r.status_code == 200 and "vyšší" in r.text and "<html" not in r.text
    r = client.post(f"/faktury/{fid}/uhrady", data={"castka": "100", "zpusob": "hotove", "okno": "1"})
    assert r.status_code == 204 and r.headers["HX-Refresh"] == "true"
    assert "100,00" in client.get(f"/faktury/{fid}").text


def test_uprava_zakazky_zmeni_vozidlo_i_datum_prijeti():
    loc = _prijem().headers["location"]
    r = client.post(f"{loc}/upravit", data={
        "spz": "3XY3333", "vozidlo_id": "", "v_znacka": "Opel", "zakaznik_id": "", "k_nazev": "Jana Dvořáková",
        "datum_prijeti": "2026-11-01T07:30", "pozadavek": "Opraveno", "okno": "1"})
    assert r.status_code == 204
    detail = client.get(loc).text
    assert "3XY3333" in detail and "01.11.2026 07:30" in detail and "Opraveno" in detail
    # chyba: kurzor na pole (data-pole), okno zůstane
    r = client.post(f"{loc}/upravit", data={"spz": "3XY3333", "tachometr": "-1", "okno": "1"})
    assert r.status_code == 200 and 'data-pole="tachometr"' in r.text


def test_cislo_zakazky_z_dokladu_se_znovu_neprideli():
    from app.db import get_session
    from app.models import Faktura
    from app.services import zakazky as zakazky_sluzba
    session = next(client.app.dependency_overrides[get_session]())
    rok = __import__("datetime").date.today().year
    session.add(Faktura(cislo="X1", cislo_zakazky=f"{rok}-0007", odb_nazev="Někdo"))
    session.commit()
    assert zakazky_sluzba.dalsi_cislo(session) == f"{rok}-0008"


def test_nastaveni_ma_tlacitko_v_akcich():
    r = client.get("/nastaveni").text
    assert 'form="formular-nastaveni"' in r and 'id="formular-nastaveni"' in r


def test_termin_ek_zrusen():
    # EK se nepoužívá – není ve formuláři vozidla, na příjmu ani na kartě vozidla
    for url in ["/vozidla/nove", "/zakazky/nova"]:
        assert "Termín EK" not in client.get(url).text, url
    loc = _prijem().headers["location"].split("?")[0]
    vid = re.search(r'href="/vozidla/(\d+)"', client.get(loc).text).group(1)
    assert "<dt>EK</dt>" not in client.get(f"/vozidla/{vid}").text

def test_tlacitko_zpet_je_vsude_stejne():
    # jednotné „Zpět“ – žádné „Zpět na seznam“, „Zpět do ceníku“…
    from pathlib import Path
    sablony = Path(__file__).resolve().parent.parent / "app" / "web" / "templates"
    for soubor in sablony.glob("*.html"):
        assert not re.search(r">\s*Zpět \w", soubor.read_text(encoding="utf-8")), soubor.name

def test_okno_cenik_storno_a_import():
    client.post("/cenik/nova", data={"typ": "material", "nazev": "Brzdová kapalina", "cena": "180", "jednotka": "l"})
    loc = _prijem().headers["location"].split("?")[0]
    # položka přidaná dřív (mimo okno) – Storno se jí nesmí dotknout
    client.post(f"{loc}/polozky", data={"typ": "material", "nazev": "Starší díl", "cena": "50"})
    okno = client.get(f"{loc}/cenik", params={"okno": "1"}).text
    # #46: nahoře Zavřít (jako Databáze zákazníků), bez Storna a hromadného Vložit; Import skrytý (#8, #35)
    assert "data-zavrit-okno" in okno and "✕ Zavřít" in okno and "stornoOknaCeniku(" not in okno
    assert ">Import</button>" not in okno and "data-vlozit-kosik" not in okno
    cid = re.search(r'name="polozka_ceniku_id" value="(\d+)"', okno).group(1)
    # Vložit je atomické: jedna chybná položka = nevloží se nic
    r = client.post(f"{loc}/polozky/vlozit", data={"polozka_ceniku_id": [cid, "999999"], "mnozstvi": ["1", "1"]})
    assert r.status_code == 422
    detail = client.get(loc).text
    assert "Starší díl" in detail and "Brzdová kapalina" not in detail
    # u položek zakázky je v řádku tlačítko Smazat
    assert 'data-smazat-radek="/polozky/' in detail

def test_uprava_radku_na_karte_ceniku_a_mnozstvi_v_radku():
    client.post("/cenik/nova", data={"typ": "material", "nazev": "Olejový filtr", "cena": "300", "kod": "OF1"})
    loc = _prijem().headers["location"].split("?")[0]
    okno = client.get(f"{loc}/cenik", params={"okno": "1"}).text
    cid = re.search(r'name="polozka_ceniku_id" value="(\d+)"', okno).group(1)
    client.post(f"{loc}/polozky/vlozit", data={"polozka_ceniku_id": [cid], "mnozstvi": ["2"]})
    detail = client.get(loc).text
    pid = re.search(r'action="/polozky/(\d+)/mnozstvi"', detail).group(1)
    # úprava řádku z ceníku = karta materiálu (stejný formulář jako v ceníku) s vazbou na řádek
    karta = client.get(f"/polozky/{pid}/upravit", params={"okno": "1"}).text
    assert "Upravit materiál" in karta and "Zaměnitelný díl" in karta and f'name="radek" value="{pid}"' in karta
    assert "Smazat z ceníku" not in karta
    r = client.post(f"/cenik/{cid}/upravit", data={"okno": "1", "radek": pid, "typ": "material", "nazev": "Filtr oleje",
                                                  "kod": "OF2", "jednotka": "ks", "cena": "350", "aktivni": "1"})
    assert r.status_code == 204
    detail = client.get(loc).text
    assert "Filtr oleje" in detail and "OF2" in detail and "Olejový filtr" not in detail
    assert "Filtr oleje" in client.get("/cenik").text  # i v ceníku
    # množství přímo v řádku
    r = client.post(f"/polozky/{pid}/mnozstvi", data={"mnozstvi": "3"}, follow_redirects=False)
    assert r.status_code == 303
    assert 'name="mnozstvi" value="3"' in client.get(loc).text
    r = client.post(f"/polozky/{pid}/mnozstvi", data={"mnozstvi": "0"}, follow_redirects=False)
    assert r.status_code == 303 and 'name="mnozstvi" value="3"' in client.get(loc).text
    # ruční položka (bez ceníku) má dál vlastní formulář
    client.post(f"{loc}/polozky", data={"typ": "material", "nazev": "Drobný materiál", "cena": "20"})
    rucni = re.findall(r'action="/polozky/(\d+)/mnozstvi"', client.get(loc).text)[-1]
    # ruční řádek (bez ceníku) se upravuje ve stejném okně jako karta Materiál, volba „do ceníku“ nezaškrtnutá
    uprava = client.get(f"/polozky/{rucni}/upravit").text
    assert "Upravit materiál" in uprava and "ruční položka" in uprava and "Zaměnitelný díl" in uprava
    assert re.search(r'name="ulozit_do_ceniku" value=""\s*checked', uprava)


def test_hledani_vin_prijme_vozidlo_s_vin():
    vin = "WVWZZZ3BZYE047008"
    r = client.get("/hledat", params={"q": vin})
    assert f'/zakazky/nova?vin={vin}' in r.text and "Přijmout vozidlo s VIN" in r.text
    assert "/zakazky/nova?spz=1XY9999" in client.get("/hledat", params={"q": "1XY9999"}).text
    for adresa in (f"/zakazky/nova?vin={vin}", f"/zakazky/nova?spz={vin}"):  # i starý odkaz přes spz
        prijem = client.get(adresa).text
        assert f'value="{vin}"' in prijem and 'name="v_vin"' in prijem
        assert not re.search(rf'name="spz"[^>]*value="{vin}"', prijem)  # do SPZ nepatří
    # vozidlo s tím VIN už v evidenci → hledání rovnou na vozidlo
    _prijem(spz="1VN0001", v_vin=vin)
    assert client.get("/hledat", params={"q": vin}, follow_redirects=False).status_code == 303


def test_material_pred_praci_v_tisku_a_dokladu():
    loc = _zakazka_s_polozkou()  # práce Diagnostika
    client.post(f"{loc}/polozky", data={"typ": "material", "nazev": "Olejový filtr", "mnozstvi": "1", "cena": "300"})
    tisk = client.get(f"{loc}/tisk").text
    assert tisk.index("Olejový filtr") < tisk.index("Diagnostika")
    assert tisk.index("<dt>Materiál</dt>") < tisk.index("<dt>Práce</dt>")
    r = client.post(f"{loc}/vystavit", data={"typ": "vyuctovani", "odb_nazev": "Jana", "forma_uhrady": "hotove"},
                    follow_redirects=False)
    doklad = r.headers["location"].split("?")[0]
    for adresa in (doklad, f"{doklad}/tisk"):
        text = client.get(adresa).text
        assert text.index("Olejový filtr") < text.index("Diagnostika"), adresa
        assert text.index("<dt>Materiál</dt>") < text.index("<dt>Práce</dt>"), adresa


def test_okno_ceniku_jen_pro_jeden_typ():
    client.post("/cenik/nova", data={"typ": "material", "kod": "MANN W712", "nazev": "Filtr oleje", "cena": "250",
                                     "zamenitelny_dil": "BOSCH 0451"})
    client.post("/prace/nova", data={"typ": "prace", "nazev": "Výměna filtru", "cena": "400"})
    loc = _prijem().headers["location"].split("?")[0]
    zid = loc.rsplit("/", 1)[1]
    material = client.get(f"{loc}/cenik", params={"typ": "material", "okno": "1"}).text
    assert "Přidat materiál z ceníku" in material and "Filtr oleje" in material and "Výměna filtru" not in material
    assert "<th>Zaměnitelný díl</th>" in material and "BOSCH 0451" in material and "<th>Typ</th>" not in material
    assert '"typ": "material"' in material and "Nová položka ceníku" not in material  # #48: nahoře jen Zavřít
    # ruční položka se do okna ceníku nedává – je jen tlačítkem + Ruční v mřížce zakázky (#25)
    # #68: Nový u hledání otevře novou položku zakázky a převezme text hledání do kódu
    assert "/polozky/nova?typ=material" in material and 'data-s-hledanim="kod"' in material
    assert "Ruční položka" not in material
    # #3: tlačítka v liště nad seznamem, okno bez sloupce akcí vlevo (sloupec Kód je širší)
    assert '<aside class="akce"' not in material and 's-akcemi' not in material
    # #46 / #48: v titulku nahoře jen Zavřít, nápověda dole vpravo
    hlavicka = material.split('class="okno-hlavicka')[1].split("</header>")[0]
    assert "✕ Zavřít" in hlavicka and "Nová položka" not in hlavicka
    assert material.index('id="cenik-vysledky"') < material.index('class="tlumene napoveda-okna')
    prace = client.get(f"{loc}/cenik", params={"typ": "prace", "okno": "1"}).text
    assert "Přidat práci z ceníku" in prace and "Výměna filtru" in prace and "Filtr oleje" not in prace
    assert "Zaměnitelný díl" not in prace
    # hledání při psaní drží typ
    vysledky = client.get("/cenik/vyber", params={"q": "filtr", "zakazka_id": zid, "okno": "1", "typ": "prace"}).text
    assert "Výměna filtru" in vysledky and "Filtr oleje" not in vysledky
    assert 'name="typ_okna" value="prace"' in vysledky
    # bez typu (starší odkazy) oba ceníky se sloupcem Typ
    oba = client.get(f"{loc}/cenik", params={"okno": "1"}).text
    assert "Filtr oleje" in oba and "Výměna filtru" in oba and "<th>Typ</th>" in oba


def test_rucni_polozka_jako_karta_ceniku():
    loc = _prijem().headers["location"].split("?")[0]
    zid = loc.rsplit("/", 1)[1]
    okno = client.get(f"{loc}/polozky/nova", params={"typ": "material", "okno": "1"}).text
    assert "Nový materiál" in okno and "Zaměnitelný díl" in okno and "Nákupní cena" in okno
    assert re.search(r'name="ulozit_do_ceniku" value="1"\s*checked', okno)  # nová položka: výchozí i do ceníku
    assert re.search(r'name="ulozit_do_ceniku" value=""\s*>', okno)
    prace = client.get(f"{loc}/polozky/nova", params={"typ": "prace"}).text
    assert "Nová práce" in prace and "Název práce" in prace and "Zaměnitelný díl" not in prace
    # uložení i do ceníku: položka ceníku se založí se všemi poli a řádek je s ní propojený
    r = client.post(f"{loc}/polozky", data={"typ": "material", "kod": "ATE 03.9901", "nazev": "Brzdová kapalina",
                                            "zamenitelny_dil": "TRW PFB", "jednotka": "l", "mnozstvi": "2",
                                            "cena": "200", "nakupni_cena": "120", "ulozit_do_ceniku": "1",
                                            "okno": "1"})
    assert r.status_code == 204  # okno se zavře a detail zakázky se obnoví
    cenik_text = client.get("/cenik", params={"q": "ATE"}).text
    assert "Brzdová kapalina" in cenik_text and "TRW PFB" in cenik_text
    detail = client.get(loc).text
    pid = re.findall(r'data-upravit="/polozky/(\d+)/upravit"', detail)[-1]
    assert "Upravit materiál" in client.get(f"/polozky/{pid}/upravit").text  # karta ceníku (propojeno)
    assert "ruční položka" not in client.get(f"/polozky/{pid}/upravit").text
    # stejný kód podruhé: nezaloží se, okno nabídne existující položku ceníku
    r = client.post(f"{loc}/polozky", data={"typ": "material", "kod": "ATE 03.9901", "nazev": "Jiná kapalina",
                                            "mnozstvi": "3", "cena": "10", "ulozit_do_ceniku": "1", "okno": "1"})
    assert r.status_code == 200 and "Použít z ceníku" in r.text and 'name="z_rucni" value="1"' in r.text
    cid = re.search(r'name="polozka_ceniku_id" value="(\d+)"', r.text).group(1)
    r = client.post(f"{loc}/polozky", data={"polozka_ceniku_id": cid, "mnozstvi": "3", "z_rucni": "1", "okno": "1"})
    assert r.status_code == 204 and "Přidat materiál z ceníku" not in r.text  # zpět na zakázku, ne do okna ceníku
    assert client.get(loc).text.count("<td>Brzdová kapalina</td>") == 2
    assert "Jiná kapalina" not in client.get("/cenik", params={"q": "kapalina"}).text
    # bez uložení do ceníku: jen řádek, cena zadaná s DPH se přepočte (zdroj „s“)
    client.post(f"{loc}/polozky", data={"typ": "prace", "nazev": "Odtah", "mnozstvi": "1", "cena_s": "1210",
                                        "cena": "", "cena_zdroj": "s", "sazba_dph": "21"})
    detail = client.get(loc).text
    assert "Odtah" in detail and "1 000,00" in detail
    assert "Nic nenalezeno" in client.get("/prace", params={"q": "Odtah"}).text  # do ceníku se neuložila


def test_smazani_zakazky_s_polozkami_s_potvrzenim():
    loc = _zakazka_s_polozkou()  # 1 položka práce
    client.post(f"{loc}/polozky", data={"typ": "material", "nazev": "Těsnění", "cena": "50"})
    uprava = client.get(f"{loc}/upravit").text  # #165: smazání je v okně Upravit zakázku
    assert f'action="{loc}/smazat" data-potvrdit=' in uprava and "nejdřív odeberte" not in uprava
    assert "Smaže se i materiál a práce na zakázce (2 položky)." in uprava
    r = client.post(f"{loc}/smazat", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/zakazky")
    assert client.get(loc).status_code == 404


def test_okno_ceniku_razeni_podle_kodu():
    """#28: okno ceníku řadí podle kódu (bez kódu na konec) a kód je tučně."""
    for kod, nazev in [("ZZ 9", "Akumulátor"), (None, "Bez kódu díl"), ("AA 1", "Žárovka H4"), ("MM 5", "Brzdy")]:
        data = {"typ": "material", "nazev": nazev, "cena": "10"}
        if kod:
            data["kod"] = kod
        client.post("/cenik/nova", data=data)
    loc = _prijem().headers["location"].split("?")[0]
    okno = client.get(f"{loc}/cenik", params={"typ": "material", "okno": "1"}).text
    poradi = [okno.index(t) for t in ("Žárovka H4", "Brzdy", "Akumulátor", "Bez kódu díl")]
    assert poradi == sorted(poradi)
    assert "<strong>AA 1</strong>" in okno and "<strong>Žárovka H4</strong>" not in okno


def test_zakazka_kopirovat_vin():
    """#45: v kartě Vozidlo na detailu zakázky jde VIN zkopírovat."""
    r = _prijem(spz="7K45454", v_vin="TMBJJ7NE8J0123456")
    detail = client.get(r.headers["location"].split("?")[0]).text
    assert 'data-kopirovat="TMBJJ7NE8J0123456"' in detail


def test_formulare_ceniku_dph_pod_cenami():
    """#42 a #43: sazba DPH (u materiálu i jednotka) je až pod cenami."""
    prace = client.get("/prace/nova").text
    material = client.get("/cenik/nova").text
    if 'name="sazba_dph"' in prace:  # plátce DPH
        assert prace.index('name="cena_s"') < prace.index('name="sazba_dph"')
        assert material.index('name="nakupni_cena_s"') < material.index('name="sazba_dph"')
    assert material.index('name="nakupni_cena') < material.index('name="jednotka"')
    assert material.index('name="nazev"') < material.index("<legend>Ceny za jednotku</legend>") \
        < material.index('name="jednotka"')


def test_kontrola_spz_a_prodej_pod_nakupem_v_sablonach():
    """#33: pole SPZ mají kontrolu tvaru (dotaz v prohlížeči), materiál má upozornění na prodej pod nákupní cenou."""
    assert "data-kontrola-spz" in client.get("/vozidla/nove").text
    assert "data-kontrola-spz" in client.get("/zakazky/nova").text
    assert "data-pod-nakupem" in client.get("/cenik/nova").text


def test_prazdny_pozadavek_a_interni_poznamka():
    """#40: prázdný požadavek ukáže „Nevyplněno · Doplnit“, interní poznámka je zvlášť."""
    loc = _prijem(spz="5P55555", pozadavek="", poznamka="Klíče na recepci").headers["location"].split("?")[0]
    detail = client.get(loc).text
    assert "Nevyplněno" in detail and f'href="{loc}/upravit" data-okno>Doplnit</a>' in detail
    assert 'class="interni-poznamka neni-tisk"' in detail and "Klíče na recepci" in detail


def test_karta_vozidla_udaje_jako_v_zakazce():
    """#47: vyplněné údaje jako seznam název: hodnota, motor = kód · objem · výkon, STK po termínu zvýrazněná."""
    r = client.post("/vozidla/nove", data={"spz": "4K44444", "znacka": "Škoda", "model": "Octavia", "vin": "TMBAA11U123456789",
                                           "rok_vyroby": "2015", "kod_motoru": "CRKB", "objem": "1968", "vykon": "110 kW",
                                           "palivo": "nafta", "termin_stk": "2020-01-01", "zakaznik_vyber": "bez"},
                    follow_redirects=False)
    karta = client.get(r.headers["location"].split("?")[0]).text.split('class="panel karta-vozidla"')[1].split("</section>")[0]
    poradi = ["<dt>VIN</dt>", "<dt>Rok výroby</dt>", ">Motor</dt>", "<dt>Druh paliva</dt>", "<dt>Termín STK</dt>"]
    assert [karta.index(t) for t in poradi] == sorted(karta.index(t) for t in poradi)
    assert "CRKB · 1968 · 110 kW" in karta and 'class="po-terminu"' in karta
    assert "<dt>Olej</dt>" not in karta and "Doplnit údaje vozidla" not in karta


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


def test_detail_vozidla_bez_tlacitka_otevrit():
    """Historie vozidla se otevírá jedním klikem, tlačítko Otevřít zakázku vlevo už není."""
    _zakazka_s_polozkou()
    vid = re.search(r'href="/vozidla/(\d+)"', client.get("/vozidla").text).group(1)
    for zalozka in ["zakazky", "prace", "material"]:
        text = client.get(f"/vozidla/{vid}", params={"zalozka": zalozka}).text
        assert "Otevřít zakázku<" not in text and 'data-radek="otevrit">' not in text, zalozka
    assert "klik-otevre" in client.get(f"/vozidla/{vid}").text


def test_detail_vozidla_a_zakaznika_sjednocene():
    """Vozidlo: lišta s nadpisem SPZ (bez rámečku), v panelu značka a typ; zákazník: bez panelu Poznámka,
    poznámka v souhrnu, vozidla a zakázky na jednom řádku."""
    loc = _prijem(spz="6S66666", k_poznamka="Platí hotově").headers["location"].split("?")[0]
    detail = client.get(loc).text
    vid = re.search(r'href="/vozidla/(\d+)"', detail).group(1)
    kid = re.search(r'href="/zakaznici/(\d+)"', detail).group(1)
    vozidlo = client.get(f"/vozidla/{vid}").text
    assert '<h1 class="nadpis-spz">6S66666</h1>' in vozidlo
    assert '<p class="hlavni-udaj hlavni-vozidla">Škoda Fabia</p>' in vozidlo
    zakaznik = client.get(f"/zakaznici/{kid}").text
    assert ">Poznámka</h2>" not in zakaznik and 'class="tlumene vedle">Zakázky</span>' in zakaznik


def test_horni_lista_nazev_firmy_a_logo():
    """Jedna horní lišta: menu vlevo, uprostřed název firmy (z Nastavení), vpravo hledání a ozubené kolo."""
    stranka = client.get("/zakazky").text
    assert 'class="horni-lista jedna-lista"' in stranka and 'aria-label="Nastavení"' in stranka
    assert "<span>Autoservis</span>" in stranka  # nic nevyplněno → výchozí
    client.post("/nastaveni", data={"nazev_servisu": "Servis Novák", "rada_faktura": "FV{RRRR}",
                                    "rada_vyuctovani": "VY{RRRR}"})
    assert "<span>Servis Novák</span>" in client.get("/zakazky").text
    png = bytes.fromhex("89504e470d0a1a0a0000000d4948445200000001000000010806000000"
                        "1f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082")
    r = client.post("/nastaveni", data={"nazev_v_liste": "Autoservis Novák", "rada_faktura": "FV{RRRR}",
                                        "rada_vyuctovani": "VY{RRRR}"},
                    files={"logo_soubor": ("logo.png", png, "image/png")}, follow_redirects=False)
    assert r.status_code == 303
    stranka = client.get("/zakazky").text
    assert "<span>Autoservis Novák</span>" in stranka and 'src="data:image/png;base64,' in stranka
    r = client.post("/nastaveni", data={"rada_faktura": "FV{RRRR}", "rada_vyuctovani": "VY{RRRR}"},
                    files={"logo_soubor": ("x.txt", b"text", "text/plain")})
    assert r.status_code == 422 and "Logo musí být obrázek" in r.text
    client.post("/nastaveni", data={"smazat_logo": "1", "rada_faktura": "FV{RRRR}", "rada_vyuctovani": "VY{RRRR}"})
    assert "data:image/png" not in client.get("/zakazky").text


# ---------------------------------------------------------------- #55: vystavení bez přepínače, vyúčtování

def test_vyuctovani_bez_prepinace_stav_a_qr():
    client.post("/nastaveni", data={"nazev_servisu": "Autoservis Test", "ico": "12345678", "dic": "CZ12345678", "mesto": "Brno",
                                    "cislo_uctu": "19-2000145399/0800", "ucet_vyuctovani": "", "platce_dph": "1",
                                    "zaokrouhlit_hotovost": "1", "vychozi_dph": "21",
                                    "rada_faktura": "FV{RRRR}", "rada_vyuctovani": "VY{RRRR}"})
    loc = _zakazka_s_polozkou()
    faktura = client.get(f"{loc}/vystavit?typ=faktura").text
    assert 'type="radio" name="typ"' not in faktura and 'name="typ" value="faktura"' in faktura
    assert 'name="forma_uhrady"' in faktura
    # bez účtu pro vyúčtování: výzva a vystavení neprojde (účet pro faktury se nepoužije)
    formular = client.get(f"{loc}/vystavit?typ=vyuctovani").text
    assert "Vystavit vyúčtování" in formular and 'type="radio" name="typ"' not in formular
    assert 'name="forma_uhrady"' not in formular and "účet pro QR platbu na vyúčtování" in formular
    assert client.post(f"{loc}/vystavit", data={"typ": "vyuctovani", "uhrazeno_ihned": "1"}).status_code == 422
    r = client.post("/nastaveni", data={"ucet_vyuctovani": "nesmysl", "platce_dph": "1", "zaokrouhlit_hotovost": "1",
                                        "rada_faktura": "FV{RRRR}", "rada_vyuctovani": "VY{RRRR}"})
    assert r.status_code == 422 and "Účet pro QR platbu" in r.text
    client.post("/nastaveni", data={"ucet_vyuctovani": "2001234567/2010", "platce_dph": "1", "zaokrouhlit_hotovost": "1",
                                    "rada_faktura": "FV{RRRR}", "rada_vyuctovani": "VY{RRRR}"})
    formular = client.get(f"{loc}/vystavit?typ=vyuctovani").text
    assert re.search(r'name="uhrazeno_ihned" value="1"\s+checked', formular)  # výchozí Uhrazeno

    # odškrtnuté Uhrazeno → Neuhrazeno
    r = client.post(f"{loc}/vystavit", data={"typ": "vyuctovani", "odb_nazev": "Jana Dvořáková"}, follow_redirects=False)
    assert r.status_code == 303
    doklad = r.headers["location"].split("?")[0]
    detail = client.get(doklad).text
    assert "Neuhrazeno" in detail and "Označit jako uhrazené" in detail and "Forma úhrady" not in detail
    assert "Zapsat úhradu" not in detail
    assert f'href="{doklad}/tisk?tisk=1" target="_blank"' in detail
    assert 'class="secondary outline tlacitko-tisk">Tisk / PDF</a>' in detail
    seznam = client.get("/faktury", params={"filtr": "vyuctovani"}).text
    assert doklad in seznam and "Neuhrazeno" in seznam

    # přepnout oběma směry – stav se shoduje v detailu i seznamu
    detail = client.post(f"{doklad}/uhrazeno", data={"uhrazeno": "1"}, follow_redirects=True).text
    assert "Označit jako neuhrazené" in detail
    assert "Uhrazeno</span>" in client.get("/faktury", params={"filtr": "vyuctovani"}).text
    detail = client.post(f"{doklad}/uhrazeno", data={"uhrazeno": "0"}, follow_redirects=True).text
    assert "Označit jako uhrazené" in detail
    assert "Neuhrazeno" in client.get("/faktury", params={"filtr": "vyuctovani"}).text

    # tisk: QR z účtu pro vyúčtování na celou částku, bez formy a stavu úhrady
    for stav in ("0", "1"):
        client.post(f"{doklad}/uhrazeno", data={"uhrazeno": stav})
        tisk = client.get(f"{doklad}/tisk").text
        assert "CZ4720100000002001234567" in tisk and "2001234567/2010" in tisk and "<svg" in tisk
        assert "19-2000145399/0800" not in tisk and "CZ6508000000192000145399" not in tisk
        assert "Forma úhrady" not in tisk and "neplaťte" not in tisk and "Hotově" not in tisk


def test_faktura_hotove_tisk_bez_qr():
    client.post("/nastaveni", data={"nazev_servisu": "Autoservis Test", "ico": "12345678", "dic": "CZ12345678", "mesto": "Brno",
                                    "cislo_uctu": "19-2000145399/0800", "platce_dph": "1", "vychozi_dph": "21",
                                    "rada_faktura": "FV{RRRR}", "rada_vyuctovani": "VY{RRRR}"})
    loc = _zakazka_s_polozkou()
    r = client.post(f"{loc}/vystavit", data={"typ": "faktura", "odb_nazev": "Jana Dvořáková", "forma_uhrady": "hotove"},
                    follow_redirects=False)
    tisk = client.get(f"{r.headers['location'].split('?')[0]}/tisk").text
    assert "Hotově" in tisk and "<svg" not in tisk


def test_splatnost_jen_u_faktury():
    """#58: vyúčtování nemá splatnost v okně vystavení, detailu ani tisku; faktura ano."""
    client.post("/nastaveni", data={"nazev_servisu": "Autoservis Test", "ico": "12345678", "dic": "CZ12345678", "mesto": "Brno",
                                    "cislo_uctu": "19-2000145399/0800", "ucet_vyuctovani": "2001234567/2010",
                                    "platce_dph": "1", "rada_faktura": "FV{RRRR}", "rada_vyuctovani": "VY{RRRR}"})
    loc = _zakazka_s_polozkou()
    assert 'name="datum_splatnosti"' not in client.get(f"{loc}/vystavit?typ=vyuctovani").text
    assert 'name="datum_splatnosti"' in client.get(f"{loc}/vystavit?typ=faktura").text
    r = client.post(f"{loc}/vystavit", data={"typ": "vyuctovani", "uhrazeno_ihned": "1"}, follow_redirects=False)
    doklad = r.headers["location"].split("?")[0]
    assert "<dt>Splatnost</dt>" not in client.get(doklad).text
    assert "splatnosti" not in client.get(f"{doklad}/tisk").text
    client.post(f"{doklad}/smazat")
    r = client.post(f"{loc}/vystavit", data={"typ": "faktura", "odb_nazev": "Jana", "forma_uhrady": "prevod"},
                    follow_redirects=False)
    doklad = r.headers["location"].split("?")[0]
    assert "<dt>Splatnost</dt>" in client.get(doklad).text
    assert "Datum splatnosti" in client.get(f"{doklad}/tisk").text


def test_zakazky_vychozi_razeni_od_nejstarsi():
    """#56: bez zvoleného řazení podle čísla vzestupně, ruční řazení zůstává."""
    for spz in ("1AA1111", "2BB2222", "3CC3333"):
        _prijem(spz=spz)
    text = client.get("/zakazky", params={"vse": "1"}).text
    cisla = re.findall(r"<strong>(\d{4}-\d{4})</strong>", text) or re.findall(r">(\d{4}-\d{4})<", text)
    assert len(cisla) >= 3 and cisla == sorted(cisla)
    opacne = re.findall(r">(\d{4}-\d{4})<", client.get("/zakazky", params={"vse": "1", "razeni": "-cislo"}).text)
    assert opacne[:3] == sorted(set(opacne), reverse=True)[:3]


def test_nastaveni_platce_dph_u_dic():
    """#52: zaškrtávátko Plátce DPH je hned u DIČ s nápovědou."""
    text = client.get("/nastaveni").text
    dic, platce, dph = text.index('name="dic"'), text.index('name="platce_dph"'), text.index("<legend>Ceny a DPH")
    assert dic < platce < dph and "DIČ je povinné jen pro plátce DPH" in text


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


def test_nastaveni_instalator_zastupce():
    """#71: v Nastavení jde stáhnout .bat s vyplněnou adresou serveru a skriptem zástupce."""
    from app.services import zastupce
    stranka = client.get("/nastaveni").text
    assert 'action="/nastaveni/zastupce"' in stranka and "Windows 10 nebo 11" in stranka
    r = client.get("/nastaveni/zastupce", params={"adresa": "server:8000/"})
    assert r.status_code == 200 and zastupce.NAZEV_SOUBORU in r.headers["content-disposition"]
    obsah = r.content.decode("utf-8")
    assert obsah.startswith("@echo off\r\n") and "-Adresa 'http://server:8000'" in obsah
    assert "\r\n#SKRIPT-AUTOSERVIS\r\n" in obsah and "CreateShortcut" in obsah and "﻿" not in obsah
    assert "--disable-print-preview" in obsah
    kandidati = obsah.split("$kandidati = @(", 1)[1].split("\r\n)", 1)[0]
    assert [radek.split("\\")[-1].rstrip('",') for radek in kandidati.splitlines() if radek.strip()] == [
        "chrome.exe", "chrome.exe", "chrome.exe", "msedge.exe", "msedge.exe",
    ]
    # nebezpečné znaky v adrese (cmd / PowerShell) se odmítnou
    r = client.get("/nastaveni/zastupce", params={"adresa": "http://x'; calc; '"}, follow_redirects=False)
    assert r.status_code == 303


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


def test_okno_materialu_enter_podle_kodu_a_tlacitka():
    """#96: řádky výsledků nesou kód dílu (Enter v hledání vloží přesnou shodu kódu, jinak otevře Nový
    s kódem z hledání); tlačítka v titulku okna jsou stejně velká a okno má okraj i vlevo."""
    client.post("/cenik/nova", data={"typ": "material", "kod": "GAT 6PK1018", "nazev": "Klínový řemen TEST",
                                     "cena": "300"})
    loc = _prijem().headers["location"].split("?")[0]
    zid = loc.rsplit("/", 1)[1]
    vyber = client.get("/cenik/vyber", params={"q": "6PK1018", "zakazka_id": zid, "okno": "1",
                                               "typ": "material"}).text
    assert 'data-kod="GAT 6PK1018"' in vyber
    okno = client.get(f"{loc}/cenik", params={"okno": "1", "typ": "material"}).text
    assert 'class="maly tlacitko-novy" data-okno' in okno and 'data-s-hledanim="kod"' in okno
    base = client.get(loc).text
    assert "function enterVHledaniMaterialu" in base and "kodProShodu(tr.dataset.kod) === hledany" in base
    css = client.get("/static/app.css").text
    assert ".okno-formular .rozvrzeni:not(.s-akcemi) > .obsah { padding-left: 20px; }" in css
    assert "text-overflow: ellipsis; }" in css and "width: 8.6rem; height: 2.4rem" in css


def test_okno_ceniku_tlacitka_vysoka_jako_v_zakazce():
    """#98: tlačítka v titulku okna ceníku (materiál i práce) mají výšku a písmo jako Ceník / Nový v zakázce."""
    css = client.get("/static/app.css").text
    assert "font-size: 1rem; line-height: calc(2.4rem - 2px)" in css
    assert ".tlacitka-hlavicky:not(.vlevo) > * { height: 2.4rem; padding: 0 .8rem; font-size: 1rem;" in css
    assert ".okno-hlavicka.hlavicka-na-stred { display: grid; grid-template-columns: auto 1fr auto; }" in css


def test_seznam_zakazek_vin_motor_stk_a_jednotne_kopirovat():
    """#99: seznam zakázek bez Požadavku, s VIN (Kopírovat), kódem motoru a platností STK (propadlá červeně);
    tlačítko Kopírovat je všude stejné (makro kopirovat)."""
    r = _prijem(spz="9ST0099", pozadavek="Výměna rozvodů TEST", v_vin="TMBTEST0000000099",
                v_kod_motoru="CAYC", v_termin_stk="01.01.2020")
    assert r.status_code == 303
    zakazka = r.headers["location"].split("?")[0]
    seznam = client.get("/zakazky").text
    hlavicka = re.search(r"<thead>.*?</thead>", seznam, re.S).group(0)
    assert "Požadavek" not in hlavicka
    for nazev in ("VIN", "Kód motoru", "Platnost STK"):
        assert nazev in hlavicka
    assert "Výměna rozvodů TEST" not in seznam
    assert 'data-kopirovat="TMBTEST0000000099"' in seznam and "CAYC" in seznam
    assert re.search(r'<td class="sl-stk"><span class="po-terminu"[^>]*>01\.01\.2020</span> <span class="stitek-po-terminu">po termínu', seznam)
    assert client.get("/zakazky", params={"razeni": "stk"}).status_code == 200
    assert client.get("/zakazky", params={"razeni": "-vin"}).status_code == 200
    tlacitko = ('<button type="button" class="kopirovat maly neni-tisk" data-kopirovat="TMBTEST0000000099" '
                'title="Zkopírovat VIN do schránky" aria-label="Zkopírovat VIN do schránky">\n<svg class="ik-kopie"')
    assert tlacitko in seznam
    assert tlacitko in client.get(zakazka).text
    assert tlacitko in client.get("/hledat", params={"q": "Výměna rozvodů"}).text


def test_okno_materialu_nejpouzivanejsi_a_oddelovac():
    """#102: okno Přidat materiál bez hledání ukáže nejpoužívanější díly (sloupec Použito); při hledání je přesný
    kód nahoře, pak používané (podbarvené) podle počtu, pak oddělovač a nepoužité."""
    for kod, nazev in [("FLT 100", "Filtr TEST A"), ("FLT 200", "Filtr TEST B"), ("FLT 300", "Filtr TEST C")]:
        client.post("/cenik/nova", data={"typ": "material", "kod": kod, "nazev": nazev, "cena": "100"})
    loc = _prijem(spz="9NP0102").headers["location"].split("?")[0]
    zid = loc.rsplit("/", 1)[1]

    def vyber(q=""):
        return client.get("/cenik/vyber", params={"q": q, "zakazka_id": zid, "okno": "1", "typ": "material"}).text

    ids = {k: re.search(rf'data-kod="{k}".*?name="polozka_ceniku_id" value="(\d+)"', vyber("FLT"), re.S).group(1)
           for k in ("FLT 100", "FLT 200", "FLT 300")}
    for kod, kolikrat in [("FLT 200", 3), ("FLT 300", 1)]:  # #113: často = aspoň 3×
        for _ in range(kolikrat):
            client.post(f"{loc}/polozky", data={"polozka_ceniku_id": ids[kod], "mnozstvi": "1"})

    prazdne = vyber()
    assert "Nejpoužívanější díly" in prazdne and ">Použito</th>" in prazdne
    assert prazdne.index('data-kod="FLT 200"') < prazdne.index('data-kod="FLT 300"')
    assert 'data-kod="FLT 100"' not in prazdne  # jen použité
    # #113: i mezi nejpoužívanějšími odděluje čára díly použité méně než 3×
    assert prazdne.index('data-kod="FLT 200"') < prazdne.index("Méně používané díly") < prazdne.index('data-kod="FLT 300"')

    hledani = vyber("flt")
    poradi = re.findall(r'data-kod="(FLT \d+)"', hledani)
    assert poradi == ["FLT 200", "FLT 300", "FLT 100"]
    # #113: čára za díly použitými aspoň 3×; FLT 300 (1×) už je pod ní, nepodbarvený
    assert hledani.index('data-kod="FLT 200"') < hledani.index("Méně používané díly") \
        < hledani.index('data-kod="FLT 300"') < hledani.index('data-kod="FLT 100"')
    assert re.search(r'data-kod="FLT 200" class="pouzivany"', hledani) and ">3×</td>" in hledani
    assert not re.search(r'data-kod="FLT 300" class="pouzivany"', hledani) and ">1×</td>" in hledani
    assert "Nejpoužívanější díly" not in hledani
    assert re.findall(r'data-kod="(FLT \d+)"', vyber("FLT100"))[0] == "FLT 100"  # přesný kód nahoře
    assert "Zaměnitelný díl" not in hledani  # #102: prázdný sloupec se neukazuje


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


def test_prijem_poradi_panelu_a_okno_zakazniku_na_jeden_radek():
    """#104: Nová zakázka – panely Vozidlo · Zakázka · Zákazník. #120: okno Databáze zákazníků bez štítků SPZ,
    ve sloupci Vozidla počet a první SPZ (všechny v bublině)."""
    form = client.get("/zakazky/nova").text
    assert form.index('id="panel-vozidlo"') < form.index("<legend>Zakázka</legend>") < form.index('id="panel-zakaznik"')
    r = _prijem(spz="9OK0120", k_nazev="Flotila TEST 120")
    assert r.status_code == 303
    zid = client.get("/hledat", params={"q": "Flotila TEST 120"}).text
    kid = re.search(r'href="/zakaznici/(\d+)"', zid).group(1)
    client.post("/vozidla/nove", data={"spz": "9OK0121", "zakaznik_id": kid})
    okno = client.get("/zakaznici/okno", params={"cil": "prijem", "q": "Flotila TEST 120"}).text
    radek = re.search(r"<tr>\s*<td[^>]*>Flotila TEST 120.*?</tr>", okno, re.S).group(0)
    assert 'class="spz' not in radek
    assert re.search(r'title="9OK012[01], 9OK012[01]">2 · 9OK012[01] …', radek)


def test_stk_vsude_stejne_po_terminu_a_nevyplneno():
    """#107: propadlá STK červeně se štítkem „po termínu“, prázdná šedě „nevyplněno“; seznam vozidel má sloupec
    Platnost STK s řazením."""
    r = client.post("/vozidla/nove", data={"spz": "9ST1071", "zakaznik_id": "bez", "termin_stk": "01.01.2020"},
                    follow_redirects=True)
    assert 'class="po-terminu"' in r.text and "po termínu" in r.text  # karta vozidla
    r = client.post("/vozidla/nove", data={"spz": "9ST1072", "zakaznik_id": "bez"}, follow_redirects=True)
    assert "Termín STK" in r.text and '<span class="nevyplneno">nevyplněno</span>' in r.text
    seznam = client.get("/vozidla", params={"q": "9ST107"}).text
    assert ">Platnost STK" in seznam and "po termínu" in seznam and "nevyplněno" in seznam
    assert client.get("/vozidla", params={"razeni": "stk"}).status_code == 200


def test_cenik_materialu_sloupec_pouzito():
    """#122: ceník materiálu ukazuje počet použití; podle něj jde řadit, výchozí řazení zůstává podle kódu."""
    client.post("/cenik/nova", data={"typ": "material", "kod": "AA122", "nazev": "Díl TEST 122 A", "cena": "10"})
    client.post("/cenik/nova", data={"typ": "material", "kod": "ZZ122", "nazev": "Díl TEST 122 Z", "cena": "10"})
    loc = _prijem(spz="9PU0122").headers["location"].split("?")[0]
    zid = loc.rsplit("/", 1)[1]
    vyber = client.get("/cenik/vyber", params={"q": "ZZ122", "zakazka_id": zid}).text
    cid = re.search(r'name="polozka_ceniku_id" value="(\d+)"', vyber).group(1)
    for _ in range(2):
        client.post(f"{loc}/polozky", data={"polozka_ceniku_id": cid, "mnozstvi": "1"})
    vychozi = client.get("/cenik", params={"q": "TEST 122"}).text
    assert ">Použito" in vychozi and ">2×</td>" in vychozi
    assert vychozi.index("AA122") < vychozi.index("ZZ122")  # výchozí podle kódu
    podle_pouziti = client.get("/cenik", params={"q": "TEST 122", "razeni": "-pouzito"}).text
    assert podle_pouziti.index("ZZ122") < podle_pouziti.index("AA122")


def test_cislo_dokladu_predpona_v_jednom_poli():
    """#106: předpona řady je uvnitř rámečku pole s pořadovým číslem."""
    css = client.get("/static/app.css").text
    assert ".cislo-dokladu-pole { display: inline-flex;" in css and "border: 0 !important" in css


def test_tisk_dokladu_sloupce_kod_a_s_dph_bez_poznamky_importu():
    """#127: kód ve vlastním sloupci, u položky cena s DPH; poznámka importu se netiskne, vlastní ano."""
    client.post("/nastaveni", data={"nazev_servisu": "Autoservis Test", "ico": "12345678", "dic": "CZ12345678", "mesto": "Brno",
                                    "cislo_uctu": "19-2000145399/0800", "platce_dph": "1", "vychozi_dph": "21",
                                    "rada_faktura": "FV{RRRR}", "rada_vyuctovani": "VY{RRRR}"})
    loc = _prijem().headers["location"].split("?")[0]
    client.post(f"{loc}/polozky", data={"typ": "material", "kod": "OPT FAF10128", "nazev": "Vzduchový filtr",
                                        "mnozstvi": "4.5", "cena": "350"})
    r = client.post(f"{loc}/vystavit", data={"typ": "faktura", "odb_nazev": "Jana", "forma_uhrady": "prevod",
                                             "poznamka": "Importováno ze starého systému\nDěkujeme za návštěvu."},
                    follow_redirects=False)
    doklad = r.headers["location"].split("?")[0]
    tisk = client.get(f"{doklad}/tisk").text
    assert "<th>Kód</th>" in tisk and '<td class="kod-polozky">OPT FAF10128</td>' in tisk and "(kód" not in tisk
    assert '<th class="cislo">S DPH</th>' in tisk
    cisla = re.sub(r"[\s\u00a0\u202f]|&nbsp;", "", tisk)
    assert "1575,00" in cisla and "1905,75" in cisla  # 4,5 × 350 = 1 575,00 bez DPH, s 21 % DPH 1 905,75
    assert "Importováno ze starého systému" not in tisk and "Děkujeme za návštěvu." in tisk
    assert "Importováno ze starého systému" in client.get(doklad).text  # detail poznámku ukazuje dál


def test_tisk_dokladu_neplatce_bez_sloupce_s_dph():
    client.post("/nastaveni", data={"nazev_servisu": "Autoservis Test", "mesto": "Brno", "platce_dph": "0",
                                    "rada_faktura": "FV{RRRR}", "rada_vyuctovani": "VY{RRRR}"})
    loc = _zakazka_s_polozkou()
    r = client.post(f"{loc}/vystavit", data={"typ": "vyuctovani", "uhrazeno_ihned": "1"}, follow_redirects=False)
    tisk = client.get(f"{r.headers['location'].split('?')[0]}/tisk").text
    assert "<th>Kód</th>" in tisk and "S DPH</th>" not in tisk


def test_kopirovat_vin_ikona_misto_napisu():
    """#154: tlačítko kopírování VIN je ikona (kopie + fajfka po zkopírování), bez nápisu Kopírovat."""
    from app.web.sablony import templates
    html = templates.env.from_string('{% from "_makra.html" import kopirovat %}{{ kopirovat("VIN123") }}').render()
    assert 'class="ik-kopie"' in html and 'class="ik-hotovo"' in html
    assert 'aria-label="Zkopírovat VIN do schránky"' in html
    assert re.sub(r"<[^>]+>", "", html).strip() == ""  # žádný viditelný text, jen ikony


def test_ikona_kopirovani_pred_vin_a_kodem_materialu():
    """#156: ikona kopírování je před VIN a před kódem materiálu (zakázka, ceník, Správa dat), u práce ne."""
    loc = _prijem(spz="1KO1560", v_vin="TMBKOPIE00000156A").headers["location"].split("?")[0]
    client.post(f"{loc}/polozky", data={"typ": "material", "kod": "OPT FAF10128", "nazev": "Vzduchový filtr",
                                        "mnozstvi": "1", "cena": "399"})
    client.post(f"{loc}/polozky", data={"typ": "prace", "kod": "MECH", "nazev": "Mechanická práce",
                                        "mnozstvi": "1", "cena": "450"})
    detail = client.get(loc).text
    # VIN: tlačítko před textem
    assert re.search(r'data-kopirovat="TMBKOPIE00000156A"[^>]*>.*?</button><span>TMBKOPIE00000156A</span>', detail, re.S)
    # kód materiálu s ikonou před kódem, práce bez ikony
    assert re.search(r'data-kopirovat="OPT FAF10128" title="Zkopírovat kód do schránky".*?</button>OPT FAF10128</td>', detail, re.S)
    assert 'data-kopirovat="MECH"' not in detail
    assert 'data-kopirovat="TMBKOPIE00000156A"' in client.get("/zakazky").text


def test_kod_materialu_tucne_v_zakazce_a_na_karte_vozidla():
    """#158: kód materiálu tučně (třída kod-materialu), kód práce šedě."""
    r = _prijem(spz="1TU1580", v_vin="TMBTUCNE0000158AB")
    loc = r.headers["location"].split("?")[0]
    client.post(f"{loc}/polozky", data={"typ": "material", "kod": "UFI 25.023.00", "nazev": "Olejový filtr",
                                        "mnozstvi": "1", "cena": "209"})
    client.post(f"{loc}/polozky", data={"typ": "prace", "kod": "MECH", "nazev": "Mechanická práce",
                                        "mnozstvi": "1", "cena": "450"})
    detail = client.get(loc).text
    assert re.search(r'<td class="kod-materialu kod-s-kopii">.*?</button>UFI 25\.023\.00</td>', detail, re.S)
    assert '<td class="tlumene kod-s-kopii">MECH</td>' in detail
    vozidlo = re.search(r'href="(/vozidla/\d+)"', detail).group(1)
    karta = client.get(vozidlo, params={"zalozka": "material"}).text
    assert '<td class="kod-materialu kod-s-kopii">' in karta


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


def test_rucni_cena_v_radku_zakazky_nemeni_cenik():
    """#163: cena za jednotku se mění přímo v řádku zakázky, ceník zůstane; rozdíl proti ceníku je vidět."""
    from app.services import cenik
    client.post("/nastaveni", data={"nazev_servisu": "Autoservis Test", "platce_dph": "1", "vychozi_dph": "21",
                                    "rada_faktura": "FV{RRRR}", "rada_vyuctovani": "VY{RRRR}"})
    client.post("/cenik/nova", data={"typ": "material", "kod": "OPT FAF10128", "nazev": "Vzduchový filtr",
                                     "jednotka": "ks", "cena": "1399", "sazba_dph": "21"})
    loc = _prijem(spz="1CE1630").headers["location"].split("?")[0]
    zid = loc.rsplit("/", 1)[1]
    vyber = client.get("/cenik/vyber", params={"q": "FAF10128", "zakazka_id": zid}).text
    cid = re.search(r'name="polozka_ceniku_id" value="(\d+)"', vyber).group(1)
    client.post(f"{loc}/polozky", data={"polozka_ceniku_id": cid, "mnozstvi": "2"})
    detail = client.get(loc).text
    rid = re.search(r'action="/polozky/(\d+)/cena"', detail).group(1)
    assert 'class="cena-ceniku"' not in detail  # cena z ceníku – žádný rozdíl
    # zápis s mezerou a čárkou jako v poli (1 299,50)
    r = client.post(f"/polozky/{rid}/cena", data={"cena": "1 299,50"}, follow_redirects=True)
    text = re.sub(r"\s+", " ", r.text.replace(" ", " "))
    assert 'value="1 299,50"' in text and "2 599,00" in text and "3 144,79" in text  # 2 × 1 299,50 bez / s DPH
    # ceníková cena přeškrtnutě vlevo od pole, ve stejném řádku (bez <br>)
    assert '<s class="cena-ceniku" title="Cena v ceníku – v zakázce upravená ručně">1 399,00</s> <input' in text
    assert 'ceník 1 399,00' not in text
    from app.db import get_session
    s = next(app.dependency_overrides[get_session]())
    assert cenik.ziskej(s, int(cid)).cena == 1399  # ceník beze změny
    # chybná cena se neuloží
    from urllib.parse import unquote
    r = client.post(f"/polozky/{rid}/cena", data={"cena": "-5"}, follow_redirects=False)
    assert r.status_code == 303 and "Cena nemůže být záporná." in unquote(r.cookies.get("zprava", ""))
    r = client.post(f"/polozky/{rid}/cena", data={"cena": ""}, follow_redirects=False)
    assert "Vyplňte cenu za jednotku." in unquote(r.cookies.get("zprava", ""))
    r = client.get(loc)
    assert 'value="1 299,50"' in re.sub(r"\s+", " ", r.text.replace(" ", " "))
    # vyúčtovaná zakázka: pole není a cenu nejde změnit
    client.post(f"{loc}/vystavit", data={"typ": "vyuctovani", "uhrazeno_ihned": "1"})
    assert f'action="/polozky/{rid}/cena"' not in client.get(loc).text
    r = client.post(f"/polozky/{rid}/cena", data={"cena": "1"}, follow_redirects=False)
    assert "vyúčtovaná" in unquote(r.cookies.get("zprava", ""))


def test_seznam_zakazek_jen_otevrene_a_uzavrene():
    """#166: předaná zakázka (bez dokladu) zůstává mezi otevřenými; filtr má jen Otevřené, Uzavřené a Všechny."""
    loc = _prijem(spz="1PR1660").headers["location"].split("?")[0]
    client.post(f"{loc}/stav", data={"stav": "hotovo"})
    seznam = client.get("/zakazky").text
    assert "1PR1660" in seznam
    assert "Předané" not in seznam and "Uzavřené" in seznam and "Otevřené (1)" in seznam
    assert "Zakázka zůstává otevřená, dokud není doklad." in client.get(loc).text
    # uzavřená bez dokladu → mezi uzavřenými
    client.post(f"{loc}/stav", data={"stav": "predano", "bez_dokladu": "1"})
    assert "1PR1660" not in client.get("/zakazky").text
    assert "1PR1660" in client.get("/zakazky", params={"stav": "predano"}).text


def test_stav_tisku_dokladu():
    """#167: sloupec Tisk v seznamu, otevření náhledu stav nemění, potvrzení / zrušení ručně."""
    client.post("/nastaveni", data={"nazev_servisu": "Autoservis Test", "platce_dph": "1", "vychozi_dph": "21",
                                    "rada_faktura": "FV{RRRR}", "rada_vyuctovani": "VY{RRRR}"})
    loc = _zakazka_s_polozkou(spz="1TI1670")
    r = client.post(f"{loc}/vystavit", data={"typ": "vyuctovani", "uhrazeno_ihned": "1"}, follow_redirects=False)
    doklad = r.headers["location"].split("?")[0]
    seznam = client.get("/faktury", params={"rok": "vse"}).text
    assert "<th>Tisk</th>" in seznam and 'class="stav-tisku nevytisteno"' in seznam
    tisk = client.get(f"{doklad}/tisk", params={"tisk": "1"}).text
    assert 'id="po-tisku" hidden' in tisk and "Ano, označit jako vytištěné" in tisk
    assert 'class="stav-tisku nevytisteno"' in client.get(doklad).text  # náhled stav nezměnil
    client.post(f"{doklad}/vytisteno", data={"vytisteno": "1"})
    detail = client.get(doklad).text
    assert 'class="stav-tisku vytisteno" title="Vytištěno ' in detail and "Zrušit označení tisku" in detail
    assert 'class="stav-tisku vytisteno"' in client.get("/faktury", params={"rok": "vse"}).text
    client.post(f"{doklad}/vytisteno", data={"vytisteno": "0"})
    assert "Označit jako vytištěné" in client.get(doklad).text


def test_stare_doklady_oznaci_jako_vytistene(engine, session):
    """#167: při zavedení stavu tisku se doklady ze starého systému označí jako vytištěné, ostatní ne."""
    from app.db import oznacit_stare_doklady_vytistene
    from app.models import Faktura
    session.add(Faktura(cislo="SS1", odb_nazev="A", poznamka="Importováno ze starého systému"))
    session.add(Faktura(cislo="FV1", odb_nazev="B", poznamka="vlastní"))
    session.commit()
    assert oznacit_stare_doklady_vytistene(engine) == 1
    session.expire_all()
    stav = {f.cislo: f.vytisteno for f in session.exec(__import__("sqlmodel").select(Faktura)).all()}
    assert stav == {"SS1": True, "FV1": False}


def test_tisk_dokladu_mensi_pismo_polozek():
    """#177: položky na tištěném dokladu 8 pt, zakázkový list beze změny."""
    loc = _zakazka_s_polozkou(spz="1PI1770")
    r = client.post(f"{loc}/vystavit", data={"typ": "vyuctovani", "uhrazeno_ihned": "1"}, follow_redirects=False)
    tisk = client.get(f"{r.headers['location'].split('?')[0]}/tisk").text
    assert "table.polozky td { font-size: 8pt;" in tisk
    # #179: číselné sloupce na šířku obsahu, Kód pevně 38 mm – zbytek pro Položku
    assert "table.polozky th.cislo, table.polozky td.cislo { width: 1%; }" in tisk and "width: 38mm" in tisk
    assert "table.polozky td { font-size: 8pt;" not in client.get(f"{loc}/tisk").text


def test_tisk_faktury_bez_napisu_uhrazeno():
    """#181: uhrazená faktura se tiskne bez nápisu „Uhrazeno – neplaťte.“"""
    client.post("/nastaveni", data={"nazev_servisu": "Autoservis Test", "ico": "12345678", "dic": "CZ12345678", "mesto": "Brno",
                                    "cislo_uctu": "19-2000145399/0800", "platce_dph": "1", "vychozi_dph": "21",
                                    "rada_faktura": "FV{RRRR}", "rada_vyuctovani": "VY{RRRR}"})
    loc = _zakazka_s_polozkou(spz="1NP1810")
    r = client.post(f"{loc}/vystavit", data={"typ": "faktura", "odb_nazev": "Jana", "forma_uhrady": "hotove",
                                             "uhrazeno_ihned": "1"}, follow_redirects=False)
    doklad = r.headers["location"].split("?")[0]
    assert "Uhrazeno" in client.get(doklad).text
    assert "neplaťte" not in client.get(f"{doklad}/tisk").text


def test_prehled_faktur_pamatuje_typ_dokladu():
    """#183: přehled Faktury z menu ukáže naposledy zvolené Vyúčtování / Faktury."""
    c = TestClient(app)
    assert 'aria-current="true">Vyúčtování' in c.get("/faktury").text  # výchozí
    c.get("/faktury", params={"filtr": "faktury"})
    assert 'aria-current="true">Faktury' in c.get("/faktury").text
    c.get("/faktury", params={"filtr": "vyuctovani"})
    assert 'aria-current="true">Vyúčtování' in c.get("/faktury").text
    c.cookies.set("doklady", "nesmysl")
    assert 'aria-current="true">Vyúčtování' in c.get("/faktury").text


def test_ovladani_sipkami_znacky_v_sablonach():
    """#185: Insert má v seznamech a v detailu zakázky svůj cíl (data-insert), stavový řádek ukazuje nápovědu kláves."""
    for url in ("/zakazky", "/vozidla", "/zakaznici", "/cenik", "/prace"):
        assert "data-insert" in client.get(url).text, url
    loc = _zakazka_s_polozkou(spz="1KL1850")
    detail = client.get(loc).text
    assert re.search(r'cenik\?typ=material" role="button" data-okno data-insert', detail)
    assert "↑↓ výběr · Enter otevřít" in client.get("/vozidla").text
    assert "radkyKlavesnici" in detail  # obsluha kláves je v base.html


def test_kopirovani_nahradne_pres_udalost_copy():
    """#195: náhradní kopírování (http) vkládá text přímo v události copy a fajfku ukáže jen při úspěchu."""
    stranka = client.get("/zakazky").text
    assert "function kopirujNahradne(text)" in stranka
    assert 'ev.clipboardData.setData("text/plain", text)' in stranka
    assert "Kopírování se nepovedlo" in stranka


def test_okna_ceniku_a_historie_jednotna_hlavicka():
    """#197: hlavička oken ceníku a historie – nadpis na středu, tlačítka nad hledáním, hláška dole."""
    import pathlib
    css = (pathlib.Path(__file__).parent.parent / "app/web/static/app.css").read_text(encoding="utf-8")
    assert "grid-template-columns: 1fr auto 1fr" in css
    assert ".okno-cenik > .hlaseni-okna { position: absolute;" in css
    assert ".okno-historie .okno-hlavicka .tlacitka-hlavicky.vlevo > button[type=submit]" in css
