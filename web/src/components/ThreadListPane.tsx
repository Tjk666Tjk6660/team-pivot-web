import { useEffect, useMemo, useRef, useState } from "react";
import { NavLink, useLocation } from "react-router-dom";
import { ChevronDown, ChevronRight, FileText, Star, Trash2 } from "lucide-react";
import { cn } from "@/lib/utils";
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
    () => [...(threads ?? [])]
      .filter((thread) => thread.favorite)
      .sort((a, b) => (b.last_updated || "").localeCompare(a.last_updated || "")),
    [threads],
  );
  const [openCategories, setOpenCategories] = useState<Record<string, boolean>>({});
  const [favoritesOpen, setFavoritesOpen] = useState(true);
  const [draftsOpen, setDraftsOpen] = useState(true);
  const [threadsOpen, setThreadsOpen] = useState(true);

  const favoritesRef = useRef<HTMLElement | null>(null);
  const draftsRef = useRef<HTMLElement | null>(null);
  const threadsRef = useRef<HTMLElement | null>(null);

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
    <div className="flex h-full flex-col px-3 py-4" style={{ background: "var(--bg)" }}>
      <div className="min-h-0 flex-1 overflow-y-auto pr-0.5">
        {threads !== null && favorites.length > 0 && (
          <Section
            sectionRef={favoritesRef}
            title="我收藏的"
            count={favorites.length}
            open={favoritesOpen}
            onToggle={() => setFavoritesOpen((v) => !v)}
            icon={
              <Star
                className="h-3 w-3 shrink-0"
                style={{ color: "var(--accent)" }}
              />
            }
          >
            {favoritesOpen && favorites.map((t) => (
              <ThreadRow
                key={`favorite-${t.category}/${t.slug}`}
                to={`/t/${encodeURIComponent(t.category)}/${encodeURIComponent(t.slug)}`}
                title={t.title}
                status={t.status}
                meta={`${t.category} · ${t.author_display ?? t.author ?? "unknown"} · ${t.post_count} 帖${t.last_updated ? ` · ${relativeTime(t.last_updated)}` : ""}`}
                unread={t.unread_count > 0 ? t.unread_count : undefined}
              />
            ))}
          </Section>
        )}

        {drafts && drafts.length > 0 && (
          <Section
            sectionRef={draftsRef}
            title="草稿"
            count={drafts.length}
            open={draftsOpen}
            onToggle={() => setDraftsOpen((v) => !v)}
            icon={
              <FileText
                className="h-3 w-3 shrink-0"
                style={{ color: "var(--text-mute)" }}
              />
            }
          >
            {draftsOpen && drafts.map((d) => {
              const isProposal = d.type === "proposal";
              const draftLabel = isProposal ? "NEW" : "REPLY";
              return (
                <div
                  key={d.id}
                  className="group mx-1 mb-0.5 flex items-start gap-2 rounded-md px-2 py-1.5 transition-colors hover:bg-[var(--surface-alt)]"
                >
                  <NavLink
                    to={
                      isProposal
                        ? `/new?draft=${d.id}`
                        : d.thread_key
                          ? `/t/${d.thread_key}`
                          : "#"
                    }
                    className="min-w-0 flex-1"
                  >
                    <div className="flex items-center gap-1.5">
                      <span
                        className="rounded-[3px] px-1 py-[1px] text-[9.5px] font-bold tracking-wider font-meta"
                        style={{
                          background: isProposal ? "var(--status-discussing-bg)" : "var(--status-project-bg)",
                          color: isProposal ? "var(--status-discussing-fg)" : "var(--status-project-fg)",
                        }}
                      >
                        {draftLabel}
                      </span>
                      <span
                        className="ml-auto text-[10.5px] font-mono"
                        style={{ color: "var(--text-mute)" }}
                      >
                        {relativeTime(new Date(d.updated_at * 1000).toISOString())}
                      </span>
                    </div>
                    <div
                      className="mt-1 truncate text-[13px] font-semibold leading-snug font-serif-body"
                      style={{ color: "var(--text)" }}
                    >
                      {isProposal
                        ? (d.title?.trim() || "(未命名)")
                        : `回复：${d.thread_key ?? ""}`}
                    </div>
                  </NavLink>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-7 w-7 opacity-0 transition-opacity group-hover:opacity-100"
                    onClick={() => onRemoveDraft(d.id)}
                    title="删除草稿"
                  >
                    <Trash2 className="h-3 w-3" style={{ color: "var(--danger-500)" }} />
                  </Button>
                </div>
              );
            })}
          </Section>
        )}

        <Section
          sectionRef={threadsRef}
          title="内容空间"
          count={threads?.length ?? 0}
          open={threadsOpen}
          onToggle={() => setThreadsOpen((v) => !v)}
        >
          {threads === null && (
            <div className="px-3 py-3 text-[12px]" style={{ color: "var(--text-mute)" }}>
              加载中…
            </div>
          )}
          {threadsOpen && threads !== null && threads.length === 0 && (
            <div className="px-3 py-3 text-[12px]" style={{ color: "var(--text-mute)" }}>
              还没有讨论。
            </div>
          )}
          {threadsOpen && threads !== null && grouped.length > 0 &&
            grouped.map((group) => {
              const open = !!openCategories[group.category];
              const swatch = categorySwatch(group.category);
              return (
                <div key={group.category} className="mx-1 mb-1">
                  <button
                    type="button"
                    onClick={() => toggleCategory(group.category)}
                    className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left transition-colors hover:bg-[var(--surface-alt)]"
                  >
                    {open ? (
                      <ChevronDown
                        className="h-3 w-3 shrink-0"
                        style={{ color: "var(--text-mute)" }}
                      />
                    ) : (
                      <ChevronRight
                        className="h-3 w-3 shrink-0"
                        style={{ color: "var(--text-mute)" }}
                      />
                    )}
                    <span
                      aria-hidden
                      className="h-2 w-2 shrink-0 rounded-[2px]"
                      style={{ background: swatch }}
                    />
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <span
                          className="truncate text-[13px] font-semibold"
                          style={{ color: "var(--text)" }}
                        >
                          {group.category}
                        </span>
                      </div>
                      {group.last_updated && (
                        <div
                          className="mt-0.5 truncate text-[10.5px] font-meta"
                          style={{ color: "var(--text-mute)" }}
                        >
                          最近活动 {relativeTime(group.last_updated)}
                        </div>
                      )}
                    </div>
                    <span
                      className="text-[11px] font-mono"
                      style={{ color: "var(--text-mute)" }}
                    >
                      {group.threads.length}
                    </span>
                    {group.unread > 0 && (
                      <span
                        className="ml-1 rounded-full px-1.5 py-[1px] text-[10px] font-bold font-meta"
                        style={{
                          background: "var(--accent)",
                          color: "var(--accent-ink)",
                        }}
                      >
                        {group.unread}
                      </span>
                    )}
                  </button>
                  {open && (
                    <div
                      className="mt-1 ml-[14px] pl-3"
                      style={{ borderLeft: "1px solid var(--line-soft)" }}
                    >
                      {group.threads.map((t) => (
                        <ThreadRow
                          key={`${t.category}/${t.slug}`}
                          to={`/t/${encodeURIComponent(t.category)}/${encodeURIComponent(t.slug)}`}
                          title={t.title}
                          status={t.status}
                          meta={`${t.author_display ?? t.author ?? "unknown"} · ${t.post_count} 帖${t.last_updated ? ` · ${relativeTime(t.last_updated)}` : ""}`}
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
    </div>
  );
}

function Section({
  title,
  count,
  open,
  onToggle,
  icon,
  children,
  sectionRef,
}: {
  title: string;
  count: number;
  open: boolean;
  onToggle: () => void;
  icon?: React.ReactNode;
  children: React.ReactNode;
  sectionRef?: React.Ref<HTMLElement>;
}) {
  return (
    <section className="mb-5 last:mb-0" ref={sectionRef}>
      <button
        type="button"
        onClick={onToggle}
        className="mx-1 mt-1 mb-2 flex w-[calc(100%-0.5rem)] items-center gap-2 px-2 py-1 text-left text-[10px] font-bold uppercase tracking-[0.14em] font-meta"
        style={{ color: "var(--text-mute)" }}
      >
        {open ? (
          <ChevronDown className="h-3 w-3 shrink-0" />
        ) : (
          <ChevronRight className="h-3 w-3 shrink-0" />
        )}
        {icon}
        <span>{title}</span>
        <span
          className="ml-auto text-[10.5px] font-mono"
          style={{ color: "var(--text-fade)" }}
        >
          {count}
        </span>
      </button>
      {children}
    </section>
  );
}

function ThreadRow({
  to,
  title,
  status,
  meta,
  unread,
  nested = false,
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
          "mx-1 mb-0.5 block rounded-md px-3 py-2 transition-colors",
          nested && "mx-0 px-2.5 py-2",
          isActive
            ? "bg-[var(--accent-bg)]"
            : "hover:bg-[var(--surface-alt)]",
        )
      }
      style={({ isActive }) =>
        isActive
          ? { borderLeft: "2px solid var(--accent)" }
          : { borderLeft: "2px solid transparent" }
      }
    >
      {({ isActive }) => (
        <>
          <div className="flex items-center gap-2">
            {unread !== undefined && (
              <span
                className="shrink-0 rounded-full px-1.5 py-[1px] text-[10px] font-bold font-meta"
                style={{
                  background: "var(--accent)",
                  color: "var(--accent-ink)",
                }}
              >
                {unread}
              </span>
            )}
            <span
              className="truncate text-[13.5px] font-semibold font-serif-body leading-snug"
              style={{ color: isActive ? "var(--accent)" : "var(--text)" }}
            >
              {title}
            </span>
            <span className="ml-auto shrink-0">
              <StatusBadge status={status} size="sm" />
            </span>
          </div>
          <div
            className="mt-1 truncate text-[10.5px] font-meta leading-tight"
            style={{ color: "var(--text-mute)" }}
          >
            {meta}
          </div>
        </>
      )}
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

const CATEGORY_PALETTE = [
  "#5a3a1a", "#2854d4", "#1f7a50", "#a36a0e",
  "#5238b8", "#2e3340", "#9e2f2f", "#0e7c66",
];

function categorySwatch(category: string): string {
  let hash = 0;
  for (let i = 0; i < category.length; i++) {
    hash = (hash * 31 + category.charCodeAt(i)) >>> 0;
  }
  return CATEGORY_PALETTE[hash % CATEGORY_PALETTE.length];
}
