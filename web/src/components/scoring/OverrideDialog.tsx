import { useState } from "react";
import { toast } from "sonner";
import {
  AdminRequiredError,
  overrideScoringScore,
  type ScoringScorePayload,
} from "@/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

type Props = {
  runId: string;
  currentOverall: number;
  currentOverride: { overall: number | null; note: string | null } | null;
  subjectDisplay: string | null;
  onClose: () => void;
  onSaved: (updated: ScoringScorePayload) => void;
  onAdminLost: () => void;
};

export function OverrideDialog({
  runId,
  currentOverall,
  currentOverride,
  subjectDisplay,
  onClose,
  onSaved,
  onAdminLost,
}: Props) {
  const hasPrior = currentOverride?.overall !== null && currentOverride !== null;
  const [overall, setOverall] = useState<number>(
    hasPrior ? (currentOverride!.overall as number) : currentOverall,
  );
  const [note, setNote] = useState<string>(
    hasPrior ? currentOverride!.note ?? "" : "",
  );
  const [saving, setSaving] = useState(false);

  const submit = async () => {
    if (overall < 1.0 || overall > 5.0) {
      toast.error("分数必须在 1.0 - 5.0 之间");
      return;
    }
    if (!note.trim()) {
      toast.error("请填写修正原因");
      return;
    }
    setSaving(true);
    try {
      const updated = await overrideScoringScore(runId, {
        overall,
        note: note.trim(),
      });
      toast.success(hasPrior ? "已更新人工修正" : "已应用人工修正");
      onSaved(updated);
    } catch (e) {
      if (e instanceof AdminRequiredError) {
        onAdminLost();
      } else {
        toast.error(e instanceof Error ? e.message : String(e));
      }
    } finally {
      setSaving(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-[60] flex items-center justify-center bg-black/40 p-4"
      onClick={onClose}
    >
      <div
        className="w-full max-w-md rounded-[var(--r-md)] bg-[var(--surface)] shadow-[var(--shadow-lg)]"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="border-b border-[var(--line)] px-5 py-3">
          <h3 className="text-base font-semibold">
            {hasPrior ? "更新人工修正" : "人工修正"}
          </h3>
          <p className="mt-0.5 text-xs text-[var(--text-mute)]">
            修正 {subjectDisplay ?? "(未知)"} 的总分（不动 AI 原始打分；
            列表 / 抽屉里以人工修正为准）
          </p>
        </div>

        <div className="space-y-4 px-5 py-4">
          <div className="rounded bg-[var(--surface-alt)] px-3 py-2 text-xs text-[var(--text-mute)]">
            AI 原始总分: <span className="font-semibold tabular-nums text-[var(--text)]">
              {currentOverall.toFixed(1)}
            </span>{" "}
            / 5
            {hasPrior && (
              <>
                {" · "}已有修正:{" "}
                <span className="font-semibold tabular-nums text-[var(--text)]">
                  {currentOverride!.overall!.toFixed(1)}
                </span>
              </>
            )}
          </div>

          <div className="space-y-2">
            <Label htmlFor="override-overall">修正后总分</Label>
            <Input
              id="override-overall"
              type="number"
              min={1.0}
              max={5.0}
              step={0.1}
              value={overall}
              onChange={(e) => setOverall(Number(e.target.value) || currentOverall)}
            />
            <p className="text-xs text-[var(--text-mute)]">
              范围 1.0 - 5.0，每 0.1 分一档
            </p>
          </div>

          <div className="space-y-2">
            <Label htmlFor="override-note">修正原因（必填）</Label>
            <textarea
              id="override-note"
              className="flex min-h-[80px] w-full rounded-[var(--r-sm)] border border-[var(--line-strong)] bg-[var(--surface)] px-3 py-2 text-sm"
              placeholder="例：AI 没看到客户的负面反馈，扣 0.5"
              value={note}
              onChange={(e) => setNote(e.target.value)}
              maxLength={500}
            />
            <p className="text-xs text-[var(--text-mute)]">
              留下原因方便后续审计 / 同事理解为什么和 AI 不同
            </p>
          </div>
        </div>

        <div className="flex justify-end gap-2 border-t border-[var(--line)] px-5 py-3">
          <Button variant="outline" onClick={onClose}>
            取消
          </Button>
          <Button onClick={submit} disabled={saving}>
            {saving ? "保存中…" : hasPrior ? "更新" : "应用"}
          </Button>
        </div>
      </div>
    </div>
  );
}
