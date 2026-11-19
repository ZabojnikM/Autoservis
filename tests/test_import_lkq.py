"""#8 Import dodacího listu LKQ (CSV) do ceníku a zakázky."""
from decimal import Decimal

import pytest
from sqlmodel import select

from app.models import PolozkaCeniku
from app.services import ChybaValidace, cenik, import_lkq, zakazky
from tests.test_web import _prijem, client

CSV = """Verze formatu;1.10
LKQ CZ s.r.o., pobočka ZLIN - dodaci list c.;3116034551
Datum vystaveni;19.11.2026
Datum splatnosti;-
Forma uhrady;-
Mena;Kč
Zakaznik;Servis Test
Dodavatel;LKQ CZ ZLIN
Vystavil(a);jhra05
Cislo;Kod;Nazev;Mnozstvi;MOC bez DPH/ks;VOC bez DPH/ks;Sleva (%);DPH (%);Cena/ks;Celkem s DPH;Merne mnozstvi;Merna velicina;poznámka zákazníka
1;OPT 06-S383;Snímač otáček kola OPTIMAL;1;839.00;839.00;0.00;21;427.89;517.75;0.00;;
2;OPT FAF10128;Vzduchový filtr Optimal;2;399.00;399.00;0.00;21;227.43;550.38;1.00;ks;
3;OPT FCF20095;Kabinový filtr Optimal;1;219.00;219.00;0.00;21;124.83;151.04;1.00;ks;
Sazba DPH (%);Bez DPH;DPH;Cena s DPH
21;1007.58;211.59;1219.17
Celkem;1007.58;211.59;1219.17
"""


def _list(text=CSV, kodovani="utf-8"):
    return import_lkq.nacti_csv(text.encode(kodovani))


def test_nacteni_csv_utf8_i_cp1250():
    for kodovani in ("utf-8", "utf-8-sig", "cp1250"):
        l = _list(kodovani=kodovani)
        assert l.cislo == "3116034551" and l.datum == "19.11.2026" and l.dodavatel == "LKQ CZ ZLIN"
        assert l.bez_dph == Decimal("1007.58") and l.s_dph == Decimal("1219.17")
        assert [d.kod for d in l.dily] == ["OPT 06-S383", "OPT FAF10128", "OPT FCF20095"]
        d = l.dily[0]
        assert d.nazev == "Snímač otáček kola OPTIMAL" and d.nakup == Decimal("427.89") and d.moc == Decimal("839.00")
        assert d.dph == Decimal("21") and l.dily[1].mnozstvi == Decimal("2")
    assert import_lkq.z_json(import_lkq.do_json(l)) == l


def test_neplatny_soubor():
    for obsah in (b"", b"nesmysl;bez;hlavicky\n", "Cislo;Kod;Nazev;Mnozstvi\n".encode()):
        with pytest.raises(ChybaValidace):
            import_lkq.nacti_csv(obsah)
    bez_dilu = CSV.split("1;OPT 06")[0] + "Sazba DPH (%);Bez DPH;DPH;Cena s DPH\n"
    with pytest.raises(ChybaValidace, match="žádné díly"):
        _list(bez_dilu)
    with pytest.raises(ChybaValidace, match="není číslo"):
        _list(CSV.replace(";427.89;", ";abc;"))


def test_import_do_ceniku_parovani_a_opakovani(session):
    # existující položka s kódem v jiném zápisu (mezery, malá písmena) se spáruje
    stara = cenik.vytvor(session, {"kod": "opt 06-s383", "nazev": "Snímač ABS (vlastní název)", "cena": "700",
                                   "nakupni_cena": "400"})
    l = _list()
    nahled = import_lkq.nahled(session, l)
    assert [r.je_novy for r in nahled] == [False, True, True] and nahled[0].polozka.id == stara.id
    assert nahled[0].zmena_cen
    souhrn = import_lkq.importuj(session, l, [0, 1, 2])
    assert (souhrn.aktualizovano, souhrn.zalozeno, souhrn.vlozeno) == (1, 2, 0)
    session.refresh(stara)
    # ceny vždy z LKQ, název zůstal
    assert stara.cena == Decimal("839.00") and stara.nakupni_cena == Decimal("427.89")
    assert stara.nazev == "Snímač ABS (vlastní název)"
    nova = import_lkq.najdi_v_ceniku(session, "OPT FAF10128")
    assert nova.nazev == "Vzduchový filtr Optimal" and nova.typ == "material" and nova.jednotka == "ks"
    assert nova.cena == Decimal("399.00") and nova.nakupni_cena == Decimal("227.43") and nova.sazba_dph == Decimal("21")
    # opakovaný import: nic se nezdvojí, ceny stejné
    pocet = len(session.exec(select(PolozkaCeniku)).all())
    assert not any(r.je_novy or r.zmena_cen for r in import_lkq.nahled(session, l))
    souhrn = import_lkq.importuj(session, l, [0, 1, 2])
    assert (souhrn.aktualizovano, souhrn.zalozeno) == (3, 0) and len(session.exec(select(PolozkaCeniku)).all()) == pocet


def test_import_jen_vybrane_do_zakazky(session):
    z = zakazky.prijem(session, zakazka={"pozadavek": "Filtry"}, vozidlo={"spz": "4LK4444"})
    l = _list()
    souhrn = import_lkq.importuj(session, l, [1, 2], zakazka_id=z.id)
    assert (souhrn.zalozeno, souhrn.vlozeno) == (2, 2)
    session.refresh(z)
    assert [(r.kod, r.mnozstvi, r.cena) for r in z.polozky] == [
        ("OPT FAF10128", Decimal("2"), Decimal("399.00")), ("OPT FCF20095", Decimal("1"), Decimal("219.00"))]
    assert import_lkq.najdi_v_ceniku(session, "OPT 06-S383") is None  # nezaškrtnutý díl se přeskočil
    with pytest.raises(ChybaValidace, match="Není vybraný"):
        import_lkq.importuj(session, l, [])


def test_import_v_uzavrene_zakazce_neulozi_nic(session):
    z = zakazky.prijem(session, zakazka={"pozadavek": "x"}, vozidlo={"spz": "5LK5555"})
    zakazky.zmen_stav(session, z.id, "predano", bez_dokladu=True)
    with pytest.raises(ChybaValidace):
        import_lkq.importuj(session, _list(), [0, 1, 2], zakazka_id=z.id)
    assert import_lkq.najdi_v_ceniku(session, "OPT FAF10128") is None  # vše, nebo nic


def test_okno_importu_web():
    # Materiál: tlačítko, okno s výběrem souboru, náhled, import
    assert 'href="/cenik/import"' in client.get("/cenik").text
    okno = client.get("/cenik/import", params={"okno": "1"}).text
    assert 'name="soubor"' in okno and 'hx-encoding="multipart/form-data"' in okno and "<html" not in okno
    r = client.post("/cenik/import/nahled", data={"okno": "1"}, files={"soubor": ("list.csv", "nesmysl".encode())})
    assert r.status_code == 200 and "není dodací list LKQ" in r.text
    r = client.post("/cenik/import/nahled", data={"okno": "1"}, files={"soubor": ("list.csv", CSV.encode())})
    assert "3116034551" in r.text and r.text.count("Nová položka") == 3 and r.text.count('name="vybrano"') == 3
    import re
    data = re.search(r'name="data_listu" value="([^"]+)"', r.text).group(1)
    import html
    r = client.post("/cenik/import", data={"okno": "1", "data_listu": html.unescape(data), "vybrano": ["0", "2"]})
    assert r.status_code == 204 and r.headers["HX-Refresh"] == "true"
    seznam = client.get("/cenik", params={"q": "OPT"}).text
    assert "OPT 06-S383" in seznam and "OPT FCF20095" in seznam and "OPT FAF10128" not in seznam
    # zakázka: Import vloží vybrané díly do zakázky
    loc = _prijem(spz="6LK6666").headers["location"].split("?")[0]
    zid = loc.rsplit("/", 1)[1]
    assert "do zakázky" in client.get("/cenik/import", params={"okno": "1", "zakazka_id": zid}).text
    r = client.post("/cenik/import", data={"okno": "1", "zakazka_id": zid, "data_listu": html.unescape(data),
                                           "vybrano": ["1"]})
    assert r.status_code == 204
    detail = client.get(loc).text
    assert "OPT FAF10128" in detail and "Vzduchový filtr Optimal" in detail
