"""The Claude provider (worker = "claude", the default): the Anthropic Messages API as a chat model - the same flow as
Ollama (chat.py): the files and the lookups in the prompt, one JSON answer, the conductor writes the files the scope
allows. It runs no commands: B6 (`consume`, the journal lookup) needs an agent (agent.py), and none is built in.

One chat() is one streamed request (an answer of whole files is long) through the official SDK, imported on the
first call - the rest of the harness runs without it:

  system          the Unit's rules, with a cache breakpoint: a fan-out's batches and a Unit's revisions share it
  messages        the conversation (a resumed session's history), with automatic caching of its tail: a revision
                  reads the files of the first message back from the cache
  output_config   effort, and the answer's JSON schema as a structured output (the SDK's transform_schema). A schema
                  with an open map (an object without fixed keys) cannot be one: that answer is asked for in the
                  prompt alone and read out of the text
  fallbacks       "default" (beta server-side-fallback-2026-07-01) on the models that take it: a request a safety
                  classifier declines is answered by the model Anthropic names for that category
  a request the API refuses (400) with the structured output or the fallbacks is sent once more without them

Credentials are the SDK's own: ANTHROPIC_API_KEY, ANTHROPIC_AUTH_TOKEN or an `ant auth login` profile. The SDK's
retries (429, 5xx, a dropped connection) are part of one call; the executor's RP-TRANSPORT comes after them.

[harness.provider_options.claude], all optional:
  effort          low | medium | high | xhigh | max (default "medium", Claude Opus 5.5's own); "" sends none
  max_tokens      the answer, thinking included (default 64000)
  context_window  tokens (default 1000000)
  fallbacks       false: no server-side fallback
  max_retries     the SDK's (default 2)
  base_url        a gateway in front of the API (default: the SDK's, or ANTHROPIC_BASE_URL)
  price_per_mtok  [input, output] in USD per million tokens, for a model PRICES does not list (else its cost is 0)
Not sent: temperature (the current models refuse it) and think (thinking is the model's own - adaptive on the
current models; effort is the control).
"""
from __future__ import annotations

import threading
import time

from .base import WorkerResult
from .chat import (RESPONSE_SCHEMA, ChatProvider, Rate, StreamDeadline, check_options, elapsed_ms, has_open_map,
                   json_text, rate_of, rate_override)

DEFAULT_MODEL = "claude-opus-5-5"
DEFAULT_EFFORT = "medium"
EFFORTS = ("low", "medium", "high", "xhigh", "max")
DEFAULT_MAX_TOKENS = 64000
DEFAULT_WINDOW = 1_000_000
READ_IDLE_S = 600.0                  # the longest silence in a stream (the API pings a live one) before it counts as cut
FALLBACK_BETA = "server-side-fallback-2026-07-01"
FALLBACK_MODELS = ("claude-fable-5-2", "claude-fable-5-1", "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5")


def _rate(pin: float, pout: float, read: float = 0.1) -> Rate:
    """A Claude list price: a cache read costs `read` x input, a 5-minute cache write 1.25x (Rate's default)."""
    return Rate(pin, pout, pin * read)


# list prices, USD per million tokens (input, output); Claude Haiku 5.5 costs more for a prompt over 100k tokens
PRICES = {
    "claude-fable-5-2": _rate(8.0, 40.0, 0.025), "claude-mythos-5-2": _rate(8.0, 40.0, 0.025),
    "claude-fable-5-1": _rate(10.0, 50.0, 0.025), "claude-mythos-5-1": _rate(10.0, 50.0, 0.025),
    "claude-fable-5": _rate(10.0, 50.0),
    "claude-opus-5-5": _rate(4.0, 20.0, 0.05), "claude-opus-5": _rate(5.0, 25.0),
    "claude-opus-4-8": _rate(5.0, 25.0), "claude-opus-4-7": _rate(5.0, 25.0), "claude-opus-4-6": _rate(5.0, 25.0),
    "claude-sonnet-5-5": _rate(2.0, 10.0, 0.05), "claude-sonnet-5": _rate(2.0, 10.0),
    "claude-sonnet-4-6": _rate(3.0, 15.0),
    "claude-haiku-5-5": [("", 0, _rate(0.10, 0.50)), ("", 100_000, _rate(0.50, 2.50))],
    "claude-haiku-4-5": _rate(1.0, 5.0),
}


def _tokens(u) -> tuple[int, ...]:
    """(fresh input, cache-written input, cache-read input, output) tokens of one attempt's usage."""
    return tuple(int(getattr(u, k, 0) or 0) for k in (
        "input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens", "output_tokens"))


def price(model: str, usage, opts: dict | None = None) -> float:
    """What one attempt cost in USD, at list prices (or the provider option price_per_mtok)."""
    fresh, wrote, read, out = _tokens(usage)
    rate = rate_override(opts) or rate_of(PRICES, model, fresh + wrote + read)
    return rate.cost(fresh, read, wrote, out) if rate else 0.0


def structured(schema: dict, transform) -> dict | None:
    """The answer's schema as a structured output - transform is the SDK's transform_schema: additionalProperties
    false on every object, the constraints the API does not take moved into the descriptions - or None where it
    cannot be one: an open map under additionalProperties false would only ever be {}."""
    if has_open_map(schema):
        return None
    try:
        return transform(schema)
    except (ValueError, TypeError, AssertionError):
        return None


def _classes(anthropic, *names: str) -> tuple:
    return tuple(c for c in (getattr(anthropic, n, None) for n in names) if isinstance(c, type))


def failure(anthropic, e: Exception) -> tuple[str, str]:
    """(category, message) of a failed request - the ideate_v2 categories an Ollama failure gets (_http_failure):
    transport (sent again) for a rate limit, an overload, a server error or a dropped connection; environment for
    credentials, access and an unknown model; budget for a spend limit or a request too large."""
    if isinstance(e, anthropic.APITimeoutError):                      # before APIConnectionError: it is one
        return "timeout", f"the Claude API did not answer in time: {e}"
    if isinstance(e, anthropic.APIConnectionError):
        return "external_service", f"cannot reach the Claude API: {e}"
    if isinstance(e, _classes(anthropic, "CredentialsError", "WorkloadIdentityError")):
        return "environment", f"no Claude API credentials ({e}): set ANTHROPIC_API_KEY or run `ant auth login`"
    if not isinstance(e, anthropic.APIStatusError):
        return "tool_invocation", f"the Claude API call failed: {e}"
    why = f"HTTP {e.status_code} from the Claude API: {getattr(e, 'message', '') or e}"
    if isinstance(e, _classes(anthropic, "EnforcedSpendLimitReachedError")):     # a 429 that waiting does not end
        return "budget", why
    if isinstance(e, anthropic.RateLimitError):
        return "external_service", why
    if isinstance(e, (anthropic.AuthenticationError, anthropic.PermissionDeniedError, anthropic.NotFoundError)
                  + _classes(anthropic, "OrganizationOnHoldError")) or e.status_code == 402:
        return "environment", why
    if isinstance(e, _classes(anthropic, "RequestTooLargeError", "ContentTooLargeError")) or e.status_code == 413:
        return "budget", why
    if isinstance(e, anthropic.InternalServerError) or e.status_code == 409:
        return "external_service", why
    if e.status_code == 408:
        return "timeout", why
    return "tool_invocation", why


class ClaudeProvider(ChatProvider):
    name = "claude"

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
        return f"claude:{self.model}"

    # ------------------------------------------------------------------------------------------------ the API
    def _client_of(self, anthropic):
        with self._lock:
            if self._client is None:
                opts = self.options()
                kw: dict = {"max_retries": int(opts.get("max_retries", 2))}
                if opts.get("base_url"):
                    kw["base_url"] = str(opts["base_url"])
                self._client = anthropic.Anthropic(**kw)
            return self._client

    def _send(self, anthropic, params: dict, fallback: bool, limit: float, t0: float):
        """One streamed request -> the final message; past the call's time limit it is closed (StreamDeadline)."""
        client = self._client_of(anthropic)
        timeout = anthropic.Timeout(limit, read=min(limit, READ_IDLE_S), connect=30.0)
        if fallback:
            manager = client.beta.messages.stream(**params, betas=[FALLBACK_BETA], fallbacks="default",
                                                  timeout=timeout)
        else:
            manager = client.messages.stream(**params, timeout=timeout)
        with manager as stream:
            for _event in stream:
                if time.time() - t0 > limit:
                    raise StreamDeadline()
            return stream.get_final_message()

    def chat(self, messages: list[dict], timeout: float, fmt: dict | None = None) -> tuple[WorkerResult, str]:
        try:
            import anthropic
        except ImportError:
            return WorkerResult(False, error='worker = "claude" needs the Anthropic SDK: pip install "anthropic>=2.8,<3"',
                                error_category="environment"), ""
        opts, model, t0 = self.options(), self.model, time.time()
        system = "\n\n".join(m["content"] for m in messages if m["role"] == "system" and m["content"])
        convo = [{"role": m["role"], "content": m["content"] or "(empty)"} for m in messages if m["role"] != "system"]
        schema = structured(fmt or RESPONSE_SCHEMA, anthropic.transform_schema)
        effort = opts.get("effort", DEFAULT_EFFORT)
        fallback = opts.get("fallbacks", True) is not False and model in FALLBACK_MODELS
        max_tokens = int(opts.get("max_tokens") or DEFAULT_MAX_TOKENS)
        msg, strict = None, False
        for extras in (True, False):             # the full request, then (after a 400) once without its extras
            params: dict = {"model": model, "max_tokens": max_tokens, "messages": convo,
                            "cache_control": {"type": "ephemeral"}}
            if system:
                params["system"] = [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]
            config = {"effort": effort} if effort else {}
            if extras and schema is not None:
                config["format"] = {"type": "json_schema", "schema": schema}
            if config:
                params["output_config"] = config
            try:
                msg = self._send(anthropic, params, extras and fallback, float(timeout), t0)
                strict = extras and schema is not None
                break
            except StreamDeadline:
                return WorkerResult(False, error=f"no complete answer from the Claude API within {timeout:.0f}s",
                                    error_category="timeout", duration_ms=elapsed_ms(t0)), ""
            except anthropic.AnthropicError as e:
                if extras and (schema is not None or fallback) and isinstance(e, anthropic.BadRequestError):
                    continue                     # a schema the API does not compile, a beta the account lacks
                cat, why = failure(anthropic, e)
                return WorkerResult(False, error=why, error_category=cat, duration_ms=elapsed_ms(t0)), ""
        # per attempt when a fallback ran (usage.iterations), else the one attempt
        attempts = [u for u in (getattr(msg.usage, "iterations", None) or [])
                    if getattr(u, "input_tokens", None) is not None] or [msg.usage]
        counts = [_tokens(u) for u in attempts]
        res = WorkerResult(True, tokens_in=sum(c[0] + c[1] + c[2] for c in counts), tokens_out=sum(c[3] for c in counts),
                           cost_usd=sum(price(str(getattr(u, "model", None) or msg.model or model), u, opts)
                                        for u in attempts), duration_ms=elapsed_ms(t0))
        text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
        if msg.stop_reason == "refusal":                 # a classifier or the model declined (after any fallback)
            category = getattr(getattr(msg, "stop_details", None), "category", None)
            res.ok, res.error_category = False, "model_output"
            res.error = "the Claude API declined the request (refusal" + (f": {category}" if category else "") + ")"
        elif msg.stop_reason == "max_tokens":
            res.ok, res.error_category = False, "budget"
            res.error = (f"the answer reached max_tokens ({max_tokens}, thinking included) before it was finished: "
                         "raise [harness.provider_options.claude] max_tokens or give the Unit less to write")
        return res, (text if strict or not res.ok else json_text(text))
