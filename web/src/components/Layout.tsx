import { Link } from "react-router-dom";
import { LogOut, MessageSquareText, RefreshCw, Users } from "lucide-react";
import type { Me } from "@/api";
import { Button } from "@/components/ui/button";
import { Toaster } from "sonner";

export function Layout({
  me,
  onLogout,
  onSyncContacts,
  syncing,
  onRefresh,
  refreshing,
  children,
}: {
  me: Me;
  onLogout: () => void;
  onSyncContacts?: () => void;
  syncing?: boolean;
  onRefresh?: () => void;
  refreshing?: boolean;
  children: React.ReactNode;
}) {
  return (
    <div className="min-h-screen bg-transparent">
      <Toaster position="top-center" richColors />
      <header className="sticky top-0 z-40 w-full border-b border-slate-200/80 bg-[rgba(247,249,251,0.94)] backdrop-blur">
        <div className="mx-auto flex min-h-[3.75rem] max-w-6xl items-center gap-3 px-3 py-2 sm:min-h-[4.25rem] sm:flex-wrap sm:gap-4 sm:px-6 sm:py-3">
          <div className="flex min-w-0 flex-1 items-center gap-3 sm:gap-5">
            <Link to="/" className="flex min-w-0 items-center gap-2.5">
              <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-xl bg-blue-600 text-white shadow-sm">
                <MessageSquareText className="h-4 w-4" />
              </span>
              <span className="truncate text-[17px] font-semibold text-slate-900">
                team-pivot
              </span>
            </Link>
            <nav className="flex items-center gap-2">
              <span className="inline-flex h-10 items-center border-b-2 border-blue-600 px-1 text-sm font-semibold text-slate-900">
                讨论
              </span>
            </nav>
          </div>
          <div className="flex items-center gap-2 sm:flex-wrap sm:gap-3">
            {onRefresh && (
              <Button
                variant="outline"
                size="sm"
                className="h-9 rounded-xl border-slate-200/90 bg-white/84 px-2.5 text-sm font-medium text-slate-700 shadow-none hover:bg-slate-50 sm:h-10 sm:px-3.5"
                onClick={onRefresh}
                disabled={refreshing}
                title="同步 Git"
              >
                <RefreshCw className={`h-4 w-4 ${refreshing ? "animate-spin" : ""}`} />
                <span className="hidden sm:inline">同步 Git</span>
              </Button>
            )}
            {onSyncContacts && (
              <Button
                variant="outline"
                size="sm"
                className="h-9 rounded-xl border-slate-200/90 bg-white/84 px-2.5 text-sm font-medium text-slate-700 shadow-none hover:bg-slate-50 sm:h-10 sm:px-3.5"
                onClick={onSyncContacts}
                disabled={syncing}
                title="从飞书通讯录拉取最新联系人（供 @mention 使用）"
              >
                <Users className="h-4 w-4" />
                <span className="hidden sm:inline">同步联系人</span>
              </Button>
            )}
          </div>
          <div className="flex items-center gap-3 rounded-xl border border-slate-200/90 bg-white/84 px-1.5 py-1 sm:px-2.5 sm:py-1.5">
            <div className="flex items-center gap-2">
              {me.avatar_url && (
                <img
                  src={me.avatar_url}
                  alt=""
                  className="h-7 w-7 rounded-full"
                />
              )}
              <div className="text-sm font-semibold text-slate-900">{me.name}</div>
            </div>
            <Button variant="ghost" size="icon" className="rounded-lg text-slate-500 hover:bg-slate-100" onClick={onLogout} title="Sign out">
              <LogOut className="h-4 w-4" />
            </Button>
          </div>
        </div>
      </header>
      <main className="mx-auto w-full max-w-6xl px-3 py-4 sm:px-6 sm:py-8">{children}</main>
    </div>
  );
}
