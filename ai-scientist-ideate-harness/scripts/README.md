# Scripts

All scripts run with the standard library (Python ≥ 3.10) except where noted; they work from any directory and
under `python -I`. Exit codes are meaningful for CI: **0** ok, **1** findings, **2** usage or I/O error (or, for
`run_checks.py --strict`, a skipped check).

| Script | Does | Typical use |
|---|---|---|
| `run_checks.py` | runs every check below plus compile, JSON parse, tests, evals, MCP smoke, lint; prints PASS / FAIL / SKIP with the reason and the command for each skip | `python scripts/run_checks.py` (CI: `--strict` where every prerequisite is installed) |
| `validate_contracts.py` | JSON Schema of the contracts; duplicate and dangling ids; step membership and gate chaining; cycles and forward references; artifact ownership, producers and implicit dependencies; completeness of the 27 fields per Unit; verdicts; legacy drift; MCP schema files parse | `--quiet`, `--json`, `--strict` (WARN fails), `--legacy-registry <ideate_units.json>` |
| `validate_architecture.py` | ARCHITECTURE.md: required sections and subsections; generated blocks present and fresh; Mermaid blocks; every registry id present; one spec heading per Unit; every typed id cited exists; local links resolve; TBD lines listed as information | `--quiet`, `--json`, `--doc <path>` |
| `render_docs.py` | regenerates the generated blocks of ARCHITECTURE.md and references/unit_contracts.md from the contracts | after editing `contracts/`; `--check` in CI |
| `import_legacy_registry.py` | snapshots the legacy `ideate_units.json` into `contracts/legacy_snapshot.json` (hash-pinned); `--check` reports drift | `IDEATE_LEGACY_SKILL_DIR=<legacy skill> python scripts/import_legacy_registry.py --check` |

Related, under `evals/`: `run_evals.py` (behaviour cases), `build_datasets.py` (fixture folders, `--check`),
`shadow_compare.py` (v2 vs legacy states; needs the legacy skill).

Optional prerequisites: `pytest` and the `mcp` SDK (`pip install -r requirements-dev.txt`) for the tests and the MCP
smoke check; `ruff` for lint; `IDEATE_LEGACY_SKILL_DIR` for the drift and shadow checks.
