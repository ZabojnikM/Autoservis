from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_zdravi():
    r = client.get("/api/zdravi")
    assert r.status_code == 200
    assert r.json()["stav"] == "ok"


def test_uvod_je_seznam_zakazek():
    r = client.get("/", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/zakazky"
    r = client.get("/")
    assert r.status_code == 200
    assert "Autoservis" in r.text and "<title>Zakázky" in r.text and 'name="stav"' in r.text


def test_karty_bez_nadpisu_a_filtry_zakazek():
    # název karty je v horní liště – velký nadpis nad seznamem se neopakuje
    for url in ["/zakazky", "/vozidla", "/zakaznici", "/cenik", "/prace", "/faktury", "/nastaveni"]:
        assert "<h1" not in client.get(url).text, url
    zakazky = client.get("/zakazky").text
    assert 'class="lista-filtru-seznamu"' in zakazky
    assert zakazky.count('name="q"') == 2  # globální hledání a filtr seznamu
    assert 'name="rok"' in zakazky
    assert 'class="lista-filtru-seznamu"' in client.get("/vozidla").text
