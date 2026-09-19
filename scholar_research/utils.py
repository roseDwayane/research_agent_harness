"""Small deterministic helpers shared by every layer.

Everything here is pure: same input → same output. Timestamps are *not*
generated here (see ``session.Clock``) so that replay can pin them.
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from pathlib import Path
from typing import Any


# --------------------------------------------------------------------------- #
# Hashing / canonical JSON
# --------------------------------------------------------------------------- #
def canonical_json(obj: Any) -> str:
    """Deterministic JSON: sorted keys, no whitespace variance, UTF-8 kept."""
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_obj(obj: Any) -> str:
    return sha256_text(canonical_json(obj))


def dump_json(path: Path, obj: Any) -> None:
    """Write pretty JSON with stable key order (2-space indent, UTF-8)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(obj, indent=2, ensure_ascii=False, sort_keys=False, default=str) + "\n"
    path.write_text(text, encoding="utf-8")


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not text.endswith("\n"):
        text += "\n"
    path.write_text(text, encoding="utf-8")


# --------------------------------------------------------------------------- #
# Strings
# --------------------------------------------------------------------------- #
def slugify(text: str, max_len: int = 40) -> str:
    """lowercase, hyphens, ascii-only, max_len chars, never ends with '-'."""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    text = re.sub(r"-{2,}", "-", text)
    if len(text) > max_len:
        text = text[:max_len].rstrip("-")
    return text or "topic"


def normalize_doi(doi: str | None) -> str | None:
    if not doi:
        return None
    d = doi.strip()
    d = re.sub(r"^https?://(dx\.)?doi\.org/", "", d, flags=re.I)
    d = re.sub(r"^doi:\s*", "", d, flags=re.I)
    d = d.strip().lower()
    return d or None


_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)
_WS = re.compile(r"\s+")


def normalize_title(title: str | None) -> str:
    if not title:
        return ""
    t = unicodedata.normalize("NFKD", title).lower()
    t = _PUNCT.sub(" ", t)
    return _WS.sub(" ", t).strip()


def title_tokens(title: str | None) -> set[str]:
    return {w for w in normalize_title(title).split() if len(w) > 2}


def word_overlap(a: str | None, b: str | None) -> float:
    """Fraction of shared words relative to the smaller title (0..1)."""
    ta, tb = title_tokens(a), title_tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / min(len(ta), len(tb))


def last_name(author: str) -> str:
    """Best-effort family-name extraction; see research-export SKILL rules."""
    a = author.strip()
    if not a:
        return ""
    if "," in a:  # "Last, First"
        return a.split(",", 1)[0].strip()
    parts = a.split()
    # skip trailing suffixes
    while len(parts) > 1 and parts[-1].rstrip(".").lower() in {"jr", "sr", "ii", "iii", "iv", "phd", "md"}:
        parts.pop()
    return parts[-1]


def ascii_fold(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")


def latex_escape(text: str) -> str:
    """Escape LaTeX special characters in running text (not math)."""
    if not text:
        return ""
    return (
        text.replace("\\", r"\textbackslash{}")
        .replace("&", r"\&")
        .replace("%", r"\%")
        .replace("$", r"\$")
        .replace("#", r"\#")
        .replace("_", r"\_")
        .replace("{", r"\{")
        .replace("}", r"\}")
    )


def bibtex_escape(text: str) -> str:
    """Escape for BibTeX field values (keeps braces used for protection)."""
    if not text:
        return ""
    return text.replace("&", r"\&").replace("%", r"\%").replace("_", r"\_").replace("$", r"\$").replace("#", r"\#")


def frontmatter(fields: dict[str, Any]) -> str:
    lines = ["---"]
    for k, v in fields.items():
        if isinstance(v, bool):
            lines.append(f"{k}: {'true' if v else 'false'}")
        elif isinstance(v, (int, float)):
            lines.append(f"{k}: {v}")
        elif isinstance(v, list):
            inner = ", ".join(json.dumps(x, ensure_ascii=False) for x in v)
            lines.append(f"{k}: [{inner}]")
        elif v is None:
            lines.append(f"{k}: null")
        else:
            lines.append(f"{k}: {json.dumps(str(v), ensure_ascii=False)}")
    lines.append("---")
    return "\n".join(lines)


def parse_frontmatter(text: str) -> dict[str, str]:
    """Tiny YAML-ish frontmatter reader (flat key: value only)."""
    out: dict[str, str] = {}
    if not text.startswith("---"):
        return out
    body = text.split("---", 2)
    if len(body) < 3:
        return out
    for line in body[1].splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            v = v.strip()
            if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
                v = v[1:-1]
            out[k.strip()] = v
    return out


def md_cell(text: Any) -> str:
    """Make a value safe inside a markdown table cell."""
    s = "" if text is None else str(text)
    return s.replace("|", "\\|").replace("\n", " ").strip()


def truncate(text: str | None, n: int = 60) -> str:
    if not text:
        return ""
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


def round2(x: float) -> float:
    """Round half-up to 2 decimals via Decimal so 3.345 -> 3.35 (never binary drift)."""
    from decimal import ROUND_HALF_UP, Decimal

    return float(Decimal(str(x)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
