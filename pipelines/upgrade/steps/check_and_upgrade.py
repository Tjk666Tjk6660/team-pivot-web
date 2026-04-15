"""Upgrade pipeline: check remote version and pull if newer.

Reads upgrade_repo / upgrade_user / upgrade_token from pivot-config.yaml.
If credentials are missing, returns an error asking the user to provide them.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import yaml


def _read_config(repo_path: str) -> dict:
    config_file = Path(repo_path) / "pivot-config.yaml"
    if not config_file.exists():
        return {}
    with open(config_file, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _get_remote_version(upgrade_url: str) -> str | None:
    """Fetch version from remote pivot-config.yaml via git archive."""
    try:
        # Use raw GitHub URL to fetch remote config
        raw_url = upgrade_url.replace("github.com", "raw.githubusercontent.com").rstrip(".git") + "/main/pivot-config.yaml"
        import urllib.request
        with urllib.request.urlopen(raw_url, timeout=10) as resp:
            remote_config = yaml.safe_load(resp.read().decode("utf-8")) or {}
            return str(remote_config.get("version", ""))
    except Exception:
        return None


def _version_lt(a: str, b: str) -> bool:
    """Return True if version a < version b (semver comparison)."""
    def parts(v: str) -> list[int]:
        try:
            return [int(x) for x in v.split(".")]
        except ValueError:
            return [0]
    return parts(a) < parts(b)


def main():
    payload = json.loads(sys.stdin.read())

    # Locate repo root
    data_space_dir = os.environ.get("PIVOT_DATA_SPACE_DIR", "")
    repo_path = os.environ.get("PIVOT_REPO_PATH") or str(Path(data_space_dir).parent)

    config = _read_config(repo_path)
    local_version = str(config.get("version", "0.0.0"))
    upgrade_repo = config.get("upgrade_repo", "")
    upgrade_user = config.get("upgrade_user", "")
    upgrade_token = config.get("upgrade_token", "")

    # Check required fields
    missing = []
    if not upgrade_repo:
        missing.append("upgrade_repo")
    if not upgrade_token:
        missing.append("upgrade_token")

    if missing:
        sys.stdout.write(json.dumps({"output": {
            "upgraded": False,
            "error": "credentials_missing",
            "missing": missing,
            "message": f"升级需要配置 {', '.join(missing)}，请在 pivot-config.yaml 中填写，或告诉我这些信息。",
        }}))
        return

    # Check remote version (use public URL, token only needed for git pull)
    remote_version = _get_remote_version(upgrade_repo)
    if remote_version is None:
        # Can't fetch remote version, try upgrade anyway
        remote_version = "unknown"

    if remote_version != "unknown" and not _version_lt(local_version, remote_version):
        sys.stdout.write(json.dumps({"output": {
            "upgraded": False,
            "local_version": local_version,
            "remote_version": remote_version,
            "message": f"当前版本 {local_version} 已是最新，无需升级。",
        }}))
        return

    # Build authenticated remote URL
    if upgrade_user:
        auth_url = upgrade_repo.replace("https://", f"https://{upgrade_user}:{upgrade_token}@")
    else:
        auth_url = upgrade_repo.replace("https://", f"https://x-access-token:{upgrade_token}@")

    # Set remote URL with credentials and pull
    try:
        subprocess.run(
            ["git", "remote", "set-url", "origin", auth_url],
            cwd=repo_path, check=True, capture_output=True, text=True,
        )
        result = subprocess.run(
            ["git", "pull", "--ff-only"],
            cwd=repo_path, capture_output=True, text=True, timeout=60,
        )

        # Restore remote URL without credentials (security)
        subprocess.run(
            ["git", "remote", "set-url", "origin", upgrade_repo],
            cwd=repo_path, check=True, capture_output=True, text=True,
        )

        if result.returncode != 0:
            sys.stdout.write(json.dumps({"output": {
                "upgraded": False,
                "error": "git_pull_failed",
                "message": f"git pull 失败：{result.stderr.strip()}",
            }}))
            return

        # Re-read version after pull
        new_config = _read_config(repo_path)
        new_version = str(new_config.get("version", local_version))

        # Copy SKILL.md to skill entry (same as install script)
        skill_dir = Path(repo_path).parent / "skills" / "pivot"
        if skill_dir.exists():
            import shutil
            shutil.copy2(Path(repo_path) / "SKILL.md", skill_dir / "SKILL.md")

        sys.stdout.write(json.dumps({"output": {
            "upgraded": True,
            "old_version": local_version,
            "new_version": new_version,
            "message": f"✅ 已从 {local_version} 升级到 {new_version}。请开启新会话以加载最新版本。",
        }}))

    except subprocess.TimeoutExpired:
        sys.stdout.write(json.dumps({"output": {
            "upgraded": False,
            "error": "timeout",
            "message": "git pull 超时，请稍后重试。",
        }}))
    except Exception as e:
        sys.stdout.write(json.dumps({"output": {
            "upgraded": False,
            "error": "exception",
            "message": f"升级异常：{str(e)}",
        }}))


if __name__ == "__main__":
    main()
