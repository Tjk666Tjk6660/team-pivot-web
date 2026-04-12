"""Verify that un-indexed files can be discovered and recovered."""
from pathlib import Path

from tools import atomicity


class TestAtomicityRecovery:
    def test_un_indexed_files_are_discoverable(self, tmp_path: Path):
        thread = tmp_path / "discussions/enclaws/t"
        thread.mkdir(parents=True)
        atomicity.write_business_file_pending(
            str(thread / "001_ken_proposal_abc123.md"),
            frontmatter={"type": "proposal", "author": "ken"},
            body="# stuck in the middle\n",
        )

        un_indexed = list(atomicity.find_un_indexed_files(str(tmp_path / "discussions")))
        assert len(un_indexed) == 1
        assert un_indexed[0].endswith("001_ken_proposal_abc123.md")

    def test_mark_indexed_clears_state(self, tmp_path: Path):
        f = tmp_path / "discussions/e/t/001.md"
        f.parent.mkdir(parents=True)
        atomicity.write_business_file_pending(
            str(f),
            frontmatter={"type": "proposal"},
            body="# x\n",
        )
        atomicity.mark_indexed(str(f))
        un_indexed = list(atomicity.find_un_indexed_files(str(tmp_path / "discussions")))
        assert len(un_indexed) == 0
