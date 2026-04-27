# 迁移上线 · 生产执行脚本

把 `AI-docs/coding-test-plan/migration-runbook.md` §C 生产上线部分脚本化。在生产服务器 `/opt/team-pivot-web` 上执行,**直接对生产 workspace in-place 迁移**(不搞 sandbox)。

## 安全不变量

1. 迁移脚本通过 SQLite URI `file:...?mode=ro` **只读直连** `PROD_DB_PATH`,绝不写入(详见 `scripts/migrate_index_schema.py::_ReadOnlyUserView` 与对应 pytest)
2. 整个迁移产生**单次** git commit,**不自动 push**
3. apply 前强制要求**1 小时内做过** bundle 备份,否则拒绝执行
4. **服务必须已停**才允许 preflight 通过 (`systemctl is-active` 检测)
5. workspace **工作树必须 clean** 且与 origin/main 同步,才允许迁移

## 与测试脚本的差异

| 项 | 测试 (`scripts/migration-test/`) | 生产 (`scripts/migration-prod/`) |
|---|---|---|
| 仓库重置 | `02-reset-repo.sh` 把测试仓库强制对齐生产 | 不需要 — 直接对生产 workspace 操作 |
| Bundle 备份 | 无 | `02-bundle-backup.sh` 强制做 (含 data.db 副本) |
| 服务控制 | 无 | preflight 校验已停 + `07-restart-service.sh` 启服 + 烟测 |
| Push 路径 | 推到测试仓库 | 推到生产 main |
| Rollback | `07-retry.sh` 重置后再来 | `99-rollback.sh` 仅 push 前 reset;push 后走 runbook §F.2 |
| `GH_TOKEN` | env.init 里填 | 不需要 — workspace `.git/config` 已带 token (来自 /admin Workspace 配置) |

## Bootstrap

假设你已经把含迁移代码的分支 (默认 `main`) 拉到 `/opt/team-pivot-web`:

```bash
cd /opt/team-pivot-web
git fetch origin
git checkout main
git pull --ff-only

cd scripts/migration-prod
cp env.init.example env.init
# 默认值通常无需改;如需改则编辑
nano env.init
```

## 生产上线流程

```bash
# 0. 通知团队 + 停飞书 bot 推送(人工)

# 1. 停服(人工,因为需要 sudo;脚本会校验"已停")
sudo systemctl stop team-pivot-web

# 2. 进生产脚本目录
cd /opt/team-pivot-web/scripts/migration-prod

# 3. 顺序跑
bash 01-preflight.sh        # 工具/分支/clean/同步/服务停了/db 可读
bash 02-bundle-backup.sh    # bundle + data.db 副本到 BACKUP_DIR
bash 03-dryrun.sh           # 不写盘
bash 04-apply.sh            # in-place 落盘 + commit (不 push)
bash 05-verify.sh           # 4 项核对 + pinyin 校验
bash 06-push.sh             # push 到 origin/main
bash 07-restart-service.sh  # 启服 + 烟测

# 出问题(push 前):
bash 99-rollback.sh         # git reset --hard HEAD~1
```

## 关键变量

| 变量 | 默认 | 说明 |
|---|---|---|
| `WORKSPACE` | `/opt/team-pivot-web/var/git/pivot-database` | Pivot 数据 workspace 路径,迁移目标 |
| `BACKUP_DIR` | `/opt/team-pivot-web/var/backup` | bundle + db 副本 + 报告落点 |
| `PROD_DB_PATH` | `/opt/team-pivot-web/var/data.db` | 只读直连用于 mention pinyin 解析;留空走 `--no-users-db` |
| `SERVICE_NAME` | `team-pivot-web` | systemd unit 名 |
| `EXPECTED_BRANCH` | `main` | workspace 与 PIVOT_CODE 都在这条分支 |
| `GIT_USER_EMAIL` / `GIT_USER_NAME` | `migration@pivot.local` / `migration` | commit 身份(仅本仓库 local config) |

## 失败回滚决策树

```
迁移失败/烟测失败,要回滚?
├── 还没 push (HEAD 是迁移 commit,但 origin/main 还没收到)
│   └── bash 99-rollback.sh   # git reset --hard HEAD~1, 干净
│
├── 已 push,但烟测失败,需要让团队回到迁移前
│   └── 走 migration-runbook.md §F.2 手工流程
│       (force-push + 通知所有团队成员 git reset --hard origin/main)
│
└── git 仓库本身受损
    └── 走 migration-runbook.md §F.3
        (从 BACKUP_DIR 里最新 .bundle 恢复)
```

## 责任与上下文

- 设计:`AI-docs/coding-test-plan/index-migration-plan.md`
- 主上线手册:`AI-docs/coding-test-plan/migration-runbook.md`
- 测试脚本:`scripts/migration-test/`
- 部署手册:`AI-docs/pivot-deploy.md`
