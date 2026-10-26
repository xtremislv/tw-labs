"""One shared HTTP client for all crawling: per-domain politeness delay,
conditional GET (ETag / If-Modified-Since), robots.txt checks."""
from __future__ import annotations

import threading
import time
import urllib.robotparser
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx

from .config import get_settings


@dataclass
class FetchResult:
    url: str
    status: int
    text: str
    headers: dict
    not_modified: bool = False
    content: bytes = b""

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300


class FetchError(Exception):
    pass


class Fetcher:
    def __init__(self, client: httpx.Client | None = None):
        s = get_settings()
        self.delay = s.per_domain_delay_seconds
        self.respect_robots = s.respect_robots_txt
        self.client = client or httpx.Client(
            headers={
                "User-Agent": s.user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/json;q=0.8,*/*;q=0.7",
                "Accept-Language": "en-IN,en;q=0.9",
            },
            timeout=s.request_timeout_seconds,
            follow_redirects=True,
        )
        self._last_hit: dict[str, float] = {}
        self._robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}
        self._lock = threading.Lock()

    # ── politeness ──────────────────────────────────────────────────────
    def _wait_turn(self, host: str) -> None:
        # Reserve this host's next slot under the lock, then sleep outside it,
        # so concurrent callers for *different* hosts never wait on each other.
        with self._lock:
            now = time.monotonic()
            start = max(now, self._last_hit.get(host, float("-inf")) + self.delay)
            self._last_hit[host] = start
        if start > now:
            time.sleep(start - now)

    def robots_for(self, url: str) -> urllib.robotparser.RobotFileParser | None:
        p = urlsplit(url)
        key = f"{p.scheme}://{p.netloc}"
        if key not in self._robots:
            rp = urllib.robotparser.RobotFileParser()
            try:
                r = self._raw_get(key + "/robots.txt")
                if r.status_code == 200:
                    rp.parse(r.text.splitlines())
                else:
                    rp.parse([])  # missing robots.txt = everything allowed
                self._robots[key] = rp
            except httpx.HTTPError:
                self._robots[key] = None
        return self._robots[key]

    def allowed(self, url: str) -> bool:
        if not self.respect_robots:
            return True
        rp = self.robots_for(url)
        if rp is None:
            return True
        # Check both our identifying token and the generic rules.
        return rp.can_fetch("TWLabsWebIntel", url) and rp.can_fetch("*", url)

    # ── requests ────────────────────────────────────────────────────────
    def _raw_get(self, url: str, headers: dict | None = None) -> httpx.Response:
        self._wait_turn(urlsplit(url).netloc)
        return self.client.get(url, headers=headers or {})

    def get(
        self,
        url: str,
        *,
        etag: str | None = None,
        last_modified: str | None = None,
        check_robots: bool = True,
    ) -> FetchResult:
        if check_robots and not self.allowed(url):
            raise FetchError(f"blocked by robots.txt: {url}")
        headers = {}
        if etag:
            headers["If-None-Match"] = etag
        if last_modified:
            headers["If-Modified-Since"] = last_modified
        try:
            r = self._raw_get(url, headers)
        except httpx.HTTPError as e:
            raise FetchError(f"{type(e).__name__}: {e}") from e
        if r.status_code == 304:
            return FetchResult(str(r.url), 304, "", dict(r.headers), not_modified=True)
        content = r.content
        if content[:2] == b"\x1f\x8b":  # a .xml.gz sitemap served without Content-Encoding
            import gzip

            try:
                content = gzip.decompress(content)
            except OSError:
                pass
            text = content.decode(r.encoding or "utf-8", errors="replace")
        else:
            text = r.text
        return FetchResult(str(r.url), r.status_code, text, dict(r.headers), content=content)

    def close(self) -> None:
        self.client.close()
