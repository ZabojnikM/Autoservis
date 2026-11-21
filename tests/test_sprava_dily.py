"""Správa dat – díly s filtrem, export, hromadné akce, sklady a deník (#136, #138, #139, #140, #142)."""
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlmodel import select

from app.main import app
from app.models import Katalog, PolozkaCeniku, PolozkaZakazky, UpravaDat
from app.services import (ChybaValidace, cenik, hromadne, import_skladu, katalogy, nastaveni, polozky, sprava,
                          zakazky, zalohy)


@pytest.fixture
def sklad(session):
    """Hlavní katalog: 3 filtry UFI (jeden použitý), olej bez nákupu, díl pod nákupní cenou; katalog LKQ."""
    lkq = katalogy.vytvor(session, "LKQ")
    d = {
        "ufi1": cenik.vytvor(session, {"kod": "UFI 25.011.00", "nazev": "Olejový filtr", "cena": "200", "nakupni_cena": "100"}),
        "ufi2": cenik.vytvor(session, {"kod": "UFI 30.779.00", "nazev": "Vzduchový filtr", "cena": "449", "nakupni_cena": "300"}),
        "holy": cenik.vytvor(session, {"kod": "23.135.00", "nazev": "Filtr bez předpony", "cena": "150", "nakupni_cena": "90"}),
        "olej": cenik.vytvor(session, {"kod": "castrol 5w30", "nazev": "Olej", "cena": "300"}),
        "ztrata": cenik.vytvor(session, {"kod": "BO 123", "nazev": "Svíčka", "cena": "80", "nakupni_cena": "100"}),
        "lkq_ufi1": cenik.vytvor(session, {"kod": "UFI 25.011.00", "nazev": "Olejový filtr LKQ", "cena": "190",
                                           "katalog_id": lkq.id}),
    }
    z = zakazky.prijem(session, zakazka={"pozadavek": "x"}, vozidlo={"spz": "1KT1111"})
    d["radek"] = polozky.pridej_z_ceniku(session, z.id, d["ufi1"].id)
    d["lkq"] = lkq
    return d


def _kody(radky):
    return [r.karta.kod for r in radky]


def test_filtr_a_razeni(session, sklad):
    hlavni = katalogy.vychozi(session).id
    assert _kody(sprava.vyber(session, sprava.Filtr(predpona="UFI", katalog=str(hlavni)))) == ["UFI 25.011.00", "UFI 30.779.00"]
    assert len(sprava.vyber(session, sprava.Filtr(predpona="UFI"))) == 3
    assert _kody(sprava.vyber(session, sprava.Filtr(q="2501100"))) == ["UFI 25.011.00", "UFI 25.011.00"]
    assert _kody(sprava.vyber(session, sprava.Filtr(pouziti="pouzite"))) == ["UFI 25.011.00"]
    assert _kody(sprava.vyber(session, sprava.Filtr(problem="pod_nakupem"))) == ["BO 123"]
    assert _kody(sprava.vyber(session, sprava.Filtr(problem="kod_podezrely"))) == ["castrol 5w30"]
    assert _kody(sprava.vyber(session, sprava.Filtr(marze_pod="35"))) == ["BO 123", "UFI 30.779.00"]
    assert _kody(sprava.vyber(session, sprava.Filtr(cena_od="200", cena_do="300", razeni="-cena"))) == \
        ["castrol 5w30", "UFI 25.011.00"]
    # použité dnes → „nepoužité od“ zítřka ho nevyřadí, od dneška ano
    zitra = datetime.now().replace(year=datetime.now().year + 1).strftime("%d.%m.%Y")
    assert "UFI 25.011.00" in _kody(sprava.vyber(session, sprava.Filtr(nepouzito_od=zitra, katalog=str(hlavni))))
    assert "UFI 25.011.00" not in _kody(sprava.vyber(session, sprava.Filtr(nepouzito_od="1.1.2000", katalog=str(hlavni))))
    with pytest.raises(ChybaValidace, match="není datum"):
        sprava.vyber(session, sprava.Filtr(nepouzito_od="zítra"))
    r = next(r for r in sprava.vyber(session, sprava.Filtr(q="BO 123")))
    assert r.marze == Decimal("-25.0")


def test_export_jde_nahrat_zpet_importem(session, sklad):
    obsah = sprava.export_csv(sprava.vyber(session, sprava.Filtr(predpona="UFI")))
    text = obsah.decode("utf-8-sig")
    assert text.splitlines()[0].startswith("Kód;Název;Sklad;MJ;Prodej bez DPH;Nákup bez DPH;DPH %")
    assert "UFI 25.011.00;Olejový filtr;Hlavní katalog;ks;200,00;100,00;21;50,0;1;" in text
    radky = import_skladu.nacti(obsah)
    assert {(r.kod, r.cena) for r in radky} >= {("UFI 30.779.00", Decimal("449.00"))}


def test_zmena_cen(session, sklad):
    ids = [sklad["ufi1"].id, sklad["olej"].id]
    plan = hromadne.planuj(session, "ceny", ids, {"cil": "prodej", "zpusob": "procenta", "hodnota": "5",
                                                 "zaokrouhleni": "devitky"})
    assert [(z.kod, z.pred, z.po) for z in plan.provede_se] == [("UFI 25.011.00", "200,00", "219,00"),
                                                                ("castrol 5w30", "300,00", "319,00")]
    plan = hromadne.planuj(session, "ceny", ids, {"cil": "prodej", "zpusob": "marze", "hodnota": "50"})
    assert [z.preskoceno for z in plan.zmeny] == ["beze změny", "nemá nákupní cenu"]   # 100 / 0,5 = 200
    plan = hromadne.planuj(session, "ceny", ids, {"cil": "prodej", "zpusob": "procenta", "hodnota": "-10",
                                                 "zaokrouhleni": "koruny"})
    assert hromadne.proved(session, plan) == 2
    session.refresh(sklad["ufi1"]), session.refresh(sklad["radek"])
    assert sklad["ufi1"].cena == Decimal("180") and sklad["radek"].cena == Decimal("200")   # zakázka beze změny
    hromadne.proved(session, hromadne.planuj(session, "ceny", ids, {"cil": "dph", "hodnota": "12"}))
    session.refresh(sklad["olej"])
    assert sklad["olej"].sazba_dph == Decimal("12")
    with pytest.raises(ChybaValidace, match="Zadejte hodnotu"):
        hromadne.planuj(session, "ceny", ids, {"cil": "prodej"})


def test_presun_a_kopie_s_kolizi(session, sklad):
    lkq = sklad["lkq"]
    ids = [sklad["ufi1"].id, sklad["ufi2"].id]
    plan = hromadne.planuj(session, "presun", ids, {"katalog": str(lkq.id), "kolize": "preskocit"})
    assert [z.preskoceno for z in plan.zmeny] == ["v cílovém skladu už je kód UFI 25.011.00", ""]
    # sloučit: použitý filtr se sloučí do karty LKQ, zakázka se napojí na ni
    plan = hromadne.planuj(session, "presun", ids, {"katalog": str(lkq.id), "kolize": "sloucit"})
    assert hromadne.proved(session, plan) == 2
    session.refresh(sklad["radek"]), session.refresh(sklad["ufi2"]), session.refresh(sklad["ufi1"])
    assert (sklad["radek"].polozka_ceniku_id, sklad["radek"].katalog_id) == (sklad["lkq_ufi1"].id, lkq.id)
    assert sklad["ufi2"].katalog_id == lkq.id and not sklad["ufi1"].aktivni
    # kopie zpět do hlavního: UFI 30.779.00 tam už není → založí se; kolize přepsat ceny
    hlavni = katalogy.vychozi(session)
    plan = hromadne.planuj(session, "kopie", [sklad["ufi2"].id, sklad["lkq_ufi1"].id],
                           {"katalog": str(hlavni.id), "kolize": "prepsat"})
    hromadne.proved(session, plan)
    kopie = cenik.najdi_podle_kodu(session, "UFI 30.779.00", hlavni.id)
    assert kopie and kopie.id != sklad["ufi2"].id and kopie.cena == Decimal("449")
    session.refresh(sklad["ufi1"])
    assert sklad["ufi1"].cena == Decimal("190")   # přepsané ceny existující (vyřazené) karty
    with pytest.raises(ChybaValidace, match="jen při přesunu"):
        hromadne.planuj(session, "kopie", ids, {"katalog": str(hlavni.id), "kolize": "sloucit"})


def test_vyradit_obnovit_smazat(session, sklad):
    ids = [sklad["ufi1"].id, sklad["holy"].id]
    hromadne.proved(session, hromadne.planuj(session, "vyradit", ids, {}))
    assert sprava.vyber(session, sprava.Filtr(q="filtr bez")) == []
    plan = hromadne.planuj(session, "smazat", ids, {})
    assert plan.preskoci_se[0].preskoceno.startswith("použitý v 1 řádcích")
    hromadne.proved(session, plan)
    assert session.get(PolozkaCeniku, sklad["holy"].id) is None and session.get(PolozkaCeniku, sklad["ufi1"].id)
    hromadne.proved(session, hromadne.planuj(session, "obnovit", [sklad["ufi1"].id], {}))
    session.refresh(sklad["ufi1"])
    assert sklad["ufi1"].aktivni


def test_upravy_kodu_se_propisou_do_zakazek(session, sklad):
    plan = hromadne.planuj(session, "kody", [sklad["holy"].id, sklad["ufi1"].id], {"operace": "predpona", "predpona": "ufi"})
    assert [(z.po, z.preskoceno) for z in plan.zmeny] == [("UFI 23.135.00", ""), ("UFI 25.011.00", "beze změny")]
    hromadne.proved(session, plan)
    plan = hromadne.planuj(session, "kody", [sklad["olej"].id], {"operace": "sjednotit"})
    assert plan.provede_se[0].po == "CASTROL 5W30"
    plan = hromadne.planuj(session, "kody", [sklad["ufi1"].id], {"operace": "nahradit", "pole": "kod",
                                                                "hledat": "25.011", "nahradit": "25.012"})
    hromadne.proved(session, plan)
    session.refresh(sklad["radek"])
    assert sklad["radek"].kod == "UFI 25.012.00" and sklad["radek"].cena == Decimal("200")
    # kolize: přejmenovat na existující kód nejde
    plan = hromadne.planuj(session, "kody", [sklad["ufi2"].id], {"operace": "nahradit", "pole": "kod",
                                                                "hledat": "30.779", "nahradit": "25.012"})
    assert "už ve skladu je" in plan.zmeny[0].preskoceno
    plan = hromadne.planuj(session, "kody", [sklad["ufi2"].id], {"operace": "nahradit", "pole": "nazev",
                                                                "hledat": "Vzduchový", "nahradit": "Vzduch."})
    assert plan.provede_se[0].po == "Vzduch. filtr"


def test_smazani_skladu_presune_pouzite(session, sklad):
    lkq = sklad["lkq"]
    # použitý filtr do LKQ přesunem (kolize se sloučí), pak smazat LKQ s přesunem zpět do hlavního
    hromadne.proved(session, hromadne.planuj(session, "presun", [sklad["ufi1"].id],
                                             {"katalog": str(lkq.id), "kolize": "sloucit"}))
    hlavni = katalogy.vychozi(session)
    with pytest.raises(ChybaValidace, match="Vyberte cílový sklad"):
        hromadne.planuj_smazani_skladu(session, lkq.id, "", False)
    plan = hromadne.planuj_smazani_skladu(session, lkq.id, str(hlavni.id), True)
    assert {z.co for z in plan.zmeny} == {"Sloučit do"}   # v hlavním zůstala vyřazená karta se stejným kódem
    hromadne.proved(session, plan)
    hromadne.smaz_sklad(session, lkq.id)
    assert session.get(Katalog, lkq.id) is None
    session.refresh(sklad["radek"])
    karta = session.get(PolozkaCeniku, sklad["radek"].polozka_ceniku_id)
    assert karta.katalog_id == hlavni.id and not karta.aktivni and sklad["radek"].kod == "UFI 25.011.00"
    with pytest.raises(ChybaValidace, match="Výchozí sklad"):
        hromadne.planuj_smazani_skladu(session, hlavni.id, "", False)


# ---------------------------------------------------------------- web

@pytest.fixture
def web(session, monkeypatch):
    nastaveni.uloz(session, {"sprava_dat": "1"})
    zalohy_ = []
    monkeypatch.setattr(zalohy, "pred_sloucenim", lambda: zalohy_.append(1) or Path("pred-sloucenim-test.db"))
    return TestClient(app), zalohy_


def test_web_dily_nahled_a_provedeni(session, sklad, web):
    klient, zalohy_ = web
    stranka = klient.get("/sprava-dat/dily", params={"predpona": "UFI", "razeni": "-cena"})
    assert stranka.status_code == 200 and "UFI 30.779.00" in stranka.text and "castrol" not in stranka.text
    hlavni = katalogy.vychozi(session)
    data = {"katalog": str(hlavni.id), "predpona": "UFI", "rozsah": "filtr", "akce": "ceny", "cil": "prodej",
            "zpusob": "procenta", "hodnota": "10", "zaokrouhleni": "koruny"}
    nahled = klient.post("/sprava-dat/dily/nahled", data=data)
    assert nahled.status_code == 200 and "220,00" in nahled.text and 'name="p_hodnota" value="10"' in nahled.text
    assert zalohy_ == []   # náhled nic neukládá
    ids = ",".join(str(sklad[k].id) for k in ("ufi1", "ufi2"))
    odpoved = klient.post("/sprava-dat/dily/provest", follow_redirects=False, data={
        "akce": "ceny", "ids": ids, "p_cil": "prodej", "p_zpusob": "procenta", "p_hodnota": "10",
        "p_zaokrouhleni": "koruny", "katalog": str(hlavni.id), "predpona": "UFI"})
    assert odpoved.status_code == 303 and "predpona=UFI" in odpoved.headers["location"] and zalohy_ == [1]
    session.refresh(sklad["ufi1"])
    assert sklad["ufi1"].cena == Decimal("220")
    zaznam = session.exec(select(UpravaDat)).one()
    assert zaznam.akce == "Změna cen" and zaznam.pocet == 2 and zaznam.zaloha == "pred-sloucenim-test.db"
    assert "Změna cen" in klient.get("/sprava-dat/denik").text


def test_web_export_a_vyber(session, sklad, web):
    klient, _ = web
    csv_ = klient.get("/sprava-dat/dily/export.csv", params={"predpona": "UFI", "sloupce": ["kod", "cena"]})
    assert csv_.text.lstrip("﻿").splitlines() == ["Kód;Prodej bez DPH", "UFI 25.011.00;200,00",
                                                       "UFI 25.011.00;190,00", "UFI 30.779.00;449,00"]
    vybrane = klient.post("/sprava-dat/dily/nahled", data={"rozsah": "vybrane", "id": [str(sklad["olej"].id)],
                                                           "akce": "export", "sloupce": ["kod"]})
    assert vybrane.text.lstrip("﻿").splitlines() == ["Kód", "castrol 5w30"]
    bez_vyberu = klient.post("/sprava-dat/dily/nahled", data={"rozsah": "vybrane", "akce": "vyradit"},
                             follow_redirects=False)
    assert bez_vyberu.status_code == 303


def test_web_smazani_skladu(session, sklad, web):
    klient, zalohy_ = web
    lkq, hlavni = sklad["lkq"], katalogy.vychozi(session)
    assert "LKQ" in klient.get("/sprava-dat/sklady").text
    nahled = klient.post(f"/sprava-dat/sklady/{lkq.id}/nahled", data={})
    assert nahled.status_code == 200 and "nepoužitý – smaže se" in nahled.text
    odpoved = klient.post(f"/sprava-dat/sklady/{lkq.id}/smazat", data={"p_katalog": str(hlavni.id)},
                          follow_redirects=False)
    assert odpoved.status_code == 303 and zalohy_ == [1]
    assert session.exec(select(Katalog).where(Katalog.nazev == "LKQ")).first() is None


def test_web_akce_skryte_bez_prepinace(session):
    klient = TestClient(app)
    for adresa in ("/sprava-dat/dily", "/sprava-dat/sklady", "/sprava-dat/denik", "/sprava-dat/dily/export.csv"):
        assert klient.get(adresa).status_code == 404


def test_web_provest_z_formulare_nahledu(session, sklad, web):
    """Provést odešle přesně skrytá pole z náhledu (jméno akce nesmí zmizet – „akce“ je i blok v base.html)."""
    import re
    klient, zalohy_ = web
    nahled = klient.post("/sprava-dat/dily/nahled", data={"rozsah": "vybrane", "id": [str(sklad["holy"].id)],
                                                          "akce": "kody", "operace": "predpona", "predpona_kodu": "UFI"})
    pole = dict(re.findall(r'<input type="hidden" name="([^"]+)" value="([^"]*)"', nahled.text))
    assert pole["akce"] == "kody" and pole["p_predpona"] == "UFI"
    assert klient.post("/sprava-dat/dily/provest", data=pole, follow_redirects=False).status_code == 303
    session.refresh(sklad["holy"])
    assert sklad["holy"].kod == "UFI 23.135.00" and zalohy_ == [1]
