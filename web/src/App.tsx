import { useEffect, useState } from "react";
import { fetchMe, logout, type Me } from "./api";
import { Login } from "./pages/Login";
import { Home } from "./pages/Home";
import { ProfileSetup } from "./pages/ProfileSetup";

export function App() {
  const [me, setMe] = useState<Me | null | undefined>(undefined);

  useEffect(() => {
    fetchMe().then(setMe).catch(() => setMe(null));
  }, []);

  if (me === undefined) return <div style={{ padding: 24 }}>Loading…</div>;
  if (me === null) return <Login />;
  if (me.needs_setup) return <ProfileSetup me={me} onDone={setMe} />;
  return (
    <Home
      me={me}
      onLogout={async () => {
        await logout();
        setMe(null);
      }}
    />
  );
}
