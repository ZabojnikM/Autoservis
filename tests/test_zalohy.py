"""Automatické zálohy databáze (#76) – nad dočasnými soubory."""
import sqlite3
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import ChybaValidace, zalohy

client = TestClient(app)


@pytest.fixture
def prostredi(tmp_path, monkeypatch):
    db = tmp_path / "autoservis.db"
    with sqlite3.connect(db) as c:
        c.execute("create table t (x)")
        c.execute("insert into t values (42)")
    c.close()
    server = tmp_path / "backups"
    sdilena = tmp_path / "sdileny-disk"
    sdilena.mkdir()
    (sdilena / zalohy.ZNACKA).write_text("")
    monkeypatch.setattr(zalohy, "ZALOHY", server)
    monkeypatch.setattr(zalohy.config, "DB_PATH", db)
    return {"db": db, "server": server, "sdilena": sdilena}


def _hodnota(soubor):
    c = sqlite3.connect(soubor)
    try:
        return c.execute("select x from t").fetchone()[0]
    finally:
        c.close()


def test_denni_zaloha_je_kopie_databaze(prostredi):
    cil = zalohy.denni(prostredi["db"], prostredi["server"])
    assert cil.parent == prostredi["server"]
    assert cil.name.startswith("denni-autoservis-")
    assert _hodnota(cil) == 42
    assert not list(prostredi["server"].glob("*.tmp"))
    assert zalohy.nacti_stav(prostredi["server"])["denni"]["soubor"] == cil.name


def test_denni_uchova_jen_posledni(prostredi):
    zacatek = datetime(2026, 1, 1, 3, 0)
    for i in range(zalohy.DENNICH + 3):
        zalohy.denni(prostredi["db"], prostredi["server"], zacatek + timedelta(days=i))
    denni = sorted(p.name for p in prostredi["server"].glob("denni-*.db"))
    assert len(denni) == zalohy.DENNICH
    assert denni[0].endswith("20260104-030000.db")  # tři nejstarší smazané


def test_promazani_nesmaze_cizi_soubory(prostredi):
    server = prostredi["server"]
    server.mkdir()
    (server / "pred-aktualizaci-20260101-000000-abc1234.db").write_bytes(b"x")
    (server / "denni-jina-db-20200101-000000.db").write_bytes(b"x")
    (server / "moje-poznamka.db").write_bytes(b"x")
    for i in range(zalohy.DENNICH + 2):
        zalohy.denni(prostredi["db"], server, datetime(2026, 2, 1) + timedelta(days=i))
    assert (server / "pred-aktualizaci-20260101-000000-abc1234.db").exists()
    assert (server / "denni-jina-db-20200101-000000.db").exists()
    assert (server / "moje-poznamka.db").exists()


def test_tydenni_do_slozky_uchova_tri(prostredi):
    zacatek = datetime(2026, 3, 2, 3, 0)
    (prostredi["sdilena"] / "cizi-soubor.db").write_bytes(b"x")
    for i in range(5):
        zalohy.tydenni(str(prostredi["sdilena"]), prostredi["db"], prostredi["server"], zacatek + timedelta(weeks=i))
    tydenni = sorted(p.name for p in prostredi["sdilena"].glob("autoservis-tydenni-*.db"))
    assert len(tydenni) == zalohy.TYDENNICH
    assert _hodnota(prostredi["sdilena"] / tydenni[-1]) == 42
    assert (prostredi["sdilena"] / "cizi-soubor.db").exists()
    assert not list(prostredi["sdilena"].glob("*.tmp"))
    assert not list((prostredi["server"] / ".tydenni").glob("*.db"))  # dočasná kopie uklizená


def test_tydenni_nedostupna_slozka_zapise_chybu(prostredi):
    with pytest.raises(zalohy.ChybaZalohy, match="není dostupná"):
        zalohy.tydenni(str(prostredi["sdilena"] / "neni"), prostredi["db"], prostredi["server"])
    assert "není dostupná" in zalohy.nacti_stav(prostredi["server"])["tydenni"]["chyba"]


def test_naplanovane_jen_kdyz_je_nacase(prostredi):
    sdilena = str(prostredi["sdilena"])
    ted = datetime.now()
    assert len(zalohy.naplanovane(sdilena, prostredi["db"], prostredi["server"], ted)) == 2
    assert zalohy.naplanovane(sdilena, prostredi["db"], prostredi["server"], ted + timedelta(hours=1)) == []
    assert len(zalohy.naplanovane(sdilena, prostredi["db"], prostredi["server"], ted + timedelta(days=1, minutes=1))) == 1
    assert len(zalohy.naplanovane(sdilena, prostredi["db"], prostredi["server"], ted + timedelta(days=8))) == 2


def test_naplanovane_bez_slozky_jen_denni(prostredi):
    hotovo = zalohy.naplanovane("", prostredi["db"], prostredi["server"])
    assert len(hotovo) == 1 and hotovo[0].startswith("denni-")


def test_chybejici_databaze(prostredi):
    with pytest.raises(zalohy.ChybaZalohy):
        zalohy.denni(prostredi["db"].with_name("neni.db"), prostredi["server"])


def test_over_slozku(prostredi):
    assert zalohy.over_slozku(str(prostredi["sdilena"])) == prostredi["sdilena"]
    with pytest.raises(ChybaValidace, match="neexistuje"):
        zalohy.over_slozku(str(prostredi["sdilena"] / "neni"))
    with pytest.raises(ChybaValidace, match="celou cestu"):
        zalohy.over_slozku("relativni/cesta")


def test_ke_stazeni_jen_z_adresare_zaloh(prostredi):
    cil = zalohy.rucni(prostredi["db"], prostredi["server"])
    assert zalohy.soubor_ke_stazeni(cil.name, prostredi["server"]) == cil
    for spatne in ("../autoservis.db", ".skryta.db", "neni.db", "zalohy.json"):
        with pytest.raises(zalohy.ChybaZalohy):
            zalohy.soubor_ke_stazeni(spatne, prostredi["server"])


def test_planovac_lze_vypnout(monkeypatch):
    monkeypatch.setenv("AUTOSERVIS_AUTOZALOHY", "0")
    assert zalohy.spust_planovac(lambda: "") is False


# --- web ---

def test_web_blok_a_rucni_zaloha(prostredi):
    r = client.get("/nastaveni/zalohy")
    assert r.status_code == 200 and "Zálohy databáze" in r.text and "zatím neproběhla" in r.text
    r = client.post("/nastaveni/zalohy/ted")
    assert r.status_code == 200 and "je hotová a zkontrolovaná" in r.text
    nazev = next(prostredi["server"].glob("rucni-*.db")).name
    r = client.get(f"/nastaveni/zalohy/stahnout/{nazev}")
    assert r.status_code == 200 and r.content.startswith(b"SQLite format 3")
    assert client.get("/nastaveni/zalohy/stahnout/neni.db").status_code == 404


def test_web_slozka_a_tydenni(prostredi):
    r = client.post("/nastaveni/zalohy/slozka", data={"zaloha_slozka": str(prostredi["sdilena"] / "neni")})
    assert "neexistuje" in r.text
    r = client.post("/nastaveni/zalohy/slozka", data={"zaloha_slozka": str(prostredi["sdilena"])})
    assert "uložena" in r.text and "Zálohovat do složky teď" in r.text
    r = client.post("/nastaveni/zalohy/tydenni")
    assert "je uložená ve složce" in r.text
    assert len(list(prostredi["sdilena"].glob("autoservis-tydenni-*.db"))) == 1
    r = client.post("/nastaveni/zalohy/slozka", data={"zaloha_slozka": ""})
    assert "vypnuté" in r.text


def test_nastaveni_nacte_blok_zaloh():
    assert 'hx-get="/nastaveni/zalohy"' in client.get("/nastaveni").text


def test_bez_znacky_se_do_slozky_nezapisuje(prostredi, tmp_path):
    """Nepřipojený sdílený disk = prázdný přípojný bod bez značky → chyba, žádný zápis."""
    prazdny = tmp_path / "mnt-nepripojeno"
    prazdny.mkdir()
    with pytest.raises(zalohy.ChybaZalohy, match="chybí značka"):
        zalohy.tydenni(str(prazdny), prostredi["db"], prostredi["server"])
    with pytest.raises(ChybaValidace, match="chybí značka"):
        zalohy.over_slozku(str(prazdny))
    assert list(prazdny.iterdir()) == []
    assert "chybí značka" in zalohy.nacti_stav(prostredi["server"])["tydenni"]["chyba"]
    # denní záloha na serveru běží dál
    assert len(zalohy.naplanovane(str(prazdny), prostredi["db"], prostredi["server"])) == 1


# --- obnova (#77) ---

@pytest.fixture
def aplikacni_db(tmp_path, monkeypatch):
    """Skutečná souborová databáze Autoservisu v dočasné složce (ne ostrá)."""
    from sqlmodel import Session as S

    from app import db as databaze
    from app.models import Zakaznik
    soubor = tmp_path / "app" / "autoservis.db"
    soubor.parent.mkdir()
    eng = databaze.vytvor_engine(f"sqlite:///{soubor}")
    databaze.init_db(eng)
    with S(eng) as s:
        s.add(Zakaznik(nazev="TEST Původní"))
        s.commit()
    server = tmp_path / "app" / "backups"
    monkeypatch.setattr(zalohy, "ZALOHY", server)
    monkeypatch.setattr(zalohy.config, "DB_PATH", soubor)
    monkeypatch.setattr(databaze, "engine", eng)
    yield {"db": soubor, "server": server, "eng": eng}
    eng.dispose()


def _zakaznici(eng):
    from sqlmodel import Session as S, select

    from app.models import Zakaznik
    with S(eng) as s:
        return sorted(z.nazev for z in s.exec(select(Zakaznik)))


def _pridej(eng, nazev):
    from sqlmodel import Session as S

    from app.models import Zakaznik
    with S(eng) as s:
        s.add(Zakaznik(nazev=nazev))
        s.commit()


def test_obnova_vrati_stav_zalohy_a_zazalohuje_soucasny(aplikacni_db):
    zaloha = zalohy.rucni(aplikacni_db["db"], aplikacni_db["server"])
    _pridej(aplikacni_db["eng"], "TEST Později")
    vysledek = zalohy.obnov(zaloha, aplikacni_db["db"], aplikacni_db["server"], aplikacni_db["eng"])
    assert _zakaznici(aplikacni_db["eng"]) == ["TEST Původní"]
    assert vysledek["pocty"]["zakaznik"] == 1
    pred = aplikacni_db["server"] / vysledek["pred_obnovou"]
    assert pred.name.startswith("pred-obnovou-autoservis-")
    c = sqlite3.connect(pred)
    assert c.execute("select count(*) from zakaznik").fetchone()[0] == 2  # stav před obnovou zachován
    c.close()
    assert zalohy.nacti_stav(aplikacni_db["server"])["obnova"]["pred_obnovou"] == pred.name


def test_obnova_starsi_zalohy_doplni_sloupce(aplikacni_db):
    zaloha = zalohy.rucni(aplikacni_db["db"], aplikacni_db["server"])
    c = sqlite3.connect(zaloha)
    c.execute("alter table zakaznik drop column poznamka")  # záloha ze starší verze bez sloupce
    c.commit()
    c.close()
    zalohy.obnov(zaloha, aplikacni_db["db"], aplikacni_db["server"], aplikacni_db["eng"])
    c = sqlite3.connect(aplikacni_db["db"])
    assert "poznamka" in [r[1] for r in c.execute("pragma table_info(zakaznik)")]
    c.close()


def test_obnova_odmitne_neplatny_soubor(aplikacni_db, tmp_path):
    aplikacni_db["server"].mkdir(exist_ok=True)
    spatna = aplikacni_db["server"] / "rucni-x-20260101-000000.db"
    spatna.write_bytes(b"neni databaze")
    jina = aplikacni_db["server"] / "rucni-y-20260101-000000.db"
    c = sqlite3.connect(jina)
    c.execute("create table t (x)")
    c.commit()
    c.close()
    for soubor, text in ((spatna, "není databáze"), (jina, "není záloha Autoservisu")):
        with pytest.raises(zalohy.ChybaZalohy, match=text):
            zalohy.obnov(soubor, aplikacni_db["db"], aplikacni_db["server"], aplikacni_db["eng"])
    assert _zakaznici(aplikacni_db["eng"]) == ["TEST Původní"]  # nic se nezměnilo
    assert not list(aplikacni_db["server"].glob("pred-obnovou-*"))


def test_obnova_ze_sdilene_slozky(aplikacni_db, tmp_path):
    sdilena = tmp_path / "nas"
    sdilena.mkdir()
    (sdilena / zalohy.ZNACKA).write_text("")
    cil = zalohy.tydenni(str(sdilena), aplikacni_db["db"], aplikacni_db["server"])
    _pridej(aplikacni_db["eng"], "TEST Později")
    soubor = zalohy.soubor_zalohy(cil.name, "slozka", str(sdilena), aplikacni_db["server"])
    zalohy.obnov(soubor, aplikacni_db["db"], aplikacni_db["server"], aplikacni_db["eng"])
    assert _zakaznici(aplikacni_db["eng"]) == ["TEST Původní"]
    assert cil.exists() and not list((aplikacni_db["server"] / ".obnova").glob("*.db"))
    with pytest.raises(zalohy.ChybaZalohy):
        zalohy.soubor_zalohy("../autoservis.db", "slozka", str(sdilena), aplikacni_db["server"])


def test_web_obnova(aplikacni_db):
    zaloha = zalohy.rucni(aplikacni_db["db"], aplikacni_db["server"])
    _pridej(aplikacni_db["eng"], "TEST Později")
    r = client.get("/nastaveni/zalohy")
    assert 'hx-post="/nastaveni/zalohy/obnovit"' in r.text
    r = client.post("/nastaveni/zalohy/obnovit", data={"nazev": zaloha.name, "zdroj": "server"})
    assert r.status_code == 200 and "Obnoveno ze zálohy" in r.text and "pred-obnovou-" in r.text
    assert _zakaznici(aplikacni_db["eng"]) == ["TEST Původní"]
    r = client.post("/nastaveni/zalohy/obnovit", data={"nazev": "neni.db", "zdroj": "server"})
    assert "neexistuje" in r.text


# --- prázdná databáze (#83) ---

def _prazdna_db(tmp_path):
    from app import db as databaze
    soubor = tmp_path / "nova" / "autoservis.db"
    soubor.parent.mkdir()
    eng = databaze.vytvor_engine(f"sqlite:///{soubor}")
    databaze.init_db(eng)
    eng.dispose()
    return soubor


def test_prazdna_databaze_se_automaticky_nezalohuje(tmp_path):
    soubor = _prazdna_db(tmp_path)
    server, nas = tmp_path / "backups", tmp_path / "nas"
    nas.mkdir()
    (nas / zalohy.ZNACKA).write_text("")
    for i in range(3):  # tři dobré týdenní zálohy z dřívějška
        (nas / f"autoservis-tydenni-autoservis-2026010{i + 1}-030000.db").write_bytes(b"x")
    assert zalohy.je_prazdna(soubor)
    assert zalohy.naplanovane(str(nas), soubor, server) == []
    assert len(list(nas.glob("autoservis-tydenni-*.db"))) == 3  # nic nevytlačeno
    assert not server.exists() or not list(server.glob("*.db"))
    assert zalohy.rucni(soubor, server).exists()  # ručně jde zálohovat vždy


def test_po_prvnich_datech_se_zalohuje(tmp_path):
    soubor = _prazdna_db(tmp_path)
    c = sqlite3.connect(soubor)
    c.execute("insert into zakaznik (nazev, vytvoreno) values ('TEST', datetime('now'))")
    c.commit()
    c.close()
    assert not zalohy.je_prazdna(soubor)
    assert len(zalohy.naplanovane("", soubor, tmp_path / "backups")) == 1


def test_neznama_databaze_se_zalohuje(prostredi):
    assert not zalohy.je_prazdna(prostredi["db"])  # tabulka t, bez tabulek Autoservisu → raději zálohovat
