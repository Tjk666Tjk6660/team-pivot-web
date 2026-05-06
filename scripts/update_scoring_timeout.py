#!/usr/bin/env python3
"""更新评分超时配置为 180 秒（3分钟）"""

import os
import sys
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from server.config import Config
from server.db import Database
from server.settings import SettingsRepo


def main():
    config = Config()
    db = Database(config.db_path)
    settings = SettingsRepo(db)
    
    old_value = settings.get("scoring.timeout_seconds")
    print(f"当前评分超时配置: {old_value} 秒")
    
    settings.set("scoring.timeout_seconds", "180")
    new_value = settings.get("scoring.timeout_seconds")
    print(f"已更新为: {new_value} 秒")
    print("\n✅ 评分超时配置已更新为 180 秒（3分钟）")


if __name__ == "__main__":
    main()
