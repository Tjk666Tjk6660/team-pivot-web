import { useEffect, useState } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { fetchMe, logout, type Me } from "@/api";
import { Login } from "@/pages/Login";
import { Dashboard } from "@/pages/Dashboard";
import { ProfileSetup } from "@/pages/ProfileSetup";
import { SettingsPage } from "@/pages/SettingsPage";
import { AdminPage } from "@/pages/AdminPage";
import { ThreadDetailEmpty, ThreadDetailPane } from "@/pages/ThreadDetailPane";
import { NewThread } from "@/pages/NewThread";

export function App() {
  const [me, setMe] = useState<Me | null | undefined>(undefined);

  useEffect(() => {
    fetchMe().then(setMe).catch(() => setMe(null));
  }, []);

  const doLogout = async () => {
    await logout();
    setMe(null);
  };

  if (me === undefined)
    return <div className="p-6 text-sm text-muted-foreground">Loading…</div>;
  if (me === null) return <Login />;
  if (me.needs_setup) return <ProfileSetup me={me} onDone={setMe} />;

  return (
    <Routes>
      <Route element={<Dashboard me={me} onLogout={doLogout} />}>
        <Route path="/" element={<ThreadDetailEmpty />} />
        <Route path="/t/:category/:slug" element={<ThreadDetailPane />} />
      </Route>
      <Route path="/new" element={<NewThread me={me} onLogout={doLogout} />} />
      <Route path="/settings" element={<SettingsPage />} />
      <Route path="/admin" element={<AdminPage />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
