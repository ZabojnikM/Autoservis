"""#220 Kontrola původu požadavků (ochrana proti podvrženým požadavkům z cizích stránek)."""
from sqlmodel import select

from app.models import Zakazka
from app.services import api_klice, zakazky
from tests.web_pomucky import client


def _zakazka(session):
    return zakazky.prijem(session, zakazka={"pozadavek": "TEST"}, vozidlo={"spz": "1AB2345"})


def test_cizi_origin_neprovede_smazani(session):
    z = _zakazka(session)
    r = client.post(f"/zakazky/{z.id}/smazat", headers={"Origin": "http://zla-stranka.example"}, follow_redirects=False)
    assert r.status_code == 403 and "nepřišel z Autoservisu" in r.text
    session.expire_all()
    assert session.get(Zakazka, z.id) is not None  # nic se nesmazalo


def test_cizi_referer_a_null_origin(session):
    z = _zakazka(session)
    for hlavicky in ({"Referer": "https://jinde.example/stranka"}, {"Origin": "null"}):
        assert client.post(f"/zakazky/{z.id}/smazat", headers=hlavicky, follow_redirects=False).status_code == 403
    assert session.exec(select(Zakazka)).first() is not None


def test_vlastni_adresa_a_bez_hlavicek_projde(session):
    z = _zakazka(session)
    r = client.post(f"/zakazky/{z.id}/smazat", headers={"Origin": "http://testserver"}, follow_redirects=False)
    assert r.status_code == 303
    z2 = _zakazka(session)
    r = client.post(f"/zakazky/{z2.id}/smazat", headers={"Referer": "http://testserver/zakazky/1"},
                    follow_redirects=False)
    assert r.status_code == 303
    z3 = _zakazka(session)
    assert client.post(f"/zakazky/{z3.id}/smazat", follow_redirects=False).status_code == 303  # bez hlaviček (program)


def test_jina_adresa_serveru_shodna_s_host(session):
    """Přístup přes jinou adresu serveru (místní síť, Tailscale): Origin = Host projde, jiný port ne."""
    z = _zakazka(session)
    hl = {"Host": "server.local:8001", "Origin": "http://server.local:8001"}
    assert client.post(f"/zakazky/{z.id}/smazat", headers=hl, follow_redirects=False).status_code == 303
    z2 = _zakazka(session)
    hl = {"Host": "server.local:8001", "Origin": "http://server.local:8002"}
    assert client.post(f"/zakazky/{z2.id}/smazat", headers=hl, follow_redirects=False).status_code == 403


def test_get_a_api_s_cizim_origin(session):
    assert client.get("/zakazky", headers={"Origin": "http://zla-stranka.example"}).status_code == 200
    api_klice.nastav_zapnuto(session, True)
    _, klic = api_klice.vytvor(session, "TEST", ["vozidla"])
    r = client.post("/api/v1/vozidla", json={"spz": "9TEST99"},
                    headers={"Authorization": f"Bearer {klic}", "Origin": "http://zla-stranka.example"})
    assert r.status_code in (200, 201)  # API chrání klíč, ne původ
