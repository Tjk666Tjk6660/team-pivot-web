import { Link } from "react-router-dom";
import { LogOut, Plus, RefreshCw, Users } from "lucide-react";
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
    <div className="min-h-screen bg-background">
      <Toaster position="top-center" richColors />
      <header className="sticky top-0 z-40 w-full border-b bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
        <div className="mx-auto flex h-14 max-w-5xl items-center gap-4 px-6">
          <Link to="/" className="font-semibold">
            team-pivot
          </Link>
          <div className="flex items-center gap-1">
            <Button asChild variant="ghost" size="sm">
              <Link to="/new">
                <Plus className="h-4 w-4" /> 新讨论
              </Link>
            </Button>
            {onRefresh && (
              <Button
                variant="ghost"
                size="sm"
                onClick={onRefresh}
                disabled={refreshing}
              >
                <RefreshCw className={`h-4 w-4 ${refreshing ? "animate-spin" : ""}`} />
                同步 Git
              </Button>
            )}
            {onSyncContacts && (
              <Button
                variant="ghost"
                size="sm"
                onClick={onSyncContacts}
                disabled={syncing}
                title="从飞书通讯录拉取最新联系人（供 @mention 使用）"
              >
                <Users className="h-4 w-4" /> 同步联系人
              </Button>
            )}
          </div>
          <div className="ml-auto flex items-center gap-3">
            <div className="flex items-center gap-2">
              {me.avatar_url && (
                <img
                  src={me.avatar_url}
                  alt=""
                  className="h-7 w-7 rounded-full"
                />
              )}
              <div className="text-sm leading-tight">
                <div className="font-medium">{me.name}</div>
                <div className="text-xs text-muted-foreground">
                  {me.pinyin}
                  {me.github_username ? ` · @${me.github_username}` : ""}
                </div>
              </div>
            </div>
            <Button variant="ghost" size="icon" onClick={onLogout} title="Sign out">
              <LogOut className="h-4 w-4" />
            </Button>
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-5xl px-6 py-8">{children}</main>
    </div>
  );
}
