import { Ban, RotateCcw, UserRound } from "lucide-react";
import type { TimelineInvalidationEventItem } from "@/api";
import { relativeTime } from "@/lib/time";
import { shortFile } from "./timeline-config";

const REASON_LABEL: Record<string, string> = {
  misposted: "误发",
  inaccurate: "不准确",
  restored: "恢复",
};

export function InvalidationEventRow({
  item,
}: {
  item: TimelineInvalidationEventItem;
}) {
  const isRestore = item.reason === "restored";
  const verb = isRestore ? "恢复了" : "撤回了";
  const Icon = isRestore ? RotateCcw : Ban;
  const reasonText = isRestore ? null : REASON_LABEL[item.reason] ?? item.reason;

  return (
    <article className="rounded-[var(--r-md)] border border-[var(--line)] bg-[var(--surface)] p-4 shadow-[var(--shadow-sm)]">
      <div className="flex flex-wrap items-center gap-2 text-sm text-[var(--text)]">
        {item.creator_avatar_url ? (
          <img
            src={item.creator_avatar_url}
            alt=""
            className="h-6 w-6 rounded-full object-cover"
          />
        ) : (
          <span className="flex h-6 w-6 items-center justify-center rounded-full bg-[var(--surface-alt)] text-[var(--text-mute)]">
            <UserRound className="h-3.5 w-3.5" />
          </span>
        )}
        <strong>{item.creator_display ?? item.creator}</strong>
        <Icon
          className={
            isRestore
              ? "h-4 w-4 text-[var(--ok-500)]"
              : "h-4 w-4 text-[var(--warn-500)]"
          }
        />
        <span className="text-[var(--text-mute)]">{verb}</span>
        <span className="font-mono text-xs text-[var(--text-soft)]">
          {shortFile(item.quote)}
        </span>
        {reasonText && (
          <span className="inline-flex items-center rounded-full bg-[color-mix(in_srgb,var(--warn-500)_12%,var(--surface))] px-2 py-0.5 text-[11px] font-medium text-[var(--warn-700)] ring-1 ring-[color-mix(in_srgb,var(--warn-500)_24%,var(--line))]">
            {reasonText}
          </span>
        )}
        <span className="ml-auto text-xs text-[var(--text-fade)]">
          {relativeTime(item.created_at)}
        </span>
      </div>
      {item.summary && (
        <div className="mt-2 text-xs leading-5 text-[var(--text-mute)]">
          原因：{item.summary}
        </div>
      )}
    </article>
  );
}
