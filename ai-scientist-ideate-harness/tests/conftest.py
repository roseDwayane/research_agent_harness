"""Shared test setup: the module root and mcp/ on sys.path, the SDK (if installed) imported before them."""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

try:                                  # resolve the official SDK before mcp/ (no __init__.py) is on sys.path
    import mcp.server.fastmcp  # noqa: F401
except ImportError:                   # MCP tests skip themselves with a reason
    pass

MODULE = Path(__file__).resolve().parent.parent
for p in (str(MODULE / "mcp" / "ideate_v2_mcp"), str(MODULE)):
    if p not in sys.path:
        sys.path.insert(0, p)

DATASETS = MODULE / "evals" / "datasets"


@pytest.fixture(scope="session")
def reg():
    from ideate_v2.registry import Registry
    return Registry.load()


@pytest.fixture
def dataset(tmp_path):
    """Copy a fixture research folder into tmp_path/root/run and return (root, run)."""
    def make(name: str) -> tuple[Path, Path]:
        root = tmp_path / "root"
        root.mkdir(exist_ok=True)
        run = root / "run"
        shutil.copytree(DATASETS / name, run)
        return root, run
    return make


@pytest.fixture
def ctx_for():
    def make(root: Path):
        from ideate_v2.paths import PathPolicy
        from ideate_v2.registry import Registry
        from tools.handlers import Context
        return Context(Registry.load(), PathPolicy((root.resolve(),)))
    return make
