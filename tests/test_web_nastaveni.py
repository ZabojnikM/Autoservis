"""Testy webu – nastavení a horní lišta (rozděleno z test_web.py, #233)."""
import re
from tests.web_pomucky import client
from tests.web_pomucky import ucet_pro_vyuctovani  # noqa: F401 – fixtury (autouse)


def test_nastaveni_ulozeni():
    r = client.post("/nastaveni", data={"vychozi_dph": "12", "mena": "Kč"}, follow_redirects=True)
    assert "Nastavení uloženo" in r.text
    assert not re.search(r'name="platce_dph" value="1"\s+checked', r.text)  # nezaškrtnuto → neplátce
    assert 'name="vychozi_dph" value="12"' in r.text
    assert "normohodin" not in r.text


def test_nastaveni_ma_tlacitko_v_akcich():
    r = client.get("/nastaveni").text
    assert 'form="formular-nastaveni"' in r and 'id="formular-nastaveni"' in r


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


def test_nastaveni_platce_dph_u_dic():
    """#52: zaškrtávátko Plátce DPH je hned u DIČ s nápovědou."""
    text = client.get("/nastaveni").text
    dic, platce, dph = text.index('name="dic"'), text.index('name="platce_dph"'), text.index("<legend>Ceny a DPH")
    assert dic < platce < dph and "DIČ je povinné jen pro plátce DPH" in text


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
