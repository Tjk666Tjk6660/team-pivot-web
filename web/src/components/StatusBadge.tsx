type Tone = "discussing" | "concluded" | "project" | "archived" | "paused";

const LABELS: Record<string, { text: string; tone: Tone; short: string }> = {
  open:      { text: "讨论中",     tone: "discussing", short: "讨论" },
  concluded: { text: "已达成结论", tone: "concluded",  short: "结论" },
  produced:  { text: "已转为项目", tone: "project",    short: "项目" },
  closed:    { text: "已关闭",     tone: "archived",   short: "归档" },
  pending:   { text: "暂时搁置",   tone: "paused",     short: "搁置" },
};

export function StatusBadge({
  status,
  size = "md",
}: {
  status: string | null;
  size?: "sm" | "md";
}) {
  if (!status) return null;
  const s = LABELS[status];
  const label = s?.text ?? status;
  const tone = s?.tone ?? "archived";
  const padding = size === "sm" ? "px-1.5 py-[1px] text-[10.5px]" : "px-2.5 py-[3px] text-[11.5px]";

  return (
    <span
      className={`inline-flex shrink-0 items-center gap-1 rounded-[var(--r-xs)] font-semibold uppercase tracking-[0.04em] font-meta whitespace-nowrap ${padding}`}
      style={{
        background: `var(--status-${tone}-bg)`,
        color: `var(--status-${tone}-fg)`,
      }}
    >
      <span
        aria-hidden
        className="h-1.5 w-1.5 shrink-0 rounded-full"
        style={{ background: "currentColor" }}
      />
      {label}
    </span>
  );
}

export const STATUS_LABELS = LABELS;
