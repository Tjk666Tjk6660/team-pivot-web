import { useEffect, useMemo, useRef, useState } from "react";
import { NavLink, useLocation } from "react-router-dom";
import {
  ChevronDown,
  ChevronRight,
  FileText,
  FolderTree,
  Star,
  Trash2,
  UserRound,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { StatusBadge } from "@/components/StatusBadge";
import { relativeTime } from "@/lib/time";
import type { Draft, MatterSummary } from "@/api";

const UNCATEGORIZED = "未分类";

export function ThreadListPane({
  drafts,
  matters,
  onRemoveDraft,
}: {
  drafts: Draft[] | null;
  matters: MatterSummary[] | null;
  onRemoveDraft: (id: string) => void;
}) {
  const location = useLocation();
  const activeMatterId = useMemo(() => {
    const match = location.pathname.match(/^\/m\/([^/]+)/);
    return match ? decodeURIComponent(match[1]) : null;
  }, [location.pathname]);

  const favorites = useMemo(() => {
    if (!matters) return [];
    return matters
      .filter((m) => m.favorite)
      .sort((a, b) => (b.updated_at || "").localeCompare(a.updated_at || ""));
  }, [matters]);

  const grouped = useMemo(() => groupByCategory(matters), [matters]);
  const activeCategory = useMemo(() => {
    if (!activeMatterId || !matters) return null;
    const m = matters.find((x) => x.id === activeMatterId);
    return m ? (m.category ?? UNCATEGORIZED) : null;
  }, [activeMatterId, matters]);

  const [openCategories, setOpenCategories] = useState<Record<string, boolean>>(
    {},
  );
  const [favoritesOpen, setFavoritesOpen] = useState(true);
  const [draftsOpen, setDraftsOpen] = useState(true);
  const [mattersOpen, setMattersOpen] = useState(true);

  const favoritesRef = useRef<HTMLElement | null>(null);
  const draftsRef = useRef<HTMLElement | null>(null);
  const mattersRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (!grouped.length) return;
    setOpenCategories((prev) => {
      const next = { ...prev };
      let changed = false;
      for (const g of grouped) {
        if (!(g.category in next)) {
          next[g.category] = activeCategory === g.category;
          changed = true;
        }
      }
      return changed ? next : prev;
    });
  }, [grouped]);

  useEffect(() => {
    if (!activeCategory) return;
    setOpenCategories((prev) =>
      prev[activeCategory] ? prev : { ...prev, [activeCategory]: true },
    );
  }, [activeCategory]);

  const toggleCategory = (c: string) =>
    setOpenCategories((prev) => ({ ...prev, [c]: !prev[c] }));

  return (
    <div className="flex h-full flex-col bg-transparent px-3 py-3 md:px-3 md:py-4">
      <div className="mt-4 min-h-0 flex-1 overflow-y-auto pr-1">
        {matters !== null && favorites.length > 0 && (
          <Section
            sectionRef={favoritesRef}
            title="收藏"
            count={favorites.length}
            open={favoritesOpen}
            onToggle={() => setFavoritesOpen((v) => !v)}
            icon={
              <Star className="h-3.5 w-3.5 shrink-0 text-[var(--warn-500)]" />
            }
          >
            {favoritesOpen &&
              favorites.map((m) => (
                <MatterRow key={`fav-${m.id}`} matter={m} />
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
              <FileText className="h-3.5 w-3.5 shrink-0 text-[var(--info-500)]" />
            }
          >
            {draftsOpen &&
              drafts.map((d) => (
                <div
                  key={d.id}
                  className="group mx-1 flex items-start gap-2 rounded-[var(--r-sm)] border border-transparent px-2 py-1.5 transition-colors hover:bg-[var(--surface-alt)]"
                >
                  <NavLink
                    to={
                      d.type === "proposal"
                        ? `/new?draft=${encodeURIComponent(d.id)}`
                        : d.thread_key
                          ? `/m/${encodeURIComponent(d.thread_key)}?draft=${encodeURIComponent(d.id)}`
                          : "#"
                    }
                    className="min-w-0 flex-1"
                  >
                    <div
                      className="truncate text-sm font-medium text-[var(--text)]"
                      title={
                        d.type === "proposal"
                          ? d.title?.trim() || "(untitled)"
                          : `Reply: ${d.thread_key ?? ""}`
                      }
                    >
                      {d.type === "proposal"
                        ? d.title?.trim() || "(untitled)"
                        : `Reply: ${d.thread_key ?? ""}`}
                    </div>
                    <div className="mt-0.5 truncate text-xs text-[var(--text-mute)]">
                      {d.type} ·{" "}
                      {relativeTime(
                        new Date(d.updated_at * 1000).toISOString(),
                      )}
                    </div>
                  </NavLink>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-7 w-7 opacity-0 transition-opacity group-hover:opacity-100"
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
          sectionRef={mattersRef}
          title="空间"
          count={matters?.length ?? 0}
          open={mattersOpen}
          onToggle={() => setMattersOpen((v) => !v)}
          icon={<FolderTree className="h-3.5 w-3.5 shrink-0" />}
        >
          {matters === null && (
            <div className="px-4 py-3 text-sm text-muted-foreground">
              Loading…
            </div>
          )}
          {mattersOpen && matters !== null && matters.length === 0 && (
            <div className="px-4 py-3 text-sm text-muted-foreground">
              还没有讨论。
            </div>
          )}
          {mattersOpen &&
            matters !== null &&
            grouped.length > 0 &&
            grouped.map((group) => {
              const open = !!openCategories[group.category];
              return (
                <div
                  key={group.category}
                  className="mx-1 border-b border-[var(--line-soft)] py-1 last:border-b-0"
                >
                  <button
                    type="button"
                    onClick={() => toggleCategory(group.category)}
                    className="flex w-full items-center gap-2 rounded-[var(--r-sm)] px-3 py-2 text-left transition-colors hover:bg-[var(--surface-alt)]"
                  >
                    {open ? (
                      <ChevronDown className="h-4 w-4 shrink-0 text-muted-foreground" />
                    ) : (
                      <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground" />
                    )}
                    <FolderTree className="h-4 w-4 shrink-0 text-[var(--text-fade)]" />
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <span className="truncate text-sm font-semibold text-[var(--text)] md:text-[15px]">
                          {group.category}
                        </span>
                        <span className="rounded-full bg-[var(--surface-alt)] px-1.5 py-0.5 text-[10px] font-medium text-[var(--text-mute)]">
                          {group.items.length}
                        </span>
                      </div>
                      {group.last_updated && (
                        <div className="mt-0.5 truncate text-[11px] text-[var(--text-mute)] md:text-xs">
                          最近活动 {relativeTime(group.last_updated)}
                        </div>
                      )}
                    </div>
                    {group.unread > 0 && (
                      <Badge variant="red" className="shrink-0">
                        {group.unread}
                      </Badge>
                    )}
                  </button>
                  {open && (
                    <div className="mt-1 ml-5 border-l border-[var(--line)] bg-transparent pl-2">
                      {group.items.map((m) => (
                        <MatterRow key={m.id} matter={m} />
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

function MatterRow({ matter }: { matter: MatterSummary }) {
  const meta = [
    matter.file_count ? `${matter.file_count} 个文件` : null,
    matter.last_file_type ? `最近 ${matter.last_file_type}` : null,
    matter.updated_at ? relativeTime(matter.updated_at) : null,
  ]
    .filter(Boolean)
    .join(" · ");
  return (
    <div>
      <NavLink
        to={`/m/${encodeURIComponent(matter.id)}`}
        className={({ isActive }) =>
          cn(
            "group mx-0 block rounded-[var(--r-sm)] border-l-2 border-transparent px-3 py-2.5 pl-4 text-[var(--text)] transition-colors duration-150 hover:border-[var(--accent-soft)] hover:bg-[var(--accent-bg)] hover:text-[var(--text)]",
            isActive &&
              "border-[var(--accent)] bg-[var(--accent-bg)] text-[var(--text)] hover:bg-[var(--accent-bg)]",
          )
        }
      >
        {({ isActive }) => (
          <>
            <div className="flex items-start gap-2">
              {matter.unread_count > 0 && (
                <Badge variant="red" className="shrink-0">
                  {matter.unread_count}
                </Badge>
              )}
              <span
                className="line-clamp-2 min-w-0 flex-1 text-[14px] font-medium leading-5 text-[var(--text)] transition-colors group-hover:text-[var(--accent)]"
                title={matter.title}
              >
                {matter.title}
              </span>
            </div>
            <div className="mt-1 flex items-center gap-2">
              <div
                className={cn(
                  "flex min-w-0 flex-1 items-center gap-1.5 text-[10px] leading-5 text-[var(--text-mute)] group-hover:text-[var(--text-soft)] md:text-[11px]",
                  isActive && "text-[var(--accent)]",
                )}
              >
                <OwnerInline matter={matter} />
                {meta && (
                  <>
                    <span className="shrink-0 text-[var(--text-fade)]">·</span>
                    <span className="min-w-0 truncate">{meta}</span>
                  </>
                )}
              </div>
              <span className="shrink-0">
                <StatusBadge
                  status={matter.current_status}
                  className="h-5 px-2 text-[10.5px] transition-transform duration-150 group-hover:translate-x-0.5"
                />
              </span>
            </div>
          </>
        )}
      </NavLink>
    </div>
  );
}

function OwnerInline({ matter }: { matter: MatterSummary }) {
  const label = matter.owner_display || "未分配";
  return (
    <span
      className="inline-flex min-w-0 max-w-[6.75rem] shrink-0 items-center gap-1 text-[var(--text-mute)]"
      title={`负责人：${label}`}
    >
      {matter.owner_avatar_url ? (
        <img
          src={matter.owner_avatar_url}
          alt=""
          className="h-3.5 w-3.5 shrink-0 rounded-full object-cover"
        />
      ) : (
        <UserRound className="h-3.5 w-3.5 shrink-0 text-[var(--text-fade)]" />
      )}
      <span className="min-w-0 truncate">{label}</span>
    </span>
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
    <section className="mb-4 last:mb-0" ref={sectionRef}>
      <button
        type="button"
        onClick={onToggle}
        className="sticky top-0 z-10 mx-1 mt-1 flex w-[calc(100%-0.5rem)] items-center gap-2 border-b border-[var(--line)] bg-[rgba(250,248,243,0.96)] px-3 py-2.5 text-left text-[10px] font-semibold uppercase tracking-[0.12em] text-[var(--text-mute)] backdrop-blur md:text-[11px] md:tracking-[0.14em]"
      >
        {open ? (
          <ChevronDown className="h-3.5 w-3.5 shrink-0" />
        ) : (
          <ChevronRight className="h-3.5 w-3.5 shrink-0" />
        )}
        {icon}
        {title}
        <span className="ml-auto text-muted-foreground/70">{count}</span>
      </button>
      {children}
    </section>
  );
}

type CategoryGroup = {
  category: string;
  items: MatterSummary[];
  last_updated: string | null;
  unread: number;
};

function groupByCategory(matters: MatterSummary[] | null): CategoryGroup[] {
  if (!matters || matters.length === 0) return [];
  const map = new Map<string, CategoryGroup>();
  for (const m of matters) {
    const cat = m.category ?? UNCATEGORIZED;
    const existing = map.get(cat);
    if (existing) {
      existing.items.push(m);
      existing.unread += m.unread_count;
      if ((m.updated_at || "") > (existing.last_updated || "")) {
        existing.last_updated = m.updated_at;
      }
    } else {
      map.set(cat, {
        category: cat,
        items: [m],
        last_updated: m.updated_at,
        unread: m.unread_count,
      });
    }
  }
  return Array.from(map.values())
    .map((g) => ({
      ...g,
      items: [...g.items].sort((a, b) =>
        (b.updated_at || "").localeCompare(a.updated_at || ""),
      ),
    }))
    .sort((a, b) => (b.last_updated || "").localeCompare(a.last_updated || ""));
}
