import { useEffect, useMemo, useRef, useState } from "react";
import { Link, NavLink, useLocation } from "react-router-dom";
import {
  ChevronDown,
  ChevronRight,
  FileText,
  FolderTree,
  Plus,
  Trash2,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { StatusBadge } from "@/components/StatusBadge";
import { relativeTime } from "@/lib/time";
import type { Draft, MatterStatus, MatterSummary } from "@/api";

type StatusBucket = {
  key: string;
  title: string;
  statuses: MatterStatus[];
};

const BUCKETS: StatusBucket[] = [
  { key: "active",   title: "进行中", statuses: ["planning", "executing", "paused"] },
  { key: "closed",   title: "已结束", statuses: ["finished", "cancelled"] },
  { key: "reviewed", title: "已复盘", statuses: ["reviewed"] },
];

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

  const grouped = useMemo(() => groupByBucket(matters), [matters]);
  const [openBuckets, setOpenBuckets] = useState<Record<string, boolean>>({
    active: true,
    closed: false,
    reviewed: false,
  });
  const [draftsOpen, setDraftsOpen] = useState(true);
  const [mattersOpen, setMattersOpen] = useState(true);

  const draftsRef = useRef<HTMLElement | null>(null);
  const mattersRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (!activeMatterId || !matters) return;
    const active = matters.find((m) => m.id === activeMatterId);
    if (!active) return;
    const bucket = BUCKETS.find((b) => b.statuses.includes(active.current_status));
    if (bucket) {
      setOpenBuckets((prev) => (prev[bucket.key] ? prev : { ...prev, [bucket.key]: true }));
    }
  }, [activeMatterId, matters]);

  const toggleBucket = (key: string) =>
    setOpenBuckets((prev) => ({ ...prev, [key]: !prev[key] }));

  return (
    <div className="flex h-full flex-col bg-transparent px-3 py-3 md:px-3 md:py-4">
      <Button
        asChild
        className="h-11 w-full justify-start rounded-xl bg-blue-600 px-4 text-sm font-medium text-white shadow-sm hover:bg-blue-700"
      >
        <Link to="/new">
          <Plus className="h-4 w-4" />
          新事项
        </Link>
      </Button>

      <div className="mt-4 min-h-0 flex-1 overflow-y-auto pr-1">
        {drafts && drafts.length > 0 && (
          <Section
            sectionRef={draftsRef}
            title="草稿"
            count={drafts.length}
            open={draftsOpen}
            onToggle={() => setDraftsOpen((v) => !v)}
            icon={<FileText className="h-3.5 w-3.5 shrink-0 text-sky-600" />}
          >
            {draftsOpen &&
              drafts.map((d) => (
                <div
                  key={d.id}
                  className="group mx-1 flex items-start gap-2 rounded-lg border border-transparent px-2 py-1.5 transition-colors hover:bg-slate-100/80"
                >
                  <NavLink
                    to={d.type === "proposal" ? `/new?draft=${d.id}` : "#"}
                    className="min-w-0 flex-1"
                  >
                    <div className="truncate text-sm font-medium text-slate-800">
                      {d.type === "proposal"
                        ? d.title?.trim() || "(untitled)"
                        : `Reply: ${d.thread_key ?? ""}`}
                    </div>
                    <div className="mt-0.5 truncate text-xs text-slate-500">
                      {d.type} · {relativeTime(new Date(d.updated_at * 1000).toISOString())}
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
          title="事项"
          count={matters?.length ?? 0}
          open={mattersOpen}
          onToggle={() => setMattersOpen((v) => !v)}
          icon={<FolderTree className="h-3.5 w-3.5 shrink-0" />}
        >
          {matters === null && (
            <div className="px-4 py-3 text-sm text-muted-foreground">Loading…</div>
          )}
          {mattersOpen && matters !== null && matters.length === 0 && (
            <div className="px-4 py-3 text-sm text-muted-foreground">还没有事项。</div>
          )}
          {mattersOpen &&
            matters !== null &&
            grouped.map((group) =>
              group.items.length === 0 ? null : (
                <div
                  key={group.key}
                  className="mx-1 border-b border-slate-200/60 py-1 last:border-b-0"
                >
                  <button
                    type="button"
                    onClick={() => toggleBucket(group.key)}
                    className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left transition-colors hover:bg-slate-100/80"
                  >
                    {openBuckets[group.key] ? (
                      <ChevronDown className="h-4 w-4 shrink-0 text-muted-foreground" />
                    ) : (
                      <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground" />
                    )}
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <span className="truncate text-sm font-semibold text-slate-900 md:text-[15px]">
                          {group.title}
                        </span>
                        <span className="rounded-full bg-slate-100 px-1.5 py-0.5 text-[10px] font-medium text-slate-500">
                          {group.items.length}
                        </span>
                      </div>
                      {group.last_updated && (
                        <div className="mt-0.5 truncate text-[11px] text-slate-500 md:text-xs">
                          最近活动 {relativeTime(group.last_updated)}
                        </div>
                      )}
                    </div>
                  </button>
                  {openBuckets[group.key] && (
                    <div className="mt-1 ml-5 border-l border-slate-200/70 bg-transparent pl-2">
                      {group.items.map((m) => (
                        <MatterRow key={m.id} matter={m} />
                      ))}
                    </div>
                  )}
                </div>
              ),
            )}
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
    <NavLink
      to={`/m/${encodeURIComponent(matter.id)}`}
      className={({ isActive }) =>
        cn(
          "mx-0 block rounded-lg border-l-2 border-transparent px-3 py-2.5 pl-4 transition-colors hover:bg-slate-100/80",
          isActive && "border-blue-500 bg-blue-100/85 text-blue-950 hover:bg-blue-100/85",
        )
      }
    >
      {({ isActive }) => (
        <>
          <div className="flex items-center gap-2">
            <span className="truncate text-[14px] font-medium">{matter.title}</span>
            <span className="ml-auto shrink-0">
              <StatusBadge status={matter.current_status} />
            </span>
          </div>
          <div
            className={cn(
              "mt-1 truncate text-[10px] leading-5 text-slate-500 md:text-[11px]",
              isActive && "text-blue-800/80",
            )}
          >
            {meta}
          </div>
        </>
      )}
    </NavLink>
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
        className="sticky top-0 z-10 mx-1 mt-1 flex w-[calc(100%-0.5rem)] items-center gap-2 border-b border-slate-200/70 bg-[rgba(248,250,252,0.96)] px-3 py-2.5 text-left text-[10px] font-semibold uppercase tracking-[0.12em] text-slate-500 backdrop-blur md:text-[11px] md:tracking-[0.14em]"
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

type BucketGroup = {
  key: string;
  title: string;
  items: MatterSummary[];
  last_updated: string | null;
};

function groupByBucket(matters: MatterSummary[] | null): BucketGroup[] {
  if (!matters) return BUCKETS.map((b) => ({ key: b.key, title: b.title, items: [], last_updated: null }));
  return BUCKETS.map((b) => {
    const items = matters
      .filter((m) => b.statuses.includes(m.current_status))
      .sort((a, b) => (b.updated_at || "").localeCompare(a.updated_at || ""));
    const last_updated = items[0]?.updated_at ?? null;
    return { key: b.key, title: b.title, items, last_updated };
  });
}
