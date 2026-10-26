import os
import tempfile

_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
# Set TEST_DATABASE_URL to run the suite against Postgres instead of SQLite.
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL") or f"sqlite:///{_db.name}"
os.environ["PER_DOMAIN_DELAY_SECONDS"] = "0"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.database import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh_db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield


@pytest.fixture
def db():
    with SessionLocal() as s:
        yield s


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def _reset_sitemap_memory():
    from app import tracker
    tracker._CHILD_SEEN.clear()
    yield
    tracker._CHILD_SEEN.clear()
