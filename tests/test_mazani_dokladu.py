"""#15: mazání dokladů a ruční volba čísla – stejně pro faktury i vyúčtování, každý typ ve své řadě."""
from datetime import date

import pytest

from app.models import TypDokladu
from app.services import ChybaValidace, faktury, nastaveni, polozky, zakazky
from tests.test_web import client

ROK = date.today().year
PREDPONY = {TypDokladu.FAKTURA: f"FV{ROK}", TypDokladu.VYUCTOVANI: f"VY{ROK}"}
FILTRY = {TypDokladu.FAKTURA: "faktury", TypDokladu.VYUCTOVANI: "vyuctovani"}


@pytest.fixture(autouse=True)
def udaje_servisu(session):
    nastaveni.uloz(session, {"nazev_servisu": "Servis Test", "ico": "12345678", "dic": "CZ12345678",
                             "mesto": "Brno", "cislo_uctu": "19-2000145399/0800",
                             "ucet_vyuctovani": "2001234567/2010"})


_spz = iter(range(1000, 9999))


def _zakazka(session):
    z = zakazky.prijem(session, zakazka={"pozadavek": "Servis"}, vozidlo={"spz": f"1T{next(_spz)}"},
                       zakaznik={"nazev": "Jan Novák"})
    polozky.pridej_rucne(session, z.id, {"typ": "prace", "nazev": "Výměna", "mnozstvi": "1", "cena": "100"})
    session.refresh(z)
    return z


def _vystav(session, typ, poradi=""):
    z = _zakazka(session)
    data = faktury.vychozi_udaje(session, z.id, typ) | {"forma_uhrady": "hotove", "poradi": poradi}
    return faktury.vystav(session, z.id, data)


def _stav_rady(session, typ):
    """Čísla dokladů, volná čísla a další nabízené číslo řady – druhá řada se nesmí změnit."""
    cisla = sorted(f.cislo for f in faktury.seznam(session, "vse") if getattr(f, "typ", None) == typ
                   and not getattr(f, "je_volne_misto", False))
    return cisla, [c.cislo for c in faktury.volna_cisla(session, typ)], faktury.dalsi_cislo(session, typ)


@pytest.mark.parametrize("typ,druhy", [(TypDokladu.FAKTURA, TypDokladu.VYUCTOVANI),
                                       (TypDokladu.VYUCTOVANI, TypDokladu.FAKTURA)])
def test_scenare_z_issue(session, typ, druhy):
    p = PREDPONY[typ]
    _vystav(session, druhy)  # druhá řada má svůj doklad, nesmí se nic z ní pohnout
    druha = _stav_rady(session, druhy)

    # jsou vystavené 0042 až 0044 (první ruční číslo, další automaticky navazují)
    prvni = _vystav(session, typ, "42")
    assert prvni.cislo == f"{p}0042"
    _vystav(session, typ)
    _vystav(session, typ)
    assert _stav_rady(session, typ)[0] == [f"{p}0042", f"{p}0043", f"{p}0044"]

    # 1) smazat 0042: označená mezera, ostatní čísla stejná, nabídne se 0045
    faktury.smaz(session, prvni.id)
    assert _stav_rady(session, typ) == ([f"{p}0043", f"{p}0044"], [f"{p}0042"], f"{p}0045")
    assert _stav_rady(session, druhy) == druha
    seznam = client.get("/faktury", params={"filtr": FILTRY[typ]}).text
    radek = seznam.split(f"{p}0042")[1].split("</tr>")[0]
    assert "Volné po smazání" in radek
    assert f"{p}0042" not in client.get("/faktury", params={"filtr": FILTRY[druhy]}).text
    formular = client.get(f"/zakazky/{_zakazka(session).id}/vystavit", params={"typ": typ}).text
    assert f">{p}</span>" in formular and 'value="0045"' in formular and f">{p}0042</button>" in formular

    # 2) přepsat návrh na 0042: číslo se použije, mezera zmizí, příště opět 0045
    znovu = _vystav(session, typ, "0042")
    assert znovu.cislo == f"{p}0042"
    assert _stav_rady(session, typ) == ([f"{p}0042", f"{p}0043", f"{p}0044"], [], f"{p}0045")
    assert _stav_rady(session, druhy) == druha
    assert "Volné po smazání" not in client.get("/faktury", params={"filtr": FILTRY[typ]}).text

    # 3) obsazené číslo 0043: chyba, doklad se nevystaví
    z = _zakazka(session)
    with pytest.raises(ChybaValidace, match=f"{p}0043 už má jiný doklad"):
        faktury.vystav(session, z.id, faktury.vychozi_udaje(session, z.id, typ)
                       | {"forma_uhrady": "hotove", "poradi": "0043"})
    session.rollback()
    session.refresh(z)
    assert z.platna_faktura is None and _stav_rady(session, typ)[0] == [f"{p}0042", f"{p}0043", f"{p}0044"]
    # web: hláška u formuláře a vyplněné údaje zůstanou
    r = client.post(f"/zakazky/{z.id}/vystavit", data={"typ": typ, "odb_nazev": "Odběratel Zůstane",
                                                       "forma_uhrady": "hotove", "poradi": "0043"})
    assert r.status_code == 422 and "už má jiný doklad" in r.text
    assert 'value="Odběratel Zůstane"' in r.text and 'value="0043"' in r.text

    # smazání posledního čísla: automatické číslování se nevrátí zpět
    posledni = next(f for f in faktury.seznam(session, "vse") if f.cislo == f"{p}0044")
    faktury.smaz(session, posledni.id)
    assert _stav_rady(session, typ)[1:] == ([f"{p}0044"], f"{p}0045")
    assert _stav_rady(session, druhy) == druha


def test_kontrola_tvaru_cisla(session):
    for spatne in ["abc", "12345", "0", "-1", "4 2x"]:
        with pytest.raises(ChybaValidace, match="pořadové číslo"):
            faktury.cislo_z_poradi(session, TypDokladu.FAKTURA, ROK, spatne)
    assert faktury.cislo_z_poradi(session, TypDokladu.FAKTURA, ROK, " 7 ") == f"FV{ROK}0007"
    assert faktury.cislo_z_poradi(session, TypDokladu.FAKTURA, 2025, "7") == "FV20250007"  # rok podle data


def test_potvrzeni_smazani_a_zruseni(session):
    """4) Zrušené potvrzení = žádný POST; doklad zůstane. Potvrzení obsahuje číslo dokladu."""
    f = _vystav(session, TypDokladu.FAKTURA)
    detail = client.get(f"/faktury/{f.id}").text
    assert f"Smazat fakturu {f.cislo}?" in detail and f'action="/faktury/{f.id}/smazat"' in detail
    assert client.get(f"/faktury/{f.id}").status_code == 200
    v = _vystav(session, TypDokladu.VYUCTOVANI)
    assert f"Smazat vyúčtování {v.cislo}?" in client.get(f"/faktury/{v.id}").text


def test_smazani_v_souhrnu_a_hledani(session):
    f = _vystav(session, TypDokladu.FAKTURA)
    _vystav(session, TypDokladu.FAKTURA)
    faktury.smaz(session, f.id)
    seznam = faktury.seznam(session, "faktury")
    assert faktury.souhrn(seznam).pocet == 1  # volné místo se do počtu ani součtu nepočítá
    assert any(getattr(x, "je_volne_misto", False) for x in faktury.seznam(session, "vse", hledat=f.cislo))
    assert not any(getattr(x, "je_volne_misto", False) for x in faktury.seznam(session, "vse", hledat="Novák"))
    for razeni in ["cislo", "vystaveno", "splatnost", "odberatel", "vozidlo", "celkem", "zbyva", "stav"]:
        assert client.get("/faktury", params={"razeni": razeni}).status_code == 200
