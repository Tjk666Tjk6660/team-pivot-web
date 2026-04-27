# 索引迁移上线 · 操作手册

本文档面向**执行迁移上线**的运维操作员。设计依据见 `index-migration-plan.md`(本目录),本手册只讲怎么跑、怎么验证、怎么回滚。

按 §A → §B → §C 顺序执行;任何一步失败前往 §F 回滚,**不要**强行往下走。

---

## §A 前置准备(上线前 1–2 小时)

### A.1 工具与权限

| 项 | 说明 |
|---|---|
| 测试机 | 物理机 / VM / 容器,与生产 Pivot 实例**不共享磁盘 / SQLite** |
| 运行依赖 | `uv` / `python 3.12` / `git` / `node` / `npm` 都可用;team-pivot-web 代码 checkout 在含 `scripts/migrate_index_schema.py` 的分支(默认是含本次迁移的 main commit) |
| 生产仓库只读 token | GitHub PAT,scope 仅 `repo:read`,**不要授 push** |
| 测试仓库写 token | 后续步骤创建测试仓库时使用,需 `repo` 全权限 |
| 飞书机器人 | 上线前可临时停推,避免迁移期间产生新数据(可选) |

### A.2 创建空测试仓库

GitHub 网页 Create new repository:

- 名字:`<生产 repo 名>-migration-test`(明示用途)
- visibility:`private`
- **不要**勾任何 init template / README / gitignore / license——保持完全空仓库,否则下一步 `push --mirror` 会冲突

记下完整 URL:`https://github.com/<org>/<生产 repo 名>-migration-test.git`。

### A.3 镜像生产 history 到测试仓库

在测试机或任何能访问 GitHub 的机器上跑:

```bash
git clone --bare \
    "https://<readonly_token>@github.com/<org>/<生产 repo 名>.git" \
    /tmp/prod-mirror.git

cd /tmp/prod-mirror.git

git remote add migration-test \
    "https://<write_token>@github.com/<org>/<生产 repo 名>-migration-test.git"

git push --mirror migration-test
```

**校验**:GitHub 网页打开测试仓库,最新 commit hash 应等于生产 main 的 head;branches / tags 全部继承。

### A.4 启动测试 Pivot 实例

```bash
cd ~/team-pivot-web    # 测试机上的代码副本
cp .env.example .env-migration-test
```

编辑 `.env-migration-test`:
- `FEISHU_APP_ID` / `FEISHU_APP_SECRET` / `SESSION_SECRET` / `WEB_DEV_ORIGIN`:正常填
- `DATA_DIR=./var-migration-test` —— 独立数据目录
- `LOG_LEVEL=DEBUG` —— 便于排查

起后端(端口避开生产):

```bash
mkdir -p var-migration-test/log
PIVOT_ENV_FILE=.env-migration-test \
    uv run uvicorn --factory server.app:create_app --port 8001 \
    2>&1 | tee var-migration-test/log/pivot.log
```

起前端(另一终端):

```bash
cd web && PIVOT_BACKEND_URL=http://localhost:8001 npm run dev
```

打开测试 Pivot 前端 → `/admin` → 输入管理员密码 → **数据仓库配置**:
- `repo_url`:**测试仓库** URL(`<生产 repo 名>-migration-test`)
- `visibility`:`private`
- `write_token` / `readonly_token`:都填测试仓库的写 token
- 保存

确认:`/api/workspace/status` 返回 `ready: true`,`path` 指向 `var-migration-test/git/<生产 repo 名>-migration-test/`。

---

## §B 测试环境演练(上线前 30 分钟)

### B.1 dry-run 预览

```bash
cd ~/team-pivot-web
WS=var-migration-test/git/<生产 repo 名>-migration-test

uv run python scripts/migrate_index_schema.py \
    --workspace "$WS" \
    --report var-migration-test/migration-report-dryrun.json
```

> ⚠️ **mention pinyin 解析的前提**:脚本默认从 `.env` 的 `DATA_DIR` 找 SQLite,该 SQLite 必须含真实 `users` 表(由生产 OAuth 登录写入)。在测试机上跑演练时,本地 `data.db` 通常**没有真实用户**,会导致 `comments[].mentions` 全部兜底为 open_id(`ou_xxx`)。要完整验证 pinyin 转换链路,先把生产 `data.db` 复制只读副本过来,然后用 `--db-path` 显式指向:
>
> ```bash
> # 生产服务器上(只读复制,不动原文件)
> scp prod-server:/pivot/var/data.db /tmp/prod-data-readonly.db
>
> uv run python scripts/migrate_index_schema.py \
>     --workspace "$WS" \
>     --db-path /tmp/prod-data-readonly.db \
>     --report var-migration-test/migration-report-dryrun.json
> ```
>
> 演练完成后清理副本:`rm /tmp/prod-data-readonly.db`。

**预期输出**:

```
[dry-run] workspace = ...
[dry-run] legacy_count=N migrated=0 skipped=0 errors=0
[dry-run] report written to .../migration-report-dryrun.json
```

打开 `migration-report-dryrun.json`,**逐 thread 检查 warnings 段**。

| Warning 文案 | 是否阻塞 | 处理 |
|---|---|---|
| `multiple 'from' refs ... took the first one as quote` | ❌ 不阻塞 | 老数据有多 from 引用,系统取第一条;若需保留所有,人工记录 |
| `mention target ... not in new timeline; dropping` | ❌ 不阻塞 | 历史 mention 指向已删/改名文件;丢弃合理 |
| `mention event without file field` | ❌ 不阻塞 | 老事件流缺字段,丢弃合理 |
| `unparseable legacy filename` | ⚠️ **阻塞** | 非标准命名文件,人工核查 |
| `MD file missing` | ⚠️ **阻塞** | INDEX 引用了不存在的 MD,数据完整性问题 |

如有阻塞类 warning,**不要往下走**,反馈给开发改数据/脚本后再来。

### B.2 apply 落盘到测试仓库

```bash
uv run python scripts/migrate_index_schema.py \
    --workspace "$WS" \
    --apply \
    --report var-migration-test/migration-report-apply.json
```

**预期输出**:

```
[apply] legacy_count=N migrated=N skipped=0 errors=0
```

如 `errors > 0`,前往 §F 回滚。

### B.3 4 项人工核对

打开测试 Pivot 前端,逐项确认:

| 核对项 | 怎么验证 |
|---|---|
| **1. 状态机跳转正确** | 老 status=`concluded` / `produced` 的 thread,在新 Pivot UI 上应显示为 `executing`;timeline 末尾恰有一条 `act` 文件,带 `status_change: planning → executing`。老 status=`closed` 显示为 `cancelled`;`open` / `pending` 显示为 `planning` |
| **2. timeline 已过滤事件** | 任意 matter 的 timeline 视图只列 file item 与其 comments[];没有独立的 `created_thread` / `replied` / `状态变更` 事件条目 |
| **3. MD frontmatter type 与文件名同步** | 在测试仓库 GitHub 网页上抽查 1-2 个 `concluded` 来源 thread:文件列表里没有 `_proposal_` / `_reply_` token,只有 `_think_` / `_act_`;打开 MD 看 frontmatter `type` 字段值与文件名 `_<type>_` 段一致;body 字节级未变 |
| **4. mention 转 comments 完整** | 老 thread 有 `@mention` 评论的:在新 Pivot UI 找到对应 timeline item 的 comments[],应见原 mention 内容;`mentions` 字段对注册用户显示 pinyin,未注册联系人显示 `ou_xxxx` open_id |

若 4 项全 OK,进入 §C。任一不合格 → §F 回滚 + 反馈。

### B.4(可选)git 历史完整性核对

```bash
cd "$WS"
# 抽一个被改名的 MD 验证 rename detection
git log --follow --oneline -- "discussions/<category>/<slug>/001_<author>_think_<hash>.md" | head -5
```

应能跨 rename 看到该文件的全部历史 commit,直到 thread 创建时(原文件名 `_proposal_`)。

---

## §C 生产上线(测试通过后)

### C.1 通知 + 停服

- 通知团队:迁移上线开始,期间 Pivot 服务**停推 / 只读**
- 停掉飞书 bot 推送(避免迁移期间老 thread 又收到新事件)
- 停掉生产 Pivot 服务(或将服务切到 read-only 模式)

### C.2 同步生产仓库到本地工作目录

```bash
# 在生产服务器上
cd /pivot/var/git/<生产 repo 名>/      # 生产 workspace 实际路径
git fetch origin main
git status --porcelain                 # 必须为空
git rev-parse --abbrev-ref HEAD        # 必须是 main
```

### C.3 离线 git bundle 备份(强制)

```bash
mkdir -p /pivot/var/backup
git bundle create \
    /pivot/var/backup/pre-migration-$(date -u +%Y%m%dT%H%M%SZ).bundle \
    --all
```

把 bundle 文件**额外复制到独立位置**(运维 ops 库 / 对象存储),作为 git 仓库本身受损时的最终兜底。

### C.4 生产 dry-run

> ⚠️ **跑前必查**:`cat .env | grep DATA_DIR` 确认 `DATA_DIR` 指向**生产 SQLite 所在目录**(里面的 `data.db` 含真实 users 表)。如果跑错了 SQLite,mention pinyin 解析会跌回 open_id 兜底分支——index 里 `comments[].mentions` 会显示为 `ou_xxx` 而非人名,**不是数据致命错,但运维 / AI 阅读体验会下降**。
>
> 替代方案:用 `--db-path` 显式指定 SQLite 路径,绕开 .env 探测。例如在测试机上跑生产数据演练时,把生产 `data.db` 复制只读副本过来,然后:
> ```bash
> --db-path /tmp/prod-data-readonly.db
> ```

```bash
cd ~/team-pivot-web   # 生产服务器上的 Pivot 代码副本
uv run python scripts/migrate_index_schema.py \
    --workspace /pivot/var/git/<生产 repo 名>/ \
    --report /pivot/var/migration-report-prod-dryrun.json
```

确认 `errors=0`,warnings 与 §B.1 测试环境一致(应该是,因为是同源数据)。

### C.5 生产 apply

```bash
uv run python scripts/migrate_index_schema.py \
    --workspace /pivot/var/git/<生产 repo 名>/ \
    --apply \
    --report /pivot/var/migration-report-prod-apply.json
```

确认 `errors=0`。脚本已自动 `git commit`,**未自动 push**。

### C.6 检查 commit 状态

```bash
cd /pivot/var/git/<生产 repo 名>/
git log -1 --name-status | head -30
```

最近一个 commit:
- message 含 `chore: migrate legacy thread indexes to matter format`
- name-status 应大量出现 `R` 行(改名),少量 `A` 行(新写的 matter yaml),少量 `D` 行(删除的 legacy yaml)
- **不应**出现 MD 文件的 `D + A`(应该被识别成 R)

如果一切正常,进入 C.7;若不正常 → §F 回滚。

### C.7 推送 + 启服

```bash
git push origin main
```

启动生产 Pivot 服务(后端 + 前端),恢复飞书 bot 推送。

### C.8 上线后烟测(执行后 5 分钟内)

| 烟测项 | 验证 |
|---|---|
| Pivot UI 能登录 + 能列出 matter | 浏览器打开生产 URL,登录正常,主页能看到几个迁移后的 matter |
| 抽查迁移产物 | 打开任一原 `concluded` thread,应显示 `executing` 状态,timeline 完整,quote / refer / comments 链路正常 |
| 新建 reply / @mention | 在某个 matter 上发一条 think,正常落盘 + 飞书通知发出 |
| 飞书 bot 历史卡片链接 | **预期失效**——已通知团队,这是已知代价,不是回滚理由 |

烟测通过即上线完成。

---

## §D 上线后清理

### D.1 销毁测试仓库与本地副本

- GitHub 网页删除测试仓库:Settings → Danger Zone → Delete this repository
- 测试机本地清理:
  ```bash
  rm -rf ~/team-pivot-web/var-migration-test/
  rm -rf /tmp/prod-mirror.git
  ```

### D.2 归档 migration-report

把 `migration-report-prod-apply.json` 与 git bundle 一并归档到运维 ops 库,留作审计依据。保留期建议 ≥ 6 个月。

---

## §E 常见问题速查

### E.1 `preflight checks failed: working tree not clean`

- 原因:工作目录有 wip 改动
- 处理:`git status` 看是什么改动,提交或 stash 后重跑;不要混在迁移 commit 里

### E.2 `preflight checks failed: not on main branch`

- 原因:当前分支不是 main
- 处理:`git checkout main` 后重跑

### E.3 `preflight checks failed: origin/main ref not found locally`

- 原因:本地缺少 origin remote 或没 fetch 过
- 处理:`git remote -v` 确认 origin 配好;`git fetch origin main` 后重跑

### E.4 `preflight checks failed: local main is behind origin/main by N commit(s)`

- 原因:测试期间生产仓库有新 commit
- 处理:`git pull --rebase origin main`(确保无 wip 时)后重跑;若有冲突,人工解决

### E.5 `rename target collision: <filename>`

- 原因:迁移目标文件名已存在(数据完整性问题)
- 处理:`git status` 检查可疑文件;通常意味着上一次迁移失败留下脏状态——前往 §F 回滚后重新做

### E.6 `new matter index ... already exists with different content; refusing to overwrite`

- 原因:`{slug}.index.yaml` 已存在但内容和迁移产物不一致
- 处理:`diff -u <existing> <expected>` 查差异;若是上一次迁移残留,§F 回滚;若是真实 matter 数据被误识别为 legacy slug 同名,人工合并

---

## §F 回滚程序

### F.1 上线尚未推送(即 `git push` 还没跑)

```bash
cd /pivot/var/git/<生产 repo 名>/
git reset --hard HEAD~1     # 退回迁移前 commit
git status                  # 确认 clean
```

工作目录回到迁移前。无副作用。fork 副本继续保留,可分析问题后重试。

### F.2 上线已推送但烟测失败

```bash
cd /pivot/var/git/<生产 repo 名>/
# 找到迁移前 commit hash
PRE_MIG=$(git log --grep="migrate legacy thread indexes" --pretty=format:"%H" -1)
PARENT=$(git rev-parse "$PRE_MIG^")

# 强制回退 + 强推 (需要 main 分支保护暂时关闭,或绕过通过运维)
git reset --hard "$PARENT"
git push --force-with-lease origin main
```

⚠️ **强推会让所有团队成员的本地 main 错乱**——上线前应通知"如失败需要 force push 回滚",上线后若回滚发生,通知所有人 `git fetch && git reset --hard origin/main` 同步。

### F.3 git 仓库本身受损(极罕见)

从 §C.3 备份的 `pre-migration-*.bundle` 恢复:

```bash
cd /tmp
git clone /pivot/var/backup/pre-migration-<TIMESTAMP>.bundle restored-repo
cd restored-repo
git push --force --mirror "https://<token>@github.com/<org>/<生产 repo 名>.git"
```

---

## §G 责任与上下文

- 迁移设计:`AI-docs/coding-test-plan/index-migration-plan.md`
- 迁移代码:`scripts/migrate_index_schema.py`
- 单元测试:`server/tests/test_migrate_index_schema.py`
- 已知偏离:`AI-docs/coding-test-plan/deviations.md`
- 评审记录:`Pivot 产品设计 - 设计哲学和基本原理` thread §016 / §018 / §024 帖
- 已接受的代价:外部对老路径的引用(飞书 bot 历史卡片、私聊链接、PR 描述等)失效,**这是预期行为,不是回滚理由**

---

最后更新:本文档随迁移脚本同 commit 演进。如有口径变化,以 `index-migration-plan.md` 为准。
