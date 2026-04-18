"""Pipeline test: file-fetch."""
from pathlib import Path


class TestFileFetch:
    def test_fetches_business_file_with_index(self, runner, make_proposal_draft):
        # Seed a thread first
        draft_id = make_proposal_draft(
            title="fetch-target", content="# Proposal\n\nFetchable content.",
        )
        runner.run("discuss-new", {
            "draft_id": draft_id,
            "category": "test",
            "mention_users": "",
            "mention_comments": "",
        })
        ws = Path(runner.data_space_dir)
        canonical = list((ws / "discussions/test/fetch-target").glob("001_*.md"))
        assert len(canonical) == 1

        rel_path = str(canonical[0].relative_to(ws).as_posix())
        result = runner.run("file-fetch", {"paths": rel_path})
        assert result.status == "completed", result.error
        files = result.output["files"]
        assert len(files) == 1
        assert files[0]["kind"] == "business"
        assert "Fetchable content" in files[0]["content"]
        assert "fetch-target" in result.output["attached_indexes"]

    def test_fetch_nonexistent_file(self, runner):
        result = runner.run("file-fetch", {"paths": "nonexistent.md"})
        assert result.status == "completed"
        assert result.output["files"][0].get("error") == "not found"
