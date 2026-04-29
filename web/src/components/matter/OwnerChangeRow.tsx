import { ArrowRight, UserRound } from "lucide-react";
import type { TimelineOwnerChangeItem } from "@/api";
import { relativeTime } from "@/lib/time";

export function OwnerChangeRow({ item }: { item: TimelineOwnerChangeItem }) {
  return (
    <article className="rounded-[var(--r-md)] border border-[var(--line)] bg-[var(--surface)] p-4 shadow-[var(--shadow-sm)]">
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
