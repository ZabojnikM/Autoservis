from datetime import date, timedelta
from decimal import Decimal

import pytest

from sqlmodel import select

from app.models import Faktura, StavZakazky, TypDokladu, Uhrada
from app.services import ChybaValidace, cenik, faktury, nastaveni, polozky, zakazky


@pytest.fixture
def zakazka(session):
    # bez údajů servisu a účtu fakturu vystavit nejde
    nastaveni.uloz(session, {"nazev_servisu": "Servis Test", "ico": "12345678", "dic": "CZ12345678", "mesto": "Brno",
                             "cislo_uctu": "19-2000145399/0800", "ucet_vyuctovani": "2001234567/2010"})
    z = zakazky.prijem(
        session, zakazka={"pozadavek": "Servis", "tachometr": "120000"},
        vozidlo={"spz": "1AB2345", "znacka": "Škoda", "model": "Fabia"},
        zakaznik={"nazev": "Jan Novák", "ulice": "Hlavní 1", "mesto": "Brno", "psc": "60200"},
    )
    filtr = cenik.vytvor(session, {"nazev": "Olejový filtr", "cena": "250"})
    polozky.pridej_z_ceniku(session, z.id, filtr.id, mnozstvi="1")
    polozky.pridej_rucne(session, z.id, {"typ": "prace", "nazev": "Výměna", "mnozstvi": "0,5", "cena": "800"})
    session.refresh(z)
    return z  # 250 + 400 = 650 bez DPH, 786,50 s DPH


def _vystav(session, z, **data):
    vychozi = faktury.vychozi_udaje(session, z.id, data.get("typ", TypDokladu.FAKTURA))
    return faktury.vystav(session, z.id, vychozi | data)


def test_iban_z_cisla_uctu():
    assert faktury.iban_z_cisla_uctu("19-2000145399/0800") == "CZ6508000000192000145399"
    assert faktury.iban_z_cisla_uctu("nesmysl") is None


def test_predpona_a_cislovani(session, zakazka):
    assert faktury.predpona_rady("FV{RRRR}", 2026) == "FV2026"
    assert faktury.predpona_rady("F{RR}-", 2026) == "F26-"
    f = _vystav(session, zakazka)
    assert f.cislo == f"FV{date.today().year}0001"
    assert f.variabilni_symbol == f"{date.today().year}0001"
    assert faktury.dalsi_cislo(session, TypDokladu.FAKTURA).endswith("0002")
    assert faktury.dalsi_cislo(session, TypDokladu.VYUCTOVANI).endswith("0001")


def test_vystaveni_faktury(session, zakazka):
    f = _vystav(session, zakazka)
    assert f.celkem == Decimal("786.50") and f.zaokrouhleni == 0
    assert f.odb_nazev == "Jan Novák" and f.odb_mesto == "Brno"
    assert f.spz == "1AB2345" and f.cislo_zakazky == zakazka.cislo and f.tachometr == 120000
    assert len(f.polozky) == 2 and f.datum_splatnosti == date.today() + timedelta(days=14)
    assert f.stav == "neuhrazena" and f.zbyva == Decimal("786.50")
    session.refresh(zakazka)
    assert zakazka.stav == StavZakazky.PREDANO and zakazka.platna_faktura.id == f.id


def test_faktura_je_kopie_zakazky(session, zakazka):
    f = _vystav(session, zakazka)
    cenik.uprav(session, cenik.seznam(session)[0].id, {"cena": "9999"})
    session.refresh(f)
    assert f.celkem == Decimal("786.50")


def test_nelze_vystavit_dvakrat_ani_prazdnou(session, zakazka):
    _vystav(session, zakazka)
    with pytest.raises(ChybaValidace):
        _vystav(session, zakazka)
    prazdna = zakazky.prijem(session, zakazka={"pozadavek": "x"}, vozidlo={"spz": "1AB2345"})
    with pytest.raises(ChybaValidace):
        _vystav(session, prazdna)


def test_vyuctovani_zaokrouhli_a_vychozi_uhrazeno(session, zakazka):
    assert faktury.vychozi_udaje(session, zakazka.id, TypDokladu.VYUCTOVANI)["uhrazeno_ihned"] == "1"
    f = _vystav(session, zakazka, typ=TypDokladu.VYUCTOVANI)
    assert f.cislo.startswith("VY") and f.forma_uhrady == ""  # #55: vyúčtování formu úhrady nemá
    assert f.celkem == Decimal("787") and f.zaokrouhleni == Decimal("0.50")
    assert f.je_uhrazena and f.stav == "uhrazena" and f.uhrady[0].zpusob == ""


def test_vyuctovani_neuhrazene_a_prepinani_stavu(session, zakazka):
    """#55: odškrtnuté Uhrazeno → Neuhrazeno; stav jde přepínat oběma směry bez duplicit a bez ztráty historie."""
    f = _vystav(session, zakazka, typ=TypDokladu.VYUCTOVANI, uhrazeno_ihned="")
    assert f.stav == "neuhrazena" and not f.uhrady
    f = faktury.nastav_uhrazeno(session, f.id, True)
    f = faktury.nastav_uhrazeno(session, f.id, True)  # opakované přepnutí nic nezdvojí
    assert f.je_uhrazena and len(f.uhrady) == 1 and f.uhrady[0].castka == Decimal("787")
    f = faktury.nastav_uhrazeno(session, f.id, False)
    f = faktury.nastav_uhrazeno(session, f.id, False)
    assert f.stav == "neuhrazena" and len(f.uhrady) == 1 and f.uhrady[0].zruseno  # historie zůstala
    f = faktury.nastav_uhrazeno(session, f.id, True)
    assert f.je_uhrazena and len(f.platne_uhrady) == 1 and len(f.uhrady) == 2
    assert f.celkem == Decimal("787")  # částka se nemění
    assert [d.id for d in faktury.seznam(session, "vyuctovani") if d.stav == "uhrazena"] == [f.id]


def test_prepnuti_stavu_jen_u_vyuctovani(session, zakazka):
    f = _vystav(session, zakazka)
    with pytest.raises(ChybaValidace, match="jen u vyúčtování"):
        faktury.nastav_uhrazeno(session, f.id, True)


def test_vyuctovani_vyzaduje_vlastni_ucet(session, zakazka):
    """#55: bez účtu pro vyúčtování nejde vystavit – účet pro faktury se nepoužije."""
    nastaveni.uloz(session, {"ucet_vyuctovani": ""})
    with pytest.raises(ChybaValidace, match="účet pro QR platbu na vyúčtování"):
        _vystav(session, zakazka, typ=TypDokladu.VYUCTOVANI)
    with pytest.raises(ChybaValidace, match="Účet pro QR platbu"):
        nastaveni.uloz(session, {"ucet_vyuctovani": "nesmysl"})
    with pytest.raises(ChybaValidace):
        nastaveni.uloz(session, {"ucet_vyuctovani": "CZ6608000000192000145399"})  # chybný kontrolní součet
    assert nastaveni.uloz(session, {"ucet_vyuctovani": "CZ47 2010 0000 0020 0123 4567"}).ucet_vyuctovani


def test_uhrady(session, zakazka):
    f = _vystav(session, zakazka)
    faktury.pridej_uhradu(session, f.id, {"castka": "500"})
    session.refresh(f)
    assert f.zbyva == Decimal("286.50") and not f.je_uhrazena
    with pytest.raises(ChybaValidace):
        faktury.pridej_uhradu(session, f.id, {"castka": "300"})  # přeplatek
    u = faktury.pridej_uhradu(session, f.id, {"castka": "286,50", "zpusob": "hotove"})
    session.refresh(f)
    assert f.je_uhrazena
    faktury.pridej_uhradu(session, f.id, {"castka": "-100"})  # vrácení
    session.refresh(f)
    assert f.zbyva == Decimal("100.00")
    assert faktury.smaz_uhradu(session, u.id) == f.id


def test_po_splatnosti(session, zakazka):
    stare = date.today() - timedelta(days=30)
    f = _vystav(session, zakazka, datum_vystaveni=stare, duzp=stare, datum_splatnosti=stare + timedelta(days=7))
    assert f.stav == "po_splatnosti"
    assert [x.id for x in faktury.seznam(session, "po_splatnosti")] == [f.id]
    assert faktury.seznam(session, "uhrazene") == []


def test_smazani_otevre_zakazku(session, zakazka):
    f = _vystav(session, zakazka)
    with pytest.raises(ChybaValidace):
        zakazky.zmen_stav(session, zakazka.id, StavZakazky.V_OPRAVE)  # vyfakturovaná
    faktury.pridej_uhradu(session, f.id, {"castka": "100"})
    session.refresh(f)
    assert f.stav == "castecne" and f.nazev_stavu == "Částečně uhrazeno"
    # smazání s úhradou: doklad i úhrady zmizí, číslo zůstane jako volné (#15)
    fid, cislo = f.id, f.cislo
    assert faktury.smaz(session, fid) == (cislo, zakazka.id)
    assert session.get(Faktura, fid) is None and not session.exec(select(Uhrada)).all()
    assert [c.cislo for c in faktury.volna_cisla(session, TypDokladu.FAKTURA)] == [cislo]
    session.refresh(zakazka)
    assert zakazka.stav == StavZakazky.PRIJATO and zakazka.platna_faktura is None and not zakazka.uzavreno
    nova = _vystav(session, zakazka)
    assert nova.cislo.endswith("0002")  # smazané číslo se automaticky znovu nenabídne
    with pytest.raises(ChybaValidace):
        zakazky.smaz(session, zakazka.id)  # zakázka s dokladem nejde smazat


def test_zruseni_uhrady_zustane_v_historii(session, zakazka):
    f = _vystav(session, zakazka)
    u = faktury.pridej_uhradu(session, f.id, {"castka": "786,50 Kč"})  # „Kč“ za částkou nevadí
    session.refresh(f)
    assert f.je_uhrazena
    assert faktury.zrus_uhradu(session, u.id) == f.id
    session.refresh(f)
    assert len(f.uhrady) == 1 and f.uhrady[0].zruseno and f.zbyva == Decimal("786.50")
    with pytest.raises(ChybaValidace):
        faktury.zrus_uhradu(session, u.id)  # už zrušená


def test_faktura_vyzaduje_udaje_servisu_a_ucet(session, zakazka):
    nastaveni.uloz(session, {"cislo_uctu": ""})
    with pytest.raises(ChybaValidace, match="číslo účtu"):
        _vystav(session, zakazka, forma_uhrady="prevod")
    assert faktury.vychozi_udaje(session, zakazka.id)["forma_uhrady"] == "hotove"  # bez účtu nabídne hotově
    nastaveni.uloz(session, {"nazev_servisu": ""})
    with pytest.raises(ChybaValidace, match="údaje servisu"):
        _vystav(session, zakazka, forma_uhrady="hotove")
    v = _vystav(session, zakazka, typ=TypDokladu.VYUCTOVANI)  # vyúčtování jde i bez údajů
    assert v.cislo.startswith("VY")


def test_variabilni_symbol_faktury_a_vyuctovani_se_lisi(session, zakazka):
    f = _vystav(session, zakazka)
    vs_faktury = f.variabilni_symbol
    faktury.smaz(session, f.id)
    session.refresh(zakazka)
    v = _vystav(session, zakazka, typ=TypDokladu.VYUCTOVANI)
    rok = date.today().year
    assert vs_faktury == f"{rok}0001" and v.variabilni_symbol == f"9{rok}0001"
    assert faktury.variabilni_symbol("VY20260002", TypDokladu.VYUCTOVANI) == "920260002"


def test_neplatce_bez_dph(session, zakazka):
    nastaveni.uloz(session, {"platce_dph": "0"})
    f = _vystav(session, zakazka)
    assert f.celkem == Decimal("650.00") and not f.platce_dph and f.nadpis == "Faktura"


def test_qr_vyuctovani_z_vlastniho_uctu_na_celou_castku(session, zakazka):
    """#55: QR na vyúčtování = účet pro vyúčtování, celková částka, i když je uhrazené."""
    v = _vystav(session, zakazka, typ=TypDokladu.VYUCTOVANI)
    assert v.je_uhrazena
    kod = faktury.spayd(v, nastaveni.nacti(session))
    assert kod.startswith("SPD*1.0*ACC:CZ4720100000002001234567*AM:787.00*CC:CZK")
    bez_uctu = nastaveni.nacti(session)
    bez_uctu.ucet_vyuctovani = ""
    assert faktury.spayd(v, bez_uctu) is None  # účet pro faktury se nepoužije


def test_faktura_hotove_bez_qr(session, zakazka):
    f = _vystav(session, zakazka, forma_uhrady="hotove")
    assert faktury.spayd(f, nastaveni.nacti(session)) is None


def test_spayd_a_qr(session, zakazka):
    f = _vystav(session, zakazka)
    bez_uctu = nastaveni.nacti(session)
    bez_uctu.cislo_uctu = bez_uctu.iban = ""
    assert faktury.spayd(f, bez_uctu) is None  # bez účtu
    nast = nastaveni.nacti(session)
    kod = faktury.spayd(f, nast)
    assert kod.startswith("SPD*1.0*ACC:CZ6508000000192000145399*AM:786.50*CC:CZK")
    assert f"X-VS:{f.variabilni_symbol}" in kod
    assert faktury.qr_svg(kod).startswith("<svg")


def test_jen_prevod_a_hotove(session, zakazka):
    with pytest.raises(ChybaValidace):
        _vystav(session, zakazka, forma_uhrady="karta")
    f = _vystav(session, zakazka, forma_uhrady="hotove")
    assert f.celkem == Decimal("787")  # hotově se zaokrouhlí
    with pytest.raises(ChybaValidace):
        faktury.pridej_uhradu(session, f.id, {"castka": "100", "zpusob": "karta"})
    faktury.pridej_uhradu(session, f.id, {"castka": "100", "zpusob": "prevod"})


def test_jen_dva_druhy_dokladu(session, zakazka):
    with pytest.raises(ChybaValidace):
        _vystav(session, zakazka, typ="predfaktura")


def test_nastaveni_udaje_a_rady(session):
    n = nastaveni.uloz(session, {"nazev_servisu": "Servis Novák", "ico": "123 456 78", "splatnost_dni": "30",
                                 "rada_faktura": "F{RR}-", "cifry_cisla": "5"})
    assert n.ico == "12345678" and n.splatnost_dni == 30 and n.cifry_cisla == 5
    with pytest.raises(ChybaValidace):
        nastaveni.uloz(session, {"rada_faktura": ""})
    with pytest.raises(ChybaValidace):
        nastaveni.uloz(session, {"splatnost_dni": "-1"})


def test_faktura_vyzaduje_zakaznika_vyuctovani_ne(session):
    nastaveni.uloz(session, {"ucet_vyuctovani": "2001234567/2010"})
    z = zakazky.prijem(session, zakazka={"pozadavek": "x"}, vozidlo={"spz": "5EE5555"}, zakaznik={"vyber": "bez"})
    polozky.pridej_rucne(session, z.id, {"nazev": "Díl", "cena": "100"})
    with pytest.raises(ChybaValidace, match="vyžaduje zákazníka"):
        _vystav(session, z, typ=TypDokladu.FAKTURA, odb_nazev="Někdo")
    v = _vystav(session, z, typ=TypDokladu.VYUCTOVANI)
    assert v.odb_nazev == "" and v.zakaznik_id is None and v.celkem == Decimal("121")


def test_platce_dph_potrebuje_dic_a_hotove_splatnost_dnes(session, zakazka):
    nastaveni.uloz(session, {"dic": ""})
    nast = nastaveni.nacti(session)
    assert not nast.udaje_vyplneny and "DIČ" in nast.chybejici_udaje_text
    with pytest.raises(ChybaValidace, match="DIČ"):
        _vystav(session, zakazka)
    nastaveni.uloz(session, {"platce_dph": "0"})  # neplátce DIČ nepotřebuje
    assert nastaveni.nacti(session).udaje_vyplneny
    nastaveni.uloz(session, {"platce_dph": "1", "dic": "CZ12345678", "cislo_uctu": ""})
    vychozi = faktury.vychozi_udaje(session, zakazka.id)
    assert vychozi["forma_uhrady"] == "hotove" and vychozi["datum_splatnosti"] == date.today()


def test_smazani_vrati_stav_pred_vystavenim(session, zakazka):
    zakazky.zmen_stav(session, zakazka.id, StavZakazky.PRIJATO)
    f = _vystav(session, zakazka)
    assert f.stav_zakazky_pred == StavZakazky.PRIJATO
    faktury.smaz(session, f.id)
    session.refresh(zakazka)
    assert zakazka.stav == StavZakazky.PRIJATO  # ne „Předáno“


def test_uzavrit_bez_dokladu_jen_s_potvrzenim(session, zakazka):
    with pytest.raises(ChybaValidace, match="bez dokladu"):
        zakazky.zmen_stav(session, zakazka.id, StavZakazky.PREDANO)
    z = zakazky.zmen_stav(session, zakazka.id, StavZakazky.PREDANO, bez_dokladu=True)
    assert z.uzavrena_bez_dokladu
    _vystav(session, z)  # doklad jde vystavit i potom
    session.refresh(z)
    assert not z.uzavrena_bez_dokladu


def test_vyuctovani_bez_splatnosti(session, zakazka):
    """#58: vyúčtování splatnost neuvádí – nikdy není po splatnosti, QR bez data splatnosti."""
    v = _vystav(session, zakazka, typ=TypDokladu.VYUCTOVANI, uhrazeno_ihned="",
                datum_splatnosti=date.today() - timedelta(days=30), datum_vystaveni=date.today() - timedelta(days=40))
    assert not v.po_splatnosti and v.stav == "neuhrazena"
    assert "*DT:" not in faktury.spayd(v, nastaveni.nacti(session))


def test_neplatce_bez_dic_vystavi_fakturu(session, zakazka):
    """#52: neplátce s prázdným DIČ vystaví fakturu bez DPH."""
    nastaveni.uloz(session, {"platce_dph": "1", "dic": ""})
    assert "zrušte „plátce DPH“" in nastaveni.nacti(session).chybejici_udaje_text
    nastaveni.uloz(session, {"platce_dph": "0"})
    f = _vystav(session, zakazka)
    assert not f.platce_dph and f.celkem == Decimal("650.00")
