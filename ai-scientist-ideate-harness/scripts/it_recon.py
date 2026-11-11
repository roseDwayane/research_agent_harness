"""Reconstruct - put the collisions back together: the field as it stands, and the questions worth asking
(rules: references/fusion/F4-reconstruct.md; decision record docs/decisions/PLAN_ideate_fusion.md).

  A7.R1  Lines + findings Points   debates from conflict groups, evolution chains from extends, analogies; findings
                                   Points from agree / boundary groups - the tool lists what may be promoted, the model
                                   writes the cards                       -> knowledge/lines/*.md, knowledge_cards.json
  A7.R2  Planes                    themes chosen now, after the collisions; Q3 / Q5 cite Lines, collisions, units
  A7.R3  descriptive Body          the seven questions; Q3 / Q5 cite Lines and collisions
  B2     synthesis                 step6_sota_review.md once per topic; consensus and debates only from collisions
  B3.5   questions                 per selected gap: common ground -> condition -> consequence -> research question, the
                                   four screens (the "settled" screen pre-filled from agree collisions)
                                                                          -> questions/Q_NNN.md
  F.9    index and views           questions/index.json, knowledge/fusion_map.md (a view)

  ideate_tools.py recon-candidates  <RD>               what may be promoted to Lines and findings Points
  ideate_tools.py fusion-map        <RD>               render knowledge/fusion_map.md
  ideate_tools.py questions-prefill <RD> GAP_NNN       same-coordinate agree / boundary collisions for the settled screen
  ideate_tools.py questions-handover <RD> Q_NNN       candidates for the question's section 9 (targets, rival accounts,
                                                       magnitudes - what the planning block attacks, rivals and powers
                                                       with; PLAN_ideate_planning §5)
  ideate_tools.py questions-index   <RD>               questions/index.json from questions/Q_*.md (refused while a check fails)
  ideate_tools.py recon-check       <RD> [--unit A7.R1|A7.R2|A7.R3|B2|B3.5|F.9|all] [--json]
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from it_common import die, now_iso, read_json, write_json, write_json_stable, write_text

TBD = "(TBD)"
WORK = "knowledge/_work/A7R"
QDIR = "questions"
INDEX = "questions/index.json"
MAP = "knowledge/fusion_map.md"
SOTA = "step6_sota_review.md"
RULES = "references/fusion/F4-reconstruct.md"
ID = re.compile(r"\b(X\d{4}|[EDA]_draft_\w+|P_draft_\w+|F_draft_T\d+_\w+|B_draft_\w+|GAP_\d{3}|Q_\d{3}|[a-z][a-z0-9]*?(?:\d{4}|nd)[a-z]?#[CALFNE]\d+)\b")     # keys: author + year | nd (no year) + suffix
DEBATE_RESULTS = {"conflict", "boundary"}
FINDING_RESULTS = {"agree", "boundary"}
COMMON_GROUND = {"agree", "boundary", "untested-shared"}    # what the field holds, or routinely does without testing
COVER = {"conflict", "boundary", "untested-shared", "assumption-challenged", "assumption-at-stake", "criterion-unmet"}
LINE_RESULTS = {"debate": DEBATE_RESULTS, "evolution": {"extends"}, "analogy": {"analogy"}}
Q_SECTIONS = ("1. Common ground", "2. Condition", "3. Consequence", "4. Three-step sentence", "5. Research question",
              "6. Screens", "7. Key terms", "8. Definitions")
SCREENS = {"settled": "already settled", "derivable": "derived from textbook", "data": "data on this machine",
           "larger": "a larger question"}
SCREEN_PASS = {"settled": ("no", "partly"), "derivable": ("no", "partly"), "data": ("yes",), "larger": ("yes",)}
Q_STATUS = ("ready", "abandoned", "screen_unresolved")
HANDOVER = "9. For the planning block"            # optional section: a ```json block (PLAN_ideate_planning §5, F-M1-M3)
NO_NUMBER = "(no reported number: this is an absence)"
TARGET_UNIT = re.compile(r"#[CA]\d+$")           # a target is something a paper holds: a claim or an assumption


def F(level, code, unit, msg):
    return {"level": level, "code": code, "unit": unit, "msg": msg}


def errors(fs):
    return [f for f in fs if f["level"] == "ERROR"]


def _cfg(rd) -> dict:
    p = Path(rd) / "step0_session_config.json"
    return read_json(p) if p.exists() else {}


# ================================================================================================ inputs
def frontmatter(text: str) -> dict:
    """The simple YAML of the cards: `key: value`, `key: [a, b]`, `key: {a: [..], b: ..}` on one line, or a list as
    `key:` and `- item` lines below it (the block form a model writes as often)."""
    m = re.match(r"^---\n(.*?)\n---", text, re.S)
    out = {}
    lines = m.group(1).splitlines() if m else []
    for i, line in enumerate(lines):
        if line.startswith((" ", "-")) or ":" not in line:
            continue
        key, _, rest = line.partition(":")
        if not rest.strip() and re.fullmatch(r"[A-Za-z_][\w-]*", key.strip()):
            items = []
            for nxt in lines[i + 1:]:
                mm = re.match(r"^\s*-\s+(.*)$", nxt)
                if not mm:
                    break
                items.append(mm.group(1).strip().strip("'\""))
            if items:
                out[key.strip()] = items
                continue
        # one key per line, or several (`topic: "…"   generation: 3   gap: GAP_003`, the older step templates)
        pairs = re.findall(r'([A-Za-z_][\w-]*):\s*(\[[^\]]*\]|\{[^}]*\}|"[^"]*"|\S+(?:\s(?!\s*[A-Za-z_][\w-]*:\s)\S+)*)', line)
        if len(pairs) <= 1:
            k, _, v = line.partition(":")
            pairs = [(k, v)]
        for k, v in pairs:
            v = v.strip()
            out[k.strip()] = [x.strip().strip("'\"") for x in v[1:-1].split(",") if x.strip()] if v.startswith("[") \
                else v.strip("'\"")
    return out


def section(text: str, heading_start: str) -> str:
    """The body of the markdown section whose heading starts with `heading_start` (any level)."""
    m = re.search(r"^#{2,3} " + re.escape(heading_start) + r".*?$(.*?)(?=^#{1,3} |\Z)", text, re.M | re.S)
    return m.group(1).strip() if m else ""


class World:
    """Everything reconstruct reads, loaded once."""

    def __init__(self, rd):
        import it_collide
        import it_decon
        rd = Path(rd)
        self.rd = rd
        self.cur = {r["collision_id"]: r for r in it_collide.current(it_collide.log(rd))}
        self.records = {k: r for k, r in it_decon.records(rd).items() if not r.get("_unreadable")}
        self.evidence = {k for k, r in self.records.items()
                         if (r.get("eligibility") or {}).get("verdict") in ("eligible", "abstract-only")}
        self.units = {u["id"]: {**u, "paper": k} for k, r in self.records.items() for u in r.get("units") or []}
        self.rows = {e["exp_id"] for r in self.records.values() for e in r.get("experiments") or []}
        cp = rd / "knowledge_cards.json"
        self.cards = read_json(cp) if cp.exists() else {}
        self.points = {"P_draft_" + re.sub(r"[^A-Za-z0-9_]+", "_", p["slug"]).strip("_"): p for p in self.cards.get("points") or []}
        self.planes = {f"F_draft_T{p['n']}_" + re.sub(r"[^A-Za-z0-9_]+", "_", p["slug"]).strip("_"): p
                       for p in self.cards.get("planes") or []}
        self.lines = {}
        ld = rd / "knowledge" / "lines"
        for f in sorted(ld.glob("*.md")) if ld.is_dir() else []:
            if f.name.startswith("frontmatter_patches"):
                continue
            text = f.read_text(encoding="utf-8")
            fm = frontmatter(text)
            self.lines[fm.get("id") or f.stem] = {"fm": fm, "text": text, "file": f.name}
        bd = rd / "knowledge" / "body"
        self.body = {f.stem: f.read_text(encoding="utf-8") for f in sorted(bd.glob("*_descriptive.md"))} if bd.is_dir() else {}
        qd = rd / QDIR
        self.questions = {f.stem for f in qd.glob("Q_*.md")} if qd.is_dir() else set()
        gp = rd / it_collide.GAPS
        self.gaps = read_json(gp) if gp.exists() else {}
        self.gap = {g["id"]: g for g in self.gaps.get("gaps") or []}
        al = rd / "knowledge" / "alignment.json"
        self.al = read_json(al) if al.exists() else {}
        self._I = None

    def same_data(self, cid: str) -> list[str]:
        import it_collide
        if self._I is None:
            self._I = it_collide.inputs(self.rd)
        return it_collide.same_data(self._I, self.cur[cid]) if cid in self.cur else []

    def known(self, i: str) -> bool:
        return (i in self.cur or i in self.lines or i in self.points or i in self.planes or i in self.units or
                i in self.rows or i in self.gap or i in self.body or i in self.questions)


# ================================================================================================ the digest
# What a reconstruct unit may cite, one line per id - for a worker that cannot open files (the harness's Ollama
# worker): the records, collisions, Lines, Points and Planes as ids with one line of text each, never the files
# themselves (collisions.jsonl and the methods matrix run to hundreds of kilobytes). Each section is capped.
DIGEST_SECTIONS = {
    "A7.R2": ("protocol", "papers", "collisions", "lines", "points", "lf_units"),
    "A7.R3": ("protocol", "absent", "planes", "lines", "collisions", "points", "habits"),
    "B2": ("protocol", "absent", "planes", "themes", "collisions", "lines", "points", "rows", "habits"),
    "B3": ("protocol", "sided_collisions", "fn_units", "lens", "paper_keys"),
}
DIGEST_CAP = {"papers": 600, "collisions": 400, "rows": 250, "lf_units": 300, "points": 200, "families": 600,
              "sided_collisions": 300, "fn_units": 250, "paper_keys": 400}


def _one(v, n=160) -> str:
    v = re.sub(r"\s+", " ", str(v or "")).strip()
    return v if len(v) <= n else v[:n - 1] + "…"


def absent(W: World) -> list[str]:
    """The kinds of id a section must cite that this corpus has none of, so that section says (TBD) (J07, J08) - a
    quick run judges no paper pairs and has no agree, conflict or extends collision to cite."""
    res = {r["result"] for r in W.cur.values()}
    out = []
    if not res & FINDING_RESULTS and not any(p.get("origin") == "collide" for p in W.points.values()):
        out.append("no agree / boundary collision and no findings Point: every Consensus section says (TBD)")
    if not res & DEBATE_RESULTS and not any(i.startswith("D_draft_") for i in W.lines):
        out.append("no conflict / boundary collision and no debate Line: every Debates section says (TBD)")
    if "extends" not in res and not any(i.startswith("E_draft_") for i in W.lines):
        out.append("no extends collision and no evolution Line: how the methods evolved (Q3) says (TBD)")
    return out


def digest(W: World, unit: str) -> str:
    cfg = read_json(W.rd / "step0_session_config.json") if (W.rd / "step0_session_config.json").exists() else {}
    prot = cfg.get("protocol") or {}
    L = [f"# Digest for {unit} - every id you may cite, one line each (generated by recon-digest; ids only from here)", ""]
    for sec in DIGEST_SECTIONS.get(unit, DIGEST_SECTIONS["B2"]):
        cap = DIGEST_CAP.get(sec, 10 ** 9)
        if sec == "protocol":
            fw = prot.get("framework") or {}
            L += ["## Protocol", f"topic: {_one(cfg.get('topic'), 300)}", f"framework: {fw.get('name')}"]
            L += [f"- slot {x.get('slot')}: {_one(x.get('value'), 200)}" for x in fw.get("slots") or []]
            L += [f"- outcome {o.get('id')}: {_one(o.get('text'), 200)}" for o in prot.get("outcomes") or []] + [""]
        elif sec == "absent":
            none = absent(W)
            if none:
                L += ["## None in this corpus (the section that would cite them says (TBD))", *[f"- {x}" for x in none], ""]
        elif sec == "papers":
            L += ["## Evidence papers (key · year · basis · problem / method)"]
            for k in sorted(W.evidence)[:cap]:
                r = W.records[k]
                sm = r.get("summary") or {}
                L.append(f"- {k} · {(r.get('year') or '')} · {r.get('basis')} · {_one(sm.get('problem'), 110)} / {_one(sm.get('method'), 90)}")
            L.append("")
        elif sec == "collisions":
            L += ["## Collisions (id · result · axes · sides · reason)"]
            for cid, r in sorted(W.cur.items())[:cap]:
                sides = ", ".join(x.get("id", "") for x in r.get("sides") or [])
                L.append(f"- {cid} · {r.get('result')} · {','.join(r.get('axes_differ') or [])} · {sides} · {_one(r.get('reason'), 150)}")
            L.append("")
        elif sec == "sided_collisions":           # B3 reads them in its source order, and quotes a side verbatim
            order = ["conflict", "untested-shared", "assumption-challenged", "assumption-at-stake", "criterion-unmet",
                     "boundary", "extends", "convention-vs-lens", "empty-cell"]
            L += ["## Collisions, in the order the rules read them (id · result · axes · reason; then each side: id · "
                  "paper · verbatim quote; then `gap:` what the rules settle for a gap resting on it)",
                  "Each collision here that two or more papers support is a gap, whatever its severity or feasibility - "
                  "low scores only rank it lower; not_gaps is for one no study could close."]
            rank = lambda r: (order.index(r["result"]) if r["result"] in order else 99,        # noqa: E731
                              r.get("axes_differ") != ["none"])
            gapish = [kv for kv in W.cur.items() if kv[1]["result"] in order]        # agree / independent: no gap
            import it_collide
            I = it_collide.inputs(W.rd)
            must = it_collide.must_account(W.cur)
            if must:
                L.append(f"Each of these {len(must)} - the straight conflicts and premise collisions - is in a gap or in "
                         f"not_gaps with a reason (W10): {', '.join(must)}")
            for cid, r in sorted(gapish, key=lambda kv: (rank(kv[1]), kv[0]))[:cap]:
                L.append(f"- {cid} · {r.get('result')} · {','.join(r.get('axes_differ') or [])} · {_one(r.get('reason'), 140)}")
                for x in r.get("sides") or []:
                    if x.get("paper"):                      # an empty cell's side is the cell, no paper and no quote
                        L.append(f"  - {x.get('id')} · {x.get('paper')} · \"{_one(x.get('quote'), 100)}\"")
                L.append(f"  - gap: {it_collide.gap_hint(I, r)}")
            L.append("")
        elif sec == "fn_units":
            L += ["## Future work (#F) and not done (#N) - the same item in >= 2 papers can be a gap"]
            n = 0
            for uid, u in sorted(W.units.items()):
                if re.search(r"#[FN]\d+$", uid) and n < cap:
                    L.append(f"- {uid}: {_one(u.get('text'), 140)}")
                    n += 1
            L.append("")
        elif sec == "paper_keys":
            L += ["## Evidence papers (key · problem) - for counter-evidence"]
            L += [f"- {k} · {_one((W.records[k].get('summary') or {}).get('problem'), 70)}" for k in sorted(W.evidence)[:cap]]
            L.append("")
        elif sec == "lens":
            lens = read_json(W.rd / "lens.json") if (W.rd / "lens.json").exists() else {}
            # one line per verdict, not per concept: the verdict is what a gap cites and what caps its feasibility
            L += ["## Lens (feasibility basis: cite as lens:<concept id>; the weakest cited verdict caps feasibility - "
                  "yes 5, partial / obtainable 4, no 2)"]
            by = defaultdict(list)
            for c, v in sorted((lens.get("on_coords") or {}).items()):
                by[str(v.get("affordable") or v.get("on_disk"))].append(f"lens:{c}")
            L += [f"- {verdict}: {', '.join(cs)}" for verdict, cs in sorted(by.items())]
            L += [f"- own:{d.get('name')} · {_one(d.get('what'), 120)}" for d in lens.get("own_data") or []] + [""]
        elif sec == "lines":
            L += ["## Lines (id · relation · collisions · title)"]
            for lid, ln in sorted(W.lines.items()):
                title = next((x[2:].strip() for x in ln["text"].splitlines() if x.startswith("# ")), "")
                L.append(f"- {lid} · {ln['fm'].get('relation_type')} · {ln['fm'].get('collisions')} · {_one(title, 140)}")
            L.append("")
        elif sec == "points":
            L += ["## Points (id · origin · core claim)"]
            for pid, pt in sorted(W.points.items())[:cap]:
                L.append(f"- {pid} · {pt.get('origin')} · {_one(pt.get('core_claim') or pt.get('description') or pt.get('name'), 150)}")
            L.append("")
        elif sec == "planes":
            L += ["## Planes (id · name · member papers · Q1)"]
            for fid, pl in sorted(W.planes.items()):
                mem = pl.get("member_papers") or []
                L.append(f"- {fid} · {_one(pl.get('name'), 100)} · {len(mem) if isinstance(mem, list) else mem} paper(s) · {_one(pl.get('q1'), 160)}")
                for q in ("q3", "q4", "q5"):
                    if pl.get(q):
                        L.append(f"  - {q.upper()}: {_one(pl.get(q), 220)}")
            L.append("")
        elif sec == "themes":                  # B2: what J08 counts in each Theme, worked out so the model only writes
            L += ["## What each Theme's Consensus and Debates may cite (J08; with none of these, the section says "
                  f"{TBD}) - the collisions touching the Plane's papers, its findings Points, its debate Lines"]
            for fid, pl in sorted(W.planes.items()):
                L.append(f"- {fid} · {_one(pl.get('name'), 100)}")
                for head, ids in theme_sources(W, pl).items():
                    L.append(f"  - {head}: {', '.join(ids) or TBD}")
            L.append("")
        elif sec == "lf_units":
            L += ["## Stated limitations (#L) and future work (#F) - the ids a Plane's Q5 may cite"]
            n = 0
            for uid, u in sorted(W.units.items()):
                if re.search(r"#[LF]\d+$", uid) and n < cap:
                    L.append(f"- {uid}: {_one(u.get('text'), 140)}")
                    n += 1
            L.append("")
        elif sec == "families":
            L += ["## Method families per paper (from the records' rows)"]
            for k in sorted(W.evidence)[:cap]:
                fams = sorted({f for e in W.records[k].get("experiments") or [] for f in e.get("method_family") or []})
                L.append(f"- {k}: {', '.join(fams) or '(TBD)'}")
            L.append("")
        elif sec == "rows":
            L += ["## Matrix rows (exp_id · data · n · metrics · headline · stats)"]
            n = 0
            for k in sorted(W.evidence):
                for e in W.records[k].get("experiments") or []:
                    if n >= cap:
                        break
                    data = "; ".join(f"{d.get('name')} n={d.get('n')}" for d in e.get("data") or [] if isinstance(d, dict))
                    L.append(f"- {e.get('exp_id')} · {_one(data, 80)} · {_one(', '.join(e.get('metrics') or []), 60)} · "
                             f"{_one(e.get('headline'), 100)} · {_one(e.get('stats'), 60)}")
                    n += 1
            L.append("")
        elif sec == "habits":
            rows = [e for k in W.evidence for e in W.records[k].get("experiments") or []]
            full = [e for e in rows if e.get("evidence") == "full-text"]
            nr = Counter(f for e in full for f, v in e.items() if v == "(NR)" or (isinstance(v, list) and "(NR)" in v))
            L += ["## Reporting habits (the matrix's (NR) counts over full-text rows)",
                  f"{len(full)} full-text row(s) of {len(rows)}" + (" - fewer than ~5: a few papers' habits, not the field's"
                                                                    if len(full) < 5 else ""),
                  "; ".join(f"{f}: {c} (NR)" for f, c in nr.most_common(12)) or "no (NR) recorded", ""]
    return "\n".join(L) + "\n"


def planes_schema(W: World) -> dict:
    """A7.R2's answer: the Planes and, apart from them, the Plane number of every evidence paper (`assign`, each paper
    required - so none is left out) and its methodology class; code turns `assign` into each Plane's member_papers
    (ideate_tools.normal_planes), and the classes go into the cards' `methodology` map (B2's mapping table)."""
    # bounded strings: a model caught repeating itself inside one text stops at the bound, not at num_predict
    name, text = {"type": "string", "maxLength": 120}, {"type": "string", "maxLength": 1200}
    most = max(1, min(6, len(W.evidence) // 2))                 # at most one theme per two papers
    # member_points, Q3 and Q5 are id lists (J05, J06): chosen from the ids that exist and count there, Q3 / Q5 joined
    # by normal_planes - a free text let a model write collision ids that do not exist, and independent collisions as
    # open problems
    q3 = sorted(W.lines) + sorted(W.cur)
    q5 = sorted(i for i in W.lines if i.startswith("D_draft_")) + sorted(c for c, r in W.cur.items() if r["result"] in COVER) \
        + sorted(u for u in W.units if re.search(r"#[LF]\d+$", u))
    ids = lambda xs: {"type": "array", "items": {"enum": xs or [TBD]}, "maxItems": 12}           # noqa: E731
    p = {"n": {"type": "integer", "minimum": 1, "maximum": most}, "name": name, "slug": name,
         "member_points": ids(sorted(W.points)), **{f"q{i}": text for i in (1, 2, 4)}, "q3": ids(q3), "q5": ids(q5),
         "judgement": text, "relations": text,                  # why one theme; how it feeds / depends on the others
         "adjacent_planes": {"type": "array", "items": {"type": "integer", "minimum": 1, "maximum": most},
                             "maxItems": most}}
    plane = {"type": "object", "properties": p, "required": list(p), "additionalProperties": False}
    assign = {k: {"type": "integer", "minimum": 1, "maximum": most} for k in sorted(W.evidence)}
    meth = {k: {"enum": list(METHODOLOGY)} for k in sorted(W.evidence)}       # B2's mapping table reads it
    return {"type": "object", "properties": {
        "planes": {"type": "array", "items": plane, "minItems": 1, "maxItems": most},
        "assign": {"type": "object", "properties": assign, "required": list(assign), "additionalProperties": False},
        "methodology": {"type": "object", "properties": meth, "required": list(meth), "additionalProperties": False}},
        "required": ["planes", "assign", "methodology"], "additionalProperties": False}


def cmd_digest(a):
    rd = Path(a.research_dir)
    W = World(rd)
    text = digest(W, a.unit)
    out = rd / "knowledge" / "_work" / "digest" / f"{a.unit}.md"
    write_text(out, text)
    print(f"recon-digest {a.unit}: {len(text)} characters -> {out.relative_to(rd)}")
    if a.unit == "A7.R2":                                       # the answer's schema beside it
        sp = out.with_suffix(".schema.json")
        write_json(sp, planes_schema(W))
        print(f"  schema: every evidence paper's Plane (assign) -> {sp.relative_to(rd)}")
    if a.unit == "B3":
        import it_collide
        sp = out.with_suffix(".schema.json")
        write_json(sp, it_collide.gaps_schema(rd))
        print(f"  schema: the gap list, its codes and this run's ids -> {sp.relative_to(rd)}")


# ================================================================================================ B2 tables
METHODOLOGY = {"experimental": "🔴 Red", "computational": "🟠 Orange", "review": "🟡 Yellow",     # research-cycle.md
               "observational": "🟢 Green", "engineering": "🔵 Cyan", "theoretical": "🟣 Purple"}  # section 2
_LEGEND = re.compile(r"^## Methodology legend\b.*?(?=^## |\Z)", re.M | re.S | re.I)
_MAPPING = re.compile(r"^## Paper.{1,3}theme mapping\b.*?(?=^## |\Z)", re.M | re.S | re.I)


def sota_tables(rd: Path, text: str) -> str:
    """The review with its two bookkeeping sections written by code (the archived layout): the methodology legend - each
    class's count over the papers the review cites - and the paper-theme mapping, one row per cited paper with its
    Plane, its methodology class (A7.R2's, (TBD) without one) and whether it bridges themes. What the model wrote
    under these headings is replaced; the papers count as cited only outside them."""
    cards = read_json(rd / "knowledge_cards.json") if (rd / "knowledge_cards.json").exists() else {}
    meth, bridges = cards.get("methodology") or {}, cards.get("bridges") or {}
    theme = {k: f"T{p.get('n')}" for p in cards.get("planes") or [] for k in p.get("member_papers") or []}
    body = _MAPPING.sub("", _LEGEND.sub("", text))
    cited = sorted({k for k in theme if re.search(rf"\b{re.escape(k)}\b", body)})
    counts = Counter(meth.get(k) for k in cited)
    legend = ["## Methodology legend", "", "| Color | Methodology | Count |", "|---|---|---|",
              *[f"| {c} | {m} | {counts.get(m, 0)} |" for m, c in METHODOLOGY.items()], ""]
    mapping = ["## Paper–theme mapping", "", "| Citation Key | Theme | Methodology | Bridge? |", "|---|---|---|---|",
               *[f"| `{k}` | {theme[k]} | {meth[k] if meth.get(k) in METHODOLOGY else TBD} | "
                 f"{bridges.get(k) or '—'} |" for k in cited], ""]
    first_theme = re.search(r"^## Theme ", body, re.M)
    at = first_theme.start() if first_theme else len(body)
    return body[:at] + "\n".join(legend) + "\n" + body[at:].rstrip("\n") + "\n\n" + "\n".join(mapping)


def id_case(W: World, text: str) -> str:
    """An id the model wrote in another case than its own ("P_draft_AbcI" for P_draft_Abci) spelled as the id: ids are
    the code's, their spelling is not a judgement."""
    own = {i.lower(): i for ids in (W.cur, W.units, W.rows, W.points, W.planes, W.lines, W.gap, W.body, W.questions)
           for i in ids}
    for i in sorted(set(ids_in(text))):
        if not W.known(i) and i.lower() in own:
            text = re.sub(rf"\b{re.escape(i)}\b", own[i.lower()], text)
    return text


def cmd_sota_tables(a):
    rd = Path(a.research_dir)
    p = rd / SOTA
    if not p.exists():
        die(f"{SOTA} missing - B2 writes it first", 2)
    write_text(p, sota_tables(rd, id_case(World(rd), p.read_text(encoding="utf-8"))))
    print(f"sota-tables: methodology legend and paper-theme mapping written, ids spelled as their own -> {SOTA}")


def ids_in(text: str) -> list[str]:
    return ID.findall(text or "")


# ================================================================================================ A7.R1 promotion
def promotion(W: World) -> dict:
    """What may be promoted: conflict / boundary groups (debates), extends chains (evolution), analogies, agree /
    boundary groups (findings Points) - grouped by the candidate they were judged on."""
    # one group per set of papers, not per candidate: two candidates on the same pair are one disagreement
    by_pair = defaultdict(list)
    for r in W.cur.values():
        by_pair[tuple(sorted({s["paper"] for s in r["sides"] if s.get("paper")}))].append(r)
    debates, findings, analogies = [], [], []
    for papers, rs in sorted(by_pair.items()):
        conf = [r for r in rs if r["result"] in DEBATE_RESULTS]
        if any(r["result"] == "conflict" for r in conf):
            debates.append({"papers": list(papers), "collisions": sorted(r["collision_id"] for r in conf),
                            "sides": len(papers), "units": len({s["id"] for r in conf for s in r["sides"]}),
                            "levels": sorted({r["evidence_level"] for r in conf})})
        agr = [r for r in rs if r["result"] in FINDING_RESULTS]
        if agr:
            findings.append({"papers": list(papers), "collisions": sorted(r["collision_id"] for r in agr),
                             "levels": sorted({r["evidence_level"] for r in agr}),
                             "same_data": sorted({d for r in agr for d in W.same_data(r["collision_id"])})})
        analogies += [{"collision": r["collision_id"], "papers": list(papers)} for r in rs if r["result"] == "analogy"]
    # evolution: extends records linked paper -> paper into chains
    nxt = defaultdict(set)
    for r in W.cur.values():
        if r["result"] == "extends":
            ps = [s["paper"] for s in r["sides"] if s.get("paper")]
            for a, b in zip(ps, ps[1:]):
                if a != b:
                    nxt[a].add((b, r["collision_id"]))
    # one lineage per connected group of papers (a branching tree is one lineage), papers in year order
    adj = defaultdict(set)
    cols_of = defaultdict(set)
    for a, outs in nxt.items():
        for b, c in outs:
            adj[a].add(b)
            adj[b].add(a)
            cols_of[frozenset((a, b))].add(c)
    seen, chains = set(), []
    for start in sorted(adj):
        if start in seen:
            continue
        comp, todo = set(), [start]
        while todo:
            p = todo.pop()
            if p not in comp:
                comp.add(p)
                todo += sorted(adj[p] - comp)
        seen |= comp
        cs = sorted({c for pair, cc in cols_of.items() if pair <= comp for c in cc})
        chains.append({"papers": sorted(comp), "collisions": cs, "size": len(comp)})
    return {"at": now_iso(), "debates": debates, "evolution": chains, "analogy": analogies, "findings": findings}


# ---- A7.R1 in batches: code decides what the rules settle, the model writes the cards
LINE_KINDS = {"debate": ("D", ("Axis of disagreement (爭論軸)", "Positions (兩派／三派主張)", "Evidence compared (證據對比)",
                               "Proposed resolutions (解套提案)", "Relevance to this topic (對本題的意義)")),
              "evolution": ("E", ("Full chain (完整鏈條)", "Mechanism of each step (每一步的機制)",
                                  "Counter-examples and exceptions (反例與例外)", "Relevance to this topic (對本題的意義)")),
              "analogy": ("A", ("Structure mapping table (結構映射表)", "Why it is an isomorphism (為什麼是同構)",
                                "Limits of the mapping (映射的極限)", "Relevance to this topic (對本題的意義)"))}
PATCHES = "knowledge/lines/frontmatter_patches.md"
PATCH_RELATION = {"debate": "debate", "evolution": "extends", "analogy": "analogy"}
POINT_FIELDS = ("description", "purpose", "core_claim", "expanded", "method", "findings")     # it_align.POINT_TEXT


def r1_items(W: World, P: dict) -> tuple[list[dict], list[str]]:
    """The promotion candidates the rules let through, each with what decides it, and the patch lines for the rest:
    a findings Point on agree / boundary collisions of >= 2 papers not abstracts only; a debate of >= 2 sides not on
    abstracts only, a card when it rests on >= 3 units or collisions (else the model judges whether it is a major axis);
    an evolution chain of >= 3 papers, or 2 when the later builds on the earlier; an analogy, a card only as a major
    cross-theme axis (the model judges). What is not a card is a patch line, so no collision drops out (J04)."""
    import it_decon
    years = {k: (v or {}).get("year") for k, v in it_decon.papers(W.rd).items()}
    later = lambda ps: sorted(ps, key=lambda k: (years.get(k) or 9999, k))              # noqa: E731
    items, patches = [], []

    def patch(kind, papers, cols, why):
        patches.append(f"- {f' ↔ {kind} ↔ '.join(f'`{k}`' for k in later(papers))} ({', '.join(cols)}) - {why}")

    for g in P["findings"]:
        if len(g["papers"]) >= 2 and set(g["levels"]) - {"abstract"}:
            items.append({"kind": "point", "papers": g["papers"], "collisions": g["collisions"], "same_data": g["same_data"]})
    for g in P["debates"]:
        if set(g["levels"]) <= {"abstract"}:
            patch("debate", g["papers"], g["collisions"], "every conflict rests on abstracts: no card (J02)")
        elif g["sides"] >= 2:
            items.append({"kind": "debate", "papers": g["papers"], "collisions": g["collisions"],
                          "card_required": g["units"] >= 3 or len(g["collisions"]) >= 3})
    for g in P["evolution"]:
        ps = later(g["papers"])
        later_says = ((W.records.get(ps[1]) or {}).get("summary") or {}).get("builds_on_keys") if len(ps) == 2 else None
        builds = ps[0] in (later_says or [])
        if g["size"] >= 3 or builds:
            items.append({"kind": "evolution", "papers": ps, "collisions": g["collisions"], "card_required": True})
        else:
            patch("extends", ps, g["collisions"], "a chain of two papers, the later not saying it builds on the earlier")
    for g in P["analogy"]:
        items.append({"kind": "analogy", "papers": g["papers"], "collisions": [g["collision"]], "card_required": False})
    return items, patches


def _side_view(W: World, c: str) -> dict:
    r = W.cur[c]
    return {"id": c, "result": r["result"], "axes_differ": r.get("axes_differ") or [], "reason": r.get("reason"),
            "evidence_level": r.get("evidence_level"),
            "sides": [{"id": x.get("id"), "paper": x.get("paper"), "kind": x.get("kind"), "quote": x.get("quote"),
                       **({k: W.units[x["id"]].get(k) for k in ("text", "strength", "overreach")} if x.get("id") in W.units
                          else {})} for x in r.get("sides") or []]}


def r1_schema(W: World, item: dict, points: list[str]) -> dict:
    """One candidate's answer: a findings Point's name, claim type and six fields, or a Line card's title, endpoints and
    sections - or, where the rules leave it open, `patch` with why it is no card. Texts have a ceiling."""
    txt = lambda n: {"type": "string", "maxLength": n}                                         # noqa: E731
    obj = lambda props, req: {"type": "object", "additionalProperties": False, "properties": props,  # noqa: E731
                              "required": req}
    if item["kind"] == "point":
        size = {"description": 400, "purpose": 300, "core_claim": 300, "expanded": 700, "method": 300, "findings": 500}
        f = {"name": txt(80), "claim_type": {"enum": ["empirical", "conceptual"]}, **{k: txt(size[k]) for k in POINT_FIELDS}}
        return obj(f, list(f))
    secs = LINE_KINDS[item["kind"]][1]
    card = obj({"title": txt(120), "endpoints": {"type": "array", "items": {"enum": points or [""]}, "maxItems": 6},
                "sections": obj({h: txt(900) for h in secs}, list(secs))}, ["title", "endpoints", "sections"])
    one = obj({"card": card}, ["card"])
    return one if item.get("card_required") else {"anyOf": [one, obj({"patch": txt(300)}, ["patch"])]}


def cmd_r1_batches(a):
    """A7.R1 for a worker that cannot run commands: one batch per candidate the rules let through (r1_items), each with
    the collisions' sides, quotes, reasons and the units' texts, the papers, and the concept Points on them (a card's
    endpoints), plus its answer's schema; the patch lines for the rest go to the plan."""
    rd = Path(a.research_dir)
    W = World(rd)
    wd = rd / WORK
    for old in [*wd.glob("r1_batch_*.json"), *(wd / "schemas").glob("r1_batch_*.json"), *(wd / "answers").glob("r1_*.json")]:
        old.unlink()
    import it_decon
    pp = it_decon.papers(rd)
    items, patches = r1_items(W, read_json(rd / WORK / "promotion.json"))
    for n, it in enumerate(items, 1):
        pts = sorted(i for i, pt in W.points.items() if {pt.get("source"), *(pt.get("also_in") or [])} & set(it["papers"]))
        b = {"batch": n, "kind": it["kind"], "answer": f"{WORK}/answers/r1_{n:03d}.json", **it,
             "papers": [{"key": k, "year": (pp.get(k) or {}).get("year"), "title": (pp.get(k) or {}).get("title")}
                        for k in it["papers"]],
             "collisions": [_side_view(W, c) for c in it["collisions"] if c in W.cur],
             "points": [{"id": i, "name": W.points[i].get("name"), "core_claim": _one(W.points[i].get("core_claim"), 160)}
                        for i in pts][:20]}
        write_json(wd / f"r1_batch_{n:03d}.json", b)
        write_json(wd / "schemas" / f"r1_batch_{n:03d}.json", r1_schema(W, it, [p["id"] for p in b["points"]]))
    write_json(wd / "r1_plan.json", {"at": now_iso(), "batches": len(items), "patches": patches})
    print(f"recon-batches: {len(items)} candidate(s) to write -> {WORK}/r1_batch_*.json ("
          + ", ".join(f"{k} {sum(1 for i in items if i['kind'] == k)}" for k in ("point", "debate", "evolution", "analogy"))
          + f"); {len(patches)} patch line(s)")


def cover_patch(W: World, c: str) -> str:
    """The patch line for a conflict, boundary or premise collision that no card or patch holds yet - the rules let a
    premise live in a patch (depends_on) and count patch lines for coverage (J04), so none drops out of the picture: a
    premise's holder <- the result <- what puts it at stake; the sides of the rest."""
    r = W.cur[c]
    ids = [x.get("id") for x in r.get("sides") or [] if x.get("id")]
    if r["result"] in PREMISE | {"criterion-unmet"}:
        hold = [i for i in ids if re.search(r"#A\d+$", i)][:1] or ids[:1]
        line = f"`{', '.join(hold)}` ← {r['result']} ← `{', '.join(i for i in ids if i not in hold)}`"
    else:
        line = f" ↔ {r['result']} ↔ ".join(f"`{i}`" for i in ids)
    return f"- {line} ({c}) - {_one(r.get('reason'), 160)}"


def _slug(name: str) -> str:
    return "_".join(w[:1].upper() + w[1:] for w in re.findall(r"[A-Za-z0-9]+", str(name or ""))[:6]) or "Untitled"


def cmd_r1_merge(a):
    """The answers made cards: findings Points (origin collide, their collisions and papers from the batch) into
    points_collide.json for cards-merge; Line cards rendered into knowledge/lines/ (id, relation, collisions and
    provenance by code); patches - the plan's and each declined card's - into frontmatter_patches.md. A7.R1 owns
    knowledge/lines/: the files of an earlier run go. A conflict, boundary or premise collision no card or patch holds
    gets a patch line of its own (cover_patch)."""
    rd = Path(a.research_dir)
    W = World(rd)
    wd = rd / WORK
    plan = read_json(wd / "r1_plan.json")
    patches, points, lines = list(plan.get("patches") or []), [], {}
    taken = {i for i, pt in W.points.items() if pt.get("origin") != "collide"}   # this Unit's own cards are rewritten
    for bf in sorted(wd.glob("r1_batch_*.json")):
        b = read_json(bf)
        ap = rd / b["answer"]
        ans = read_json(ap) if ap.exists() else None
        if not isinstance(ans, dict):
            print(f"  {bf.name}: no answer - left out")
            continue
        cols = [c["id"] for c in b["collisions"]]
        papers = [p["key"] for p in b["papers"]]
        if b["kind"] == "point":
            slug, k = _slug(ans.get("name")), 1
            while "P_draft_" + slug in taken:
                k += 1
                slug = f"{_slug(ans.get('name'))}_{k}"
            taken.add("P_draft_" + slug)
            points.append({"slug": slug, "origin": "collide", "collisions": cols, "source": papers[0],
                           "also_in": papers[1:], **{f: str(ans.get(f) or "").strip() or TBD
                                                     for f in ("name", "claim_type", *POINT_FIELDS)}})
        elif "patch" in ans:
            rel = PATCH_RELATION[b["kind"]]
            patches.append(f"- {f' ↔ {rel} ↔ '.join(f'`{k}`' for k in papers)} ({', '.join(cols)}) - "
                           f"{str(ans['patch']).strip()}")
        else:
            card = ans.get("card") or {}
            pre, secs = LINE_KINDS[b["kind"]]
            lid, k = f"{pre}_draft_{_slug(card.get('title'))}", 1
            while lid in lines:
                k += 1
                lid = f"{pre}_draft_{_slug(card.get('title'))}_{k}"
            sec = card.get("sections") or {}
            ends = [e for e in card.get("endpoints") or [] if e in W.points]
            lines[lid] = "\n".join(["---", f"id: {lid}", "type: line", f"relation_type: {b['kind']}",
                                     f"endpoints: [{', '.join(ends)}]", f"collisions: [{', '.join(cols)}]", "status: draft",
                                     f"provenance: {{source_files: [knowledge/collisions.jsonl], generated_at: {now_iso()[:10]}}}",
                                     "---", f"# {str(card.get('title') or lid).strip()}"]
                                    + [x for h in secs for x in (f"## {h}", str(sec.get(h) or "").strip() or TBD)]) + "\n"
    said = set(ids_in(" ".join([*lines.values(), *patches])))
    patches += [cover_patch(W, c) for c, r in sorted(W.cur.items()) if r["result"] in COVER and c not in said]
    ld = rd / "knowledge" / "lines"
    for old in ld.glob("*.md") if ld.is_dir() else []:
        old.unlink()
    for lid, text in lines.items():
        write_text(ld / f"{lid}.md", text)
    if patches:
        write_text(rd / PATCHES, "# Frontmatter patches (A7.R1: relations below a card's threshold)\n\n"
                   + "\n".join(patches) + "\n")
    write_json(wd / "points_collide.json", {"points": points})
    print(f"recon-merge: {len(points)} findings Point(s) -> {WORK}/points_collide.json, {len(lines)} Line card(s), "
          f"{len(patches)} patch line(s) -> knowledge/lines/")


def r1_problems(W: World) -> list[dict]:
    U = "A7.R1"
    fs = []
    for lid, L in sorted(W.lines.items()):
        fm = L["fm"]
        rel = fm.get("relation_type")
        cols = fm.get("collisions") or []
        if isinstance(cols, str):
            cols = [cols]
        if not cols:
            fs.append(F("ERROR", "J01", U, f"{lid}: a Line names the collisions it is built from (`collisions` in its frontmatter)"))
            continue
        bad = [c for c in cols if c not in W.cur]
        if bad:
            fs.append(F("ERROR", "J01", U, f"{lid}: collisions {bad} are not current"))
            continue
        want = LINE_RESULTS.get(rel)
        if want and not any(W.cur[c]["result"] in want for c in cols):
            fs.append(F("ERROR", "J01", U, f"{lid}: a {rel} Line needs at least one {sorted(want)} collision"))
        if rel == "debate":
            papers = {s["paper"] for c in cols for s in W.cur[c]["sides"] if s.get("paper")}
            levels = {W.cur[c]["evidence_level"] for c in cols if W.cur[c]["result"] in DEBATE_RESULTS}
            if len(papers) < 2:
                fs.append(F("ERROR", "J02", U, f"{lid}: a debate needs two named sides (papers)"))
            if levels and levels <= {"abstract"}:
                fs.append(F("ERROR", "J02", U, f"{lid}: every conflict behind this debate rests on abstracts only - a side "
                                                "made of abstracts cannot stand alone (PLAN F-D2)"))
    for pid, p in sorted(W.points.items()):
        if p.get("origin") != "collide":
            continue
        cols = p.get("collisions") or []
        bad = [c for c in cols if c not in W.cur or W.cur[c]["result"] not in FINDING_RESULTS]
        papers = {s["paper"] for c in cols if c in W.cur for s in W.cur[c]["sides"] if s.get("paper")}
        if not cols or bad or len(papers) < 2:
            fs.append(F("ERROR", "J03", U, f"{pid}: a findings Point (origin collide) rests on current agree / boundary "
                                            f"collisions of >= 2 papers (bad: {bad or 'none given'})"))
        elif {W.cur[c]["evidence_level"] for c in cols} <= {"abstract"}:
            fs.append(F("ERROR", "J03", U, f"{pid}: every collision behind this findings Point rests on abstracts only"))
        elif all(W.same_data(c) for c in cols):
            fs.append(F("WARN", "J03", U, f"{pid}: every agreement behind it is on shared data "
                                           f"({sorted({d for c in cols for d in W.same_data(c)})}) - one dataset reported "
                                           "twice, not a replication; say so in the card"))
    return fs


# ================================================================================================ A7.R2 / A7.R3 / coverage
def r2_problems(W: World) -> list[dict]:
    U = "A7.R2"
    fs = []
    if not W.planes:
        return [F("ERROR", "J05", U, "no Planes in knowledge_cards.json (themes are chosen at A7.R2)")]
    member = Counter(k for p in W.planes.values() for k in p.get("member_papers") or [])
    missing = sorted(W.evidence - set(member))
    twice = sorted(k for k, n in member.items() if n > 1)
    alien = sorted(set(member) - W.evidence)
    if missing or twice or alien:
        fs.append(F("ERROR", "J05", U, f"every evidence paper sits in exactly one Plane: missing {missing[:6]}, twice "
                                        f"{twice[:6]}, not evidence {alien[:6]}"))
    linked = defaultdict(set)              # papers each paper shares a relational collision with
    for r in W.cur.values():
        if r["result"] in COVER | FINDING_RESULTS | {"extends", "analogy"}:
            ps = {s["paper"] for s in r["sides"] if s.get("paper")}
            for x in ps:
                linked[x] |= ps - {x}
    for fid, p in sorted(W.planes.items()):
        mp = p.get("member_papers") or []
        if len(mp) == 1 and linked.get(mp[0]):
            fs.append(F("ERROR", "J05", U, f"{fid}: a one-paper theme, although {mp[0]} collides with "
                                            f"{sorted(linked[mp[0]])[:4]} - put it with them"))
    cap = max(1, len(W.evidence) // 2)
    if len(W.planes) > cap:
        fs.append(F("WARN", "J05", U, f"{len(W.planes)} Planes for {len(W.evidence)} evidence papers - at most {cap} "
                                       "(two papers a theme)"))
    for fid, p in sorted(W.planes.items()):
        bad_pts = [x for x in p.get("member_points") or [] if x not in W.points]
        if bad_pts:
            fs.append(F("ERROR", "J05", U, f"{fid}: member_points {bad_pts[:4]} do not exist"))
        for q in ("q3", "q5"):
            text = str(p.get(q) or "")
            ids = ids_in(text)
            if not text.strip() or (TBD not in text and not ids):
                fs.append(F("ERROR", "J06", U, f"{fid} {q.upper()}: cite Lines, collisions or units (or write {TBD})"))
            unknown = [i for i in ids if not W.known(i)]
            if unknown:
                fs.append(F("ERROR", "J06", U, f"{fid} {q.upper()}: unknown ids {unknown[:5]}"))
            if q == "q5":
                off = [i for i in ids if W.known(i) and not (re.search(r"#[LF]\d+$", i) or i.startswith("D_draft_") or
                                                             (i in W.cur and W.cur[i]["result"] in COVER))]
                if off:
                    fs.append(F("ERROR", "J06", U, f"{fid} Q5: open problems come from the papers' own limitation / "
                                                    f"future-work units, debates and conflict, boundary or premise "
                                                    f"collisions - not {off[:5]}"))
    return fs


BODY_HEADINGS = {"Q3": "How the methods evolved", "Q5": "Dependencies and conflicts between lines"}   # knowledge-templates.md


def r3_problems(W: World) -> list[dict]:
    U = "A7.R3"
    fs = []
    if not W.body:
        return [F("ERROR", "J07", U, "no descriptive Body (knowledge/body/B_draft_*_descriptive.md)")]
    for bid, text in W.body.items():
        for q in ("Q3", "Q5"):
            s = section(text, q)
            ids = ids_in(s)
            if not re.search(r"^#{2,3} " + q + r"\b", text, re.M):     # say what is missing: the heading itself
                fs.append(F("ERROR", "J07", U, f"{bid}: no section headed '## {q} ...' - the seven questions' headings "
                                                f"start with Q1 ... Q7 as in references/knowledge-templates.md "
                                                f"(here: '## {q} {BODY_HEADINGS[q]}')"))
            elif not s or (TBD not in s and not ids):
                fs.append(F("ERROR", "J07", U, f"{bid} {q}: cite Lines and collisions (or write {TBD})"))
            unknown = [i for i in ids if not W.known(i)]
            if unknown:
                fs.append(F("ERROR", "J07", U, f"{bid} {q}: unknown ids {unknown[:5]}"))
            if q == "Q3" and ids and TBD not in s and not any(i.startswith("E_draft_") or (i in W.cur and W.cur[i]["result"] == "extends")
                                                             for i in ids):
                fs.append(F("ERROR", "J07", U, f"{bid} Q3: how the methods evolved cites an evolution Line or an extends "
                                                "collision (or says (TBD))"))
    return fs


def coverage_problems(W: World) -> list[dict]:
    """Every conflict, boundary and premise collision lands somewhere in the reconstruction (a Line, a Plane's Q3 / Q5,
    the Body's Q5) or in the gap list - none is silently dropped."""
    patches = W.rd / "knowledge" / "lines" / "frontmatter_patches.md"
    text = " ".join([*(L["text"] for L in W.lines.values()),
                     patches.read_text(encoding="utf-8") if patches.exists() else "",
                     *(str(p.get("q3", "")) + " " + str(p.get("q5", "")) for p in W.planes.values()),
                     *(section(t, "Q5") + " " + section(t, "Q3") for t in W.body.values())])
    used = set(ids_in(text))
    left = sorted(c for c, r in W.cur.items() if r["result"] in COVER and c not in used)
    return [F("ERROR", "J04", "A7.R2", f"{len(left)} conflict / boundary / premise collision(s) in no Line, Plane Q3 / Q5 "
                                        f"or Body Q3 / Q5 - the field's picture must hold them (the gap list does not "
                                        f"count): {left[:10]}")] if left else []


# ================================================================================================ B2 synthesis
def counts_for(W: World, heading: str, i: str) -> bool:
    """Whether id i is what a Consensus (agree / boundary collision, findings Point) or Debates (conflict / boundary
    collision, debate Line) section rests on (J08)."""
    if i in W.cur:
        return W.cur[i]["result"] in (FINDING_RESULTS if heading == "Consensus" else DEBATE_RESULTS)
    if heading == "Consensus":
        return i in W.points and W.points[i].get("origin") == "collide"
    return i.startswith("D_draft_") and i in W.lines


def theme_sources(W: World, plane: dict) -> dict[str, list[str]]:
    """The ids a Plane's Theme may cite under Consensus and Debates: those that count (counts_for) and touch the Plane's
    papers - a collision with a side among them, a Point or Line resting on them."""
    mem = set(plane.get("member_papers") or [])
    touch = {c for c, r in W.cur.items() if {x.get("paper") for x in r.get("sides") or []} & mem}
    pts = {i for i, p in W.points.items() if {p.get("source"), *(p.get("also_in") or [])} & mem}
    lines = {i for i, ln in W.lines.items() if set(ids_in(str(ln["fm"].get("collisions") or ""))) & touch}
    return {h: sorted(i for i in touch | pts | lines if counts_for(W, h, i)) for h in ("Consensus", "Debates")}


def b2_problems(W: World) -> list[dict]:
    U = "B2"
    p = W.rd / SOTA
    if not p.exists():
        return [F("ERROR", "J08", U, f"{SOTA} missing (once per topic, at the research folder's root)")]
    text = p.read_text(encoding="utf-8")
    fs = []
    if frontmatter(text).get("scope") != "topic":
        fs.append(F("ERROR", "J08", U, f"{SOTA}: frontmatter `scope: topic` (one synthesis per topic, no angle)"))
    for heading in ("Consensus", "Debates"):
        for m in re.finditer(r"^### " + heading + r".*?$(.*?)(?=^#{1,3} |\Z)", text, re.M | re.S):
            body = m.group(1)
            ids = ids_in(body)
            if TBD in body or any(counts_for(W, heading, i) for i in ids):
                continue
            theme = ([t for t in re.findall(r"^## (Theme .*)$", text[:m.start()], re.M)] or ["?"])[-1]
            what = lambda i: W.cur[i]["result"] if i in W.cur else (f"{W.points[i].get('origin')} Point"   # noqa: E731
                                                                    if i in W.points else "unknown")
            fs.append(F("ERROR", "J08", U, f"{SOTA}: '{theme}' - its {heading} cites no "
                                            f"{'agree / boundary collision or findings Point' if heading == 'Consensus' else 'conflict / boundary collision or debate Line'}"
                                            f" (cited: {', '.join(f'{i} {what(i)}' for i in dict.fromkeys(ids)) or 'nothing'});"
                                            f" the digest lists what each Theme may cite - or write {TBD} when there is none"))
    unknown = sorted({i for i in ids_in(text) if not W.known(i)})
    if unknown:
        fs.append(F("ERROR", "J08", U, f"{SOTA}: unknown ids {unknown[:8]}"))
    themes = len(re.findall(r"^## Theme ", text, re.M))
    if W.planes and themes < len(W.planes):
        fs.append(F("ERROR", "J08", U, f"{SOTA}: {themes} '## Theme' section(s) for {len(W.planes)} Planes - one per Plane"))
    return fs


# ================================================================================================ fusion map (view)
def render_map(W: World) -> str:
    coords = (W.al.get("coords") or {})
    names = {c["id"]: c.get("name") for c in ((W.al.get("vocab") or {}).get("concepts") or [])}
    vals = lambda v: [x for x in (v if isinstance(v, list) else [v]) if x not in (None, "unstated", "n/a")]
    cell_units = defaultdict(set)
    for uid, c in coords.items():
        ax = c.get("axes") or {}
        for con in vals(ax.get("construct")) or ["-"]:
            for mea in vals(ax.get("measure")) or ["-"]:
                cell_units[(con, mea)].add(uid)
    cell_cols = defaultdict(list)
    for r in W.cur.values():
        sides = {s["id"] for s in r["sides"]}
        for cell, us in cell_units.items():
            if sides & us:
                cell_cols[cell].append(r)
    L = ["# Fusion map — construct × measure", "",
         "One row per construct × measure that some claim or assumption sits on; the cell says what the collisions found "
         "there. A view of knowledge/alignment.json and knowledge/collisions.jsonl (`ideate_tools.py fusion-map`).", "",
         "| construct | measure | papers | consensus | disputed | boundary | premises | collisions |", "|---|---|---|---|---|---|---|---|"]
    for (con, mea) in sorted(cell_units, key=lambda k: (k[0], k[1])):
        rs = cell_cols.get((con, mea), [])
        n = Counter(r["result"] for r in rs)
        papers = sorted({W.units[u]["paper"] for u in cell_units[(con, mea)] if u in W.units})
        prem = n["untested-shared"] + n["assumption-challenged"] + n["assumption-at-stake"] + n["criterion-unmet"]
        L.append(f"| {names.get(con, con)} | {names.get(mea, mea)} | {len(papers)} | {n['agree'] or ''} | {n['conflict'] or ''} | "
                 f"{n['boundary'] or ''} | {prem or ''} | {', '.join(sorted(r['collision_id'] for r in rs)) or '—'} |")
    return "\n".join(L) + "\n"


# ================================================================================================ B3.5 questions
def collision_axes(W: World, r: dict | None) -> tuple[set, set]:
    """The constructs and the measures on a collision's sides (alignment coordinates)."""
    coords = W.al.get("coords") or {}
    vals = lambda v: [x for x in (v if isinstance(v, list) else [v]) if x not in (None, "unstated", "n/a")]  # noqa: E731
    c, m = set(), set()
    for s in (r or {}).get("sides") or []:
        ax = (coords.get(s["id"]) or {}).get("axes") or {}
        c |= set(vals(ax.get("construct")))
        m |= set(vals(ax.get("measure")))
    return c, m


def prefill(W: World, gap_id: str) -> list[dict]:
    """agree / boundary collisions on the gap's coordinates - the candidates for 'already settled'."""
    g = W.gap.get(gap_id)
    if not g:
        die(f"{gap_id} is not in step7_gaps.json", 2)
    def concepts(r):
        """the constructs of a collision's sides - their measures only where no construct is stated"""
        c, m = collision_axes(W, r)
        return c or m
    own = set(g.get("collisions") or [])
    primary = W.cur.get((g.get("collisions") or [None])[0])
    mine = concepts(primary)
    out = []
    for r in W.cur.values():
        if r["result"] not in FINDING_RESULTS or r["collision_id"] in own:
            continue
        theirs = concepts(r)
        if mine & theirs:
            out.append({"collision": r["collision_id"], "result": r["result"], "reason": r["reason"],
                        "shared": sorted(mine & theirs)})
    return out


def raw_lookup(W: World, g: dict) -> dict:
    """The settled screen's `raw` lookup (question-craft §2, 6), run by code for a worker that cannot grep: the names of
    the constructs and measures on the gap's primary collision, each searched in the raw collection's titles and
    abstracts (artefact / artifact, hyphens and plurals folded), the papers holding all of them, a few shown. A miss
    shows only that the words are absent."""
    import it_align
    V = it_align.Vocab(W.al.get("vocab") or {})
    c, m = collision_axes(W, W.cur.get((g.get("collisions") or [None])[0]))
    terms = list(dict.fromkeys(str((V.concepts.get(x) or {}).get("name") or x.partition(":")[2].replace("-", " "))
                               for x in sorted(c) + sorted(m)))[:4]
    raw = W.rd / "step2_raw_papers.json"
    papers = (read_json(raw).get("papers") or []) if raw.exists() else []
    fold = lambda t: re.sub(r"[-_/]+", " ", str(t or "").lower()).replace("artefact", "artifact")   # noqa: E731
    pat = {t: re.compile(r"\b" + r"\s+".join(re.escape(w.rstrip("s")) + r"s?" for w in fold(t).split()) + r"\b")
           for t in terms}
    texts = [(p.get("id"), p.get("year"), p.get("title"), fold(f"{p.get('title')} {p.get('abstract')}")) for p in papers]
    every = [x for x in texts if terms and all(pat[t].search(x[3]) for t in terms)]
    return {"collection": f"step2_raw_papers.json: {len(papers)} papers, titles and abstracts",
            "terms": {t: sum(1 for x in texts if pat[t].search(x[3])) for t in terms}, "all_terms": len(every),
            "examples": [{"id": i, "year": y, "title": _one(ti, 120)} for i, y, ti, _ in every[:8]]}


def parse_question(text: str) -> dict:
    fm = frontmatter(text)
    screens = {}
    for line in section(text, "6. Screens").splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 3:
            continue
        for k, needle in SCREENS.items():
            if needle in cells[0].lower():
                # the result is the cell's first word: "yes (partial)" or "partly: tested only in ..." say yes / partly
                m = re.match(r"[\s*_`]*(yes|no|partly)\b", cells[1], re.I)
                screens[k] = {"result": m.group(1).lower() if m else cells[1].split(":")[0].strip().lower(),
                              "basis": " | ".join(cells[2:])}
    title = re.search(r"^# Problem and question — (.+)$", text, re.M)
    rq = section(text, "5. Research question").splitlines()
    return {"fm": fm, "screens": screens, "title": title.group(1).strip() if title else "",
            "question": rq[0].strip() if rq else ""}


def questions(rd) -> dict:
    qd = Path(rd) / QDIR
    return {f.stem: f.read_text(encoding="utf-8") for f in sorted(qd.glob("Q_*.md"))} if qd.is_dir() else {}


# ------------------------------------------------------------------------------------------------ section 9: hand-over
def handover_of(text: str):
    """The question's section 9 as a dict; None when the section is absent (a question written before it existed);
    a str naming the defect when the section is there but unreadable."""
    if not re.search(r"^## " + re.escape(HANDOVER), text, re.M):
        return None
    m = re.search(r"```(?:json)?[ \t]*\n(.*?)\n```", section(text, HANDOVER), re.S)
    if not m:
        return "section 9 holds no ```json block"
    try:
        d = json.loads(m.group(1))
    except ValueError as e:
        return f"section 9's JSON does not parse ({e})"
    return d if isinstance(d, dict) else "section 9's JSON is not an object"


def level_of(W: World, key: str) -> str:
    r = W.records.get(key) or {}
    return "abstract" if ((r.get("eligibility") or {}).get("verdict") == "abstract-only" or r.get("basis") == "abstract") \
        else "full"


def _ids(v) -> list:
    return [v] if isinstance(v, str) else [x for x in (v or []) if isinstance(x, str)]


PREMISE = {"assumption-challenged", "assumption-at-stake"}   # the #A side holds the premise, the #C side is the evidence
# (in untested-shared every side relies on the premise untested: its claims read their effects through it, so all hold it)
STRENGTH_ORDER = ("causes", "shows", "suggests", "may", "correlates")        # it_decon.STRENGTH, strongest first


def target_strength(W: World, units: list):
    """A target's strength: the source's own verb, the weakest of its claims (None when it holds assumptions only)."""
    ss = [W.units[u].get("strength") for u in units if re.search(r"#C\d+$", u) and u in W.units
          and W.units[u].get("strength") in STRENGTH_ORDER]
    return max(ss, key=STRENGTH_ORDER.index) if ss else None


def target_level(W: World, papers) -> str:
    return "abstract" if any(level_of(W, p) == "abstract" for p in papers) else "full"


def settle_handover(W: World, H: dict) -> dict:
    """Section 9's copies of the records, written by code - the model chooses the units, the collision and the accounts:
    each target's papers, strength and evidence level from its claim_units, its weakness's type and axes from the
    collision, and the ids numbered T1… and RA1… in order."""
    H = json.loads(json.dumps(H))
    targets, n = [], 0
    for t in H.get("targets") or []:
        if not isinstance(t, dict):
            targets.append(t)                  # Y11 says so
            continue
        if "unit" in t or ("overreach" in t and "claim_units" not in t):    # the schema's form (handover_schema)
            head = t.pop("unit", None) or t.get("overreach")
            t["claim_units"] = list(dict.fromkeys([head, *_ids(t.pop("also", []))]))
            t["weakness"] = {"collision": t.pop("collision")} if "collision" in t else {"overreach": t.pop("overreach")}
        n += 1
        t = {"id": f"T{n}", **{k: v for k, v in t.items() if k != "id"}}
        units = [u for u in _ids(t.get("claim_units")) if u in W.units]
        if units:
            t["papers"] = sorted({W.units[u]["paper"] for u in units})
            t["strength"] = target_strength(W, units)
            t["evidence_level"] = target_level(W, t["papers"])
        w = t.get("weakness")
        if isinstance(w, dict) and w.get("collision") in W.cur:
            r = W.cur[w["collision"]]
            w.update(type=r["result"], axes=r.get("axes_differ") or [])
        targets.append(t)
    if "targets" in H:
        H["targets"] = targets
    for i, ra in enumerate(x for x in H.get("rival_accounts") or [] if isinstance(x, dict)):
        ra["id"] = f"RA{i + 1}"
    return H


def _line_cols(W: World, lid: str) -> list:
    L = W.lines.get(lid)
    return _ids(L["fm"].get("collisions")) if L else []


def _involved(W: World, text: str, fm: dict, g: dict) -> tuple[list, set]:
    """the question's and its gap's collisions, and the papers on their sides or cited by the question's text"""
    qcols = _ids(fm.get("collisions"))
    cols = qcols + [c for c in g.get("collisions") or [] if c not in qcols]
    papers = {s["paper"] for c in cols if c in W.cur for s in W.cur[c]["sides"] if s.get("paper")}
    papers |= {i.split("#")[0] for i in ids_in(text) if "#" in i}
    return cols, papers


def handover_problems(W: World, qid: str, text: str, fm: dict, g: dict) -> list[dict]:
    """Y11 targets, Y12 rival accounts, Y13 magnitudes - checked only when section 9 exists; its absence is a WARN, so
    the questions of a topic made before it stay valid."""
    U = "B3.5"
    H = handover_of(text)
    if H is None:
        return [F("WARN", "Y11", U, f"{qid}: no '## {HANDOVER}' section - the planning block then has no attack targets, "
                                     "rival accounts or magnitudes from the fusion records (questions-handover)")] \
            if fm.get("status") == "ready" else []
    if isinstance(H, str):
        return [F("ERROR", "Y11", U, f"{qid}: {H}")]
    fs = []
    # ---- Y11 targets: a sentence a paper holds, and the collision it loses (or stands untested) in
    T = H.get("targets")
    if not isinstance(T, list) or not 1 <= len(T) <= 5:
        fs.append(F("ERROR", "Y11", U, f"{qid}: section 9 `targets` is a list of 1-5 attack targets"))
        T = []
    seen = set()
    for t in T:
        t = t if isinstance(t, dict) else {}
        tid = str(t.get("id"))
        if not re.fullmatch(r"T\d+", tid) or tid in seen:
            fs.append(F("ERROR", "Y11", U, f"{qid}: target id {tid!r} - T1, T2, … each once"))
        seen.add(tid)
        units = _ids(t.get("claim_units"))
        papers = set(_ids(t.get("papers")))
        bad = [u for u in units if u not in W.units or not TARGET_UNIT.search(u)]
        if not units or bad:
            fs.append(F("ERROR", "Y11", U, f"{qid} {tid}: claim_units name existing claims or assumptions (#C / #A) of the "
                                            f"deconstruction records (bad: {bad or 'none given'})"))
            continue
        if {W.units[u]["paper"] for u in units} != papers:
            fs.append(F("ERROR", "Y11", U, f"{qid} {tid}: papers {sorted(papers)} are not the papers of its claim_units"))
        want = target_strength(W, units)
        if t.get("strength") != want:
            fs.append(F("ERROR", "Y11", U, f"{qid} {tid}: strength is {want!r} - the source's own verb, the weakest of its "
                                            f"claims when it bundles several (null for assumptions only), not "
                                            f"{t.get('strength')!r}"))
        w = t.get("weakness") if isinstance(t.get("weakness"), dict) else {}
        if w.get("overreach"):
            ou = w["overreach"]
            if ou not in units or not str(W.units.get(ou, {}).get("overreach") or "").strip():
                fs.append(F("ERROR", "Y11", U, f"{qid} {tid}: weakness overreach {ou!r} is not one of its units marked "
                                                "`overreach` in the deconstruction"))
        else:
            c = w.get("collision")
            r = W.cur.get(c)
            if not r or r["result"] not in COVER:
                fs.append(F("ERROR", "Y11", U, f"{qid} {tid}: weakness.collision {c!r} is a current conflict, boundary or "
                                                f"premise collision (one of {sorted(COVER)})"))
            else:
                if w.get("type") != r["result"]:
                    fs.append(F("ERROR", "Y11", U, f"{qid} {tid}: weakness.type {w.get('type')!r} is the collision's result "
                                                    f"({r['result']!r})"))
                if "axes" in w and sorted(_ids(w.get("axes"))) != sorted(r.get("axes_differ") or []):
                    fs.append(F("ERROR", "Y11", U, f"{qid} {tid}: weakness.axes {w.get('axes')} are not {c}'s axes_differ "
                                                    f"{r.get('axes_differ')}"))
                on = {s["id"] for s in r["sides"]} & set(units)
                if not on:
                    fs.append(F("ERROR", "Y11", U, f"{qid} {tid}: none of its claim_units is on a side of {c} - a target "
                                                    "is the side that loses or stands untested, not the evidence against it"))
                elif r["result"] in PREMISE and not [u for u in on if re.search(r"#A\d+$", u)]:
                    fs.append(F("ERROR", "Y11", U, f"{qid} {tid}: in a {r['result']} collision the target holds the premise "
                                                    f"(an #A unit on a side); {sorted(on)} are the evidence against it"))
        lvl = target_level(W, papers)
        if t.get("evidence_level") != lvl:
            fs.append(F("ERROR", "Y11", U, f"{qid} {tid}: evidence_level is {lvl!r} (the papers' deconstruction basis), "
                                            f"not {t.get('evidence_level')!r}"))
        if not str(t.get("holds") or "").strip():
            fs.append(F("ERROR", "Y11", U, f"{qid} {tid}: `holds` says in one line what the target holds, at its strength"))
    # ---- Y12 rival accounts of the condition, on the axes the question does not vary
    varies = _ids(H.get("varies"))
    if not varies:
        fs.append(F("ERROR", "Y12", U, f"{qid}: section 9 `varies` names the axis (an axes_differ code) the question varies"))
    else:
        cols, _ = _involved(W, text, fm, g)
        on = {a for c in cols if c in W.cur for a in W.cur[c].get("axes_differ") or []}
        if set(varies) - on:
            fs.append(F("WARN", "Y12", U, f"{qid}: varies {sorted(set(varies) - on)} is an axis none of the question's or "
                                           f"its gap's collisions differ on ({sorted(on)}) - check that the question really "
                                           "varies it"))
    R = H.get("rival_accounts")
    if not isinstance(R, list) or not R:
        fs.append(F("ERROR", "Y12", U, f"{qid}: section 9 `rival_accounts` lists the competing explanations of the "
                                        "condition (questions-handover lists the differing axes and debate Lines)"))
        R = []
    seen = set()
    for ra in R:
        ra = ra if isinstance(ra, dict) else {}
        rid = str(ra.get("id"))
        if not re.fullmatch(r"RA\d+", rid) or rid in seen:
            fs.append(F("ERROR", "Y12", U, f"{qid}: rival account id {rid!r} - RA1, RA2, … each once"))
        seen.add(rid)
        basis = _ids(ra.get("basis"))
        if not str(ra.get("account") or "").strip():
            fs.append(F("ERROR", "Y12", U, f"{qid} {rid}: the account in one sentence"))
            continue
        if not basis:
            if str(ra.get("unrecorded") or "").strip():
                fs.append(F("WARN", "Y12", U, f"{qid} {rid}: no record behind this account ({ra['unrecorded']}) - the "
                                               "planning block treats it as the study's own conjecture"))
            else:
                fs.append(F("ERROR", "Y12", U, f"{qid} {rid}: a basis of collision, Line or gap ids - or `unrecorded` with "
                                                "why no record exists"))
            continue
        wrong = [b for b in basis if not (b in W.cur or b in W.lines or b in W.gap)]
        if wrong:
            fs.append(F("ERROR", "Y12", U, f"{qid} {rid}: basis {wrong} - only collision (X…), Line (D_/E_/A_draft_…) or "
                                            "gap (GAP_…, its counter-evidence) ids"))
            continue
        ax = ra.get("axis")
        if ax:
            cols = [b for b in basis if b in W.cur] + [c for b in basis for c in _line_cols(W, b)]
            free = sorted({a for c in cols if c in W.cur for a in W.cur[c].get("axes_differ") or []} - set(varies) - {"none"})
            if ax in varies:
                fs.append(F("ERROR", "Y12", U, f"{qid} {rid}: axis {ax!r} is the one the question varies ({varies}) - a "
                                                "rival account explains the condition by another axis: "
                                                + (f"one of {free}, or leave `axis` out" if free else
                                                   "its basis differs on no other, so leave `axis` out")
                                                + " (an account with no axis of its own: the other side of a debate, "
                                                "a mechanism)"))
            if cols and not any(ax in (W.cur[c].get("axes_differ") or []) for c in cols if c in W.cur):
                fs.append(F("ERROR", "Y12", U, f"{qid} {rid}: axis {ax!r} is not an axis on which its basis collisions "
                                                "(or its Lines' collisions) differ"))
    # ---- Y13 magnitudes the planning block can predict and power with
    M = H.get("magnitudes")
    if M != NO_NUMBER:
        if not isinstance(M, list) or not M:
            fs.append(F("ERROR", "Y13", U, f"{qid}: section 9 `magnitudes` lists reported numbers (exp_id, value) or is "
                                            f"{NO_NUMBER!r}"))
        else:
            rows = [m if isinstance(m, dict) else {} for m in M]
            bad = [m.get("exp_id") for m in rows if m.get("exp_id") not in W.rows or not str(m.get("value") or "").strip()
                   or m.get("relation", "same") not in ("same", "neighbour")]
            if bad:
                fs.append(F("ERROR", "Y13", U, f"{qid}: magnitudes {bad} - each an existing matrix row (exp_id) with its "
                                                "value, `relation` same | neighbour"))
            elif all(m.get("relation") == "neighbour" for m in rows) and not str(H.get("magnitude_absent") or "").strip():
                fs.append(F("ERROR", "Y13", U, f"{qid}: every magnitude is a neighbouring coordinate's - say in "
                                                "`magnitude_absent` which number has never been reported"))
            _, papers = _involved(W, text, fm, g)
            off = [m["exp_id"] for m in rows if m.get("exp_id") in W.rows and m["exp_id"].split("#")[0] not in papers]
            if off:
                fs.append(F("WARN", "Y13", U, f"{qid}: magnitudes {off} come from papers on none of the question's "
                                               "collisions and not cited by it - say why they bear on it"))
    return fs


def _role(uid: str, result: str) -> str:
    if result == "untested-shared":
        return "holder"
    if result in PREMISE:
        return "holder" if re.search(r"#A\d+$", uid) else "challenger"
    return "side"


TARGET_FULLTEXT_CAP = 5        # PLAN_ideate_planning P-D13: per topic


def abstract_targets(rd) -> list[dict]:
    """The papers that the questions' section 9 attack on an abstract only (F-M4), most needed first: a first target
    (T1, or the lowest-numbered) before the rest, then by how many questions attack it."""
    seen = {}
    for qid, text in questions(rd).items():
        H = handover_of(text)
        if not isinstance(H, dict):
            continue
        for i, t in enumerate(H.get("targets") or []):
            if not isinstance(t, dict) or t.get("evidence_level") != "abstract":
                continue
            for k in _ids(t.get("papers")):
                e = seen.setdefault(k, {"key": k, "questions": [], "first": False})
                e["questions"].append(f"{qid}:{t.get('id')}")
                e["first"] = e["first"] or i == 0
    return sorted(seen.values(), key=lambda e: (not e["first"], -len(e["questions"]), e["key"]))


def handover_candidates(W: World, qid: str) -> dict:
    """What section 9 may hold, one entry per unit: the units on the sides of the question's (then its gap's) conflict,
    boundary and premise collisions and the other such collisions they sit in (`role`: holder of a premise, challenger,
    or a side of a conflict / boundary); the claims of the papers involved that sit in no such collision (to be bundled
    with the premise they ride on); the differing axes, the debate Lines, the gap's counter-evidence and the matrix rows
    of the papers involved or cited by the question. The model chooses and writes section 9."""
    p = W.rd / QDIR / f"{qid}.md"
    if not p.exists():
        die(f"{p} not found", 2)
    text = p.read_text(encoding="utf-8")
    fm = parse_question(text)["fm"]
    g = W.gap.get(fm.get("gap")) or {}
    cols, papers = _involved(W, text, fm, g)
    qcols = set(_ids(fm.get("collisions")))
    cited = set(ids_in(text))
    by_unit, axes = {}, defaultdict(list)

    def add(uid, c, r):
        u = W.units[uid]
        e = by_unit.setdefault(uid, {"unit": uid, "paper": u["paper"], "kind": u.get("kind"), "strength": u.get("strength"),
                                     "text": u.get("text"), "overreach": u.get("overreach"),
                                     "evidence_level": level_of(W, u["paper"]), "cited_in_question": uid in cited,
                                     "collisions": []})
        if c and c not in [x["id"] for x in e["collisions"]]:
            e["collisions"].append({"id": c, "result": r["result"], "axes": r.get("axes_differ") or [],
                                    "on_question": c in qcols, "role": _role(uid, r["result"])})

    for c in cols:
        r = W.cur.get(c)
        if not r or r["result"] not in COVER:
            continue
        for ax in r.get("axes_differ") or []:
            if ax != "none":
                axes[ax].append(c)
        for s in r["sides"]:
            if s["id"] in W.units and TARGET_UNIT.search(s["id"]):
                add(s["id"], c, r)
    also = []
    held = set(by_unit)
    for c, r in sorted(W.cur.items()):
        if c in cols or r["result"] not in COVER:
            continue
        for s in r["sides"]:
            if s["id"] in held:
                add(s["id"], c, r)
                also.append(c)
    # claims that no conflict / boundary / premise collision holds but that the question reaches: cited by it, of a paper on
    # one of the question's own collisions, or tied by an `extends` lineage to a unit above (how a premise is carried forward)
    holders = {e["paper"] for e in by_unit.values() if any(x["role"] == "holder" for x in e["collisions"])}
    in_cover = {s["id"] for r in W.cur.values() if r["result"] in COVER for s in r["sides"]}
    loose = []
    for uid, u in sorted(W.units.items()):
        if uid in by_unit or uid in in_cover or not re.search(r"#C\d+$", uid):
            continue
        ext = sorted(c for c, r in W.cur.items() if r["result"] == "extends" and uid in {s["id"] for s in r["sides"]})
        linked = [c for c in ext if {s["id"] for s in W.cur[c]["sides"]} & held]
        # a claim the question cites, a claim of a paper whose premise the question holds, or one an extends lineage
        # ties to a unit above (how a premise is carried forward)
        if uid not in cited and u["paper"] not in holders and not linked:
            continue
        loose.append({"unit": uid, "paper": u["paper"], "strength": u.get("strength"), "text": u.get("text"),
                      "overreach": u.get("overreach"), "evidence_level": level_of(W, u["paper"]),
                      "cited_in_question": uid in cited, "extends": ext})
    lines = []
    for lid, L in sorted(W.lines.items()):
        lc = set(_ids(L["fm"].get("collisions"))) & (set(cols) | set(also))
        if lc:
            lines.append({"line": lid, "relation": L["fm"].get("relation_type"), "collisions": sorted(lc)})
    rows = []
    for k in sorted(papers):
        for e in (W.records.get(k) or {}).get("experiments") or []:
            rows.append({"exp_id": e["exp_id"], "headline": e.get("headline"), "stats": e.get("stats"),
                         "n": [d.get("n") for d in e.get("data") or [] if isinstance(d, dict)], "metrics": e.get("metrics"),
                         "cited_in_question": e["exp_id"] in cited})
    return {"at": now_iso(), "question": qid, "collisions": cols, "question_axes": _ids(fm.get("axes")),
            "targets": sorted(by_unit.values(), key=lambda e: (not any(x["on_question"] for x in e["collisions"]), e["unit"])),
            "claims_without_collision": sorted(loose, key=lambda e: (not e["cited_in_question"], not e["extends"], e["unit"])),
            "axes": [{"axis": a, "collisions": cs} for a, cs in sorted(axes.items())], "debate_lines": lines,
            "gap_counter": g.get("counter") or [], "magnitudes": rows}


def q_problems(W: World) -> list[dict]:
    U = "B3.5"
    fs = []
    qs = questions(W.rd)
    if not qs:
        return [F("ERROR", "Y01", U, "no questions/Q_*.md (B3.5)")]
    per_gap = defaultdict(list)
    lens = read_json(W.rd / "lens.json") if (W.rd / "lens.json").exists() else {}
    own = {f"own:{d.get('name')}" for d in lens.get("own_data") or []}
    for qid, text in qs.items():
        P = parse_question(text)
        fm = P["fm"]
        g = W.gap.get(fm.get("gap"))
        if fm.get("question") != qid or not re.fullmatch(r"Q_\d{3}", qid) or not g or fm.get("study") not in ("analytic", "descriptive") \
                or fm.get("status") not in Q_STATUS:
            fs.append(F("ERROR", "Y01", U, f"{qid}: frontmatter needs question (= file name), gap (in step7_gaps.json), "
                                            f"study analytic|descriptive, status {Q_STATUS}"))
            continue
        if fm.get("move") != g.get("move"):
            fs.append(F("ERROR", "Y01", U, f"{qid}: move {fm.get('move')!r} differs from {g['id']}'s ({g.get('move')!r})"))
        qax = fm.get("axes") or []
        qax = [qax] if isinstance(qax, str) else qax
        if g.get("axes") and set(qax) - set(g["axes"]):
            fs.append(F("ERROR", "Y01", U, f"{qid}: axes {sorted(set(qax) - set(g['axes']))} are not the gap's {g['axes']} - "
                                            "a question takes some of its gap's axes"))
        per_gap[g["id"]].append((qid, fm))
        fs += handover_problems(W, qid, text, fm, g)
        missing = [s for s in Q_SECTIONS if not re.search(r"^## " + re.escape(s), text, re.M)]
        if missing:
            fs.append(F("ERROR", "Y02", U, f"{qid}: sections missing: {missing}"))
            continue
        s1 = section(text, "1. Common ground")
        ok1 = [i for i in ids_in(s1) if (i in W.cur and W.cur[i]["result"] in COMMON_GROUND) or
               (i in W.points and W.points[i].get("origin") == "collide")]
        if not ok1 and TBD not in s1:
            fs.append(F("ERROR", "Y03", U, f"{qid}: common ground cites no agree / boundary / untested-shared collision "
                                            "or findings Point (what the field holds or routinely does)"))
        s2 = section(text, "2. Condition")
        own_ids = set(g.get("collisions") or []) | set(g.get("not_done") or [])
        if not set(ids_in(s2)) & own_ids:
            fs.append(F("ERROR", "Y04", U, f"{qid}: the condition cites none of {g['id']}'s collisions {sorted(own_ids)}"))
        fmc = fm.get("collisions") or []
        fmc = [fmc] if isinstance(fmc, str) else fmc
        if not fmc or set(fmc) - own_ids:
            fs.append(F("ERROR", "Y04", U, f"{qid}: frontmatter `collisions` = the gap's collisions the question rests on "
                                            f"(a subset of {sorted(own_ids)})"))
        for line in section(text, "3. Consequence").splitlines():
            if "evidence:" in line:
                ev = line.split("evidence:", 1)[1]
                if TBD not in ev and not ids_in(ev):
                    fs.append(F("ERROR", "Y05", U, f"{qid}: a ladder rung cites no evidence id (or {TBD}): {line.strip()[:80]}"))
                notes = [i for i in ids_in(ev) if re.search(r"#N\d+$", i)]
                if notes:
                    fs.append(F("ERROR", "Y05", U, f"{qid}: {notes} are reading-note observations, not evidence that "
                                                    "anyone else asks the question (question-craft §2.2)"))
        unknown = sorted({i for i in ids_in(text) if not W.known(i)})
        if unknown:
            fs.append(F("ERROR", "Y05", U, f"{qid}: unknown ids {unknown[:6]}"))
        sc = P["screens"]
        if set(sc) != set(SCREENS):
            fs.append(F("ERROR", "Y06", U, f"{qid}: the screens table needs the four screens ({sorted(set(SCREENS) - set(sc))} missing)"))
            continue
        passed = all(sc[k]["result"] in SCREEN_PASS[k] for k in SCREENS)
        if fm["status"] == "ready" and not passed:
            fs.append(F("ERROR", "Y06", U, f"{qid}: status ready but a screen fails: "
                                            f"{[k for k in SCREENS if sc[k]['result'] not in SCREEN_PASS[k]]}"))
        if fm["status"] == "abandoned" and not str(fm.get("abandoned_reason") or "").strip():
            fs.append(F("ERROR", "Y06", U, f"{qid}: abandoned without abandoned_reason"))
        pre = [x["collision"] for x in prefill(W, g["id"])]
        # the weighing may sit in a section of its own when the list is long
        basis = sc["settled"]["basis"] + " " + section(text, "6a. Settled-screen detail")
        unweighed = [c for c in pre if c not in basis]
        if unweighed:
            fs.append(F("ERROR", "Y06", U, f"{qid}: the settled screen must weigh each agree / boundary collision on these "
                                            f"coordinates (questions-prefill); not mentioned: {unweighed[:6]}"))
        if not pre and "no agree" not in basis.lower():
            fs.append(F("ERROR", "Y06", U, f"{qid}: the settled screen says what questions-prefill found "
                                            "('no agree / boundary collision on these coordinates')"))
        dbasis = sc["data"]["basis"]
        if not re.search(r"lens:[\w:-]+", dbasis) and not any(o in dbasis for o in own):
            fs.append(F("ERROR", "Y10", U, f"{qid}: the data screen cites the lens (lens:<concept>) or own data (own:<name>)"))
    for gid, qq in per_gap.items():
        if len(qq) > 2:
            fs.append(F("ERROR", "Y07", U, f"{gid}: {len(qq)} questions - at most 2 per gap"))
        if len(qq) == 2:
            (a, fa), (b, fb) = qq
            if sorted(fa.get("axes") or []) == sorted(fb.get("axes") or []):
                fs.append(F("ERROR", "Y07", U, f"{gid}: {a} and {b} share their axes - two questions on one gap differ in axes "
                                                "(the move is the gap's)"))
    return fs


def target(rd) -> int:
    cfg = _cfg(rd)
    return max(int(cfg.get("max_num_generations") or 3), 3) + 2


def _handover_keys(text: str) -> dict:
    """section 9's three lists, only when the section exists - an index of older questions stays byte-identical (Y08)"""
    H = handover_of(text)
    if not isinstance(H, dict):
        return {}
    return {k: H.get(k) for k in ("targets", "rival_accounts", "magnitudes", "varies", "magnitude_absent")
            if k in ("targets", "rival_accounts", "magnitudes") or H.get(k)}


def build_index(W: World) -> dict:
    ranked = (W.gaps.get("ranked") or [])
    items = []
    for qid, text in questions(W.rd).items():
        P = parse_question(text)
        fm = P["fm"]
        g = W.gap.get(fm.get("gap")) or {}
        items.append({"id": qid, "gap": fm.get("gap"), "gap_rank": ranked.index(g["id"]) + 1 if g.get("id") in ranked else None,
                      "status": fm.get("status"), "move": fm.get("move"), "axes": fm.get("axes") or [],
                      "study": fm.get("study"), "collisions": fm.get("collisions") or g.get("collisions") or [],
                      "title": P["title"], "research_question": P["question"],
                      "screens": {k: v["result"] for k, v in P["screens"].items()},
                      **{k: fm[k] for k in ("abandoned_reason", "narrowed", "original_question") if fm.get(k)},
                      **_handover_keys(text)})
    items.sort(key=lambda x: (x["status"] != "ready", x["gap_rank"] or 999, x["id"]))
    ready = [x for x in items if x["status"] == "ready"]
    covered = {x["gap"] for x in items}
    return {"at": now_iso(), "target_ready": target(W.rd),
            "target_basis": "max(step0 max_num_generations, 3) + 2" if _cfg(W.rd).get("max_num_generations") else
            "default: max_num_generations not in step0, so 3 + 2", "ready": len(ready), "questions": items,
            "gaps_without_question": [g for g in ranked if g not in covered]}


def index_problems(W: World) -> list[dict]:
    U = "F.9"
    p = W.rd / INDEX
    if not p.exists():
        return [F("ERROR", "Y08", U, f"{INDEX} missing (questions-index)")]
    old = read_json(p)
    new = build_index(W)
    strip = lambda d: {k: v for k, v in d.items() if k != "at"}
    fs = []
    if strip(old) != strip(new):
        fs.append(F("ERROR", "Y08", U, f"{INDEX} is not the index of questions/ (a question changed since) - questions-index"))
    if new["ready"] < new["target_ready"] and new["gaps_without_question"]:
        fs.append(F("WARN", "Y09", U, f"{new['ready']} ready question(s) of the {new['target_ready']} wanted, and ranked gaps "
                                       f"without a question remain: {new['gaps_without_question'][:5]}"))
    if not new["ready"] and not any(q["status"] == "screen_unresolved" for q in new["questions"]):
        fs.append(F("ERROR", "Y09", U, "no ready question and none kept as screen_unresolved - keep the one that failed the "
                                        "fewest screens (research-cycle §3.5)"))
    mp = W.rd / MAP
    if not mp.exists() or mp.read_text(encoding="utf-8") != render_map(W):
        fs.append(F("ERROR", "J10", U, f"{MAP} is not the rendering of the alignment and the collisions - fusion-map"))
    return fs


# ================================================================================================ hand-over to planning
def question_meta(rd, qid: str) -> dict:
    p = Path(rd) / QDIR / f"{qid}.md"
    if not p.exists():
        die(f"{p} not found", 2)
    P = parse_question(p.read_text(encoding="utf-8"))
    fm = P["fm"]
    axes = fm.get("axes") or []
    axes = [axes] if isinstance(axes, str) else axes
    return {"id": qid, "gap": fm.get("gap"), "status": fm.get("status"), "axes": axes, "move": fm.get("move"),
            "collisions": fm.get("collisions") or [], "title": P["title"],
            "angle": (", ".join(axes) or "-") + " — " + P["title"]}


def consumed(rd) -> list[dict]:
    p = Path(rd) / "step0_session_config.json"
    return (read_json(p) if p.exists() else {}).get("consumed", [])


def next_question(rd) -> tuple[dict | None, list[dict]]:
    """The planning block's pick: a ready question nobody consumed; among them, prefer a gap no idea used, then axes no
    idea on that gap used, then a gap no idea borrowed from (also_uses); then the index order (gap rank)."""
    p = Path(rd) / INDEX
    if not p.exists():
        die(f"{p} not found - the fusion block hands over questions/index.json (questions-index)", 2)
    idx = read_json(p)
    # only entries that consumed a question: an older entry names a gap of the old per-generation analysis, whose ids
    # (GAP_001…) mean other gaps than the fusion block's list - a topic copied onto the block inherits them
    every = [e for e in consumed(rd) if e.get("question")]
    taken = {e.get("question") for e in every}                     # consumed or abandoned: never taken again
    led = [e for e in every if e.get("status") != "abandoned"]     # only ideas that were made steer the diversity
    gaps_used = {e.get("gap") for e in led}
    borrowed = {g for e in led for g in e.get("also_uses") or []}
    axes_used = defaultdict(set)
    for e in led:
        if e.get("question"):
            axes_used[e["gap"]].add(tuple(sorted(question_meta(rd, e["question"])["axes"])))
    pool = [q for q in idx["questions"] if q["status"] == "ready" and q["id"] not in taken]
    if not pool:
        pool = [q for q in idx["questions"] if q["status"] == "screen_unresolved" and q["id"] not in taken]
    scored = sorted(pool, key=lambda q: (q["gap"] in gaps_used, tuple(sorted(q.get("axes") or [])) in axes_used[q["gap"]],
                                         q["gap"] in borrowed, q.get("gap_rank") or 999, q["id"]))
    return (scored[0] if scored else None), scored


def take(rd, qid: str, gen: int | None = None) -> Path:
    """Copy a question into a new generation as its step7b_problem.md (B5 may revise that copy; the topic's question
    file is never edited by the planning block) and leave gen_k/question.json behind."""
    rd = Path(rd)
    meta = question_meta(rd, qid)
    if meta["status"] not in ("ready", "screen_unresolved"):
        die(f"{qid} is {meta['status']} - take a ready question (question-next)", 1)
    if any(e.get("question") == qid for e in consumed(rd)):
        die(f"{qid} is already consumed", 1)
    gens = sorted(int(g.name.split("_")[1]) for g in rd.glob("gen_*") if g.name.split("_")[1].isdigit())
    k = gen or ((gens[-1] + 1) if gens else 1)
    gd = rd / f"gen_{k}"
    if (gd / "step7b_problem.md").exists():
        die(f"{gd}/step7b_problem.md exists - this generation already has its question", 1)
    src = (rd / QDIR / f"{qid}.md").read_text(encoding="utf-8")
    copy = src.replace("---\n", f"---\ngeneration: {k}\nsource_question: {QDIR}/{qid}.md\n", 1)
    write_text(gd / "step7b_problem.md", copy)
    lens = rd / "lens.json"
    cfg = _cfg(rd)
    stale = bool(lens.exists() and (read_json(lens).get("local") or {}).get("date") !=
                 ((cfg.get("local_environment") or {}).get("probe") or {}).get("date"))
    write_json(gd / "question.json", {"question": qid, "gap": meta["gap"], "axes": meta["axes"], "angle": meta["angle"],
                                      "move": meta["move"],
                                      "collisions": meta["collisions"], "taken_at": now_iso(),
                                      "lens_stale": stale, "handover": bool(_handover_keys(src)), **_handover_keys(src)})
    return gd


# ================================================================================================ commands
def run_checks(rd, unit="all") -> list[dict]:
    W = World(rd)
    fs = []
    if unit in ("all", "A7.R1"):
        fs += r1_problems(W)
    if unit in ("all", "A7.R2"):
        fs += r2_problems(W) + coverage_problems(W)
    if unit in ("all", "A7.R3"):
        fs += r3_problems(W)
    if unit in ("all", "B2"):
        fs += b2_problems(W)
    if unit in ("all", "B3.5"):
        fs += q_problems(W)
    if unit in ("all", "F.9"):
        fs += index_problems(W)
    return fs


def _print(fs, as_json=False):
    if as_json:
        print(json.dumps(fs, indent=2, ensure_ascii=False))
        return
    for f in fs:
        print(f"  {f['level']:<5} {f['code']} [{f['unit']}] {f['msg']}")


def cmd_candidates(a):
    rd = Path(a.research_dir)
    out = promotion(World(rd))
    write_json(rd / WORK / "promotion.json", out)
    print(f"recon-candidates: {len(out['debates'])} debate group(s), {len(out['evolution'])} evolution chain(s), "
          f"{len(out['analogy'])} analogy(ies), {len(out['findings'])} findings group(s) -> {WORK}/promotion.json")


def cmd_map(a):
    rd = Path(a.research_dir)
    write_text(rd / MAP, render_map(World(rd)))
    print(f"fusion-map: -> {MAP}")


def cmd_prefill(a):
    rd = Path(a.research_dir)
    out = prefill(World(rd), a.gap)
    write_json(rd / "knowledge" / "_work" / "B35" / f"prefill_{a.gap}.json", out)
    if not out:
        print(f"questions-prefill {a.gap}: no agree / boundary collision on these coordinates")
    for x in out:
        print(f"  {x['collision']} ({x['result']}, on {', '.join(x['shared'])}): {x['reason']}")


# ---- B3.5 for a worker that cannot run commands: the conductor runs prefill / handover around two fan-outs
B35 = "knowledge/_work/B35"


def question_target(rd) -> int:
    cfg = read_json(Path(rd) / "step0_session_config.json") if (Path(rd) / "step0_session_config.json").exists() else {}
    return max(int(cfg.get("max_num_generations") or 3), 3) + 2


S9_CODES = ("Y11", "Y12", "Y13")
TEXT_MAX = 300                  # section 9's one-line texts (holds, account): characters, said in the task too          # section 9's checks; the rest are the question's sections 1-8


def question_refusals(W: World) -> dict[str, dict[str, list[str]]]:
    """Each question's ERRORs, split into its sections 1-8 (`body`) and its section 9 (`s9`): what the next round asks
    again, with why."""
    out: dict = {}
    for f in q_problems(W):
        qid = f["msg"].split()[0].rstrip(":")
        if f["level"] == "ERROR" and re.fullmatch(r"Q_\d{3}", qid):
            out.setdefault(qid, {"body": [], "s9": []})["s9" if f["code"] in S9_CODES else "body"].append(
                f"{f['code']} {f['msg']}")
    return out


def must_cite(W: World, g: dict, pre: list[dict], basis: list[str]) -> dict:
    """What each part of a question has to cite for the checks, worked out by code so the model only writes: section 1's
    common ground (Y03), section 2's own collisions (Y04), the settled screen's weighing (Y06), the data screen's lens
    ids (Y10)."""
    papers = {x.get("key") for x in (g.get("supporting") or []) + (g.get("counter") or []) if isinstance(x, dict)}
    papers |= {x.get("paper") for c in g.get("collisions") or [] if c in W.cur for x in W.cur[c]["sides"]}
    common = sorted({c for c, r in W.cur.items() if r["result"] in COMMON_GROUND and
                     {x.get("paper") for x in r.get("sides") or []} & papers} | {x["collision"] for x in pre})
    common += sorted(i for i, pt in W.points.items() if pt.get("origin") == "collide" and
                     {pt.get("source"), *(pt.get("also_in") or [])} & papers)
    own = sorted(set(g.get("collisions") or []) | set(g.get("not_done") or []))
    return {"1. Common ground (at least one; an independent collision or an align Point is not common ground)":
                common or f"{TBD} - no agree / boundary / untested-shared collision or findings Point on this gap's papers",
            "2. Condition (at least one)": own,
            "frontmatter collisions (a subset)": sorted(g.get("collisions") or []),
            "6. Screens - already settled (basis)": [f"weigh each: {x['collision']}" for x in pre] or
                ["write: no agree / boundary collision on these coordinates (questions-prefill found none)"]
                + ["the raw lookup (`raw_lookup`): its terms and hit counts, run by the conductor",
                   "the matrix rows (`matrix_rows`): their headlines - claim_tested is (TBD) where the record left it"],
            "6. Screens - data on this machine (basis cites at least one)": basis}


def _qnum(qid: str) -> int:
    return int(qid.split("_")[1])


def cmd_questions_plan(a):
    """One batch per question to write, in gap rank order: a question for each gap still without one (the target ready
    count, plus two spares), and each question the checks refused, again - its file moved to previous/ (shown to the
    model) with why. A batch holds the gap, its prefill (the already-settled screen), its collisions, its lens verdicts
    (the gap's feasibility basis), its papers' matrix rows and what each section must cite - ids with one line each."""
    rd = Path(a.research_dir)
    wd = rd / B35
    prev = wd / "previous"
    for old in [*wd.glob("q_batch_*.json"), *(wd / "schemas").glob("q_batch_*.json")]:
        old.unlink()
    for f in prev.glob("Q_*.md") if prev.is_dir() else []:      # a rewrite that never came back: the question returns
        if not (rd / QDIR / f.name).exists():
            write_text(rd / QDIR / f.name, f.read_text(encoding="utf-8"))
    W = World(rd)
    refused = {q: r["body"] for q, r in question_refusals(W).items() if r["body"]} if questions(rd) else {}
    have = {}
    for qid, text in questions(rd).items():
        have.setdefault(parse_question(text)["fm"].get("gap"), qid)
    lens = read_json(rd / "lens.json") if (rd / "lens.json").exists() else {}
    on = lens.get("on_coords") or {}
    nums = [_qnum(q) for q in questions(rd)] + [_qnum(f.stem) for f in prev.glob("Q_*.md")] if prev.is_dir() else \
        [_qnum(q) for q in questions(rd)]
    n = max(nums, default=0)
    todo = [(have[g], g) for g in have if have[g] in refused and g in W.gap]
    for gid in (W.gaps.get("ranked") or [g["id"] for g in W.gaps.get("gaps") or []])[:question_target(rd) + 2]:
        if gid not in have and gid in W.gap:
            n += 1
            todo.append((f"Q_{n:03d}", gid))
    made = []
    for qid, gid in todo:
        g = W.gap[gid]
        keys = sorted({x.get("key") for x in (g.get("supporting") or []) + (g.get("counter") or []) if isinstance(x, dict)})
        rows = [{"exp_id": e.get("exp_id"), "headline": _one(e.get("headline"), 120), "stats": _one(e.get("stats"), 80),
                 "metrics": e.get("metrics"), "n": [d.get("n") for d in e.get("data") or [] if isinstance(d, dict)]}
                for k in keys for e in (W.records.get(k) or {}).get("experiments") or []]
        cols = [{"id": c, "result": W.cur[c]["result"], "axes": W.cur[c].get("axes_differ"),
                 "sides": [x.get("id") for x in W.cur[c].get("sides") or []], "reason": _one(W.cur[c].get("reason"), 200)}
                for c in g.get("collisions") or [] if c in W.cur]
        basis = [x for x in g.get("feasibility_basis") or [] if str(x).startswith("own:") or str(x)[5:] in on]
        lens_c = {c: {k: _one(v, 140) for k, v in (x or {}).items()} for c, x in on.items()
                  if not basis or f"lens:{c}" in basis}
        pre = prefill(W, gid)
        sides = lambda c: [{"id": x.get("id"), "paper": x.get("paper"), "quote": _one(x.get("quote"), 200)}   # noqa: E731
                           for x in W.cur[c].get("sides") or []]
        b = {"question": qid, "out": f"{QDIR}/{qid}.md",
             "frontmatter": {"question": qid, "gap": gid, "move": g.get("move"), "date": now_iso()[:10]},
             "gap": g, "must_cite": must_cite(W, g, pre, basis or ["a lens:<concept> id from `lens` that the question's data needs"]),
             "prefill": [{**x, "sides": sides(x["collision"])} for x in pre], "raw_lookup": raw_lookup(W, g),
             "gap_collisions": cols, "lens": lens_c, "own_data": lens.get("own_data") or [], "matrix_rows": rows[:60]}
        if qid in refused:
            write_text(prev / f"{qid}.md", (rd / QDIR / f"{qid}.md").read_text(encoding="utf-8"))
            (rd / QDIR / f"{qid}.md").unlink()
            b.update(previous=f"{B35}/previous/{qid}.md", refused_before=refused[qid][:12])
        write_json(wd / f"q_batch_{qid}.json", b)
        made.append((gid, qid, qid in refused))
    print(f"questions-plan: {len(made)} question(s) to write -> {B35}/q_batch_*.json"
          + "".join(f"\n  {g} -> {q}" + (" (again: refused)" if again else "") for g, q, again in made))


def handover_schema(W: World, cand: dict, gap_id: str | None) -> dict:
    """Section 9's answer, for a worker whose answer is decoded under a schema: the choices from the question's own
    candidates - target units, weakness collisions or overreach units, rival-account bases and axes, magnitude rows. The
    copies of the records (papers, strength, evidence level, the weakness's type and axes, the ids) are settle_handover's.
    Texts and lists have a ceiling: under a schema a free string had no end, and one `holds` ran to num_predict."""
    import it_collide
    txt = lambda n: {"type": "string", "maxLength": n}                                         # noqa: E731
    one = lambda xs: {"enum": sorted(set(xs)) or [""]}                                         # noqa: E731
    arr = lambda item, **kw: {"type": "array", "items": item, **kw}                            # noqa: E731
    obj = lambda props, req: {"type": "object", "additionalProperties": False, "properties": props,  # noqa: E731
                              "required": req}
    every = [e["unit"] for e in cand["targets"] + cand["claims_without_collision"]]
    # a target is chosen as a collision and the unit on its losing or untested side - the premise's holder in a premise
    # collision, either side of a conflict or boundary - plus what it bundles (`also`): settle_handover makes it
    # claim_units + weakness, so a target on the evidence against it cannot be written
    sides = defaultdict(list)
    for e in cand["targets"]:
        for x in e["collisions"]:
            if x["role"] in ("holder", "side"):
                sides[x["id"]].append(e["unit"])
    over = [e["unit"] for e in cand["targets"] + cand["claims_without_collision"] if str(e.get("overreach") or "").strip()]
    basis = set(cand["collisions"]) | set(sides) | {ln["line"] for ln in cand["debate_lines"]} | \
        ({gap_id} if gap_id else set())
    codes = [a for a in it_collide.AXES_DIFFER if a != "none"]
    also = arr(one(every), maxItems=3)
    kinds = [obj({"collision": {"enum": [c]}, "unit": one(us), "also": also, "holds": txt(TEXT_MAX)},
                 ["collision", "unit", "holds"]) for c, us in sorted(sides.items())]
    kinds += [obj({"overreach": one(over), "also": also, "holds": txt(TEXT_MAX)}, ["overreach", "holds"])] if over else []
    target = {"anyOf": kinds} if len(kinds) > 1 else (kinds or [obj({"holds": txt(TEXT_MAX)}, ["holds"])])[0]
    vary = [x["axis"] for x in cand["axes"]] or codes
    # a rival account's axis is one its basis differs on and the question does not vary: when only one axis can be
    # varied, it is no rival's; when none is left, an account has no axis of its own (the schema then offers none)
    free = {a for c in basis if c in W.cur for a in W.cur[c].get("axes_differ") or [] if a != "none"} - \
        (set(vary) if len(vary) == 1 else set())
    rival = obj({"account": txt(TEXT_MAX), **({"axis": one(free)} if free else {}), "basis": arr(one(basis), maxItems=6),
                 "unrecorded": txt(TEXT_MAX)}, ["account", "basis"])
    rows = [m["exp_id"] for m in cand["magnitudes"]]
    mag = arr(obj({"exp_id": one(rows), "value": txt(200), "relation": one(["same", "neighbour"]), "n": txt(80)},
                  ["exp_id", "value"]), minItems=1, maxItems=8)          # relation: same when left out
    return obj({"varies": arr(one(vary), minItems=1, maxItems=2), "targets": arr(target, minItems=1, maxItems=5),
                "rival_accounts": arr(rival, minItems=1, maxItems=6),
                "magnitudes": {"anyOf": [mag, {"enum": [NO_NUMBER]}]} if rows else {"enum": [NO_NUMBER]},
                "magnitude_absent": txt(TEXT_MAX)}, ["varies", "targets", "rival_accounts", "magnitudes"])


def cmd_questions_handovers(a):
    """Section 9's candidates for every ready question without one, or whose section 9 the checks refused (with why),
    each as a batch; an earlier answer moves out of the way."""
    rd = Path(a.research_dir)
    W = World(rd)
    wd = rd / B35
    for old in [*wd.glob("s9_batch_*.json"), *(wd / "schemas").glob("s9_batch_*.json")]:
        old.unlink()
    refused = {q: r["s9"] for q, r in question_refusals(W).items() if r["s9"]} if questions(rd) else {}
    n = 0
    for qid, text in questions(rd).items():
        ready = parse_question(text)["fm"].get("status") == "ready"
        if qid not in refused and (not ready or isinstance(handover_of(text), dict)):
            continue                     # a section 9 the checks refused is asked again whatever the status
        for old in wd.glob(f"s9_{qid}.*"):
            old.unlink()
        cand = handover_candidates(W, qid)
        b = {"question": qid, "question_file": f"{QDIR}/{qid}.md", "out": f"{B35}/s9_{qid}.json", "candidates": cand}
        if qid in refused:
            b["refused_before"] = refused[qid][:12]
        write_json(wd / f"s9_batch_{qid}.json", b)
        write_json(wd / "schemas" / f"s9_batch_{qid}.json",
                   handover_schema(W, cand, parse_question(text)["fm"].get("gap")))
        n += 1
    print(f"questions-handovers: {n} section 9 batch(es) -> {B35}/s9_batch_*.json")


def cmd_questions_attach(a):
    """Each written section 9 into its question, under the section's own heading (whatever heading the answer gave it)
    and with the records' copies written by code (settle_handover): replaces the question's section 9, or is appended."""
    rd = Path(a.research_dir)
    W = World(rd)
    n = 0
    for f in sorted([*(rd / B35).glob("s9_Q_*.json"), *(rd / B35).glob("s9_Q_*.md")]):
        qp = rd / QDIR / f"{f.stem[3:]}.md"
        s9 = re.sub(r"^(#+ .*\n+)+", "", f.read_text(encoding="utf-8").strip() + "\n").strip()
        if not qp.exists() or not s9:
            continue
        m = re.search(r"```(?:json)?[ \t]*\n(.*?)\n```", s9, re.S)       # an .md answer: its block; a .json one: itself
        try:
            H = json.loads(m.group(1) if m else s9)
        except ValueError:
            H = None
        if isinstance(H, dict):
            s9 = "```json\n" + json.dumps(settle_handover(W, H), indent=1, ensure_ascii=False) + "\n```"
        s9 = f"## {HANDOVER}\n\n{s9}"
        text = qp.read_text(encoding="utf-8")
        m = re.search(r"^## " + re.escape(HANDOVER) + r".*?(?=^## |\Z)", text, re.M | re.S)
        text = (text[:m.start()] + s9 + "\n\n" + text[m.end():]) if m else text.rstrip() + "\n\n" + s9 + "\n"
        write_text(qp, text)
        n += 1
    print(f"questions-attach: section 9 written into {n} question(s)")


def cmd_handover(a):
    rd = Path(a.research_dir)
    out = handover_candidates(World(rd), a.question)
    p = f"knowledge/_work/B35/handover_{a.question}.json"
    write_json(rd / p, out)
    print(f"questions-handover {a.question}: {len(out['targets'])} unit(s) on {len(out['collisions'])} collision(s) "
          f"(+ {len(out['claims_without_collision'])} claim(s) in none), {len(out['axes'])} differing axis(es), "
          f"{len(out['debate_lines'])} debate Line(s), {len(out['gap_counter'])} gap counter-evidence, "
          f"{len(out['magnitudes'])} matrix row(s) -> {p}")
    for t in out["targets"]:
        cs = ", ".join(f"{x['id']} {x['result']}/{x['role']}" for x in t["collisions"])
        print(f"  unit    {t['unit']} ({t['strength']}, {t['evidence_level']}{', overreach' if t.get('overreach') else ''}"
              f"{', cited' if t['cited_in_question'] else ''}) in {cs}: {str(t['text'])[:80]}")
    for t in out["claims_without_collision"]:
        print(f"  loose   {t['unit']} ({t['strength']}{', cited' if t['cited_in_question'] else ''}"
              f"{', extends ' + ','.join(t['extends']) if t['extends'] else ''}): {str(t['text'])[:80]}")
    for x in out["axes"]:
        print(f"  axis    {x['axis']}: {', '.join(x['collisions'])}")
    for L in out["debate_lines"]:
        print(f"  line    {L['line']} ({L['relation']}): {', '.join(L['collisions'])}")
    print(f"  then write '## {HANDOVER}' with a ```json block {{varies, targets, rival_accounts, magnitudes}} "
          f"(F4-reconstruct.md, B3.5) and run questions-index")


def cmd_index(a):
    from it_ledger import run_unit
    rd = Path(a.research_dir)
    with run_unit(rd, "F.9", check=lambda: run_checks(rd, "F.9")):
        _cmd_index(a)


def _cmd_index(a):
    rd = Path(a.research_dir)
    W = World(rd)
    fs = q_problems(W)
    _print(fs)
    if errors(fs):
        print("questions-index: NOT written")
        raise SystemExit(1)
    idx = build_index(W)
    write_json_stable(rd / INDEX, idx)
    write_text(rd / MAP, render_map(W))                  # the fusion map is a view F.9 keeps current
    print(f"questions-index: {idx['ready']} ready of {len(idx['questions'])} (target {idx['target_ready']}) -> {INDEX}")


def cmd_check(a):
    fs = run_checks(Path(a.research_dir), a.unit)
    _print(fs, a.json)
    if not a.json:
        print("OK" if not errors(fs) else f"{len(errors(fs))} error(s)")
    raise SystemExit(1 if errors(fs) else 0)


def cmd_next(a):
    q, pool = next_question(Path(a.research_dir))
    if not q:
        print("question-next: no ready question left - write questions for the next ranked gaps (F4, 'More questions "
              "later') or stop")
        raise SystemExit(1)
    print(f"question-next: {q['id']} ({q['gap']}, rank {q.get('gap_rank')}, axes {q.get('axes')}) - {q['title']}")
    print(f"  {len(pool)} candidate(s); then: question-take <RD> {q['id']}")


def cmd_take(a):
    gd = take(Path(a.research_dir), a.question, a.gen)
    qj = read_json(gd / "question.json")
    print(f"question-take: {a.question} -> {gd.name}/step7b_problem.md (+ question.json); B4 starts from it")
    if qj["lens_stale"]:
        print("  WARN the machine was probed after the lens was set: lens-set again before B4 reads it (align-check B1)")


def add_parsers(sub) -> None:
    sp = sub.add_parser("question-next", help="planning: the next ready question for a new generation")
    sp.add_argument("research_dir")
    sp.set_defaults(fn=cmd_next)
    sp = sub.add_parser("question-take", help="planning: copy a question into gen_k/step7b_problem.md")
    sp.add_argument("research_dir")
    sp.add_argument("question")
    sp.add_argument("--gen", type=int, help="the generation number (default: the next free one)")
    sp.set_defaults(fn=cmd_take)
    sp = sub.add_parser("recon-candidates", help="A7.R1: what may be promoted to Lines and findings Points")
    sp.add_argument("research_dir")
    sp.set_defaults(fn=cmd_candidates)
    sp = sub.add_parser("fusion-map", help="F.9: render knowledge/fusion_map.md (construct x measure)")
    sp.add_argument("research_dir")
    sp.set_defaults(fn=cmd_map)
    sp = sub.add_parser("questions-prefill", help="B3.5: agree / boundary collisions on a gap's coordinates (settled screen)")
    sp.add_argument("research_dir")
    sp.add_argument("gap")
    sp.set_defaults(fn=cmd_prefill)
    sp = sub.add_parser("questions-handover", help="B3.5: candidates for a question's section 9 (targets, rival accounts, "
                                                   "magnitudes) for the planning block")
    sp.add_argument("research_dir")
    sp.add_argument("question")
    sp.set_defaults(fn=cmd_handover)
    sp = sub.add_parser("sota-tables", help="B2: the methodology legend and paper-theme mapping, from the Planes")
    sp.add_argument("research_dir")
    sp.set_defaults(fn=cmd_sota_tables)
    sp = sub.add_parser("recon-digest", help="the ids a reconstruct unit may cite, one line each (for a worker "
                                             "that cannot open files)")
    sp.add_argument("research_dir")
    sp.add_argument("unit", choices=sorted(DIGEST_SECTIONS))
    sp.set_defaults(fn=cmd_digest)
    for name, fn, hlp in (("recon-batches", cmd_r1_batches, "A7.R1: one batch per candidate the rules let through"),
                          ("recon-merge", cmd_r1_merge, "A7.R1: the answers made findings Points, Line cards and patches"),
                          ("questions-plan", cmd_questions_plan, "B3.5: one batch per gap still without a question"),
                          ("questions-handovers", cmd_questions_handovers, "B3.5: section 9 candidates, one batch per question"),
                          ("questions-attach", cmd_questions_attach, "B3.5: written section 9s into their questions")):
        sp = sub.add_parser(name, help=hlp)
        sp.add_argument("research_dir")
        sp.set_defaults(fn=fn)
    sp = sub.add_parser("questions-index", help="F.9: questions/index.json from questions/Q_*.md")
    sp.add_argument("research_dir")
    sp.set_defaults(fn=cmd_index)
    sp = sub.add_parser("recon-check", help="reconstruct checks (J01-J10, Y01-Y13)")
    sp.add_argument("research_dir")
    sp.add_argument("--unit", default="all", choices=["all", "A7.R1", "A7.R2", "A7.R3", "B2", "B3.5", "F.9"])
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(fn=cmd_check)
