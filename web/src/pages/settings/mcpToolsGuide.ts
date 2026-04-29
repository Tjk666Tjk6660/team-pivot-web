export interface McpToolGuide {
  name: string;
  title: string;
  body: string;
  examples: string[];
}

export const MCP_TOOLS_GUIDE: McpToolGuide[] = [
  {
    name: "resolve_context",
    title: "解析复制链接",
    body: "AI 收到「复制给 AI」的 matter / 文件 URL 后，用这个工具确认链接对应的 matter、文件和当前状态，并把可读摘要展示给你核对。",
    examples: [
      "看一下这个帖子 <粘贴 Pivot 链接>",
      "对这个 matter 加条评论 <url>",
    ],
  },
  {
    name: "list_matters",
    title: "查找可见 matters",
    body: "按状态、负责人或关键词列出当前用户能访问的 matters，适合让 AI 先帮你找相关讨论。",
    examples: [
      "看一下所有的 matter",
      "最近有什么 matter",
      "列一下 xxx 的 matter",
    ],
  },
  {
    name: "get_matter",
    title: "读取时间线目录",
    body: "获取 matter 标题、状态、可触发的状态迁移，以及时间线上的文件元数据；不拉正文，方便 AI 先判断该读哪些文件。",
    examples: [
      "看下「X」这条 matter",
      "X matter 现在的进度",
      "summarize matter X",
    ],
  },
  {
    name: "read_files",
    title: "读取文件正文",
    body: "按文件路径读取完整正文和作者、类型等信息。单次最多 5 篇、总量有上限，避免 AI 一次拉太多上下文。",
    examples: [
      "展开这条 think 的具体内容",
      "读一下这个 matter 里 002 那篇的正文",
    ],
  },
  {
    name: "create_matter",
    title: "新建 matter",
    body: "在你的明确确认后，AI 可以新建一个 matter，连同首条 timeline 文件（type=think/act）一起落盘。",
    examples: [
      "在 mcp 下新开一个 matter，标题叫 X，帮我起草内容",
      "起一个 matter 跟踪 X",
    ],
  },
  {
    name: "create_file",
    title: "写入新文件",
    body: "在你的明确确认后，AI 可以在已有 matter 下创建 think / act / verify / result / insight 文件；如果涉及状态变更，也必须先把可选迁移展示给你选择。",
    examples: [
      "回复 002 那条，写一下 ...",
      "针对 X 跟一条 verify",
      "在 X matter 里加一条 act：...",
    ],
  },
  {
    name: "add_comment",
    title: "评论 / 圈人",
    body: "在已有文件下追加一条评论（等价于 Web 上的「@ 提及」按钮），可选 @-mention 通知相关同事到飞书。",
    examples: [
      "对这条 think 评论：...，并圈 X 看",
      "@ X review 这条",
      "圈一下 X 提醒看这条",
    ],
  },
];

export const MCP_FIRST_MESSAGE_PROMPT =
  "你已经接入了 Pivot MCP。请告诉我它现在能做什么，每个能力我用中文什么样的话能触发，给我每个能力 2 个具体例子。";
