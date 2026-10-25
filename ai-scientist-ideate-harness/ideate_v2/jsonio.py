"""File primitives: bounded reads, atomic writes, locked appends, hashes.

Every write is LF-only and atomic (temporary file + ``os.replace``) on every platform; appends to shared JSONL files
take a lock file created with O_EXCL (portable - no ``fcntl``), so concurrent writers cannot lose lines.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any

DEFAULT_MAX_BYTES = 50 * 1024 * 1024        # refuse to load a JSON/JSONL file larger than this
LOCK_TIMEOUT_S = 10.0
LOCK_STALE_S = 60.0                         # a lock file older than this is assumed abandoned by a crashed writer


class FileTooLarge(OSError):
    pass


class LockTimeout(TimeoutError):
    pass


def sha256_file(path: Path) -> str | None:
    """Hex sha256 of the bytes - the same format as the legacy it_common.sha256_file."""
    p = Path(path)
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None


def sha256_json(data: Any) -> str:
    """Hex sha256 of canonical JSON - the same format as the legacy it_common.sha256_json."""
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def _check_size(p: Path, max_bytes: int) -> None:
    size = p.stat().st_size
    if size > max_bytes:
        raise FileTooLarge(f"{p} is {size} bytes, over the {max_bytes}-byte limit")


def read_json(path: Path, max_bytes: int = DEFAULT_MAX_BYTES) -> Any:
    p = Path(path)
    _check_size(p, max_bytes)
    return json.loads(p.read_text(encoding="utf-8"))


def read_jsonl(path: Path, max_bytes: int = DEFAULT_MAX_BYTES) -> tuple[list[dict], list[dict]]:
    """-> (records, problems). A line that does not parse is reported with its number, never silently skipped."""
    p = Path(path)
    if not p.exists():
        return [], []
    _check_size(p, max_bytes)
    records, problems = [], []
    for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as e:
            problems.append({"line": i, "error": f"not JSON: {e.msg}"})
            continue
        if not isinstance(obj, dict):
            problems.append({"line": i, "error": "not a JSON object"})
            continue
        records.append(obj)
    return records, problems


def write_text_atomic(path: Path, text: str) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + f".{os.getpid()}.tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    os.replace(tmp, p)


def write_json_atomic(path: Path, data: Any) -> None:
    write_text_atomic(path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")


class FileLock:
    """A lock file created with O_CREAT|O_EXCL. Portable; a stale lock (crashed writer) is broken after LOCK_STALE_S."""

    def __init__(self, target: Path, timeout: float = LOCK_TIMEOUT_S, stale_after: float = LOCK_STALE_S):
        self.lock = Path(str(target) + ".lock")
        self.timeout = timeout
        self.stale_after = stale_after

    def __enter__(self) -> "FileLock":
        self.lock.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                fd = os.open(self.lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, str(os.getpid()).encode())
                os.close(fd)
                return self
            except (FileExistsError, PermissionError):
                # Windows raises PermissionError, not FileExistsError, while another writer's lock file is being
                # deleted ("delete pending"): that is contention too, so wait and retry until the deadline.
                try:
                    if time.time() - self.lock.stat().st_mtime > self.stale_after:
                        self.lock.unlink(missing_ok=True)
                        continue
                except (FileNotFoundError, PermissionError):
                    pass
                if time.monotonic() > deadline:
                    raise LockTimeout(f"could not lock {self.lock} within {self.timeout}s")
                time.sleep(0.02)

    def __exit__(self, *exc) -> None:
        for _ in range(50):                       # Windows: a concurrent open of the lock path can block the delete
            try:
                self.lock.unlink(missing_ok=True)
                return
            except PermissionError:
                time.sleep(0.01)
        self.lock.unlink(missing_ok=True)


def append_jsonl_unlocked(path: Path, record: dict) -> None:
    """Append one JSON line; the caller holds the FileLock. The line and its newline go out in one write, and a torn
    last line from an earlier crash is terminated first so it cannot merge with this record."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, ensure_ascii=False) + "\n"
    if p.exists() and p.stat().st_size > 0:
        with open(p, "rb") as f:
            f.seek(-1, os.SEEK_END)
            if f.read(1) != b"\n":
                line = "\n" + line
    with open(p, "a", encoding="utf-8", newline="\n") as f:
        f.write(line)
        f.flush()
        os.fsync(f.fileno())


def append_jsonl(path: Path, record: dict) -> None:
    """Append one JSON line under the file's lock."""
    with FileLock(Path(path)):
        append_jsonl_unlocked(path, record)
