"""Upgrade pipeline: re-clone and install the latest version.

Since the skill directory contains only copied files (no .git), upgrading
works by re-running the install script which clones to a tmp dir, copies
the needed files, and cleans up.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import yaml


def _read_config(skill_path: str) -> dict:
    """Read pivot.yaml (version info)."""
    config_file = Path(skill_path) / "pivot.yaml"
    if not config_file.exists():
        return {}
    with open(config_file, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _get_remote_version(repo_url: str) -> str | None:
    """Fetch version from remote pivot.yaml."""
    try:
        raw_url = repo_url.replace("github.com", "raw.githubusercontent.com").rstrip(".git") + "/main/pivot.yaml"
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

    # Locate skill directory: app-runner.py is at skills/team-pivot/bin/,
    # so the pipeline cwd is skills/team-pivot/pipelines/upgrade/.
    # Walk up to find skill root (where pivot.yaml lives).
    pipeline_dir = Path(os.getcwd())
    skill_dir = pipeline_dir.parent.parent  # pipelines/upgrade → skills/team-pivot

    project_info = _read_config(str(skill_dir))
    local_version = str(project_info.get("version", "0.0.0"))
    upgrade_repo = project_info.get("upgrade_repo", "https://github.com/hashSTACS-Global/team-pivot.git")

    # Check remote version
    remote_version = _get_remote_version(upgrade_repo)

    if remote_version and remote_version != "unknown" and not _version_lt(local_version, remote_version):
        sys.stdout.write(json.dumps({"output": {
            "upgraded": False,
            "local_version": local_version,
            "remote_version": remote_version,
            "message": f"当前版本 {local_version} 已是最新，无需升级。",
        }}))
        return

    # Determine tenant root from skill_dir path: .../tenants/{id}/skills/team-pivot
    tenant_root = skill_dir.parent.parent  # skills/team-pivot → tenant root
    tmp_dir = tenant_root / "tmp" / "team-pivot"

    try:
        # Clone to tmp
        if tmp_dir.exists():
            subprocess.run(["rm", "-rf", str(tmp_dir)], check=True)

        # If upgrade_repo needs auth, read token from pivot-config.yaml
        data_dir = Path(os.environ.get("PIVOT_DATA_DIR", "")) or (tenant_root / "workspace" / "skill-team-pivot")
        user_config_file = data_dir / "pivot-config.yaml"
        user_config = {}
        if user_config_file.exists():
            with open(user_config_file, encoding="utf-8") as f:
                user_config = yaml.safe_load(f) or {}
        upgrade_token = user_config.get("upgrade_token", "")

        clone_url = upgrade_repo
        if upgrade_token:
            clone_url = upgrade_repo.replace("https://", f"https://x-access-token:{upgrade_token}@")

        tmp_dir.parent.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(
            ["git", "clone", "--depth", "1", clone_url, str(tmp_dir)],
            capture_output=True, text=True, errors="replace", timeout=60,
        )
        if result.returncode != 0:
            sys.stdout.write(json.dumps({"output": {
                "upgraded": False,
                "error": "git_clone_failed",
                "message": f"git clone 失败：{result.stderr.strip()}",
            }}))
            return

        # Run the install script (it handles copying files and cleanup)
        result = subprocess.run(
            ["bash", str(tmp_dir / "bin" / "pivot-app-install.sh")],
            capture_output=True, text=True, errors="replace", timeout=120,
            cwd=str(skill_dir),  # pwd must be under .enclaws/tenants/{id}/
        )

        if result.returncode != 0:
            sys.stdout.write(json.dumps({"output": {
                "upgraded": False,
                "error": "install_failed",
                "message": f"安装脚本执行失败：{result.stderr.strip()}\n{result.stdout.strip()}",
            }}))
            return

        # Re-read version after upgrade
        new_config = _read_config(str(skill_dir))
        new_version = str(new_config.get("version", local_version))

        sys.stdout.write(json.dumps({"output": {
            "upgraded": True,
            "old_version": local_version,
            "new_version": new_version,
            "install_log": result.stdout.strip(),
            "message": f"✅ 已从 {local_version} 升级到 {new_version}。请开启新会话以加载最新版本。",
        }}))

    except subprocess.TimeoutExpired:
        sys.stdout.write(json.dumps({"output": {
            "upgraded": False,
            "error": "timeout",
            "message": "升级超时，请稍后重试。",
        }}))
    except Exception as e:
        sys.stdout.write(json.dumps({"output": {
            "upgraded": False,
            "error": "exception",
            "message": f"升级异常：{str(e)}",
        }}))
    finally:
        # Cleanup tmp (install script should have done this, but just in case)
        if tmp_dir.exists():
            subprocess.run(["rm", "-rf", str(tmp_dir)], check=False)
        try:
            (tenant_root / "tmp").rmdir()
        except OSError:
            pass


if __name__ == "__main__":
    main()
