import { useEffect, useLayoutEffect, useRef, useState } from "react";
import Markdown from "react-markdown";
import type { Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import { MermaidBlock } from "./MermaidBlock";
import { Plus } from "lucide-react";
import { toast } from "sonner";
import {
  markFileRead,
  type DocType,
  type Judgement,
  type MatterStatus,
  type MentionBlock,
  type Reader,
  type TimelineFileItem,
} from "@/api";
import { Button } from "@/components/ui/button";
import { CopyForAIButton } from "@/components/CopyForAIButton";
import {
  MentionField,
  emptyMention,
  isMentionValid,
} from "@/components/MentionField";
import { cn } from "@/lib/utils";
import {
  getMarkdownStyleClass,
  type MarkdownStyleId,
} from "@/components/markdown/markdownStyles";
import { relativeTime, formatFullDateTime } from "@/lib/time";
import {
  ALLOWED_TYPES_BY_STATUS,
  TYPE_VISUAL,
  shortFile,
} from "./timeline-config";
import { ReadersRow } from "./ReadersRow";
import { RelevanceChip } from "./RelevanceChip";
import { publishListRefresh } from "@/events/listRefresh";

const COLLAPSE_HEIGHT = 208;

const markdownComponents: Components = {
  table({ node: _node, ...props }) {
    return (
      <div className="table-scroll">
        <table {...props} />
      </div>
    );
  },
  code({ className, children, ...rest }) {
    if (className === "language-mermaid") {
      return <MermaidBlock code={String(children).replace(/\n$/, "")} />;
    }
    return (
      <code className={className} {...rest}>
        {children}
      </code>
    );
  },
  pre({ children, ...rest }) {
    const only = Array.isArray(children) ? children[0] : children;
    if (
      typeof only === "object" &&
      only !== null &&
      "type" in only &&
      (only as { type?: unknown }).type === MermaidBlock
    ) {
      return <>{children}</>;
    }
    return <pre {...rest}>{children}</pre>;
  },
};

export function FileCard({
  item,
  index,
  matterId,
  matterStatus,
  activeType,
  onCreate,
  onAddComment,
  onJump,
  registerRef,
  highlighted,
  markdownStyle,
  me,
}: {
  item: TimelineFileItem;
  index: number;
  matterId: string;
  matterStatus: MatterStatus;
  activeType: DocType | null;
  onCreate: (type: DocType, quote: string) => void;
  onAddComment: (body: string, mentions?: string[]) => Promise<void>;
  onJump: (file: string) => void;
  registerRef?: (el: HTMLDivElement | null) => void;
  highlighted?: boolean;
  markdownStyle: MarkdownStyleId;
  me: { open_id: string; name: string; avatar_url: string | null };
}) {
  const cfg = TYPE_VISUAL[item.type];
  const [expanded, setExpanded] = useState(false);
  const [canExpand, setCanExpand] = useState(false);
  const bodyRef = useRef<HTMLDivElement>(null);
  const cardRef = useRef<HTMLElement | null>(null);
  const allowed = ALLOWED_TYPES_BY_STATUS[matterStatus];
  const allowThink = allowed.includes("think");
  const allowAct = allowed.includes("act");
  const allowVerify = allowed.includes("verify");

  // Local mirror of readers for optimistic updates. Reset when the parent's
  // server-side readers change (refetch after SSE / visibility resume).
  const [readers, setReaders] = useState<Reader[]>(item.readers ?? []);
  useEffect(() => {
    setReaders(item.readers ?? []);
  }, [item.readers]);

  // Track whether the card is currently in viewport. Used to decide whether
  // to auto-fire triggerMark when SSE delivers a new mention mid-session —
  // the IntersectionObserver only fires on threshold crossings, so a new
  // unread mention arriving while the card sits visible would otherwise
  // not get marked-read until the user scrolls or navigates away.
  const isVisibleRef = useRef(false);

  useEffect(() => {
    setExpanded(false);
  }, [item.file]);

  const fileBasename = item.file.split("/").pop() ?? item.file;

  // Fire on every "view" — short file scrolled into viewport, or long file
  // expanded. No client-side session dedupe: backend is idempotent
  // (file_reads.mark uses INSERT OR IGNORE; mark_all_read_for_file is a
  // no-op when there are no unread relevance rows). Repeated calls let
  // mid-session new mentions get cleared as soon as the user looks at
  // the file again, which is what users expect.
  const triggerMark = () => {
    if (!me.open_id) return;
    // Optimistic "I've read it" insert. The dedup MUST be inside the
    // functional updater — the closure-captured `readers` value is stale
    // when triggerMark fires from a re-attached observer (second viewport
    // entry, etc.), so a pre-call `readers.some(...)` would happily push
    // me a second time. functional setState with `prev` reads latest state
    // atomically. No catch-rollback: if the API fails, the next detail
    // refetch will replace these readers with the server version.
    setReaders((prev) => {
      if (prev.some((r) => r.open_id === me.open_id)) return prev;
      return [
        ...prev,
        {
          open_id: me.open_id,
          name: me.name || me.open_id,
          avatar_url: me.avatar_url,
          first_read_at: new Date().toISOString(),
        },
      ];
    });
    void markFileRead(matterId, fileBasename)
      .then(() => {
        // Tell Dashboard to silently refetch the matters list so the
        // sidebar's red/gray badges reflect the cleared mention. We do
        // not go through the SSE/resume channel because that would also
        // trigger MatterDetailPane to refetch the full detail, replacing
        // FileCard's optimistic readers state.
        publishListRefresh();
      })
      .catch(() => {
        // No rollback: if the mark API failed, the next detail refetch
        // (SSE-driven, visibility resume, etc.) will replace the local
        // readers with the server-side version, which won't include me
        // until a successful mark lands.
      });
  };

  useLayoutEffect(() => {
    const el = bodyRef.current;
    if (!el) {
      setCanExpand(false);
      return;
    }

    const measure = () => {
      setCanExpand(el.scrollHeight > COLLAPSE_HEIGHT + 1);
    };

    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, [item.body]);

  // Short-form auto-mark: only when the body is fully revealed (no expand
  // affordance). Long-form requires the user to click "展开全文 ↓" — that
  // path is wired on the button onClick below.
  //
  // Visibility is detected by absolute pixel height (>= MIN_VISIBLE_PX),
  // not the original `intersectionRatio >= 0.5`. The ratio approach
  // breaks for tall cards (long body, many comments, big readers row):
  // if the card is taller than the viewport, the maximum ratio is
  // viewport / card and never crosses 0.5, so the observer's callback
  // never qualifies as "visible" and triggerMark never fires.
  // Multi-threshold subscription guarantees callbacks at multiple
  // scroll positions so we don't miss the moment height crosses the cut.
  // Visibility is also mirrored to isVisibleRef so the comment-update
  // effect below can decide whether to fire when SSE delivers a new
  // mention while the card sits statically on screen.
  useEffect(() => {
    if (canExpand) return;
    if (!item.body) return;
    const el = cardRef.current;
    if (!el) return;
    const MIN_VISIBLE_PX = 100;
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          const visible =
            entry.isIntersecting &&
            entry.intersectionRect.height >= MIN_VISIBLE_PX;
          isVisibleRef.current = visible;
          if (visible) {
            triggerMark();
            break;
          }
        }
      },
      { threshold: [0, 0.25, 0.5, 0.75, 1] },
    );
    observer.observe(el);
    return () => observer.disconnect();
    // me.open_id intentionally in deps: on initial mount fetchMe hasn't
    // resolved yet so me.open_id is "", triggerMark short-circuits, and
    // the observer is permanently bound to that stale closure (the card
    // is statically visible after that, never crosses the threshold
    // again). Adding me.open_id forces a re-attach when fetchMe lands —
    // the new observer fires immediately on observe(el) with a closure
    // that sees the populated me, and the mark API actually gets called.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [canExpand, item.body, item.file, me.open_id]);

  // When the parent re-fetches the matter detail (typically because SSE
  // pushed a `matter.updated` event), item.comments swaps in place. If the
  // new comments contain an unread @ to me AND this card is currently in
  // viewport, fire triggerMark — otherwise the IntersectionObserver, which
  // only fires on threshold crossings, would leave the new red dot
  // dangling until the user scrolls or navigates away.
  useEffect(() => {
    if (!isVisibleRef.current) return;
    if (!item.comments.some((c) => c.mention_unread_for_me)) return;
    triggerMark();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [item.comments]);

  return (
    <article
      ref={(el) => {
        cardRef.current = el;
        registerRef?.(el as HTMLDivElement | null);
      }}
      className={cn(
        "min-w-0 scroll-mt-24 overflow-hidden rounded-[var(--r-md)] border border-[var(--line)] border-l-[6px] bg-[var(--surface)] p-4 shadow-[var(--shadow-sm)] sm:p-5",
        cfg.side,
        highlighted && "ring-2 ring-[var(--accent-soft)]",
      )}
    >
      {/* header */}
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="flex min-w-0 flex-wrap items-center gap-2 text-[11px] text-[var(--text-mute)]">
          <span
            className={cn(
              "inline-flex items-center rounded-md px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide ring-1",
              cfg.chip,
            )}
          >
            {cfg.label}
          </span>
          <span>第 {index + 1} 条</span>
          <span>·</span>
          <span>
            作者{" "}
            <span className="font-medium text-[var(--text-soft)]">
              {item.creator}
            </span>
          </span>
          <span>·</span>
          <span title={formatFullDateTime(item.created_at)}>
            {relativeTime(item.created_at)}
          </span>
          <RelevanceChip reason={item.relevance_reason} />
        </div>
        <MentionPopover onSubmit={onAddComment} align="right" />
      </div>
      <div className="mt-1 break-all font-mono text-xs text-[var(--text-soft)]">
        {shortFile(item.file)}
      </div>

      <p className="mt-3 text-[14px] font-medium text-[var(--text)]">
        {item.summary}
      </p>

      {/* quote / refer / status_change chips */}
      {(item.quote ||
        (item.refer && item.refer.length > 0) ||
        item.status_change) && (
        <div className="mt-2 flex flex-wrap items-center gap-1.5">
          {item.quote && (
            <button
              type="button"
              onClick={() => onJump(item.quote as string)}
              className="inline-flex items-center gap-1 rounded-full bg-[var(--surface-alt)] px-2 py-0.5 text-[11px] text-[var(--text-soft)] ring-1 ring-[var(--line)] hover:bg-[var(--accent-bg)]"
              title={item.quote}
            >
              ← quote:{" "}
              <span className="font-mono">{shortFile(item.quote)}</span>
            </button>
          )}
          {item.refer && item.refer.length > 0 && (
            <span
              className="inline-flex items-center gap-1 rounded-full bg-[var(--accent-bg)] px-2 py-0.5 text-[11px] text-[var(--accent)] ring-1 ring-[var(--accent-soft)]"
              title={item.refer.join("\n")}
            >
              ↔ refer: {item.refer.length}
            </span>
          )}
          {item.status_change && (
            <span className="inline-flex items-center gap-1 rounded-full bg-[var(--status-project-bg)] px-2 py-0.5 text-[11px] text-[var(--status-project-fg)] ring-1 ring-[var(--accent-soft)]">
              status: {item.status_change.from} → {item.status_change.to}
            </span>
          )}
        </div>
      )}

      {/* verify: verifications table */}
      {item.type === "verify" &&
        item.verifications &&
        item.verifications.length > 0 && (
          <div className="mt-3 overflow-hidden rounded-[var(--r-sm)] border border-[var(--accent-soft)]">
            <table className="w-full text-xs">
              <thead className="bg-[var(--accent-bg)] text-[11px] uppercase text-[var(--accent)]">
                <tr>
                  <th className="px-3 py-1.5 text-left">target (act)</th>
                  <th className="px-3 py-1.5 text-left">judgement</th>
                  <th className="px-3 py-1.5 text-left">comment</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[var(--line-soft)] bg-[var(--surface)]">
                {item.verifications.map((v, i) => (
                  <tr key={i}>
                    <td className="px-3 py-1.5">
                      <button
                        type="button"
                        onClick={() => onJump(v.target)}
                        className="font-mono text-[11px] text-[var(--text-soft)] hover:underline"
                      >
                        {shortFile(v.target)}
                      </button>
                    </td>
                    <td className="px-3 py-1.5">
                      <JudgementChip judgement={v.judgement} />
                    </td>
                    <td className="px-3 py-1.5 text-[var(--text-soft)]">
                      {v.comment}
                    </td>
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
              ? "bg-[var(--status-concluded-bg)] text-[var(--status-concluded-fg)] ring-1 ring-[var(--line)]"
              : "bg-[var(--status-archived-bg)] text-[var(--status-archived-fg)] ring-1 ring-[var(--line)]",
          )}
        >
          Matter 结果：
          {item.outcome === "finished" ? "已完成 finished" : "已取消 cancelled"}
        </div>
      )}

      {/* body */}
      {item.body && (
        <>
          <div
            ref={bodyRef}
            style={
              expanded || !canExpand
                ? undefined
                : { maxHeight: COLLAPSE_HEIGHT, overflow: "hidden" }
            }
            className={cn(
              "prose-pivot mt-3 min-w-0 max-w-none overflow-hidden text-[var(--text-soft)]",
              getMarkdownStyleClass(markdownStyle),
            )}
          >
            <Markdown
              remarkPlugins={[remarkGfm]}
              components={markdownComponents}
            >
              {item.body}
            </Markdown>
          </div>
          {canExpand && (
            <button
              type="button"
              onClick={() => {
                if (!expanded) triggerMark();
                setExpanded((v) => !v);
              }}
              className="mt-1 text-xs text-[var(--accent)] hover:underline"
            >
              {expanded ? "收起 ↑" : "展开全文 ↓"}
            </button>
          )}
        </>
      )}

      {/* comments (read-only; "添加评论" was removed — use the @ 提及 button at the top to leave a note instead) */}
      <CommentsBlock item={item} />

      <ReadersRow readers={readers} />

      {/* 三入口 */}
      <div className="mt-3 flex flex-wrap items-center gap-1.5 border-t border-[var(--line-soft)] pt-3">
        <CardAddButton
          label="think"
          disabled={!allowThink}
          active={activeType === "think"}
          onClick={() => onCreate("think", item.file)}
        />
        <CardAddButton
          label="act"
          disabled={!allowAct}
          active={activeType === "act"}
          onClick={() => onCreate("act", item.file)}
        />
        <CardAddButton
          label="verify"
          disabled={!allowVerify}
          active={activeType === "verify"}
          onClick={() => onCreate("verify", item.file)}
        />
        <CopyForAIButton matterId={matterId} filePath={item.file} />
        <div className="ml-auto text-[10px] text-[var(--text-fade)]">
          点按钮 · 新文件 quote 自动写入{" "}
          <span className="font-mono">{shortFile(item.file)}</span>
        </div>
      </div>
    </article>
  );
}

// 对应 master ThreadDetailPane.PostMentionPopover 的形态:点开按钮弹一个 popover,
// 选人 + 留一句话,提交后调 onSubmit(body, open_ids)。本质走的是
// appendMatterComment 通道——matter 的"提及"实现就是给文件追加一条带 mentions
// 的评论。
function MentionPopover({
  onSubmit,
  align = "left",
}: {
  onSubmit: (body: string, mentions: string[]) => Promise<void>;
  align?: "left" | "right";
}) {
  const [open, setOpen] = useState(false);
  const [value, setValue] = useState<MentionBlock>(emptyMention());
  const resolvedNames = useRef<Record<string, string>>({});
  const [submitting, setSubmitting] = useState(false);
  const popoverRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (
        popoverRef.current &&
        !popoverRef.current.contains(e.target as Node)
      ) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  const submit = async () => {
    if (value.open_ids.length === 0) {
      toast.error("至少选一个人");
      return;
    }
    if (!isMentionValid(value)) {
      toast.error("圈人后必须填一句话");
      return;
    }
    setSubmitting(true);
    try {
      await onSubmit(value.comments.trim(), value.open_ids);
      setOpen(false);
      setValue(emptyMention());
      toast.success("已发送提及");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="relative" ref={popoverRef}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        title="圈人留言（追加为本文件的一条带 mention 的评论）"
        className="inline-flex items-center rounded-[var(--r-sm)] border border-[var(--accent-soft)] bg-[var(--surface)] px-2 py-1 text-[11px] font-semibold text-[var(--accent)] hover:bg-[var(--accent-bg)]"
      >
        @ 提及
      </button>
      {open && (
        <div
          className={cn(
            "absolute top-full z-50 mt-2 max-h-[calc(100vh-8rem)] w-[calc(100vw-2rem)] max-w-[22rem] overflow-y-auto rounded-[var(--r-md)] border border-[var(--line)] bg-[var(--surface)] p-3 shadow-[var(--shadow-lg)] sm:max-h-none sm:w-[22rem] sm:overflow-visible",
            align === "right" ? "right-0" : "left-0",
          )}
        >
          <p className="mb-2 text-[10.5px] font-bold uppercase tracking-wider text-[var(--text-mute)]">
            提及某人
          </p>
          <MentionField
            value={value}
            onChange={setValue}
            resolvedNames={resolvedNames.current}
          />
          <div className="mt-3 flex justify-end gap-2">
            <Button
              type="button"
              size="sm"
              variant="outline"
              onClick={() => {
                setOpen(false);
                setValue(emptyMention());
              }}
              disabled={submitting}
            >
              取消
            </Button>
            <Button
              type="button"
              size="sm"
              onClick={() => void submit()}
              disabled={submitting}
              className="bg-[var(--accent)] text-[var(--accent-ink)] hover:opacity-90"
            >
              {submitting ? "发送中…" : "发送"}
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}

function CardAddButton({
  label,
  disabled,
  active,
  onClick,
}: {
  label: string;
  disabled: boolean;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      title={
        disabled ? "当前 matter 状态不允许新增此类型" : `基于此新增 ${label}`
      }
      className={cn(
        "inline-flex items-center gap-1 rounded-md border px-2 py-1 text-[11px] font-medium transition-colors",
        disabled
          ? "cursor-not-allowed border-[var(--line)] text-[var(--text-fade)]"
          : active
            ? "border-[var(--accent-soft)] bg-[var(--accent-bg)] text-[var(--accent)]"
            : "border-[var(--line-strong)] text-[var(--text-soft)] hover:border-[var(--accent-soft)] hover:bg-[var(--accent-bg)] hover:text-[var(--accent)]",
      )}
    >
      <Plus className="h-3 w-3" />
      {label}
    </button>
  );
}

function JudgementChip({ judgement }: { judgement: Judgement }) {
  const MAP: Record<Judgement, string> = {
    passed:
      "bg-[var(--status-concluded-bg)] text-[var(--status-concluded-fg)] ring-[var(--line)]",
    failed:
      "bg-[color-mix(in_srgb,var(--danger-500)_12%,var(--surface))] text-[var(--danger-600)] ring-[color-mix(in_srgb,var(--danger-500)_24%,var(--line))]",
    cancelled:
      "bg-[var(--status-archived-bg)] text-[var(--status-archived-fg)] ring-[var(--line)]",
  };
  return (
    <span
      className={cn(
        "inline-flex rounded-full px-2 py-0.5 text-[11px] font-medium ring-1",
        MAP[judgement],
      )}
    >
      {judgement}
    </span>
  );
}

function CommentsBlock({ item }: { item: TimelineFileItem }) {
  if (item.comments.length === 0) return null;

  return (
    <div className="mt-3">
      <ul className="space-y-2">
        {item.comments.map((c, i) => {
          const author =
            ((c.author_display || c.author) ?? "").trim() || "未知用户";
          const mentionNames = c.mentions_display ?? c.mentions ?? [];
          const body = c.body?.trim();
          return (
            <li
              key={i}
              className="rounded-[var(--r-sm)] border border-[var(--line)] bg-[var(--surface-alt)] px-3 py-2 text-[12.5px] leading-6 text-[var(--text-soft)]"
            >
              <span className="inline-flex items-center rounded-full border border-[var(--line)] bg-[var(--surface)] px-2 py-0.5 text-[11px] font-medium text-[var(--text-soft)]">
                评论{i + 1}
              </span>
              <span
                className="ml-1 text-[var(--text-fade)]"
                title={formatFullDateTime(c.created_at)}
              >
                · {relativeTime(c.created_at)}
              </span>
              <span className="ml-2 font-semibold text-[var(--text)]">
                {author}
              </span>
              {mentionNames.map((name, mi) => (
                <span key={mi} className="ml-1 text-[var(--accent)]">
                  @{name}
                </span>
              ))}
              <span className="ml-1 text-[var(--text-mute)]">说:</span>
              {body ? (
                <span className="ml-0.5">{body}</span>
              ) : (
                <span className="ml-0.5 text-[var(--text-fade)]">
                  未填写评论内容
                </span>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
