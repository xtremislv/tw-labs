import pytest
from fastapi.testclient import TestClient

from app import auth
from app.config import Settings, get_settings
from app.main import app


@pytest.fixture
def locked(monkeypatch):
    monkeypatch.setenv("DASHBOARD_PASSWORD", "correct horse")
    monkeypatch.setenv("SESSION_SECRET", "test-secret")
    get_settings.cache_clear()
    auth._failures.clear()
    yield
    get_settings.cache_clear()


def test_api_requires_login_when_password_set(locked):
    c = TestClient(app)
    assert c.get("/healthz").status_code == 200  # Render health check stays open
    assert c.get("/api/sites").status_code == 401
    assert c.get("/api/auth/me").json() == {"auth_required": True, "authenticated": False}
    assert c.post("/api/auth/login", json={"password": "nope"}).status_code == 401
    r = c.post("/api/auth/login", json={"password": "correct horse"})
    assert r.status_code == 200 and "httponly" in r.headers["set-cookie"].lower()
    assert c.get("/api/sites").status_code == 200
    assert c.get("/api/sites").headers["cache-control"] == "no-store"
    c.post("/api/auth/logout")
    assert c.get("/api/sites").status_code == 401


def test_forged_or_expired_cookie_rejected(locked):
    good = auth.make_token()
    assert auth.valid_token(good)
    body, sig = good.rsplit(".", 1)
    assert not auth.valid_token(body + "." + "0" * len(sig))
    assert not auth.valid_token(auth.make_token(now=0))  # expired long ago
    c = TestClient(app)
    c.cookies.set(auth.COOKIE, body + ".bad")
    assert c.get("/api/sites").status_code == 401


def test_login_rate_limited(locked):
    c = TestClient(app)
    for _ in range(auth.MAX_FAILURES):
        c.post("/api/auth/login", json={"password": "x"})
    assert c.post("/api/auth/login", json={"password": "correct horse"}).status_code == 429


def test_starts_open_on_render_without_password(monkeypatch):
    # No DASHBOARD_PASSWORD = no login (the team's chosen default).
    monkeypatch.setenv("RENDER", "true")
    monkeypatch.delenv("DASHBOARD_PASSWORD", raising=False)
    get_settings.cache_clear()
    try:
        with TestClient(app) as c:
            assert c.get("/api/auth/me").json() == {"auth_required": False, "authenticated": True}
            assert c.get("/api/sites").status_code == 200
    finally:
        get_settings.cache_clear()


def test_database_url_normalised():
    assert Settings(database_url="postgres://u:p@h:5432/d").sqlalchemy_url == "postgresql+psycopg://u:p@h:5432/d"
    assert Settings(database_url="postgresql://u:p@h/d?sslmode=require").sqlalchemy_url == "postgresql+psycopg://u:p@h/d?sslmode=require"
    assert Settings(database_url="sqlite:///./dev.db").sqlalchemy_url == "sqlite:///./dev.db"
