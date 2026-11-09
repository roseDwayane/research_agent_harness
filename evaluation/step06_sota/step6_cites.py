#!/usr/bin/env python3
"""Citations in a Step 6 text, for the LLM-judged evaluations (AutoSurvey, MetaSyn, the naive baseline).

Two text formats exist, and the judges must read both:

  fusion block (B2)     cites ids: collisions `X0019`, experiments / units `galt2019#E1`, Points / Lines / Planes
                        `P_/D_/E_/F_draft_...`; a bare paper key `galt2019` in the mapping table
  archived engine and   cites paper keys: `(AuthorYear)`, `(Smith et al., 2024)`, `\\cite{key}` (step6_common)
  the naive baseline    and, now, bare keys of the session's bibliography (`[galt2019]`)

`CiteFinder` hides the difference: for a session written by the fusion-block harness (it has knowledge/decon/) the
citations are the ids of step6_world, each resolving to the papers it rests on; otherwise the archived parsing of
step6_common is used unchanged. Either way a citation is `Cite(id, raw, span)`, `papers_of(id)` says which papers
a judge must read for it, and `strip` / `render` give the text without citations / with ids written as paper keys.

`render` exists because the Step 6 judges (Structure, Relevance, Coverage) should read a survey, not identifiers: a
B2 sentence "agree (X0005, abstract level)" is shown to them as "agree (galt2019; jacksonetal2023, abstract level)",
the same form a baseline that cites keys has.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from step6_common import extract_citations
from step6_world import CARD_RE, COLLISION_RE, UNIT_RE, World, load_world

LEGACY_PAREN_RE = re.compile(r"\s*[（(][^()（）]*[)）]")
GROUP_RE = re.compile(r"[（(\[]([^()（）\[\]]*)[)）\]]")
TOKEN_RE = re.compile(r"(?<![A-Za-z0-9_#])([A-Za-z][A-Za-z0-9]*)(?![A-Za-z0-9_#])")
MAX_PAPERS_PER_ID = 6          # a collision / Point rarely rests on more; a Plane would flood the judge's source text
GROUP_LEFTOVER_WORDS = 4       # "(X0005, abstract level)" keeps nothing once the ids go; a longer remark stays


@dataclass(frozen=True)
class Cite:
    id: str
    raw: str
    start: int
    end: int


def is_fusion_session(session: Path | None) -> bool:
    return bool(session) and (Path(session) / "knowledge" / "decon").is_dir()


class CiteFinder:
    def __init__(self, session: Path | None, legal_keys: set[str]):
        self.legal = set(legal_keys)
        self.world: World | None = load_world(Path(session)) if is_fusion_session(session) else None

    # ---- what an id stands for ------------------------------------------------------------------------------
    def is_valid(self, ident: str) -> bool:
        if self.world is not None:
            return self.world.kind(ident) is not None
        return ident in self.legal

    def papers_of(self, ident: str) -> list[str]:
        """The papers a judge must read to decide whether `ident` supports a claim (legal keys only, capped)."""
        if self.world is not None:
            papers = sorted(self.world.papers_of(ident))
        else:
            papers = [ident]
        return [p for p in papers if p in self.legal][:MAX_PAPERS_PER_ID]

    # ---- finding ---------------------------------------------------------------------------------------------
    def find(self, text: str) -> list[Cite]:
        if self.world is None:
            out: list[Cite] = []
            for c in extract_citations(text):
                at = text.find(c.raw)
                out.append(Cite(c.key, c.raw, at, at + len(c.raw) if at >= 0 else -1))
            known = {c.id for c in out}
            return out + self._bare_keys(text, known)
        spans: list[Cite] = []
        for regex in (COLLISION_RE, CARD_RE, UNIT_RE):
            spans += [Cite(m.group(0), m.group(0), m.start(), m.end()) for m in regex.finditer(text)]
        taken = [(c.start, c.end) for c in spans]
        spans += [c for c in self._bare_keys(text, set()) if not any(a <= c.start < b for a, b in taken)]
        # A baseline may cite keys in the archived style `(SmithEtAl2024)` that are not in the bibliography: those
        # are invented citations and must count as invalid. B2 never writes that form.
        taken = [(c.start, c.end) for c in spans]
        for c in extract_citations(text):
            at = text.find(c.raw)
            if at >= 0 and c.key not in self.legal and not any(a <= at < b for a, b in taken):
                spans.append(Cite(c.key, c.raw, at, at + len(c.raw)))
        return sorted(spans, key=lambda c: c.start)

    def _bare_keys(self, text: str, known: set[str]) -> list[Cite]:
        """A bare bibliography key (`[galt2019]`, `(Galt2019; ...)`): any token that is exactly a key of the session."""
        return [Cite(m.group(1), m.group(1), m.start(1), m.end(1)) for m in TOKEN_RE.finditer(text)
                if m.group(1) in self.legal and m.group(1) not in known]

    def ids(self, text: str) -> list[str]:
        return list(dict.fromkeys(c.id for c in self.find(text)))

    # ---- text without citations / with ids as paper keys -----------------------------------------------------
    def strip(self, text: str) -> str:
        if self.world is None:  # archived format: parenthetical groups that cite, and narrative keys
            text = LEGACY_PAREN_RE.sub(lambda m: "" if extract_citations(m.group(0)) else m.group(0), text)
            for c in extract_citations(text):
                text = text.replace(c.raw, "")
            return re.sub(r"\s+([.,;:!?])", r"\1", re.sub(r"\s{2,}", " ", text)).strip()
        cites = [c for c in self.find(text) if c.start >= 0]
        drop = [False] * len(text)
        for g in GROUP_RE.finditer(text):
            inside = [c for c in cites if g.start(1) <= c.start and c.end <= g.end(1)]
            if not inside:
                continue
            rest = list(g.group(1))
            for c in inside:
                for i in range(c.start - g.start(1), c.end - g.start(1)):
                    rest[i] = " "
            words = re.findall(r"[A-Za-z]+", "".join(rest))
            if len(words) <= GROUP_LEFTOVER_WORDS:
                for i in range(g.start(), g.end()):
                    drop[i] = True
        for c in cites:
            for i in range(c.start, c.end):
                drop[i] = True
        kept = "".join(ch for ch, d in zip(text, drop) if not d)
        kept = re.sub(r"[ \t]{2,}", " ", kept)
        return re.sub(r"\s+([.,;:!?])", r"\1", kept).strip()

    def render(self, text: str) -> str:
        """Ids written as the paper keys they rest on, so a judge reads a survey rather than identifiers."""
        if self.world is None:
            return text
        out, pos = [], 0
        for c in self.find(text):
            if c.start < pos:
                continue
            out.append(text[pos:c.start])
            keys = self.papers_of(c.id) if c.id not in self.legal else [c.id]
            out.append("; ".join(keys))
            pos = c.end
        out.append(text[pos:])
        rendered = "".join(out)
        return re.sub(r"\(\s*\)|\[\s*\]", "", rendered)
