"""A chat provider: a model without tools, over a chat API. The conductor does what an agent's tools did:

  - the files the Unit may read are put into the prompt (FileScope.reads; a folder: its files);
  - read-only skill lookups and checks the recipe allows (LOOKUPS: list-papers, list-methods, env-probe, plan-status,
    B5's argument-check / tree-check / attack-check / pack-check) are run first (executors.py) and their output is
    put into the prompt; a state-changing command the task needs the worker to run itself (questions-prefill,
    frame query-revise, consume ...) cannot be, and the worker refuses the step at once instead of pretending;
  - the model answers with ONE JSON object - {"files": [{"path", "content"}], "note"} - decoded under that JSON
    schema where the API can (Ollama's `format`: grammar-constrained, far more reliable for a local model than tool
    calls); a step whose recipe names a `schema` for its one file gets {"answer": <that schema>, "note"} instead, so
    the file's own structure is decoded under the grammar too, not written as a string inside a string (the
    archived engine's way);
  - the conductor writes only the files the scope allows (the step's `writes`, the Unit's contract outputs, scratch
    folders), and checks a .json / .jsonl file parses before writing it.

A conversation is kept per session id, so a refused submission goes back to the same history (the RP-MODEL-OUTPUT
feedback of executors.py), as an agent resumes its own session. A server that cuts an over-long prompt silently would
answer another question: each prompt is estimated before it is sent (prompt_too_long).

ChatProvider does all of this. A chat API subclasses it and implements chat() - one call: the conversation and the
answer's JSON schema in, (WorkerResult with tokens and cost, the answer's text) out - and may override window(),
prompt_too_long() and before_call(). claude.py (the Anthropic Messages API), gpt.py (the OpenAI Responses API),
gemini.py (the Gemini API) and ollama.py are four; an OpenAI-compatible server or vLLM would be another.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
import uuid
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path
from typing import Callable

from .base import CHARS_PER_TOKEN, FileScope, Provider, WorkerRequest, WorkerResult

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "files": {"type": "array", "items": {"type": "object", "properties": {
            "path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}},
        "note": {"type": "string"}},
    "required": ["files", "note"]}
# the same envelope where a .json file's content may be its JSON value itself: decoded under a grammar that holds an
# open object (Ollama's), a big JSON file is never a JSON text escaped inside a string - the format error that made a
# local model's answer unusable most often
TYPED_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "files": {"type": "array", "items": {"type": "object", "properties": {
            "path": {"type": "string"},
            "content": {"anyOf": [{"type": "string"}, {"type": "object"}, {"type": "array"}]}},
            "required": ["path", "content"]}},
        "note": {"type": "string"}},
    "required": ["files", "note"]}

# read-only lookups a recipe lets a worker run, and how the conductor runs them for a worker that cannot
LOOKUPS = {
    # the shortlist with its citation keys (the raw default listed 30 of 300 records by paper id only, and a model
    # citing from it made up keys: marlats2020, wanghsieh2024)
    "ideate_tools.py list-papers": ["ideate_tools.py list-papers $RD --file shortlist --slice 0:80 --abstract-chars 160"],
    "ideate_tools.py list-methods": ["ideate_tools.py list-methods $RD"],
    "ideate_tools.py env-probe": ["ideate_tools.py env-probe $RD --json"],
    "ideate_tools.py plan-status": ["ideate_tools.py plan-status $GEN --json"],
    "ideate_tools.py search-check": ["ideate_tools.py search-check $RD"],
    "ideate_tools.py venues": ["ideate_tools.py venues $RD"],          # B6: target venues + the shortlist's venues
    "ideate_tools.py id-texts": ["ideate_tools.py id-texts $GEN"],    # P1-P5: what the ids of gen_k's files say
    "ideate_tools.py reflection-tail": ["ideate_tools.py reflection-tail $GEN"],  # a revision: the log's last rounds
    # B5's checks are read-only too: their findings are what the round pastes into reflection_log.md - one line each
    # (the text form: a third shorter than --json, and the form a reader pastes)
    "ideate_tools.py argument-check": ["ideate_tools.py argument-check $GEN --idea $GEN/idea_draft.json"],
    "ideate_tools.py tree-check": ["ideate_tools.py tree-check $GEN"],
    "ideate_tools.py attack-check": ["ideate_tools.py attack-check $GEN --idea $GEN/idea_draft.json"],
    "ideate_tools.py pack-check": ["ideate_tools.py pack-check $GEN --idea $GEN/idea_draft.json"],
}
NEEDS_ARGUMENTS = ("ideate_tools.py trace", "ideate_tools.py power")   # a lookup about one item: not run blind
TEXT_SUFFIXES = {".md", ".json", ".jsonl", ".txt", ".bib", ".csv", ".tsv", ".yaml", ".yml", ""}

CHAT_RULES = """\
You are one Unit (a small step) of the ai-scientist ideate pipeline, run by a code conductor. Rules:
- Do exactly the task below, following the Unit's rules (appended). You cannot open files or run commands: every file
  you may read, and the output of the lookups the conductor ran for you, is included in the task message.
- Answer with ONE JSON object, in the shape the task's "# Your answer" section gives. Where it is {"files": [...]},
  each file's content is its complete new text (not a diff); write only the files the task names or allows; a JSON
  file must be valid JSON.
- Knowledge comes from the files given, never from memory: a field you cannot support from a source is (TBD).
- No human is available: decide by the rules; where a rule leaves a choice, take the conservative one and say why
  in "note". If you cannot do the task with what you were given, write no file and say why in "note".
- The conductor checks what you wrote; if it finds problems it will tell you, in this same conversation, what to fix.
"""

_SESSIONS: dict[str, list[dict]] = {}
_WROTE: dict[str, dict[str, str]] = {}           # session -> {file: sha256 of what the model wrote there}


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else ""


SUPERSEDED = "(an earlier answer - the files it wrote were replaced by the answer further down)"


def _latest_answer_only(history: list[dict]) -> list[dict]:
    """A resumed history with every answer but the last cut to one line: each answer writes the whole files again, so
    the earlier ones are superseded, and keeping them grew the prompt by a file per revision (a 12k-token gap list
    took a B3 revision past num_ctx). The requests and findings stay: they say what was fixed."""
    last = max((i for i, m in enumerate(history) if m["role"] == "assistant"), default=-1)
    return [{**m, "content": SUPERSEDED} if m["role"] == "assistant" and i != last else m for i, m in enumerate(history)]


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
    # a revision (writes_only: the conversation goes on) starts from what is there; on a first call the file was left
    # by an earlier run - context, not an answer to keep (a model shown "revise it" keeps an earlier run's mistakes)
    note = " (current content - revise it, write it back whole)" if writes_only else \
        " (left by an earlier run - write it anew from the inputs; keep only what they still support)"
    for w in scope.writes:
        add(str(w), w, note)
    return "\n\n".join(out)


def build_message(task: str, scope: FileScope, grammar: bool = False) -> str:
    """The user message of a first call; grammar: a .json file's content is written as its JSON value (answer_format)."""
    parts = [task]
    files = _files_block(scope)
    if files:
        parts += ["# Files you can read", files]
    if scope.lookups:
        parts += ["# Lookups the conductor ran for you"] + [f"$ {c}\n{o.strip()}" for c, o in scope.lookups]
    if scope.schema is not None:
        if len(scope.writes) == 1:
            parts += ["# Your answer", f"One JSON object: {{\"answer\": <the content of {scope.writes[0]}>, \"note\"}}. "
                      "The conductor writes `answer` to that file."]
        else:
            parts += ["# Your answer", "One JSON object: {\"answer\": {<name>: <that file's content>, ...}, \"note\"}, "
                      "one entry per file, named by its file name without the extension: "
                      + ", ".join(f"{w.stem} -> {w}" for w in scope.writes) + ". The conductor writes each file."]
        return "\n\n".join(parts)
    allowed = [str(w) for w in scope.writes] + [f"{scope.base}/{g}" for g in scope.globs]
    parts += ["# Your answer", "One JSON object: {\"files\": [{\"path\", \"content\"}], \"note\"}. You may write only: "
              + "; ".join(allowed) + "."
              + (" A .json file's content is its JSON object itself, not a string; any other file's is its text."
                 if grammar else "")]
    return "\n\n".join(parts)


def answer_format(scope: FileScope, grammar: bool = False) -> dict:
    """The JSON schema an answer is decoded under: the files envelope (grammar: a .json file's content may be its JSON
    value), or {answer: <the step's schema>, note} (grammar: its optional properties in place, in_order)."""
    if scope.schema is None:
        return TYPED_RESPONSE_SCHEMA if grammar else RESPONSE_SCHEMA
    return {"type": "object", "properties": {"answer": in_order(scope.schema) if grammar else scope.schema,
                                             "note": {"type": "string"}},
            "required": ["answer", "note"]}


_SUBSCHEMAS = ("items", "additionalProperties", "not")
_BRANCHES = ("anyOf", "oneOf", "allOf", "prefixItems")


def in_order(s):
    """A JSON schema for a grammar (Ollama's `format`) with every optional property required but nullable. Such a
    grammar writes the required properties first and an optional one only after the last of them, and a model that has
    reached the end of an object closes it: a field the checker then asks for is never written (B3's move_reason, three
    revisions). Nullable, each optional property comes in its place - null where it does not apply, and drop_nulls
    takes it out again, so the file has the shape of the step's schema."""
    if isinstance(s, list):
        return [in_order(x) for x in s]
    if not isinstance(s, dict):
        return s
    out = dict(s)
    for k in _SUBSCHEMAS:
        if isinstance(s.get(k), dict):
            out[k] = in_order(s[k])
    for k in _BRANCHES:
        if isinstance(s.get(k), list):
            out[k] = [in_order(x) for x in s[k]]
    if isinstance(s.get("$defs"), dict):
        out["$defs"] = {k: in_order(v) for k, v in s["$defs"].items()}
    props = s.get("properties")
    if isinstance(props, dict) and props:
        req = set(s.get("required") or [])
        out["properties"] = {k: in_order(v) if k in req else {"anyOf": [in_order(v), {"type": "null"}]}
                             for k, v in props.items()}
        out["required"] = list(props)
    return out


def drop_nulls(v, s):
    """An answer decoded under in_order(s) back in the shape of s: an optional property written as null removed."""
    if not isinstance(s, dict):
        return v
    if isinstance(v, dict):
        props, req = s.get("properties") or {}, set(s.get("required") or [])
        extra = s.get("additionalProperties")
        for k in list(v):
            if k in props:
                if v[k] is None and k not in req:
                    del v[k]
                else:
                    v[k] = drop_nulls(v[k], props[k])
            elif isinstance(extra, dict):
                v[k] = drop_nulls(v[k], extra)
    elif isinstance(v, list) and isinstance(s.get("items"), dict):
        v = [drop_nulls(x, s["items"]) for x in v]
    for alt in (s.get("anyOf") or s.get("oneOf") or []) + (s.get("allOf") or []):
        if isinstance(alt, dict) and ((isinstance(v, dict) and (alt.get("properties") or alt.get("type") == "object"))
                                      or (isinstance(v, list) and (alt.get("items") or alt.get("type") == "array"))):
            v = drop_nulls(v, alt)
    return v


def _apply(scope: FileScope, content: str, grammar: bool = False) -> tuple[list[Path], list[str], str]:
    """Parse the answer and write what the scope allows -> (written, problems, note). grammar: the answer was decoded
    under answer_format(scope, grammar=True)."""
    try:
        answer = json.loads(content)
    except ValueError as e:
        return [], [f"your answer is not one JSON object ({e})"], ""
    if scope.schema is not None:                       # the answer is the file's object itself
        if not isinstance(answer, dict) or not isinstance(answer.get("answer"), dict) or not scope.writes:
            return [], ['your answer needs "answer": the object the task names, and "note"'], ""
        ans = drop_nulls(answer["answer"], scope.schema) if grammar else answer["answer"]
        if len(scope.writes) == 1:                     # one file: the object, or keyed by the file's name (a batch
            w = scope.writes[0]                        # schema keyed by its items, with one item in it)
            objs = {w: ans[w.stem] if set(ans) == {w.stem} and isinstance(ans[w.stem], dict) else ans}
        else:
            objs = {w: ans.get(w.stem) for w in scope.writes}
        written, problems = [], []
        for dest, obj in objs.items():
            if not isinstance(obj, dict):
                problems.append(f"answer.{dest.stem} is missing: one object per file")
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(json.dumps(obj, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
            written.append(dest)
        return written, problems, str(answer.get("note") or "")
    if not isinstance(answer, dict) or not isinstance(answer.get("files"), list):
        return [], ['your answer needs "files": a list of {"path", "content"}'], ""
    written, problems = [], []
    for f in answer["files"]:
        if not isinstance(f, dict) or not isinstance(f.get("path"), str) \
                or not isinstance(f.get("content"), (str, dict, list)):
            problems.append(f"a files entry without a string path and content: {str(f)[:120]}")
            continue
        dest = scope.target(f["path"])
        if dest is None:
            problems.append(f"{f['path']}: not a file you may write")
            continue
        text = f["content"]
        if not isinstance(text, str):                  # a JSON value (TYPED_RESPONSE_SCHEMA): a .json / .jsonl file's
            if dest.suffix == ".json":
                text = json.dumps(text, indent=1, ensure_ascii=False)
            elif dest.suffix == ".jsonl" and isinstance(text, list):
                text = "\n".join(json.dumps(x, ensure_ascii=False) for x in text)
            else:
                problems.append(f"{f['path']}: its content must be the file's text (a string)")
                continue
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


# ---------------------------------------------------------------------------------------- what chat APIs share
def has_open_map(s) -> bool:
    """Whether a schema has an object whose keys are not fixed (a map) anywhere in it: a strict structured output
    (Anthropic's, OpenAI's) closes every object, so such a map could only ever be {}."""
    if isinstance(s, list):
        return any(has_open_map(x) for x in s)
    if not isinstance(s, dict):
        return False
    t = s.get("type")
    if t == "object" or (isinstance(t, list) and "object" in t):
        extra = s.get("additionalProperties")
        if extra not in (None, False) or (extra is None and not s.get("properties")) or s.get("patternProperties"):
            return True
    subs = [s.get(k) for k in ("items", "prefixItems", "anyOf", "oneOf", "allOf")]
    subs += list((s.get("properties") or {}).values()) + list((s.get("$defs") or {}).values())
    return any(has_open_map(x) for x in subs if x is not None)


_FENCE = re.compile(r"^```[\w-]*[ \t]*\n(.*?)\n?```$", re.S)


def json_text(text: str) -> str:
    """The JSON object of an answer asked for in the prompt alone: a code fence or a sentence around it dropped."""
    t = text.strip()
    m = _FENCE.match(t)
    if m:
        t = m.group(1).strip()
    if not t.startswith("{") and "{" in t and "}" in t:
        t = t[t.index("{"): t.rindex("}") + 1]
    return t


@dataclass(frozen=True)
class Rate:
    """A model's list price in USD per million tokens: input, output, a cache read, and a cache write (None: 1.25x
    input - Anthropic's 5-minute and OpenAI's 30-minute writes)."""
    input: float
    output: float
    cached: float
    write: float | None = None

    def cost(self, fresh: int, read: int = 0, wrote: int = 0, out: int = 0) -> float:
        w = self.write if self.write is not None else self.input * 1.25
        return (fresh * self.input + read * self.cached + wrote * w + out * self.output) / 1e6


def rate_of(table: dict, model: str, prompt_tokens: int = 0, day: str | None = None) -> Rate | None:
    """A model's rate in a price table: its entry (or the longest entry its id extends - a dated snapshot), the price
    in force on `day` (YYYY-MM-DD, default today) and the tier of a prompt this long. An entry is a Rate, or a list of
    (since, over, Rate): from the date `since` ("" = always), for a prompt of more than `over` tokens."""
    key = model if model in table else max((k for k in table if model.startswith(k + "-")), key=len, default=None)
    if key is None:
        return None
    entry = table[key]
    if isinstance(entry, Rate):
        return entry
    day = day or date.today().isoformat()
    live = [e for e in entry if e[0] <= day]
    if not live:
        return None
    latest = max(e[0] for e in live)
    tiers = sorted(((over, r) for since, over, r in live if since == latest), key=lambda t: t[0])
    return next((r for over, r in reversed(tiers) if prompt_tokens > over), tiers[0][1])


def rate_override(opts: dict | None) -> Rate | None:
    """The provider option price_per_mtok = [input, output] (a cache read at 0.1x input), for a model the table lacks
    or a price of one's own."""
    p = (opts or {}).get("price_per_mtok")
    if not p:
        return None
    pin, pout = (float(x) for x in list(p)[:2])
    return Rate(pin, pout, pin * 0.1)


def check_options(name: str, o: dict, efforts: tuple[str, ...] = ()) -> None:
    """Refuse the settings a chat API provider shares when they are wrong: effort, max_tokens, context_window,
    max_retries, price_per_mtok."""
    where = f"[harness.provider_options.{name}]"
    if efforts and o.get("effort") not in (None, "", *efforts):
        raise ValueError(f"{where} effort must be one of {', '.join(efforts)} (or \"\"), not {o['effort']!r}")
    for k, least in (("max_tokens", 1), ("context_window", 1), ("max_retries", 0)):
        if k in o and not (isinstance(o[k], int) and not isinstance(o[k], bool) and o[k] >= least):
            raise ValueError(f"{where} {k} must be an integer >= {least}, not {o[k]!r}")
    p = o.get("price_per_mtok")
    if p is not None and not (isinstance(p, (list, tuple)) and len(p) == 2
                              and all(isinstance(x, (int, float)) and x >= 0 for x in p)):
        raise ValueError(f"{where} price_per_mtok must be [input, output] in USD per million tokens, not {p!r}")


class StreamDeadline(Exception):
    """A call ran past its time limit while its answer was still streaming."""


def elapsed_ms(t0: float) -> int:
    return int((time.time() - t0) * 1000)


class ChatProvider(Provider):
    """A model without tools: the files in the prompt, one JSON answer, the conductor writes it (see the top)."""
    runs_commands = False
    rules = CHAT_RULES
    grammar = False           # True: the answer is decoded under a grammar built from its schema (Ollama's `format`):
                              # an open object decodes, so a .json file's content is its JSON value (TYPED_RESPONSE_
                              # SCHEMA), and optional properties are sent in place (in_order). A strict structured
                              # output (Anthropic, OpenAI) holds no open object

    @classmethod
    def check_config(cls, cfg) -> None:
        if not cfg.model:
            raise ValueError(f'worker = "{cls.name}" needs a model ([harness] model)')

    @classmethod
    def batch_budget(cls, cfg) -> int:
        """Everything a chat worker reads is pasted into one prompt, so its batches are cut to what the context and
        max_file_chars hold: at most 40k characters (~12k tokens) whatever the context - a server reads such a prompt
        and sends its first byte before a proxy gives up (100 s at Cloudflare; ~17k tokens took longer on a 27B
        model), and a refused batch costs little to ask again."""
        w = cls.window(cfg)
        return max(8000, min(cls.file_chars(cfg), int(w * CHARS_PER_TOKEN * 0.4) if w else 40000, 40000))

    # ------------------------------------------------------------------------------------------------ the API
    def chat(self, messages: list[dict], timeout: float, fmt: dict | None = None) -> tuple[WorkerResult, str]:
        """One call of the API: the conversation, and the JSON schema the answer must follow (fmt; None: the files
        envelope) -> (the call's result: ok, tokens, duration or the error and its category; the answer's raw text)."""
        raise NotImplementedError(f"{type(self).__name__}.chat")

    def prompt_too_long(self, est_tokens: int) -> str | None:
        """Why a prompt of about est_tokens is not sent (it would be cut), or None to send it."""
        w = self.window(self.cfg)
        if w and est_tokens > int(w) * 0.95:
            return (f"the prompt is about {est_tokens} tokens, more than the {w}-token context the model runs with: "
                    "give the Unit less to read")
        return None

    def before_call(self, messages: list[dict], say: Callable[[str], None] | None = None) -> None:
        """Just before each call (Ollama: a long prompt is read into the server's cache first)."""

    # ------------------------------------------------------------------------------------------------ the worker
    def run(self, req: WorkerRequest) -> WorkerResult:
        """One worker turn (and, for an answer the conductor cannot use, one correction turn in the same
        conversation). An agent's arguments (commands, tools, add_dirs) do not apply."""
        cfg, scope, model = self.cfg, req.scope, self.model
        if not model:
            return WorkerResult(False, error=f'worker = "{self.name}" needs a model ([harness] model)',
                                error_category="environment")
        if scope.unavailable and not req.resume:
            return WorkerResult(False, error="this step needs a worker that runs skill commands itself ("
                                + ", ".join(scope.unavailable) + f"); the {self.name} worker cannot run commands - "
                                "run this Unit with an agent of your own (AgentProvider, providers/agent.py), or "
                                "make them steps of the recipe", error_category="environment")
        if req.resume:  # the history has the model's own answer: show a file again only where a tool changed it since
            wrote = _WROTE.get(req.resume, {})            # (re-reading its own answer made a revision the longest
            changed = [w for w in scope.writes if wrote.get(str(w.resolve())) != _sha(w)]    # prompt a Unit sends)
            current = _files_block(replace(scope, writes=changed), writes_only=True)
            message = req.task + ("\n\n# The files as they are now\n\n" + current if current else
                                  "\n\n(The files are as you wrote them.)" if scope.writes else "")
        else:
            message = build_message(req.task, scope, grammar=self.grammar)
        history = _latest_answer_only(_SESSIONS.get(req.resume, [])) if req.resume else \
            [{"role": "system", "content": req.system}]
        history.append({"role": "user", "content": message})
        too_long = self.prompt_too_long(int(sum(len(m["content"]) for m in history) / CHARS_PER_TOKEN))
        if too_long:
            return WorkerResult(False, error=too_long, error_category="budget")
        limit = req.timeout or cfg.worker_timeout_s
        total = WorkerResult(True, session_id=req.resume or uuid.uuid4().hex)
        note, written = "", []
        for turn in (1, 2):                                       # the answer, and one correction of an unusable one
            self.before_call(history, req.say)
            res, content = self.chat(history, limit, answer_format(scope, grammar=self.grammar))
            total.tokens_in += res.tokens_in
            total.tokens_out += res.tokens_out
            total.cost_usd += res.cost_usd
            total.duration_ms += res.duration_ms
            total.turns += 1
            if req.log_dir is not None:
                req.log_dir.mkdir(parents=True, exist_ok=True)
                (req.log_dir / f"{req.label}.{self.name}.{turn}.json").write_text(json.dumps(
                    {"model": model, "request_head": history[-1]["content"][:6000],
                     "request_tail": history[-1]["content"][-4000:], "answer": content, "error": res.error,
                     "tokens_in": res.tokens_in, "tokens_out": res.tokens_out, "duration_ms": res.duration_ms},
                    ensure_ascii=False, indent=1), encoding="utf-8")
            if not res.ok:
                total.ok, total.error, total.error_category = False, res.error, res.error_category
                break
            history.append({"role": "assistant", "content": content})
            got, problems, note = _apply(scope, content, grammar=self.grammar)
            written += got
            for w in got:
                _WROTE.setdefault(total.session_id, {})[str(w.resolve())] = _sha(w)
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
