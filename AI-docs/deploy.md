# Deployment Guide

本文档记录 `team-pivot-web` 首次部署到生产环境时的实际过程、踩坑和修复方案，供以后再次部署或迁移服务器时参考。

## 生产环境信息

- 域名: `pivot.enclaws.ai`
- 服务器公网 IP: `43.156.44.240`
- 系统: `Ubuntu 24 LTS`
- 运行方式:
  - `systemd` 启动 FastAPI/Uvicorn
  - `Caddy` 提供 HTTPS 和反向代理
- 部署目录:
  - 代码: `/opt/team-pivot-web`
  - 数据: 当前实际使用 `/opt/team-pivot-web/var`

## 首次部署的实际步骤

### 1. SSH 连接

使用 PEM 私钥连接服务器时，遇到过两个问题:

- 私钥权限过宽，`0644` 被 SSH 拒绝
- `known_hosts` 里有旧主机指纹

修复方法:

```bash
chmod 600 /Users/ken/Codes/ssh/my_test_singapore.pem
ssh-keygen -R 43.156.44.240
ssh -i /Users/ken/Codes/ssh/my_test_singapore.pem ubuntu@43.156.44.240
```

### 2. 安装基础依赖

服务器上安装过这些依赖:

```bash
sudo apt update
sudo apt install -y caddy git curl nodejs npm
curl -LsSf https://astral.sh/uv/install.sh | sh
```

说明:

- 服务器安装出的 Node 版本是 `v18.19.1`
- 前端构建时会有 `react-router` 对 Node 20 的 warning，但当时构建成功，没有阻塞上线

### 3. 上传代码

仓库是私有仓库，服务器直接 `git clone https://github.com/...` 失败，因为缺少 GitHub 凭据。

当时采用的方案不是在服务器上直接 clone，而是从本地用 `rsync` 上传代码:

```bash
rsync -avz \
  --exclude='.git' \
  --exclude='node_modules' \
  --exclude='web/node_modules' \
  --exclude='web/dist' \
  --exclude='__pycache__' \
  --exclude='.venv' \
  --exclude='var/' \
  -e "ssh -i /Users/ken/Codes/ssh/my_test_singapore.pem" \
  /Users/ken/Codes/team-pivot-web/ \
  ubuntu@43.156.44.240:/opt/team-pivot-web/
```

如果以后服务器已经有可用的 GitHub 凭据，也可以直接在服务器上拉代码。

### 4. 安装 Python 依赖并构建前端

```bash
cd /opt/team-pivot-web
~/.local/bin/uv sync

cd web
npm install
npm run build
```

### 5. 上传 `.env`

生产环境需要至少确认这些变量:

```env
FEISHU_APP_ID=...
FEISHU_APP_SECRET=...
FEISHU_REDIRECT_URI=https://pivot.enclaws.ai/auth/callback
SESSION_SECRET=...
WEB_DEV_ORIGIN=https://pivot.enclaws.ai
WORKSPACE_REPO_URL=https://github.com/kellerman-koh/test-team-pivot.git
WORKSPACE_BRANCH=main
GIT_TOKEN=...
LOG_LEVEL=INFO
ADMIN_PASSWORD=...
```

注意:

- `FEISHU_REDIRECT_URI` 必须是生产域名
- `WEB_DEV_ORIGIN` 虽然名字叫 `DEV`，生产上也要改成正式域名
- `GIT_TOKEN` 用于服务器上的 workspace 自动 pull/push 目标仓库

## systemd 配置

最终可工作的服务配置核心如下:

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

常用命令:

```bash
sudo systemctl daemon-reload
sudo systemctl enable team-pivot-web
sudo systemctl restart team-pivot-web
systemctl status team-pivot-web --no-pager
journalctl -u team-pivot-web -n 100 --no-pager
```

## Caddy 配置

最终修正后的 Caddy 配置重点是: 后端路由必须先 `handle`，不能直接让 SPA 把 `/login`、`/auth/*` 等路径吃掉。

```caddy
pivot.enclaws.ai {
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

重载:

```bash
sudo systemctl reload caddy
sudo systemctl restart caddy
sudo journalctl -u caddy -n 100 --no-pager
```

## 真实部署中遇到的问题与解决方案

### 问题 1: SSH 报私钥权限错误

现象:

- `UNPROTECTED PRIVATE KEY FILE`
- `Permissions 0644 ... are too open`

原因:

- PEM 私钥权限不正确

解决:

```bash
chmod 600 /path/to/key.pem
```

### 问题 2: SSH 报主机指纹变更

现象:

- `REMOTE HOST IDENTIFICATION HAS CHANGED`

原因:

- 目标 IP 之前对应过别的机器，`known_hosts` 里残留了旧记录

解决:

```bash
ssh-keygen -R 43.156.44.240
```

### 问题 3: 无法从服务器直接 clone 私有仓库

现象:

- `fatal: could not read Username for 'https://github.com'`

原因:

- 仓库是私有仓库，但服务器端没有 GitHub 认证信息

解决:

- 短期方案: 本地 `rsync` 到服务器
- 长期方案: 给服务器配置 PAT 或 deploy key

### 问题 4: systemd 服务启动失败，状态 `209/STDOUT`

现象:

- `team-pivot-web.service: Failed to set up standard output: No such file or directory`
- `status=209/STDOUT`

原因:

- `StandardOutput=append:...` 指向的日志目录不存在

解决:

- 最后直接移除了 `StandardOutput` / `StandardError` 的文件追加配置，改用 `journalctl`
- 如果后续仍想写文件日志，必须先确保目录存在

### 问题 5: DNS 本地看起来没生效

现象:

- 本地 `dig pivot.enclaws.ai` 返回旧地址 `198.18.0.177`
- 但公共 DNS 已经返回 `43.156.44.240`

原因:

- 本地 DNS 缓存没刷新

解决:

直接指定公共 DNS 验证:

```bash
dig +short pivot.enclaws.ai @8.8.8.8
dig +short pivot.enclaws.ai @1.1.1.1
```

### 问题 6: Caddy 无法申请证书

现象:

- `Timeout during connect (likely firewall problem)`
- Let's Encrypt / ACME challenge 失败

原因:

- 腾讯云安全组没有放通 80/443

解决:

在腾讯云安全组添加入站规则:

- TCP 80, 来源 `0.0.0.0/0`
- TCP 443, 来源 `0.0.0.0/0`

然后重启 Caddy 触发重新申请证书:

```bash
sudo systemctl restart caddy
```

成功标志:

- `certificate obtained successfully`

### 问题 7: `/login` 没有跳转飞书 OAuth，而是返回前端首页

现象:

- 访问 `https://pivot.enclaws.ai/login` 返回的是 SPA 页面
- 浏览器里点登录后没有进入飞书授权页

原因:

- Caddy 的 `try_files` 先把 `/login` 重写成了 `index.html`

解决:

- 改用 `handle /login`、`handle /auth/*`、`handle /me` 等明确走后端
- 最后再用一个兜底 `handle` 服务前端静态资源

### 问题 8: 飞书授权成功后又回到登录页

现象:

- 飞书授权页能打开
- 授权成功后后端日志有 `login success`
- 但浏览器回到首页仍显示未登录

原因:

- 生产环境下 session cookie 的跨站回跳兼容性有问题
- 最终修复为:
  - 生产环境 `secure=True`
  - 生产环境 `samesite="none"`
  - 开发环境保持 `samesite="lax"`

涉及代码:

- `server/auth/routes.py`

结论:

- 只看后端 `login success` 不够，还要确认浏览器是否真正保存了 cookie

### 问题 9: 修复代码同步到服务器时传错路径，导致服务反复重启

现象:

- `build_router() got an unexpected keyword argument 'secure_cookie'`

原因:

- 本地修了 `server/auth/routes.py`
- 但第一次同步时路径写错，没有把文件传到 `/opt/team-pivot-web/server/auth/routes.py`

解决:

重新把正确文件传到正确位置，然后重启服务:

```bash
scp -i /path/to/key.pem \
  /local/server/auth/routes.py \
  ubuntu@43.156.44.240:/opt/team-pivot-web/server/auth/routes.py

ssh -i /path/to/key.pem ubuntu@43.156.44.240 \
  "sudo systemctl restart team-pivot-web"
```

这个问题说明: 生产热修时，必须确认远端文件路径，不然很容易以为“代码已上线”，实际没有。

## 飞书开放平台配置

至少需要确认:

- 重定向 URL 包含:
  - `https://pivot.enclaws.ai/auth/callback`
- 安全域名包含生产域名

如果 OAuth 无法正常回跳，除了看服务器日志，也要回头检查飞书后台配置。

## 以后再次部署时的建议顺序

推荐顺序:

1. 确认 DNS 已指向服务器
2. 确认安全组已放通 `22/80/443`
3. 上传代码或拉取代码
4. 更新 `.env`
5. `uv sync`
6. `npm install && npm run build`
7. 重启 `team-pivot-web`
8. 重启或重载 `caddy`
9. 验证:
   - `systemctl is-active team-pivot-web`
   - `curl http://127.0.0.1:8000/me`
   - `curl -I https://pivot.enclaws.ai`
   - 浏览器里走完整飞书登录

## 部署后最重要的检查项

### 后端健康检查

```bash
systemctl status team-pivot-web --no-pager
journalctl -u team-pivot-web -n 100 --no-pager
curl -s http://127.0.0.1:8000/me
```

预期:

- 服务是 `active`
- 未登录时 `/me` 返回 `401` 或 `{"detail":"not logged in"}`

### HTTPS 检查

```bash
curl -I https://pivot.enclaws.ai
```

预期:

- 返回 `HTTP/2 200`

### 登录流程检查

浏览器中验证:

1. 打开首页
2. 点击登录
3. 跳转飞书 OAuth
4. 授权后回到站点
5. 不应再回到登录页

## 结论

这次生产部署真正遇到的核心坑只有四类:

- SSH 与服务器访问问题
- 私有仓库代码同步问题
- Caddy / DNS / HTTPS / 防火墙问题
- OAuth 回跳后的 session cookie 问题

以后再次部署时，优先排查这四类，能节省最多时间。
