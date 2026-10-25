"""Shared helpers for the ideate Unit modules (it_*.py): io, atomic writes, hashing, word counting.

Imported by sibling modules only; it has no CLI of its own. It writes nothing by itself - every file is written by the
Unit module that owns it.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import unicodedata
import sys
from datetime import datetime
from pathlib import Path



def smoke_cap(default: int) -> int:
    """A collection-size cap: `default`, or IDEATE_SMOKE_CAP when set (a smoke test of the whole pipeline on a
    handful of papers - every per-source, dense and snowball limit becomes that number). Unset: unchanged."""
    v = os.environ.get("IDEATE_SMOKE_CAP", "").strip()
    return min(default, int(v)) if v.isdigit() and int(v) > 0 else default

def read_json(path: Path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


class InjectedFailure(BaseException):
    """Raised by the interrupt test harness (IDEATE_FAIL_AFTER_WRITES=N): the N+1-th write stops between writing its
    temporary file and renaming it - the moment a crash would leave a half-written file. A BaseException, like a
    KeyboardInterrupt, so that no `except Exception` turns the crash into a degraded path."""


_WRITES = [0]


def _interrupt_point() -> None:
    n = os.environ.get("IDEATE_FAIL_AFTER_WRITES", "")
    if n == "":
        return
    if _WRITES[0] >= int(n):
        raise InjectedFailure(f"injected failure after {n} write(s)")
    _WRITES[0] += 1


def write_text(path: Path, text: str) -> None:
    """Write-to-temp-then-rename so a crash never leaves a truncated file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    _interrupt_point()
    os.replace(tmp, path)


def write_json(path: Path, data) -> None:
    write_text(path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def write_json_stable(path: Path, data: dict, stamps: tuple = ("at",)) -> bool:
    """write_json for a deterministic Unit's output: when the file already holds the same content apart from its
    top-level time stamps (`at`, or the keys in `stamps`), it is kept as it is, so an unchanged rerun leaves its hash -
    and the Units downstream - alone."""
    path = Path(path)
    if path.exists():
        try:
            old = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            old = None
        if isinstance(old, dict) and {k: v for k, v in old.items() if k not in stamps} == \
                json.loads(json.dumps({k: v for k, v in data.items() if k not in stamps}, ensure_ascii=False)):
            return False
    write_json(path, data)
    return True


def read_jsonl(path: Path) -> list:
    """One JSON object per line. A line that does not parse is an error naming the line, never skipped."""
    p = Path(path)
    if not p.exists():
        return []
    out = []
    for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            raise ValueError(f"{p}: line {i} is not valid JSON (an interrupted write?)") from None
    return out


def append_jsonl(path: Path, records: list) -> None:
    """Add lines to an append-only log atomically: read, add, write a temporary file, rename."""
    if not records:
        return
    p = Path(path)
    old = p.read_text(encoding="utf-8") if p.exists() else ""
    if old and not old.endswith("\n"):
        old += "\n"
    write_text(p, old + "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records))


def die(msg: str, code: int = 1):
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(code)


def require_protocol(cfg: dict, rd=None) -> None:
    """Every search-block command and check runs on a topic framed by A1: step0 must hold A1.p's protocol."""
    if "protocol" not in (cfg or {}):
        where = f"{Path(rd) / 'step0_session_config.json'}" if rd else "step0_session_config.json"
        die(f"{where} has no `protocol`: the literature search starts at A1 "
            "(`ideate_tools.py frame set-protocol <RD> protocol.json`; references/search/A1-frame.md#a1p)", 2)


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def sha256_file(path: Path) -> str | None:
    p = Path(path)
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None


def sha256_json(data) -> str:
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


# The same stop-word set the search bridge uses when it shortens a query (mcp_bridge.shorten): a query's length is
# counted in content words, the way the AND-ing backends see it.
STOP_WORDS = {"a", "an", "the", "of", "for", "and", "or", "in", "on", "to", "with", "by", "from", "under", "via", "using"}


def content_words(text: str) -> list[str]:
    return [w for w in re.findall(r"[^\s\"()]+", str(text or "")) if w.lower() not in STOP_WORDS]


def norm_title(title) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(title or "").lower())


def resolve_topic_file(rd: Path, topic_file: str | None) -> Path | None:
    """step0 stores topic_file relative to the repo (ai_scientist/ideas/x.md) or absolute; the research dir sits next
    to the topic file, so its sibling is the fallback."""
    if not topic_file:
        return None
    p = Path(topic_file).expanduser()
    if p.is_absolute() and p.exists():
        return p
    for base in (Path.cwd(), *Path(rd).resolve().parents):
        if (base / p).exists():
            return base / p
    sib = Path(rd).resolve().parent / p.name
    return sib if sib.exists() else None


# ------------------------------------------------------------------------------------------- network record / replay
# Every network answer a Unit acts on is stored under <RD>/_state/net/<channel>/<key>.json, keyed by the request.
# With IDEATE_REPLAY=1 nothing goes to the network: answers come from those files, and a request with no recording
# fails (ReplayMiss) instead of silently going live. This is what makes a search re-runnable offline.
import urllib.parse as _up
import urllib.request as _ur


class ReplayMiss(RuntimeError):
    pass


def replaying() -> bool:
    return os.environ.get("IDEATE_REPLAY", "") not in ("", "0")


def net_key(channel: str, request) -> str:
    return sha256_json({"channel": channel, "request": request})[:24]


def net_path(rd: Path | None, channel: str, request) -> Path | None:
    return (Path(rd) / "_state" / "net" / channel / f"{net_key(channel, request)}.json") if rd else None


_REPLAY_SEEN: dict = {}


def net_load(rd: Path | None, channel: str, request):
    """The recorded answer. The same request asked twice (a 429, then a success on the retry) has two answers; they
    are served in the order they were recorded, the last one repeating."""
    p = net_path(rd, channel, request)
    if p is None or not p.exists():
        raise ReplayMiss(f"no recording for {channel} {json.dumps(request, ensure_ascii=False)[:160]}")
    rec = read_json(p)
    answers = rec.get("responses") or [rec.get("response")]
    i = _REPLAY_SEEN.get(str(p), 0)
    _REPLAY_SEEN[str(p)] = i + 1
    return answers[min(i, len(answers) - 1)]


def recorded(rd: Path | None, channel: str, request, live):
    """Record / replay one request: with IDEATE_REPLAY=1 the recorded answer, else live() recorded under _state/net/."""
    if replaying():
        return net_load(rd, channel, request)
    out = live()
    net_save(rd, channel, request, out)
    return out


async def recorded_async(rd: Path | None, channel: str, request, live):
    """`recorded` for an awaitable: the transport (mcp_bridge.Server.call) and the tests' fake servers share it."""
    if replaying():
        return net_load(rd, channel, request)
    out = await live()
    net_save(rd, channel, request, out)
    return out


def net_save(rd: Path | None, channel: str, request, response) -> None:
    p = net_path(rd, channel, request)
    if p is None:
        return
    rec = read_json(p) if p.exists() else {"channel": channel, "request": request, "responses": [], "at": []}
    if "responses" not in rec:                  # a recording that holds one `response`
        rec = {"channel": channel, "request": request, "responses": [rec.get("response")], "at": [rec.get("at")]}
    rec["responses"].append(response)
    rec["at"].append(now_iso())
    write_json(p, rec)


SCHOLAR_ENV = Path(__file__).resolve().parent.parent / "mcp" / "scholar_mcp" / ".env"


def scholar_key(name: str) -> str | None:
    """An API key from the environment, else from the scholar server's gitignored .env. Never printed or recorded."""
    if os.environ.get(name):
        return os.environ[name]
    if SCHOLAR_ENV.is_file():
        for line in SCHOLAR_ENV.read_text(encoding="utf-8", errors="replace").splitlines():
            k, sep, v = line.strip().partition("=")
            if sep and not k.startswith("#") and k.strip() == name:
                return v.strip().strip("'\"") or None
    return None


def _send_url(url: str) -> str:
    """The URL as sent: OpenAlex requests carry OPENALEX_API_KEY when one is configured (a key has its own daily budget;
    without one, every client on the network shares one). The recorded request never contains it."""
    if "//api.openalex.org/" in url:
        key = scholar_key("OPENALEX_API_KEY")
        if key:
            return url + ("&" if "?" in url else "?") + "api_key=" + _up.quote(key)
    return url


def http_json(url: str, rd: Path | None = None, timeout: int = 30):
    """GET a JSON document, recorded under _state/net/http/ by the URL without credentials."""
    def live():
        try:
            with _ur.urlopen(_ur.Request(_send_url(url), headers={"User-Agent": "ai-scientist-ideate/1.0"}),
                             timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:  # noqa: BLE001 - re-raised without the URL, which may carry a key
            raise RuntimeError(f"GET {url[:120]} failed: {type(e).__name__}: {getattr(e, 'code', '') or ''}".strip()) from None
    return recorded(rd, "http", {"url": url}, live)


PREFLIGHT = "_state/preflight.json"
PREFLIGHT_HOURS = 12


def preflight_says(rd: Path | None, service: str):
    """(ok, detail) from a recent preflight (`mcp_bridge.py preflight`), or None: no preflight, an old one, or a
    replayed run (a replay never consults the live state of a service)."""
    if rd is None or replaying():
        return None
    p = Path(rd) / PREFLIGHT
    if not p.exists():
        return None
    pf = read_json(p)
    try:
        age = (datetime.now().astimezone() - datetime.fromisoformat(pf["at"])).total_seconds() / 3600
    except (KeyError, ValueError):
        return None
    if age > PREFLIGHT_HOURS:
        return None
    s = (pf.get("services") or {}).get(service)
    return (bool(s.get("ok")), s.get("detail", "")) if s else None


def quote(s: str) -> str:
    return _up.quote(s)


# ------------------------------------------------------------------------------------------- author names
def ascii_fold(s: str) -> str:
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")


INITIALS = re.compile(r"^(?:[A-Z]\.?-?){1,4}$")  # "M."  "K.L."  "JQ"  "A.-S."


def split_name(author: str) -> tuple[str, str]:
    """(family, given) for the three shapes the sources use: "Family, Given" · "Given Family" · Scopus "Family I.I."."""
    author = re.sub("[\u2010-\u2015\u2212]", "-", str(author or "")).strip()  # unicode hyphens -> ASCII
    if "," in author:
        fam, _, given = author.partition(",")
        return fam.strip(), given.strip()
    toks = author.split()
    if len(toks) < 2:
        return author, ""
    if INITIALS.match(toks[-1]) and not INITIALS.match(toks[0]):  # Scopus: trailing initials, surname first
        return " ".join(toks[:-1]), toks[-1]
    return toks[-1], " ".join(toks[:-1])


def last_name(author: str) -> str:
    return re.sub(r"[^A-Za-z\-]", "", ascii_fold(split_name(author)[0]))
