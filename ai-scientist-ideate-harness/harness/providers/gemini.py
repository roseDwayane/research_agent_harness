"""The Gemini provider (worker = "gemini"): the Gemini API's generateContent as a chat model - the same flow as Claude,
GPT and Ollama (chat.py): the files and the lookups in the prompt, one JSON answer, the conductor writes the files the
scope allows. It runs no commands: B6 (`consume`, the journal lookup) needs an agent (agent.py), and none is built in.

One chat() is one streamed generateContent (generate_content_stream) through the official SDK (google-genai),
imported on the first call - the rest of the harness runs without it:

  system_instruction    the Unit's rules
  contents              the conversation (a resumed session's history) as user / model turns
  response_json_schema  the answer's JSON schema as it is, with response_mime_type application/json: Gemini takes an
                        open map (additionalProperties as a schema) and ignores the keywords it does not support. A
                        schema the API refuses (400: too large or deep to compile) is sent once more without it - the
                        answer is then JSON, decoded under no schema
  thinking_config       {"thinking_level": LOW | MEDIUM | HIGH} when the provider option effort is set (else the
                        model's own default)
The SDK goes on with an answer longer than one stream by itself (automatic continuation). Gemini's prompt caching is
implicit; the cost counts its cache reads. A model turn goes back as its text: Gemini validates thought signatures
only for function calls.

Credentials are the SDK's: GEMINI_API_KEY or GOOGLE_API_KEY; Vertex AI through GOOGLE_GENAI_USE_VERTEXAI,
GOOGLE_CLOUD_PROJECT and GOOGLE_CLOUD_LOCATION.

[harness.provider_options.gemini], all optional:
  effort          minimal | low | medium | high (the levels a model takes: the model's page; Gemini 4 refuses minimal)
  max_tokens      the answer, thinking included (default 65536)
  context_window  tokens, input and output (default 1048576)
  max_retries     the SDK's (default 0: the executor's RP-TRANSPORT alone)
  base_url        another endpoint of the Gemini API (default: the SDK's)
  price_per_mtok  [input, output] in USD per million tokens, for a model PRICES does not list (else its cost is 0)
Not sent: temperature and the other sampling settings (Gemini 4 ignores them), thinking_budget (Gemini 4 refuses it).
"""
from __future__ import annotations

import json
import threading
import time

from .base import WorkerResult
from .chat import (RESPONSE_SCHEMA, ChatProvider, Rate, StreamDeadline, check_options, elapsed_ms, json_text,
                   rate_of, rate_override)

DEFAULT_MODEL = "gemini-4-argon"
EFFORTS = ("minimal", "low", "medium", "high")
DEFAULT_MAX_TOKENS = 65536
DEFAULT_WINDOW = 1_048_576

# list prices, USD per million tokens: input, output (thinking included), a cache read; dated entries are the
# announced price changes, and Gemini 3.1 Pro costs more for a prompt over 200k tokens
PRICES = {
    "gemini-4-argon": [("", 0, Rate(2.0, 10.0, 0.10)), ("2026-12-01", 0, Rate(4.0, 20.0, 0.20))],
    "gemini-4-carbon": [("", 0, Rate(2.0, 10.0, 0.10)), ("2026-12-01", 0, Rate(4.0, 20.0, 0.20))],
    "gemini-3.8-flash": [("", 0, Rate(0.75, 3.75, 0.075)), ("2027-01-01", 0, Rate(1.50, 7.50, 0.15))],
    "gemini-3.6-flash": [("", 0, Rate(0.75, 3.75, 0.075)), ("2027-01-01", 0, Rate(1.50, 7.50, 0.15))],
    "gemini-3.1-pro-preview": [("", 0, Rate(2.0, 12.0, 0.20)), ("", 200_000, Rate(4.0, 18.0, 0.40))],
    "gemini-3.5-flash-lite": Rate(0.30, 2.50, 0.03),
}


def _tokens(u) -> tuple[int, int, int]:
    """(prompt, of it read from the cache, output with thinking) tokens of a response's usage_metadata."""
    g = lambda k: int(getattr(u, k, 0) or 0)                      # noqa: E731
    return g("prompt_token_count"), g("cached_content_token_count"), g("candidates_token_count") + \
        g("thoughts_token_count")


def price(model: str, usage, opts: dict | None = None, day: str | None = None) -> float:
    """What one answer cost in USD, at the list price in force (or the provider option price_per_mtok)."""
    prompt, read, out = _tokens(usage)
    rate = rate_override(opts) or rate_of(PRICES, model, prompt, day)
    return rate.cost(max(0, prompt - read), read, 0, out) if rate else 0.0


def _value(x) -> str | None:
    """An SDK enum (FinishReason, BlockedReason) as its name."""
    return None if x is None else str(getattr(x, "value", x))


def failure(errors, e: Exception) -> tuple[str, str]:
    """(category, message) of a failed request - the ideate_v2 categories the other providers' failures get."""
    if isinstance(e, getattr(errors, "ContinuationInterruptedError", ())):
        return "external_service", f"the Gemini API stream was cut while it went on with the answer: {e}"
    if isinstance(e, errors.APIError):
        code, status = int(getattr(e, "code", 0) or 0), getattr(e, "status", None) or ""
        why = f"HTTP {code} {status} from the Gemini API: {getattr(e, 'message', '') or e}"
        if code == 429:
            return "external_service", why
        if code in (401, 403, 404) or (code == 400 and "API_KEY_INVALID" in json.dumps(getattr(e, "details", None),
                                                                                     default=str)):
            return "environment", why
        if code == 504:
            return "timeout", why
        if code >= 500 or code == 409:
            return "external_service", why
        return "tool_invocation", why
    name, module = type(e).__name__, type(e).__module__
    if "Timeout" in name:
        return "timeout", f"the Gemini API did not answer in time: {e}"
    if module.startswith(("httpx", "httpcore", "aiohttp")) or isinstance(e, OSError):
        return "external_service", f"cannot reach the Gemini API: {e}"
    return "tool_invocation", f"the Gemini API call failed: {e}"


def outcome(finish: str | None, blocked: str | None, max_tokens: int) -> tuple[str, str] | None:
    """(category, message) of a stream that is no usable answer, or None."""
    if blocked:
        return "model_output", f"the Gemini API blocked the prompt ({blocked})"
    if finish == "STOP":
        return None
    if finish == "MAX_TOKENS":
        return "budget", (f"the answer reached max_output_tokens ({max_tokens}, thinking included) before it was "
                          "finished: raise [harness.provider_options.gemini] max_tokens or give the Unit less to write")
    if finish in (None, "CONTINUATION", "FINISH_REASON_UNSPECIFIED"):
        return "external_service", "the Gemini API stream ended before the answer was finished"
    return "model_output", f"the Gemini API stopped the answer ({finish})"


class GeminiProvider(ChatProvider):
    name = "gemini"

    def __init__(self, cfg, state_dir=None):
        super().__init__(cfg, state_dir)
        self._client = None                          # made on the first call (one per run, shared by the fan-out)
        self._lock = threading.Lock()

    # ------------------------------------------------------------------------------------------------ settings
    @classmethod
    def default_model(cls, cfg) -> str:
        return DEFAULT_MODEL

    @classmethod
    def check_config(cls, cfg) -> None:
        check_options(cls.name, cls.options_of(cfg), EFFORTS)

    @classmethod
    def window(cls, cfg) -> int:
        return int(cls.options_of(cfg).get("context_window") or DEFAULT_WINDOW)

    @property
    def label(self) -> str:
        return f"gemini:{self.model}"

    # ------------------------------------------------------------------------------------------------ the API
    def _client_of(self, genai):
        with self._lock:
            if self._client is None:
                opts, http = self.options(), {}
                if opts.get("base_url"):
                    http["base_url"] = str(opts["base_url"])
                if int(opts.get("max_retries", 0)) > 0:
                    http["retry_options"] = {"attempts": int(opts["max_retries"]) + 1}
                self._client = genai.Client(http_options=http) if http else genai.Client()
            return self._client

    @staticmethod
    def _send(client, model: str, contents: list, config, limit: float, t0: float):
        """One streamed answer -> (its text, the finish reason, the usage, the prompt's block reason, the model that
        answered); past the call's time limit the stream is left (StreamDeadline)."""
        text, finish, usage, blocked, version = [], None, None, None, None
        for chunk in client.models.generate_content_stream(model=model, contents=contents, config=config):
            if time.time() - t0 > limit:
                raise StreamDeadline()
            usage = getattr(chunk, "usage_metadata", None) or usage
            version = getattr(chunk, "model_version", None) or version
            feedback = getattr(chunk, "prompt_feedback", None)
            if feedback is not None and getattr(feedback, "block_reason", None):
                blocked = _value(feedback.block_reason)
            for cand in (getattr(chunk, "candidates", None) or [])[:1]:
                if getattr(cand, "finish_reason", None) is not None:
                    finish = _value(cand.finish_reason)
                parts = getattr(getattr(cand, "content", None), "parts", None) or []
                text += [p.text for p in parts if getattr(p, "text", None) and not getattr(p, "thought", False)]
        return "".join(text), finish, usage, blocked, version

    def chat(self, messages: list[dict], timeout: float, fmt: dict | None = None) -> tuple[WorkerResult, str]:
        try:
            from google import genai
            from google.genai import errors, types
        except ImportError:
            return WorkerResult(False, error='worker = "gemini" needs the Google Gen AI SDK: pip install '
                                '"google-genai>=3.2,<4"', error_category="environment"), ""
        opts, model, t0 = self.options(), self.model, time.time()
        try:
            client = self._client_of(genai)
        except ValueError as e:                  # no key: the SDK makes no client
            return WorkerResult(False, error=f"no Gemini client ({e}): set GEMINI_API_KEY",
                                error_category="environment"), ""
        system = "\n\n".join(m["content"] for m in messages if m["role"] == "system" and m["content"])
        contents = [{"role": "model" if m["role"] == "assistant" else "user", "parts": [{"text": m["content"] or "(empty)"}]}
                    for m in messages if m["role"] != "system"]
        effort = opts.get("effort")
        max_tokens = int(opts.get("max_tokens") or DEFAULT_MAX_TOKENS)
        got = None
        for extras in (True, False):             # the full request, then (after a 400) once without its schema
            # the SDK's types, not dicts: it writes their nested fields in the API's own (camelCase) names
            config = types.GenerateContentConfig(
                max_output_tokens=max_tokens, response_mime_type="application/json",
                http_options=types.HttpOptions(timeout=int(float(timeout) * 1000)),            # milliseconds
                system_instruction=system or None,
                response_json_schema=(fmt or RESPONSE_SCHEMA) if extras else None,
                thinking_config=types.ThinkingConfig(thinking_level=str(effort).upper()) if effort else None)
            try:
                got = self._send(client, model, contents, config, float(timeout), t0)
                break
            except StreamDeadline:
                return WorkerResult(False, error=f"no complete answer from the Gemini API within {timeout:.0f}s",
                                    error_category="timeout", duration_ms=elapsed_ms(t0)), ""
            except Exception as e:               # noqa: BLE001 - a provider returns its failures, it never raises
                if extras and isinstance(e, errors.APIError) and int(getattr(e, "code", 0) or 0) == 400 and \
                        "API_KEY_INVALID" not in json.dumps(getattr(e, "details", None), default=str):
                    continue                     # a schema the API does not compile
                cat, why = failure(errors, e)
                return WorkerResult(False, error=why, error_category=cat, duration_ms=elapsed_ms(t0)), ""
        text, finish, usage, blocked, version = got
        prompt, _read, out = _tokens(usage)
        res = WorkerResult(True, tokens_in=prompt, tokens_out=out, duration_ms=elapsed_ms(t0),
                           cost_usd=price(str(version or model), usage, opts) if usage is not None else 0.0)
        bad = outcome(finish, blocked, max_tokens)
        if bad:
            res.ok, (res.error_category, res.error) = False, bad
        return res, (text if not res.ok else json_text(text))
