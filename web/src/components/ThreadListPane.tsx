import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { NavLink, useLocation } from "react-router-dom";
import {
  ChevronDown,
  ChevronRight,
  FileText,
  FolderTree,
  Loader2,
  Search,
  Star,
  Trash2,
  UserRound,
  X,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { StatusBadge } from "@/components/StatusBadge";
import { relativeTime } from "@/lib/time";
import {
  fetchMatters,
  type Draft,
  type MatterScope,
  type MatterStatus,
  type MatterSummary,
} from "@/api";

const UNCATEGORIZED = "未分类";
const PAGE_SIZE = 200;

// All possible matter statuses. Labels keep the raw English value to match
// other places in the codebase that still surface the underlying token (the
// status dropdown can be localized later as a dedicated pass).
const ALL_STATUSES: { value: MatterStatus; label: string }[] = [
  { value: "planning", label: "planning" },
  { value: "executing", label: "executing" },
  { value: "paused", label: "paused" },
  { value: "finished", label: "finished" },
  { value: "cancelled", label: "cancelled" },
  { value: "reviewed", label: "reviewed" },
];

export type MatterListFilter = "all" | "mine";

export function ThreadListPane({
  drafts,
  matters,
  onRemoveDraft,
  listFilter = "all",
  onListFilterChange,
}: {
  drafts: Draft[] | null;
  matters: MatterSummary[] | null;
  onRemoveDraft: (id: string) => void;
  listFilter?: MatterListFilter;
  onListFilterChange?: (next: MatterListFilter) => void;
}) {
  const location = useLocation();
  const activeMatterId = useMemo(() => {
    const match = location.pathname.match(/^\/m\/([^/]+)/);
    return match ? decodeURIComponent(match[1]) : null;
  }, [location.pathname]);

  // ---- search / filter state ----
  const [searchInput, setSearchInput] = useState("");
  const [debouncedQ, setDebouncedQ] = useState("");
  useEffect(() => {
    const t = setTimeout(() => setDebouncedQ(searchInput.trim()), 300);
    return () => clearTimeout(t);
  }, [searchInput]);

  const [ownerFilter, setOwnerFilter] = useState<string[]>([]);
  const [statusFilter, setStatusFilter] = useState<MatterStatus[]>([]);
  const scope: MatterScope = listFilter === "mine" ? "relevant" : "all";

  // The parent (Dashboard) holds the unfiltered, SSE-driven snapshot. As
  // long as the user has applied no filter and stays in the "all" scope
  // we render that directly to avoid an extra round-trip; once they touch
  // search/owner/status/scope, we fetch from the backend so that scope=
  // relevant + multi-value filters work uniformly.
  const isFiltered =
    scope === "relevant"
    || debouncedQ.length > 0
    || ownerFilter.length > 0
    || statusFilter.length > 0;

  const [serverItems, setServerItems] = useState<MatterSummary[] | null>(null);
  const [serverTotal, setServerTotal] = useState(0);
  const [serverHasMore, setServerHasMore] = useState(false);
  const [serverLoading, setServerLoading] = useState(false);
  const [loadMoreLoading, setLoadMoreLoading] = useState(false);
  const reqRef = useRef(0);

  useEffect(() => {
    if (!isFiltered) {
      setServerItems(null);
      setServerTotal(0);
      setServerHasMore(false);
      return;
    }
    const seq = ++reqRef.current;
    setServerLoading(true);
    fetchMatters({
      q: debouncedQ || undefined,
      owner: ownerFilter.length ? ownerFilter : undefined,
      status: statusFilter.length ? statusFilter : undefined,
      scope,
      limit: PAGE_SIZE,
      offset: 0,
    })
      .then((res) => {
        if (seq !== reqRef.current) return;
        setServerItems(res.items);
        setServerTotal(res.total);
        setServerHasMore(res.has_more);
      })
      .catch(() => {
        if (seq !== reqRef.current) return;
        // soft-fail: leave previous items, just clear loading
      })
      .finally(() => {
        if (seq === reqRef.current) setServerLoading(false);
      });
    // `matters` reference is in the deps so SSE-driven refreshes upstream
    // (Dashboard's refreshMattersSilently → setMatters) cascade into a
    // re-fetch of the filtered/relevant slice. Without this, a new @mention
    // arriving via SSE updates the unfiltered list but the mine view stays
    // frozen on its last server response.
  }, [isFiltered, debouncedQ, ownerFilter, statusFilter, scope, matters]);

  const loadMore = useCallback(async () => {
    if (!serverItems || !serverHasMore || loadMoreLoading) return;
    setLoadMoreLoading(true);
    try {
      const res = await fetchMatters({
        q: debouncedQ || undefined,
        owner: ownerFilter.length ? ownerFilter : undefined,
        status: statusFilter.length ? statusFilter : undefined,
        scope,
        limit: PAGE_SIZE,
        offset: serverItems.length,
      });
      setServerItems((prev) => (prev ? [...prev, ...res.items] : res.items));
      setServerTotal(res.total);
      setServerHasMore(res.has_more);
    } finally {
      setLoadMoreLoading(false);
    }
  }, [
    serverItems, serverHasMore, loadMoreLoading,
    debouncedQ, ownerFilter, statusFilter, scope,
  ]);

  // The list to render: server result when filtered, parent prop otherwise.
  const effectiveMatters: MatterSummary[] | null = isFiltered
    ? serverItems
    : matters;

  // Owner options derived from the parent (full) snapshot — keeps the
  // dropdown stable even as the user filters. Falls back to current
  // effectiveMatters if parent is not yet loaded.
  const ownerOptions = useMemo(() => {
    const source = matters ?? effectiveMatters ?? [];
    const seen = new Map<string, string>();
    for (const m of source) {
      if (!m.owner) continue;
      if (!seen.has(m.owner)) seen.set(m.owner, m.owner_display || m.owner);
    }
    return Array.from(seen.entries())
      .map(([value, label]) => ({ value, label }))
      .sort((a, b) => a.label.localeCompare(b.label));
  }, [matters, effectiveMatters]);

  // Favorites (always from full parent list — favorites is an explicit pin
  // and shouldn't be hidden by filter/scope).
  const favorites = useMemo(() => {
    if (!matters) return [];
    return matters
      .filter((m) => m.favorite)
      .sort((a, b) => (b.updated_at || "").localeCompare(a.updated_at || ""));
  }, [matters]);

  // Tab indicator dots: each tab shows red if there's any red-unread under
  // its scope, else gray if any gray-unread, else nothing.
  // - "全部" aggregates from the full parent list (always available).
  // - "与我相关" aggregates from the relevant-scope fetch the last time it
  //   ran. We don't pre-fetch the mine slice when sitting in the all tab —
  //   so the dot only appears once the user has visited 与我相关 at least
  //   once (or after an SSE refresh while sitting in it).
  const allUnread = useMemo(() => {
    let red = 0;
    let gray = 0;
    for (const m of matters ?? []) {
      red += m.red_unread_count ?? m.unread_count ?? 0;
      gray += m.gray_unread_count ?? 0;
    }
    return { red, gray };
  }, [matters]);
  const [mineUnread, setMineUnread] = useState<{ red: number; gray: number }>({
    red: 0,
    gray: 0,
  });
  useEffect(() => {
    // On the mine tab the isFiltered fetch above already populated
    // effectiveMatters with the relevant slice — just reuse it.
    if (scope === "relevant" && effectiveMatters) {
      let red = 0;
      let gray = 0;
      for (const m of effectiveMatters) {
        red += m.red_unread_count ?? m.unread_count ?? 0;
        gray += m.gray_unread_count ?? 0;
      }
      setMineUnread((prev) =>
        prev.red === red && prev.gray === gray ? prev : { red, gray },
      );
      return;
    }
    // On the all tab the mine slice isn't being fetched, so the "与我相关"
    // tab indicator would otherwise stay frozen. Poll the relevant slice
    // independently each time `matters` changes (SSE refresh propagates
    // there) so the dot stays realtime even without visiting the tab.
    if (!matters) return;
    let cancelled = false;
    fetchMatters({ scope: "relevant", limit: PAGE_SIZE, offset: 0 })
      .then((res) => {
        if (cancelled) return;
        let red = 0;
        let gray = 0;
        for (const m of res.items) {
          red += m.red_unread_count ?? m.unread_count ?? 0;
          gray += m.gray_unread_count ?? 0;
        }
        setMineUnread((prev) =>
          prev.red === red && prev.gray === gray ? prev : { red, gray },
        );
      })
      .catch(() => {
        // soft-fail — don't clobber the previous value on transient errors
      });
    return () => {
      cancelled = true;
    };
  }, [scope, effectiveMatters, matters]);

  // Both "全部" and "与我相关" use the same category-grouped layout. The
  // difference is just the data source: relevant scope asks the backend for
  // owner / @-mention / authored matters and that set already includes both
  // unread and read items — so reading a matter does NOT remove it from
  // the list (spec §2.3: 已读后不消失). In the relevant scope we also sort
  // each category's items "unread first, then by last_activity desc"
  // (spec §2.3 排序). The unread/read split is computed in real time from
  // red+gray counts — once you read a matter, on the next list refresh it
  // sinks below the unread band; the matter itself is never removed.
  const grouped = useMemo(
    () =>
      groupByCategory(effectiveMatters, {
        unreadFirst: scope === "relevant",
      }),
    [effectiveMatters, scope],
  );

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

  // When the user runs a search / filter, the result is meaningless if the
  // matched categories stay collapsed. Force every grouped category open
  // whenever the filter key changes — and only then, so the user can still
  // manually collapse a category mid-typing without it springing back.
  const filterKey = useMemo(
    () =>
      `${debouncedQ}|${ownerFilter.slice().sort().join(",")}|${statusFilter.slice().sort().join(",")}`,
    [debouncedQ, ownerFilter, statusFilter],
  );
  useEffect(() => {
    if (!isFiltered) return;
    setOpenCategories((prev) => {
      const next = { ...prev };
      let changed = false;
      for (const g of grouped) {
        if (!next[g.category]) {
          next[g.category] = true;
          changed = true;
        }
      }
      return changed ? next : prev;
    });
    // grouped intentionally omitted — we only want to expand on a fresh
    // filter/scope change, not every time the result list re-references
    // the same categories (e.g. SSE refresh that adds a row inside an
    // already-expanded category).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filterKey, isFiltered]);

  useEffect(() => {
    if (!activeCategory) return;
    setOpenCategories((prev) =>
      prev[activeCategory] ? prev : { ...prev, [activeCategory]: true },
    );
  }, [activeCategory]);

  const toggleCategory = (c: string) =>
    setOpenCategories((prev) => ({ ...prev, [c]: !prev[c] }));

  const totalCount = isFiltered
    ? serverTotal
    : (effectiveMatters?.length ?? 0);
  const isLoadingList = effectiveMatters === null || (isFiltered && serverLoading && (serverItems?.length ?? 0) === 0);
  const isEmptyMatch =
    effectiveMatters !== null && effectiveMatters.length === 0;

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
          count={totalCount}
          open={mattersOpen}
          onToggle={() => setMattersOpen((v) => !v)}
          icon={<FolderTree className="h-3.5 w-3.5 shrink-0" />}
        >
          {mattersOpen && (
            <div className="mx-2 mb-2 mt-2 space-y-2">
              {onListFilterChange && (
                <FilterToggle
                  value={listFilter}
                  onChange={onListFilterChange}
                  allUnread={allUnread}
                  mineUnread={mineUnread}
                />
              )}
              <div className="flex flex-wrap items-center gap-1">
                <div className="min-w-[7rem] flex-1">
                  <SearchBar
                    value={searchInput}
                    onChange={setSearchInput}
                  />
                </div>
                <MultiSelectDropdown
                  label="Owner"
                  options={ownerOptions}
                  selected={ownerFilter}
                  onChange={setOwnerFilter}
                />
                <MultiSelectDropdown
                  label="Status"
                  options={ALL_STATUSES.map((s) => ({
                    value: s.value,
                    label: s.label,
                  }))}
                  selected={statusFilter}
                  onChange={(next) =>
                    setStatusFilter(next as MatterStatus[])
                  }
                />
              </div>
            </div>
          )}

          {mattersOpen && isLoadingList && (
            <div className="flex items-center gap-2 px-4 py-3 text-sm text-muted-foreground">
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
              加载中…
            </div>
          )}
          {mattersOpen
            && !isLoadingList
            && isEmptyMatch
            && (debouncedQ
              || ownerFilter.length
              || statusFilter.length
              || scope === "relevant") && (
            <div className="px-4 py-3 text-sm text-muted-foreground">
              没有匹配的 matter。
            </div>
          )}
          {mattersOpen
            && !isLoadingList
            && isEmptyMatch
            && !debouncedQ
            && !ownerFilter.length
            && !statusFilter.length
            && scope === "all" && (
            <div className="px-4 py-3 text-sm text-muted-foreground">
              还没有讨论。
            </div>
          )}

          {/* By-category grouping for both 全部 and 与我相关. The data set
              for 与我相关 comes from scope=relevant and intentionally keeps
              read matters present (spec §2.3 已读后不消失). */}
          {mattersOpen
            && !isLoadingList
            && effectiveMatters
            && grouped.length > 0
            && grouped.map((group) => {
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
                    <UnreadBadges red={group.red} gray={group.gray} />
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

          {mattersOpen
            && isFiltered
            && serverHasMore
            && !isLoadingList && (
            <div className="px-4 py-2">
              <button
                type="button"
                onClick={loadMore}
                disabled={loadMoreLoading}
                className="w-full rounded-[var(--r-sm)] border border-[var(--line)] px-3 py-1.5 text-xs text-[var(--text-soft)] transition-colors hover:bg-[var(--surface-alt)] disabled:opacity-60"
              >
                {loadMoreLoading
                  ? "加载中…"
                  : `加载更多（${(effectiveMatters?.length ?? 0)} / ${serverTotal}）`}
              </button>
            </div>
          )}
        </Section>
      </div>
    </div>
  );
}

function MatterRow({ matter }: { matter: MatterSummary }) {
  const lastActivity = activityKey(matter);
  const meta = [
    matter.file_count ? `${matter.file_count} 个文件` : null,
    matter.last_file_type ? `最近 ${matter.last_file_type}` : null,
    lastActivity ? relativeTime(lastActivity) : null,
  ]
    .filter(Boolean)
    .join(" · ");
  // Prefer the new red/gray split. Fall back to the legacy single-number
  // rendering when the backend hasn't been upgraded yet (red/gray omitted
  // → keep showing unread_count as red, matching old behavior).
  const red = matter.red_unread_count;
  const gray = matter.gray_unread_count;
  const hasSplit = red !== undefined && gray !== undefined;
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
              {hasSplit ? (
                <UnreadBadges red={red} gray={gray} />
              ) : (
                matter.unread_count > 0 && (
                  <Badge variant="red" className="shrink-0">
                    {matter.unread_count}
                  </Badge>
                )
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
  // Sum of red_unread_count / gray_unread_count across the category's
  // matters. Falls back to splitting unread_count entirely into red when
  // the backend is older and didn't return the split (matches the legacy
  // single-red-badge behavior).
  red: number;
  gray: number;
};

function UnreadBadges({ red, gray }: { red: number; gray: number }) {
  if (red <= 0 && gray <= 0) return null;
  const fmt = (n: number) => (n > 99 ? "99+" : String(n));
  // Both present → single rounded pill split into two halves: red left,
  // gray right. Reads as one unit visually but the two colors signal the
  // semantic split — red is "your stuff", gray is "background updates".
  if (red > 0 && gray > 0) {
    return (
      <span
        className="inline-flex shrink-0 items-center overflow-hidden rounded-full text-xs font-medium leading-tight"
        title={`相关 ${red} · 普通 ${gray}`}
      >
        <span className="bg-[var(--danger-500)] px-2 py-0.5 text-white">
          {fmt(red)}
        </span>
        <span className="bg-[var(--status-archived-bg)] px-2 py-0.5 text-[var(--status-archived-fg)]">
          {fmt(gray)}
        </span>
      </span>
    );
  }
  if (red > 0) {
    return (
      <Badge variant="red" className="shrink-0" title="跟你相关的未读">
        {fmt(red)}
      </Badge>
    );
  }
  return (
    <Badge variant="gray" className="shrink-0" title="普通更新">
      {fmt(gray)}
    </Badge>
  );
}

function FilterToggle({
  value,
  onChange,
  allUnread,
  mineUnread,
}: {
  value: MatterListFilter;
  onChange: (next: MatterListFilter) => void;
  allUnread: { red: number; gray: number };
  mineUnread: { red: number; gray: number };
}) {
  const options: {
    key: MatterListFilter;
    label: string;
    hint?: string;
    unread: { red: number; gray: number };
  }[] = [
    { key: "all", label: "全部", unread: allUnread },
    {
      key: "mine",
      label: "与我相关",
      hint: "owner / @ / 我创建过",
      unread: mineUnread,
    },
  ];
  return (
    <div
      role="tablist"
      aria-label="matter 列表筛选"
      className="flex rounded-full bg-[var(--surface-alt)] p-1 text-[12px]"
    >
      {options.map((opt) => {
        const active = value === opt.key;
        // Red wins over gray — any red-unread under this scope flags the
        // tab as having "your stuff", regardless of how many gray sit
        // underneath.
        const dotColor =
          opt.unread.red > 0
            ? "var(--danger-500)"
            : opt.unread.gray > 0
              ? "var(--text-fade)"
              : null;
        return (
          <button
            key={opt.key}
            type="button"
            role="tab"
            aria-selected={active}
            title={opt.hint}
            onClick={() => {
              if (!active) onChange(opt.key);
            }}
            className={cn(
              "relative flex-1 rounded-full px-3.5 py-1 text-center font-medium transition-all",
              active
                ? "bg-[var(--accent)] text-[var(--accent-ink)] shadow-[0_1px_3px_rgba(0,0,0,0.18)]"
                : "text-[var(--text-soft)] hover:bg-[var(--surface)] hover:text-[var(--text)] hover:shadow-[0_1px_2px_rgba(0,0,0,0.06)]",
            )}
          >
            {opt.label}
            {dotColor && (
              <span
                aria-hidden
                className="absolute right-2 top-1 h-1.5 w-1.5 rounded-full"
                style={{ backgroundColor: dotColor }}
              />
            )}
          </button>
        );
      })}
    </div>
  );
}

function SearchBar({
  value,
  onChange,
}: {
  value: string;
  onChange: (next: string) => void;
}) {
  return (
    <div className="relative flex h-7 w-full min-w-0 items-center rounded-[var(--r-sm)] border border-[var(--line)] bg-[var(--surface)] transition-colors focus-within:border-[var(--accent)] focus-within:ring-1 focus-within:ring-[var(--accent-soft)]">
      <Search
        className="pointer-events-none ml-2 h-3.5 w-3.5 shrink-0 text-[var(--text-fade)]"
        aria-hidden
      />
      <input
        type="text"
        size={1}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder="搜索标题"
        aria-label="搜索 matter 标题"
        className="w-full min-w-0 flex-1 bg-transparent px-2 py-0 text-[13px] text-[var(--text)] placeholder:text-[var(--text-fade)] focus:outline-none"
      />
      {value && (
        <button
          type="button"
          aria-label="清空搜索"
          onClick={() => onChange("")}
          className="mr-1 flex h-5 w-5 shrink-0 items-center justify-center rounded text-[var(--text-fade)] hover:bg-[var(--surface-alt)] hover:text-[var(--text)]"
        >
          <X className="h-3 w-3" />
        </button>
      )}
    </div>
  );
}

function MultiSelectDropdown({
  label,
  options,
  selected,
  onChange,
}: {
  label: string;
  options: { value: string; label: string }[];
  selected: string[];
  onChange: (next: string[]) => void;
}) {
  const [open, setOpen] = useState(false);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  // Menu is portaled to document.body to escape any overflow:auto/hidden
  // ancestor (the sidebar's scroll container would otherwise clip it on
  // narrow viewports). Fixed positioning is recomputed on scroll/resize.
  const [pos, setPos] = useState<{ top: number; right: number } | null>(null);

  const updatePos = useCallback(() => {
    const btn = buttonRef.current;
    if (!btn) return;
    const r = btn.getBoundingClientRect();
    setPos({
      top: r.bottom + 4,
      right: Math.max(8, window.innerWidth - r.right),
    });
  }, []);

  useEffect(() => {
    if (!open) {
      setPos(null);
      return;
    }
    updatePos();
    const onDocClick = (e: MouseEvent) => {
      const t = e.target as Node;
      if (buttonRef.current?.contains(t)) return;
      if (menuRef.current?.contains(t)) return;
      setOpen(false);
    };
    const onWindow = () => updatePos();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDocClick);
    window.addEventListener("scroll", onWindow, true);
    window.addEventListener("resize", onWindow);
    window.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDocClick);
      window.removeEventListener("scroll", onWindow, true);
      window.removeEventListener("resize", onWindow);
      window.removeEventListener("keydown", onKey);
    };
  }, [open, updatePos]);

  const toggle = (v: string) => {
    if (selected.includes(v)) onChange(selected.filter((x) => x !== v));
    else onChange([...selected, v]);
  };

  const isActive = selected.length > 0;

  return (
    <>
      <button
        ref={buttonRef}
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        title={
          isActive
            ? selected
                .map(
                  (v) => options.find((o) => o.value === v)?.label ?? v,
                )
                .join("、")
            : undefined
        }
        className={cn(
          "inline-flex h-7 items-center gap-1 rounded-[var(--r-sm)] border px-2 text-[12px] transition-colors",
          isActive
            ? "border-[var(--accent)] bg-[var(--accent-bg)] font-medium text-[var(--text)]"
            : "border-[var(--line)] bg-transparent text-[var(--text-soft)] hover:border-[var(--text-fade)] hover:bg-[var(--surface-alt)] hover:text-[var(--text)]",
        )}
      >
        <span>{label}</span>
        <ChevronDown className="h-3 w-3 opacity-70" />
      </button>
      {open && pos && createPortal(
        <div
          ref={menuRef}
          style={{
            position: "fixed",
            top: pos.top,
            right: pos.right,
            zIndex: 50,
          }}
          className="max-h-64 min-w-[10rem] max-w-[16rem] w-max overflow-y-auto rounded-[var(--r-md)] border border-[var(--line)] bg-[var(--surface)] py-1 shadow-lg"
        >
          {options.length === 0 && (
            <div className="px-3 py-2 text-[11px] text-[var(--text-fade)]">
              无可选项
            </div>
          )}
          {options.map((opt) => {
            const checked = selected.includes(opt.value);
            return (
              <button
                key={opt.value}
                type="button"
                onClick={() => toggle(opt.value)}
                title={opt.label}
                className={cn(
                  "flex w-full items-center gap-2 px-2.5 py-1.5 text-left text-[12px] transition-colors hover:bg-[var(--surface-alt)]",
                  checked && "text-[var(--text)]",
                )}
              >
                <span
                  className={cn(
                    "flex h-3.5 w-3.5 shrink-0 items-center justify-center rounded-[3px] border transition-colors",
                    checked
                      ? "border-[var(--accent)] bg-[var(--accent)] text-[var(--accent-ink)]"
                      : "border-[var(--line)]",
                  )}
                >
                  {checked && <span className="text-[10px] leading-none">✓</span>}
                </span>
                <span className="truncate">{opt.label}</span>
              </button>
            );
          })}
        </div>,
        document.body,
      )}
    </>
  );
}


// Sort key: last_activity_at when the backend provides it (max of
// matter.updated_at and the latest comment.created_at), falling back to
// matter.updated_at for older backends. This is what makes a matter that
// just received a new comment / @-mention float to the top — comments
// don't bump matter.updated_at on their own.
function activityKey(m: MatterSummary): string {
  return m.last_activity_at || m.updated_at || "";
}

// Per-matter red / gray, with back-compat fallback when the backend is
// pre-split: the entire unread_count counts as red, mirroring the
// legacy single-red-badge UX.
function matterRed(m: MatterSummary): number {
  return m.red_unread_count ?? m.unread_count ?? 0;
}
function matterGray(m: MatterSummary): number {
  return m.gray_unread_count ?? 0;
}

function groupByCategory(
  matters: MatterSummary[] | null,
  options: { unreadFirst?: boolean } = {},
): CategoryGroup[] {
  if (!matters || matters.length === 0) return [];
  const map = new Map<string, CategoryGroup>();
  for (const m of matters) {
    const cat = m.category ?? UNCATEGORIZED;
    const ak = activityKey(m);
    const r = matterRed(m);
    const g = matterGray(m);
    const existing = map.get(cat);
    if (existing) {
      existing.items.push(m);
      existing.red += r;
      existing.gray += g;
      if (ak > (existing.last_updated || "")) {
        existing.last_updated = ak;
      }
    } else {
      map.set(cat, {
        category: cat,
        items: [m],
        last_updated: ak,
        red: r,
        gray: g,
      });
    }
  }
  // Per-category sort:
  //   unreadFirst (与我相关 spec §2.3): unread bucket first by last_activity
  //   desc, then read bucket by last_activity desc.
  //   else: pure last_activity desc.
  return Array.from(map.values())
    .map((grp) => ({
      ...grp,
      items: [...grp.items].sort((a, b) => {
        if (options.unreadFirst) {
          const aUnread = matterRed(a) + matterGray(a) > 0 ? 0 : 1;
          const bUnread = matterRed(b) + matterGray(b) > 0 ? 0 : 1;
          if (aUnread !== bUnread) return aUnread - bUnread;
        }
        return activityKey(b).localeCompare(activityKey(a));
      }),
    }))
    .sort((a, b) => (b.last_updated || "").localeCompare(a.last_updated || ""));
}
