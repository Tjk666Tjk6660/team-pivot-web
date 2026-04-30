type Confidence = "low" | "medium" | "high";

const PALETTE: Record<Confidence, { bg: string; fg: string; dot: string; label: string }> = {
  high: { bg: "var(--ok-bg)", fg: "var(--ok-600)", dot: "🟢", label: "high" },
  medium: { bg: "var(--accent-bg)", fg: "var(--accent)", dot: "🟡", label: "medium" },
  low: { bg: "var(--warn-bg)", fg: "var(--warn-600)", dot: "🔴", label: "low" },
};

export function ScoreConfidenceBadge({
  confidence,
  size = "md",
}: {
  confidence: Confidence | string;
  size?: "sm" | "md";
}) {
  const c = PALETTE[(confidence as Confidence)] ?? {
    bg: "var(--surface-alt)",
    fg: "var(--text-mute)",
    dot: "·",
    label: confidence,
  };
  const padding = size === "sm" ? "px-1.5 py-0" : "px-2 py-0.5";
  const text = size === "sm" ? "text-[10px]" : "text-xs";
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full ${padding} ${text} font-medium`}
      style={{ background: c.bg, color: c.fg }}
    >
      <span aria-hidden>{c.dot}</span>
      <span>{c.label}</span>
    </span>
  );
}
