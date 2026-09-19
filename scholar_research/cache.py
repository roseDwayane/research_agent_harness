"""Content-addressed cache (plan §4.1).

Key = sha256(canonical(request descriptor)).  Three namespaces live under
``{session}/.cache/``:

    http/{hash}.json   {request, status, headers(subset), body_text|body_b64, fetched_at}
    pdf/{sha256}.pdf   raw binary blobs, addressed by their own content hash
    llm/{hash}.json    {prompt_version, model, params, messages, schema, response}

Modes
-----
read-write  hit → return; miss → caller fetches, we store.        (default)
read-only   hit → return; miss → CacheMissError.                 (replay)
refresh     never read; always fetch and overwrite.              (--refresh)
off         never read, never write.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .config import CacheMode
from .utils import dump_json, load_json, sha256_bytes, sha256_obj


class CacheMissError(RuntimeError):
    """Raised in read-only (replay) mode when a request has no cached response."""

    def __init__(self, namespace: str, key: str, descriptor: Any):
        self.namespace, self.key, self.descriptor = namespace, key, descriptor
        super().__init__(f"cache miss in {namespace}/{key[:12]}… for {descriptor}")


@dataclass
class CacheStats:
    hits: int = 0
    misses: int = 0
    writes: int = 0
    by_namespace: dict[str, dict[str, int]] = field(default_factory=dict)

    def bump(self, ns: str, kind: str) -> None:
        setattr(self, kind, getattr(self, kind) + 1)
        d = self.by_namespace.setdefault(ns, {"hits": 0, "misses": 0, "writes": 0})
        d[kind] += 1

    def as_dict(self) -> dict[str, Any]:
        return {"hits": self.hits, "misses": self.misses, "writes": self.writes, "by_namespace": self.by_namespace}


class Cache:
    def __init__(self, root: Path, mode: CacheMode = "read-write"):
        self.root = Path(root)
        self.mode = mode
        self.stats = CacheStats()

    # ------------------------------------------------------------------ #
    @staticmethod
    def key_for(descriptor: Any) -> str:
        return sha256_obj(descriptor)

    def _path(self, ns: str, key: str, ext: str = ".json") -> Path:
        return self.root / ns / f"{key}{ext}"

    def get_or_fetch(self, ns: str, descriptor: Any, fetch: Callable[[], dict[str, Any]]) -> dict[str, Any]:
        """Generic JSON-record cache. ``descriptor`` must be JSON-serialisable."""
        key = self.key_for(descriptor)
        path = self._path(ns, key)
        if self.mode in ("read-write", "read-only") and path.exists():
            self.stats.bump(ns, "hits")
            rec = load_json(path)
            rec["_cache"] = {"hit": True, "key": key}
            return rec
        if self.mode == "read-only":
            self.stats.bump(ns, "misses")
            raise CacheMissError(ns, key, descriptor)
        self.stats.bump(ns, "misses")
        rec = fetch()
        rec = dict(rec)
        rec["_descriptor"] = descriptor
        if self.mode != "off":
            dump_json(path, rec)
            self.stats.bump(ns, "writes")
        rec["_cache"] = {"hit": False, "key": key}
        return rec

    # ------------------------------------------------------------------ #
    # Binary blobs (PDFs) — addressed by content hash; an index record maps
    # the *request* descriptor to the blob hash so replay can find it.
    # ------------------------------------------------------------------ #
    def put_blob(self, data: bytes, ext: str = ".pdf") -> str:
        h = sha256_bytes(data)
        path = self._path("pdf", h, ext)
        if self.mode != "off" and not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            self.stats.bump("pdf", "writes")
        return h

    def get_blob(self, sha: str, ext: str = ".pdf") -> bytes | None:
        path = self._path("pdf", sha, ext)
        if path.exists():
            self.stats.bump("pdf", "hits")
            return path.read_bytes()
        return None

    def blob_path(self, sha: str, ext: str = ".pdf") -> Path:
        return self._path("pdf", sha, ext)

    @staticmethod
    def b64(data: bytes) -> str:
        return base64.b64encode(data).decode("ascii")

    @staticmethod
    def unb64(text: str) -> bytes:
        return base64.b64decode(text.encode("ascii"))
