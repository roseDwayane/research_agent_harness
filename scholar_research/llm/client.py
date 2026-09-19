"""Anthropic Messages API wrapper with structured output, caching and ledger.

* Every call uses **tool use with a forced tool** whose ``input_schema`` is the
  pydantic model's JSON schema → the response is validated with pydantic.
* ``temperature=0`` and the model ID come from config; both are part of the
  cache key, as are prompt name+version and the full message list.
* Cache hits skip the network entirely (replay); misses are recorded in the
  ledger with token usage.

``LLMClient.backend`` is injectable so tests can plug in a fake that returns
canned JSON without touching the API.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable, Protocol, TypeVar

from pydantic import BaseModel, ValidationError

from ..cache import Cache
from ..config import LLMConfig
from ..utils import sha256_obj
from .ledger import Ledger
from .prompts import load_prompt

T = TypeVar("T", bound=BaseModel)


class Backend(Protocol):
    def __call__(self, *, model: str, system: str, messages: list[dict[str, Any]], tool: dict[str, Any], temperature: float, max_tokens: int) -> dict[str, Any]:
        """Return {"input": <tool input dict>, "usage": {...}, "stop_reason": str}."""


class AnthropicBackend:
    def __init__(self, api_key: str | None, max_retries: int = 3):
        import anthropic  # local import so tests without the SDK still import the package

        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set (needed for LLM steps; replay from cache needs no key)")
        self._client = anthropic.Anthropic(api_key=api_key, max_retries=max_retries)

    def __call__(self, *, model, system, messages, tool, temperature, max_tokens):
        resp = self._client.messages.create(
            model=model,
            system=system,
            messages=messages,
            tools=[tool],
            tool_choice={"type": "tool", "name": tool["name"]},
            temperature=temperature,
            max_tokens=max_tokens,
        )
        tool_input = None
        for block in resp.content:
            if getattr(block, "type", "") == "tool_use" and block.name == tool["name"]:
                tool_input = block.input
                break
        if tool_input is None:
            raise RuntimeError(f"model returned no tool_use block (stop_reason={resp.stop_reason})")
        usage = {"input_tokens": resp.usage.input_tokens, "output_tokens": resp.usage.output_tokens}
        return {"input": tool_input, "usage": usage, "stop_reason": resp.stop_reason, "model": resp.model}


class LLMError(RuntimeError):
    pass


class LLMClient:
    def __init__(self, cfg: LLMConfig, cache: Cache, ledger: Ledger, backend: Backend | None = None, api_key: str | None = None):
        self.cfg = cfg
        self.cache = cache
        self.ledger = ledger
        self._backend = backend
        self._api_key = api_key
        self.prompt_versions: dict[str, str] = {}

    @property
    def backend(self) -> Backend:
        if self._backend is None:
            self._backend = AnthropicBackend(self._api_key, self.cfg.max_retries)
        return self._backend

    # ------------------------------------------------------------------ #
    def structured(self, prompt_name: str, schema: type[T], variables: dict[str, Any], *, step: int, tag: str = "") -> T:
        """Render prompt → call model (or cache) → validate → return model."""
        prompt = load_prompt(prompt_name)
        self.prompt_versions[prompt_name] = prompt.version
        system = prompt.system
        user = prompt.render(variables)
        tool = {
            "name": prompt.tool_name,
            "description": prompt.tool_description,
            "input_schema": _strict_schema(schema),
        }
        messages: list[dict[str, Any]] = [{"role": "user", "content": user}]
        descriptor = {
            "kind": "llm",
            "prompt": prompt_name,
            "prompt_version": prompt.version,
            "model": self.cfg.model,
            "temperature": self.cfg.temperature,
            "max_tokens": self.cfg.max_tokens,
            "system": system,
            "messages": messages,
            "schema": tool["input_schema"],
        }
        t0 = time.time()
        attempts: list[str] = []

        def fetch() -> dict[str, Any]:
            msgs = list(messages)
            last_err: Exception | None = None
            for attempt in range(self.cfg.validation_retries + 1):
                raw = self.backend(model=self.cfg.model, system=system, messages=msgs, tool=tool, temperature=self.cfg.temperature, max_tokens=self.cfg.max_tokens)
                try:
                    schema.model_validate(raw["input"])
                    return {"response": raw["input"], "usage": raw.get("usage", {}), "stop_reason": raw.get("stop_reason"), "model": raw.get("model", self.cfg.model), "attempts": attempt + 1}
                except ValidationError as e:  # feed the error back and retry
                    last_err = e
                    attempts.append(str(e)[:500])
                    msgs = msgs + [
                        {"role": "assistant", "content": [{"type": "tool_use", "id": f"retry{attempt}", "name": tool["name"], "input": raw["input"]}]},
                        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": f"retry{attempt}", "content": f"Your output failed schema validation. Fix ONLY the listed problems and call the tool again.\n{e}"}]},
                    ]
            raise LLMError(f"{prompt_name}: output failed validation after retries: {last_err}")

        rec = self.cache.get_or_fetch("llm", descriptor, fetch)
        wall = time.time() - t0
        cache_hit = rec["_cache"]["hit"]
        result = schema.model_validate(rec["response"])
        self.ledger.record(
            {
                "step": step,
                "tag": tag,
                "prompt": prompt_name,
                "prompt_version": prompt.version,
                "model": rec.get("model", self.cfg.model),
                "temperature": self.cfg.temperature,
                "cache_hit": cache_hit,
                "cache_key": rec["_cache"]["key"],
                "usage": {} if cache_hit else rec.get("usage", {}),
                "wall_seconds": round(wall, 3),
                "request_sha256": sha256_obj(descriptor),
                "response_sha256": sha256_obj(rec["response"]),
                "validation_attempts": rec.get("attempts", 1),
            }
        )
        return result


def _strict_schema(model: type[BaseModel]) -> dict[str, Any]:
    """pydantic JSON schema → tool input_schema (inline $defs, no titles)."""
    schema = model.model_json_schema()
    defs = schema.pop("$defs", {})

    def inline(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                ref = node["$ref"].split("/")[-1]
                return inline(defs[ref])
            return {k: inline(v) for k, v in node.items() if k not in ("title",)}
        if isinstance(node, list):
            return [inline(x) for x in node]
        return node

    out = inline(schema)
    out["type"] = "object"
    return out


class FakeBackend:
    """Test double: ``responder(prompt_tool_name, messages) -> dict``."""

    def __init__(self, responder: Callable[[str, list[dict[str, Any]]], dict[str, Any]]):
        self.responder = responder
        self.calls = 0

    def __call__(self, *, model, system, messages, tool, temperature, max_tokens):
        self.calls += 1
        return {"input": self.responder(tool["name"], messages), "usage": {"input_tokens": 10, "output_tokens": 5}, "stop_reason": "tool_use", "model": model}
