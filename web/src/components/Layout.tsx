import { Link } from "react-router-dom";
import { LogOut, RefreshCw, Users } from "lucide-react";
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
    <div className="min-h-screen" style={{ background: "var(--bg)" }}>
      <Toaster position="top-center" richColors />
      <header
        className="sticky top-0 z-40 w-full backdrop-blur"
        style={{
          borderBottom: "1px solid var(--line)",
          background: "rgba(255, 253, 248, 0.94)",
        }}
      >
        <div className="mx-auto flex min-h-[3.6rem] max-w-6xl items-center gap-3 px-3 py-2 sm:gap-4 sm:px-6">
          <div className="flex min-w-0 flex-1 items-center gap-3 sm:gap-5">
            <Link to="/" className="flex min-w-0 items-center gap-2.5">
              <img
                src="/pivot-logo.png"
                alt="Pivot"
                className="h-10 w-10 shrink-0 rounded-lg object-cover object-top"
                style={{
                  background: "var(--surface-alt)",
                  border: "1px solid var(--line)",
                }}
              />
              <span
                className="truncate text-[17px] font-semibold"
                style={{ color: "var(--text)", letterSpacing: "var(--letter-tight)" }}
              >
                Pivot
              </span>
            </Link>
          </div>
          <div className="flex items-center gap-2">
            {onRefresh && (
              <Button
                variant="ghost"
                size="sm"
                className="h-8 rounded-md px-2.5 text-[12.5px] font-medium hover:bg-[var(--surface-alt)]"
                style={{ color: "var(--text-soft)" }}
                onClick={onRefresh}
                disabled={refreshing}
                title="同步 Git"
              >
                <RefreshCw
                  className={`h-3.5 w-3.5 ${refreshing ? "animate-spin" : ""}`}
                  style={{ color: "var(--text-mute)" }}
                />
                <span className="hidden sm:inline">同步 Git</span>
              </Button>
            )}
            {onSyncContacts && (
              <Button
                variant="ghost"
                size="sm"
                className="h-8 rounded-md px-2.5 text-[12.5px] font-medium hover:bg-[var(--surface-alt)]"
                style={{ color: "var(--text-soft)" }}
                onClick={onSyncContacts}
                disabled={syncing}
                title="从飞书通讯录拉取最新联系人（供 @mention 使用）"
              >
                <Users className="h-3.5 w-3.5" style={{ color: "var(--text-mute)" }} />
                <span className="hidden sm:inline">同步联系人</span>
              </Button>
            )}
            <div
              className="flex items-center gap-2 rounded-md px-2 py-1"
              style={{
                border: "1px solid var(--line)",
                background: "var(--surface)",
              }}
            >
              {me.avatar_url && (
                <img src={me.avatar_url} alt="" className="h-6 w-6 rounded-full" />
              )}
              <div
                className="text-[12.5px] font-semibold"
                style={{ color: "var(--text)" }}
              >
                {me.name}
              </div>
              <Button
                variant="ghost"
                size="icon"
                className="h-7 w-7 rounded-md hover:bg-[var(--surface-alt)]"
                style={{ color: "var(--text-mute)" }}
                onClick={onLogout}
                title="Sign out"
              >
                <LogOut className="h-3.5 w-3.5" />
              </Button>
            </div>
          </div>
        </div>
      </header>
      <main className="mx-auto w-full max-w-6xl px-3 py-5 sm:px-6 sm:py-8">
        {children}
      </main>
    </div>
  );
}
