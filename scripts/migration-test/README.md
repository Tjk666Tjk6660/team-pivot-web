# 迁移测试 · 可执行脚本

跟着脚本走完一轮迁移测试。脚本只打开测试仓库 (`pivot-database-migration-test`),**不**碰生产仓库;对生产 `data.db` 严格只读。

设计依据:`AI-docs/coding-test-plan/migration-test-on-linux.md`(原版手册)。

---

## 安全不变量(必读)

迁移脚本通过 SQLite URI `file:...?mode=ro` 只读打开 `PROD_DB_PATH`,**绝不写入、绝不创建、绝不 schema 同步**。所以可以安全地把 `PROD_DB_PATH` 直接填生产路径(默认 `/opt/team-pivot-web/var/data.db`)。

实现见 `scripts/migrate_index_schema.py::_ReadOnlyUserView`,测试见
`server/tests/test_migrate_index_schema.py::test_build_users_repo_opens_db_in_readonly_mode`(用例显式构造 INSERT/UPDATE/DELETE/ALTER 验证全部被 sqlite3 拒绝)。

`08-cleanup.sh` 只清自己产生的临时目录,**不动 `PROD_DB_PATH`**。

---

## Bootstrap(一次性)

在 Linux 测试服务器上:

```bash
mkdir -p ~/tmp/pivot-migration-test
cd ~/tmp/pivot-migration-test

# 先 clone team-pivot-web,需要含本次迁移分支
GH_TOKEN='<你的 PAT>' \
  git clone "https://${GH_TOKEN}@github.com/hashSTACS-Global/team-pivot-web.git"
cd team-pivot-web/scripts/migration-test

# 把变量模板复制成 env.init,填好 GH_TOKEN 等
cp env.init.example env.init
nano env.init   # 至少要填 GH_TOKEN,其它默认值适用于本团队
```

---

## 跑一轮测试(顺序执行)

```bash
cd ~/tmp/pivot-migration-test/team-pivot-web/scripts/migration-test

bash 01-check.sh        # 环境检查 + uv sync (缺包提示安装命令,不主动装)
bash 02-reset-repo.sh   # 重置测试仓库 → 生产最新,clone 工作目录,配 git 身份
bash 03-dryrun.sh       # 迁移预演,看报告 errors=0 + warnings 都可接受
bash 04-apply.sh        # 真落盘 + commit (不自动 push)
bash 05-verify.sh       # 4 项核对 + pinyin 校验

# 可选 / 按需
bash 06-push.sh         # 把迁移 commit 推到测试仓库,供 GitHub 网页 review
bash 07-retry.sh        # 不满意要重来:重置远端 + 本地,然后回 03
bash 08-cleanup.sh      # 收尾:删 mirror、test-workspace
```

每个脚本头部都会 source `lib.sh` + `env.init`,自动校验必填变量、预检前置目录、给出失败原因。

---

## 关键变量(`env.init.example` 看注释)

| 变量 | 默认 | 说明 |
|---|---|---|
| `GH_TOKEN` | (无) | GitHub PAT,需要对两个仓库都有权限 |
| `PROD_REPO` | `hashSTACS-Global/pivot-database` | 生产源仓库 |
| `TEST_REPO` | `hashSTACS-Global/pivot-database-migration-test` | 测试目标仓库 |
| `PIVOT_REPO` | `hashSTACS-Global/team-pivot-web` | 代码仓库(含迁移脚本) |
| `PIVOT_BRANCH` | `feat/pivot-matter` | 当前含迁移脚本的分支 |
| `WORKDIR` | `~/tmp/pivot-migration-test` | 放 mirror、test-workspace、报告 |
| `PROD_DB_PATH` | `/opt/team-pivot-web/var/data.db` | 生产 data.db **只读**用于 mention pinyin 解析。留空走 `--no-users-db` 兜底,mention 落 open_id 字面量 |
| `GIT_USER_EMAIL` / `GIT_USER_NAME` | `migration@pivot.local` / `migration` | 迁移 commit 的身份 |

---

## 安全提示

- `env.init` 含 `GH_TOKEN`,**已被 .gitignore 忽略**,不要 commit
- `PROD_DB_PATH` 文件**只读访问,绝不被脚本修改或删除**

---

## 与生产迁移的关系

本目录脚本**只对测试仓库**有效。真正生产上线另有手册 `AI-docs/coding-test-plan/migration-runbook.md`,流程含通知、停服、bundle 备份等,不通用。
