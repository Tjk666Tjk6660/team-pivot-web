import type { Me } from "../api";

export function Home({ me, onLogout }: { me: Me; onLogout: () => void }) {
  return (
    <div style={{ padding: 48, fontFamily: "system-ui, sans-serif" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        {me.avatar_url && (
          <img
            src={me.avatar_url}
            alt=""
            width={40}
            height={40}
            style={{ borderRadius: "50%" }}
          />
        )}
        <div>
          <div style={{ fontWeight: 600 }}>{me.name}</div>
          <div style={{ fontSize: 12, color: "#666" }}>{me.open_id}</div>
        </div>
        <button onClick={onLogout} style={{ marginLeft: "auto" }}>
          Sign out
        </button>
      </div>
      <h2 style={{ marginTop: 48 }}>Signed in.</h2>
      <p style={{ color: "#666" }}>MVP shell — discussions UI next.</p>
    </div>
  );
}
