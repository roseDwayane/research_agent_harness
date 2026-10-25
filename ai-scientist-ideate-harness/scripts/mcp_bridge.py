#!/usr/bin/env python3
"""Drive the bundled MCP servers (scholar_mcp, paper_pdf_mcp) over stdio - the transport Claude Code uses - and run
the network steps of the literature pipeline.

A session or a subagent may not have the servers attached; the bridge works either way and keeps bulky paper lists out
of the model's context. With a research dir, every answer is recorded under <RD>/_state/net/<server>/; with
IDEATE_REPLAY=1 the recordings are returned and nothing is sent.

  python mcp_bridge.py tools  {scholar|paper_pdf}
  python mcp_bridge.py call   {scholar|paper_pdf} <tool> '<json params>' [--params-file f.json] [--out result.json] [--titles]

Literature search - the network run of one Unit each (rules: references/search/; every command needs A1's protocol):
  python mcp_bridge.py preflight     <RD>                                 keys, services, SPECTER2 -> _state/preflight.json
  python mcp_bridge.py probe         <RD> [--limit 10] [--queries Q1,Q3]   A1.q  scope probe + known-item lookup
  python mcp_bridge.py search        <RD> [--only Q4] [--no-dense] [--force] [--limit 50]
                                                                          A2.s  one instance per query + D1, then A2.m
  python mcp_bridge.py merge         <RD>                                 A2.m  the merge alone
  python mcp_bridge.py bibliometrics <RD>                                 A3.b  citations, venues, in-collection links
  python mcp_bridge.py snowball      <RD> [--round 2]                     A5    backward, co-citation, forward, similar
  python mcp_bridge.py bibliography  <RD> [--offline]                     A4.b  BibTeX completed from Crossref

Full text:
  python mcp_bridge.py download <RD> [--concurrency 4] [--retry-failed]
        paper_pdf_download over step3_tier1_candidates.json -> pdfs/{citation_key}.pdf + step3_missing_pdfs.md

Run with the interpreter that has the `mcp` package (bash .claude/skills/ai-scientist/scripts/check_env.sh);
exit code 4 = the package is missing.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
SERVERS = {
    "scholar": HERE / "mcp" / "scholar_mcp" / "server.py",
    "paper_pdf": HERE / "mcp" / "paper_pdf_mcp" / "server.py",
}

try:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
except ImportError:
    print("error: python package `mcp` not available in this interpreter; use the one reported by check_env.sh",
          file=sys.stderr)
    sys.exit(4)


sys.path.insert(0, str(Path(__file__).resolve().parent))
from it_common import recorded_async, replaying, require_protocol  # noqa: E402  (sibling module)

SECRET_PARAM = re.compile(r"""(?i)((?:api_?key|apikey|x-els-apikey|x-apikey|insttoken|token)=)[^&\s"']+""")


def scrub_log(path: Path | None) -> None:
    """Replace credential values in a server log with REDACTED. Safe to call repeatedly."""
    if not path or not Path(path).exists():
        return
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    clean = SECRET_PARAM.sub(r"\1REDACTED", text)
    if clean != text:
        Path(path).write_text(clean, encoding="utf-8")


class Server:
    def __init__(self, name: str, log_dir: Path | None = None):
        # httpx logs every outgoing request URL at INFO, and several APIs (PubMed, IEEE) carry the API key as a query
        # parameter - so a request log is a credential leak. Primary defence: the bundled servers silence the httpx
        # logger themselves. Backstop: scrub_log() redacts anything credential-shaped when the session closes.
        # (FASTMCP_LOG_LEVEL has no effect on httpx in this mcp version - do not rely on it.)
        self.name, self._rd = name, log_dir
        self.params = StdioServerParameters(command=sys.executable, args=[str(SERVERS[name])], env={**os.environ})
        self._log_path = (log_dir / f"_mcp_{name}.log") if log_dir else None
        self._log = open(self._log_path or "/dev/null", "a", encoding="utf-8")

    async def __aenter__(self):
        if replaying():          # IDEATE_REPLAY=1: answers come from _state/net/, no server process is started
            self.session = None
            return self
        self._cm = stdio_client(self.params, errlog=self._log)
        read, write = await self._cm.__aenter__()
        self._sess_cm = ClientSession(read, write)
        self.session = await self._sess_cm.__aenter__()
        await self.session.initialize()
        return self

    async def __aexit__(self, *exc):
        if self.session is None:
            self._log.close()
            return
        await self._sess_cm.__aexit__(*exc)
        await self._cm.__aexit__(*exc)
        self._log.close()
        scrub_log(self._log_path)

    async def call(self, tool: str, params: dict):
        """One tool call. With a research dir every answer is recorded under _state/net/<server>/ (record / replay:
        it_common.net_*); with IDEATE_REPLAY=1 the recording is returned and nothing is sent."""
        async def live():
            res = await self.session.call_tool(tool, {"params": params})
            text = res.content[0].text if res.content else ""
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return {"_text": text}
        return await recorded_async(self._rd, self.name, {"tool": tool, "params": params}, live)


def write_json(path: Path, data) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


async def cmd_tools(a):
    async with Server(a.server) as s:
        for t in (await s.session.list_tools()).tools:
            print(f"{t.name}: {(t.description or '').strip().splitlines()[0][:110]}")


async def cmd_call(a):
    params = json.loads(Path(a.params_file).read_text()) if a.params_file else json.loads(a.params or "{}")
    async with Server(a.server) as s:
        out = await s.call(a.tool, params)
    if a.titles and isinstance(out.get("papers"), list):  # compact view for probing a query without flooding the context
        print(f"count={out.get('count')} skipped={out.get('sources_skipped') or {}} errors={out.get('source_errors') or {}}")
        for p_ in out["papers"][:25]:
            print(f"  ({p_.get('year')}) [{','.join(p_.get('sources_found_in') or [])}] {str(p_.get('title'))[:110]}")
        return
    text = out.get("_text") if set(out) == {"_text"} else json.dumps(out, indent=2, ensure_ascii=False)
    if a.out:
        Path(a.out).write_text(text + "\n", encoding="utf-8")
        print(f"wrote {a.out} ({len(text)} chars)")
    else:
        print(text)


# =========================================================================================== literature search
# One command per Unit's network run; the logic is in the Unit's module (it_*.py), the rules in references/search/.

def _mailto() -> str:
    return os.environ.get("SCHOLAR_CONTACT_EMAIL", "research-agent@example.com")


def _cfg(rd: Path) -> dict:
    p = Path(rd) / "step0_session_config.json"
    if not p.exists():
        sys.exit(f"error: {p} not found: the literature search starts at A1 (`ideate_tools.py frame set-protocol`)")
    cfg = json.loads(p.read_text())
    require_protocol(cfg, rd)
    return cfg


async def cmd_probe(a):
    """A1.q's scope probe (it_frame.run_probe)."""
    import it_frame
    rd = Path(a.research_dir)
    cfg = _cfg(rd)
    queries = [x.strip() for x in (a.queries or "").split(",") if x.strip()] or None
    try:
        async with Server("scholar", rd) as s:
            summary = await it_frame.run_probe(s, cfg, rd, _mailto(), queries=queries, limit=a.limit)
    except Exception as e:  # noqa: BLE001 - the server would not start: the probe records why it was skipped
        print(f"  scholar server unavailable: {str(e)[:160]}", file=sys.stderr)
        summary = await it_frame.run_probe(None, cfg, rd, _mailto(), queries=queries, limit=a.limit)
    if summary.get("skipped"):
        print(f"probe skipped: {summary['skipped']}")
        return
    for q in summary["queries"]:
        print(f"  {q['id']}: " + "  ".join(f"{k}={v}" for k, v in q["hits_per_source"].items())
              + f"   OpenAlex total={q['openalex_total']}   ({q['flat_query']})")
    ki = summary.get("known_items") or []
    print(f"  known items found: {sum(1 for k in ki if k['resolved'])}/{len(ki)}")
    for k in ki:
        if not k["resolved"]:
            print(f"   NOT FOUND: {k['ref']}")


async def cmd_search(a):
    """A2.s + A2.m: every active query in each source's own form and the dense instance D1 (one recorded instance
    each), then the merge. Refuses until A1.p, A1.q and A1.e pass."""
    import it_search
    from it_frame import search_gate
    rd = Path(a.research_dir)
    cfg = _cfg(rd)
    gate = search_gate(cfg, rd)
    if gate:
        for f in gate[:12]:
            print(f"  {f['code']} [{f['unit']}] {f['msg']}", file=sys.stderr)
        sys.exit(f"error: A1 is not done ({len(gate)} error(s)): `ideate_tools.py frame check {rd}`")
    only = [x.strip() for x in (a.only or "").split(",") if x.strip()] or None
    async with Server("scholar", rd) as s:
        await it_search.run_search(s, cfg, rd, only=only, limit=a.limit or it_search.LIMIT, dense=not a.no_dense,
                                   force=a.force)
        raw = await it_search.run_merge(s, cfg, rd, _mailto())
    sm = raw["search_summary"]
    print(f"merge: {sm['total_raw_results']} records -> {sm['after_dedup']} papers (merges {sm['merges']}); "
          f"no anchor term {sm['without_anchor_term']}; dense-only {sm['dense_only']}; sem_sim {sm['sem_sim']}")
    for c in sm["caveats"]:
        print(f"  caveat {c['code']}: {c['text']}")
    print("  next (A2.c): `ideate_tools.py search-check <RD>`, judge every query, `ideate_tools.py relevance-set`")


async def cmd_merge(a):
    """A2.m alone: merge the query instances on disk again (after an anchor-list change, or once SPECTER2 is there)."""
    import it_search
    rd = Path(a.research_dir)
    cfg = _cfg(rd)
    async with Server("scholar", rd) as s:
        raw = await it_search.run_merge(s, cfg, rd, _mailto())
    sm = raw["search_summary"]
    print(f"merge: {sm['total_raw_results']} records -> {sm['after_dedup']} papers (merges {sm['merges']}); sem_sim {sm['sem_sim']}")


async def cmd_bibliometrics(a):
    """A3.b: citations, venue metrics and the collection's own citation links per candidate -> step3_bibliometrics.json."""
    import it_screen
    rd = Path(a.research_dir)
    cfg = _cfg(rd)
    async with Server("scholar", rd) as s:
        out = await it_screen.run_bibliometrics(s, cfg, rd, _mailto())
    ps = out["papers"].values()
    print(f"bibliometrics: {len(out['papers'])} candidates; OpenAlex records {sum(1 for r in ps if r['metadata'] != 'none')}; "
          f"venues with SNIP {out['venues_with_snip']}; mean impact {sum(r['impact'] for r in ps) / max(1, len(out['papers'])):.2f}")
    for c in out["caveats"]:
        print(f"  caveat {c['code']}: {c['text']}")
    print("  next (A3.g): `ideate_tools.py screen-gate <RD>`")


async def cmd_snowball(a):
    """A5: backward and co-citation from A3.b's reference lists, forward through OpenAlex `cites:`, similar through
    Semantic Scholar recommendations -> step2b_snowball_papers.json. Refuses until A3 passes."""
    import it_snowball
    rd = Path(a.research_dir)
    cfg = _cfg(rd)
    it_snowball.preflight(cfg, rd, a.round)          # refuse before the server starts
    async with Server("scholar", rd) as s:
        out = await it_snowball.run_snowball(s, cfg, rd, _mailto(), round_no=a.round)
    r = out["rounds"][-1]
    print(f"snowball round {r['round']}: {r['added']} additions {r['by_direction']} (threshold: cited by >= "
          f"{r['threshold']} of {r['included_before']} included papers); truncated {r['truncated']}")
    for d, st in r["status"].items():
        print(f"  {d:<11} {st['status']}" + (f" - {st['why']}" if st.get("why") else ""))
    for c in out["caveats"]:
        if c.get("round") == r["round"]:
            print(f"  caveat {c['code']}: {c['text']}")
    print("  next (A3 on the additions): `mcp_bridge.py bibliometrics <RD>`, `screen-gate`, `screen-plan` (only the "
          "unscored), `screen-merge`, `screen-build`; then A4 (`export`, `mcp_bridge.py bibliography`)")


async def cmd_bibliography(a):
    """A4.b: one complete BibTeX entry per citation key, from Crossref by DOI -> step4_references.bib and
    step4_bib_metadata.json. Refuses until A4.k passes."""
    import it_export
    rd = Path(a.research_dir)
    cfg = _cfg(rd)
    out = it_export.build_bibliography(cfg, rd, _mailto(), offline=a.offline)
    n = len(out["entries"])
    cr = sum(1 for v in out["entries"].values() if v["source"] == "crossref")
    print(f"bibliography: {n} entries, {cr} completed from Crossref, {n - cr} from the search records"
          + (f" ({out['crossref_failed_batches']} Crossref batch(es) failed)" if out["crossref_failed_batches"] else "")
          + " -> step4_references.bib")
    print("  next: `ideate_tools.py a4-check <RD>`")


async def cmd_preflight(a):
    """Before a run: which keys are configured (names only), whether each service answers, whether SPECTER2 is cached
    -> <RD>/_state/preflight.json. Network Units read it (for 12 hours) to take a degraded path at once instead of
    waiting for time-outs. Nothing here is recorded for replay."""
    from it_common import PREFLIGHT, http_json, now_iso, scholar_key, write_json as wj
    rd = Path(a.research_dir)
    names = [l.split("=", 1)[0].strip() for l in (HERE / "mcp" / ".env.example").read_text().splitlines()
             if "=" in l and not l.lstrip().startswith("#")]
    keys = {n: bool(scholar_key(n)) for n in names}
    services = {}

    def probe(name, fn):
        try:
            detail = fn()
            services[name] = {"ok": True, "detail": str(detail)[:160]}
        except Exception as e:  # noqa: BLE001 - a failing service is the finding
            services[name] = {"ok": False, "detail": f"{type(e).__name__}: {str(e)[:160]}"}
    probe("openalex", lambda: http_json(f"https://api.openalex.org/works?per-page=1&select=id&mailto={_mailto()}", None)["meta"]["count"])
    probe("crossref", lambda: http_json("https://api.crossref.org/works?rows=0", None)["message"]["total-results"])
    try:
        async with Server("scholar") as s:
            r = await s.call("scholar_search", {"query": "electroencephalography", "sources": ["openalex"], "limit": 1})
            services["scholar_server"] = {"ok": "papers" in r, "detail": str(r.get("_text") or f"{r.get('count')} hit(s)")[:160]}
            r = await s.call("scholar_recommend", {"paper_ids": ["DOI:10.1016/j.neuroimage.2017.06.030"], "limit": 1})
            ok = isinstance(r.get("papers"), list)
            services["semantic_scholar"] = {"ok": ok, "detail": (f"{len(r['papers'])} recommendation(s)" if ok
                                                               else str(r.get("_text") or r)[:160])}
    except Exception as e:  # noqa: BLE001
        services.setdefault("scholar_server", {"ok": False, "detail": f"{type(e).__name__}: {str(e)[:160]}"})
        services.setdefault("semantic_scholar", {"ok": False, "detail": "scholar server unavailable"})
    hub = Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface")) / "hub" / "models--allenai--specter2_base"
    out = {"at": now_iso(), "python": sys.executable, "keys": keys, "services": services,
           "specter2": hub.exists() and any((hub / "snapshots").glob("*"))}
    wj(rd / PREFLIGHT, out)
    print(f"preflight -> {rd / PREFLIGHT}")
    print("  keys: " + " · ".join(f"{k} {'✔' if v else '—'}" for k, v in keys.items()))
    for k, v in services.items():
        print(f"  {k:<16} {'ok' if v['ok'] else 'UNAVAILABLE'}  {v['detail']}")
    print(f"  specter2         {'cached' if out['specter2'] else 'not in the Hugging Face cache (sem_sim off)'}")


# ================================================================================================== full text
async def cmd_download(a):
    from it_fulltext import check_fetch
    from it_ledger import degraded_codes, run_unit
    rd = Path(a.research_dir).resolve()
    with run_unit(rd, "A6.d", check=lambda: check_fetch(rd), degraded=lambda: degraded_codes(rd, "A6.d")):
        await _download(a)


async def _download(a):
    from it_fulltext import record_attempts
    rd = Path(a.research_dir).resolve()
    cand = rd / "step3_tier1_candidates.json"
    if not cand.exists():
        sys.exit("error: step3_tier1_candidates.json not found - run `ideate_tools.py tier1` first")
    # Remember what was already attempted: after `tier1 --top-up` only the new candidates need fetching. Re-trying every
    # earlier paywall took 24 minutes in practice and changed nothing.
    att_path = rd / "_download_attempted.json"
    attempted = set(json.loads(att_path.read_text())) if att_path.exists() and not a.retry_failed else set()
    keys = [c["citation_key"] for c in json.loads(cand.read_text())["candidates"]]
    todo = [k for k in keys if k not in attempted and not (rd / "pdfs" / f"{k}.pdf").exists()]
    if not todo:
        print(f"download: nothing new to fetch ({len(keys)} candidates, all attempted; use --retry-failed to try again)")
        return
    print(f"download: fetching {len(todo)} candidate(s)" + (f", skipping {len(keys) - len(todo)} already attempted" if len(todo) < len(keys) else ""), flush=True)
    async with Server("paper_pdf", rd) as s:
        r = await s.call("paper_pdf_download", {"md_path": str(cand), "output_dir": str(rd / "pdfs"), "overwrite": False,
                                                "only_keys": todo, "concurrency": a.concurrency,
                                                "write_missing_report": True, "response_format": "json"})
    if "_text" in r:                             # the server failed: nothing was tried, so nothing is remembered as tried
        sys.exit(f"error: {r['_text'][:500]}")
    write_json(att_path, sorted(attempted | set(todo)))
    status = {"downloaded": "ok", "skipped": "skipped", "failed": "failed"}
    record_attempts(rd, "paper_pdf", [{"key": x["citation_key"], "status": status.get(x.get("status"), "failed"),
                                       "reason": x.get("reason") or x.get("source") or ""}
                                      for x in r.get("results") or [] if x.get("citation_key")])
    print(f"download: {r.get('downloaded')} downloaded, {r.get('skipped')} skipped, {r.get('failed')} failed "
          f"of {r.get('total')} -> {r.get('output_dir')}")
    for x in r.get("results") or []:
        if x.get("status") == "failed":
            print(f"  failed {x['citation_key']}: {x.get('reason')}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("tools"); p.add_argument("server", choices=SERVERS); p.set_defaults(fn=cmd_tools)
    p = sub.add_parser("call"); p.add_argument("server", choices=SERVERS); p.add_argument("tool")
    p.add_argument("params", nargs="?"); p.add_argument("--params-file"); p.add_argument("--out")
    p.add_argument("--titles", action="store_true", help="for scholar_search: print only counts and titles")
    p.set_defaults(fn=cmd_call)
    p = sub.add_parser("preflight"); p.add_argument("research_dir"); p.set_defaults(fn=cmd_preflight)
    p = sub.add_parser("probe"); p.add_argument("research_dir"); p.add_argument("--limit", type=int, default=10)
    p.add_argument("--queries", default="", help="comma-separated query ids (default: primary, loosen, anchor-methods)")
    p.set_defaults(fn=cmd_probe)
    p = sub.add_parser("search"); p.add_argument("research_dir")
    p.add_argument("--limit", type=int, default=None, help="per source per query (default 50)")
    p.add_argument("--only", default="", help="comma-separated query ids to run (a revised query); other instances are kept")
    p.add_argument("--no-dense", action="store_true", help="skip the dense instance D1")
    p.add_argument("--force", action="store_true", help="run instances again that already completed")
    p.set_defaults(fn=cmd_search)
    p = sub.add_parser("merge"); p.add_argument("research_dir"); p.set_defaults(fn=cmd_merge)
    p = sub.add_parser("bibliometrics"); p.add_argument("research_dir"); p.set_defaults(fn=cmd_bibliometrics)
    p = sub.add_parser("snowball"); p.add_argument("research_dir")
    p.add_argument("--round", type=int, default=1, help="2 = a second round (only after >= 10%% growth of the included set)")
    p.set_defaults(fn=cmd_snowball)
    p = sub.add_parser("bibliography"); p.add_argument("research_dir")
    p.add_argument("--offline", action="store_true", help="entries from the search records only (no Crossref)")
    p.set_defaults(fn=cmd_bibliography)
    p = sub.add_parser("download"); p.add_argument("research_dir"); p.add_argument("--concurrency", type=int, default=4)
    p.add_argument("--retry-failed", action="store_true", help="also re-try candidates that failed in an earlier pass")
    p.set_defaults(fn=cmd_download)
    a = ap.parse_args()
    asyncio.run(a.fn(a))


if __name__ == "__main__":
    main()
