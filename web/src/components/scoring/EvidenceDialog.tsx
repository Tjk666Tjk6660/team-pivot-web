import { useState } from "react";
import { ChevronDown, ChevronRight, ExternalLink } from "lucide-react";
import { Link } from "react-router-dom";
import type { ScoringDimensions, ScoringEvidenceItem } from "@/api";
import { ScoreConfidenceBadge } from "./ScoreConfidenceBadge";

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

const POLARITY_GLYPH: Record<string, { icon: string; color: string }> = {
  positive: { icon: "✅", color: "var(--ok-600)" },
  negative: { icon: "⚠️", color: "var(--warn-600)" },
  neutral: { icon: "·", color: "var(--text-mute)" },
};

type Props = {
  matterId: string;
  matterTitle: string | null;
  subjectDisplay: string | null;
  overall: number;
  confidence: string;
  rationale: string;
  dimensions: ScoringDimensions;
  evidence: ScoringEvidenceItem[];
  onClose: () => void;
};

export function EvidenceDialog({
  matterId,
  matterTitle,
  subjectDisplay,
  overall,
  confidence,
  rationale,
  dimensions,
  evidence,
  onClose,
}: Props) {
  const byDim: Record<string, ScoringEvidenceItem[]> = {};
  for (const e of evidence) {
    (byDim[e.dimension] ||= []).push(e);
  }

  return (
    <div
      className="fixed inset-0 z-[60] flex items-center justify-center bg-black/40 p-4"
      onClick={onClose}
    >
      <div
        className="w-full max-w-2xl max-h-[85vh] overflow-hidden rounded-[var(--r-md)] bg-[var(--surface)] shadow-[var(--shadow-lg)] flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between border-b border-[var(--line)] px-5 py-3">
          <div>
            <div className="flex items-center gap-3">
              <h3 className="text-base font-semibold">
                {subjectDisplay ?? "(未知用户)"} 的评分证据
              </h3>
              <ScoreConfidenceBadge confidence={confidence} />
            </div>
            <p className="mt-0.5 text-xs text-[var(--text-mute)]">
              {matterTitle ?? matterId} · 总分{" "}
              <span className="font-semibold tabular-nums text-[var(--text)]">
                {overall.toFixed(1)} / 5
              </span>
            </p>
          </div>
          <button
            type="button"
            aria-label="关闭"
            className="rounded p-1 text-[var(--text-mute)] hover:bg-[var(--surface-alt)] hover:text-[var(--text)]"
            onClick={onClose}
          >
            ✕
          </button>
        </div>

        {rationale && (
          <div className="border-b border-[var(--line)] px-5 py-3 text-sm">
            "<span className="text-[var(--text-soft)]">{rationale}</span>"
          </div>
        )}

        <div className="flex-1 overflow-y-auto px-5 py-3 space-y-3">
          {DIM_ORDER.map((dim) => {
            const dimEvidence = byDim[dim] || [];
            const score = dimensions[dim];
            return (
              <DimensionGroup
                key={dim}
                label={DIM_LABELS[dim]}
                dim={dim}
                score={score}
                evidence={dimEvidence}
                matterId={matterId}
                onClose={onClose}
              />
            );
          })}
        </div>

        <div className="flex justify-end border-t border-[var(--line)] px-5 py-3">
          <button
            type="button"
            className="rounded px-3 py-1 text-sm hover:bg-[var(--surface-alt)]"
            onClick={onClose}
          >
            关闭
          </button>
        </div>
      </div>
    </div>
  );
}

function DimensionGroup({
  label,
  dim,
  score,
  evidence,
  matterId,
  onClose,
}: {
  label: string;
  dim: string;
  score: number | null;
  evidence: ScoringEvidenceItem[];
  matterId: string;
  onClose: () => void;
}) {
  const [open, setOpen] = useState(true);
  const isUnscored = score === null;

  return (
    <div className="rounded-[var(--r-sm)] border border-[var(--line)]">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-2 px-3 py-2 text-left hover:bg-[var(--surface-alt)]"
      >
        {open ? (
          <ChevronDown className="h-3.5 w-3.5" />
        ) : (
          <ChevronRight className="h-3.5 w-3.5" />
        )}
        <span className="font-semibold text-sm">{label}</span>
        <span className="text-[10px] text-[var(--text-mute)]">{dim}</span>
        <span className="ml-auto text-sm tabular-nums">
          {isUnscored ? (
            <span className="italic text-[var(--text-mute)]">
              — 证据不足，不评分
            </span>
          ) : (
            <>
              <span className="font-semibold">{score!.toFixed(1)}</span>
              <span className="ml-2 text-xs text-[var(--text-mute)]">
                · {evidence.length} 条证据
              </span>
            </>
          )}
        </span>
      </button>
      {open && evidence.length > 0 && (
        <div className="space-y-2 border-t border-[var(--line)] px-3 py-2">
          {evidence.map((e) => (
            <EvidenceCard
              key={e.id}
              ev={e}
              matterId={matterId}
              onJump={onClose}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function EvidenceCard({
  ev,
  matterId,
  onJump,
}: {
  ev: ScoringEvidenceItem;
  matterId: string;
  onJump: () => void;
}) {
  const polarity = POLARITY_GLYPH[ev.polarity] ?? { icon: "·", color: "var(--text-mute)" };
  const isComment = ev.source_kind === "comment";
  const isHighWeight = ev.weight_applied !== 1.0;

  // Build a link to the matter detail with #file=<basename> hash.
  const jumpUrl = `/m/${encodeURIComponent(matterId)}#file=${encodeURIComponent(ev.source_filename)}`;

  return (
    <div className="rounded border border-[var(--line)] bg-[var(--surface-alt)] px-3 py-2 text-xs space-y-1.5">
      <div className="flex flex-wrap items-center gap-2">
        <span style={{ color: polarity.color }}>
          {polarity.icon} {ev.polarity}
        </span>
        <ScoreConfidenceBadge confidence={ev.confidence} size="sm" />
        {isHighWeight && (
          <span className="rounded bg-[var(--accent-bg)] px-1.5 text-[10px] font-medium text-[var(--accent)]">
            weight {ev.weight_applied.toFixed(1)}x
          </span>
        )}
        <span className="text-[var(--text-mute)]">
          {isComment ? "评论" : ev.source_file_type + " 文件"}
        </span>
      </div>
      <div className="font-mono text-[10.5px] text-[var(--text-mute)] truncate">
        {ev.source_filename}
        {isComment && ev.source_comment_author_display && (
          <span className="ml-2">
            · 作者 {ev.source_comment_author_display}
          </span>
        )}
        {isComment && ev.source_comment_created_at && (
          <span className="ml-2">· {ev.source_comment_created_at}</span>
        )}
      </div>
      <div className="rounded bg-[var(--surface)] px-2 py-1 text-[var(--text)] italic">
        "{ev.quote}"
      </div>
      <div className="flex items-start gap-1 text-[var(--text-soft)]">
        <span aria-hidden>🤖</span>
        <span>{ev.explanation}</span>
      </div>
      <div className="flex justify-end">
        <Link
          to={jumpUrl}
          onClick={onJump}
          className="inline-flex items-center gap-1 text-[var(--accent)] hover:underline"
        >
          跳到 timeline
          <ExternalLink className="h-3 w-3" />
        </Link>
      </div>
    </div>
  );
}
