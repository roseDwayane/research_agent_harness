"""An Ollama worker: the same job as claude_worker.run_worker, over Ollama's HTTP API, with no Claude Code involved.

A local model gets no tools. The conductor does what Claude Code's tools did:
  - the files the Unit may read are put into the prompt (FileScope.reads; a folder: its files);
  - read-only skill lookups and checks the recipe allows (list-papers, list-methods, env-probe, plan-status, B5's
    argument-check / tree-check / attack-check / pack-check) are run first and their
    output is put into the prompt; a state-changing command the task needs the worker to run itself (questions-prefill,
    frame query-revise, consume ...) cannot be, and the worker refuses the step at once instead of pretending;
  - the model answers with ONE JSON object - {"files": [{"path", "content"}], "note"} - decoded under Ollama's
    `format` (a JSON schema: grammar-constrained, far more reliable for a local model than tool calls);
  - the conductor writes only the files the scope allows (the step's `writes`, the Unit's contract outputs, scratch
    folders), and checks a .json / .jsonl file parses before writing it.

A conversation is kept per session id, so a refused submission goes back to the same history (the RP-MODEL-OUTPUT
feedback of executors.py) exactly as `claude -p --resume` does. Ollama truncates an over-long prompt silently: the
prompt is estimated before it is sent, and a reply whose prompt_eval_count reached num_ctx is refused.

    [harness]
    worker = "ollama"
    ollama_url = "https://ollama.example.org"     # or http://127.0.0.1:11434
    model = "qwen3.8"
    num_ctx = 131072                              # what the server loads the model with (`ollama ps`)
    # OLLAMA_API_KEY in the environment -> "Authorization: Bearer <key>" (for a server behind an auth proxy)
"""
from __future__ import annotations

import fnmatch
import json
import os
import re
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from . import __version__
from . import claude_worker as cw
from .claude_worker import WorkerResult
from .config import HarnessConfig

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "files": {"type": "array", "items": {"type": "object", "properties": {
            "path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}},
        "note": {"type": "string"}},
    "required": ["files", "note"]}

# read-only lookups a recipe lets a worker run, and how the conductor runs them for an Ollama worker
LOOKUPS = {
    "ideate_tools.py list-papers": ["ideate_tools.py list-papers $RD --abstract-chars 300"],
    "ideate_tools.py list-methods": ["ideate_tools.py list-methods $RD"],
    "ideate_tools.py env-probe": ["ideate_tools.py env-probe $RD --json"],
    "ideate_tools.py plan-status": ["ideate_tools.py plan-status $GEN --json"],
    "ideate_tools.py search-check": ["ideate_tools.py search-check $RD"],
    # B5's checks are read-only too: their findings are what the round pastes into reflection_log.md
    "ideate_tools.py argument-check": ["ideate_tools.py argument-check $GEN --idea $GEN/idea_draft.json --json"],
    "ideate_tools.py tree-check": ["ideate_tools.py tree-check $GEN --json"],
    "ideate_tools.py attack-check": ["ideate_tools.py attack-check $GEN --idea $GEN/idea_draft.json --json"],
    "ideate_tools.py pack-check": ["ideate_tools.py pack-check $GEN --idea $GEN/idea_draft.json --json"],
}
NEEDS_ARGUMENTS = ("ideate_tools.py trace", "ideate_tools.py power")   # a lookup about one item: not run blind
SCRATCH = ("_work/**", "knowledge/_work/**", "_state/harness/decisions/**")
PROTECTED = ("_state/ledger*", "_state/ledger_snap/**", "_state/errors/**", "_state/net/**", "ERRORS.md",
             "step0_session_config.json")
CHARS_PER_TOKEN = 3.0            # a conservative estimate for mixed English, JSON and Markdown
TEXT_SUFFIXES = {".md", ".json", ".jsonl", ".txt", ".bib", ".csv", ".tsv", ".yaml", ".yml", ""}

OLLAMA_RULES = """\
You are one Unit (a small step) of the ai-scientist ideate pipeline, run by a code conductor. Rules:
- Do exactly the task below, following the Unit's rules (appended). You cannot open files or run commands: every file
  you may read, and the output of the lookups the conductor ran for you, is included in the task message.
- Answer with ONE JSON object: {"files": [{"path": "...", "content": "..."}], "note": "..."}. Each file's content is
  its complete new text (not a diff). Write only the files the task names or allows; a JSON file must be valid JSON.
- Knowledge comes from the files given, never from memory: a field you cannot support from a source is (TBD).
- No human is available: decide by the rules; where a rule leaves a choice, take the conservative one and say why
  in "note". If you cannot do the task with what you were given, write no file and say why in "note".
- The conductor checks what you wrote; if it finds problems it will tell you, in this same conversation, what to fix.
"""

_SESSIONS: dict[str, list[dict]] = {}


@dataclass
class FileScope:
    """What one worker may read and write - decided by the executor, enforced here."""
    base: Path                                            # relative paths in the answer resolve against it
    reads: list[tuple[str, Path]] = field(default_factory=list)      # (the name the task uses, the file to show)
    writes: list[Path] = field(default_factory=list)      # files the step must leave written
    globs: list[str] = field(default_factory=list)        # base-relative patterns it may also write
    forbid: list[Path] = field(default_factory=list)      # never shown (a scorer's blinding)
    lookups: list[tuple[str, str]] = field(default_factory=list)     # (command, output) the conductor ran
    unavailable: list[str] = field(default_factory=list)  # commands the task asks the worker itself to run
    max_file_chars: int = 60000

    def target(self, path: str) -> Path | None:
        """Where an answered path may be written, or None when the scope does not allow it."""
        p = Path(path.strip())
        if p.is_absolute():
            dest = p
        else:
            dest = self.base / p
        try:
            dest = dest.resolve()
            rel = dest.relative_to(self.base.resolve()).as_posix()
        except (ValueError, OSError):
            rel = None
        for w in self.writes:                                 # an exact name of the task (also its bare file name)
            if dest == w.resolve() or (not p.is_absolute() and p.as_posix().lstrip("./") == w.name and
                                       len([x for x in self.writes if x.name == w.name]) == 1):
                return w
        if rel is None or ".." in Path(rel).parts:
            return None
        if any(fnmatch.fnmatch(rel, g) for g in PROTECTED):
            return None
        if any(fnmatch.fnmatch(rel, g) for g in self.globs):
            return dest
        return None


def _read_text(path: Path, limit: int) -> str:
    text = path.read_text(encoding="utf-8", errors="replace")
    if len(text) > limit:
        text = text[:limit] + f"\n[... truncated by the conductor at {limit} characters of {len(text)} ...]"
    return text


def _files_block(scope: FileScope, writes_only: bool = False) -> str:
    out, seen = [], set()
    forbid = {f.resolve() for f in scope.forbid}

    def add(label: str, path: Path, note: str = "") -> None:
        if path.resolve() in seen or path.resolve() in forbid or not path.is_file():
            return
        if path.suffix.lower() not in TEXT_SUFFIXES:
            out.append(f"=== FILE: {label} ({path.suffix} file, not shown) ===")
            return
        seen.add(path.resolve())
        out.append(f"=== FILE: {label}{note} ===\n{_read_text(path, scope.max_file_chars)}\n=== END FILE ===")

    for label, path in ([] if writes_only else scope.reads):
        if path.is_dir():
            for f in sorted(path.iterdir())[:40]:
                add(f"{label.rstrip('/')}/{f.name}", f)
        else:
            add(label, path)
    for w in scope.writes:                                    # a revision starts from what is there
        add(str(w), w, " (current content - revise it, write it back whole)")
    return "\n\n".join(out)


def build_message(task: str, scope: FileScope) -> str:
    parts = [task]
    files = _files_block(scope)
    if files:
        parts += ["# Files you can read", files]
    if scope.lookups:
        parts += ["# Lookups the conductor ran for you"] + [f"$ {c}\n{o.strip()}" for c, o in scope.lookups]
    allowed = [str(w) for w in scope.writes] + [f"{scope.base}/{g}" for g in scope.globs]
    parts += ["# Your answer", "One JSON object: {\"files\": [{\"path\", \"content\"}], \"note\"}. You may write only: "
              + "; ".join(allowed) + "."]
    return "\n\n".join(parts)


def ollama_system(system: str) -> str:
    """The Claude worker's system prompt with the Ollama rules instead of the shell's, and no command list."""
    if system.startswith(cw.SHELL_RULES):
        system = OLLAMA_RULES + system[len(cw.SHELL_RULES):]
    return re.sub(r"\n## Commands you may run\n.*?(?=\n## |\Z)", "\n", system, flags=re.S)


# ------------------------------------------------------------------------------------------------------- http
def _post(cfg: HarnessConfig, body: dict, timeout: float) -> tuple[int, dict | None, str]:
    url = cfg.ollama_url.rstrip("/") + "/api/chat"
    # a named client: a proxy in front of the server (Cloudflare's "error code: 1010") refuses Python-urllib's default
    headers = {"Content-Type": "application/json", "User-Agent": f"ideate-harness/{__version__}"}
    key = os.environ.get(cfg.ollama_api_key_env or "")
    if key:
        headers["Authorization"] = f"Bearer {key}"
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return resp.status, json.loads(raw), raw
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace") if e.fp else ""
        return e.code, None, raw
    except ValueError as e:
        return 200, None, f"the server's answer is not JSON: {e}"


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


def chat(cfg: HarnessConfig, messages: list[dict], timeout: float) -> tuple[WorkerResult, str]:
    """One /api/chat call -> (result, the assistant's raw content)."""
    body = {"model": cfg.model, "messages": messages, "format": RESPONSE_SCHEMA, "stream": False,
            "options": {"num_ctx": int(cfg.num_ctx), "num_predict": int(cfg.num_predict)}}
    if cfg.think is not None:
        body["think"] = bool(cfg.think)
    if cfg.temperature is not None:
        body["options"]["temperature"] = float(cfg.temperature)
    t0 = time.time()
    try:
        status, data, raw = _post(cfg, body, timeout)
    except TimeoutError:
        return WorkerResult(False, error=f"no answer from {cfg.ollama_url} within {timeout}s", error_category="timeout",
                            duration_ms=int((time.time() - t0) * 1000)), ""
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


# ------------------------------------------------------------------------------------------------------- worker
def _apply(scope: FileScope, content: str) -> tuple[list[Path], list[str], str]:
    """Parse the answer and write what the scope allows -> (written, problems, note)."""
    try:
        answer = json.loads(content)
    except ValueError as e:
        return [], [f"your answer is not one JSON object ({e})"], ""
    if not isinstance(answer, dict) or not isinstance(answer.get("files"), list):
        return [], ['your answer needs "files": a list of {"path", "content"}'], ""
    written, problems = [], []
    for f in answer["files"]:
        if not isinstance(f, dict) or not isinstance(f.get("path"), str) or not isinstance(f.get("content"), str):
            problems.append(f"a files entry without a string path and content: {str(f)[:120]}")
            continue
        dest = scope.target(f["path"])
        if dest is None:
            problems.append(f"{f['path']}: not a file you may write")
            continue
        text = f["content"]
        if dest.suffix == ".json":
            try:
                json.loads(text)
            except ValueError as e:
                problems.append(f"{f['path']}: not valid JSON ({e})")
                continue
        elif dest.suffix == ".jsonl":
            bad = [i + 1 for i, ln in enumerate(text.splitlines()) if ln.strip() and not _parses(ln)]
            if bad:
                problems.append(f"{f['path']}: lines {bad[:5]} are not valid JSON")
                continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")
        written.append(dest)
    return written, problems, str(answer.get("note") or "")


def _parses(line: str) -> bool:
    try:
        json.loads(line)
        return True
    except ValueError:
        return False


def run_worker(cfg: HarnessConfig, *, task: str, system: str, cwd: Path, scope: FileScope | None = None,
               resume: str | None = None, timeout: float | None = None, log_dir: Path | None = None,
               label: str = "worker", **_claude_only) -> WorkerResult:
    """One Ollama worker turn (and, for an answer the conductor cannot use, one correction turn in the same
    conversation). The claude-only arguments (allowed tools, add_dirs, budget_usd, bin_dir) do not apply."""
    if not cfg.model:
        return WorkerResult(False, error="worker = \"ollama\" needs a model ([harness] model)",
                            error_category="environment")
    scope = scope or FileScope(base=Path(cwd))
    if scope.unavailable and not resume:
        return WorkerResult(False, error="this step needs a worker that runs skill commands itself ("
                            + ", ".join(scope.unavailable) + "); the Ollama worker cannot run commands - the recipe "
                            "has to run them as steps of its own", error_category="environment")
    if resume:                                            # the history has the files; show what is written now
        current = _files_block(scope, writes_only=True)
        message = task + ("\n\n# The files as they are now\n\n" + current if current else "")
    else:
        message = build_message(task, scope)
    history = list(_SESSIONS.get(resume, [])) if resume else [{"role": "system", "content": ollama_system(system)}]
    history.append({"role": "user", "content": message})
    est = int(sum(len(m["content"]) for m in history) / CHARS_PER_TOKEN)
    if est > int(cfg.num_ctx) * 0.95:
        return WorkerResult(False, error=f"the prompt is about {est} tokens, more than num_ctx {cfg.num_ctx}: Ollama "
                            "would cut it silently - raise num_ctx (and the server's) or give the Unit less to read",
                            error_category="budget")
    limit = timeout or cfg.worker_timeout_s
    total = WorkerResult(True, session_id=resume or uuid.uuid4().hex)
    note, written = "", []
    for turn in (1, 2):                                       # the answer, and one correction of an unusable one
        res, content = chat(cfg, history, limit)
        total.tokens_in += res.tokens_in
        total.tokens_out += res.tokens_out
        total.duration_ms += res.duration_ms
        total.turns += 1
        if log_dir is not None:
            log_dir.mkdir(parents=True, exist_ok=True)
            (log_dir / f"{label}.ollama.{turn}.json").write_text(json.dumps(
                {"model": cfg.model, "request_tail": history[-1]["content"][-4000:], "answer": content,
                 "error": res.error}, ensure_ascii=False, indent=1), encoding="utf-8")
        if not res.ok:
            total.ok, total.error, total.error_category = False, res.error, res.error_category
            break
        history.append({"role": "assistant", "content": content})
        got, problems, note = _apply(scope, content)
        written += got
        if not problems:
            break
        if turn == 2:
            total.ok, total.error_category = False, "model_output"
            total.error = "the answer could not be used: " + "; ".join(problems[:4])
            break
        history.append({"role": "user", "content": "The conductor could not use part of your answer:\n- "
                        + "\n- ".join(problems) + "\nAnswer again with the complete JSON object."})
    _SESSIONS[total.session_id] = history
    total.text = note or ("wrote " + ", ".join(p.name for p in written) if written else "no file written")
    if not total.ok and not total.error:
        total.error = "the worker did not finish"
    return total
