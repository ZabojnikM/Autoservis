"""#160: záložka Statistiky – výkon servisu z uzavřených zakázek."""
from datetime import datetime
from decimal import Decimal

from fastapi.testclient import TestClient

from app.main import app
from app.models import PolozkaCeniku, PolozkaZakazky, Zakazka
from app.services import nastaveni, statistiky

client = TestClient(app)


def _zakazka(session, cislo, uzavreno, radky):
    z = Zakazka(cislo=cislo, stav="predano", datum_prijeti=uzavreno, uzavreno=uzavreno)
    session.add(z); session.commit(); session.refresh(z)
    for r in radky:
        session.add(PolozkaZakazky(zakazka_id=z.id, **r))
    session.commit()
    return z


def _data(session):
    dil = PolozkaCeniku(kod="OPT FAF10128", nazev="Vzduchový filtr", cena=Decimal("399"), nakupni_cena=Decimal("250"))
    session.add(dil); session.commit(); session.refresh(dil)
    mat = dict(typ="material", kod="OPT FAF10128", nazev="Vzduchový filtr", jednotka="ks", mnozstvi=Decimal("2"),
               cena=Decimal("399"), polozka_ceniku_id=dil.id)
    bez = dict(typ="material", kod="X", nazev="Bez ceníku", jednotka="ks", mnozstvi=Decimal("1"), cena=Decimal("100"))
    prace = dict(typ="prace", kod="MECH", nazev="Mechanická práce", jednotka="hod", mnozstvi=Decimal("1.5"), cena=Decimal("800"))
    _zakazka(session, "2026-0001", datetime(2026, 3, 5, 10), [mat, bez, prace])
    _zakazka(session, "2026-0002", datetime(2026, 3, 20, 10), [prace])
    _zakazka(session, "2025-0001", datetime(2025, 3, 1, 10), [prace])
    _zakazka(session, "2025-0002", datetime(2025, 11, 1, 10), [prace])  # po srovnávaném období
    session.add(Zakazka(cislo="2026-0003", stav="prijato", datum_prijeti=datetime(2026, 3, 6)))  # neuzavřená
    session.commit()


def test_statistika_mesice_rok_a_srovnani(session):
    _data(session)
    s = statistiky.statistika(session, 2026, dnes=datetime(2026, 4, 15))
    brezen = s.mesice[2]
    assert brezen.zakazek == 2
    assert brezen.material_prodej == Decimal("898.00")       # 2 × 399 + 100
    assert brezen.material_nakup == Decimal("500.00")        # jen díl s nákupní cenou
    assert brezen.material_vydelek == Decimal("298.00")      # 798 − 500, řádek bez nákupu se nepočítá
    assert brezen.prace == Decimal("2400.00") and brezen.hodiny == Decimal("3.0")
    assert brezen.celkem == Decimal("3298.00") and brezen.bez_nakupu == 1
    assert s.rok_celkem.celkem == brezen.celkem and s.mesice[0].zakazek == 0
    assert s.roky == [2026, 2025]
    # běžný rok: srovnání jen leden–duben v obou letech (listopad 2025 se nepočítá)
    assert s.do_mesice == 4 and s.loni.zakazek == 1 and s.loni.prace == Decimal("1200.00")
    celkem = s.srovnani[-1]
    assert celkem.rozdil == Decimal("2098.00") and celkem.procent == Decimal("174.8")


def test_minuly_rok_srovnava_cele_roky(session):
    _data(session)
    s = statistiky.statistika(session, 2025, dnes=datetime(2026, 4, 15))
    assert s.do_mesice is None and s.rok_celkem.zakazek == 2 and s.loni.zakazek == 0
    assert s.srovnani[-1].procent is None


def test_zalozka_se_zapina_v_nastaveni(session):
    _data(session)
    assert client.get("/statistiky").status_code == 404
    assert 'href="/statistiky"' not in client.get("/zakazky").text
    assert 'name="statistiky"' in client.get("/nastaveni").text
    nastaveni.uloz(session, {"statistiky": "1"})
    assert 'href="/statistiky"' in client.get("/zakazky").text
    stranka = client.get("/statistiky", params={"rok": "2026"})
    assert stranka.status_code == 200
    assert "březen" in stranka.text and "Výdělek na materiálu je odhad" in stranka.text
    assert "Bez nákupní ceny: 1 řádků" in stranka.text
    assert client.get("/statistiky", params={"rok": "nesmysl"}).status_code == 200
