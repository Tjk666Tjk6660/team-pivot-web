import { useEffect, useState } from "react";
import { fetchMe, logout, type Me } from "./api";
import { Login } from "./pages/Login";
import { Home } from "./pages/Home";

export function App() {
  const [me, setMe] = useState<Me | null | undefined>(undefined);

  useEffect(() => {
    fetchMe().then(setMe).catch(() => setMe(null));
  }, []);

  if (me === undefined) return <div style={{ padding: 24 }}>Loading…</div>;
  if (me === null) return <Login />;
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
