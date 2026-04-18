"""Tests for index_state atomicity mechanism."""
from pathlib import Path

from tools import atomicity


class TestIndexStateMarker:
    def test_write_file_marks_un_indexed(self, tmp_path: Path):
        file_path = tmp_path / "001_test.md"
        atomicity.write_business_file_pending(
            str(file_path),
            frontmatter={"type": "proposal", "author": "ken", "summary": "x"},
            body="# test\nbody\n",
        )
        content = file_path.read_text(encoding="utf-8")
        assert "index_state: un-indexed" in content
        assert "type: proposal" in content
        assert "# test" in content

    def test_mark_indexed_updates_state(self, tmp_path: Path):
        file_path = tmp_path / "001_test.md"
        atomicity.write_business_file_pending(
            str(file_path),
            frontmatter={"type": "proposal"},
            body="# test\n",
        )
        atomicity.mark_indexed(str(file_path))
        content = file_path.read_text(encoding="utf-8")
        assert "index_state: indexed" in content
        assert "un-indexed" not in content

    def test_find_un_indexed_files(self, tmp_path: Path):
        f1 = tmp_path / "discussions/proj/thread/001.md"
        f1.parent.mkdir(parents=True)
        atomicity.write_business_file_pending(
            str(f1),
            frontmatter={"type": "proposal"},
            body="# a\n",
        )
        atomicity.mark_indexed(str(f1))

        f2 = tmp_path / "discussions/proj/thread/002.md"
        atomicity.write_business_file_pending(
            str(f2),
            frontmatter={"type": "reply"},
            body="# b\n",
        )

        un_indexed = list(atomicity.find_un_indexed_files(str(tmp_path / "discussions")))
        assert len(un_indexed) == 1
        assert un_indexed[0].endswith("002.md")

    def test_read_business_file_parses_frontmatter_and_body(self, tmp_path: Path):
        file_path = tmp_path / "001_test.md"
        atomicity.write_business_file_pending(
            str(file_path),
            frontmatter={"type": "proposal", "author": "ken"},
            body="# hello\nworld\n",
        )
        parsed = atomicity.read_business_file(str(file_path))
        assert parsed.frontmatter["type"] == "proposal"
        assert parsed.frontmatter["author"] == "ken"
        assert "# hello" in parsed.body
        assert parsed.frontmatter["index_state"] == "un-indexed"
