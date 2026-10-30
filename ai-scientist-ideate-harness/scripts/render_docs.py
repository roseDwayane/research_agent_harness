#!/usr/bin/env python3
"""Regenerate the generated blocks of ARCHITECTURE.md and references/unit_contracts.md from the contracts.

    python scripts/render_docs.py            # rewrite the blocks in place
    python scripts/render_docs.py --check    # exit 1 when a block is out of date (CI)

Exit codes: 0 ok, 1 stale blocks (--check), 2 a file or the contracts could not be read.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))   # the module root: ideate_v2 importable,
                                                                  # also under python -I

from ideate_v2 import ARCHITECTURE_DOC, MODULE_ROOT
from ideate_v2.docs import blocks_in, render_file, stale_blocks
from ideate_v2.jsonio import write_text_atomic
from ideate_v2.registry import Registry

TARGETS = [ARCHITECTURE_DOC, MODULE_ROOT / "references" / "unit_contracts.md"]


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):        # a console code page (cp1252) must not crash on a path
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="backslashreplace")
    ap = argparse.ArgumentParser(description="Render generated documentation blocks from the contracts.")
    ap.add_argument("--check", action="store_true", help="report stale blocks, change nothing")
    ap.add_argument("files", nargs="*", type=Path, help="files to render (default: ARCHITECTURE.md, unit_contracts.md)")
    a = ap.parse_args(argv)
    try:
        reg = Registry.load()
    except (OSError, ValueError) as e:
        print(f"error: cannot load the contracts: {e}", file=sys.stderr)
        return 2
    status = 0
    for path in a.files or TARGETS:
        if not path.is_file():
            print(f"error: {path} not found", file=sys.stderr)
            return 2
        text = path.read_text(encoding="utf-8")
        names = blocks_in(text)
        if a.check:
            stale = stale_blocks(reg, path)
            if stale:
                status = 1
                print(f"STALE {path.name}: {', '.join(stale)} (run scripts/render_docs.py)")
            else:
                print(f"ok    {path.name}: {len(names)} generated block(s) up to date")
        else:
            new = render_file(reg, text)
            if new != text:
                write_text_atomic(path, new)
                print(f"wrote {path.name}: {len(names)} generated block(s)")
            else:
                print(f"ok    {path.name}: unchanged")
    return status


if __name__ == "__main__":
    sys.exit(main())
