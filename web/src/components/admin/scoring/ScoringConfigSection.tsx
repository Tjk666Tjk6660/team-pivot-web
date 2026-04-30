import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowRight, Award, Pencil, Plus, RotateCw, Trash2, Users2 } from "lucide-react";
import { toast } from "sonner";
import {
  AdminRequiredError,
  deleteCommenterWeight,
  fetchScoringConfig,
  fetchScoringRuns,
  listCommenterWeights,
  triggerScoringRerun,
  updateScoringConfig,
  type CommenterWeight,
  type ScoringConfig,
  type ScoringRunSummary,
} from "@/api";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

import { AddCommenterWeightDialog } from "./AddCommenterWeightDialog";

const SUGGESTED_MODELS = [
  "",
  "anthropic/claude-sonnet-4-5",
  "anthropic/claude-haiku-4-5",
  "openai/gpt-4o-mini",
];

const RECENT_RUNS_LIMIT = 5;

type Props = {
  onAdminLost: () => void;
};

export function ScoringConfigSection({ onAdminLost }: Props) {
  const [config, setConfig] = useState<ScoringConfig | null>(null);
  const [weights, setWeights] = useState<CommenterWeight[]>([]);
  const [recentRuns, setRecentRuns] = useState<ScoringRunSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [addDialogOpen, setAddDialogOpen] = useState(false);
  const [editingWeight, setEditingWeight] = useState<CommenterWeight | null>(null);

  const loadAll = async () => {
    try {
      const [cfg, w, runs] = await Promise.all([
        fetchScoringConfig(),
        listCommenterWeights(),
        fetchScoringRuns({ limit: RECENT_RUNS_LIMIT }),
      ]);
      setConfig(cfg);
      setWeights(w.items);
      setRecentRuns(runs.items);
    } catch (e) {
      if (e instanceof AdminRequiredError) {
        toast.error("管理员密码已失效，请重新输入");
        onAdminLost();
      } else {
        toast.error(e instanceof Error ? e.message : String(e));
      }
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadAll();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const save = async () => {
    if (!config) return;
    setSaving(true);
    try {
      await updateScoringConfig(config);
      toast.success("评分配置已保存");
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

  const update = (patch: Partial<ScoringConfig>) => {
    if (!config) return;
    setConfig({ ...config, ...patch });
  };

  const onWeightDeleted = async (userId: string) => {
    try {
      await deleteCommenterWeight(userId);
      toast.success("已移除");
      setWeights((prev) => prev.filter((w) => w.pivot_user_id !== userId));
    } catch (e) {
      if (e instanceof AdminRequiredError) {
        onAdminLost();
      } else {
        toast.error(e instanceof Error ? e.message : String(e));
      }
    }
  };

  const onRerun = async (matterId: string) => {
    try {
      const r = await triggerScoringRerun(matterId);
      toast.success(r.message);
      // Refresh recent runs after a moment
      setTimeout(() => {
        fetchScoringRuns({ limit: RECENT_RUNS_LIMIT })
          .then((res) => setRecentRuns(res.items))
          .catch(() => {});
      }, 800);
    } catch (e) {
      if (e instanceof AdminRequiredError) {
        onAdminLost();
      } else {
        toast.error(e instanceof Error ? e.message : String(e));
      }
    }
  };

  return (
    <section>
      <Card className="shadow-[var(--shadow-sm)]">
        <CardHeader className="pb-4">
          <CardTitle className="flex items-center gap-2 text-base">
            <Award className="h-4 w-4" />
            Matter 评分配置
          </CardTitle>
          <CardDescription>
            Matter 进入 finished 后由 AI 基于时间线生成 owner 评分。v1 仅 admin 可见。
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-6">
          {loading || !config ? (
            <p className="text-sm text-muted-foreground">加载中…</p>
          ) : (
            <>
              {/* Toggle + visibility */}
              <div className="space-y-4">
                <ToggleRow
                  label="评分功能总开关"
                  checked={config.enabled}
                  onChange={(v) => update({ enabled: v })}
                  hint="关闭后 finished 不再触发评分（已生成的不删除）"
                />

                <div className="rounded-[var(--r-md)] border border-[var(--line)] bg-[var(--surface)] p-3 space-y-2">
                  <Label className="text-sm font-semibold">评分结果可见范围</Label>
                  <div className="space-y-1.5 text-sm">
                    <RadioRow
                      checked={config.visibility === "admin_only"}
                      onCheck={() => update({ visibility: "admin_only" })}
                      label="仅管理员（v1 默认）"
                    />
                    <RadioRow
                      checked={config.visibility === "subjects"}
                      onCheck={() => update({ visibility: "subjects" })}
                      label="仅本人和管理员"
                      disabled
                      hint="v1 暂不开放"
                    />
                    <RadioRow
                      checked={config.visibility === "all"}
                      onCheck={() => update({ visibility: "all" })}
                      label="全员可见"
                      disabled
                      hint="v1 暂不开放"
                    />
                  </div>
                </div>
              </div>

              {/* Model + timeout */}
              <div className="grid gap-3 md:grid-cols-2">
                <div className="space-y-2">
                  <Label htmlFor="scoring-model">评分模型（覆盖默认）</Label>
                  <Input
                    id="scoring-model"
                    placeholder="留空 = 使用主 AI 模型"
                    value={config.model}
                    onChange={(e) => update({ model: e.target.value })}
                  />
                  <div className="flex flex-wrap gap-1.5">
                    {SUGGESTED_MODELS.map((m) => (
                      <button
                        key={m || "(default)"}
                        type="button"
                        onClick={() => update({ model: m })}
                        className={`rounded px-2 py-0.5 text-xs transition-colors ${
                          config.model === m
                            ? "bg-[var(--accent-bg)] text-[var(--accent)]"
                            : "bg-[var(--surface-alt)] text-[var(--text-mute)] hover:bg-[var(--accent-bg)]"
                        }`}
                      >
                        {m || "（继承主 AI）"}
                      </button>
                    ))}
                  </div>
                </div>
                <div className="space-y-2">
                  <Label htmlFor="scoring-timeout">单次超时（秒）</Label>
                  <Input
                    id="scoring-timeout"
                    type="number"
                    min={1}
                    max={600}
                    value={config.timeout_seconds}
                    onChange={(e) =>
                      update({ timeout_seconds: Number(e.target.value) || 120 })
                    }
                  />
                  <p className="text-xs text-muted-foreground">
                    AI 调用超时后 run 标 failed
                  </p>
                </div>
              </div>

              {/* Save button */}
              <div className="flex justify-end border-t pt-4">
                <Button onClick={save} disabled={saving}>
                  {saving ? "保存中…" : "保存配置"}
                </Button>
              </div>

              {/* Commenter weights */}
              <div className="space-y-3 rounded-[var(--r-md)] border border-[var(--line)] bg-[var(--surface-alt)] p-4">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2 text-sm font-semibold">
                    <Users2 className="h-4 w-4" />
                    高权重发言人
                  </div>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => {
                      setEditingWeight(null);
                      setAddDialogOpen(true);
                    }}
                  >
                    <Plus className="mr-1 h-3.5 w-3.5" />
                    添加
                  </Button>
                </div>
                <p className="text-xs text-muted-foreground">
                  这些人的评论会被 AI 视为更强的信号（影响 confidence + 微调分数 ±0.5）
                </p>
                {weights.length === 0 ? (
                  <p className="text-xs text-muted-foreground italic">
                    （未配置；不在表里的人默认权重 1.0）
                  </p>
                ) : (
                  <ul className="space-y-1.5">
                    {weights.map((w) => (
                      <li
                        key={w.pivot_user_id}
                        className="flex items-center gap-3 rounded border border-[var(--line)] bg-[var(--surface)] px-3 py-2 text-sm"
                      >
                        {w.user_avatar_url ? (
                          <img
                            src={w.user_avatar_url}
                            alt=""
                            className="h-6 w-6 rounded-full"
                          />
                        ) : (
                          <span className="h-6 w-6 rounded-full bg-[var(--surface-alt)]" />
                        )}
                        <span className="min-w-0 flex-1 truncate">
                          <span className="font-medium">
                            {w.user_display ?? "(已删除)"}
                          </span>
                          {w.user_pinyin && (
                            <span className="ml-2 text-xs text-[var(--text-mute)]">
                              {w.user_pinyin}
                            </span>
                          )}
                        </span>
                        <span className="rounded bg-[var(--accent-bg)] px-2 py-0.5 text-xs font-medium text-[var(--accent)]">
                          {w.label}
                        </span>
                        <span className="text-sm font-semibold tabular-nums">
                          {formatWeight(w.weight)}x
                        </span>
                        <button
                          type="button"
                          aria-label="编辑"
                          className="rounded p-1 text-[var(--text-mute)] hover:bg-[var(--surface-alt)] hover:text-[var(--text)]"
                          onClick={() => {
                            setEditingWeight(w);
                            setAddDialogOpen(true);
                          }}
                        >
                          <Pencil className="h-3.5 w-3.5" />
                        </button>
                        <button
                          type="button"
                          aria-label="删除"
                          className="rounded p-1 text-[var(--text-mute)] hover:bg-[var(--warn-bg)] hover:text-[var(--warn-600)]"
                          onClick={() => onWeightDeleted(w.pivot_user_id)}
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </div>

              {/* Recent runs */}
              <div className="space-y-2 rounded-[var(--r-md)] border border-[var(--line)] bg-[var(--surface-alt)] p-4">
                <div className="flex items-center justify-between">
                  <div className="text-sm font-semibold">
                    最近 {RECENT_RUNS_LIMIT} 次评分任务
                  </div>
                  <Link
                    to="/admin/scoring"
                    className="inline-flex items-center gap-1 text-xs text-[var(--accent)] hover:underline"
                  >
                    前往评分管理
                    <ArrowRight className="h-3 w-3" />
                  </Link>
                </div>
                {recentRuns.length === 0 ? (
                  <p className="text-xs italic text-muted-foreground">
                    （还没有评分任务；启用后 finished 的 matter 会自动入队）
                  </p>
                ) : (
                  <ul className="space-y-1">
                    {recentRuns.map((r) => (
                      <RunRow
                        key={r.run_id}
                        run={r}
                        onRerun={() => onRerun(r.matter_id)}
                      />
                    ))}
                  </ul>
                )}
              </div>
            </>
          )}
        </CardContent>
      </Card>

      {addDialogOpen && (
        <AddCommenterWeightDialog
          editing={editingWeight}
          onClose={() => setAddDialogOpen(false)}
          onSaved={(w) => {
            setWeights((prev) => {
              const without = prev.filter(
                (x) => x.pivot_user_id !== w.pivot_user_id,
              );
              return [...without, w].sort((a, b) => b.weight - a.weight);
            });
            setAddDialogOpen(false);
          }}
          onAdminLost={onAdminLost}
        />
      )}
    </section>
  );
}

// ─────────────────────────────────────────────────────────────────────────────

function ToggleRow({
  label,
  checked,
  onChange,
  hint,
}: {
  label: string;
  checked: boolean;
  onChange: (v: boolean) => void;
  hint?: string;
}) {
  return (
    <label className="flex items-start gap-3 rounded-[var(--r-md)] border border-[var(--line)] bg-[var(--surface)] p-3 cursor-pointer hover:bg-[var(--surface-alt)]">
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="mt-0.5"
      />
      <span className="min-w-0 flex-1">
        <span className="block text-sm font-semibold text-[var(--text)]">
          {label}
        </span>
        {hint && (
          <span className="mt-0.5 block text-xs text-[var(--text-mute)]">
            {hint}
          </span>
        )}
      </span>
    </label>
  );
}

function RadioRow({
  checked,
  onCheck,
  label,
  hint,
  disabled,
}: {
  checked: boolean;
  onCheck: () => void;
  label: string;
  hint?: string;
  disabled?: boolean;
}) {
  return (
    <label
      className={`flex items-center gap-2 ${
        disabled ? "opacity-50 cursor-not-allowed" : "cursor-pointer"
      }`}
    >
      <input
        type="radio"
        checked={checked}
        onChange={() => !disabled && onCheck()}
        disabled={disabled}
      />
      <span>
        {label}
        {hint && (
          <span className="ml-2 text-xs text-[var(--text-mute)]">{hint}</span>
        )}
      </span>
    </label>
  );
}

function RunRow({
  run,
  onRerun,
}: {
  run: ScoringRunSummary;
  onRerun: () => void;
}) {
  const icon = STATUS_ICONS[run.status] ?? "·";
  const statusColor = STATUS_COLORS[run.status] ?? "var(--text-mute)";
  return (
    <li className="flex items-center gap-2 rounded border border-[var(--line)] bg-[var(--surface)] px-3 py-1.5 text-xs">
      <span style={{ color: statusColor }}>{icon}</span>
      <span className="min-w-0 flex-1 truncate">
        <span className="font-medium">
          {run.matter_title ?? run.matter_id}
        </span>
        {run.subject_display && (
          <span className="ml-2 text-[var(--text-mute)]">
            {run.subject_display}
          </span>
        )}
      </span>
      {run.score && (
        <span className="tabular-nums font-semibold">
          {run.score.overall.toFixed(1)} / {run.score.confidence}
        </span>
      )}
      {run.status === "failed" && run.error && (
        <span className="text-[var(--warn-600)] truncate max-w-[140px]">
          {run.error}
        </span>
      )}
      <span className="text-[var(--text-mute)] tabular-nums">
        {formatRunTime(run.started_at)}
      </span>
      {(run.status === "failed" || run.status === "skipped") && (
        <button
          type="button"
          aria-label="重跑"
          className="rounded p-1 text-[var(--text-mute)] hover:bg-[var(--surface-alt)] hover:text-[var(--text)]"
          onClick={onRerun}
        >
          <RotateCw className="h-3 w-3" />
        </button>
      )}
    </li>
  );
}

const STATUS_ICONS: Record<ScoringRunSummary["status"], string> = {
  queued: "⏳",
  running: "⏳",
  success: "✅",
  failed: "❌",
  skipped: "⚪",
};

const STATUS_COLORS: Record<ScoringRunSummary["status"], string> = {
  queued: "var(--text-mute)",
  running: "var(--accent)",
  success: "var(--ok-600)",
  failed: "var(--warn-600)",
  skipped: "var(--text-mute)",
};

function formatWeight(w: number): string {
  return Number.isInteger(w) ? String(w) : w.toFixed(1);
}

function formatRunTime(seconds: number): string {
  const d = new Date(seconds * 1000);
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  const hh = String(d.getHours()).padStart(2, "0");
  const mi = String(d.getMinutes()).padStart(2, "0");
  return `${mm}-${dd} ${hh}:${mi}`;
}
