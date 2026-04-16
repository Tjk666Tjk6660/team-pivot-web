"""Check if required external tools are available."""
from __future__ import annotations

import json
import platform
import shutil
import sys


TOOLS = [
    {
        "name": "python3",
        "purpose": "Pipeline runner 的运行时",
        "install_hint": {
            "macos": "系统自带或 brew install python3",
            "linux": "apt install python3",
        },
    },
    {
        "name": "git",
        "purpose": "数据仓库的版本管理",
        "install_hint": {
            "macos": "brew install git 或安装 Xcode Command Line Tools",
            "linux": "apt install git",
        },
    },
    {
        "name": "pandoc",
        "purpose": "将 Word 文档（.docx/.doc）转为 Markdown 草稿",
        "install_hint": {
            "macos": "brew install pandoc",
            "linux": "apt install pandoc",
        },
    },
    {
        "name": "pdftotext",
        "purpose": "将 PDF 文档转为 Markdown 草稿",
        "install_hint": {
            "macos": "brew install poppler",
            "linux": "apt install poppler-utils",
        },
    },
]


def main():
    json.loads(sys.stdin.read())  # payload not used

    system = platform.system().lower()
    platform_key = "macos" if system == "darwin" else "linux"

    available = []
    missing = []
    for tool in TOOLS:
        if shutil.which(tool["name"]):
            available.append(tool["name"])
        else:
            missing.append({
                "name": tool["name"],
                "purpose": tool["purpose"],
                "install_hint": tool["install_hint"].get(platform_key, tool["install_hint"]["linux"]),
            })

    sys.stdout.write(json.dumps({
        "output": {
            "available": available,
            "missing": missing,
            "all_ready": len(missing) == 0,
        }
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
