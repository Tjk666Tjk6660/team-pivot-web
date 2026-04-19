import { useEffect, useRef, useState } from "react";
import { Link, Outlet, useOutletContext } from "react-router-dom";
import { ChevronDown, LogOut, Plus, RefreshCw, ShieldCheck, User } from "lucide-react";
import { Toaster, toast } from "sonner";
import {
  deleteDraft,
  fetchDrafts,
  fetchThreads,
  fetchWorkspaceStatus,
  refreshWorkspace,
  type Draft,
  type Me,
  type ThreadMeta,
  type WorkspaceStatus,
} from "@/api";
import { Button } from "@/components/ui/button";
import { ThreadListPane } from "@/components/ThreadListPane";

type DashboardContext = { reloadLists: () => Promise<void> };

export function useDashboard() {
  return useOutletContext<DashboardContext>();
}

export function Dashboard({ me, onLogout }: { me: Me; onLogout: () => void }) {
  const [threads, setThreads] = useState<ThreadMeta[] | null>(null);
  const [drafts, setDrafts] = useState<Draft[] | null>(null);
  const [workspace, setWorkspace] = useState<WorkspaceStatus | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  const load = async () => {
    try {
      const [t, w, d] = await Promise.all([
        fetchThreads(), fetchWorkspaceStatus(), fetchDrafts(),
      ]);
      setThreads(t); setWorkspace(w); setDrafts(d);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
    }
  };

  useEffect(() => { load(); }, []);

  const onRefresh = async () => {
    setRefreshing(true);
    try {
      await refreshWorkspace();
      await load();
      toast.success("已从远端拉取最新");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
    } finally {
      setRefreshing(false);
    }
  };

  const removeDraft = async (id: string) => {
    if (!confirm("Delete this draft?")) return;
    try {
      await deleteDraft(id);
      setDrafts((ds) => (ds ?? []).filter((d) => d.id !== id));
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <div className="flex h-screen flex-col bg-background">
      <Toaster position="top-center" richColors />
      <header className="shrink-0 border-b bg-background/95 backdrop-blur">
        <div className="flex h-14 items-center gap-4 px-6">
          <Link to="/" className="font-semibold">team-pivot</Link>
          <div className="flex items-center gap-1">
            <Button asChild variant="ghost" size="sm">
              <Link to="/new"><Plus className="h-4 w-4" /> 新讨论</Link>
            </Button>
            <Button variant="ghost" size="sm" onClick={onRefresh} disabled={refreshing}>
              <RefreshCw className={`h-4 w-4 ${refreshing ? "animate-spin" : ""}`} /> 同步 Git
            </Button>
            {workspace?.head && (
              <span className="ml-2 text-xs text-muted-foreground">
                HEAD {workspace.head}
              </span>
            )}
          </div>
          <div className="ml-auto">
            <UserMenu me={me} onLogout={onLogout} />
          </div>
        </div>
      </header>

      <div className="flex flex-1 overflow-hidden">
        <aside className="w-96 shrink-0 overflow-y-auto border-r">
          <ThreadListPane
            drafts={drafts}
            threads={threads}
            onRemoveDraft={removeDraft}
          />
        </aside>
        <main className="flex-1 overflow-y-auto">
          <Outlet context={{ reloadLists: load } satisfies DashboardContext} />
        </main>
      </div>
    </div>
  );
}

function UserMenu({ me, onLogout }: { me: Me; onLogout: () => void }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, [open]);

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex items-center gap-2 rounded-full px-2 py-1 transition-colors hover:bg-muted"
      >
        {me.avatar_url && (
          <img src={me.avatar_url} alt="" className="h-7 w-7 rounded-full" />
        )}
        <div className="text-left text-sm leading-tight">
          <div className="font-medium">{me.name}</div>
          <div className="text-xs text-muted-foreground">
            {me.pinyin}
            {me.github_username ? ` · @${me.github_username}` : ""}
          </div>
        </div>
        <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" />
      </button>
      {open && (
        <div className="absolute right-0 top-full z-50 mt-1 w-44 overflow-hidden rounded-lg border bg-white shadow-lg dark:bg-zinc-900">
          <Link
            to="/settings"
            onClick={() => setOpen(false)}
            className="flex items-center gap-2 px-3 py-2 text-sm hover:bg-muted"
          >
            <User className="h-4 w-4" />
            个人设置
          </Link>
          <Link
            to="/admin"
            onClick={() => setOpen(false)}
            className="flex items-center gap-2 px-3 py-2 text-sm hover:bg-muted"
          >
            <ShieldCheck className="h-4 w-4" />
            管理员设置
          </Link>
          <button
            type="button"
            onClick={() => { setOpen(false); onLogout(); }}
            className="flex w-full items-center gap-2 border-t px-3 py-2 text-left text-sm hover:bg-muted"
          >
            <LogOut className="h-4 w-4" />
            退出登录
          </button>
        </div>
      )}
    </div>
  );
}
