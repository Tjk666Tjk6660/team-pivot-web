# Changelog

## 0.2.0 - 2026-04-27
### Title
Matter 工作流首个完整版本

### Added
- 新增 Matter 模型与六态状态机，支持 `think / act / verify / insight / result` 时间线文件。
- 新增 Matter 列表、详情、创建、追加文件、结果收口、收藏、未读和负责人能力。
- 新增 Matter 草稿自动保存、恢复、指定草稿打开，以及 AI 生成摘要和回复草稿。
- 新增 Matter 实时刷新事件流，列表和详情可响应创建、更新、评论和状态变化。
- 新增 MCP 外部 AI 接入：PAT 鉴权、上下文解析、Matter 查询、文件读取、创建文件预览和客户端配置生成。
- 新增 legacy thread 到 Matter index 的迁移脚本与迁移测试辅助。

### Changed
- 首页、主导航和核心工作流从 `thread` 叙事切换为 `Matter` 叙事。
- AI 助手改为 Matter 作用域，支持读取 Matter index、搜索 Matter，并在对话中复用当前讨论上下文。
- 飞书通知补齐 Matter 状态中文标签、触发文件信息和 `/m/:matter_id` 跳转。
- Matter UI 持续打磨：侧边栏、时间线、移动端交互、AI 面板、复制给 AI、草稿卡片和状态提示更贴近实际使用。
- 草稿发布路径收紧为 Matter 发布合同，历史 thread 草稿不再作为主要发布路径。

### Fixed
- 修复 Matter 收藏、未读、负责人、评论作者、提及写入和状态流转中的多处一致性问题。
- 修复 SSE 恢复、会话过期跳转、MCP 视图 URL、迁移时 SQLite 只读打开和 mention.comments 保留问题。
- 修复旧 thread 迁移到 Matter index 时的文件命名、frontmatter 更新、验证关系和异常恢复边界。

### Notes
- 当前产品核心已经从 `Discuss/thread` 迁移到 `Matter`。
- 旧 thread 相关 API 和测试仍有兼容残留，后续版本会继续清理 P5 范围内的历史接口。

## 0.1.0 - 2026-04-20
### Title
讨论工作台首个可用版本

### Added
- 飞书 OAuth 登录、首次登录补全个人资料。
- 讨论线程列表、详情、回复、提及与未读状态。
- Proposal / Reply 草稿与自动保存。
- 线程内 AI 助手、引用文件浏览与回复草稿生成。
- 个人 PAT 管理接口，支持 VS Code 客户端接入。
- 管理员工作区配置与 Git mirror bootstrap 接口。

### Changed
- 工作区仓库配置从环境变量迁移到 SQLite `settings`。
- 管理员设置页针对 PC 宽屏重新布局。

### Notes
- 0.1.0 的核心对象是 `Discuss/thread`，0.2.0 已切换到 `Matter`。
