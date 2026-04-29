# 团队日报 · 部署 + 调试速查

每天 09:30 (Asia/Shanghai) 自动跑一次,统计前一天 09:30 到今天 09:30 这 24h 内团队的 matter 活动 + 代码 commits,用 AI 评分总结,以飞书群卡片形式广播。

设计 / 实施细节见:
- `AI-docs/daily-report/product-design.md`
- `AI-docs/daily-report/implementation-plan.md`

---

## 1. 一次性部署 setup

### 1.1 部署最新代码到生产服

按现有部署流程把代码部署到 `/opt/team-pivot-web/`(rsync / 各位负责人惯用方式)。

### 1.2 创建代码仓库 mirror workspace

`/opt/team-pivot-web` 是 rsync-deployed,**没有 `.git`**,没法 `git log`。日报需要单独的代码仓库 mirror。

```bash
# 用一个 readonly PAT (scope: contents:read on team-pivot-web)
sudo mkdir -p /opt/team-pivot-web/var/code-mirror
sudo chown ubuntu:ubuntu /opt/team-pivot-web/var/code-mirror
cd /opt/team-pivot-web/var/code-mirror

git clone https://<readonly_token>@github.com/hashSTACS-Global/team-pivot-web.git
# .git/config 里嵌入 token,后续 fetch 自动认证
```

校验:`ls team-pivot-web/.git/HEAD` 应输出 `ref: refs/heads/main`。

### 1.3 设置飞书群

确认 Pivot 飞书 bot **已被拉进**预期接收日报的所有群。日报会广播给 bot 在的**所有**群(没有白名单/黑名单配置)。

### 1.4 安装 systemd unit

```bash
cd /opt/team-pivot-web
sudo cp scripts/daily-report/systemd/team-pivot-daily-report.service.example \
        /etc/systemd/system/team-pivot-daily-report.service
sudo cp scripts/daily-report/systemd/team-pivot-daily-report.timer.example \
        /etc/systemd/system/team-pivot-daily-report.timer

# 改 User / 路径(若不是 ubuntu / /opt/team-pivot-web)
sudo nano /etc/systemd/system/team-pivot-daily-report.service

sudo systemctl daemon-reload
sudo systemctl enable --now team-pivot-daily-report.timer

# 确认下次触发时间
systemctl list-timers | grep daily-report
```

---

## 2. 验证流程

### 2.1 dry-run 调试(不发飞书,不调 AI)

```bash
cd /opt/team-pivot-web
uv run python scripts/daily-report/run.py \
    --dry-run --no-ai \
    --since 2026-04-26T09:30:00+08:00 \
    --until 2026-04-27T09:30:00+08:00 \
    --report-out /tmp/daily-report-debug.json
```

stdout 是即将发送的 card JSON;`/tmp/daily-report-debug.json` 含完整 debug 数据(window / 数量 / fetch_warning 等)。

### 2.2 dry-run 含 AI 调用(仍不发飞书)

```bash
uv run python scripts/daily-report/run.py --dry-run \
    --since 2026-04-26T09:30:00+08:00 \
    --until 2026-04-27T09:30:00+08:00
```

stdout card JSON 中 `template=blue` + 评分块完整 → AI 路径正常。
若 `template=wathet` + 含"⚠️ AI 评分缺失"提示 → 看日志看 fallback_reason 排错。

### 2.3 手工立刻触发(不等 09:30)

```bash
sudo systemctl start team-pivot-daily-report.service
sudo journalctl -u team-pivot-daily-report.service -n 50 --no-pager
```

每个群应该收到一张卡片。

---

## 3. 配置(SQLite settings)

只 3 个 key,通过 SQL 直改即可(管理 UI 留迭代):

| Key | 默认 | 说明 |
|---|---|---|
| `daily_report.enabled` | `"1"` | `"0"` 临时停推日报(脚本退出码 0,不让 systemd timer failed) |
| `daily_report.commit_author_overrides` | `"{}"` | JSON `{"<pinyin>": ["alt-email1", "alt-email2"]}`,人工修正 commit 归属 |
| `daily_report.code_repo_dir` | `/opt/team-pivot-web/var/code-mirror/team-pivot-web` | 代码仓库 mirror 本地路径(若你放别处需改这里) |

```bash
# 临时停推日报
sqlite3 /opt/team-pivot-web/var/data.db \
  "INSERT OR REPLACE INTO settings(key, value, updated_at)
   VALUES('daily_report.enabled', '0', strftime('%s','now'))"

# 补 commit author override(发现"未识别 commits"后)
sqlite3 /opt/team-pivot-web/var/data.db \
  "INSERT OR REPLACE INTO settings(key, value, updated_at)
   VALUES('daily_report.commit_author_overrides',
          '{\"huangshengli\": [\"captain.ronly@gmail.com\"]}',
          strftime('%s','now'))"
```

---

## 4. 排错速查

### 飞书没收到日报

1. `systemctl list-timers | grep daily-report` → 确认 timer 启用且下次触发时间正常
2. `sudo journalctl -u team-pivot-daily-report.service -n 100 --no-pager` → 看日志 / 报错
3. `tail -200 /opt/team-pivot-web/var/log/daily-report.log` → 看应用日志
4. `sqlite3 ... 'SELECT value FROM settings WHERE key="daily_report.enabled"'` → 确认未被禁用
5. 飞书 bot 是否在那个群里?

### "代码仓库未刷新" 警告一直出现

1. `cd /opt/team-pivot-web/var/code-mirror/team-pivot-web && git fetch --all --prune`
2. 看 fetch 报错,通常是 token 过期 / 网络
3. 重新 setup mirror(改 `.git/config` 或重 clone)

### "未识别 commits N 个" 一直显示

1. `bash -c "cd /opt/team-pivot-web/var/code-mirror/team-pivot-web && git log --all --since=24h --pretty='%ae|%an'"` 看 author 形态
2. 在 `daily_report.commit_author_overrides` JSON 里加映射

### AI 评分降级一直出现

1. 看日志的 `fallback_reason`
2. `parse_error` → AI 模型可能输出非 JSON,试换更听话的模型
3. `ai_error: AIError: ...` → API key 失效 / 网络 / 配额
4. `TimeoutError` → 提高 `oneshot.generate_text` 的 `timeout_seconds`(目前硬编码 90s)

### 临时停推

```bash
sudo systemctl stop team-pivot-daily-report.timer    # 暂停 timer
# 或
sqlite3 /opt/team-pivot-web/var/data.db \
  "UPDATE settings SET value='0' WHERE key='daily_report.enabled'"
```

---

## 5. 与其它 scripts/ 的关系

- `scripts/migration-test/` — 历史迁移测试(已用过)
- `scripts/migration-prod/` — 历史迁移生产上线(已用过)
- **`scripts/daily-report/`** — 本目录,定时任务

三个目录互相独立。
