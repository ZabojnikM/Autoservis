"""Testy webu – doklady, úhrady a tisk (rozděleno z test_web.py, #233)."""
import re
from fastapi.testclient import TestClient
from app.main import app
from tests.web_pomucky import client, _prijem, _zakazka_s_polozkou, _je_okno
from tests.web_pomucky import ucet_pro_vyuctovani  # noqa: F401 – fixtury (autouse)


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
