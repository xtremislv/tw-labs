"""Team login: one shared password → a signed, HttpOnly session cookie.

Deliberately simple (an internal tool for one team): no user table. The
cookie holds only an expiry timestamp signed with SESSION_SECRET, so it
can't be forged, and changing SESSION_SECRET logs everyone out.

In production the browser talks to Vercel, which proxies /api/* to Render
(vercel.json), so the cookie is first-party on the dashboard's own domain.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import threading
import time

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from .config import get_settings

COOKIE = "wi_session"
log = logging.getLogger("webintel.auth")
router = APIRouter(prefix="/api/auth", tags=["auth"])

_failures: dict[str, list[float]] = {}
_lock = threading.Lock()
MAX_FAILURES, WINDOW = 10, 15 * 60


def auth_required() -> bool:
    return bool(get_settings().dashboard_password)


def _secret() -> bytes:
    s = get_settings()
    if s.session_secret:
        return s.session_secret.encode()
    # Fallback keeps the app usable if only the password was set; rotating
    # the password then also logs everyone out.
    return hashlib.sha256(("webintel:" + s.dashboard_password).encode()).digest()


def make_token(now: float | None = None) -> str:
    exp = int((time.time() if now is None else now) + get_settings().session_days * 86400)
    body = base64.urlsafe_b64encode(json.dumps({"exp": exp}).encode()).decode().rstrip("=")
    sig = hmac.new(_secret(), body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{sig}"


def valid_token(token: str | None) -> bool:
    if not token or "." not in token:
        return False
    body, sig = token.rsplit(".", 1)
    expected = hmac.new(_secret(), body.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        return False
    try:
        data = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
        return float(data["exp"]) > time.time()
    except (ValueError, KeyError, TypeError):
        return False


def is_authenticated(request: Request) -> bool:
    return not auth_required() or valid_token(request.cookies.get(COOKIE))


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    return fwd.split(",")[0].strip() or (request.client.host if request.client else "?")


def _is_https(request: Request) -> bool:
    return request.headers.get("x-forwarded-proto", request.url.scheme) == "https"


class LoginBody(BaseModel):
    password: str = Field(min_length=1, max_length=200)


@router.get("/me")
def me(request: Request):
    return {"auth_required": auth_required(), "authenticated": is_authenticated(request)}


@router.post("/login")
def login(body: LoginBody, request: Request, response: Response):
    if not auth_required():
        return {"ok": True}
    ip = _client_ip(request)
    now = time.time()
    with _lock:
        recent = [t for t in _failures.get(ip, []) if now - t < WINDOW]
        _failures[ip] = recent
        if len(recent) >= MAX_FAILURES:
            raise HTTPException(429, "Too many attempts — wait 15 minutes and try again.")
    if not hmac.compare_digest(body.password.encode(), get_settings().dashboard_password.encode()):
        with _lock:
            _failures.setdefault(ip, []).append(now)
        log.warning("failed login from %s", ip)
        raise HTTPException(401, "Wrong password.")
    with _lock:
        _failures.pop(ip, None)
    response.set_cookie(
        COOKIE,
        make_token(),
        max_age=get_settings().session_days * 86400,
        httponly=True,
        secure=_is_https(request),
        samesite="lax",
        path="/",
    )
    return {"ok": True}


@router.post("/logout")
def logout(request: Request, response: Response):
    response.delete_cookie(COOKIE, path="/", secure=_is_https(request), httponly=True, samesite="lax")
    return {"ok": True}
