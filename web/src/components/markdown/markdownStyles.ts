export const DEFAULT_MARKDOWN_STYLE = "code-light" as const;

export const MARKDOWN_STYLES = [
  {
    id: "code-light",
    label: "代码白",
    description: "接近 GitHub 文档的浅色技术文档风格，代码和表格边界清晰。",
    tone: "light",
  },
  {
    id: "collab-blue",
    label: "协作蓝",
    description: "清爽办公文档风格，蓝色标题强调，适合团队协作阅读。",
    tone: "light",
  },
  {
    id: "page-brown",
    label: "书页棕",
    description: "偏长文和书页阅读的暖色衬线风格。",
    tone: "light",
  },
  {
    id: "solarized-light",
    label: "护眼浅",
    description: "低刺激浅色配色，标题色彩层级明显。",
    tone: "light",
  },
  {
    id: "neon-dark",
    label: "霓虹暗",
    description: "高对比暗色技术风格，适合夜间和代码阅读。",
    tone: "dark",
  },
  {
    id: "nord-dark",
    label: "极地暗",
    description: "克制冷色暗色主题，适合长时间阅读。",
    tone: "dark",
  },
] as const;

export type MarkdownStyleId = (typeof MARKDOWN_STYLES)[number]["id"];
export type MarkdownStyleTone = (typeof MARKDOWN_STYLES)[number]["tone"];

export type MarkdownStyleMeta = {
  id: MarkdownStyleId;
  label: string;
  description: string;
  tone: MarkdownStyleTone;
};

const STYLE_IDS = new Set<string>(MARKDOWN_STYLES.map((style) => style.id));

export function isMarkdownStyleId(value: unknown): value is MarkdownStyleId {
  return typeof value === "string" && STYLE_IDS.has(value);
}

export function normalizeMarkdownStyle(value: unknown): MarkdownStyleId {
  return isMarkdownStyleId(value) ? value : DEFAULT_MARKDOWN_STYLE;
}

export function getMarkdownStyleClass(styleId: MarkdownStyleId): string {
  return `prose-pivot--${styleId}`;
}
