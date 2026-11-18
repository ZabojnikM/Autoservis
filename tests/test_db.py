from sqlalchemy import text
from sqlmodel import create_engine

from app.db import doplnit_sloupce


def test_doplneni_chybejiciho_sloupce(tmp_path):
    eng = create_engine(f"sqlite:///{tmp_path / 'stara.db'}")
    with eng.begin() as c:  # „stará“ tabulka nastavení bez sloupce hodnota
        c.execute(text("CREATE TABLE nastaveni (klic VARCHAR PRIMARY KEY)"))
        c.execute(text("INSERT INTO nastaveni (klic) VALUES ('x')"))
    assert doplnit_sloupce(eng) == ["nastaveni.hodnota"]
    assert doplnit_sloupce(eng) == []
    with eng.begin() as c:
        assert c.execute(text("SELECT hodnota FROM nastaveni")).scalar() == ""
    eng.dispose()
