import { useEffect, useRef, useState } from "react";
import { searchContacts, type Contact, type MentionBlock } from "../api";

const COMMENTS_REQUIRED_MIN = 1;

export function MentionField({
  value,
  onChange,
  resolvedNames,
}: {
  value: MentionBlock;
  onChange: (v: MentionBlock) => void;
  resolvedNames?: Record<string, string>;
}) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<Contact[]>([]);
  const [loading, setLoading] = useState(false);
  const [focused, setFocused] = useState(false);
  const debounceRef = useRef<number | null>(null);

  useEffect(() => {
    if (debounceRef.current) window.clearTimeout(debounceRef.current);
    if (!focused) return;
    debounceRef.current = window.setTimeout(async () => {
      setLoading(true);
      try {
        const items = await searchContacts(query);
        setResults(items);
      } catch {
        setResults([]);
      } finally {
        setLoading(false);
      }
    }, 250);
    return () => {
      if (debounceRef.current) window.clearTimeout(debounceRef.current);
    };
  }, [query, focused]);

  const add = (c: Contact) => {
    if (value.open_ids.includes(c.open_id)) return;
    onChange({ ...value, open_ids: [...value.open_ids, c.open_id] });
    if (resolvedNames) resolvedNames[c.open_id] = c.name;
    setQuery("");
  };

  const remove = (oid: string) => {
    onChange({ ...value, open_ids: value.open_ids.filter((x) => x !== oid) });
  };

  const names = resolvedNames ?? {};

  return (
    <div
      style={{
        border: "1px solid #ddd",
        borderRadius: 6,
        padding: 10,
        background: "#fafbfc",
      }}
    >
      <div style={{ fontWeight: 600, fontSize: 13, marginBottom: 6 }}>
        圈人（@mention）
      </div>
      <div
        style={{
          display: "flex",
          flexWrap: "wrap",
          gap: 6,
          alignItems: "center",
          padding: 6,
          background: "white",
          border: "1px solid #e0e0e0",
          borderRadius: 4,
          minHeight: 34,
        }}
      >
        {value.open_ids.map((oid) => (
          <span
            key={oid}
            style={{
              background: "#e7efff",
              color: "#1650a7",
              borderRadius: 3,
              padding: "2px 8px",
              fontSize: 12,
              display: "inline-flex",
              alignItems: "center",
              gap: 4,
            }}
          >
            @{names[oid] ?? oid.slice(0, 8)}
            <button
              type="button"
              onClick={() => remove(oid)}
              style={{
                border: "none",
                background: "transparent",
                cursor: "pointer",
                color: "inherit",
                padding: 0,
                fontSize: 13,
                lineHeight: 1,
              }}
            >
              ×
            </button>
          </span>
        ))}
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onFocus={() => setFocused(true)}
          onBlur={() => window.setTimeout(() => setFocused(false), 200)}
          placeholder={value.open_ids.length === 0 ? "搜索名字加人…" : "继续加人…"}
          style={{
            flex: 1,
            minWidth: 140,
            border: "none",
            outline: "none",
            fontSize: 13,
            background: "transparent",
          }}
        />
      </div>

      {focused && (
        <div
          style={{
            marginTop: 4,
            background: "white",
            border: "1px solid #ddd",
            borderRadius: 4,
            maxHeight: 220,
            overflow: "auto",
            boxShadow: "0 2px 8px rgba(0,0,0,0.08)",
          }}
        >
          {loading && (
            <div style={{ padding: 10, fontSize: 12, color: "#888" }}>搜索中…</div>
          )}
          {!loading && results.length === 0 && (
            <div style={{ padding: 10, fontSize: 12, color: "#888" }}>
              没有匹配项。可以尝试点击上方的"同步联系人"按钮。
            </div>
          )}
          {!loading &&
            results.map((c) => (
              <button
                key={c.open_id}
                type="button"
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => add(c)}
                disabled={value.open_ids.includes(c.open_id)}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 8,
                  width: "100%",
                  padding: "6px 10px",
                  border: "none",
                  background: value.open_ids.includes(c.open_id) ? "#f5f5f5" : "white",
                  textAlign: "left",
                  cursor: "pointer",
                  fontSize: 13,
                }}
              >
                {c.avatar_url && (
                  <img
                    src={c.avatar_url}
                    alt=""
                    width={20}
                    height={20}
                    style={{ borderRadius: "50%" }}
                  />
                )}
                <span>{c.name}</span>
                {c.en_name && (
                  <span style={{ color: "#888", fontSize: 11 }}>({c.en_name})</span>
                )}
              </button>
            ))}
        </div>
      )}

      <div style={{ marginTop: 10 }}>
        <div style={{ fontWeight: 600, fontSize: 12, marginBottom: 4 }}>
          想跟他们说一句话（必填）
        </div>
        <input
          value={value.comments}
          onChange={(e) => onChange({ ...value, comments: e.target.value })}
          maxLength={500}
          placeholder="这个方案希望你们 review"
          style={{
            width: "100%",
            padding: 8,
            fontSize: 13,
            border: "1px solid #e0e0e0",
            borderRadius: 4,
            boxSizing: "border-box",
          }}
        />
      </div>
    </div>
  );
}

export function isMentionValid(m: MentionBlock): boolean {
  if (m.open_ids.length === 0) return true;
  return m.comments.trim().length >= COMMENTS_REQUIRED_MIN;
}

export function emptyMention(): MentionBlock {
  return { open_ids: [], comments: "" };
}
