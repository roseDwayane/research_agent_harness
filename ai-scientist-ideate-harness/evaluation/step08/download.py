"""Download and verify the public IdeaBench dataset release."""
from __future__ import annotations

import hashlib
import json
import os
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPOSITORY = "kdm-daiict/Ideabench"
FILES = ("target_papers.csv", "filtered_references.csv", "ideabench_clustering.json")
MANIFEST = "download_manifest.json"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _open_json(url: str, timeout: float, opener=urllib.request.urlopen) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": "research-agent-harness/ideabench-downloader"})
    with opener(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def resolve_revision(revision: str, *, timeout: float = 60, opener=urllib.request.urlopen) -> str:
    quoted = urllib.parse.quote(revision, safe="")
    doc = _open_json(f"https://huggingface.co/api/datasets/{REPOSITORY}/revision/{quoted}", timeout, opener)
    sha = str(doc.get("sha") or "").strip()
    if len(sha) < 7:
        raise RuntimeError(f"Hugging Face returned no commit SHA for revision {revision!r}")
    return sha


def verify_download(out: Path) -> dict:
    manifest_path = Path(out) / MANIFEST
    if not manifest_path.is_file():
        raise FileNotFoundError(f"missing {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for name in FILES:
        expected = (manifest.get("files") or {}).get(name) or {}
        path = Path(out) / name
        if not path.is_file():
            raise FileNotFoundError(f"download is incomplete: {path} is missing")
        actual = _sha256(path)
        if actual != expected.get("sha256"):
            raise ValueError(f"download checksum mismatch for {name}: expected {expected.get('sha256')}, got {actual}")
    return manifest


def download(out: Path, *, revision: str = "main", timeout: float = 300,
             opener=urllib.request.urlopen, say=print) -> dict:
    out = Path(out)
    manifest_path = out / MANIFEST
    if manifest_path.is_file():
        manifest = verify_download(out)
        say(f"Reusing verified IdeaBench dataset at {out} ({manifest['resolved_revision'][:12]})")
        return manifest
    out.mkdir(parents=True, exist_ok=True)
    resolved = resolve_revision(revision, timeout=timeout, opener=opener)
    records = {}
    for name in FILES:
        url = f"https://huggingface.co/datasets/{REPOSITORY}/resolve/{resolved}/{name}?download=true"
        target, partial = out / name, out / f"{name}.part"
        request = urllib.request.Request(url, headers={"User-Agent": "research-agent-harness/ideabench-downloader"})
        say(f"Downloading {name} ...")
        try:
            with opener(request, timeout=timeout) as response, partial.open("wb") as stream:
                while chunk := response.read(1024 * 1024):
                    stream.write(chunk)
            os.replace(partial, target)
        finally:
            if partial.exists():
                partial.unlink()
        records[name] = {"url": url, "bytes": target.stat().st_size, "sha256": _sha256(target)}
    manifest = {"schema": "ideabench-download/1", "repository": REPOSITORY,
                "requested_revision": revision, "resolved_revision": resolved,
                "downloaded_at": datetime.now(timezone.utc).isoformat(), "files": records,
                "license": "MIT", "dataset_page": f"https://huggingface.co/datasets/{REPOSITORY}"}
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    verify_download(out)
    say(f"Verified {len(FILES)} IdeaBench files at {out}")
    return manifest
