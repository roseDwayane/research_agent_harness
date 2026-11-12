"""The GPT provider (worker = "gpt"): the OpenAI Responses API as a chat model - the same flow as Claude and Ollama
(chat.py): the files and the lookups in the prompt, one JSON answer, the conductor writes the files the scope allows.
It runs no commands: B6 (`consume`, the journal lookup) needs an agent (agent.py), and none is built in.

One chat() is one streamed request (an answer of whole files is long) through the official SDK (openai), imported on
the first call - the rest of the harness runs without it:

  instructions    the Unit's rules
  input           the conversation (a resumed session's history) as user / assistant messages
  text.format     the answer's JSON schema as a strict structured output: every object closed (additionalProperties
                  false) and every field required, as OpenAI's strict mode needs. A schema it cannot take - an open
                  map, an optional field, a keyword strict mode refuses - gets JSON mode instead, and the answer is
                  read out of the text
  reasoning       {"effort": ...} when the provider option effort is set (else the model's own default)
  store           false: the conductor keeps the conversation, OpenAI keeps nothing
  a request the API refuses (400) with its text.format is sent once more without it
Prompt caching is OpenAI's own (automatic); the cost counts its cache reads and writes.

Credentials are the SDK's: OPENAI_API_KEY. The SDK's retries (429, 5xx, a dropped connection) are part of one call;
the executor's RP-TRANSPORT comes after them.

[harness.provider_options.gpt], all optional:
  effort          none | low | medium | high | xhigh | max (none and the levels a model takes: the model's page)
  max_tokens      the answer, reasoning included (default 64000)
  context_window  tokens (default 1050000)
  store           true: let OpenAI keep the responses (default false)
  max_retries     the SDK's (default 2)
  base_url        another endpoint of the Responses API (default: the SDK's, or OPENAI_BASE_URL)
  price_per_mtok  [input, output] in USD per million tokens, for a model PRICES does not list (else its cost is 0)
Not sent: temperature (the reasoning models refuse it).
"""
from __future__ import annotations

import threading
import time

from .base import WorkerResult
from .chat import (RESPONSE_SCHEMA, ChatProvider, Rate, StreamDeadline, check_options, elapsed_ms, has_open_map,
                   json_text, rate_of, rate_override)

DEFAULT_MODEL = "gpt-6-astra"
EFFORTS = ("none", "low", "medium", "high", "xhigh", "max")
DEFAULT_MAX_TOKENS = 64000
DEFAULT_WINDOW = 1_050_000
LONG = 272_000                       # a prompt of more input tokens than this is priced as long context

# list prices, USD per million tokens: input, output, a cache read, a 30-minute cache write
PRICES = {
    "gpt-6-astra": [("", 0, Rate(10.0, 50.0, 1.00, 12.50)), ("", LONG, Rate(20.0, 75.0, 2.00, 25.00))],
    "gpt-6.1-sol": [("", 0, Rate(2.0, 10.0, 0.10, 2.50)), ("", LONG, Rate(4.0, 15.0, 0.20, 5.00))],
    "gpt-6.1-terra": [("", 0, Rate(1.0, 5.0, 0.05, 1.25)), ("", LONG, Rate(2.0, 7.5, 0.10, 2.50))],
    "gpt-6-luna": [("", 0, Rate(0.10, 0.50, 0.01, 0.125)), ("", LONG, Rate(0.20, 0.75, 0.02, 0.25))],
}
REFUSED_KEYWORDS = {"allOf", "not", "dependentRequired", "dependentSchemas", "if", "then", "else", "patternProperties"}
TRANSIENT = ("server_error", "rate_limit_exceeded", "vector_store_timeout")          # a failed response's codes
DECLINED = ("bio_policy", "misalignment_policy_violation", "invalid_prompt")


def _strict(s):
    """A schema without open maps as OpenAI's strict structured output - a copy with additionalProperties false on
    every object - or None where strict mode cannot take it: an optional field (strict mode needs every field
    required), a keyword it refuses."""
    if isinstance(s, list):
        out = [_strict(x) for x in s]
        return None if any(x is None for x in out) else out
    if not isinstance(s, dict):
        return s
    if REFUSED_KEYWORDS & s.keys():
        return None
    out: dict = {}
    for k, v in s.items():
        if k in ("properties", "$defs"):
            sub = {name: _strict(x) for name, x in (v or {}).items()}
            if any(x is None for x in sub.values()):
                return None
            out[k] = sub
        elif k in ("items", "anyOf", "prefixItems"):
            sub = _strict(v)
            if sub is None:
                return None
            out[k] = sub
        else:
            out[k] = v
    if "properties" in out:
        if set(out.get("required") or []) != set(out["properties"]):
            return None
        out["additionalProperties"] = False
    return out


def answer_format(fmt: dict) -> tuple[dict, bool]:
    """text.format for an answer schema -> (the format, whether the answer is decoded under the schema itself): the
    strict schema, or JSON mode for one strict mode cannot take (an open map would only ever be {})."""
    s = None if has_open_map(fmt) else _strict(fmt)
    if s is None:
        return {"type": "json_object"}, False
    return {"type": "json_schema", "name": "answer", "schema": s, "strict": True}, True


def price(model: str, usage, opts: dict | None = None) -> float:
    """What one response cost in USD, at list prices (or the provider option price_per_mtok)."""
    total, read, wrote, out = _tokens(usage)
    rate = rate_override(opts) or rate_of(PRICES, model, total)
    return rate.cost(max(0, total - read - wrote), read, wrote, out) if rate else 0.0


def _tokens(u) -> tuple[int, int, int, int]:
    """(input, of it read from the cache, of it written to the cache, output) tokens of a response's usage."""
    details = getattr(u, "input_tokens_details", None)
    return (int(getattr(u, "input_tokens", 0) or 0), int(getattr(details, "cached_tokens", 0) or 0),
            int(getattr(details, "cache_write_tokens", 0) or 0), int(getattr(u, "output_tokens", 0) or 0))


def failure(openai, e: Exception) -> tuple[str, str]:
    """(category, message) of a failed request - the ideate_v2 categories the other providers' failures get."""
    if isinstance(e, openai.APITimeoutError):                         # before APIConnectionError: it is one
        return "timeout", f"the OpenAI API did not answer in time: {e}"
    if isinstance(e, openai.APIConnectionError):
        return "external_service", f"cannot reach the OpenAI API: {e}"
    if not isinstance(e, openai.APIStatusError):
        return "tool_invocation", f"the OpenAI API call failed: {e}"
    code = getattr(e, "code", None)
    why = f"HTTP {e.status_code} from the OpenAI API" + (f" ({code})" if code else "") + f": {e.message}"
    if code in ("insufficient_quota", "context_length_exceeded"):     # waiting changes neither
        return "budget", why
    if isinstance(e, openai.RateLimitError):
        return "external_service", why
    if isinstance(e, (openai.AuthenticationError, openai.PermissionDeniedError, openai.NotFoundError)) \
            or e.status_code == 402:
        return "environment", why
    if e.status_code == 413:
        return "budget", why
    if isinstance(e, (openai.InternalServerError, openai.ConflictError)):
        return "external_service", why
    if e.status_code == 408:
        return "timeout", why
    return "tool_invocation", why


def outcome(resp, max_tokens: int) -> tuple[str, str] | None:
    """(category, message) of a response that is no usable answer, or None."""
    status = getattr(resp, "status", None)
    refusal = next((c.refusal for item in getattr(resp, "output", None) or [] if getattr(item, "type", "") == "message"
                    for c in getattr(item, "content", None) or [] if getattr(c, "type", "") == "refusal"), None)
    if refusal:
        return "model_output", f"the OpenAI API declined the request (refusal: {refusal[:200]})"
    if status == "completed":
        return None
    if status == "incomplete":
        reason = getattr(getattr(resp, "incomplete_details", None), "reason", None)
        if reason == "max_output_tokens":
            return "budget", (f"the answer reached max_output_tokens ({max_tokens}, reasoning included) before it was "
                              "finished: raise [harness.provider_options.gpt] max_tokens or give the Unit less to write")
        return "model_output", f"the OpenAI API stopped the answer ({reason or 'incomplete'})"
    err = getattr(resp, "error", None)
    code, msg = getattr(err, "code", None), getattr(err, "message", "") or ""
    why = f"the OpenAI API failed the response ({code or status}): {msg}"
    if code in TRANSIENT:
        return "external_service", why
    if code in DECLINED:
        return "model_output", why
    if code == "data_residency_mismatch":
        return "environment", why
    return "tool_invocation", why


class GPTProvider(ChatProvider):
    name = "gpt"

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
        o = cls.options_of(cfg)
        check_options(cls.name, o, EFFORTS)
        if "store" in o and not isinstance(o["store"], bool):
            raise ValueError(f"[harness.provider_options.{cls.name}] store must be true or false, not {o['store']!r}")

    @classmethod
    def window(cls, cfg) -> int:
        return int(cls.options_of(cfg).get("context_window") or DEFAULT_WINDOW)

    @property
    def label(self) -> str:
        return f"gpt:{self.model}"

    # ------------------------------------------------------------------------------------------------ the API
    def _client_of(self, openai):
        with self._lock:
            if self._client is None:
                opts = self.options()
                kw: dict = {"max_retries": int(opts.get("max_retries", 2))}
                if opts.get("base_url"):
                    kw["base_url"] = str(opts["base_url"])
                self._client = openai.OpenAI(**kw)
            return self._client

    def _send(self, client, openai, params: dict, limit: float, t0: float):
        """One streamed response -> the final response (completed, incomplete or failed); past the call's time limit
        the stream is closed (StreamDeadline)."""
        final, error = None, None
        with client.responses.create(**params, stream=True, timeout=openai.Timeout(limit, connect=30.0)) as stream:
            for event in stream:
                if time.time() - t0 > limit:
                    raise StreamDeadline()
                kind = getattr(event, "type", "")
                if kind in ("response.completed", "response.incomplete", "response.failed"):
                    final = event.response
                elif kind == "error":
                    error = event
        return final, error

    def chat(self, messages: list[dict], timeout: float, fmt: dict | None = None) -> tuple[WorkerResult, str]:
        try:
            import openai
        except ImportError:
            return WorkerResult(False, error='worker = "gpt" needs the OpenAI SDK: pip install "openai>=3.49,<4"',
                                error_category="environment"), ""
        opts, model, t0 = self.options(), self.model, time.time()
        try:
            client = self._client_of(openai)
        except openai.OpenAIError as e:          # no key: the SDK makes no client
            return WorkerResult(False, error=f"no OpenAI client ({e}): set OPENAI_API_KEY",
                                error_category="environment"), ""
        system = "\n\n".join(m["content"] for m in messages if m["role"] == "system" and m["content"])
        convo = [{"role": m["role"], "content": m["content"] or "(empty)"} for m in messages if m["role"] != "system"]
        text_format, strict = answer_format(fmt or RESPONSE_SCHEMA)
        effort = opts.get("effort")
        max_tokens = int(opts.get("max_tokens") or DEFAULT_MAX_TOKENS)
        final = error = None
        for extras in (True, False):             # the full request, then (after a 400) once without its text.format
            params: dict = {"model": model, "input": convo, "max_output_tokens": max_tokens,
                            "store": bool(opts.get("store", False))}
            if system:
                params["instructions"] = system
            if effort:
                params["reasoning"] = {"effort": effort}
            if extras:
                params["text"] = {"format": text_format}
            try:
                final, error = self._send(client, openai, params, float(timeout), t0)
                strict = strict and extras
                break
            except StreamDeadline:
                return WorkerResult(False, error=f"no complete answer from the OpenAI API within {timeout:.0f}s",
                                    error_category="timeout", duration_ms=elapsed_ms(t0)), ""
            except openai.OpenAIError as e:
                if extras and isinstance(e, openai.BadRequestError) and getattr(e, "code", None) not in (
                        "context_length_exceeded",):
                    continue                     # a schema strict mode cannot compile
                cat, why = failure(openai, e)
                return WorkerResult(False, error=why, error_category=cat, duration_ms=elapsed_ms(t0)), ""
        if final is None:                        # the stream ended without a response: an error event, or cut
            code = getattr(error, "code", None)
            why = (f"the OpenAI API stream failed ({code}): {getattr(error, 'message', '')}" if error is not None
                   else "the OpenAI API stream ended before the response was complete")
            cat = "budget" if code in ("insufficient_quota", "context_length_exceeded") else "external_service"
            return WorkerResult(False, error=why, error_category=cat, duration_ms=elapsed_ms(t0)), ""
        total, _read, _wrote, out = _tokens(final.usage)
        res = WorkerResult(True, tokens_in=total, tokens_out=out, duration_ms=elapsed_ms(t0),
                           cost_usd=price(str(getattr(final, "model", None) or model), final.usage, opts))
        text = getattr(final, "output_text", "") or ""
        bad = outcome(final, max_tokens)
        if bad:
            res.ok, (res.error_category, res.error) = False, bad
        return res, (text if strict or not res.ok else json_text(text))
