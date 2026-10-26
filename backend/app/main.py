import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import auth
from .config import get_settings
from .routers import articles, health, sites, system

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("webintel.api")


def _check_production_config() -> None:
    s = get_settings()
    if s.dashboard_password and not s.session_secret:
        log.warning("SESSION_SECRET is not set — deriving one from the password. Set SESSION_SECRET too.")
    if not s.dashboard_password:
        # Login is optional: the team chose an open internal link. Setting
        # DASHBOARD_PASSWORD on Render turns the login screen back on.
        log.info("DASHBOARD_PASSWORD is not set — the dashboard is open to anyone with the link (no login).")


@asynccontextmanager
async def lifespan(_: FastAPI):
    _check_production_config()
    sched = None
    if get_settings().embedded_worker:
        from .worker import start_embedded

        sched = start_embedded()
    yield
    if sched is not None:
        sched.shutdown(wait=False)


app = FastAPI(title="TW-Labs Web Intel API", version="0.2.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origin_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Content-Type"],
)


@app.middleware("http")
async def guard(request: Request, call_next):
    path = request.url.path
    if path.startswith("/api/") and not path.startswith("/api/auth/") and request.method != "OPTIONS":
        if not auth.is_authenticated(request):
            return JSONResponse(status_code=401, content={"detail": "Please log in."}, headers={"Cache-Control": "no-store"})
    response = await call_next(request)
    if path.startswith("/api/"):
        # Never let Vercel's CDN (or a browser) cache API answers.
        response.headers["Cache-Control"] = "no-store"
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    return response


@app.exception_handler(Exception)
async def _unhandled(_: Request, exc: Exception):  # never leak stack traces / DB URLs
    log.exception("unhandled error", exc_info=exc)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


app.include_router(health.router)
app.include_router(auth.router)
app.include_router(sites.router)
app.include_router(articles.router)
app.include_router(system.router)
