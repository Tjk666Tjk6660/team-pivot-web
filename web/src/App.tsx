import { useEffect, useState } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { fetchMe, getInitStatus, logout, type Me } from "@/api";
import { Login } from "@/pages/Login";
import { Init } from "@/pages/Init";
import { InviteAccept } from "@/pages/InviteAccept";
import { Dashboard } from "@/pages/Dashboard";
import { ProfileSetup } from "@/pages/ProfileSetup";
import { SettingsPage } from "@/pages/SettingsPage";
import { SettingsExternalAI } from "@/pages/SettingsExternalAI";
import { AdminAI } from "@/pages/admin/AdminAI";
import { AdminApplications } from "@/pages/admin/AdminApplications";
import { AdminContacts } from "@/pages/admin/AdminContacts";
import { AdminDailyReport } from "@/pages/admin/AdminDailyReport";
import { AdminHome } from "@/pages/admin/AdminHome";
import { AdminInvites } from "@/pages/admin/AdminInvites";
import { AdminLayout } from "@/pages/admin/AdminLayout";
import { AdminMarkdown } from "@/pages/admin/AdminMarkdown";
import { AdminRoles } from "@/pages/admin/AdminRoles";
import { AdminScoringPage } from "@/pages/admin/AdminScoringPage";
import { AdminUsers } from "@/pages/admin/AdminUsers";
import { AdminWorkspace } from "@/pages/admin/AdminWorkspace";
import { MatterDetailEmpty, MatterDetailPane } from "@/pages/MatterDetailPane";
import { NewMatter } from "@/pages/NewMatter";
import { MatterEventsProvider } from "@/events/MatterEventsProvider";
import { MarkdownStyleProvider } from "@/components/markdown/MarkdownStyleProvider";

export function App() {
  const [me, setMe] = useState<Me | null | undefined>(undefined);
  const [needsInit, setNeedsInit] = useState<boolean | null>(null);

  useEffect(() => {
    fetchMe().then(setMe).catch(() => setMe(null));
    getInitStatus()
      .then((r) => setNeedsInit(r.needs_init))
      .catch(() => setNeedsInit(false));
  }, []);

  const doLogout = async () => {
    await logout();
    setMe(null);
  };

  if (me === undefined || needsInit === null)
    return <div className="p-6 text-sm text-muted-foreground">Loading…</div>;

  // 系统未初始化 → 强制 /init；不允许走登录或任何业务页。
  if (needsInit) {
    if (window.location.pathname !== "/init") {
      return <Navigate to="/init" replace />;
    }
    return <Init />;
  }

  // 已初始化但不小心进了 /init → 拍回首页。
  if (window.location.pathname === "/init") {
    return <Navigate to="/" replace />;
  }

  // /invite/:token 走独立公共页（无需登录），让被邀请人在创建账号前
  // 也能打开链接。需要在 me/Login 守卫之前判，否则会被弹回 Login。
  const inviteMatch = window.location.pathname.match(/^\/invite\/([^/]+)$/);
  if (inviteMatch) {
    return (
      <Routes>
        <Route path="/invite/:token" element={<InviteAccept />} />
      </Routes>
    );
  }

  if (me === null) return <Login />;
  if (me.needs_setup) return <ProfileSetup me={me} onDone={setMe} />;

  return (
    <MarkdownStyleProvider>
      <MatterEventsProvider>
        <Routes>
          <Route element={<Dashboard me={me} onLogout={doLogout} />}>
            <Route path="/" element={<MatterDetailEmpty />} />
            <Route path="/m/:matter_id" element={<MatterDetailPane />} />
            <Route path="/new" element={<NewMatter me={me} />} />
          </Route>
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="/settings/external-ai" element={<SettingsExternalAI />} />
          <Route path="/admin" element={<AdminLayout />}>
            <Route index element={<AdminHome />} />
            <Route path="applications" element={<AdminApplications />} />
            <Route path="users" element={<AdminUsers />} />
            <Route path="roles" element={<AdminRoles />} />
            <Route path="invites" element={<AdminInvites />} />
            <Route path="workspace" element={<AdminWorkspace />} />
            <Route path="markdown" element={<AdminMarkdown />} />
            <Route path="daily-report" element={<AdminDailyReport />} />
            <Route path="ai" element={<AdminAI />} />
            <Route path="contacts" element={<AdminContacts />} />
            <Route path="scoring" element={<AdminScoringPage />} />
          </Route>
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </MatterEventsProvider>
    </MarkdownStyleProvider>
  );
}
