const LABELS: Record<string, { text: string; color: string; bg: string }> = {
  open: { text: "讨论中", color: "#1650a7", bg: "#e7efff" },
  concluded: { text: "已达成结论", color: "#0f7a3b", bg: "#e3f6ea" },
  produced: { text: "已转为项目", color: "#5b2f9f", bg: "#efe6ff" },
  closed: { text: "已关闭", color: "#666", bg: "#eee" },
  pending: { text: "暂时搁置", color: "#8a5a00", bg: "#fff1cc" },
};

export function StatusBadge({ status }: { status: string | null }) {
  if (!status) return null;
  const s = LABELS[status] ?? { text: status, color: "#333", bg: "#f0f0f0" };
  return (
    <span
      style={{
        display: "inline-block",
        fontSize: 11,
        padding: "2px 8px",
        borderRadius: 10,
        color: s.color,
        background: s.bg,
        fontWeight: 500,
      }}
    >
      {s.text}
    </span>
  );
}
