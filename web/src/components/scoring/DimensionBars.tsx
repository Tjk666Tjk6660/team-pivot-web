import type { ScoringDimensions } from "@/api";

const DIM_LABELS: Record<keyof ScoringDimensions, string> = {
  delivery: "交付质量",
  accountability: "责任闭环",
  judgment: "判断质量",
  collaboration: "协作贡献",
  process: "过程规范",
};

const DIM_ORDER: (keyof ScoringDimensions)[] = [
  "delivery",
  "accountability",
  "judgment",
  "collaboration",
  "process",
];

export function DimensionBars({
  dimensions,
  evidenceCounts,
}: {
  dimensions: ScoringDimensions;
  evidenceCounts?: Partial<Record<keyof ScoringDimensions, number>>;
}) {
  return (
    <div className="space-y-1.5">
      {DIM_ORDER.map((dim) => {
        const score = dimensions[dim];
        const count = evidenceCounts?.[dim] ?? 0;
        return (
          <DimensionBarRow
            key={dim}
            label={DIM_LABELS[dim]}
            dim={dim}
            score={score}
            evidenceCount={count}
          />
        );
      })}
    </div>
  );
}

function DimensionBarRow({
  label,
  dim,
  score,
  evidenceCount,
}: {
  label: string;
  dim: string;
  score: number | null;
  evidenceCount: number;
}) {
  const pct = score === null ? 0 : (score / 5) * 100;
  return (
    <div className="grid grid-cols-[100px_minmax(0,1fr)_60px] items-center gap-2 text-xs">
      <div className="truncate">
        <span className="font-medium">{label}</span>
        <span className="ml-1 text-[10px] text-[var(--text-mute)]">{dim}</span>
      </div>
      <div className="relative h-2 rounded-full bg-[var(--surface-alt)] overflow-hidden">
        {score !== null && (
          <div
            className="absolute inset-y-0 left-0 rounded-full"
            style={{
              width: `${pct}%`,
              background: barColor(score),
            }}
          />
        )}
      </div>
      <div className="text-right tabular-nums">
        {score === null ? (
          <span
            className="text-[var(--text-mute)] italic text-[11px]"
            title="证据不足，未评分"
          >
            —
          </span>
        ) : (
          <>
            <span className="font-semibold">{score.toFixed(1)}</span>
            {evidenceCount > 0 && (
              <span className="ml-1 text-[10px] text-[var(--text-mute)]">
                ·{evidenceCount}
              </span>
            )}
          </>
        )}
      </div>
    </div>
  );
}

function barColor(score: number): string {
  if (score >= 4.5) return "var(--ok-600)";
  if (score >= 3.5) return "var(--accent)";
  if (score >= 2.5) return "var(--text-mute)";
  return "var(--warn-600)";
}
