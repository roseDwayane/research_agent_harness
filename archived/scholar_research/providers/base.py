"""HTTP layer: one cached, retrying, rate-limited ``HttpClient``.

Every request is content-addressed (method + url + sorted params + body) and
stored in ``.cache/http``.  Providers never call httpx directly.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import httpx

from ..cache import Cache

RETRY_STATUS = {406, 429, 500, 502, 503, 504}  # 406: arXiv's throttling answer


class ProviderError(RuntimeError):
    pass


@dataclass
class Response:
    status: int
    text: str | None
    body_bytes: bytes | None
    headers: dict[str, str]
    url: str
    cache_hit: bool
    fetched_at: str | None

    def json(self) -> Any:
        import json

        if self.text is None:
            raise ProviderError(f"no text body for {self.url}")
        return json.loads(self.text)

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300


class RateLimiter:
    """Simple per-host minimum interval (seconds between requests)."""

    def __init__(self) -> None:
        self._last: dict[str, float] = {}
        self.intervals: dict[str, float] = {}

    def wait(self, host: str) -> None:
        iv = self.intervals.get(host, 0.0)
        if iv <= 0:
            return
        last = self._last.get(host)
        if last is not None:
            delta = time.monotonic() - last
            if delta < iv:
                time.sleep(iv - delta)
        self._last[host] = time.monotonic()


class HttpClient:
    def __init__(self, cache: Cache, timeout: float = 30.0, max_attempts: int = 4, user_agent: str = "scholar-research/0.1 (+https://github.com/roseDwayane)"):
        self.cache = cache
        self.timeout = timeout
        self.max_attempts = max_attempts
        self.limiter = RateLimiter()
        self._client = httpx.Client(timeout=timeout, follow_redirects=True, headers={"User-Agent": user_agent})
        self.failures: list[str] = []

    def close(self) -> None:
        self._client.close()

    # ------------------------------------------------------------------ #
    def request(self, method: str, url: str, *, params: dict[str, Any] | None = None, headers: dict[str, str] | None = None, body: str | None = None, binary: bool = False, cache_ns: str = "http", secret_headers: tuple[str, ...] = ("x-api-key", "api_key")) -> Response:
        params = {k: v for k, v in (params or {}).items() if v is not None}
        # secrets never enter the cache key — same request with/without a key hits the same entry
        public_params = {k: v for k, v in params.items() if k.lower() not in secret_headers}
        public_headers = {k: v for k, v in (headers or {}).items() if k.lower() not in secret_headers}
        descriptor = {"method": method.upper(), "url": url, "params": sorted(public_params.items()), "headers": sorted(public_headers.items()), "body": body, "binary": binary}

        def fetch() -> dict[str, Any]:
            host = httpx.URL(url).host or ""
            last_exc: Exception | None = None
            for attempt in range(self.max_attempts):
                self.limiter.wait(host)
                try:
                    r = self._client.request(method, url, params=params, headers=headers, content=body)
                except httpx.HTTPError as e:
                    last_exc = e
                    time.sleep(min(2 ** attempt, 20))
                    continue
                if r.status_code in RETRY_STATUS and attempt < self.max_attempts - 1:
                    retry_after = r.headers.get("retry-after")
                    delay = float(retry_after) if retry_after and retry_after.isdigit() else min(2 ** attempt * 2, 30)
                    time.sleep(delay)
                    continue
                rec: dict[str, Any] = {
                    "status": r.status_code,
                    "headers": {k: v for k, v in r.headers.items() if k.lower() in ("content-type", "content-length", "retry-after")},
                    "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                    "final_url": str(r.url),
                }
                if binary:
                    rec["body_b64"] = Cache.b64(r.content)
                else:
                    rec["text"] = r.text
                return rec
            raise ProviderError(f"{method} {url} failed after {self.max_attempts} attempts: {last_exc}")

        rec = self.cache.get_or_fetch(cache_ns, descriptor, fetch)
        return Response(
            status=int(rec["status"]),
            text=rec.get("text"),
            body_bytes=Cache.unb64(rec["body_b64"]) if rec.get("body_b64") else None,
            headers=rec.get("headers", {}),
            url=rec.get("final_url", url),
            cache_hit=rec["_cache"]["hit"],
            fetched_at=rec.get("fetched_at"),
        )

    def get(self, url: str, **kw: Any) -> Response:
        return self.request("GET", url, **kw)

    def post(self, url: str, body: str, **kw: Any) -> Response:
        return self.request("POST", url, body=body, **kw)
