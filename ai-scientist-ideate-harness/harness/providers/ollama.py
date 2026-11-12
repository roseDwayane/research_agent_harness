"""The Ollama provider: the chat flow (chat.py) over one Ollama server's HTTP API (/api/chat), no Claude Code involved.

    [harness]
    worker = "ollama"
    ollama_url = "https://ollama.example.org"     # or http://127.0.0.1:11434
    model = "qwen3.8"
    num_ctx = 131072                              # what the server loads the model with (`ollama ps`)
    # OLLAMA_API_KEY in the environment -> "Authorization: Bearer <key>" (for a server behind an auth proxy)

What is Ollama's own:
  - the answer is decoded under `format` (its JSON schema: grammar-constrained) and streamed (NDJSON), so a proxy in
    front of the server never sees an idle request (Cloudflare closes one after 100 s);
  - Ollama truncates an over-long prompt silently: a prompt estimated past num_ctx is not sent, a reply whose
    prompt_eval_count reached num_ctx is refused, and so is an answer cut at num_predict;
  - one server answers one call at a time: fan-outs run ollama_parallel calls at once, a long prompt is read into
    the server's cache before the call (prewarm), and a dropped call is sent again only once the server is free
    (wait_idle) - its own transport retry (ollama_busy_retries, ollama_busy_wait_s) instead of RP-TRANSPORT's.
"""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.request

from .. import __version__
from .base import WorkerResult
from .chat import TYPED_RESPONSE_SCHEMA, ChatProvider

STREAM_IDLE_S = 900.0               # the longest silence while streaming: a prompt being read (prefill) sends nothing


class StreamTimeout(TimeoutError):
    """A call that ran out of time, with what the model had written by then (logged: a runaway answer shows)."""

    def __init__(self, msg: str, partial: str = ""):
        super().__init__(msg)
        self.partial = partial


def _post(cfg, body: dict, timeout: float) -> tuple[int, dict | None, str]:
    url = cfg.ollama_url.rstrip("/") + "/api/chat"
    # a named client: a proxy in front of the server (Cloudflare's "error code: 1010") refuses Python-urllib's default
    headers = {"Content-Type": "application/json", "User-Agent": f"ideate-harness/{__version__}"}
    key = os.environ.get(cfg.ollama_api_key_env or "")
    if key:
        headers["Authorization"] = f"Bearer {key}"
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers=headers, method="POST")
    t0 = time.time()
    try:
        # streamed (NDJSON, one chunk per line): bytes flow while the model writes, so a proxy in front of the server
        # never sees an idle request (Cloudflare closes one after 100 s: "error code: 524"); a server that answers
        # with one JSON object (stream off, or a test fake) is the same loop with one line
        with urllib.request.urlopen(req, timeout=min(timeout, STREAM_IDLE_S)) as resp:
            parts, thinking, last = [], [], None
            try:
                for line in resp:
                    if not line.strip():
                        continue
                    chunk = json.loads(line.decode("utf-8", errors="replace"))
                    if chunk.get("error"):
                        return 500, None, str(chunk["error"])
                    msg = chunk.get("message") or {}
                    parts.append(str(msg.get("content") or ""))
                    thinking.append(str(msg.get("thinking") or ""))
                    last = chunk
                    if time.time() - t0 > timeout:
                        raise TimeoutError(f"no complete answer within {timeout}s")
            except TimeoutError as e:                   # our limit, or a read that waited STREAM_IDLE_S
                raise StreamTimeout(str(e), "".join(parts)) from e
            if last is None or not last.get("done"):     # cut off mid-answer: a dropped connection, not an answer
                return 502, None, "the stream ended before the answer was complete (connection dropped)"
            data = dict(last, message={"role": "assistant", "content": "".join(parts), "thinking": "".join(thinking)})
            return resp.status, data, ""
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace") if e.fp else ""
        return e.code, None, raw
    except ValueError as e:
        return 200, None, f"the server's answer is not JSON: {e}"


IDLE_PROBE_S, IDLE_PAUSE_S, IDLE_ROUNDS = 60.0, 30.0, 40   # wait_idle: at most ~1 h for a busy server to drain
WARM_CHARS = 20000            # a longer prompt is read into the server's cache (prewarm) before the call is sent
_LAST_MESSAGES: dict[int, list] = {}                       # thread -> the messages of its last call (the probe's)


def server_idle(cfg) -> bool:
    """Is the server free to take a request now? A one-token answer within IDLE_PROBE_S says so. Behind a proxy a
    dropped request is not cancelled - the server still writes the whole answer - and a re-send meanwhile only queues
    one more behind it (a cheap probe queues instead). The probe repeats this thread's last prompt: a server with one
    slot keeps the cache of the last prompt it read, so the probe either finds it cached or reads it into the cache -
    and the re-send then starts writing at once instead of reading a long prompt past a proxy's limit again."""
    messages = _LAST_MESSAGES.get(threading.get_ident()) or [{"role": "user", "content": "ok"}]
    body = {"model": cfg.model, "messages": messages, "stream": False,
            "options": {"num_ctx": int(cfg.num_ctx), "num_predict": 1}}       # num_ctx as loaded: no reload
    if cfg.think is not None:
        body["think"] = bool(cfg.think)                  # as the call sends it: the same prompt, the same cache
    if cfg.ollama_keep_alive:
        body["keep_alive"] = cfg.ollama_keep_alive
    try:
        status, data, _ = _post(cfg, body, IDLE_PROBE_S)
    except (TimeoutError, urllib.error.URLError, ConnectionError, OSError):
        return False
    return status == 200 and data is not None


def prewarm(cfg, messages: list[dict], say=None) -> None:
    """Read a long prompt into the server's cache with a one-token call before the call itself. Behind a proxy that
    closes a request whose first byte is late (Cloudflare: 100 s), a long prompt is otherwise dropped, and the server
    writes its whole answer for nobody before the re-send; a dropped one-token call costs only the prompt's reading,
    which the server finishes - the call then finds the prompt cached and starts writing at once. A prompt already
    cached answers the probe in about a second."""
    _LAST_MESSAGES[threading.get_ident()] = list(messages)
    if server_idle(cfg):
        return
    if say:
        say("reading the long prompt into the server's cache before the call (a proxy would drop it otherwise)")
    wait_idle(cfg)


def wait_idle(cfg, say=None) -> bool:
    """Wait, probing, until the server is free (True) or IDLE_ROUNDS probes found it busy (False)."""
    for i in range(IDLE_ROUNDS):
        if server_idle(cfg):
            return True
        if i == 0 and say:
            say("the server is still busy (most often with a dropped answer it is still writing); waiting for it")
        time.sleep(IDLE_PAUSE_S)
    return False


def _http_failure(status: int, raw: str, url: str) -> tuple[str, str]:
    text = raw.strip()[:300] or f"HTTP {status}"
    if status == 404:
        return "environment", f"{text} (is the model pulled on {url}? `ollama pull <model>`)"
    if status in (401, 403):
        if "1010" in text or "1020" in text:
            return "environment", f"{text} (a Cloudflare rule in front of {url} refused this client)"
        return "environment", f"{text} (the server wants credentials: export the key as OLLAMA_API_KEY)"
    if status == 429 or status >= 500:
        return "external_service", text
    return "tool_invocation", text


class OllamaProvider(ChatProvider):
    name = "ollama"
    grammar = True            # `format` is a grammar: a .json file written as JSON, optional fields in place

    @classmethod
    def check_config(cls, cfg) -> None:
        if not cfg.model:
            raise ValueError('worker = "ollama" needs a model (e.g. model = "qwen3.8")')

    @classmethod
    def window(cls, cfg) -> int:
        return int(cfg.num_ctx)

    @classmethod
    def parallel(cls, cfg) -> int:
        """At most ollama_parallel: one server answers one call at a time, and a queued request sends nothing (a
        proxy closes it)."""
        return max(1, min(cfg.max_parallel, cfg.ollama_parallel))

    @property
    def label(self) -> str:
        return f"ollama:{self.cfg.model}"

    def prompt_too_long(self, est_tokens: int) -> str | None:
        if est_tokens > int(self.cfg.num_ctx) * 0.95:
            return (f"the prompt is about {est_tokens} tokens, more than num_ctx {self.cfg.num_ctx}: Ollama would cut "
                    "it silently - raise num_ctx (and the server's) or give the Unit less to read")
        return None

    def before_call(self, messages: list[dict], say=None) -> None:
        if sum(len(m["content"]) for m in messages) > WARM_CHARS and not self.cfg.dry_run:
            prewarm(self.cfg, messages, say)

    def chat(self, messages: list[dict], timeout: float, fmt: dict | None = None) -> tuple[WorkerResult, str]:
        """One /api/chat call -> (result, the assistant's raw content)."""
        cfg = self.cfg
        body = {"model": cfg.model, "messages": messages, "format": fmt or TYPED_RESPONSE_SCHEMA, "stream": True,
                "options": {"num_ctx": int(cfg.num_ctx), "num_predict": int(cfg.num_predict)}}
        if cfg.think is not None:
            body["think"] = bool(cfg.think)
        if cfg.ollama_keep_alive:
            body["keep_alive"] = cfg.ollama_keep_alive
        if cfg.temperature is not None:
            body["options"]["temperature"] = float(cfg.temperature)
        t0 = time.time()
        try:
            _LAST_MESSAGES[threading.get_ident()] = list(messages)
            status, data, raw = _post(cfg, body, timeout)
        except TimeoutError as e:                    # our own limit, or a socket read that waited STREAM_IDLE_S
            took = time.time() - t0
            why = f"within {timeout:.0f}s" if took >= timeout else \
                f"- silent for {STREAM_IDLE_S:.0f}s after {took:.0f}s (busy, reloading the model, or the connection stalled)"
            return WorkerResult(False, error=f"no answer from {cfg.ollama_url} {why}", error_category="timeout",
                                duration_ms=int(took * 1000)), getattr(e, "partial", "")
        except (urllib.error.URLError, ConnectionError, OSError) as e:
            why = getattr(e, "reason", e)
            cat = "timeout" if "timed out" in str(why) else "external_service"
            return WorkerResult(False, error=f"cannot reach {cfg.ollama_url}: {why}", error_category=cat,
                                duration_ms=int((time.time() - t0) * 1000)), ""
        ms = int((time.time() - t0) * 1000)
        if status != 200 or data is None:
            cat, why = _http_failure(status, raw, cfg.ollama_url)
            return WorkerResult(False, error=why, error_category=cat, duration_ms=ms), ""
        tin, tout = int(data.get("prompt_eval_count") or 0), int(data.get("eval_count") or 0)
        res = WorkerResult(True, tokens_in=tin, tokens_out=tout, duration_ms=ms, turns=1)
        if tin >= int(cfg.num_ctx) - 32:
            res.ok, res.error_category = False, "budget"
            res.error = (f"the prompt filled the whole context ({tin} of num_ctx {cfg.num_ctx} tokens): Ollama cut it "
                         "silently - raise num_ctx (and the server's), or give the Unit less to read")
        elif data.get("done_reason") == "length":
            res.ok, res.error_category = False, "budget"
            res.error = f"the answer hit num_predict ({cfg.num_predict} tokens) and was cut: raise num_predict"
        return res, str((data.get("message") or {}).get("content") or "")

    # ------------------------------------------------------------------------------------------------ transport
    def retry_delay(self, ctx, wr: WorkerResult, attempt: int, error_id: str) -> float | None:
        """One server, one answer at a time: when it is busy, a request waits and a proxy closes it (524) - and the
        server may still finish the dropped answer. Wait for it to drain: 2, 4, 8, 15 minutes."""
        if attempt > self.cfg.ollama_busy_retries:
            return None
        return min(self.cfg.ollama_busy_wait_s * 2 ** (attempt - 1), 900.0)

    def before_resend(self, say=None) -> None:
        wait_idle(self.cfg, say=say)                 # never re-send to a server still busy
