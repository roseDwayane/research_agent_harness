"""A4 export - names and bibliography for the shortlist (rules: references/search/A4-export.md).

  A4.k  keys          one citation key per shortlisted paper, for good: minted from the most complete author list,
                      a collision takes the next unused suffix, a retired key is never handed out again
                                                     -> step4_citation_keys.jsonl (append-only), step4_citation_keys.md,
                                                        step3_shortlist.json `citation_key` (projected from the log)
  A4.b  bibliography  one complete BibTeX entry per key: Crossref metadata by DOI (type, authors, venue, volume, issue,
                      pages), recorded; a paper Crossref does not know keeps the entry built from the search record
                                                     -> step4_references.bib, step4_bib_metadata.json

  ideate_tools.py export <RD> [--no-snowball REASON]   A4.k (refuses before A3 and A5 pass)
  mcp_bridge.py   bibliography <RD>           A4.b (network: Crossref; offline: entries from the search records)
  ideate_tools.py a4-check <RD> [--unit A4.k|A4.b|all] [--json]
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

from it_common import (append_jsonl, die, http_json, last_name, now_iso, quote, read_json, read_jsonl,
                       require_protocol, sha256_file, split_name, write_json, write_json_stable, write_text)

KEY_RE = re.compile(r"^[a-z0-9]+(\d{4}|nd)[a-z]?$")
LOG = "step4_citation_keys.jsonl"
CROSSREF_KIND = {"journal-article": "article", "proceedings-article": "inproceedings", "posted-content": "misc",
                 "book-chapter": "incollection", "book": "book", "monograph": "book", "edited-book": "book",
                 "dissertation": "phdthesis", "report": "techreport", "dataset": "misc", "standard": "misc"}


def F(level, code, unit, msg):
    return {"level": level, "code": code, "unit": unit, "msg": msg}


def errors(fs):
    return [f for f in fs if f["level"] == "ERROR"]


def _cfg(rd):
    p = Path(rd) / "step0_session_config.json"
    if not p.exists():
        die(f"{p} not found", 2)
    return read_json(p)


# ===================================================================================== key and entry format
CONFERENCE_HINTS = re.compile(
    r"proceedings|conference|symposium|workshop|\b(neurips|nips|iclr|icml|cvpr|iccv|eccv|aaai|ijcai|acl|emnlp|naacl|"
    r"interspeech|icassp|embc|miccai|kdd|www|sigir|chi|icse|fse|ase|issta)\b",
    re.I,
)


def base_key(authors: list[str], year) -> str:
    names = [last_name(x) for x in authors if x and last_name(x)]
    if not names:
        names = ["anon"]
    if len(names) == 1:
        stem = names[0]
    elif len(names) == 2:
        stem = names[0] + names[1]
    else:
        stem = names[0] + "etal"
    # Lower-case on purpose: the writeup stage's bib_tools.py lower-cases every key it caches,
    # so CamelCase keys would stop matching the keys cited in the ideation documents.
    return re.sub(r"[^a-z0-9]", "", stem.lower()) + str(year or "nd")


def bib_escape(s: str) -> str:
    s = re.sub("[\u2010-\u2015\u2212]", "-", s).replace("\\", "")  # unicode hyphens/dashes break pdflatex
    for ch in "&%$#_":
        s = s.replace(ch, "\\" + ch)
    return s


def protect_caps(title: str) -> str:
    """Brace tokens with an internal capital or all-caps acronyms so BibTeX styles keep their case."""
    def fix(m):
        w = m.group(0)
        return "{" + w + "}" if (re.search(r"[a-z][A-Z]|[A-Z]{2,}", w)) else w
    return re.sub(r"[A-Za-z][A-Za-z0-9\-]*", fix, title)


def bib_author(author: str) -> str:
    fam, given = split_name(author)
    return f"{fam}, {given}" if given else fam


def bib_entry(p: dict, key: str) -> str:
    venue = (p.get("journal") or "").strip()
    arxiv = p.get("arxiv_id")
    doi = p.get("doi")
    fields = [("author", bib_escape(" and ".join(bib_author(x) for x in p.get("authors") or []))),
              ("title", protect_caps(bib_escape(p.get("title") or "")))]
    if arxiv and (not venue or "arxiv" in venue.lower()):
        kind = "misc"
        fields += [("year", p.get("year")), ("eprint", arxiv), ("archiveprefix", "arXiv"),
                   ("url", f"https://arxiv.org/abs/{arxiv}")]
    else:
        kind = "inproceedings" if CONFERENCE_HINTS.search(venue) else "article"
        fields += [("booktitle" if kind == "inproceedings" else "journal", bib_escape(venue)),
                   ("year", p.get("year")), ("doi", doi),
                   ("url", f"https://doi.org/{doi}" if doi else p.get("url"))]
    body = ",\n".join(f"  {k:<13} = {{{v}}}" for k, v in fields if v not in (None, "", []))
    todo = "" if (doi or arxiv or p.get("url")) else "  % TODO: missing DOI/URL - verify manually\n"
    return f"@{kind}{{{key},\n{todo}{body}\n}}"


# ======================================================================================================= A4.k keys
def log_path(rd) -> Path:
    return Path(rd) / LOG


def read_log(rd) -> list[dict]:
    return read_jsonl(log_path(rd))


def registry(rd) -> dict:
    """id -> its (first) key; a later line for the same id with another key is a violation A4.k reports (K02)."""
    out = {}
    for e in read_log(rd):
        out.setdefault(e["id"], e)
    return out


def best_authors(paper: dict, bibrec: dict | None) -> tuple[list[str], str]:
    """The longest author list on record: the search record, or OpenAlex's authorships (A3.b) - Scopus's standard view
    names only the first author, which would mint `smith2020` for a five-author paper."""
    raw = list(paper.get("authors") or [])
    full = list((bibrec or {}).get("authors_full") or [])
    return (full, "openalex") if len(full) > len(raw) else (raw, "search")


def mint_keys(cfg: dict, rd: Path, no_snowball: str | None = None) -> dict:
    rd = Path(rd)
    sl = read_json(rd / "step3_shortlist.json")
    bib = read_json(rd / "step3_bibliometrics.json")["papers"] if (rd / "step3_bibliometrics.json").exists() else {}
    reg = registry(rd)
    taken = {e["key"] for e in read_log(rd)}
    new = []
    for p in sl["papers"]:
        if p["id"] in reg:
            continue
        authors, basis = best_authors(p, bib.get(p["id"]))
        if not authors or not p.get("title"):
            continue
        base = base_key(authors, p.get("year"))
        key = base
        for suffix in "abcdefghijklmnopqrstuvwxyz":
            if key not in taken:
                break
            key = base + suffix
        e = {"id": p["id"], "key": key, "at": now_iso(), "authors_basis": basis, "n_authors": len(authors)}
        new.append(e)
        taken.add(key)
        reg[p["id"]] = e
    if new:
        append_jsonl(log_path(rd), new)
    # project the keys onto the shortlist (A4.k owns that field)
    in_sl = {p["id"] for p in sl["papers"]}
    for p in sl["papers"]:
        if p["id"] in reg:
            p["citation_key"] = reg[p["id"]]["key"]
        else:
            p.pop("citation_key", None)
    write_json(rd / "step3_shortlist.json", sl)
    retired = sorted(k for k in reg if k not in in_sl)
    rows = ["| Citation key | Paper | Title | Year | Authors from | Status |", "|---|---|---|---|---|---|"]
    for p in sorted(sl["papers"], key=lambda q: q.get("citation_key") or "~"):
        e = reg.get(p["id"])
        rows.append(f"| `{p.get('citation_key', '(none: no authors or title)')}` | {p['id']} | {str(p.get('title'))[:80]} | "
                    f"{p.get('year') or 'n.d.'} | {(e or {}).get('authors_basis', '-')} | active |")
    rows += [f"| `{reg[i]['key']}` | {i} | (left the shortlist) | | {reg[i].get('authors_basis')} | retired, never reused |"
             for i in retired]
    write_text(rd / "step4_citation_keys.md", "<!-- generated by A4.k (`ideate_tools.py export`) - do not edit -->\n"
               f"# Citation keys\n\nTopic: {cfg.get('topic')}  \nActive {len(in_sl & set(reg))} · retired {len(retired)} · "
               "\n\n" + (f"**Exported before the snowball:** {no_snowball}\n\n" if no_snowball else "")
               + "\n".join(rows) + "\n\nCite as `\\cite{key}` in LaTeX and as "
               "`(Author, Year) [key]` in the ideation documents. A key never changes and is never reused.\n")
    return {"new": len(new), "active": len(in_sl & set(reg)), "retired": len(retired),
            "without_key": sorted(in_sl - set(reg)), "from_openalex_authors": sum(1 for e in new if e["authors_basis"] == "openalex")}


def check_keys(cfg, rd) -> list[dict]:
    U = "A4.k"
    rd = Path(rd)
    if not log_path(rd).exists():
        return [F("ERROR", "K01", U, f"no {LOG}: run `ideate_tools.py export <RD>`")]
    sl = read_json(rd / "step3_shortlist.json")
    log = read_log(rd)
    reg = registry(rd)
    fs = []
    for p in sl["papers"]:
        if p.get("authors") and p.get("title") and p["id"] not in reg:
            fs.append(F("ERROR", "K01", U, f"{p['id']} is shortlisted but has no key: run export"))
            break
    by_id = {}
    for e in log:
        if e["id"] in by_id and by_id[e["id"]] != e["key"]:
            fs.append(F("ERROR", "K02", U, f"{e['id']} was keyed {by_id[e['id']]} and later {e['key']}: a key never changes"))
        by_id.setdefault(e["id"], e["key"])
    owners = Counter(e["key"] for e in reg.values())
    dup = sorted(k for k, n in owners.items() if n > 1)
    if dup:
        fs.append(F("ERROR", "K03", U, f"keys handed to two papers (a retired key reused?): {dup[:5]}"))
    bad = sorted(e["key"] for e in reg.values() if not KEY_RE.match(e["key"]))
    if bad:
        fs.append(F("ERROR", "K04", U, f"keys not lower-case author+year(+suffix): {bad[:5]}"))
    for p in sl["papers"]:
        if p["id"] in reg and p.get("citation_key") != reg[p["id"]]["key"]:
            fs.append(F("ERROR", "K05", U, f"{p['id']}: shortlist says {p.get('citation_key')!r}, the log {reg[p['id']]['key']!r} "
                                           "(edited by hand, or export not re-run)"))
            break
    return fs


def snowball_gate(cfg, rd) -> list[dict]:
    """A4 runs once, on the final shortlist: after A5 and A3's screening of its additions."""
    from it_snowball import errors as a5_errors, run_checks as a5_checks
    return a5_errors(a5_checks(cfg, rd))


def _cmd_export(a):
    from it_screen import export_gate
    rd = Path(a.research_dir)
    cfg = _cfg(rd)
    gate3 = export_gate(cfg, rd)
    if gate3:
        for f in gate3[:12]:
            print(f"  {f['code']} [{f['unit']}] {f['msg']}")
        die(f"A3 is not done ({len(gate3)} error(s)): `ideate_tools.py a3-check {rd}`", 2)
    gate = snowball_gate(cfg, rd)
    if gate and not getattr(a, "no_snowball", None):
        for f in gate[:8]:
            print(f"  {f['code']} [{f['unit']}] {f['msg']}")
        die("A5 is not done: keys are minted once, on the final shortlist (snowball, then screen the additions). "
            "`export --no-snowball \"<reason>\"` exports anyway and records why", 2)
    out = mint_keys(cfg, rd, no_snowball=getattr(a, "no_snowball", None) if gate else None)
    print(f"A4.k: {out['active']} active keys ({out['new']} new, {out['from_openalex_authors']} of them from OpenAlex's "
          f"fuller author lists), {out['retired']} retired -> {LOG}; keys projected onto the shortlist")
    if out["without_key"]:
        print(f"  no key (no authors or no title on record): {out['without_key'][:8]}")
    print("  next (A4.b): `mcp_bridge.py bibliography <RD>`")


# =================================================================================================== A4.b bibliography
def _bib_escape(s: str) -> str:
    return bib_escape(str(s))


def crossref_batch(rd: Path, dois: list[str], mailto: str, fetch=http_json) -> dict:
    """Crossref metadata for many DOIs: one request per 40 (filter=doi:a,doi:b,...), recorded under _state/net/http/."""
    out, failed = {}, 0
    for i in range(0, len(dois), 40):
        chunk = dois[i:i + 40]
        url = (f"https://api.crossref.org/works?filter={quote(','.join('doi:' + d for d in chunk))}&rows=50"
               f"&mailto={quote(mailto)}")
        try:
            for m in ((fetch(url, rd).get("message") or {}).get("items") or []):
                out[str(m.get("DOI") or "").lower()] = m
        except Exception:  # noqa: BLE001 - those papers keep their search-record entry
            failed += 1
    return {"items": out, "failed_batches": failed}


def entry_from_crossref(key: str, m: dict) -> str:
    kind = CROSSREF_KIND.get(m.get("type"), "article")
    authors = " and ".join(
        f"{a.get('family')}, {a.get('given')}" if a.get("given") else str(a.get("family") or a.get("name") or "")
        for a in m.get("author") or [] if a.get("family") or a.get("name"))
    year = None
    for k in ("published-print", "published-online", "issued", "created"):
        parts = ((m.get(k) or {}).get("date-parts") or [[None]])[0]
        if parts and parts[0]:
            year = parts[0]
            break
    venue = ((m.get("container-title") or [None])[0]) or None
    fields = [("author", _bib_escape(authors)), ("title", protect_caps(_bib_escape((m.get("title") or [""])[0])))]
    if kind == "article":
        fields.append(("journal", _bib_escape(venue or "")))
    elif kind in ("inproceedings", "incollection"):
        fields.append(("booktitle", _bib_escape(venue or "")))
    elif kind == "misc" and m.get("type") == "posted-content":
        fields.append(("howpublished", _bib_escape(m.get("institution", [{}])[0].get("name") if m.get("institution")
                                                    else (m.get("publisher") or "preprint"))))
    fields += [("year", year), ("volume", m.get("volume")), ("number", m.get("issue")), ("pages", m.get("page")),
               ("publisher", _bib_escape(m.get("publisher") or "") if kind in ("book", "incollection", "techreport") else None),
               ("doi", m.get("DOI")), ("url", f"https://doi.org/{m.get('DOI')}" if m.get("DOI") else None)]
    body = ",\n".join(f"  {k:<13} = {{{v}}}" for k, v in fields if v not in (None, "", []))
    return f"@{kind}{{{key},\n{body}\n}}"


def _build_bibliography(cfg: dict, rd: Path, mailto: str, fetch=http_json, offline=False) -> dict:
    rd = Path(rd)
    fs = check_keys(cfg, rd)
    if errors(fs):
        for f in fs:
            print(f"  {f['level']:<5} {f['code']} [{f['unit']}] {f['msg']}")
        die("A4.k is not done: `ideate_tools.py export <RD>` first", 2)
    sl = read_json(rd / "step3_shortlist.json")
    bibrec = read_json(rd / "step3_bibliometrics.json")["papers"] if (rd / "step3_bibliometrics.json").exists() else {}
    keyed = [p for p in sl["papers"] if p.get("citation_key")]
    dois = sorted({str(p["doi"]).lower() for p in keyed if p.get("doi")})
    cr = {"items": {}, "failed_batches": 0} if offline else crossref_batch(rd, dois, mailto, fetch)
    entries, meta = [], {}
    for p in sorted(keyed, key=lambda q: q["citation_key"]):
        m = cr["items"].get(str(p.get("doi") or "").lower())
        if m and (m.get("author") or m.get("title")):
            entries.append(entry_from_crossref(p["citation_key"], m))
            meta[p["citation_key"]] = {"id": p["id"], "source": "crossref", "type": m.get("type"), "doi": m.get("DOI")}
        else:
            q = dict(p)
            authors, basis = best_authors(p, bibrec.get(p["id"]))
            q["authors"] = authors
            entries.append(bib_entry(q, p["citation_key"]))
            meta[p["citation_key"]] = {"id": p["id"], "source": f"search record ({basis} authors)",
                                       "why": "no DOI" if not p.get("doi") else ("offline" if offline else "not in Crossref")}
    header = (f"% Generated by A4.b (`mcp_bridge.py bibliography`) - do not edit\n% Topic: {cfg.get('topic')}\n"
              f"% Entries: {len(entries)} ({sum(1 for v in meta.values() if v['source'] == 'crossref')} from Crossref)\n\n")
    write_text(rd / "step4_references.bib", header + "\n\n".join(entries) + "\n")
    out = {"schema": "ideate-bib/1", "at": now_iso(), "basis": {"log": sha256_file(log_path(rd)),
                                                                 "shortlist": sha256_file(rd / "step3_shortlist.json")},
           "crossref_failed_batches": cr["failed_batches"], "offline": offline, "entries": meta}
    write_json_stable(rd / "step4_bib_metadata.json", out)
    return out


BIB_KEY = re.compile(r"^@(\w+)\{([^,\s]+),", re.M)


def check_bibliography(cfg, rd) -> list[dict]:
    U = "A4.b"
    rd = Path(rd)
    bp, mp = rd / "step4_references.bib", rd / "step4_bib_metadata.json"
    if not bp.exists() or not mp.exists():
        return [F("ERROR", "L01", U, "no step4_references.bib / step4_bib_metadata.json: run `mcp_bridge.py bibliography <RD>`")]
    sl = read_json(rd / "step3_shortlist.json")
    keys = {p["citation_key"] for p in sl["papers"] if p.get("citation_key")}
    found = BIB_KEY.findall(bp.read_text())
    bib_keys = [k for _, k in found]
    fs = []
    if sorted(bib_keys) != sorted(keys) or len(bib_keys) != len(set(bib_keys)):
        fs.append(F("ERROR", "L01", U, f"the .bib must hold one entry per active key: missing {sorted(keys - set(bib_keys))[:5]}, "
                                       f"extra {sorted(set(bib_keys) - keys)[:5]}"))
    meta = read_json(mp)
    if set(meta.get("entries") or {}) != keys:
        fs.append(F("ERROR", "L02", U, "step4_bib_metadata.json does not describe exactly the active keys"))
    if (meta.get("basis") or {}) != {"log": sha256_file(log_path(rd)), "shortlist": sha256_file(rd / "step3_shortlist.json")}:
        fs.append(F("ERROR", "L03", U, "STALE: keys or shortlist changed after the bibliography: run it again"))
    if meta.get("offline"):
        fs.append(F("WARN", "L04", U, "built offline: no entry was completed from Crossref"))
    return fs


def run_checks(cfg, rd, unit="all") -> list[dict]:
    require_protocol(cfg, rd)
    fs = []
    if unit in ("all", "A4.k"):
        fs += check_keys(cfg, rd)
    if unit in ("all", "A4.b"):
        fs += check_bibliography(cfg, rd)
    return fs


def cmd_a4_check(a):
    rd = Path(a.research_dir)
    fs = run_checks(_cfg(rd), rd, a.unit)
    if a.json:
        print(json.dumps(fs, indent=2, ensure_ascii=False))
    else:
        for f in fs:
            print(f"  {f['level']:<5} {f['code']} [{f['unit']}] {f['msg']}")
        print("OK" if not errors(fs) else f"{len(errors(fs))} error(s)")
    raise SystemExit(1 if errors(fs) else 0)


# ---------------------------------------------------------------------------------------------- ledger boundaries
def cmd_export(a):
    from it_ledger import degraded_codes, run_unit
    rd = Path(a.research_dir)
    with run_unit(rd, "A4.k", check=lambda: check_keys(_cfg(rd), rd), degraded=lambda: degraded_codes(rd, "A4.k")):
        _cmd_export(a)


def build_bibliography(cfg: dict, rd: Path, mailto: str, fetch=http_json, offline=False) -> dict:
    from it_ledger import degraded_codes, run_unit
    with run_unit(rd, "A4.b", check=lambda: check_bibliography(cfg, Path(rd)), degraded=lambda: degraded_codes(rd, "A4.b")):
        return _build_bibliography(cfg, rd, mailto, fetch=fetch, offline=offline)


def add_parsers(sub) -> None:
    sp = sub.add_parser("export", help="A4.k: citation keys on the final shortlist (append-only)")
    sp.add_argument("research_dir")
    sp.add_argument("--no-snowball", metavar="REASON", help="mint keys before A5 has run; the reason is written into "
                                                             "step4_citation_keys.md")
    sp.set_defaults(fn=cmd_export)
    sp = sub.add_parser("a4-check", help="A4 handoff checks (A4.k keys, A4.b bibliography)")
    sp.add_argument("research_dir")
    sp.add_argument("--unit", default="all", choices=["all", "A4.k", "A4.b"])
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(fn=cmd_a4_check)
