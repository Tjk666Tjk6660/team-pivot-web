import type { Me } from "../api";

export function UserBar({ me, onLogout }: { me: Me; onLogout: () => void }) {
  return (
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
        <div style={{ fontSize: 12, color: "#666" }}>
          {me.pinyin}
          {me.github_username ? ` · @${me.github_username}` : ""}
        </div>
      </div>
      <button onClick={onLogout} style={{ marginLeft: "auto" }}>
        Sign out
      </button>
    </div>
  );
}
