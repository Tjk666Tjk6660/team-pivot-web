# Pivot-Deploy

本文档是 `team-pivot-web` 的公开部署手册，面向：

- 部署工程师
- 被授权执行部署的 AI 代理

它的目标不是记录某一台机器的私有信息，而是给 AI 一个可以重复执行的、不会泄露敏感信息的生产部署指令集。

本文档只保留：

- 通用部署步骤
- 初始化要求
- 已验证过的排障路径
- AI 与人工的协作边界

本文档不保留：

- 私有域名、IP、SSH key 路径
- GitHub PAT、AI Key、管理员口令
- 任何当前环境专属的 secret

## 1. 部署目标

部署完成后，应同时满足下面这些条件：

1. `team-pivot-web` 后端以 `systemd` 常驻运行
2. 前端静态文件由 `Caddy` 对外提供
3. HTTPS 正常可用
4. 飞书 OAuth 登录可用
5. 首位管理员用户可登录站点
6. 管理员可在 `/admin` 完成：
   - Workspace 配置
   - AI 配置
   - 联系人同步
7. 用户可以创建 thread、回复、同步 Git、收藏 thread

## 2. 部署原则

### 2.1 配置分层

- `.env` 只保存部署级配置
- Workspace 配置不保存在 `.env`，而是保存在 SQLite `settings`
- AI 配置不保存在 `.env`，而是在 `/admin` 中保存到 SQLite `settings`

### 2.2 AI 的边界

AI 可以执行：

- SSH 登录服务器
- 安装系统依赖
- 拉取或同步代码
- 写 `.env`
- 执行 `uv sync`
- 执行 `npm install` / `npm run build`
- 写 `systemd` unit
- 写 `Caddy` 配置
- 启动或重启服务
- 做回环健康检查
- 查日志并排障

AI 不应擅自执行：

- 修改 DNS / 安全组
- 创建飞书应用
- 生成和保管长期密钥
- 未经授权直接修改线上管理员口令策略

### 2.3 公开仓库约束

因为这份文档会进入公开仓库，所以所有示例都必须使用占位符：

- `<your-domain>`
- `<server-ip>`
- `/path/to/key.pem`
- `<github-repo-url>`
- `replace-with-long-random-secret`

不要在本文档中写任何真实 token、私钥路径、生产域名或环境专属地址。

## 3. 架构概要

### 3.1 运行组件

- 后端：FastAPI + Uvicorn
- 前端：Vite 构建后的静态文件
- 反向代理：Caddy
- 本地状态存储：SQLite
- 文档权威源：Git 仓库（Workspace）
- 登录：飞书 OAuth

### 3.2 推荐目录

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

## 4. 部署前准备

部署前应先收齐：

- GitHub 仓库地址
- 服务器 SSH 地址
- SSH 用户
- SSH 私钥
- 正式域名
- `.env` 变量值
- 飞书应用配置
- 是否启用飞书通知
- 服务器是否需要代理

### 4.1 代理确认

在安装依赖和拉代码前，必须先确认服务器是否能访问：

- GitHub
- PyPI
- npm registry
- Let’s Encrypt

推荐先明确问一句：

> 当前这台服务器是否需要配置代理才能访问 GitHub / PyPI / npm？

规则：

- 如果服务器位于中国境外且访问正常，不额外配置代理
- 如果服务器位于中国境内，或实际测试发现 GitHub / PyPI / npm 无法稳定访问，则先配置代理，再继续部署

### 4.2 区分部署期代理和运行期代理

这一点是历史部署里验证过的关键坑点。

- 部署期代理：影响 `apt`、`git clone`、`uv sync`、`npm install`
- 运行期代理：影响服务启动后的 workspace `clone / pull / push`

只在 SSH shell 里执行一次：

```bash
source /etc/profile
```

只能解决部署期问题，不能保证 `systemd` 启动的应用在运行期也能访问 GitHub。

如果服务器运行期也需要代理，则代理变量还必须进入服务环境，例如通过：

- `EnvironmentFile=/opt/team-pivot-web/.env`
- 在 `.env` 中加入代理变量

## 5. `.env` 最小配置

```env
FEISHU_APP_ID=
FEISHU_APP_SECRET=
FEISHU_REDIRECT_URI=https://<your-domain>/auth/callback
SESSION_SECRET=replace-with-long-random-secret
WEB_DEV_ORIGIN=https://<your-domain>
DATA_DIR=/opt/team-pivot-web/var
LOG_LEVEL=INFO
NOTIFY_ENABLED=true
```

说明：

- `FEISHU_REDIRECT_URI` 必须是外部可访问的正式回调地址
- `WEB_DEV_ORIGIN` 虽然名字里有 `DEV`，线上也必须写正式域名
- 新部署不要把 Workspace / AI 配置继续写进 `.env`

## 6. 首次部署步骤

### 6.1 SSH 登录

```bash
chmod 600 /path/to/key.pem
ssh -i /path/to/key.pem <user>@<server-ip>
```

如果遇到旧主机指纹冲突：

```bash
ssh-keygen -R <server-ip>
```

### 6.2 如有需要，先加载代理

```bash
source /etc/profile
env | grep -iE '^(http|https|all)_proxy=|^no_proxy='
```

如果没有看到预期代理变量，不要继续部署。

### 6.3 安装系统依赖

```bash
sudo apt update
sudo apt install -y caddy git curl nodejs npm
curl -LsSf https://astral.sh/uv/install.sh | sh
```

补充：

- 当前项目已验证 `Node 18 + npm` 可构建
- 某些前端依赖可能会对 Node 20 给出 warning，但 Node 18 当前可构建通过

### 6.4 获取代码

推荐方式：

```bash
sudo mkdir -p /opt
sudo chown -R $USER:$USER /opt
cd /opt
git clone <github-repo-url> team-pivot-web
cd /opt/team-pivot-web
```

如果服务器无法直接拉取私有仓库，可退回本地 `rsync`：

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
  <user>@<server-ip>:/opt/team-pivot-web/
```

### 6.5 写入 `.env`

在 `/opt/team-pivot-web/.env` 中写入部署级配置。

### 6.6 安装后端依赖

```bash
cd /opt/team-pivot-web
~/.local/bin/uv sync
```

### 6.7 构建前端

```bash
cd /opt/team-pivot-web/web
npm install
npm run build
```

### 6.8 写入 `systemd` 服务

`/etc/systemd/system/team-pivot-web.service`

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

### 6.9 写入 `Caddy` 配置

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

- `/login`、`/auth/*`、`/me`、`/api/*` 必须优先走后端
- 不能让 SPA fallback 把这些路由吞掉

重载：

```bash
sudo systemctl reload caddy
sudo systemctl restart caddy
sudo journalctl -u caddy -n 100 --no-pager
```

## 7. 首次健康检查

### 7.1 服务器本机回环检查

```bash
curl -s -i http://127.0.0.1:8000/me | head -n 8
```

未登录时看到 `401 {"detail":"not logged in"}`，说明后端是活的。

### 7.2 域名检查

```bash
curl -I https://<your-domain>
```

如果失败，优先排查：

- DNS
- 安全组 80/443
- Caddy 配置
- 目录权限和静态文件可读性

## 8. 首次初始化配置

这部分不是 SSH 里完成，而是在部署成功后由管理员进入站点操作。

### 8.1 管理员登录

1. 打开 `https://<your-domain>/`
2. 使用飞书登录
3. 首次登录时填写 `pinyin` 和可选的 `github_username`

### 8.2 管理员页面

进入 `/admin` 后，依次完成：

- Workspace 配置
- AI 配置
- 联系人同步

注意：

- 当前管理员口令是代码侧控制，不是完整 RBAC
- 不要在公开文档里写真实管理员口令
- 如果要用于正式生产，建议在发布前先改掉默认实现

### 8.3 Workspace 配置

需要填写：

- `repo_url`
- `visibility`
- `write_token`
- `readonly_token`

说明：

- `write_token` 供服务器 `pull / push / publish`
- `readonly_token` 供外部客户端 clone / pull

配置完成后，系统会写入 SQLite `settings` 并重载 workspace。

### 8.4 AI 配置

在 `/admin` 中填写：

- Base URL
- API Key
- Model
- 最大上下文 token
- 最小轮数
- 最大轮数

不配置 AI Key 时，站点仍可运行，但 AI 助手不可用。

### 8.5 联系人同步

联系人同步要求：

- 当前是 Cookie 登录态
- 提供管理员口令
- 当前 session 带飞书 `user_access_token`

同步成功后，`@mention` 搜索才能正常使用。

## 9. 生产验收清单

至少验证：

### 登录与鉴权

- 飞书登录成功
- 首登 profile 可保存
- 刷新后登录态仍存在
- `/admin` 需要管理员口令

### Workspace

- Workspace 配置保存成功
- Git 同步成功
- thread 列表可正常读取

### Threads

- 能创建讨论
- 能回复
- 能切换状态
- 能收藏 / 取消收藏

### Contacts

- 联系人同步成功
- `@mention` 可搜索联系人

### AI

- AI 配置保存成功
- thread 内 AI 助手可正常使用

### Feishu

- 飞书通知可发出
- 从飞书 IM / 工作台打开链接后可正确进入站点

## 10. AI 执行模板

### 10.1 人类先给 AI 的信息

至少提供：

- SSH 地址 / 用户 / 私钥路径
- 目标域名
- GitHub 仓库地址
- `.env` 变量值
- 是否启用飞书通知
- 是否已经准备好 GitHub 凭据

### 10.2 AI 可直接执行的阶段

1. SSH 登录
2. 安装依赖
3. clone / pull / rsync 代码
4. 写 `.env`
5. `uv sync`
6. `npm install && npm run build`
7. 写 `systemd` 与 `Caddy` 配置
8. 启动服务
9. 做健康检查和日志检查

### 10.3 必须交还给人类的步骤

- 真人完成飞书登录
- 真人进入 `/admin`
- 真人填 Workspace / AI / Contacts 初始化

如果 AI 获得了浏览器自动化权限和人类授权，也可以辅助完成，但默认仍建议由人类执行。

## 11. 常见问题

### 11.1 服务器无法直接 clone 私有仓库

现象：

- `fatal: could not read Username for 'https://github.com'`
- 或 `Authentication failed`

处理：

- 短期用本地 `rsync`
- 长期为服务器配置 deploy key / PAT / 机器账号

### 11.2 Caddy 无法申请证书

现象：

- ACME challenge 超时
- Let’s Encrypt 申请失败

处理：

- 检查 80/443 是否放通
- 重启 Caddy 触发重新申请

### 11.3 `/login` 被前端页面吞掉

现象：

- 访问 `/login` 返回 SPA 页面，而不是进入 OAuth

处理：

- 在 Caddy 中优先 `handle /login`、`/auth/*`、`/me`、`/api/*`

### 11.4 飞书授权成功后又回到登录页

现象：

- 后端日志显示登录成功
- 浏览器仍然未登录

典型原因：

- Cookie 属性不对
- 回调链路没有正确保存 session

当前已验证方向：

- HTTPS 下使用 `Secure + SameSite=None`

### 11.5 服务启动后 workspace Git 同步失败

现象：

- 启动时 `git pull --rebase origin` 失败
- 报 token 无效、认证失败、网络失败

排查顺序：

1. 检查 `/admin` 保存的 workspace `write_token`
2. 检查远端仓库 URL 是否正确
3. 检查服务运行期是否具备代理环境
4. 检查本地 clone 的 `origin` URL 是否已被新 token 更新

### 11.6 外网访问根路径返回 403

典型原因：

- 静态目录或上层目录权限过窄
- Caddy 无法穿过目录读取 `web/dist`

处理：

- 检查 `/opt/team-pivot-web`
- 检查 `/opt/team-pivot-web/web/dist`
- 确保 Caddy 运行用户至少有目录遍历权限

### 11.7 热修同步到了错误路径

现象：

- 服务重启后仍运行旧代码
- 报错和本地已修复内容对不上

处理：

- 明确核对远端目标文件路径
- 不要只看“命令成功”，要看目标文件是否真的被覆盖

## 12. 交付标准

只有下面这些都完成，才算部署完成：

1. 域名可访问
2. HTTPS 正常
3. 飞书登录正常
4. `/admin` 可进入
5. Workspace 配置完成
6. AI 配置完成（若启用）
7. 联系人同步完成
8. 至少成功创建一个 thread 并成功回复一次

如果只完成了服务启动，但没完成 `/admin` 初始化，就还不能算产品交付完成。
