import { NavLink } from "react-router-dom";
import { Trash2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { StatusBadge } from "@/components/StatusBadge";
import { relativeTime } from "@/lib/time";
import type { Draft, ThreadMeta } from "@/api";

export function ThreadListPane({
  drafts,
  threads,
  onRemoveDraft,
}: {
  drafts: Draft[] | null;
  threads: ThreadMeta[] | null;
  onRemoveDraft: (id: string) => void;
}) {
  return (
    <div>

      {drafts && drafts.length > 0 && (
        <Section title="草稿" count={drafts.length}>
          {drafts.map((d) => (
            <div
              key={d.id}
              className="group flex items-start gap-2 border-b px-4 py-2.5 hover:bg-accent/40"
            >
              <NavLink
                to={
                  d.type === "proposal"
                    ? `/new?draft=${d.id}`
                    : d.thread_key
                      ? `/t/${d.thread_key}`
                      : "#"
                }
                className="flex-1 min-w-0"
              >
                <div className="truncate text-sm font-medium">
                  {d.type === "proposal"
                    ? (d.title?.trim() || "(untitled)")
                    : `Reply: ${d.thread_key ?? ""}`}
                </div>
                <div className="mt-0.5 truncate text-xs text-muted-foreground">
                  {d.type} · {relativeTime(new Date(d.updated_at * 1000).toISOString())}
                </div>
              </NavLink>
              <Button
                variant="ghost"
                size="icon"
                className="h-7 w-7 opacity-0 group-hover:opacity-100"
                onClick={() => onRemoveDraft(d.id)}
                title="删除草稿"
              >
                <Trash2 className="h-3.5 w-3.5 text-destructive" />
              </Button>
            </div>
          ))}
        </Section>
      )}

      <Section title="讨论" count={threads?.length ?? 0}>
        {threads === null && (
          <div className="px-4 py-3 text-sm text-muted-foreground">Loading…</div>
        )}
        {threads !== null && threads.length === 0 && (
          <div className="px-4 py-3 text-sm text-muted-foreground">
            No threads yet.
          </div>
        )}
        {threads !== null && threads.length > 0 &&
          threads.map((t) => (
            <ThreadRow
              key={`${t.category}/${t.slug}`}
              to={`/t/${encodeURIComponent(t.category)}/${encodeURIComponent(t.slug)}`}
              title={t.title}
              status={t.status}
              meta={`${t.category} · ${t.author_display ?? t.author ?? "unknown"} · ${t.post_count} posts${t.last_updated ? ` · ${relativeTime(t.last_updated)}` : ""}`}
              unread={t.unread_count > 0 ? t.unread_count : undefined}
            />
          ))}
      </Section>
    </div>
  );
}

function Section({
  title, count, children,
}: { title: string; count: number; children: React.ReactNode }) {
  return (
    <section>
      <div className="sticky top-0 z-10 flex items-center gap-2 border-b bg-muted/40 px-4 py-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        {title}
        <span className="text-muted-foreground/70">{count}</span>
      </div>
      {children}
    </section>
  );
}

function ThreadRow({
  to, title, status, meta, unread,
}: {
  to: string;
  title: string;
  status: string | null;
  meta: string;
  unread?: number;
}) {
  return (
    <NavLink
      to={to}
      className={({ isActive }) =>
        cn(
          "block border-b px-4 py-2.5 hover:bg-accent/40",
          isActive && "bg-accent/60",
        )
      }
    >
      <div className="flex items-center gap-2">
        {unread !== undefined && (
          <Badge variant="red" className="shrink-0">{unread}</Badge>
        )}
        <span className="truncate text-sm font-medium">{title}</span>
        <span className="ml-auto shrink-0">
          <StatusBadge status={status} />
        </span>
      </div>
      <div className="mt-0.5 truncate text-xs text-muted-foreground">{meta}</div>
    </NavLink>
  );
}
