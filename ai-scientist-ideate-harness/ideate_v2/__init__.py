"""ideate_v2 - contracts, validation and orchestration support for the v2 ideate architecture (slides 3-5).

Standard library only, so that the validators run anywhere. The MCP adapter (../mcp/ideate_v2_mcp/server.py) is the only part
that needs a third-party package (the official ``mcp`` SDK).
"""
from __future__ import annotations

import os
from pathlib import Path

__version__ = "2.0.0"

MODULE_ROOT = Path(__file__).resolve().parent.parent          # ai-scientist-ideate-harness/
CONTRACTS_DIR = MODULE_ROOT / "contracts"
ARCHITECTURE_JSON = CONTRACTS_DIR / "architecture.json"
ARCHITECTURE_SCHEMA = CONTRACTS_DIR / "architecture.schema.json"
LEGACY_SNAPSHOT = CONTRACTS_DIR / "legacy_snapshot.json"
MCP_DIR = MODULE_ROOT / "mcp" / "ideate_v2_mcp"
MCP_SCHEMAS_DIR = MCP_DIR / "schemas"
REPO_ROOT = MODULE_ROOT
ARCHITECTURE_DOC = MODULE_ROOT / "ARCHITECTURE.md"
# The skill that implements the Units (ideate_tools.py, the registry). In this module it is the module itself; the
# environment variable still points the validators at another copy (e.g. to compare two versions).
LEGACY_SKILL_DIR = Path(os.environ.get("IDEATE_LEGACY_SKILL_DIR") or MODULE_ROOT)
