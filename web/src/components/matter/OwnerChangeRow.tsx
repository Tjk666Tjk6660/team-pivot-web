import { useEffect, useRef } from "react";
import { ArrowRight, UserRound } from "lucide-react";
import { markMatterEventsRead, type TimelineOwnerChangeItem } from "@/api";
import { publishListRefresh } from "@/events/listRefresh";
import { relativeTime } from "@/lib/time";

export function OwnerChangeRow({
  item,
  matterId,
}: {
  item: TimelineOwnerChangeItem;
  matterId: string;
}) {
  // Matter-level relevance rows (filename='') don't get cleared by FileCard's
  // read-mark side effect when no file becomes visible. Mark them as read
  // when this row scrolls into view so the red badge actually clears.
  // Backend dedupes (idempotent UPDATE), so no client-side guard needed.
  const ref = useRef<HTMLElement | null>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (
            entry.isIntersecting &&
            entry.intersectionRect.height >= 60
          ) {
            void markMatterEventsRead(matterId)
              .then((r) => {
                if (r.cleared > 0) publishListRefresh();
              })
              .catch(() => {});
            observer.disconnect();
            break;
          }
        }
      },
      { threshold: [0, 0.25, 0.5, 0.75, 1] },
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, [matterId]);

  return (
    <article
      ref={ref}
      className="rounded-[var(--r-md)] border border-[var(--line)] bg-[var(--surface)] p-4 shadow-[var(--shadow-sm)]"
    >
      <div className="flex flex-wrap items-center gap-2 text-sm text-[var(--text)]">
        {item.actor_avatar_url ? (
          <img
            src={item.actor_avatar_url}
            alt=""
            className="h-6 w-6 rounded-full object-cover"
          />
        ) : (
          <span className="flex h-6 w-6 items-center justify-center rounded-full bg-[var(--surface-alt)] text-[var(--text-mute)]">
            <UserRound className="h-3.5 w-3.5" />
          </span>
        )}
        <strong>{item.actor_display ?? item.actor}</strong>
        <span className="text-[var(--text-mute)]">将负责人从</span>
        <strong>{item.from_owner_display ?? "未分配"}</strong>
        <ArrowRight className="h-4 w-4 text-[var(--text-mute)]" />
        <strong>{item.to_owner_display ?? item.to_owner}</strong>
        <span className="ml-auto text-xs text-[var(--text-fade)]">
          {relativeTime(item.created_at)}
        </span>
      </div>
      <div className="mt-2 text-xs leading-5 text-[var(--text-mute)]">
        原因：{item.reason}
      </div>
    </article>
  );
}
