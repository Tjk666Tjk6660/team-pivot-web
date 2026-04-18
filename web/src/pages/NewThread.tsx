import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { createThread, type Me } from "../api";
import { UserBar } from "../components/UserBar";

export function NewThread({ me, onLogout }: { me: Me; onLogout: () => void }) {
  const navigate = useNavigate();
  const [category, setCategory] = useState("general");
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      const r = await createThread({ category: category.trim(), title: title.trim(), body });
      navigate(`/t/${encodeURIComponent(r.category)}/${encodeURIComponent(r.slug)}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div style={{ padding: 48, maxWidth: 820, fontFamily: "system-ui, sans-serif" }}>
      <UserBar me={me} onLogout={onLogout} />
      <div style={{ marginTop: 24 }}>
        <Link to="/" style={{ fontSize: 13, color: "#666" }}>
          ← Back to discussions
        </Link>
      </div>
      <h1 style={{ marginTop: 24 }}>New discussion</h1>
      <form
        onSubmit={submit}
        style={{ display: "flex", flexDirection: "column", gap: 16, marginTop: 16 }}
      >
        <label>
          <div style={{ fontWeight: 600, marginBottom: 4 }}>Category</div>
          <input
            value={category}
            onChange={(e) => setCategory(e.target.value)}
            required
            pattern="^[a-zA-Z0-9_-]{1,40}$"
            style={{ width: "100%", padding: 8, fontSize: 14 }}
          />
          <div style={{ fontSize: 12, color: "#888", marginTop: 4 }}>
            ASCII letters, digits, <code>- _</code>. Max 40 chars.
          </div>
        </label>
        <label>
          <div style={{ fontWeight: 600, marginBottom: 4 }}>Title</div>
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            required
            maxLength={200}
            style={{ width: "100%", padding: 8, fontSize: 14 }}
          />
        </label>
        <label>
          <div style={{ fontWeight: 600, marginBottom: 4 }}>Body (markdown)</div>
          <textarea
            value={body}
            onChange={(e) => setBody(e.target.value)}
            required
            rows={16}
            maxLength={50000}
            style={{
              width: "100%",
              padding: 8,
              fontSize: 14,
              fontFamily: "ui-monospace, SFMono-Regular, monospace",
            }}
          />
          <div style={{ fontSize: 12, color: "#888", marginTop: 4 }}>
            Title is auto-prepended as <code># heading</code> if you don't include one.
          </div>
        </label>
        {error && <div style={{ color: "#c00" }}>{error}</div>}
        <div>
          <button
            type="submit"
            disabled={submitting || !title.trim() || !body.trim()}
            style={{
              padding: "10px 20px",
              background: "#3370ff",
              color: "white",
              border: "none",
              borderRadius: 6,
              cursor: "pointer",
            }}
          >
            {submitting ? "Publishing…" : "Publish"}
          </button>
        </div>
      </form>
    </div>
  );
}
