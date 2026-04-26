import { useEffect, useState } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { fetchMe, logout, type Me } from "@/api";
import { Login } from "@/pages/Login";
import { Dashboard } from "@/pages/Dashboard";
import { ProfileSetup } from "@/pages/ProfileSetup";
import { SettingsPage } from "@/pages/SettingsPage";
import { AdminPage } from "@/pages/AdminPage";
import { MatterDetailEmpty, MatterDetailPane } from "@/pages/MatterDetailPane";
import { NewMatter } from "@/pages/NewMatter";
import { MatterEventsProvider } from "@/events/MatterEventsProvider";

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
    <MatterEventsProvider>
      <Routes>
        <Route element={<Dashboard me={me} onLogout={doLogout} />}>
          <Route path="/" element={<MatterDetailEmpty />} />
          <Route path="/m/:matter_id" element={<MatterDetailPane />} />
        </Route>
        <Route path="/new" element={<NewMatter me={me} onLogout={doLogout} />} />
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="/admin" element={<AdminPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </MatterEventsProvider>
  );
}
