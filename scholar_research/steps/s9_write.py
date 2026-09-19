"""Step 9 — research-write.  LLM drafts; **code** validates every \\cite against the .bib and prunes it.

Zero phantom citations is enforced mechanically: unknown keys are stripped and
replaced with a TODO comment before anything is written to disk.
"""
from __future__ import annotations

import re

from ..utils import dump_json, load_json, parse_frontmatter, write_text
from .base import Context, StepOutput

CITE_RE = re.compile(r"\\cite[tp]?\*?\{([^}]*)\}")
BIB_ENTRY_RE = re.compile(r"@(\w+)\{([^,\s]+),")


def parse_bib(text: str) -> dict[str, str]:
    """key → full entry text (brace-balanced)."""
    entries: dict[str, str] = {}
    for m in BIB_ENTRY_RE.finditer(text):
        start = m.start()
        depth, i = 0, m.end() - len(m.group(2)) - 2
        i = text.index("{", start)
        j = i
        while j < len(text):
            if text[j] == "{":
                depth += 1
            elif text[j] == "}":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        entries[m.group(2)] = text[start : j + 1]
    return entries


def validate_citations(tex: str, valid: set[str]) -> tuple[str, list[str], set[str]]:
    """Strip phantom keys; return (tex, phantom_keys, used_keys)."""
    phantoms: list[str] = []
    used: set[str] = set()

    def repl(m: re.Match) -> str:
        keys = [k.strip() for k in m.group(1).split(",") if k.strip()]
        ok = [k for k in keys if k in valid]
        bad = [k for k in keys if k not in valid]
        phantoms.extend(bad)
        used.update(ok)
        cmd = m.group(0)[: m.group(0).index("{")]
        out = f"{cmd}{{{', '.join(ok)}}}" if ok else ""
        if bad:
            out += f" % TODO: citation needed — no matching entry in references.bib for {', '.join(bad)}"
        return out

    return CITE_RE.sub(repl, tex), phantoms, used


def word_count(tex: str) -> int:
    t = re.sub(r"%.*", "", tex)
    t = re.sub(r"\\[a-zA-Z]+\*?(\[[^\]]*\])?(\{[^}]*\})?", " ", t)
    t = re.sub(r"[{}$&]", " ", t)
    return len([w for w in t.split() if re.search(r"[A-Za-z0-9]", w)])


def check_refs(tex: str) -> list[str]:
    labels = set(re.findall(r"\\label\{([^}]+)\}", tex))
    refs = set(re.findall(r"\\ref\{([^}]+)\}", tex))
    allowed_future = {"sec:method", "sec:experiment", "sec:discussion", "sec:conclusion", "sec:results", "sec:methods"}
    return sorted(r for r in refs - labels if r not in allowed_future)


def run(ctx: Context) -> StepOutput:
    s = ctx.session
    sc = s.load_config()
    cp4 = s.load_checkpoints().get(4)
    if not cp4 or not cp4.decision.get("approved"):
        raise RuntimeError("Checkpoint 4 unresolved: scope not approved")
    date = ctx.date(9)
    bib_text = s.path("step4_references.bib").read_text(encoding="utf-8")
    bib = parse_bib(bib_text)
    valid = set(bib)
    sota_md = s.path("step6_sota_review.md").read_text(encoding="utf-8")
    gaps_md = s.path("step7_gap_analysis.md").read_text(encoding="utf-8")
    hyp_md = s.path("step8_hypothesis_specification.md").read_text(encoding="utf-8")
    hyp_fm = parse_frontmatter(hyp_md)
    topic = hyp_fm.get("topic") or sc.topic
    fm6 = parse_frontmatter(sota_md)
    abstract_only = fm6.get("abstract_only") == "true" or fm6.get("full_text_papers") == "0"
    journal = cp4.decision.get("journal") or _top_journal(s.path("step8_journal_recommendations.md").read_text(encoding="utf-8"))
    # reorder gaps: locked first
    locked = hyp_fm.get("selected_gap", "")
    gaps_txt = gaps_md
    if locked and f"## {locked}:" in gaps_md:
        head, rest = gaps_md.split(f"## {locked}:", 1)
        gaps_txt = f"## {locked}:" + rest + "\n\n" + head
    out = ctx.llm.structured("s9_write", ctx_schema(), {"topic": topic, "journal": journal, "n_keys": len(valid), "keys": ", ".join(sorted(valid)), "hypothesis": hyp_md, "gaps": gaps_txt, "sota": sota_md, "abstract_only_note": "\n- Abstract-only pipeline: prefer qualitative framing and flag numbers with % TODO: verify against full text." if abstract_only else ""}, step=9)
    intro, ph1, used1 = validate_citations(out.intro_latex, valid)
    related, ph2, used2 = validate_citations(out.relatedwork_latex, valid)
    used = sorted(used1 | used2)
    unresolved = sorted(set(check_refs(intro + related)))
    header = lambda name: [f"% {name} — Research Agent Pipeline — Step 9", f"% Session: {sc.session_id} | Topic: {topic}", f"% Target journal: {journal}", f"% Generated: {date}", f"% Citation inventory: {len(valid)} keys available, {len(used)} keys used"] + (["% NOTE: This introduction was generated from an abstract-only pipeline.", "% Quantitative claims may need verification against full-text sources.", "% Run /research-fulltext to improve source material before finalizing."] if abstract_only else []) + ([f"% TODO: phantom citations removed: {', '.join(sorted(set(ph1 + ph2)))}"] if (ph1 or ph2) else []) + ([f"% TODO: unresolved \\ref: {', '.join(unresolved)}"] if unresolved else []) + [""]  # noqa: E731
    out_dir = s.path("step9_manuscript")
    out_dir.mkdir(exist_ok=True)
    write_text(out_dir / "01_intro.tex", "\n".join(header("01_intro.tex — Introduction")) + intro.strip())
    write_text(out_dir / "02_relatedwork.tex", "\n".join(header("02_relatedwork.tex — Related Work")) + related.strip())
    pruned = "\n".join([f"% Pruned BibTeX — Research Agent Pipeline Step 9", f"% Session: {sc.session_id} | Topic: {topic}", f"% Generated: {date}", f"% Entries: {len(used)} (pruned from {len(valid)} total in step4_references.bib)", "% Only includes entries actually cited in 01_intro.tex and 02_relatedwork.tex", ""] + [bib[k] + "\n" for k in used])
    write_text(out_dir / "references.bib", pruned)
    wc = {"intro": word_count(intro), "relatedwork": word_count(related)}
    todos = len(re.findall(r"% TODO", intro + related))
    report = {"target_journal": journal, "word_counts": wc, "citations_used": len(used), "citations_available": len(valid), "phantom_removed": sorted(set(ph1 + ph2)), "unresolved_refs": unresolved, "todo_flags": todos, "abstract_only": abstract_only}
    dump_json(out_dir / "_validation.json", report)
    notes = []
    if ph1 or ph2:
        notes.append(f"removed {len(set(ph1 + ph2))} phantom citation keys")
    if wc["intro"] < 2000:
        notes.append(f"introduction below the 2000-word floor ({wc['intro']} words)")
    return StepOutput(files=[out_dir / "01_intro.tex", out_dir / "02_relatedwork.tex", out_dir / "references.bib", out_dir / "_validation.json"], notes=notes, summary=report)


def ctx_schema():
    from ..schemas.llm_outputs import S9Manuscript

    return S9Manuscript


def _top_journal(md: str) -> str:
    m = re.search(r"^### 1\. (.+?)(?: ⭐.*)?$", md, re.M)
    return m.group(1).strip() if m else "target journal"
