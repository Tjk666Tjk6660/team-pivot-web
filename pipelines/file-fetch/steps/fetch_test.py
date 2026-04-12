"""Tests for file-fetch fetch step."""
import json
import os
import subprocess
import sys
from pathlib import Path


STEP = Path(__file__).parent / "fetch.py"


def _seed(tmp_path: Path):
    thread_dir = tmp_path / "discussions" / "enclaws" / "alpha"
    thread_dir.mkdir(parents=True)
    (thread_dir / "001_ken_proposal_x.md").write_text(
        "---\ntype: proposal\nauthor: ken\n---\n# proposal body\n", encoding="utf-8"
    )
    idx_dir = tmp_path / "index"
    idx_dir.mkdir()
    (idx_dir / "alpha-discuss.index.yaml").write_text(
        "origin_path: discussions/enclaws/alpha/\n"
        "created: '2026-04-11T10:00:00+08:00'\n"
        "last_updated: '2026-04-11T10:00:00+08:00'\n"
        "discussions: []\n"
        "timeline: []\n",
        encoding="utf-8",
    )
    (tmp_path / "SKILL.md").write_text("# skill doc\n", encoding="utf-8")


def _run(tmp_path: Path, paths: list[str]) -> dict:
    env = {
        **os.environ,
        "PIVOT_TENANT_ID": "t",
        "PIVOT_USER_ID": "u",
        "PIVOT_WORKSPACE_DIR": str(tmp_path),
        "PIVOT_APP_NAME": "pivot",
    }
    proc = subprocess.run(
        [sys.executable, str(STEP)],
        input=json.dumps({"input": {"paths": ",".join(paths)}, "steps": {}}),
        capture_output=True,
        text=True,
        env=env,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


class TestFetch:
    def test_business_file_attaches_index(self, tmp_path: Path):
        _seed(tmp_path)
        result = _run(
            tmp_path, ["discussions/enclaws/alpha/001_ken_proposal_x.md"]
        )
        assert len(result["output"]["files"]) == 1
        f = result["output"]["files"][0]
        assert f["kind"] == "business"
        assert "proposal body" in f["content"]
        assert "alpha" in result["output"]["attached_indexes"]
        assert "origin_path" in result["output"]["attached_indexes"]["alpha"]

    def test_index_file_returns_as_index_kind(self, tmp_path: Path):
        _seed(tmp_path)
        result = _run(tmp_path, ["index/alpha-discuss.index.yaml"])
        f = result["output"]["files"][0]
        assert f["kind"] == "index"
        assert result["output"]["attached_indexes"] == {}

    def test_other_file_no_attachment(self, tmp_path: Path):
        _seed(tmp_path)
        result = _run(tmp_path, ["SKILL.md"])
        f = result["output"]["files"][0]
        assert f["kind"] == "other"
        assert "skill doc" in f["content"]
        assert result["output"]["attached_indexes"] == {}

    def test_missing_file_error(self, tmp_path: Path):
        _seed(tmp_path)
        result = _run(tmp_path, ["discussions/enclaws/alpha/nope.md"])
        assert result["output"]["files"][0].get("error") == "not found"
