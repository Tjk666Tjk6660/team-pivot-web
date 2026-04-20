import { useEffect, useMemo, useState } from "react";
import { NavLink, useLocation } from "react-router-dom";
import { ChevronDown, ChevronRight, FileText, FolderTree, Star, Trash2 } from "lucide-react";
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
  const location = useLocation();
  const activeCategory = useMemo(() => {
    const match = location.pathname.match(/^\/t\/([^/]+)\//);
    return match ? decodeURIComponent(match[1]) : null;
  }, [location.pathname]);

  const grouped = useMemo(() => groupThreadsByCategory(threads), [threads]);
  const favorites = useMemo(
    () => [...(threads ?? [])].filter((thread) => thread.favorite)
      .sort((a, b) => (b.last_updated || "").localeCompare(a.last_updated || "")),
    [threads],
  );
  const [openCategories, setOpenCategories] = useState<Record<string, boolean>>({});
  const [draftsOpen, setDraftsOpen] = useState(true);
  const [favoritesOpen, setFavoritesOpen] = useState(true);
  const [threadsOpen, setThreadsOpen] = useState(true);

  useEffect(() => {
    if (!grouped.length) return;
    setOpenCategories((current) => {
      const next = { ...current };
      let changed = false;
      for (const group of grouped) {
        if (!(group.category in next)) {
          next[group.category] = activeCategory === group.category;
          changed = true;
        }
      }
      if (activeCategory && !next[activeCategory]) {
        next[activeCategory] = true;
        changed = true;
      }
      return changed ? next : current;
    });
  }, [grouped, activeCategory]);

  const toggleCategory = (category: string) => {
    setOpenCategories((current) => ({ ...current, [category]: !current[category] }));
  };

  return (
    <div>

      {threads !== null && favorites.length > 0 && (
        <Section
          title="收藏"
          count={favorites.length}
          open={favoritesOpen}
          onToggle={() => setFavoritesOpen((v) => !v)}
          icon={<Star className="h-3.5 w-3.5 shrink-0 text-amber-500" />}
        >
          {favoritesOpen && favorites.map((t) => (
            <ThreadRow
              key={`favorite-${t.category}/${t.slug}`}
              to={`/t/${encodeURIComponent(t.category)}/${encodeURIComponent(t.slug)}`}
              title={t.title}
              status={t.status}
              meta={`${t.category} · ${t.author_display ?? t.author ?? "unknown"} · ${t.post_count} posts${t.last_updated ? ` · ${relativeTime(t.last_updated)}` : ""}`}
              unread={t.unread_count > 0 ? t.unread_count : undefined}
            />
          ))}
        </Section>
      )}

      {drafts && drafts.length > 0 && (
        <Section
          title="草稿"
          count={drafts.length}
          open={draftsOpen}
          onToggle={() => setDraftsOpen((v) => !v)}
          icon={<FileText className="h-3.5 w-3.5 shrink-0 text-sky-600" />}
        >
          {draftsOpen && drafts.map((d) => (
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

      <Section
        title="讨论"
        count={threads?.length ?? 0}
        open={threadsOpen}
        onToggle={() => setThreadsOpen((v) => !v)}
        icon={<FolderTree className="h-3.5 w-3.5 shrink-0" />}
      >
        {threads === null && (
          <div className="px-4 py-3 text-sm text-muted-foreground">Loading…</div>
        )}
        {threadsOpen && threads !== null && threads.length === 0 && (
          <div className="px-4 py-3 text-sm text-muted-foreground">
            No threads yet.
          </div>
        )}
        {threadsOpen && threads !== null && grouped.length > 0 &&
          grouped.map((group) => {
            const open = !!openCategories[group.category];
            return (
              <div key={group.category} className="border-b">
                <button
                  type="button"
                  onClick={() => toggleCategory(group.category)}
                  className="flex w-full items-center gap-2 bg-muted/40 px-4 py-3 text-left hover:bg-muted/70"
                >
                  {open ? (
                    <ChevronDown className="h-4 w-4 shrink-0 text-muted-foreground" />
                  ) : (
                    <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground" />
                  )}
                  <FolderTree className="h-4 w-4 shrink-0 text-muted-foreground" />
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="truncate text-sm font-medium">{group.category}</span>
                      <span className="text-xs text-muted-foreground">{group.threads.length}</span>
                    </div>
                    <div className="mt-0.5 truncate text-xs text-muted-foreground">
                      {group.last_updated
                        ? `最近活动 ${relativeTime(group.last_updated)}`
                        : "暂无活动时间"}
                    </div>
                  </div>
                  {group.unread > 0 && (
                    <Badge variant="red" className="shrink-0">{group.unread}</Badge>
                  )}
                </button>
                {open && (
                  <div className="border-t bg-background">
                    {group.threads.map((t) => (
                      <ThreadRow
                        key={`${t.category}/${t.slug}`}
                        to={`/t/${encodeURIComponent(t.category)}/${encodeURIComponent(t.slug)}`}
                        title={t.title}
                        status={t.status}
                        meta={`${t.author_display ?? t.author ?? "unknown"} · ${t.post_count} posts${t.last_updated ? ` · ${relativeTime(t.last_updated)}` : ""}`}
                        unread={t.unread_count > 0 ? t.unread_count : undefined}
                        nested
                      />
                    ))}
                  </div>
                )}
              </div>
            );
          })}
      </Section>
    </div>
  );
}

function Section({
  title, count, open, onToggle, icon, children,
}: {
  title: string;
  count: number;
  open: boolean;
  onToggle: () => void;
  icon?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section>
      <button
        type="button"
        onClick={onToggle}
        className="sticky top-0 z-10 flex w-full items-center gap-2 border-b bg-muted/60 px-4 py-2 text-left text-xs font-semibold uppercase tracking-wide text-muted-foreground hover:bg-muted"
      >
        {open ? (
          <ChevronDown className="h-3.5 w-3.5 shrink-0" />
        ) : (
          <ChevronRight className="h-3.5 w-3.5 shrink-0" />
        )}
        {icon}
        {title}
        <span className="text-muted-foreground/70">{count}</span>
      </button>
      {children}
    </section>
  );
}

function ThreadRow({
  to, title, status, meta, unread, nested = false,
}: {
  to: string;
  title: string;
  status: string | null;
  meta: string;
  unread?: number;
  nested?: boolean;
}) {
  return (
    <NavLink
      to={to}
      className={({ isActive }) =>
        cn(
          "block border-b px-4 py-2.5 hover:bg-accent/40",
          nested && "border-b-0 border-l-2 border-l-muted/50 px-5 py-3 pl-9 hover:bg-accent/25",
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

type CategoryGroup = {
  category: string;
  threads: ThreadMeta[];
  unread: number;
  last_updated: string | null;
};

function groupThreadsByCategory(threads: ThreadMeta[] | null): CategoryGroup[] {
  if (!threads || threads.length === 0) return [];

  const grouped = new Map<string, CategoryGroup>();
  for (const thread of threads) {
    const existing = grouped.get(thread.category);
    if (existing) {
      existing.threads.push(thread);
      existing.unread += thread.unread_count;
      if ((thread.last_updated || "") > (existing.last_updated || "")) {
        existing.last_updated = thread.last_updated;
      }
      continue;
    }
    grouped.set(thread.category, {
      category: thread.category,
      threads: [thread],
      unread: thread.unread_count,
      last_updated: thread.last_updated,
    });
  }

  return Array.from(grouped.values())
    .map((group) => ({
      ...group,
      threads: [...group.threads].sort((a, b) => (b.last_updated || "").localeCompare(a.last_updated || "")),
    }))
    .sort((a, b) => (b.last_updated || "").localeCompare(a.last_updated || ""));
}
