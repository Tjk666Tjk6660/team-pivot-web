import { useState } from "react";
import { updateProfile, type Me } from "../api";

export function ProfileSetup({ me, onDone }: { me: Me; onDone: (m: Me) => void }) {
  const [pinyin, setPinyin] = useState("");
  const [github, setGithub] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const updated = await updateProfile({
        pinyin: pinyin.trim(),
        github_username: github.trim() || null,
      });
      onDone(updated);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div style={{ padding: 48, maxWidth: 480, fontFamily: "system-ui, sans-serif" }}>
      <h1>Welcome, {me.name}</h1>
      <p style={{ color: "#666" }}>
        One-time setup. This info is used as your git author name and branch prefix.
      </p>
      <form onSubmit={submit} style={{ display: "flex", flexDirection: "column", gap: 16 }}>
        <label>
          <div style={{ fontWeight: 600, marginBottom: 4 }}>Pinyin name *</div>
          <input
            value={pinyin}
            onChange={(e) => setPinyin(e.target.value)}
            required
            placeholder="e.g. dengke or keller.koh"
            style={{ width: "100%", padding: 8, fontSize: 14 }}
          />
          <div style={{ fontSize: 12, color: "#888", marginTop: 4 }}>
            Lowercase letters, digits, <code>. _ -</code> only. Must start with a letter.
          </div>
        </label>
        <label>
          <div style={{ fontWeight: 600, marginBottom: 4 }}>GitHub username (optional)</div>
          <input
            value={github}
            onChange={(e) => setGithub(e.target.value)}
            placeholder="your-github-handle"
            style={{ width: "100%", padding: 8, fontSize: 14 }}
          />
        </label>
        {error && <div style={{ color: "#c00" }}>{error}</div>}
        <button
          type="submit"
          disabled={submitting || !pinyin.trim()}
          style={{
            padding: "10px 20px",
            background: "#3370ff",
            color: "white",
            border: "none",
            borderRadius: 6,
            cursor: "pointer",
          }}
        >
          {submitting ? "Saving…" : "Continue"}
        </button>
      </form>
    </div>
  );
}
