from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from scholar_research.cli import main
from scholar_research.config import Config
from scholar_research.session import Session


def test_cli_status_checkpoint_and_prompts(tmp_path: Path):
    root = tmp_path / "10_Research"
    cfg = Config.load(None)
    s = Session.create(root, "Topic X", cfg, session_id="20260101")
    r = CliRunner()
    out = r.invoke(main, ["status", "--root", str(root)])
    assert out.exit_code == 0 and "20260101_topic-x" in out.output and "Pending" in out.output
    out = r.invoke(main, ["checkpoint", "1", "--root", str(root), "--session", "topic-x", "--note", "looks good"])
    assert out.exit_code == 0, out.output
    assert json.loads((s.dir / "checkpoints.json").read_text())["decisions"]["1"]["decision"]["approved"] is True
    out = r.invoke(main, ["prompts"])
    assert out.exit_code == 0 and "s3_score" in out.output
    out = r.invoke(main, ["new", "T", "--root", str(root), "--no-run", "--session-id", "20260102"])
    assert out.exit_code == 0 and (root / "20260102_t").is_dir()
