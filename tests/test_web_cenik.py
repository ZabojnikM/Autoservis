"""Testy webu – ceník a okna ceníku (rozděleno z test_web.py, #233)."""
import re
from app.main import app
from tests.web_pomucky import client, _se_skriptem, _prijem, _je_okno
from tests.web_pomucky import ucet_pro_vyuctovani  # noqa: F401 – fixtury (autouse)


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
    base = _se_skriptem(client.get(loc).text)
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


def test_okna_ceniku_a_historie_jednotna_hlavicka():
    """#197: hlavička oken ceníku a historie – nadpis na středu, tlačítka nad hledáním, hláška dole."""
    import pathlib
    css = (pathlib.Path(__file__).parent.parent / "app/web/static/app.css").read_text(encoding="utf-8")
    assert "grid-template-columns: 1fr auto 1fr" in css
    assert ".okno-cenik > .hlaseni-okna { position: absolute;" in css
    assert ".okno-historie .okno-hlavicka .tlacitka-hlavicky.vlevo > button[type=submit]" in css
