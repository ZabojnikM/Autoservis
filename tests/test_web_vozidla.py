"""Testy webu – vozidla a zákazníci (rozděleno z test_web.py, #233)."""
import re
from tests.web_pomucky import client, _prijem, _zakazka_s_polozkou, _je_okno
from tests.web_pomucky import ucet_pro_vyuctovani  # noqa: F401 – fixtury (autouse)


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


def test_vyber_zakaznika():
    _prijem()
    r = client.get("/zakaznici/vyber", params={"q": "dvoř", "pole": "zakaznik_vyber", "novy": "1"})
    assert "Jana Dvořáková" in r.text and "Nový zákazník" in r.text


def test_novy_zakaznik_a_vozidlo():
    r = client.post("/zakaznici/novy", data={"nazev": "Auto Plus s.r.o.", "ico": "12345678"},
                    follow_redirects=False)
    zid = r.headers["location"].rsplit("/", 1)[1]
    r = client.post("/vozidla/nove", data={"spz": "2ab0001", "zakaznik_id": zid}, follow_redirects=True)
    assert "2AB0001" in r.text and "Auto Plus" in r.text
    r = client.post("/vozidla/nove", data={"spz": "2AB 0001"})
    assert r.status_code == 422 and "už v evidenci" in r.text


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

    # vyúčtování jde i bez zákazníka, faktura jen s odběratelem (#208: vybere se v okně vystavení)
    client.post(f"{loc}/polozky", data={"typ": "material", "nazev": "Díl", "mnozstvi": "1", "cena": "100"})
    assert "Vystavit fakturu" in client.get(loc).text
    okno = client.get(f"{loc}/vystavit?typ=faktura").text
    assert "Zakázka nemá zákazníka" in okno and 'id="panel-odberatel"' in okno
    r = client.post(f"{loc}/vystavit", data={"typ": "faktura", "odb_nazev": "", "zakaznik_id": ""})
    assert r.status_code == 422 and "Vyplňte odběratele" in r.text
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
