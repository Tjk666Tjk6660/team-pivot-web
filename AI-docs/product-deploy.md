# Product Deploy Manual

本文件是 `team-pivot-web` 的**正式部署手册**。它同时面向：

- 部署工程师
- 被授权执行部署的 AI 代理

目标是从 **GitHub 源代码** 开始，把系统部署到一台全新的 Linux 服务器，并完成**首次初始化配置**，直到产品可用。

这份文档关注的是：

- 从零部署
- 哪些步骤必须人工完成
- 哪些步骤可以让 AI 通过 SSH 远程执行
- 首次登录后还需要在产品内做哪些初始化配置

说明：

- `AI-docs/deploy.md` 是当前维护者自己测试环境里的历史调试文档，不再作为正式产品部署手册。
- 本文档才是应该跟随仓库长期维护的端到端部署说明。

---

## 1. 部署目标

部署完成后，应同时满足下面这些条件：

1. `team-pivot-web` 后端以 `systemd` 常驻运行
2. 前端静态文件可由 `Caddy` 对外提供
3. HTTPS 正常可用
4. 飞书 OAuth 登录可用
5. 首位管理员用户可登录站点
6. 管理员可在 `/admin` 完成：
   - 数据仓库配置
   - AI 配置
   - 联系人同步
7. 用户可以创建 thread、回复、同步 Git、收藏 thread

---

## 2. 架构概要

### 运行组件

- 后端：FastAPI + Uvicorn
- 前端：Vite 构建后的静态文件
- 反向代理：Caddy
- 本地状态存储：SQLite
- 文档权威源：Git 仓库（Workspace）
- 登录：飞书 OAuth

### 服务器上的推荐目录

```text
/opt/team-pivot-web
  ├── .env
  ├── server/
  ├── web/
  ├── AI-docs/
  └── var/
      ├── data.db
      └── git/
```

### 关键事实

- `.env` 只保存**部署级配置**
- `workspace` 配置不再放在 `.env`，而是保存到 SQLite `settings`
- AI 配置也不在 `.env`，而是在 `/admin` 中保存到 SQLite `settings`

---

## 3. 角色分工

## 3.1 必须人工完成的事情

下面这些事情通常不适合交给 AI 自动做，或者必须由拥有真实账号/管理权限的人完成。

### 云资源与网络

- 购买或准备 Linux 服务器
- 配置公网 IP
- 配置域名 DNS
- 在云防火墙/安全组中放通：
  - TCP 80
  - TCP 443
  - 可选 TCP 22

### GitHub 访问准备

如果仓库是私有仓库，人工必须先决定服务器如何拿到源码：

- deploy key
- GitHub PAT
- 组织级机器账号

如果不做这一步，服务器无法直接 `git clone` 私有仓库。

### 飞书开放平台配置

人工必须在飞书开放平台完成：

- 创建/准备应用
- 获取：
  - `FEISHU_APP_ID`
  - `FEISHU_APP_SECRET`
- 配置网页应用回调地址
- 配置主页地址
- 授予所需权限
- 如要使用 IM 通知，配置机器人能力和可用范围

### 秘钥与口令准备

人工必须提供或生成：

- `SESSION_SECRET`
- 飞书 App ID / Secret
- Workspace 远程仓库的：
  - write token
  - readonly token
- OpenRouter API Key（如果启用 AI）

### 首次产品内登录

首次进入系统并做初始化配置时，必须有一个真实的人类用户：

- 在浏览器中完成飞书登录
- 首登填写 profile
- 进入 `/admin`
- 输入管理员密码
- 完成 Workspace / AI / Contacts 初始化

---

## 3.2 可以交给 AI 执行的事情

在下面这些前提成立时，AI 可以安全执行：

- 人工已经提供 SSH 权限
- 人工已经提供部署目标域名
- 人工已经提供需要写入 `.env` 的值
- 人工已经给服务器准备好 GitHub 访问能力

AI 可代做：

- SSH 登录服务器
- 安装系统依赖
- 克隆或更新代码
- 创建 `.env`
- 执行 `uv sync`
- 执行 `npm install` / `npm run build`
- 写入 `systemd` unit
- 写入 `Caddyfile`
- 启动/重启服务
- 做回环健康检查
- 查看日志并排障

AI 不应擅自做：

- 自行创建或修改云平台 DNS / 安全组
- 自行创建飞书应用
- 自行生成并保管长期生产密钥
- 未经授权直接改动线上管理员口令策略

---

## 4. 部署前准备清单

在真正开始部署前，请先收齐以下信息。

## 4.1 仓库与服务器

- GitHub 仓库地址
- 服务器 SSH 地址
- SSH 用户
- SSH 私钥
- 部署目录：推荐 `/opt/team-pivot-web`

## 4.2 域名

- 正式域名，例如：`pivot.example.com`

## 4.3 网络访问确认

在安装依赖和拉取源码之前，部署工程师或 AI 必须先确认当前服务器是否能直接访问外网，尤其是：

- GitHub
- PyPI
- npm registry
- Let’s Encrypt

推荐先明确问一句：

- “当前这台服务器是否需要配置代理才能访问 GitHub / PyPI / npm？”

规则：

- 如果服务器位于中国境外，且访问 GitHub / PyPI / npm 正常，则不要额外配置代理
- 如果服务器位于中国境内，或实际测试发现 GitHub / PyPI / npm 无法稳定访问，则先配置代理，再继续部署

AI 不应默认所有生产服务器都需要代理，也不应默认所有服务器都不需要代理。这一步应先和部署工程师确认。

如果确认需要代理，不要把代理的具体地址、端口或凭据写进本手册。应直接读取目标服务器自身已经准备好的系统配置，然后在部署过程中显式加载，例如：

```bash
source /etc/profile
```

对于本项目，只有在“服务器确实需要代理”时，才应该加这一步。

## 4.4 `.env` 所需变量

当前代码里必须存在的 `.env` 项：

```env
FEISHU_APP_ID=
FEISHU_APP_SECRET=
FEISHU_REDIRECT_URI=
SESSION_SECRET=
WEB_DEV_ORIGIN=
DATA_DIR=
LOG_LEVEL=INFO
NOTIFY_ENABLED=true
```

推荐值示例：

```env
FEISHU_APP_ID=cli_xxx
FEISHU_APP_SECRET=xxx
FEISHU_REDIRECT_URI=https://pivot.example.com/auth/callback
SESSION_SECRET=replace-with-long-random-secret
WEB_DEV_ORIGIN=https://pivot.example.com
DATA_DIR=/opt/team-pivot-web/var
LOG_LEVEL=INFO
NOTIFY_ENABLED=true
```

说明：

- `FEISHU_REDIRECT_URI` 必须是外部可访问的正式域名回调地址
- `WEB_DEV_ORIGIN` 虽然名字里有 `DEV`，但线上也必须填正式域名
  - 当前代码会用它生成飞书通知里的网页链接
  - 当前代码会用它作为 CORS `allow_origins`
  - 当前代码会用它作为登录完成后的默认回跳首页
  - 因此线上绝不能写成 `http://localhost:5173`
- `DATA_DIR` 推荐显式写成 `/opt/team-pivot-web/var`

---

## 5. 飞书开放平台配置要求

部署工程师需要人工确认以下配置已经在飞书后台完成。

## 5.1 网页应用地址

至少应保证：

- 回调地址：`https://<your-domain>/auth/callback`
- 应用主页：`https://<your-domain>/`

## 5.2 权限

当前代码至少依赖这些能力：

- 飞书 OAuth 登录
- 联系人读取相关权限
- 如果要启用联系人同步：通讯录读取权限
- 如果要启用通知：机器人 / IM 发送消息能力

## 5.3 端内打开

当前代码已经支持统一登录入口：

- `/auth/entry?next=...`

飞书 IM 或工作台里的链接，应尽量走这个入口，而不是直接发 `/t/...`。

---

## 6. 首次部署步骤

## 6.1 登录服务器

```bash
ssh -i /path/to/key.pem ubuntu@<server-ip>
```

## 6.1.1 如有需要，先加载代理

如果在 `4.3 网络访问确认` 中已经确认这台服务器需要代理，则在继续安装依赖、拉代码、执行 `uv` / `pip` / `npm` 之前先执行：

```bash
source /etc/profile
env | grep -iE '^(http|https|all)_proxy=|^no_proxy='
```

如果这里没有看到预期的代理变量，不要继续部署，应先让人工修正代理配置。

如果 PEM 权限过宽：

```bash
chmod 600 /path/to/key.pem
```

---

## 6.2 安装系统依赖

在 Ubuntu 24 上，当前实践可用的命令：

```bash
source /etc/profile   # 仅当服务器需要代理时执行
sudo apt update
sudo apt install -y caddy git curl nodejs npm
curl -LsSf https://astral.sh/uv/install.sh | sh
```

说明：

- 当前项目已验证 `Node 18 + npm` 可构建
- `uv` 用于 Python 依赖安装和运行

---

## 6.3 获取源代码

### 推荐方案：服务器直接 clone

```bash
source /etc/profile   # 仅当服务器需要代理时执行
sudo mkdir -p /opt
sudo chown -R $USER:$USER /opt
cd /opt
git clone <github-repo-url> team-pivot-web
cd /opt/team-pivot-web
```

### 如果服务器无法访问私有仓库

可以改用本地机器上传：

```bash
rsync -avz \
  --exclude='.git' \
  --exclude='node_modules' \
  --exclude='web/node_modules' \
  --exclude='web/dist' \
  --exclude='__pycache__' \
  --exclude='.venv' \
  --exclude='var/' \
  -e "ssh -i /path/to/key.pem" \
  /local/path/team-pivot-web/ \
  ubuntu@<server-ip>:/opt/team-pivot-web/
```

正式生产长期建议还是让服务器具备直接拉代码的能力。

---

## 6.4 写入 `.env`

在 `/opt/team-pivot-web/.env` 中写入：

```env
FEISHU_APP_ID=...
FEISHU_APP_SECRET=...
FEISHU_REDIRECT_URI=https://<your-domain>/auth/callback
SESSION_SECRET=...
WEB_DEV_ORIGIN=https://<your-domain>
DATA_DIR=/opt/team-pivot-web/var
LOG_LEVEL=INFO
NOTIFY_ENABLED=true
```

注意：

- 新部署**不要**把 workspace / AI 配置继续写进 `.env`
- 这些配置已经迁到数据库，必须在应用启动后通过管理界面初始化
- `WEB_DEV_ORIGIN` 在线上必须写成正式站点根地址，例如 `https://pivot.enclaws.com`

---

## 6.5 安装后端依赖

```bash
source /etc/profile   # 仅当服务器需要代理时执行
cd /opt/team-pivot-web
~/.local/bin/uv sync
```

---

## 6.6 构建前端

```bash
source /etc/profile   # 仅当服务器需要代理时执行
cd /opt/team-pivot-web/web
npm install
npm run build
```

---

## 6.7 写入 systemd 服务

新建：

`/etc/systemd/system/team-pivot-web.service`

内容建议：

```ini
[Unit]
Description=team-pivot-web
After=network.target

[Service]
Type=simple
User=ubuntu
Group=ubuntu
WorkingDirectory=/opt/team-pivot-web
EnvironmentFile=/opt/team-pivot-web/.env
ExecStart=/home/ubuntu/.local/bin/uv run uvicorn --factory server.app:create_app --host 127.0.0.1 --port 8000
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

启用并启动：

```bash
sudo systemctl daemon-reload
sudo systemctl enable team-pivot-web
sudo systemctl restart team-pivot-web
systemctl status team-pivot-web --no-pager
```

---

## 6.8 写入 Caddy 配置

典型配置：

```caddy
<your-domain> {
    handle /api/* {
        reverse_proxy localhost:8000
    }
    handle /auth/* {
        reverse_proxy localhost:8000
    }
    handle /login {
        reverse_proxy localhost:8000
    }
    handle /logout {
        reverse_proxy localhost:8000
    }
    handle /me {
        reverse_proxy localhost:8000
    }
    handle /me/* {
        reverse_proxy localhost:8000
    }
    handle {
        root * /opt/team-pivot-web/web/dist
        try_files {path} /index.html
        file_server
    }
}
```

说明：

- `/login`、`/auth/*`、`/me` 这些后端路由必须优先 `handle`
- 不能直接让 SPA fallback 把它们吞掉

重载：

```bash
sudo systemctl reload caddy
sudo systemctl restart caddy
sudo journalctl -u caddy -n 100 --no-pager
```

---

## 6.9 首次健康检查

### 服务器本机回环检查

在服务器上执行：

```bash
curl -s -i http://127.0.0.1:8000/me | head -n 8
```

看到：

- `401 {"detail":"not logged in"}`

说明后端是活的。

### 域名检查

```bash
curl -I https://<your-domain>
```

如果这里失败，再看：

- Caddy 配置
- DNS
- 安全组 80/443

---

## 7. 首次初始化配置

这一部分不是 SSH 里做，而是在产品部署成功后由管理员进入站点操作。

## 7.1 第一个管理员登录

步骤：

1. 打开 `https://<your-domain>/`
2. 使用飞书登录
3. 首次登录时填写：
   - `pinyin`
   - `github_username`（可选）

---

## 7.2 进入管理员页面

路径：

- 右上角用户菜单
- 点击 `管理员设置`

当前系统中的管理员口令不是数据库配置，而是代码常量：

- `server/auth/admin.py`
- 当前值：`000123`

### 重要说明

当前实现是 MVP 级别：

- 管理员密码是硬编码常量
- 不是用户体系里的 RBAC

如果是正式生产环境，建议在发布前先修改这段常量，再部署。

---

## 7.3 初始化数据仓库配置

进入 `/admin` 后，先配置 **数据仓库**。

需要填写：

- `repo_url`
- `visibility`
- `write_token`
- `readonly_token`

### 含义

- `repo_url`
  - 产品内容仓库地址
  - 服务器和客户端共用同一个仓库事实源
- `visibility`
  - `public` 或 `private`
- `write_token`
  - 服务器用于 `pull / push / publish`
- `readonly_token`
  - 外部客户端（如 VS Code 插件）用于 clone / pull

### 配置完成后

系统会把这些值写入 SQLite `settings`，并立即重载 workspace。

你可以再点：

- 顶部 `同步 Git`

验证服务器是否能拉到目标文档仓库。

---

## 7.4 初始化 AI 配置

在 `/admin` 页面配置 AI。

当前支持的关键配置：

- OpenRouter API Key
- Model
- 最大上下文 token
- 最小轮数
- 最大轮数

这些值保存到 SQLite `settings`，对应 key 包括：

- `ai.openrouter_api_key`
- `ai.model`
- `ai.max_context_tokens`
- `ai.min_rounds`
- `ai.max_rounds`

### 推荐最小初始化

- 先填 OpenRouter API Key
- 先选一个稳定模型
- 其他参数保持默认

如果不配置 AI Key：

- 站点仍然可以运行
- 但 AI 助手相关功能不可用

---

## 7.5 首次联系人同步

在 `/admin` 页面执行联系人同步。

说明：

- 这个接口必须用 Cookie 登录态调用
- 还要求管理员口令
- 当前会话中必须带飞书 `user_access_token`

如果首位管理员刚完成飞书登录，这一步通常就能直接成功。

同步完成后：

- `contacts` 表会有飞书通讯录镜像
- @mention 才能正常搜索组织内成员

---

## 7.6 可选：创建 PAT 给外部客户端

如果要给 VS Code 插件或其他客户端使用：

1. 进入个人设置 `/settings`
2. 创建 PAT
3. 外部客户端使用：

```text
Authorization: Bearer pvt_xxx
```

如果客户端还需要文档仓库镜像地址，可调用：

- `GET /api/workspace/mirror`

---

## 8. 生产验收清单

至少验证下面这些项目：

### 登录与鉴权

- 飞书登录成功
- 首登 profile 可保存
- 重新打开页面仍保持登录
- `/admin` 需要管理员密码

### Workspace

- `/admin` 能保存 workspace 配置
- 顶部 `同步 Git` 成功
- 能正常读取 thread 列表

### Threads

- 能创建新讨论
- 能回复
- 能切换状态
- 能收藏 / 取消收藏

### Contacts

- 联系人同步成功
- @mention 能搜到联系人

### AI

- `/admin` 保存 AI key 成功
- Thread 详情页里的 AI 助手可正常使用

### Feishu

- 飞书通知能发出
- 从飞书 IM / 工作台点开链接后能正确进入站点

---

## 9. AI 代理执行模板

如果让 AI 代做部署，推荐按下面的分界协作。

## 9.1 人类先给 AI 的信息

至少提供：

- 服务器 SSH 地址 / 用户 / 私钥路径
- 目标域名
- GitHub 仓库地址
- `.env` 变量值
- 是否需要启用飞书通知
- 是否已经准备好 GitHub 凭据

## 9.2 AI 可以直接执行的命令阶段

AI 可执行：

1. SSH 登录
2. 安装依赖
3. clone / pull 代码
4. 写 `.env`
5. `uv sync`
6. `npm install && npm run build`
7. 写 `systemd` 和 `Caddy` 配置
8. 启动服务
9. 做回环检查和日志检查

## 9.3 必须交还给人类的步骤

AI 到这里应该停下并通知人工：

- 请真人打开网页登录飞书
- 请真人进入 `/admin`
- 请真人配置：
  - workspace
  - AI
  - contacts sync

如果 AI 有浏览器自动化能力，并且获得了人类授权与会话上下文，也可以辅助完成这部分，但**默认仍建议由人类完成**。

---

## 10. 常见问题

## 10.1 `/login` 被前端页面吞掉

原因：

- Caddy 把 `/login` 当成静态前端路由处理了

解决：

- 在 Caddy 中对 `/login`、`/auth/*`、`/me`、`/api/*` 先做 `handle`

## 10.2 登录后仍然反复跳回登录页

常见原因：

- Cookie 属性不正确
- 反向代理没把认证回调路由转发到后端

当前验证过的线上行为是：

- HTTPS 下使用 `Secure + SameSite=None`

## 10.3 `workspace` 接口返回未配置

原因：

- 新部署没有在 `/admin` 保存 workspace 配置

解决：

- 管理员登录后进入 `/admin` 填写 `repo_url / visibility / write_token / readonly_token`

## 10.4 AI 助手报未配置 Key

原因：

- 没在 `/admin` 里保存 OpenRouter API Key

解决：

- 管理员进入 `/admin` 保存 AI 配置

## 10.5 联系人同步失败

原因通常是：

- 当前不是 Cookie 登录态
- 没有管理员密码
- 当前 session 里没有飞书 `user_access_token`
- 飞书权限不够

---

## 11. 交付标准

只有当下面这些都完成，才算部署完成：

1. 域名可访问
2. HTTPS 正常
3. 飞书登录正常
4. `/admin` 可进入
5. Workspace 配置完成
6. AI 配置完成（若启用）
7. 联系人同步完成
8. 至少成功创建一个 thread 并成功回复一次

如果只完成了服务启动，但没完成 `/admin` 初始化，那么还不能算产品交付完成。
