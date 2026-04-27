import type { DocType, MatterStatus } from "@/api";

// status × type 允许矩阵（pivot-interface.md §最小服务端校验建议）
export const ALLOWED_TYPES_BY_STATUS: Record<MatterStatus, DocType[]> = {
  planning:  ["think", "act", "verify"],
  executing: ["think", "act", "verify", "result"],
  paused:    ["think"],
  finished:  ["insight"],
  cancelled: ["insight"],
  reviewed:  [],
};

export type TypeVisual = {
  label: string;
  side: string;
  chip: string;
  dot: string;
  pill: string;
};

export const TYPE_VISUAL: Record<DocType, TypeVisual> = {
  think:   { label: "think",   side: "border-l-[var(--info-500)]",   chip: "bg-[var(--status-discussing-bg)] text-[var(--status-discussing-fg)] ring-[var(--line)]", dot: "bg-[var(--info-500)]",    pill: "text-[var(--status-discussing-fg)]" },
  act:     { label: "act",     side: "border-l-[var(--ok-500)]",     chip: "bg-[var(--status-concluded-bg)] text-[var(--status-concluded-fg)] ring-[var(--line)]",   dot: "bg-[var(--ok-500)]",      pill: "text-[var(--status-concluded-fg)]" },
  verify:  { label: "verify",  side: "border-l-[var(--warn-500)]",   chip: "bg-[var(--status-paused-bg)] text-[var(--status-paused-fg)] ring-[var(--line)]",        dot: "bg-[var(--warn-500)]",    pill: "text-[var(--status-paused-fg)]" },
  result:  { label: "result",  side: "border-l-[var(--violet-500)]", chip: "bg-[var(--status-project-bg)] text-[var(--status-project-fg)] ring-[var(--line)]",       dot: "bg-[var(--violet-500)]",  pill: "text-[var(--status-project-fg)]" },
  insight: { label: "insight", side: "border-l-[var(--text-fade)]",  chip: "bg-[var(--status-archived-bg)] text-[var(--status-archived-fg)] ring-[var(--line)]",    dot: "bg-[var(--text-mute)]",   pill: "text-[var(--status-archived-fg)]" },
};

export const STATUS_DESC: Record<MatterStatus, string> = {
  planning:  "think 为主，允许预演 act / verify",
  executing: "act 驱动推进，可随时 verify",
  paused:    "冻结写入：只允许 think",
  finished:  "收口：只允许 insight",
  cancelled: "收口：只允许 insight",
  reviewed:  "终态：不再新增文件",
};

export const MAX_REFER = 4;

export function shortFile(path: string | null | undefined): string {
  if (!path) return "";
  return path.split("/").pop() || "";
}
