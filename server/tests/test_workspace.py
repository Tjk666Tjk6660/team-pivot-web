from __future__ import annotations

from server.workspace import Workspace, repo_dir_name


def test_repo_dir_name_strips_dot_git():
    assert repo_dir_name("https://github.com/a/b.git") == "b"
    assert repo_dir_name("https://github.com/a/b") == "b"
    assert repo_dir_name("https://github.com/a/b/") == "b"


def test_auth_url_injects_token_for_https():
    ws = Workspace(
        path="/tmp/x",
        repo_url="https://github.com/a/b.git",
        token="ghp_xxx",
    )
    assert ws._auth_url() == "https://oauth2:ghp_xxx@github.com/a/b.git"


def test_auth_url_unchanged_when_no_token():
    ws = Workspace(path="/tmp/x", repo_url="https://github.com/a/b.git")
    assert ws._auth_url() == "https://github.com/a/b.git"


def test_auth_url_unchanged_for_ssh():
    ws = Workspace(
        path="/tmp/x",
        repo_url="git@github.com:a/b.git",
        token="ghp_xxx",
    )
    assert ws._auth_url() == "git@github.com:a/b.git"


def test_is_cloned_false_for_empty_dir(tmp_path):
    ws = Workspace(path=tmp_path / "nope", repo_url="https://x/y.git")
    assert ws.is_cloned() is False
    assert ws.head() is None
