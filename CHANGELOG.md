# Changelog

## 0.1.0 - 2026-04-20
### Title
讨论工作台首个可用版本

### Added
- 飞书 OAuth 登录、首次登录补充个人资料
- 讨论线程列表、详情、回复、提及与未读状态
- Proposal / Reply 草稿与自动保存
- 线程内 AI 助手、引用文件浏览与回复草稿生成
- 个人 PAT 管理接口，支持 VS Code 客户端接入
- 管理员工作区配置与 Git mirror bootstrap 接口

### Changed
- 工作区仓库配置从环境变量迁移到 SQLite `settings`
- 管理员设置页针对 PC 宽屏重新布局

### Notes
- 当前产品核心仍是 `Discuss` 模块。
- 欢迎首页、接口文档与后续 `Result / Project / Task` 会在后续版本持续完善。
