# Pivot 团队日报 · 实施计划

> 配套产品文档:[`product-design.md`](./product-design.md)
> 评审通过后才进入实施。本文档描述工程实现细节、模块切分、测试覆盖、部署路径。

## Context

每天 09:30 (Asia/Shanghai) 自动跑一次,统计前一天 09:30 到今天 09:30 这 24h 内团队的工作活动,用 AI 评分总结,以飞书群卡片形式广播到所有 bot 所在的飞书群。产品定位与目标见 [`product-design.md`](./product-design.md)。

**MVP 定位**:本次实施按 MVP 标准——先跑出能用的版本上生产收集真实反馈,再迭代。文档里标的 trade-off 都是有意保留的简化,不在 MVP 阶段预先优化。

**两个数据源(独立呈现,MVP 不交叉归并)**:
1. **Matter 数据仓库**(`/opt/team-pivot-web/var/git/<repo>/index/*.index.yaml`) —— timeline 事件 = 用户工作行为
2. **代码仓库 mirror**(独立 clone 在 `/opt/team-pivot-web/var/code-mirror/team-pivot-web/`,见 §"代码仓库 mirror workspace") —— 全分支 `git log`

**评分**:5 星制(0.5 步进),团队 + 个人,4 维度子分(产出量/推进结果/阻塞情况/协作密度)

**部署**:独立 systemd timer + 一次性脚本(类似 `scripts/migration-prod/`),与主服务隔离

**MVP 不做**:不写回 matter / 不做 commit ↔ matter 归并 / 不支持人为豁免成员(留迭代,不在 MVP 阶段考虑)

---

## 模块结构

```
scripts/daily-report/
├── README.md                                       # 部署 + 调试 + 排错速查
├── run.py                                          # CLI 入口
└── systemd/
    ├── team-pivot-daily-report.service.example
    └── team-pivot-daily-report.timer.example

server/daily_report/
├── __init__.py
├── types.py                                        # dataclasses (TimeWindow / MatterEvent / CommitRecord / UserActivity / TeamReport / ScoringResult / UserScore)
├── window.py                                       # compute_window(now) → TimeWindow
├── collect_matter.py                               # collect_matter_events(index_dir, window) → list[MatterEvent]
├── collect_git.py                                  # collect_commits(repo_dir, window) → list[CommitRecord]
├── attribution.py                                  # attribute_commits(commits, users, overrides) → (matched, unmatched)
├── aggregate.py                                    # aggregate(events, commits, users, window) → (UserActivity[], TeamSummary)
├── score.py                                        # score_team(activities, summary, ai_settings, no_ai) → ScoringResult
├── render.py                                       # build_daily_report_card(report) → dict (无 CTA button)
├── runner.py                                       # generate_and_send(now, dry_run, no_ai, report_out) → int
├── config_keys.py                                  # KEY_ENABLED / KEY_OVERRIDES
└── tests/                                          # 见下方测试矩阵

server/git_ops.py                                   # 新增 log_commits(repo_dir, since, until, branches='--all')
server/ai/oneshot.py                                # 新文件:generate_text(messages, model, api_key, base_url, timeout) → str
server/users.py                                     # 新增 UserRepo.list_all() → list[User]
server/notify.py                                    # 新增 public broadcast_card(card, *, event)(对 _broadcast 的薄封装)
```

---

## 复用的现有函数 / 工具(不要重写)

| 用途 | 函数 | 路径 |
|---|---|---|
| 飞书群广播(枚举 bot 所在群,发卡) | `FeishuNotifier._broadcast(card, *, event)` | `server/notify.py:267` |
| 卡片框架(标题/template/markdown/button) | `_card_shell(header, template, markdown, button_text, thread_url, ...)` | `server/notify.py:636` |
| 飞书 token 管理 | `FeishuTokenManager.get()` | `server/feishu_token.py` |
| 配置读写(SQLite K-V) | `SettingsRepo.get/set` | `server/settings.py` |
| Matter index 读取(返回 dict) | `read_matter_index(path)` | `server/matter_index.py:73` |
| Matter index 路径构造 | `matter_index_path(index_dir, matter_id)` | `server/matter_index.py:64` |
| AI 流式调用(被同步包装复用) | `stream_chat(messages, model, api_key, base_url, tools=None)` | `server/ai/client.py:20` |
| AI 配置加载 | `_KEY_API_KEY / _KEY_BASE_URL / _KEY_MODEL / _KEY_MAX_CONTEXT_TOKENS` | `server/api/ai.py:29-32` |
| Workspace 运行时(拿 path / index_dir) | `WorkspaceRuntime` | `server/workspace_runtime.py` |
| 用户单条查询(按 pinyin 反查) | `UserRepo.get_by_any_id(id_)` | `server/users.py:67` |
| 同款独立脚本结构参考 | `scripts/migration-prod/run.py` 等 | 整个目录 |

---

## 关键实现要点

### 时间窗口
- 用 `zoneinfo.ZoneInfo("Asia/Shanghai")`,**不**用 hardcode `+08:00`
- 半开区间 `[since, until)`,默认 `since = (now - 1d).replace(hour=9, minute=30, second=0, microsecond=0)`,`until = since + 24h`
- CLI 接 `--since/--until` ISO8601 覆盖默认值,方便手动回放

### 代码仓库 mirror workspace(关键前置依赖)

详见 [`product-design.md`](./product-design.md) §3.3。MVP 阶段固化的工程口径如下。

**部署一次性 setup**(见 `scripts/daily-report/README.md`):

```bash
sudo mkdir -p /opt/team-pivot-web/var/code-mirror
sudo chown ubuntu:ubuntu /opt/team-pivot-web/var/code-mirror
cd /opt/team-pivot-web/var/code-mirror

# 用一个 readonly PAT (scope: contents:read on team-pivot-web)
git clone https://<readonly_token>@github.com/<org>/team-pivot-web.git
# .git/config 里嵌入 token,后续 fetch 自动认证
```

**runner 起手**:

```python
# runner.py
def _fetch_code_mirror(code_repo_dir: Path) -> str | None:
    """fetch --all --prune;失败返回原因字符串,卡片用以标'代码仓库未刷新';
    成功返回 None。**不让 fetch 失败导致日报整体失败**。"""
    try:
        subprocess.run(
            ["git", "-C", str(code_repo_dir), "fetch", "--all", "--prune"],
            check=True, capture_output=True, text=True, timeout=60,
        )
        return None
    except subprocess.CalledProcessError as e:
        log.warning("code mirror fetch failed: %s", e.stderr.strip()[:200])
        return f"git fetch 失败:{e.stderr.strip()[:80]}"
    except subprocess.TimeoutExpired:
        log.warning("code mirror fetch timed out")
        return "git fetch 超时"
```

`code_repo_dir` 从 `daily_report.code_repo_dir` settings 读,默认 `/opt/team-pivot-web/var/code-mirror/team-pivot-web`。

后续 `collect_git.py::collect_commits(code_repo_dir, window)` 用同一个路径跑 `git log --all`。

### Author 匹配(`attribution.py`,从严到松,不命中即"未识别")

**前提**:日报只对 `team-pivot-web`(代码仓库) commits 做 attribution。`pivot-database`(matter 数据仓库)的活动归属直接来自 matter index 里的 `creator` / `owner`,**不**走 git log 路径,所以不需要匹配。

代码仓库的 commit 身份**完全由用户本地 git config 决定**,可以是任何形态:
- `git config user.name` 可能是 pinyin、github_username、中文名,或者随便写的什么
- `git config user.email` 可能是公司邮箱、私人邮箱、GitHub noreply、本地伪邮箱

所以匹配必须**对名字与邮箱都做多通道反查**。优先级:

1. **manual override**:settings 里 `daily_report.commit_author_overrides` JSON `{"pinyin": ["alt-email1", ...]}` → 反向表精确匹配 `commit.author_email`
2. **GitHub noreply**:正则 `\d+\+(\w+)@users\.noreply\.github\.com` 提取 username 后,反查 `users.github_username`(忽略大小写)
3. **author_name == users.pinyin**(精确)
4. **author_name == users.github_username**(精确,忽略大小写)
5. **author_name == users.name**(精确,中文也走)
6. **email local part == users.pinyin**(取 `@` 前面那段精确匹配,适配 `pinyin@stacs.cn` 这种)
7. **email local part == users.github_username**(同上)
8. 都未命中 → 进 `unattributed_commits` 桶,卡片末尾单独列总数(**不**做模糊 / substring 匹配,避免错算)

冲突处理:同一条 commit 命中多个 user 时,按上面优先级取**第一个匹配**,并 log warning;debug 时可以从 log 里看到要不要补 override。

### AI 评分接口(`score.py` + `ai/oneshot.py`)
- `oneshot.generate_text` 是 `stream_chat` 的同步包装:`asyncio.run(asyncio.wait_for(_collect_text(stream_chat(...)), 90))`
- 输入给 AI 的是**精简后的 JSON**(per_user 摘要、不喂 raw timeline,避免 token 爆)
- AI prompt 强约束输出严格 JSON schema(team / per_user / inactive),**容错剥离 ```json``` 包裹**
- 解析失败 / score 越界 / 缺字段 → 全部走 `_fallback_scoring`(team 评 3.0 中性,per_user 按 `len(file_creates)+len(commits)` 给粗分)
- `ScoringResult.status` 字段标记 `"ai" | "fallback"`,卡片明显标注降级

### 卡片渲染(`render.py`)
- 复用 `_card_shell`,`directory_content` 传 `None`,`button_text` / `thread_url` 也都不传
  (日报与 Pivot 主站点解耦,管理端目前没有任何页面支持这个任务,放按钮指向首页是无意义的)
- header:`📊 团队日报 · {month}-{day}`(覆盖日期 = since 的日期)
- template:`"blue"`(AI 评分模式) / `"wathet"`(降级模式)
- markdown 块顺序:窗口标识 → 团队总览统计 → 团队评分 + AI 总结 → 个人评分列表(按总分降序)→ 0 活动用户 → 未识别 commits 统计

### Runner(`runner.py`)
- bootstrap 路径:`Database` → `SettingsRepo` → `WorkspaceRuntime` → `UserRepo`(**不**起 FastAPI)
- `KEY_ENABLED=0` → 退出码 0 + log INFO,**不**报错(让管理员可临时停推但不让 systemd timer 失败告警)
- workspace 未配置 → 退出码 2 + log ERROR
- 全员 0 活动 → **仍然发卡**,标注"今日团队无活动"(让管理层确认脚本活着,不是没收到)
- 飞书发送失败 → 退出码 1(systemd timer 显示 failed,触发监控)

### Notify 公共接口
- 在 `server/notify.py` 加一个 `def broadcast_card(self, card: dict, *, event: str)`(就是 `_broadcast` 的 alias),让日报、周报这种"任意卡片群发"用例不再依赖 underscore-private API

---

## 配置(SQLite settings)

3 个 key 当前消费 + 1 个 key 留作未来开关:

| Key | 类型 | 默认 | 说明 |
|---|---|---|---|
| `daily_report.enabled` | bool | `"1"` | `"0"` 时 runner 退出码 0,跳过执行 |
| `daily_report.commit_author_overrides` | JSON | `{}` | `{"pinyin": ["alt-email1", "alt-email2"]}`,人工修正 author 匹配 |
| `daily_report.code_repo_dir` | string | `/opt/team-pivot-web/var/code-mirror/team-pivot-web` | 代码仓库 mirror workspace 的本地路径(见产品文档 §3.3)。`/opt/team-pivot-web` 本身**不是 git 仓库**(rsync 部署),日报必须用独立 mirror。runner 起手 `git fetch --all --prune`(失败容错继续) |
| `daily_report.allow_ai_read_body` | bool | `"0"` | **stub,MVP 不消费**。预留给 v0.x 的 AI tool-use 路径(见产品 §六 trade-off / §七 第 8 条)。`config_keys.KEY_ALLOW_AI_READ_BODY` 已声明;实施 tool-use 时直接消费即可,届时无需新增 key |

不存 chat_id(走 `_broadcast` 全群)、不存触发时间(systemd timer 决定)、不存豁免名单(产品上禁止)。

---

## systemd Unit(部署在 `/etc/systemd/system/`)

```ini
# team-pivot-daily-report.service
[Unit]
Description=team-pivot-web Daily Report (24h window)
After=network-online.target team-pivot-web.service

[Service]
Type=oneshot
User=ubuntu
Group=ubuntu
WorkingDirectory=/opt/team-pivot-web
EnvironmentFile=/opt/team-pivot-web/.env
ExecStart=/home/ubuntu/.local/bin/uv run python scripts/daily-report/run.py
StandardOutput=append:/opt/team-pivot-web/var/log/daily-report.log
StandardError=append:/opt/team-pivot-web/var/log/daily-report.log
TimeoutStartSec=600
```

```ini
# team-pivot-daily-report.timer
[Unit]
Description=Trigger team-pivot-web daily report at 09:30 every day
Requires=team-pivot-daily-report.service

[Timer]
OnCalendar=*-*-* 09:30:00 Asia/Shanghai
AccuracySec=30s
Persistent=true                        # 关机过夜后开机补一次
Unit=team-pivot-daily-report.service

[Install]
WantedBy=timers.target
```

模板文件存 `scripts/daily-report/systemd/*.example`,部署时 `cp` + `systemctl daemon-reload` + `systemctl enable --now team-pivot-daily-report.timer`。

---

## 测试矩阵(`server/daily_report/tests/`)

| 测试文件 | 覆盖 |
|---|---|
| `test_window.py` | 默认窗口推算、跨月、闰年、夏令时(虽然中国不用)边界 |
| `test_collect_matter.py` | fake yaml,timeline + comments 双重过滤;creator==open_id 兜底 |
| `test_collect_git.py` | fake `git log` parsing,含 shortstat 空行、含逗号 email、合并 commit |
| `test_runner_fetch_failure.py` | mock `_fetch_code_mirror` 返回失败原因,runner 不退出且 TeamReport 携带 fetch_warning |
| `test_attribution.py` | 8 级匹配各自命中(override / GitHub noreply / name == pinyin/github/中文 / email local part == pinyin/github)+ 全 miss;同 commit 命中多 user 时取首个 + log warning |
| `test_aggregate.py` | UserActivity 的 file_creates/file_owns 不重复,verify 反向计数 |
| `test_score.py` | mock `generate_text`:正常 JSON / 缺字段 / 非 JSON / score 越界 → 全部 fallback;`no_ai` 也 fallback |
| `test_render.py` | 卡片关键字段(header/统计/评分块/inactive 列表/unattributed 计数)及 AI/fallback template 颜色不同 |
| `test_runner_smoke.py` | 端到端 dry-run:fake workspace + fake users + fake AI,产出 dict 不抛 |

不写实发飞书的 e2e。

---

## 实施顺序(依赖序,可按 PR 拆分)

1. `server/git_ops.py::log_commits` + 单测
2. `server/users.py::UserRepo.list_all` + 单测
3. `server/ai/oneshot.py::generate_text` + 单测(mock httpx)
4. `server/notify.py::FeishuNotifier.broadcast_card`(public alias)+ 单测
5. `server/daily_report/types.py` + `window.py` + 单测
6. `collect_matter.py` + `collect_git.py` + 单测
7. `attribution.py` + 单测
8. `aggregate.py` + 单测
9. `score.py` + 单测(mock AI)
10. `render.py` + 单测(快照式)
11. `runner.py` 串起来 + smoke 测
12. `scripts/daily-report/run.py` CLI 包装
13. systemd unit example + README + 测试服 dry-run 跑一周
14. 切生产

---

## 部署 / 验证流程(scripts/daily-report/README.md 必含)

### 前置:setup 代码仓库 mirror(只做一次)
```bash
sudo mkdir -p /opt/team-pivot-web/var/code-mirror
sudo chown ubuntu:ubuntu /opt/team-pivot-web/var/code-mirror
cd /opt/team-pivot-web/var/code-mirror
git clone https://<readonly_token>@github.com/<org>/team-pivot-web.git
ls team-pivot-web/.git/HEAD                    # 应输出 ref: refs/heads/main
```

### 测试服跑一遍(无 AI,无飞书发送)
```bash
cd /opt/team-pivot-web                          # 仅 cd 到部署目录(用于读 .env)
uv run python scripts/daily-report/run.py --dry-run --no-ai \
    --since 2026-04-26T09:30:00+08:00 \
    --until 2026-04-27T09:30:00+08:00 \
    --report-out /tmp/daily-report-debug.json
```
检查 `/tmp/daily-report-debug.json` 数据结构;`--dry-run` 把卡片 JSON 打到 stdout。**默认会去 `/opt/team-pivot-web/var/code-mirror/team-pivot-web` fetch 最新 commits**;若该 mirror 不存在或 fetch 失败,日报会带 `⚠️ 代码仓库未刷新` 提示但仍出卡。

### 测试服跑一遍 AI 评分(仍不发飞书)
```bash
uv run python scripts/daily-report/run.py --dry-run \
    --since ... --until ...
```
检查 stdout 卡片 JSON 里 `template=blue` + 评分块齐全。

### 接 systemd timer
```bash
sudo cp scripts/daily-report/systemd/*.example \
        /etc/systemd/system/team-pivot-daily-report.{service,timer}
sudo nano /etc/systemd/system/team-pivot-daily-report.service   # 改 User/路径
sudo systemctl daemon-reload
sudo systemctl enable --now team-pivot-daily-report.timer
systemctl list-timers | grep daily-report                       # 确认下次触发时间
```

### 手动跑一次(立刻发飞书,不等 09:30)
```bash
sudo systemctl start team-pivot-daily-report.service
journalctl -u team-pivot-daily-report.service -n 50
```

### 临时停推
在 `/admin` 设置或直接 SQL:
```sql
UPDATE settings SET value='0' WHERE key='daily_report.enabled';
```
(或 systemd 关:`sudo systemctl stop team-pivot-daily-report.timer`)

---

## 已知潜在坑(README 写明)

- **`git log --all`** 可能拉到 stale remote 分支引入冗余 commit:部署后用 `git for-each-ref refs/remotes/` 看实际数,如果太多可改成 `git log refs/heads/main refs/remotes/origin/main`
- **`comments[].created_at`** 在迁移过的老 matter index 里可能为空字符串:解析时 `dt = parse(c.get('created_at') or item.created_at)` 兜底
- **`creator/owner == open_id`(未注册用户)的 file 事件**:计入 `team_summary.total_files` 但不归到任何 pinyin 个人统计 —— 跟"个人=已注册用户"配置最少化原则一致
- **AI 输出偶尔包 ```json``` markdown**:`_parse_strict_json` 容错剥离前后缀,不要为这种小问题强制 fallback
- **systemd `OnCalendar=*-*-* 09:30:00 Asia/Shanghai`** 需要 systemd ≥ 244,Ubuntu 20.04+ 都满足

---

## 关键文件路径(实施时编辑)

**新建**:
- `server/daily_report/__init__.py`
- `server/daily_report/types.py`
- `server/daily_report/window.py`
- `server/daily_report/collect_matter.py`
- `server/daily_report/collect_git.py`
- `server/daily_report/attribution.py`
- `server/daily_report/aggregate.py`
- `server/daily_report/score.py`
- `server/daily_report/render.py`
- `server/daily_report/runner.py`
- `server/daily_report/config_keys.py`
- `server/daily_report/tests/test_*.py`
- `server/ai/oneshot.py`
- `scripts/daily-report/run.py`
- `scripts/daily-report/README.md`
- `scripts/daily-report/systemd/team-pivot-daily-report.service.example`
- `scripts/daily-report/systemd/team-pivot-daily-report.timer.example`

**修改**:
- `server/git_ops.py`(加 `log_commits`)
- `server/users.py`(加 `UserRepo.list_all`)
- `server/notify.py`(加 public `broadcast_card`)
- `AI-docs/pivot-memo.md`(在 §3 目录结构补 `server/daily_report/` 与 `scripts/daily-report/`,§8 功能完成情况里加日报)
