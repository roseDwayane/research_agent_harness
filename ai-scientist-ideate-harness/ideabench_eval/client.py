from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .jsonio import append_jsonl


@dataclass(frozen=True)
class ModelConfig:
    url: str
    model: str
    num_ctx: int = 32768
    num_predict: int = 8192
    temperature: float = 0.0
    timeout_s: float = 3600.0
    api_key_env: str = "OLLAMA_API_KEY"


class OllamaJSONClient:
    """Small grammar-constrained Ollama client with per-call usage logging."""

    def __init__(self, config: ModelConfig, ledger: Path):
        self.config = config
        self.ledger = Path(ledger)

    def complete(self, *, system: str, prompt: str, schema: dict, tag: str) -> dict:
        cfg = self.config
        body = {
            "model": cfg.model,
            "stream": False,
            "format": schema,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
            "options": {"num_ctx": cfg.num_ctx, "num_predict": cfg.num_predict, "temperature": cfg.temperature},
        }
        headers = {"Content-Type": "application/json", "User-Agent": "ideabench-offline/1.0"}
        key = os.environ.get(cfg.api_key_env)
        if key:
            headers["Authorization"] = f"Bearer {key}"
        request = urllib.request.Request(
            cfg.url.rstrip("/") + "/api/chat", data=json.dumps(body).encode("utf-8"), headers=headers, method="POST"
        )
        started = time.time()
        status = "error"
        error = None
        usage: dict[str, Any] = {}
        try:
            with urllib.request.urlopen(request, timeout=cfg.timeout_s) as response:
                payload = json.loads(response.read().decode("utf-8"))
            content = (payload.get("message") or {}).get("content")
            if not content:
                raise RuntimeError("Ollama returned no message content")
            result = json.loads(content)
            usage = {
                "input_tokens": int(payload.get("prompt_eval_count") or 0),
                "output_tokens": int(payload.get("eval_count") or 0),
                "total_duration_ns": int(payload.get("total_duration") or 0),
            }
            status = "ok"
            return result
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
            error = f"HTTP {exc.code}: {detail[:500]}"
            raise RuntimeError(error) from exc
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            append_jsonl(self.ledger, {
                "tag": tag, "model": cfg.model, "url": cfg.url, "status": status,
                "wall_seconds": round(time.time() - started, 3), "usage": usage, "error": error,
            })


class ScriptedClient:
    """Deterministic test client. Each call consumes one preloaded response."""

    def __init__(self, responses: list[dict]):
        self.responses = list(responses)
        self.calls: list[dict] = []

    def complete(self, *, system: str, prompt: str, schema: dict, tag: str) -> dict:
        self.calls.append({"system": system, "prompt": prompt, "schema": schema, "tag": tag})
        if not self.responses:
            raise AssertionError(f"unexpected model call {tag}")
        return self.responses.pop(0)

