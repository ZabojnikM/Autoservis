import os

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, create_engine

from app.db import get_session, init_db
from app.main import app

# plánovač záloh v testech nespouštět (TestClient v režimu `with` by spustil lifespan)
os.environ.setdefault("AUTOSERVIS_AUTOZALOHY", "0")


@pytest.fixture
def engine():
    eng = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    init_db(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def session(engine):
    with Session(engine) as s:
        yield s


@pytest.fixture(autouse=True)
def testovaci_db(engine):
    """Web běží v testech nad čistou databází v paměti."""
    def _session():
        with Session(engine) as s:
            yield s

    app.dependency_overrides[get_session] = _session
    yield
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def bez_pinu(request, monkeypatch):
    """#219: PIN pro Nastavení je v testech vypnutý, kromě testů označených @pytest.mark.pin."""
    from app.services import pin
    if "pin" not in request.keywords:
        monkeypatch.setattr(pin, "ZAPNUTO", False)


@pytest.fixture(autouse=True, scope="session")
def zaznam_do_docasne_slozky(tmp_path_factory):
    """#225: start aplikace v testech (TestClient ve `with`) zapisuje záznam událostí do dočasné složky, ne do repa."""
    from app import zaznam
    puvodni = zaznam.soubor
    slozka = tmp_path_factory.mktemp("zaznam")
    zaznam.soubor = lambda: slozka / "autoservis.log"
    yield
    zaznam.soubor = puvodni
    zaznam.ukonci()
