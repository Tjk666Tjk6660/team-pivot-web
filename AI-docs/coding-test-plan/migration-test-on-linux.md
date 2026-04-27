# 迁移测试 · Linux 服务器执行手册

本文档面向**测试仓库重置 + 重跑迁移测试**的场景。在 Linux 服务器上执行,避开 Windows 终端中文 mojibake 与 NTFS 大小写歧义。

> 实际操作已脚本化,见 `scripts/migration-test/`。本文档只讲整体流程与每一步的语义,具体命令请直接运行对应脚本。

设计依据见 `index-migration-plan.md`,主迁移上线手册见 `migration-runbook.md`。

---

## Bootstrap(一次性)

在 Linux 测试服务器上:

```bash
mkdir -p ~/tmp/pivot-migration-test
cd ~/tmp/pivot-migration-test
GH_TOKEN='<你的 PAT>' \
  git clone "https://${GH_TOKEN}@github.com/hashSTACS-Global/team-pivot-web.git"
cd team-pivot-web/scripts/migration-test

# 复制变量模板,填好 GH_TOKEN(必填)及其它(默认值适用于本团队)
cp env.init.example env.init
nano env.init
```

GH_TOKEN 权限要求:
- Classic PAT:勾 `repo` scope
- Fine-grained PAT:把 `pivot-database` 与 `pivot-database-migration-test` 都加进 Repository access,Contents 给 Read and write

---

## 顺序跑脚本

```bash
cd ~/tmp/pivot-migration-test/team-pivot-web/scripts/migration-test

bash 01-check.sh        # 环境检查 + uv sync (缺包给安装命令,不主动装)
bash 02-reset-repo.sh   # 重置测试仓库 → 生产最新,clone 工作目录,配 git 身份
bash 03-dryrun.sh       # 迁移预演,看 errors=0 + warnings 都可接受
bash 04-apply.sh        # 真落盘 + commit (不自动 push)
bash 05-verify.sh       # 4 项核对 + pinyin 校验

# 可选 / 按需
bash 06-push.sh         # 推迁移 commit 到测试仓库,GitHub 网页 review
bash 07-retry.sh        # 不满意要重来:重置远端 + 本地,回到 03
bash 08-cleanup.sh      # 收尾:删 mirror、test-workspace
```

每个脚本头部 source `lib.sh` + `env.init`,自动校验必填变量、预检前置目录、给出失败原因。脚本按 fail-fast 原则编写(`set -euo pipefail`)。

---

## 关键安全不变量

迁移脚本通过 SQLite URI `file:...?mode=ro` 只读打开 `PROD_DB_PATH`,**绝不写入、绝不创建、绝不 schema 同步**。所以 `env.init` 里的 `PROD_DB_PATH` 可以**直接填生产路径**(默认 `/opt/team-pivot-web/var/data.db`),不需要先拷贝副本。

实现见 `scripts/migrate_index_schema.py::_ReadOnlyUserView`;单测在
`test_migrate_index_schema.py::test_build_users_repo_opens_db_in_readonly_mode` 显式断言 INSERT / UPDATE / DELETE / ALTER 全部被 sqlite3 拒绝。

`08-cleanup.sh` 不删 `PROD_DB_PATH`,只清自己产生的临时目录。

---

## 每一步语义

### §1 (`01-check.sh`)
- 检查 git / python3 / sqlite3 / uv 是否在 PATH;**缺什么打印安装命令并 exit,不主动装**
- 校验 `PROD_DB_PATH` 可读 + users 表能查
- 切到 `$PIVOT_BRANCH` 并 `uv sync`
- smoke import 一下迁移模块

### §2 (`02-reset-repo.sh`)
- bare clone 生产 → mirror push 强制覆盖测试仓库,把上次迁移 commit 冲掉
- clone 测试仓库到 `$WORKDIR/test-workspace`
- 配 git 身份(`user.email` / `user.name`)在该工作目录,确保后续 commit 不挂

### §3 (`03-dryrun.sh`)
- 不写盘的预演,生成 `migration-report-dryrun.json`
- 关键检查:`errors=0`,warnings 列表里没有阻塞类(`unparseable legacy filename` / `MD file missing`)
- `DB_FLAG` 由 `lib.sh` 根据 `PROD_DB_PATH` 是否可读自动选 `--db-path` 或 `--no-users-db`

### §4 (`04-apply.sh`)
- 真写盘:rename MD、写新 matter index、改 frontmatter type、删老 yaml
- 单次 `git commit`(message:`chore: migrate legacy thread indexes to matter format`)
- 不自动 push
- 启动前预检 git 身份,无身份直接拒绝运行

### §5 (`05-verify.sh`)
4 项核对(plan §B.3)+ pinyin 解析校验:
1. commit 里大量 R 行(MD rename),少量 A/D 行
2. 老命名 token(`_proposal_` / `_reply_` / `*-discuss.index.yaml`)完全消失
3. 新 matter index 数量 = 老 thread 数量
4. mention.comments 完整迁入(本次生产数据预期 `items=56 / total=67`)
5. mention 解析:`--db-path` 模式 pinyin 应远多于 open_id

### §6 (`06-push.sh`,可选)
推到测试仓库的 main,让 GitHub 网页能 review 产物。

### §7 (`07-retry.sh`,需要时)
- 测试仓库远端通过 `prod-mirror.git` 重新 push --mirror 对齐生产
- 本地 `test-workspace` `git reset --hard origin/main` + `git clean -fd`
- 回到 §3 重跑

### §8 (`08-cleanup.sh`)
- 删 `prod-mirror.git`、`test-workspace`
- **不动** `PROD_DB_PATH`(用户填的生产路径,只读用)
- 保留 `migration-report-*.json` 留档

---

## Linux 默认就避开的 Windows 坑

- 终端默认 UTF-8,中文不再 mojibake(`cat`、`grep` 中文文件名直接正常)
- `os.rename` / `git add -A` 对中文路径无 NTFS 大小写歧义
- `subprocess.run(..., text=True)` 在 Linux 走 UTF-8,不会像 Windows 那样吃 cp936

---

## 安全提示

- `env.init` 含 `GH_TOKEN`,**已被 .gitignore 忽略**,不要 commit
- `PROD_DB_PATH` 是只读路径,脚本不会修改也不会删除它

---

## 责任与上下文

- 本文档:测试流程概览
- 实际脚本:`scripts/migration-test/` + `scripts/migration-test/README.md`
- 主迁移上线手册:`migration-runbook.md`(生产环境完整流程)
- 迁移设计:`index-migration-plan.md`
- 迁移代码:`scripts/migrate_index_schema.py`
- 单元测试:`server/tests/test_migrate_index_schema.py`
