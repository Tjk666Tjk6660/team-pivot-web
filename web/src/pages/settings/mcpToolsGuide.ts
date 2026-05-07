export interface McpToolGuide {
  name: string;
  title: string;
  body: string;
  examples: string[];
}

export const MCP_TOOLS_GUIDE: McpToolGuide[] = [
  {
    name: "list_matters",
    title: "查找可见 matters",
    body:
      "按状态、负责人或关键词列出当前用户能访问的 matters。" +
      "也支持「与我相关」过滤——只看你有未读相关项（被 @、回复你的文件、verify 你的文件等）的 matter。",
    examples: [
      "看一下所有的 matter",
      "最近有什么 matter",
      "列一下 xxx 的 matter",
      "我的待办",
      "查看与我相关的帖子",
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
    body:
      "在你的明确确认后，AI 可以新建一个 matter，连同首条 timeline 文件（type=think/act）一起落盘。" +
      "如果设置了限制可见范围（matter 或新分类），创建者必须落在范围内——AI 会先校验、不然直接拒，避免发出来连自己都看不见。",
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
    name: "add_mention",
    title: "留言 / 圈人",
    body: "在已有文件下追加一条留言（等价于 Web 上的「@ 提及」按钮），可选 @ 通知相关同事到飞书。",
    examples: [
      "对这条 think 留言：...，并圈 X 看",
      "@ X review 这条",
      "圈一下 X 提醒看这条",
    ],
  },
  {
    name: "add_annotation",
    title: "评估 / 评分意见",
    body: "对某条文件写一条结构化评估（v1 仅 type=evaluation）。无需 @ 谁，文件的相关方（创建者 / matter owner / matter creator）会自动收到飞书 DM。",
    examples: [
      "对这条 verify 写个评估",
      "评一下这条 result",
      "给 003 这条做个 evaluation",
    ],
  },
  {
    name: "list_visibility_options",
    title: "查看可见范围候选",
    body: "列出可以选作 matter / 分类可见范围的角色和成员名单——通常配合 create_matter 使用，让你 / AI 知道当前能限给谁。",
    examples: [
      "哪些角色能选",
      "看下这个分类能限制给谁",
    ],
  },
];

export const MCP_FIRST_MESSAGE_PROMPT =
  "你已经接入了 Pivot MCP。请告诉我它现在能做什么，每个能力我用中文什么样的话能触发，给我每个能力 2 个具体例子。";
