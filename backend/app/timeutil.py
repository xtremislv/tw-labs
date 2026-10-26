from datetime import datetime, timezone

from dateutil import parser as _dtparser


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(dt: datetime | None) -> datetime | None:
    """Normalise to an aware UTC datetime (SQLite hands back naive ones)."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_dt(value) -> datetime | None:
    """Best-effort parse of the many date formats sitemaps/feeds/JSON-LD use.

    Returns None for anything unparseable or clearly bogus (before 2000 or
    more than a day in the future — some CMSes emit 0000-00-00 or far-future
    placeholder dates).
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        s = str(value).strip()
        if not s or s.startswith("0000"):
            return None
        try:
            dt = _dtparser.parse(s)
        except (ValueError, OverflowError, TypeError):
            return None
    dt = as_utc(dt)
    if dt.year < 2000:
        return None
    if (dt - utcnow()).total_seconds() > 86400:
        return None
    return dt
