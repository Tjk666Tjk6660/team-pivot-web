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
  think:   { label: "think",   side: "border-l-blue-400",    chip: "bg-blue-100 text-blue-700 ring-blue-200",         dot: "bg-blue-500",    pill: "text-blue-700"    },
  act:     { label: "act",     side: "border-l-emerald-400", chip: "bg-emerald-100 text-emerald-700 ring-emerald-200", dot: "bg-emerald-500", pill: "text-emerald-700" },
  verify:  { label: "verify",  side: "border-l-amber-400",   chip: "bg-amber-100 text-amber-700 ring-amber-200",       dot: "bg-amber-500",   pill: "text-amber-700"   },
  result:  { label: "result",  side: "border-l-purple-500",  chip: "bg-purple-100 text-purple-700 ring-purple-200",    dot: "bg-purple-600",  pill: "text-purple-700"  },
  insight: { label: "insight", side: "border-l-slate-400",   chip: "bg-slate-100 text-slate-700 ring-slate-200",       dot: "bg-slate-500",   pill: "text-slate-700"   },
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
