"""Bulk-add sites from a JSON file (safe to re-run; existing ones are skipped).

    python scripts/add_sites.py sites.example.json

The worker discovers feeds and imports 30 days for each new site.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.models import JobRequest, Site  # noqa: E402
from app.urlnorm import normalize_domain  # noqa: E402


def main(path: str) -> None:
    entries = json.loads(Path(path).read_text(encoding="utf-8"))
    with SessionLocal() as db:
        for e in entries:
            domain = normalize_domain(e["url"])
            if db.scalar(select(Site).where(Site.domain == domain)):
                print(f"skip  {domain} (already tracked)")
                continue
            site = Site(domain=domain, name=e.get("name") or domain, home_url=f"https://{domain}/",
                        cohort=e.get("cohort"), is_own_site=bool(e.get("is_own_site")))
            db.add(site)
            db.flush()
            db.add(JobRequest(kind="backfill", site_id=site.id))
            print(f"added {domain}")
        db.commit()


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "sites.example.json")
