"""Aktualizace z gitu – nad dočasnými repozitáři (origin → server), bez sítě."""
import json
import sqlite3
import subprocess

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import aktualizace as akt

client = TestClient(app)


def _git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def _commit(repo, soubor, obsah, zprava, tag=None):
    (repo / soubor).write_text(obsah, encoding="utf-8")
    _git(repo, "add", soubor)
    _git(repo, "commit", "-q", "-m", zprava)
    if tag:
        _git(repo, "tag", tag)
    _git(repo, "push", "-q", "--tags", "origin", "main")


@pytest.fixture
def repa(tmp_path, monkeypatch):
    """vyvoj → origin (bare) → server (klon na v0.1.0)."""
    for k in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{k}_NAME", "Test")
        monkeypatch.setenv(f"GIT_{k}_EMAIL", "test@example.com")
    monkeypatch.delenv("AUTOSERVIS_AKTUALIZACE", raising=False)
    origin, vyvoj, server = tmp_path / "origin.git", tmp_path / "vyvoj", tmp_path / "server"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    _git(tmp_path, "clone", "-q", str(origin), str(vyvoj))
    _git(vyvoj, "checkout", "-q", "-b", "main")
    _commit(vyvoj, "requirements.txt", "fastapi\n", "Základ")
    _commit(vyvoj, "app.py", "verze = 1\n", "Verze 1", tag="v0.1.0")
    _git(tmp_path, "clone", "-q", str(origin), str(server))
    _git(server, "checkout", "-q", "--detach", "v0.1.0")
    db = tmp_path / "autoservis.db"
    with sqlite3.connect(db) as c:
        c.execute("create table t (x)")
        c.execute("insert into t values (42)")
    c.close()
    return {"vyvoj": vyvoj, "server": server, "db": db, "zalohy": tmp_path / "backups"}


class Pip:
    def __init__(self, selze=False):
        self.volani, self.selze = 0, selze

    def __call__(self, repo):
        self.volani += 1
        if self.selze:
            raise akt.ChybaAktualizace("pip selhal")


def _instaluj(r, pip=None):
    return akt.nainstaluj(r["server"], db_path=r["db"], zalohy=r["zalohy"], pip=pip or Pip())


def test_stav_bez_kontroly(repa):
    s = akt.stav(repa["server"], zalohy=repa["zalohy"])
    assert s.git and s.popis == "v0.1.0" and not s.zkontrolovano and s.kanal is None


def test_kontrola_najde_nove_vydani_ne_rozpracovany_main(repa, monkeypatch):
    monkeypatch.setenv("AUTOSERVIS_AKTUALIZACE", "vydani")
    _commit(repa["vyvoj"], "app.py", "verze = 2\n", "Verze 2", tag="v0.2.0")
    _commit(repa["vyvoj"], "app.py", "verze = 3\n", "Rozpracováno")
    s = akt.stav(repa["server"], zkontrolovat=True, zalohy=repa["zalohy"])
    assert s.cil == "v0.2.0" and [p for _, p in s.nove_commity] == ["Verze 2"]


def test_kanal_main_bere_posledni_commit(repa, monkeypatch):
    monkeypatch.setenv("AUTOSERVIS_AKTUALIZACE", "main")
    _commit(repa["vyvoj"], "app.py", "verze = 3\n", "Rozpracováno")
    s = akt.stav(repa["server"], zkontrolovat=True, zalohy=repa["zalohy"])
    assert s.cil == "origin/main" and [p for _, p in s.nove_commity] == ["Rozpracováno"]


def test_instalace_zalohuje_db_a_prepne_kod(repa, monkeypatch):
    monkeypatch.setenv("AUTOSERVIS_AKTUALIZACE", "vydani")
    _commit(repa["vyvoj"], "app.py", "verze = 2\n", "Verze 2", tag="v0.2.0")
    pip = Pip()
    z = _instaluj(repa, pip)
    assert (repa["server"] / "app.py").read_text() == "verze = 2\n"
    assert pip.volani == 0 and z["zavislosti"] is False  # requirements.txt se nezměnil
    with sqlite3.connect(z["zaloha_db"]) as c:
        assert c.execute("select x from t").fetchone() == (42,)
    c.close()
    zaznam = json.loads((repa["zalohy"] / akt.ZAZNAM).read_text(encoding="utf-8"))
    assert zaznam["cil"] == "v0.2.0" and zaznam["nova"] == _git(repa["server"], "rev-parse", "HEAD")
    with pytest.raises(akt.ChybaAktualizace, match="aktuální"):
        _instaluj(repa)


def test_zmena_zavislosti_spusti_pip_a_pri_chybe_vrati_kod(repa, monkeypatch):
    monkeypatch.setenv("AUTOSERVIS_AKTUALIZACE", "vydani")
    _commit(repa["vyvoj"], "requirements.txt", "fastapi\nnovy-balik\n", "Nový balík", tag="v0.2.0")
    puvodni = _git(repa["server"], "rev-parse", "HEAD")
    with pytest.raises(akt.ChybaAktualizace, match="pip"):
        _instaluj(repa, Pip(selze=True))
    assert _git(repa["server"], "rev-parse", "HEAD") == puvodni
    assert akt.nacti_zaznam(repa["zalohy"]) is None
    pip = Pip()
    assert _instaluj(repa, pip)["zavislosti"] is True and pip.volani == 1


def test_vraceni_predchozi_verze(repa, monkeypatch):
    monkeypatch.setenv("AUTOSERVIS_AKTUALIZACE", "vydani")
    _commit(repa["vyvoj"], "app.py", "verze = 2\n", "Verze 2", tag="v0.2.0")
    z = _instaluj(repa)
    akt.vrat(repa["server"], zalohy=repa["zalohy"], pip=Pip())
    assert _git(repa["server"], "rev-parse", "HEAD") == z["predchozi"]
    assert (repa["server"] / "app.py").read_text() == "verze = 1\n"
    assert akt.nacti_zaznam(repa["zalohy"]) is None


def test_odmitne_bez_zapnuti_a_s_upravenymi_soubory(repa, monkeypatch):
    _commit(repa["vyvoj"], "app.py", "verze = 2\n", "Verze 2", tag="v0.2.0")
    with pytest.raises(akt.ChybaAktualizace, match="vypnutá"):
        _instaluj(repa)
    monkeypatch.setenv("AUTOSERVIS_AKTUALIZACE", "vydani")
    (repa["server"] / "app.py").write_text("ručně upraveno\n", encoding="utf-8")
    with pytest.raises(akt.ChybaAktualizace, match="ručně upravené"):
        _instaluj(repa)
    assert (repa["server"] / "app.py").read_text(encoding="utf-8") == "ručně upraveno\n"


def test_bez_git_klonu(tmp_path):
    s = akt.stav(tmp_path, zalohy=tmp_path / "backups")
    assert not s.git and not s.commit


def test_blok_se_zapnutou_aktualizaci(monkeypatch):
    s = akt.Stav(kanal="vydani", git=True, commit="abc1234", popis="v0.2.0", zkontrolovano=True, cil="v0.3.0",
                 cil_commit="def5678", nove_commity=[("def5678", "Nová karta")],
                 predchozi={"predchozi": "1111111aaa", "nova": "abc1234bbb", "cas": "2026-11-19T10:00:00",
                            "zaloha_db": "data/backups/pred-aktualizaci.db"})
    monkeypatch.setattr(akt, "stav", lambda *a, **k: s)
    monkeypatch.setattr(akt, "spusteny_commit", lambda *a: "abc1234")
    r = client.post("/nastaveni/aktualizace/zkontrolovat").text
    assert "v0.3.0" in r and "Nová karta" in r and 'hx-post="/nastaveni/aktualizace/instalovat"' in r
    assert "Vrátit předchozí verzi" in r and "pred-aktualizaci.db" in r and "restartujte" not in r
    # #49: název zálohy a datum viditelně, celá cesta jen v Podrobnostech
    assert "<strong>pred-aktualizaci.db</strong> (2026-11-19)" in r and "<details" in r
    monkeypatch.setattr(akt, "spusteny_commit", lambda *a: "0000000")  # nainstalováno, čeká na restart
    assert "restartujte aplikaci" in client.get("/nastaveni/aktualizace").text


def test_blok_v_nastaveni(monkeypatch):
    monkeypatch.delenv("AUTOSERVIS_AKTUALIZACE", raising=False)
    assert 'hx-get="/nastaveni/aktualizace"' in client.get("/nastaveni").text
    r = client.get("/nastaveni/aktualizace")
    assert r.status_code == 200 and 'id="aktualizace"' in r.text and "AUTOSERVIS_AKTUALIZACE" in r.text
    assert "Nainstalovat" not in r.text  # na vývojovém počítači vypnuto
    r = client.post("/nastaveni/aktualizace/instalovat")
    assert r.status_code == 200 and "vypnutá" in r.text
    assert "commit" in client.get("/nastaveni/aktualizace/spusteno").json()
