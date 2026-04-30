# team-pivot-web

带身份 / 审批 / 邀请治理的团队讨论 Web 客户端，邮件客户端式 UX，Git 作数据后端。

从 [hashSTACS-Global/team-pivot](https://github.com/hashSTACS-Global/team-pivot) fork 而来，正在从零重构为独立 Web 应用。原 APP 版本全部代码已移入 [old/](./old) 供参考和选择性复用（尤其 `pipelines/` 里的 markdown 解析、git 同步、inbox 聚合逻辑）。

## 状态

- [x] 飞书 OAuth2 登录 + 邀请码邮箱密码登录
- [x] 用户管理（首部署初始化、申请审批、暂停 / 停用、邀请生成）
- [x] 后端脚手架（FastAPI + SQLite）
- [x] 前端脚手架（React + Vite + shadcn/ui）
- [x] 讨论列表 / 详情 / 回复
- [x] 草稿管理
- [x] 飞书机器人通知
- [x] Matter（项目类讨论）+ owner 流转

## 技术栈

后端 Python 3.12 + FastAPI + SQLite + bcrypt；前端 React + Vite + TanStack Query + shadcn/ui；部署直接跑 systemd + Caddy 在 Ubuntu 24 LTS 上。
