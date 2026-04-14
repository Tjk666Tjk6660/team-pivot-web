# Ken's Changelog

## 2026-04-15: 修正 EC 技能安装方式

### 原因

原来的安装流程要求 EC 管理员通过服务端控制面板手动配置（填写 Git URL、预装 Python 依赖等），但实际场景中用户只能通过飞书客户端或 EC 网页控制台的 chat 访问 EC，无法直接操作服务器目录。

EC 的标准 skill 安装方式是：把包含 `SKILL.md` 的目录放到 `~/.enclaws/skills/` 下，EC 自动发现。而 EC agent 本身有 Bash 工具，可以在服务器上执行 `git clone`，所以用户只需在 chat 中告诉 bot 执行克隆命令即可完成安装。

### 改动

**SKILL.md**
- 添加了标准 EC skill frontmatter（`name: team-pivot`、`description`、`metadata.openclaw`），使 EC 能正确发现和加载此技能
- 删除了旧的 HTML 注释头（"此文件是 EC 平台 Pipeline Runner 的 LLM fallback prompt"），该描述已不再准确
- 功能性内容（pipeline 列表、调用规则、禁止事项等）保持不变

**README.md / README_zh.md**
- 移除了旧的「EC 管理员（服务端）」安装部分（要求打开管理面板、添加 Agent APP 等）
- 新增「EC 用户（通过 chat 安装）」部分，提供一句话安装/更新/卸载指令
- 项目结构中 `SKILL.md` 的描述从 "EC server-side LLM fallback prompt" 改为 "EC skill definition"
- 「AI 工具怎么用」部分区分了 EC agent 和 Claude Code 两种使用方式
