"""HTTP with retries, exponential backoff + jitter, Retry-After and a per-host minimum interval."""

from __future__ import annotations

import random
import threading
import time
from urllib.parse import urlsplit

import httpx

from radar.config import get_settings

RETRY_STATUS = {408, 425, 429, 500, 502, 503, 504}


class RateLimiter:
    def __init__(self) -> None:
        self._next: dict[str, float] = {}
        self._lock = threading.Lock()

    def wait(self, host: str, min_interval: float) -> None:
        if min_interval <= 0:
            return
        with self._lock:
            now = time.monotonic()
            at = max(now, self._next.get(host, 0.0))
            self._next[host] = at + min_interval
        if at > now:
            time.sleep(at - now)


_limiter = RateLimiter()


def client(timeout: float | None = None, **kw) -> httpx.Client:
    s = get_settings()
    headers = {"User-Agent": s.http_user_agent, "Accept-Language": s.accept_language, **kw.pop("headers", {})}
    return httpx.Client(timeout=timeout or s.http_timeout, headers=headers, follow_redirects=True, **kw)


def request(c: httpx.Client, method: str, url: str, *, retries: int = 4, backoff: float = 2.0,
            min_interval: float = 0.0, sleep=time.sleep, **kw) -> httpx.Response:
    """Send with retries on network errors and 408/429/5xx. Raises the last error."""
    host = urlsplit(url).netloc
    for attempt in range(retries + 1):
        _limiter.wait(host, min_interval)
        try:
            r = c.request(method, url, **kw)
        except httpx.TransportError:
            if attempt == retries:
                raise
            sleep(backoff * 2**attempt + random.uniform(0, backoff))
            continue
        if r.status_code in RETRY_STATUS and attempt < retries:
            ra = r.headers.get("retry-after", "")
            delay = float(ra) if ra.isdigit() else backoff * 2**attempt + random.uniform(0, backoff)
            sleep(min(delay, 300))
            continue
        r.raise_for_status()
        return r
    raise RuntimeError("unreachable")
