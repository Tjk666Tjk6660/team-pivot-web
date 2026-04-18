from __future__ import annotations

import subprocess

import pytest

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


@pytest.fixture
def git_workspace(tmp_path):
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", "-b", "main", str(remote)], check=True)
    seed = tmp_path / "seed"
    subprocess.run(["git", "clone", str(remote), str(seed)], check=True)
    (seed / "README.md").write_text("seed\n")
    env = {
        "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
    }
    subprocess.run(["git", "-C", str(seed), "add", "-A"], check=True)
    subprocess.run(
        ["git", "-C", str(seed), "commit", "-m", "init"], env=env, check=True,
    )
    subprocess.run(["git", "-C", str(seed), "push", "origin", "main"], check=True)

    local = tmp_path / "local"
    ws = Workspace(path=local, repo_url=str(remote), branch="main")
    ws.ensure_cloned()
    return ws, remote


def test_write_session_commits_and_pushes(git_workspace, tmp_path):
    ws, remote = git_workspace
    with ws.write_session(
        message="feat: test", author_name="Ken", author_email="ken@pivot.local",
    ):
        (ws.path / "new.txt").write_text("hello\n")

    log = subprocess.run(
        ["git", "-C", str(remote), "log", "--format=%an <%ae>%x09%s", "-1"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    author_line, subject = log.split("\t", 1)
    assert author_line == "Ken <ken@pivot.local>"
    assert subject == "feat: test"


def test_write_session_no_op_if_nothing_changed(git_workspace):
    ws, remote = git_workspace
    before = subprocess.run(
        ["git", "-C", str(remote), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    with ws.write_session(
        message="noop", author_name="x", author_email="x@y",
    ):
        pass  # no writes
    after = subprocess.run(
        ["git", "-C", str(remote), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    assert before == after


def test_write_session_serializes_concurrent_writers(git_workspace):
    import threading
    ws, remote = git_workspace
    results = []

    def do_write(i):
        with ws.write_session(
            message=f"feat: {i}", author_name="x", author_email="x@y",
        ):
            (ws.path / f"f{i}.txt").write_text(str(i))
        results.append(i)

    threads = [threading.Thread(target=do_write, args=(i,)) for i in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    count = subprocess.run(
        ["git", "-C", str(remote), "rev-list", "--count", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    assert int(count) == 6  # 1 seed + 5 concurrent
    assert sorted(results) == [0, 1, 2, 3, 4]
