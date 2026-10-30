"""Load the v2 contracts (contracts/architecture.json + its unit files) and the legacy snapshot into one index.

Entity kinds: pipeline, stage, block, step, unit, substep, gate, loop, artifact, infrastructure, external_service,
data_store, mcp_server, retry_policy, decision, open_question, source.
"""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Iterable

from . import ARCHITECTURE_JSON, LEGACY_SNAPSHOT
from .jsonio import read_json

COLLECTIONS = {
    "stages": "stage", "blocks": "block", "steps": "step", "gates": "gate", "loops": "loop", "artifacts": "artifact",
    "infrastructure": "infrastructure", "external_services": "external_service", "data_stores": "data_store",
    "mcp_servers": "mcp_server", "retry_policies": "retry_policy", "decisions": "decision",
    "open_questions": "open_question", "sources": "source",
}
ORCHESTRATOR = "@orchestrator"


class RegistryError(ValueError):
    pass


class CycleError(RegistryError):
    def __init__(self, cycle: list[str]):
        super().__init__("dependency cycle: " + " -> ".join(cycle))
        self.cycle = cycle


class Registry:
    def __init__(self, arch: dict, unit_docs: list[dict], legacy: dict | None, path: Path | None = None):
        self.arch = arch
        self.unit_docs = unit_docs
        self.path = path
        self.legacy = legacy or {}
        self.units: dict[str, dict] = {}
        self.substeps: dict[str, dict] = {}
        self.duplicates: list[str] = []
        self.index: dict[str, tuple[str, dict]] = {}
        self._add("pipeline", arch.get("pipeline") or {})
        for coll, kind in COLLECTIONS.items():
            for e in arch.get(coll) or []:
                self._add(kind, e)
        for doc in unit_docs:
            for u in doc.get("units") or []:
                if self._add("unit", u):
                    self.units[u["id"]] = u
            for s in doc.get("substeps") or []:
                if self._add("substep", s):
                    self.substeps[s["id"]] = s

    def _add(self, kind: str, entity: dict) -> bool:
        """Index an entity; a second entity with an id already taken (by any kind) is recorded as a duplicate."""
        eid = entity.get("id")
        if not eid:
            return False
        if eid in self.index:
            self.duplicates.append(eid)
            return False
        self.index[eid] = (kind, entity)
        return True

    # ------------------------------------------------------------------ loading
    @classmethod
    def load(cls, path: Path | None = None, legacy_path: Path | None = None) -> "Registry":
        path = Path(path or ARCHITECTURE_JSON)
        arch = read_json(path)
        docs = [read_json(path.parent / f) for f in arch.get("unit_files") or []]
        lp = Path(legacy_path) if legacy_path else (LEGACY_SNAPSHOT if path == ARCHITECTURE_JSON else
                                                    path.parent / "legacy_snapshot.json")
        legacy = read_json(lp) if lp.is_file() else None
        return cls(arch, docs, legacy, path)

    # ------------------------------------------------------------------ lookups
    def kind_of(self, eid: str) -> str | None:
        return self.index[eid][0] if eid in self.index else None

    def get(self, eid: str) -> dict:
        if eid not in self.index:
            raise KeyError(eid)
        return self.index[eid][1]

    def of_kind(self, kind: str) -> list[dict]:
        return [e for k, e in self.index.values() if k == kind]

    def steps(self) -> list[dict]:
        return self.arch.get("steps") or []

    def step_order(self) -> list[str]:
        """Steps in pipeline order: block order, then ordinal."""
        out = []
        for b in self.arch.get("blocks") or []:
            out += sorted(b.get("steps") or [], key=lambda s: (self.get(s).get("ordinal", 0)) if s in self.index else 0)
        return out

    def unit_order(self) -> list[str]:
        """Units in pipeline order: step order, then the order the step lists them."""
        out = []
        for sid in self.step_order():
            out += [u for u in self.get(sid).get("units") or [] if u in self.units]
        return out

    def legacy_card(self, unit_id: str) -> dict | None:
        return (self.legacy.get("units") or {}).get(unit_id)

    def requires(self, unit_id: str) -> list[str]:
        return list(self.units[unit_id].get("requires") or [])

    def dependents(self, unit_id: str) -> list[str]:
        return [u for u, spec in self.units.items() if unit_id in (spec.get("requires") or [])]

    def upstream(self, unit_id: str) -> set[str]:
        seen, stack = set(), list(self.requires(unit_id))
        while stack:
            u = stack.pop()
            if u in seen or u not in self.units:
                continue
            seen.add(u)
            stack += self.requires(u)
        return seen

    def downstream(self, unit_id: str) -> set[str]:
        seen, stack = set(), self.dependents(unit_id)
        while stack:
            u = stack.pop()
            if u in seen:
                continue
            seen.add(u)
            stack += self.dependents(u)
        return seen

    def topo_order(self, units: Iterable[str] | None = None) -> list[str]:
        """Kahn's algorithm over requires; raises CycleError with one cycle when the graph is not a DAG."""
        nodes = list(units) if units is not None else list(self.units)
        nodeset = set(nodes)
        indeg = {u: 0 for u in nodes}
        out_edges = defaultdict(list)
        for u in nodes:
            for r in self.requires(u):
                if r in nodeset:
                    indeg[u] += 1
                    out_edges[r].append(u)
        order_hint = {u: i for i, u in enumerate(self.unit_order())}
        ready = sorted([u for u, d in indeg.items() if d == 0], key=lambda u: order_hint.get(u, 1e9))
        out = []
        while ready:
            u = ready.pop(0)
            out.append(u)
            for v in out_edges[u]:
                indeg[v] -= 1
                if indeg[v] == 0:
                    ready.append(v)
                    ready.sort(key=lambda x: order_hint.get(x, 1e9))
        if len(out) != len(nodes):
            raise CycleError(self._find_cycle([u for u in nodes if u not in out]))
        return out

    def _find_cycle(self, nodes: list[str]) -> list[str]:
        nodeset, color, stack = set(nodes), {}, []

        def dfs(u: str) -> list[str] | None:
            color[u] = 1
            stack.append(u)
            for r in self.requires(u):
                if r not in nodeset:
                    continue
                if color.get(r) == 1:
                    return stack[stack.index(r):] + [r]
                if color.get(r) is None:
                    found = dfs(r)
                    if found:
                        return found
            stack.pop()
            color[u] = 2
            return None

        for n in nodes:
            if color.get(n) is None:
                c = dfs(n)
                if c:
                    return c
        return nodes

    def step_of(self, unit_id: str) -> str | None:
        return self.units.get(unit_id, {}).get("step")

    def substeps_of(self, unit_id: str) -> list[dict]:
        return [s for s in self.substeps.values() if s.get("parent") == unit_id]

    def gates_into(self, step_id: str) -> list[dict]:
        """Every gate on the path into ``step_id``: gates whose to_step is this step or any earlier step."""
        order = self.step_order()
        if step_id not in order:
            return []
        pos = order.index(step_id)
        return [g for g in self.arch.get("gates") or [] if g.get("to_step") in order and
                order.index(g["to_step"]) <= pos]

    def producers(self, art_id: str, _seen: set | None = None) -> set[str]:
        """Units that produce an artifact; for a view, the producers of what it is derived from."""
        _seen = _seen or set()
        if art_id in _seen or art_id not in self.index:
            return set()
        _seen.add(art_id)
        art = self.get(art_id)
        owners = {o["unit"] for o in art.get("owners") or [] if o.get("unit") != ORCHESTRATOR}
        if art.get("kind") == "view":
            for d in art.get("derived_from") or []:
                owners |= self.producers(d, _seen)
        return owners

    def loop_covers(self, producer: str, consumer: str) -> bool:
        """True when a declared loop feeds back from ``producer`` to ``consumer`` (or to the consumer's step)."""
        cstep = self.step_of(consumer)
        for lp in self.arch.get("loops") or []:
            if lp.get("from") == producer and (consumer in lp.get("to", []) or cstep in lp.get("to", [])):
                return True
        return False
