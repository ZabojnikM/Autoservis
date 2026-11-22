"""#150: skrytý sklad se nenabízí v zakázkách ani na kartě Materiál, staré zakázky zůstávají."""
import re
from decimal import Decimal

from fastapi.testclient import TestClient

from app.main import app
from app.models import Katalog, PolozkaCeniku, PolozkaZakazky, Vozidlo, Zakazka
from app.services import ChybaValidace, katalogy, polozky

client = TestClient(app)


def _data(session):
    stary = katalogy.vytvor(session, "Starý systém")
    dil = PolozkaCeniku(kod="OLD 123", nazev="Starý filtr", cena=Decimal("100"), katalog_id=stary.id)
    novy = PolozkaCeniku(kod="NEW 456", nazev="Nový filtr", cena=Decimal("120"),
                         katalog_id=katalogy.vychozi(session).id)
    v = Vozidlo(spz="1SK1500")
    session.add_all([dil, novy, v]); session.commit()
    stara = Zakazka(cislo="2026-0001", vozidlo_id=v.id, stav="predano")
    otevrena = Zakazka(cislo="2026-0002", vozidlo_id=v.id, stav="prijato")
    session.add_all([stara, otevrena]); session.commit()
    session.add(PolozkaZakazky(zakazka_id=stara.id, polozka_ceniku_id=dil.id, katalog_id=stary.id, typ="material",
                               kod="OLD 123", nazev="Starý filtr", mnozstvi=Decimal("1"), cena=Decimal("90")))
    session.commit()
    return stary, dil, novy, stara, otevrena


def test_skryty_sklad_se_nenabizi(session):
    stary, dil, novy, stara, otevrena = _data(session)
    # před skrytím se nabízí v okně (přepínač), v historii i při přidání
    okno = client.get(f"/zakazky/{otevrena.id}/cenik", params={"typ": "material", "katalog": stary.id}).text
    assert "OLD 123" in okno
    assert len(polozky.historie_vozidla(session, otevrena)) == 1

    r = client.post(f"/katalogy/{stary.id}/skryt", data={"skryty": "1"}, follow_redirects=True)
    assert "skrytý" in r.text and ">Zobrazit</button>" in r.text
    # přepínač katalogů a okno Přidat materiál: skrytý není, ani když si ho prohlížeč pamatuje
    okno = client.get(f"/zakazky/{otevrena.id}/cenik", params={"typ": "material", "katalog": stary.id}).text
    assert "OLD 123" not in okno and "NEW 456" in okno and "Starý systém" not in okno
    okno = client.get(f"/zakazky/{otevrena.id}/cenik", params={"typ": "material", "q": "OLD 123"}).text
    assert "Starý filtr" not in okno  # ani přesný kód (v poli hledání text zůstane)
    assert "Starý systém" not in client.get("/cenik").text
    session.expire_all()  # skrytí proběhlo v jiném spojení (požadavek webu)
    assert polozky.historie_vozidla(session, otevrena) == []
    try:
        polozky.pridej_z_ceniku(session, otevrena.id, dil.id)
        assert False, "díl ze skrytého skladu nejde přidat"
    except ChybaValidace as e:
        assert "skrytém skladu" in str(e)
    # stará zakázka beze změny
    detail = client.get(f"/zakazky/{stara.id}").text
    assert "OLD 123" in detail and "Starý filtr" in detail
    # znovu zobrazit
    client.post(f"/katalogy/{stary.id}/skryt", data={"skryty": "0"})
    assert "OLD 123" in client.get(f"/zakazky/{otevrena.id}/cenik",
                                   params={"typ": "material", "katalog": stary.id}).text


def test_vychozi_sklad_nejde_skryt(session):
    vychozi = katalogy.vychozi(session)
    r = client.post(f"/katalogy/{vychozi.id}/skryt", data={"skryty": "1"}, follow_redirects=False)
    assert r.status_code == 303
    session.expire_all()
    assert session.get(Katalog, vychozi.id).skryty is False
