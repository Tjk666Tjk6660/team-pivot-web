import { useEffect, useState } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { fetchMe, logout, type Me } from "./api";
import { Login } from "./pages/Login";
import { Home } from "./pages/Home";
import { ProfileSetup } from "./pages/ProfileSetup";
import { ThreadDetail } from "./pages/ThreadDetail";
import { NewThread } from "./pages/NewThread";

export function App() {
  const [me, setMe] = useState<Me | null | undefined>(undefined);

  useEffect(() => {
    fetchMe().then(setMe).catch(() => setMe(null));
  }, []);

  const doLogout = async () => {
    await logout();
    setMe(null);
  };

  if (me === undefined) return <div style={{ padding: 24 }}>Loading…</div>;
  if (me === null) return <Login />;
  if (me.needs_setup) return <ProfileSetup me={me} onDone={setMe} />;

  return (
    <Routes>
      <Route path="/" element={<Home me={me} onLogout={doLogout} />} />
      <Route
        path="/t/:category/:slug"
        element={<ThreadDetail me={me} onLogout={doLogout} />}
      />
      <Route path="/new" element={<NewThread me={me} onLogout={doLogout} />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
