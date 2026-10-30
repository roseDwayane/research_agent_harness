"""Redaction of secrets and bulky payloads before anything reaches a log, an event or an error record.

Observability metadata (ids, codes, counts, hashes, durations) passes through; content is truncated; anything that
looks like a credential is replaced by "[REDACTED]".
"""
from __future__ import annotations

import re
from typing import Any

REDACTED = "[REDACTED]"
SENSITIVE_KEY = re.compile(r"(api[_-]?key|apikey|token|secret|password|passwd|authorization|auth|cookie|credential|"
                           r"session[_-]?id|private[_-]?key|access[_-]?key)", re.I)
# values that look like credentials wherever they appear
_VALUE_PATTERNS = [
    re.compile(r"\bsk-[A-Za-z0-9_\-]{16,}"),                       # Anthropic / OpenAI style keys
    re.compile(r"\bBearer\s+[A-Za-z0-9._\-]{8,}", re.I),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"),                    # GitHub tokens
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),                             # AWS access key ids
    re.compile(r"(?i)([?&](?:api[_-]?key|apikey|key|token|access_token|mailto)=)[^&\s\"']+"),
]
MAX_STR = 2000
MAX_ITEMS = 100
MAX_DEPTH = 6


def redact_text(s: str, max_len: int = MAX_STR) -> str:
    for pat in _VALUE_PATTERNS:
        if pat.groups:
            s = pat.sub(lambda m: m.group(1) + REDACTED, s)
        else:
            s = pat.sub(REDACTED, s)
    if len(s) > max_len:
        s = s[:max_len] + f"... [truncated {len(s) - max_len} chars]"
    return s


def redact(obj: Any, depth: int = 0) -> Any:
    """Return a redacted, size-bounded copy of ``obj`` (dict/list/str/scalars)."""
    if depth > MAX_DEPTH:
        return "[depth limit]"
    if isinstance(obj, dict):
        out = {}
        for i, (k, v) in enumerate(obj.items()):
            if i >= MAX_ITEMS:
                out["..."] = f"[{len(obj) - MAX_ITEMS} more keys]"
                break
            ks = str(k)
            out[ks] = REDACTED if SENSITIVE_KEY.search(ks) and v not in (None, "", False) else redact(v, depth + 1)
        return out
    if isinstance(obj, (list, tuple)):
        items = [redact(v, depth + 1) for v in list(obj)[:MAX_ITEMS]]
        if len(obj) > MAX_ITEMS:
            items.append(f"[{len(obj) - MAX_ITEMS} more items]")
        return items
    if isinstance(obj, str):
        return redact_text(obj)
    if obj is None or isinstance(obj, (bool, int, float)):
        return obj
    return redact_text(repr(obj))
