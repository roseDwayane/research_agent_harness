"""An OpenAI-compatible worker: the Ollama worker's conversation (ollama_worker.converse - the files in the prompt,
one JSON answer back, one correction turn) over a `/chat/completions` endpoint instead of Ollama's /api/chat.

One worker covers every provider that speaks the OpenAI Chat Completions API:

    [harness]                                       [harness]
    worker = "openai"                               worker = "openai"
    api_base = "https://api.openai.com/v1"          api_base = "https://generativelanguage.googleapis.com/v1beta/openai"
    api_key_env = "OPENAI_API_KEY"                  api_key_env = "GEMINI_API_KEY"
    model = "<a GPT model your key may use>"        model = "<a Gemini model your key may use>"
    max_context = 128000                            max_context = 1000000

The key is read from the environment variable `api_key_env` names - never from the config file - and is sent only
as "Authorization: Bearer ..."; it is never logged. The answer is asked for under `response_format` = the step's JSON
schema (non-strict: the conductor checks the answer anyway); a provider that refuses that form gets one plain
`json_object` request with the schema written into the prompt instead. With `api_price_in` / `api_price_out` (USD per
million tokens) every call's cost is counted, and `api_budget_usd` stops a run before it spends more.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from . import __version__
from . import ollama_worker as ow
from .claude_worker import WorkerResult
from .config import HarnessConfig

_SPENT = {"usd": 0.0}                    # this process's spend on API calls (api_budget_usd is checked against it)
_LOCK = threading.Lock()
SCHEMA_REFUSED = re.compile(r"response_format|json_schema|schema", re.I)


def spent() -> float:
    with _LOCK:
        return _SPENT["usd"]


def _cost(cfg: HarnessConfig, tin: int, tout: int) -> float:
    if cfg.api_price_in is None or cfg.api_price_out is None:
        return 0.0
    return (tin * float(cfg.api_price_in) + tout * float(cfg.api_price_out)) / 1e6


def _post(cfg: HarnessConfig, body: dict, timeout: float) -> tuple[int, dict | None, str]:
    url = cfg.api_base.rstrip("/") + "/chat/completions"
    headers = {"Content-Type": "application/json", "User-Agent": f"ideate-harness/{__version__}",
               "Authorization": f"Bearer {os.environ.get(cfg.api_key_env, '')}"}
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            try:
                return resp.status, json.loads(raw), raw
            except ValueError as e:
                return 502, None, f"the API's answer is not JSON: {e}"
    except urllib.error.HTTPError as e:
        return e.code, None, e.read().decode("utf-8", errors="replace") if e.fp else ""


def _failure(cfg: HarnessConfig, status: int, raw: str) -> tuple[str, str]:
    text = raw.strip()[:400] or f"HTTP {status}"
    if status in (401, 403):
        return "environment", (f"{text} (the API refused the key: export a valid key as {cfg.api_key_env}, "
                               f"and check it may use {cfg.model})")
    if status == 404:
        return "environment", f"{text} (is {cfg.model!r} a model this API serves? is api_base right: {cfg.api_base}?)"
    if status == 429 or status >= 500:
        return "external_service", text
    return "tool_invocation", text


def chat(cfg: HarnessConfig, messages: list[dict], timeout: float, fmt: dict | None = None) -> tuple[WorkerResult, str]:
    """One /chat/completions call -> (result, the assistant's raw content). The transport of ollama_worker.converse."""
    if not os.environ.get(cfg.api_key_env):
        return WorkerResult(False, error=f"no API key: export it as {cfg.api_key_env} (worker = \"openai\", "
                                         f"api_base {cfg.api_base})", error_category="environment"), ""
    if cfg.api_budget_usd is not None and spent() >= float(cfg.api_budget_usd):
        return WorkerResult(False, error=f"the run has spent ${spent():.2f} of api_budget_usd ${cfg.api_budget_usd}: "
                                         "no further call is sent", error_category="budget"), ""
    fmt = fmt or ow.RESPONSE_SCHEMA
    body: dict = {"model": cfg.model, "messages": messages,
                  "response_format": {"type": "json_schema",
                                      "json_schema": {"name": "answer", "schema": fmt, "strict": False}}}
    if cfg.num_predict:
        body[cfg.api_max_tokens_field] = int(cfg.num_predict)
    if cfg.temperature is not None:
        body["temperature"] = float(cfg.temperature)
    if cfg.api_reasoning_effort:
        body["reasoning_effort"] = cfg.api_reasoning_effort
    t0 = time.time()
    try:
        status, data, raw = _post(cfg, body, timeout)
        if status == 400 and SCHEMA_REFUSED.search(raw or ""):
            # a provider that refuses this schema form: the plain JSON mode, with the schema written into the prompt
            body["response_format"] = {"type": "json_object"}
            body["messages"] = messages[:-1] + [{**messages[-1], "content": messages[-1]["content"]
                                                 + "\n\nThe JSON object must follow this JSON schema:\n"
                                                 + json.dumps(fmt, ensure_ascii=False)}]
            status, data, raw = _post(cfg, body, timeout)
    except (TimeoutError, urllib.error.URLError, ConnectionError, OSError) as e:
        why = getattr(e, "reason", e)
        cat = "timeout" if isinstance(e, TimeoutError) or "timed out" in str(why) else "external_service"
        return WorkerResult(False, error=f"cannot reach {cfg.api_base}: {why}", error_category=cat,
                            duration_ms=int((time.time() - t0) * 1000)), ""
    ms = int((time.time() - t0) * 1000)
    if status != 200 or data is None:
        cat, why = _failure(cfg, status, raw)
        return WorkerResult(False, error=why, error_category=cat, duration_ms=ms), ""
    usage = data.get("usage") or {}
    tin, visible = int(usage.get("prompt_tokens") or 0), int(usage.get("completion_tokens") or 0)
    # a thinking model's reasoning: Gemini leaves it out of completion_tokens but counts it in total_tokens, in the
    # output limit and in the bill (OpenAI counts it in completion_tokens already) - so output = total - prompt
    tout = max(visible, int(usage.get("total_tokens") or 0) - tin)
    cost = _cost(cfg, tin, tout)
    with _LOCK:
        _SPENT["usd"] += cost
    choice = (data.get("choices") or [{}])[0]
    content = str((choice.get("message") or {}).get("content") or "")
    res = WorkerResult(True, tokens_in=tin, tokens_out=tout, cost_usd=cost, duration_ms=ms, turns=1)
    if choice.get("finish_reason") == "length":
        res.ok, res.error_category = False, "budget"
        hidden = tout - visible
        res.error = f"the answer hit the output limit ({cfg.num_predict} tokens) and was cut: raise num_predict" + \
            (f" - {hidden} of them were the model's hidden reasoning; api_reasoning_effort = \"low\" (or \"none\") "
             "leaves more for the answer" if hidden > visible else "")
    elif not content.strip():
        refusal = (choice.get("message") or {}).get("refusal")
        res.ok, res.error_category = False, "model_output"
        res.error = f"the API returned no content (finish_reason {choice.get('finish_reason')!r}" + \
            (f", refusal: {str(refusal)[:200]}" if refusal else "") + ")"
    return res, content


def run_worker(cfg: HarnessConfig, *, task: str, system: str, cwd: Path, scope: ow.FileScope | None = None,
               resume: str | None = None, timeout: float | None = None, log_dir: Path | None = None,
               label: str = "worker", say=None, **_claude_only) -> WorkerResult:
    """One API worker turn (and one correction turn for an answer the conductor cannot use), in the same conversation
    as a resumed session. The claude-only arguments (allowed tools, add_dirs, budget_usd, bin_dir) do not apply."""
    return ow.converse(cfg, task=task, system=system, cwd=cwd, scope=scope, resume=resume, timeout=timeout,
                       log_dir=log_dir, label=label, say=say, chat_fn=chat, context_tokens=cfg.context_tokens(),
                       warm=False, name="API", log_tag="api")
