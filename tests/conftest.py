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
