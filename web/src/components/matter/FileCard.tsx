import { useState } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { MessageSquare, Plus } from "lucide-react";
import type { DocType, Judgement, MatterStatus, TimelineItem } from "@/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import { relativeTime, formatFullDateTime } from "@/lib/time";
import {
  ALLOWED_TYPES_BY_STATUS,
  TYPE_VISUAL,
  shortFile,
} from "./timeline-config";

const COLLAPSE_HEIGHT = 208;

export function FileCard({
  item,
  index,
  matterStatus,
  onCreate,
  onAddComment,
  onJump,
  registerRef,
  highlighted,
}: {
  item: TimelineItem;
  index: number;
  matterStatus: MatterStatus;
  onCreate: (type: DocType, quote: string) => void;
  onAddComment: (body: string) => Promise<void>;
  onJump: (file: string) => void;
  registerRef?: (el: HTMLDivElement | null) => void;
  highlighted?: boolean;
}) {
  const cfg = TYPE_VISUAL[item.type];
  const [expanded, setExpanded] = useState(false);
  const allowed = ALLOWED_TYPES_BY_STATUS[matterStatus];
  const allowThink = allowed.includes("think");
  const allowAct = allowed.includes("act");
  const allowVerify = allowed.includes("verify");

  return (
    <article
      ref={registerRef}
      className={cn(
        "scroll-mt-24 rounded-2xl border border-slate-200 border-l-[6px] bg-white p-4 shadow-sm sm:p-5",
        cfg.side,
        highlighted && "ring-2 ring-blue-300",
      )}
    >
      {/* header */}
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          <span
            className={cn(
              "inline-flex items-center rounded-md px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide ring-1",
              cfg.chip,
            )}
          >
            {cfg.label}
          </span>
          <span className="font-mono text-xs text-slate-700">{shortFile(item.file)}</span>
          <span className="text-[11px] text-slate-400">#{index + 1}</span>
        </div>
        <div className="flex flex-wrap items-center gap-2 text-[11px] text-slate-500">
          <span>
            作者 <span className="font-medium text-slate-700">{item.creator}</span>
          </span>
          {item.creator !== item.owner && (
            <span>
              · 执行 <span className="font-medium text-slate-700">{item.owner}</span>
            </span>
          )}
          <span>·</span>
          <span title={formatFullDateTime(item.created_at)}>{relativeTime(item.created_at)}</span>
        </div>
      </div>

      {/* summary + AI 摘要候选 slot */}
      <div className="mt-3 flex flex-wrap items-start gap-2">
        <p className="min-w-0 flex-1 text-[14px] font-medium text-slate-900">{item.summary}</p>
        <span
          className="shrink-0 rounded border border-dashed border-slate-300 bg-slate-50/70 px-1.5 py-0.5 text-[10px] text-slate-500"
          title="AI 摘要候选（Phase 3 占位）"
        >
          AI 摘要候选
        </span>
      </div>

      {/* quote / refer / status_change chips */}
      {(item.quote || (item.refer && item.refer.length > 0) || item.status_change) && (
        <div className="mt-2 flex flex-wrap items-center gap-1.5">
          {item.quote && (
            <button
              type="button"
              onClick={() => onJump(item.quote as string)}
              className="inline-flex items-center gap-1 rounded-full bg-slate-100 px-2 py-0.5 text-[11px] text-slate-700 ring-1 ring-slate-200 hover:bg-slate-200"
              title={item.quote}
            >
              ← quote: <span className="font-mono">{shortFile(item.quote)}</span>
            </button>
          )}
          {item.refer && item.refer.length > 0 && (
            <span
              className="inline-flex items-center gap-1 rounded-full bg-indigo-50 px-2 py-0.5 text-[11px] text-indigo-700 ring-1 ring-indigo-200"
              title={item.refer.join("\n")}
            >
              ↔ refer: {item.refer.length}
            </span>
          )}
          {item.status_change && (
            <span className="inline-flex items-center gap-1 rounded-full bg-purple-50 px-2 py-0.5 text-[11px] text-purple-700 ring-1 ring-purple-200">
              status: {item.status_change.from} → {item.status_change.to}
            </span>
          )}
        </div>
      )}

      {/* verify: verifications table */}
      {item.type === "verify" && item.verifications && item.verifications.length > 0 && (
        <div className="mt-3 overflow-hidden rounded-lg border border-amber-200">
          <table className="w-full text-xs">
            <thead className="bg-amber-50 text-[11px] uppercase text-amber-800">
              <tr>
                <th className="px-3 py-1.5 text-left">target (act)</th>
                <th className="px-3 py-1.5 text-left">judgement</th>
                <th className="px-3 py-1.5 text-left">comment</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-amber-100 bg-white">
              {item.verifications.map((v, i) => (
                <tr key={i}>
                  <td className="px-3 py-1.5">
                    <button
                      type="button"
                      onClick={() => onJump(v.target)}
                      className="font-mono text-[11px] text-slate-700 hover:underline"
                    >
                      {shortFile(v.target)}
                    </button>
                  </td>
                  <td className="px-3 py-1.5">
                    <JudgementChip judgement={v.judgement} />
                  </td>
                  <td className="px-3 py-1.5 text-slate-600">{v.comment}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* result banner */}
      {item.type === "result" && item.outcome && (
        <div
          className={cn(
            "mt-3 rounded-lg px-4 py-3 text-sm font-semibold",
            item.outcome === "finished"
              ? "bg-green-50 text-green-800 ring-1 ring-green-200"
              : "bg-slate-100 text-slate-700 ring-1 ring-slate-300",
          )}
        >
          Matter 结果：{item.outcome === "finished" ? "已完成 finished" : "已取消 cancelled"}
        </div>
      )}

      {/* body */}
      {item.body && (
        <>
          <div
            style={expanded ? undefined : { maxHeight: COLLAPSE_HEIGHT, overflow: "hidden" }}
            className="prose-pivot mt-3 max-w-none text-[13.5px] leading-7 text-slate-700"
          >
            <Markdown remarkPlugins={[remarkGfm]}>{item.body}</Markdown>
          </div>
          <button
            type="button"
            onClick={() => setExpanded((v) => !v)}
            className="mt-1 text-xs text-blue-600 hover:underline"
          >
            {expanded ? "收起 ↑" : "展开全文 ↓"}
          </button>
        </>
      )}

      {/* comments */}
      <CommentsBlock item={item} onAddComment={onAddComment} />

      {/* AI 建议 slot */}
      <div className="mt-3 rounded-lg border border-dashed border-slate-300 bg-slate-50/50 px-3 py-2 text-[11px] text-slate-500">
        <span className="rounded-full bg-slate-200 px-2 py-0.5 text-[10px] font-medium text-slate-600">AI</span>
        <span className="ml-2">AI 建议（Phase 3 占位）· 将针对这篇 {cfg.label} 给出后续判断</span>
      </div>

      {/* 三入口 */}
      <div className="mt-3 flex flex-wrap items-center gap-1.5 border-t border-slate-100 pt-3">
        <CardAddButton label="think" disabled={!allowThink} onClick={() => onCreate("think", item.file)} />
        <CardAddButton label="act" disabled={!allowAct} onClick={() => onCreate("act", item.file)} />
        <CardAddButton label="verify" disabled={!allowVerify} onClick={() => onCreate("verify", item.file)} />
        <div className="ml-auto text-[10px] text-slate-400">
          点按钮 · 新文件 quote 自动写入 <span className="font-mono">{shortFile(item.file)}</span>
        </div>
      </div>
    </article>
  );
}

function CardAddButton({
  label,
  disabled,
  onClick,
}: {
  label: string;
  disabled: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      title={disabled ? "当前 matter 状态不允许新增此类型" : `基于此新增 ${label}`}
      className={cn(
        "inline-flex items-center gap-1 rounded-md border px-2 py-1 text-[11px] font-medium transition-colors",
        disabled
          ? "cursor-not-allowed border-slate-200 text-slate-400"
          : "border-slate-300 text-slate-700 hover:border-blue-400 hover:bg-blue-50 hover:text-blue-700",
      )}
    >
      <Plus className="h-3 w-3" />
      {label}
    </button>
  );
}

function JudgementChip({ judgement }: { judgement: Judgement }) {
  const MAP: Record<Judgement, string> = {
    passed: "bg-green-100 text-green-800 ring-green-200",
    failed: "bg-red-100 text-red-800 ring-red-200",
    cancelled: "bg-slate-100 text-slate-600 ring-slate-300",
  };
  return (
    <span className={cn("inline-flex rounded-full px-2 py-0.5 text-[11px] font-medium ring-1", MAP[judgement])}>
      {judgement}
    </span>
  );
}

function CommentsBlock({
  item,
  onAddComment,
}: {
  item: TimelineItem;
  onAddComment: (body: string) => Promise<void>;
}) {
  const [draft, setDraft] = useState("");
  const [open, setOpen] = useState(item.comments.length > 0);
  const [submitting, setSubmitting] = useState(false);

  if (item.comments.length === 0 && !open) {
    return (
      <div className="mt-3">
        <button
          type="button"
          onClick={() => setOpen(true)}
          className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-[11px] text-slate-500 hover:bg-slate-100 hover:text-slate-700"
        >
          <MessageSquare className="h-3 w-3" />
          添加评论
        </button>
      </div>
    );
  }

  const submit = async () => {
    if (!draft.trim()) return;
    setSubmitting(true);
    try {
      await onAddComment(draft);
      setDraft("");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="mt-3 rounded-lg border border-slate-200 bg-slate-50/60 p-3">
      <div className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-slate-500">
        <MessageSquare className="h-3 w-3" />
        comments · {item.comments.length}
      </div>
      {item.comments.length > 0 && (
        <ul className="mt-2 space-y-2">
          {item.comments.map((c, i) => (
            <li key={i} className="text-xs">
              <div className="flex items-center gap-2 text-[11px] text-slate-500">
                <span className="font-medium text-slate-700">{c.author}</span>
                <span>·</span>
                <span>{relativeTime(c.created_at)}</span>
              </div>
              <div className="mt-0.5 text-slate-700">{c.body}</div>
            </li>
          ))}
        </ul>
      )}
      <div className="mt-2 flex items-center gap-1.5">
        <Input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="写条评论 …"
          className="h-7 flex-1 text-xs"
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              void submit();
            }
          }}
        />
        <Button
          type="button"
          size="sm"
          className="h-7 px-3 text-[11px]"
          onClick={() => void submit()}
          disabled={!draft.trim() || submitting}
        >
          {submitting ? "…" : "发送"}
        </Button>
      </div>
    </div>
  );
}
