"""A7.D deconstruct - each paper on its own, taken apart into addressable units (rules: references/fusion/F1-deconstruct.md).

The first step of the fusion block (docs/decisions/PLAN_ideate_fusion.md): one record per shortlisted paper, written
from that paper alone - its full text when A6 obtained one, otherwise its abstract - and never from another paper's
notes. Comparing papers is the collision step's job, so nothing here says who a paper disagrees with.

  record  knowledge/decon/<key>.json (ai-scientist-decon/1)
          eligibility       eligible | ineligible (+ reason, protocol criteria) | abstract-only
          summary           problem, method, data, metrics, headline, builds_on - the free lines of a reading note
          units[]           <key>#C claims (strength, scope, overreach?), #A assumptions, #L stated limitations, #F stated future
                            work - each with where + a verbatim quote, checked against the source - and #N not done
                            (the reader's observation, never quoted)
          experiments[]     the paper's methods-matrix rows (build-methods schema, exp_id <key>#E<n>)
          terms[]           the paper's own words for methods, measures (with the defining sentence), datasets, splits,
                            populations, constructs, paradigms - the raw material of the alignment step
  view    knowledge/_notes/<key>.md, rendered from an eligible full-text record (labels and order as before, so concept-index and
          stage B read it unchanged); never edited by hand

  ideate_tools.py decon-plan   <RD> [--ft-size 6] [--abs-size 40]   batches for the subagents (missing and stale only)
  ideate_tools.py decon-check  <RD> [--answer FILE ...] [--json]    the checks; --answer: one answer, nothing written
  ideate_tools.py decon-merge  <RD> [--revise REASON]               answers -> records + notes (valid ones only)
  ideate_tools.py decon-render <RD>                                 re-render every note from its record

The methods matrix is built from the records directly: `build-methods <RD> knowledge/methods_matrix_input.json
knowledge/decon/*.json` (build-methods concatenates the `experiments` of every input file).
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections import Counter
from pathlib import Path

from it_common import die, now_iso, read_json, sha256_file, sha256_json, write_json, write_text

SCHEMA = "ai-scientist-decon/1"
UNIT = "A7.D"
TBD = "(TBD)"
NR = "(NR)"
NA = "(NA)"            # read in full: the field does not apply to this design
KINDS = {"C": "claim", "A": "assumption", "L": "limitation", "F": "future", "N": "not-done"}
QUOTED = {"claim", "assumption", "limitation", "future"}      # not-done is the reader's observation: never quoted
# The source's own verb, strongest first. A note that upgrades a hedge makes a later contradiction attack something
# the paper never said (Craft of Research 6.6.4).
STRENGTH = ("causes", "shows", "suggests", "may", "correlates")
STRONG = {"causes", "shows"}
HEDGE = re.compile(r"\b(may|might|could|suggests?|suggesting|possibl[ey]|likely|potentially|appears?|seems?|indicates?)\b",
                   re.I)
SCOPE_KEYS = ("population", "data", "conditions")
SUMMARY_KEYS = ("problem", "method", "data", "metrics", "headline", "builds_on")
TERM_KINDS = ("method", "measure", "dataset", "split", "population", "construct", "paradigm")
VERDICTS = ("eligible", "ineligible", "abstract-only")
QUOTE_MIN_WORDS, QUOTE_MAX_WORDS, QUOTE_MIN_CHARS = 4, 60, 20
MAX_ROWS_FULL, MAX_CLAIMS_ABSTRACT, MAX_CLAIMS_FULL = 4, 3, 12
ROW_LISTS = ("method_family", "factors", "baselines", "ablations", "metrics", "not_done", "data")   # build-methods M_LIST + data
WORK = "knowledge/_work/A7D"
RULES = "references/fusion/F1-deconstruct.md"
VIEW_MARK = "<!-- view of knowledge/decon/"   # first line of every rendered note; a note without it is hand-written
SKILL = Path(__file__).resolve().parent.parent


def F(level, code, unit, msg):
    return {"level": level, "code": code, "unit": unit, "msg": msg}


def errors(fs):
    return [f for f in fs if f["level"] == "ERROR"]


# ================================================================================================ paths and sources
def decon_dir(rd: Path) -> Path:
    return Path(rd) / "knowledge" / "decon"


def notes_dir(rd: Path) -> Path:
    return Path(rd) / "knowledge" / "_notes"


def work_dir(rd: Path) -> Path:
    return Path(rd) / WORK


def _cfg(rd: Path) -> dict:
    p = Path(rd) / "step0_session_config.json"
    return read_json(p) if p.exists() else {}


def papers(rd: Path) -> dict:
    """citation_key -> shortlisted paper (A4 keys are the names of every fusion file)."""
    p = Path(rd) / "step3_shortlist.json"
    if not p.exists():
        die(f"{p} not found - the search block (A1-A5) comes first", 2)
    data = read_json(p)
    rows = data.get("papers") if isinstance(data, dict) else data
    return {x["citation_key"]: x for x in rows or [] if isinstance(x, dict) and x.get("citation_key")}


def full_text_path(rd: Path, key: str) -> Path:
    return Path(rd) / "step5_full_text" / f"{key}.md"


def source(rd: Path, key: str, paper: dict) -> tuple[str, str, str]:
    """(basis, text, sha) of what a record of this paper must be written from: the full text when A6 obtained one."""
    ft = full_text_path(rd, key)
    if ft.exists():
        return "full-text", ft.read_text(encoding="utf-8", errors="replace"), sha256_file(ft)
    abstract = str(paper.get("abstract") or "")
    return "abstract", f"{paper.get('title') or ''}\n{abstract}", sha256_json({"title": paper.get("title"),
                                                                              "abstract": abstract})


def squash(s) -> str:
    """Letters and digits only, case-folded. pdf2md / pdftotext break lines and hyphenate words ("detec-\\ntion"),
    and a quote is typed without either; comparing the squashed strings makes line breaks, hyphens, ligatures (NFKC)
    and markdown emphasis irrelevant while keeping every word and number in order."""
    return re.sub(r"[\W_]+", "", unicodedata.normalize("NFKC", str(s or "")).casefold())


def quote_problem(q, text_squashed: str, min_words: int = QUOTE_MIN_WORDS, min_chars: int = QUOTE_MIN_CHARS) -> str | None:
    q = str(q or "").strip()
    words = len(q.split())
    if (words < min_words or len(squash(q)) < min_chars) and not (squash(q) and squash(q) == text_squashed):
        return f"quote too short ({words} words; at least {min_words})"   # a source shorter than the minimum (a
                                                                           # three-word title, no abstract) is quoted whole
    if words > QUOTE_MAX_WORDS:
        return f"quote too long ({words} words; at most {QUOTE_MAX_WORDS} - quote the sentence that carries the unit)"
    if squash(q) not in text_squashed:
        return f"quote not found verbatim in the source: {q[:70]!r}"
    return None


def _criteria_ids(cfg: dict) -> set:
    """The protocol's IN* / EX* ids; on a topic framed before protocols, its pico slots (population, intervention, …)
    - an ineligible paper then names the slot it falls outside of."""
    crit = ((cfg.get("protocol") or {}).get("criteria") or {})
    ids = {c.get("id") for side in ("inclusion", "exclusion") for c in crit.get(side) or [] if c.get("id")}
    return ids or {k for k in (cfg.get("pico") or {}) if isinstance(k, str)}


def _is_tag(v, tag) -> bool:
    return isinstance(v, str) and v.strip().upper().startswith(tag)


# ================================================================================================ one record
def record_problems(rec: dict, rd: Path, pp: dict, cfg: dict, *, stale_check=True) -> list[dict]:
    """Every check one record must pass on its own (D01-D10, D14, D16, D17; D11 when stale_check)."""
    U = UNIT
    fs = []
    key = rec.get("citation_key")
    if rec.get("schema") != SCHEMA:
        fs.append(F("ERROR", "D01", U, f"{key or '?'}: schema must be {SCHEMA}"))
    if key not in pp:
        fs.append(F("ERROR", "D01", U, f"{key or '?'}: not a citation key of step3_shortlist.json"))
        return fs
    basis, text, sha = source(rd, key, pp[key])
    if rec.get("basis") != basis:
        if basis == "full-text":
            fs.append(F("ERROR", "D02", U, f"{key}: a full text exists (step5_full_text/{key}.md) but the record is "
                                            f"written from the {rec.get('basis')!r} - deconstruct the full text"))
        else:
            fs.append(F("ERROR", "D02", U, f"{key}: basis {rec.get('basis')!r} but no full text exists - basis abstract"))
        return fs
    if stale_check and rec.get("source_sha") and rec["source_sha"] != sha:
        fs.append(F("ERROR", "D11", U, f"{key}: STALE - the {basis} changed after the record was written; "
                                        "re-deconstruct it (decon-plan lists it)"))
    if not str(rec.get("model") or "").strip():
        fs.append(F("ERROR", "D16", U, f"{key}: `model` missing - every record names the model that wrote it"))
    ts = squash(text)
    # ---- eligibility
    el = rec.get("eligibility") or {}
    verdict = el.get("verdict")
    if verdict not in VERDICTS:
        fs.append(F("ERROR", "D07", U, f"{key}: eligibility.verdict must be one of {VERDICTS}"))
    elif (verdict == "abstract-only") != (basis == "abstract"):
        fs.append(F("ERROR", "D07", U, f"{key}: verdict {verdict!r} does not fit basis {basis!r} "
                                        "(abstract-only exactly when there is no full text)"))
    elif verdict == "ineligible":
        crit = set(el.get("criteria") or [])
        known = _criteria_ids(cfg)
        if not str(el.get("reason") or "").strip():
            fs.append(F("ERROR", "D07", U, f"{key}: ineligible needs a reason"))
        if known and (not crit or crit - known):
            fs.append(F("ERROR", "D07", U, f"{key}: ineligible must name the protocol criteria it fails "
                                            f"(IN* not met / EX* met), from {sorted(known)}; got {sorted(crit)}"))
        if rec.get("units") or rec.get("experiments"):
            fs.append(F("ERROR", "D07", U, f"{key}: an ineligible paper is not evidence - units and experiments "
                                            "stay empty (the reason is the record)"))
    # ---- summary
    summ = rec.get("summary") or {}
    miss = [k for k in SUMMARY_KEYS if not str(summ.get(k) or "").strip()]
    if miss and verdict != "ineligible":
        fs.append(F("ERROR", "D01", U, f"{key}: summary needs {miss} (write {TBD} when the source does not say)"))
    bok = summ.get("builds_on_keys")
    if bok is not None and (not isinstance(bok, list) or [k for k in bok if k not in pp or k == key]):
        fs.append(F("ERROR", "D19", U, f"{key}: builds_on_keys lists the shortlisted papers (by citation key) that this "
                                        f"paper says it builds on or argues with - not {bok}"))
    # ---- units
    seen, counts = set(), Counter()
    for u in rec.get("units") or []:
        uid, kind = str(u.get("id") or ""), u.get("kind")
        m = re.fullmatch(re.escape(key) + r"#([CALFN])(\d+)", uid)
        if not m or KINDS.get(m.group(1)) != kind:
            fs.append(F("ERROR", "D04", U, f"{uid or '?'}: id must be {key}#<C|A|L|F|N><n> with the letter of its kind "
                                            f"({kind!r})"))
            continue
        if uid in seen:
            fs.append(F("ERROR", "D04", U, f"{uid}: duplicate unit id"))
            continue
        seen.add(uid)
        counts[kind] += 1
        if not str(u.get("text") or "").strip():
            fs.append(F("ERROR", "D04", U, f"{uid}: empty text"))
        if kind in QUOTED:
            if not str(u.get("where") or "").strip():
                fs.append(F("ERROR", "D05", U, f"{uid}: `where` missing (section / page / table; 'abstract')"))
            prob = quote_problem(u.get("quote"), ts)
            if prob:
                fs.append(F("ERROR", "D05", U, f"{uid}: {prob}"))
        elif u.get("quote"):
            fs.append(F("ERROR", "D05", U, f"{uid}: a not-done unit is the reader's observation and carries no quote"))
        if kind == "claim":
            if u.get("strength") not in STRENGTH:
                fs.append(F("ERROR", "D06", U, f"{uid}: strength must be one of {STRENGTH} (the source's own verb)"))
            sc = u.get("scope")
            if not isinstance(sc, dict) or set(sc) != set(SCOPE_KEYS) or \
                    all(_is_tag(sc.get(k), TBD) or not str(sc.get(k) or "").strip() for k in SCOPE_KEYS):
                fs.append(F("ERROR", "D06", U, f"{uid}: scope must be {{{', '.join(SCOPE_KEYS)}}} with at least one "
                                                "stated (the population, data or conditions the claim is made for)"))
            if "overreach" in u and not str(u.get("overreach") or "").strip():
                fs.append(F("ERROR", "D06", U, f"{uid}: overreach, when present, says in one line what the analysis "
                                                "actually was"))
            if u.get("strength") in STRONG and HEDGE.search(str(u.get("quote") or "")):
                fs.append(F("WARN", "D17", U, f"{uid}: strength {u.get('strength')!r} but the quote hedges "
                                               f"({HEDGE.search(str(u.get('quote'))).group(0)!r}) - keep the source's verb"))
    if verdict in ("eligible", "abstract-only") and not counts["claim"]:
        fs.append(F("ERROR", "D09", U, f"{key}: no claim unit - every eligible paper states at least its main claim "
                                        f"({key}#C1)"))
    if basis == "full-text" and counts["claim"] > MAX_CLAIMS_FULL:
        fs.append(F("WARN", "D18", U, f"{key}: {counts['claim']} claims - more than {MAX_CLAIMS_FULL} usually means statistics "
                                       "recorded as claims; keep the results another paper could agree or disagree with"))
    if basis == "abstract" and counts["claim"] > MAX_CLAIMS_ABSTRACT:
        fs.append(F("WARN", "D10", U, f"{key}: {counts['claim']} claims from an abstract (at most "
                                       f"{MAX_CLAIMS_ABSTRACT}: an abstract states its main findings, not more)"))
    # ---- experiments (the methods-matrix rows; build-methods validates every field)
    rows = rec.get("experiments") or []
    eids = [r.get("exp_id") for r in rows]
    for r in rows:
        eid = str(r.get("exp_id") or "")
        if not re.fullmatch(re.escape(key) + r"#E\d+", eid) or r.get("citation_key") != key:
            fs.append(F("ERROR", "D08", U, f"{eid or '?'}: exp_id must be {key}#E<n> with citation_key {key}"))
        if r.get("evidence") != basis:
            fs.append(F("ERROR", "D08", U, f"{eid}: evidence must equal the record's basis ({basis})"))
        if "affordable_here" in r and not _is_tag(r["affordable_here"], TBD):
            fs.append(F("ERROR", "D08", U, f"{eid}: affordable_here is the lens's verdict, not the reader's - leave it "
                                            f"{TBD} (or out)"))
        bad = [k for k in ROW_LISTS if k in r and not isinstance(r[k], list)]
        if bad:
            fs.append(F("ERROR", "D08", U, f"{eid}: {bad} must be lists (['(TBD)'] when unknown)"))
        if basis == "abstract":
            nr = [k for k, v in r.items() for tag in (NR, NA)
                  if _is_tag(v, tag) or (isinstance(v, list) and any(_is_tag(x, tag) for x in v))]
            if nr:
                fs.append(F("ERROR", "D08", U, f"{eid}: (NR) / (NA) on an abstract row ({nr}) - both need the full "
                                                f"text; write {TBD}"))
    if len(set(eids)) != len(eids):
        fs.append(F("ERROR", "D08", U, f"{key}: duplicate exp_id"))
    if verdict == "eligible" and not 1 <= len(rows) <= MAX_ROWS_FULL:
        fs.append(F("ERROR", "D08", U, f"{key}: {len(rows)} experiment rows - a full-text paper has 1-{MAX_ROWS_FULL} "
                                        "(its main experiments)"))
    if verdict == "abstract-only" and len(rows) != 1:
        fs.append(F("ERROR", "D08", U, f"{key}: {len(rows)} experiment rows - an abstract-only paper has exactly 1"))
    # ---- terms
    terms = rec.get("terms") or []
    for t in terms:
        if t.get("kind") not in TERM_KINDS or not str(t.get("term") or "").strip():
            fs.append(F("ERROR", "D14", U, f"{key}: term {t.get('term')!r} needs a term and a kind from {TERM_KINDS}"))
        elif t.get("definition"):
            # a band's definition is often its edges: "Alpha Low (8-10 Hz)" is a complete definition
            prob = quote_problem(t["definition"], ts, min_words=2, min_chars=8)
            if prob:
                fs.append(F("ERROR", "D05", U, f"{key}: definition of {t['term']!r}: {prob}"))
    if verdict in ("eligible", "abstract-only") and not terms:
        fs.append(F("WARN", "D14", U, f"{key}: no terms - the alignment step has nothing of this paper's vocabulary"))
    return fs


# ================================================================================================ the note (a view)
def _lines(label: str, units, kind) -> list[str]:
    """One line per unit, each with the label: concept-index harvests a labelled line as one entry (up to 400
    characters), so eight `Not done:` items joined on one line would lose the last ones."""
    xs = [u for u in units if u.get("kind") == kind]
    return [f"{label} {u['text'].strip()} [{u['id'].split('#')[1]}]" for u in xs] or [f"{label} {TBD}"]


def render_note(rec: dict, paper: dict, disagreements: list[str] | None = None) -> str:
    """The reading note of a full-text record, in the old note's labels and order (knowledge-templates.md) so that
    concept-index harvests `Future work:` / `Not done:` / `Assumes:` / `Disagrees with:` as before. `Disagrees with:`
    is the collision step's projection; until it has run the line is (TBD)."""
    key, s, units = rec["citation_key"], rec.get("summary") or {}, rec.get("units") or []
    title = str(paper.get("title") or "").strip()
    short = title if len(title) <= 70 else title[:69] + "…"
    L = [f"{VIEW_MARK}{key}.json, rendered by `ideate_tools.py decon-render`: edit the record, "
         "not this file -->", f"# {key} — {short}"]
    L += [f"- Problem: {s.get('problem', TBD)}", f"- Method: {s.get('method', TBD)}", f"- Data: {s.get('data', TBD)}",
          f"- Metrics: {s.get('metrics', TBD)}", f"- Headline: {s.get('headline', TBD)}",
          *_lines("- Stated limitations:", units, "limitation"), *_lines("- Future work:", units, "future"),
          f"- Builds on / argues with: {s.get('builds_on', TBD)}"]
    main = next((u for u in units if u.get("kind") == "claim"), None)
    if main:
        sc = main.get("scope") or {}
        scope = "; ".join(f"{k} {sc.get(k)}" for k in SCOPE_KEYS if sc.get(k) and not _is_tag(sc.get(k), TBD))
        L.append(f"Claim scope: {main['text'].strip()} ({main.get('strength')}; {scope}) [C{main['id'].split('#C')[1]}]")
    else:
        L.append(f"Claim scope: {TBD}")
    L += [*_lines("Assumes:", units, "assumption"),
          *([f"Disagrees with: {d}" for d in disagreements] or [f"Disagrees with: {TBD}"]),
          *_lines("Not done:", units, "not-done")]
    return "\n".join(L) + "\n"


def has_note(rec: dict) -> bool:
    """A note is the view of an eligible full-text record: a paper read in full that is evidence. An ineligible paper
    gets none (its record holds the reason), so the notes still mean "read in full" to concept-index and stage B."""
    return not rec.get("_unreadable") and rec.get("basis") == "full-text" and \
        (rec.get("eligibility") or {}).get("verdict") == "eligible"



def note_disagreements(rd: Path, key: str) -> list[str]:
    """The `Disagrees with:` entries of one paper, projected from the collision log when the collision step has run
    (knowledge/collisions.jsonl). Empty before that."""
    p = Path(rd) / "knowledge" / "collisions.jsonl"
    if not p.exists():
        return []
    try:
        import it_collide  # noqa: F401 - the collision step owns the projection
        return it_collide.disagreements_of(rd, key)
    except ImportError:
        return []


def records(rd: Path) -> dict:
    d = decon_dir(rd)
    out = {}
    for f in sorted(d.glob("*.json")) if d.is_dir() else []:
        try:
            out[f.stem] = read_json(f)
        except json.JSONDecodeError:
            out[f.stem] = {"_unreadable": True}
    return out


def withdraw(rd: Path, pp: dict | None = None) -> dict:
    """A record (and a pending answer) of a paper that left the shortlist - its key retired by A4.k after a screening
    change - moves to knowledge/decon/_withdrawn/ with its rendered note removed; a withdrawn record whose paper is back
    on the shortlist is restored. Nothing is deleted: the record stays for the trail and comes back unchanged."""
    rd = Path(rd)
    pp = papers(rd) if pp is None else pp
    d, wd = decon_dir(rd), decon_dir(rd) / "_withdrawn"
    moved, restored = [], []
    for f in sorted(d.glob("*.json")) if d.is_dir() else []:
        if f.stem not in pp:
            wd.mkdir(parents=True, exist_ok=True)
            f.replace(wd / f.name)
            nf = notes_dir(rd) / f"{f.stem}.md"
            if nf.exists() and nf.read_text(encoding="utf-8").startswith(VIEW_MARK):
                nf.unlink()
            moved.append(f.stem)
    for f in sorted(wd.glob("*.json")) if wd.is_dir() else []:
        if f.stem in pp and not (d / f.name).exists():
            f.replace(d / f.name)
            restored.append(f.stem)
    ad = work_dir(rd) / "answers"
    for f in sorted(ad.glob("*.json")) if ad.is_dir() else []:
        if f.stem not in pp:
            (ad / "_withdrawn").mkdir(exist_ok=True)
            f.replace(ad / "_withdrawn" / f.name)
    return {"withdrawn": moved, "restored": restored}


def legacy_notes(rd: Path) -> list[str]:
    """Hand-written notes of a knowledge base built before the fusion block: they are never overwritten in place."""
    nd = notes_dir(rd)
    if not nd.is_dir() or decon_dir(rd).is_dir():
        return []
    return sorted(f.stem for f in nd.glob("*.md"))


# ================================================================================================ the whole step
def run_checks(rd: Path, cfg: dict | None = None) -> list[dict]:
    rd = Path(rd)
    cfg = cfg if cfg is not None else _cfg(rd)
    pp = papers(rd)
    recs = records(rd)
    fs = []
    for key, rec in recs.items():
        if rec.get("_unreadable"):
            fs.append(F("ERROR", "D01", UNIT, f"knowledge/decon/{key}.json does not parse (an interrupted write?)"))
            continue
        if rec.get("citation_key") != key:
            fs.append(F("ERROR", "D01", UNIT, f"knowledge/decon/{key}.json holds citation_key "
                                               f"{rec.get('citation_key')!r} - the file name is the key"))
            continue
        fs += record_problems(rec, rd, pp, cfg)
    missing = [k for k in pp if k not in recs]
    if missing:
        fs.append(F("ERROR", "D12", UNIT, f"{len(missing)} shortlisted paper(s) without a record: {missing[:10]}"
                                           f"{' …' if len(missing) > 10 else ''} (decon-plan lists them)"))
    for key, rec in recs.items():
        nf = notes_dir(rd) / f"{key}.md"
        if key not in pp or rec.get("_unreadable"):
            continue
        if not has_note(rec):
            if nf.exists():
                fs.append(F("ERROR", "D13", UNIT, f"{key}: knowledge/_notes/{key}.md exists but the record is not an "
                                                   "eligible full text - run decon-render (it removes the view)"))
            continue
        want = render_note(rec, pp[key], note_disagreements(rd, key))
        if not nf.exists():
            fs.append(F("ERROR", "D13", UNIT, f"{key}: knowledge/_notes/{key}.md missing - run decon-render"))
        elif nf.read_text(encoding="utf-8") != want:
            fs.append(F("ERROR", "D13", UNIT, f"{key}: knowledge/_notes/{key}.md differs from its record - the note is a "
                                               "view; edit the record (decon-merge --revise) and run decon-render"))
    return fs


def needing_records(rd: Path) -> tuple[list[str], list[str]]:
    """(missing, stale) citation keys."""
    pp, recs = papers(rd), records(rd)
    missing = [k for k in pp if k not in recs]
    stale = [k for k, r in recs.items() if k in pp and not r.get("_unreadable")
             and r.get("source_sha") != source(rd, k, pp[k])[2]]
    return missing, stale


def plan(rd: Path, ft_size: int = 6, abs_size: int = 40) -> dict:
    rd = Path(rd)
    cfg = _cfg(rd)
    pp = papers(rd)
    moved = withdraw(rd, pp)
    missing, stale = needing_records(rd)
    todo = missing + stale
    prot = cfg.get("protocol") or {}
    sp = rd / "screening_scores.json"                  # A3's amendments change what the criteria mean: an eligibility
    amend = (read_json(sp).get("criteria_amendments") or []) if sp.exists() else []   # verdict must see them too
    context = {"topic": cfg.get("topic"), "framework": prot.get("framework"), "outcomes": prot.get("outcomes"),
               "criteria": prot.get("criteria"), "criteria_amendments": [{k: a.get(k) for k in ("change", "reason", "refs")}
                                                                          for a in amend],
               "pico": None if prot else cfg.get("pico")}
    ft = [k for k in todo if full_text_path(rd, k).exists()]
    ab = [k for k in todo if k not in ft]
    wd = work_dir(rd)
    (wd / "answers").mkdir(parents=True, exist_ok=True)
    for old in wd.glob("batch_*.json"):
        old.unlink()
    batches = []

    def entry(k, basis):
        p = pp[k]
        e = {"citation_key": k, "title": p.get("title"), "year": p.get("year"), "basis": basis,
             "answer": f"{WORK}/answers/{k}.json"}
        if basis == "full-text":
            e["full_text"] = f"step5_full_text/{k}.md"
            fig = Path(rd) / "step5_full_text" / "figure" / "index.json"
            e["figure_index"] = "step5_full_text/figure/index.json" if fig.exists() else None
        else:
            e["abstract"] = p.get("abstract") or ""
        return e

    # an answer left from an earlier round for a paper planned again was written from the old source: move it away
    stale_answers = [wd / "answers" / f"{k}.json" for k in todo if (wd / "answers" / f"{k}.json").exists()]
    if stale_answers:
        arch = wd / "answers" / ("_superseded_" + now_iso().replace(":", "").replace("-", ""))
        arch.mkdir(parents=True, exist_ok=True)
        for f in stale_answers:
            f.rename(arch / f.name)
    for basis, keys, size in (("full-text", ft, ft_size), ("abstract", ab, abs_size)):
        for i in range(0, len(keys), size):
            n = len(batches) + 1
            b = {"batch": n, "basis": basis, "rules": RULES, "context": context,
                 "papers": [entry(k, basis) for k in keys[i:i + size]]}
            write_json(wd / f"batch_{n:03d}.json", b)
            batches.append({"batch": n, "basis": basis, "keys": keys[i:i + size]})
    out = {"at": now_iso(), "missing": missing, "stale": stale, "batches": batches, **moved}
    write_json(wd / "plan.json", out)
    return out


def merge(rd: Path, revise: str | None = None) -> dict:
    """Validate every answer under knowledge/_work/A7D/answers/ and write the valid ones as records (+ their notes).
    An answer for a paper whose current record stands is refused unless `revise` names why (a declared revision)."""
    rd = Path(rd)
    cfg, pp = _cfg(rd), papers(rd)
    legacy = legacy_notes(rd)
    if legacy:
        die(f"knowledge/_notes/ holds {len(legacy)} hand-written note(s) and there is no knowledge/decon/: a knowledge "
            "base built before the fusion block is frozen (PLAN_ideate_fusion §6) - run the fusion block on a copy of "
            "the research folder", 2)
    recs = records(rd)
    written, refused, kept = [], [], []
    for f in sorted((work_dir(rd) / "answers").glob("*.json")):
        try:
            ans = read_json(f)
        except json.JSONDecodeError:
            refused.append((f.stem, ["answer does not parse"]))
            continue
        key = ans.get("citation_key") or f.stem
        ans = {"schema": SCHEMA, **ans, "citation_key": key}
        fs = errors(record_problems(ans, rd, pp, cfg, stale_check=False))
        if fs:
            refused.append((key, [x["code"] + " " + x["msg"] for x in fs]))
            continue
        basis, _, sha = source(rd, key, pp[key])
        cur = recs.get(key)
        if cur and not cur.get("_unreadable") and cur.get("source_sha") == sha:
            same = {k: v for k, v in cur.items() if k not in ("at", "source_sha", "history")} == \
                   {k: v for k, v in ans.items() if k not in ("at", "source_sha", "history")}
            if same:
                kept.append(key)
                continue
            if not revise:
                refused.append((key, ["a current record exists; a change is a revision: decon-merge --revise "
                                      "'<why>' (e.g. a source check in B3 opened the full text)"]))
                continue
        hist = list((cur or {}).get("history") or [])
        if cur and not cur.get("_unreadable"):
            hist.append({"at": now_iso(), "reason": revise or "the source changed (stale record)",
                         "previous": sha256_json({k: v for k, v in cur.items() if k != "history"})})
        rec = {**ans, "basis": basis, "source_sha": sha, "at": now_iso(), "history": hist}
        write_json(decon_dir(rd) / f"{key}.json", rec)
        _write_view(rd, key, rec, pp[key])
        written.append(key)
    return {"written": written, "kept": kept, "refused": refused}


def render_all(rd: Path) -> int:
    rd = Path(rd)
    pp, n = papers(rd), 0
    for key, rec in records(rd).items():
        if key in pp and not rec.get("_unreadable"):
            n += _write_view(rd, key, rec, pp[key])
    return n


def _write_view(rd: Path, key: str, rec: dict, paper: dict) -> int:
    """Render the note of an eligible full-text record; remove a view left over from a record that no longer has one
    (never a hand-written note: only a file carrying the view mark)."""
    nf = notes_dir(rd) / f"{key}.md"
    if has_note(rec):
        write_text(nf, render_note(rec, paper, note_disagreements(rd, key)))
        return 1
    if nf.exists() and nf.read_text(encoding="utf-8").startswith(VIEW_MARK):
        nf.unlink()
    return 0


# ================================================================================================ CLI
def _print(fs, as_json=False):
    if as_json:
        print(json.dumps(fs, indent=2, ensure_ascii=False))
        return
    for f in fs:
        print(f"  {f['level']:<5} {f['code']} [{f['unit']}] {f['msg']}")
    print("OK" if not errors(fs) else f"{len(errors(fs))} error(s)")


def cmd_plan(a):
    rd = Path(a.research_dir)
    out = plan(rd, a.ft_size, a.abs_size)
    nft = sum(len(b["keys"]) for b in out["batches"] if b["basis"] == "full-text")
    nab = sum(len(b["keys"]) for b in out["batches"] if b["basis"] == "abstract")
    print(f"decon-plan: {len(out['missing'])} missing, {len(out['stale'])} stale -> {len(out['batches'])} batch(es) "
          f"({nft} full-text, {nab} abstract) in {WORK}/")
    if out.get("withdrawn") or out.get("restored"):
        print(f"  {len(out.get('withdrawn') or [])} record(s) of papers that left the shortlist moved to "
              f"knowledge/decon/_withdrawn/, {len(out.get('restored') or [])} restored")
    for b in out["batches"]:
        print(f"  batch_{b['batch']:03d}.json  {b['basis']:<9} {len(b['keys'])} paper(s)")
    if out["batches"]:
        print(f"  one subagent per batch: read {RULES} and its batch file, write one answer per paper under "
              f"{WORK}/answers/<key>.json, self-check with `decon-check <RD> --answer <file>`; then `decon-merge <RD>`")


def cmd_check(a):
    rd = Path(a.research_dir)
    if a.answer:
        cfg, pp, fs = _cfg(rd), papers(rd), []
        for path in a.answer:
            path = Path(path) if Path(path).exists() else Path(rd) / path      # batch files name paths relative to RD
            if not path.exists():
                die(f"answer file not found: {path}", 2)
            ans = read_json(path)
            ans = {"schema": SCHEMA, **ans}
            fs += record_problems(ans, rd, pp, cfg, stale_check=False)
    else:
        fs = run_checks(rd)
    _print(fs, a.json)
    raise SystemExit(1 if errors(fs) else 0)


def cmd_merge(a):
    from it_ledger import degraded_codes, run_unit
    rd = Path(a.research_dir)
    with run_unit(rd, UNIT, check=lambda: run_checks(rd), degraded=lambda: degraded_codes(rd, UNIT)):
        code = _cmd_merge(a)          # a refused answer leaves its paper without a record: the checks keep A7.D pending
    raise SystemExit(code)


def _cmd_merge(a) -> int:
    out = merge(Path(a.research_dir), a.revise)
    print(f"decon-merge: {len(out['written'])} written, {len(out['kept'])} unchanged, {len(out['refused'])} refused")
    for key, why in out["refused"]:
        print(f"  REFUSED {key}:")
        for w in why[:6]:
            print(f"    - {w}")
    return 1 if out["refused"] else 0


def cmd_render(a):
    n = render_all(Path(a.research_dir))
    print(f"decon-render: {n} note(s) rendered to knowledge/_notes/")


def add_parsers(sub) -> None:
    sp = sub.add_parser("decon-plan", help="A7.D: batches of papers to deconstruct (missing and stale records)")
    sp.add_argument("research_dir")
    sp.add_argument("--ft-size", type=int, default=6, help="full-text papers per subagent (default 6)")
    sp.add_argument("--abs-size", type=int, default=40, help="abstract-only papers per subagent (default 40)")
    sp.set_defaults(fn=cmd_plan)
    sp = sub.add_parser("decon-check", help="A7.D checks (D01-D17); --answer validates one answer without writing")
    sp.add_argument("research_dir")
    sp.add_argument("--answer", nargs="+", metavar="FILE")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(fn=cmd_check)
    sp = sub.add_parser("decon-merge", help="A7.D: valid answers -> knowledge/decon/<key>.json + the rendered note")
    sp.add_argument("research_dir")
    sp.add_argument("--revise", metavar="REASON", help="replace current records, recording why (a declared revision)")
    sp.set_defaults(fn=cmd_merge)
    sp = sub.add_parser("decon-render", help="A7.D: re-render knowledge/_notes/<key>.md from every full-text record")
    sp.add_argument("research_dir")
    sp.set_defaults(fn=cmd_render)


if __name__ == "__main__":  # direct use while the fusion block is not yet registered in ideate_tools.py
    import argparse
    ap = argparse.ArgumentParser(prog="it_decon.py")
    add_parsers(ap.add_subparsers(dest="cmd", required=True))
    ns = ap.parse_args()
    ns.fn(ns)
