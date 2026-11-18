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
    assert "Autoservis" in r.text and "<title>Zakázky" in r.text and 'class="filtr-stavu"' in r.text


def test_karty_bez_nadpisu_a_zakazky_bez_hledani():
    # název karty je v horní liště – velký nadpis nad seznamem se neopakuje
    for url in ["/zakazky", "/vozidla", "/zakaznici", "/cenik", "/prace", "/faktury", "/nastaveni"]:
        assert "<h1" not in client.get(url).text, url
    # zakázek je málo – bez vyhledávacího pole (hledat jde horní lištou)
    zakazky = client.get("/zakazky").text
    assert 'class="filtr"' not in zakazky and 'name="q"' in zakazky  # name="q" = jen horní lišta
    assert zakazky.count('name="q"') == 1
    assert 'class="filtr"' in client.get("/vozidla").text  # ostatní seznamy hledání mají
