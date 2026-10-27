from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..database import get_db

router = APIRouter()


@router.get("/healthz")
async def healthz():
    """Render's health check and the keep-awake ping. Answers instantly and
    never waits for a database connection: if background work has the small
    free-plan connection pool busy, Render must not mistake that for a crash."""
    return {"ok": True}


@router.get("/healthz/db")
def healthz_db(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {"ok": True}
