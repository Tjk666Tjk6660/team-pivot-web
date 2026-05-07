import { useEffect, useState } from "react";
import { toast } from "sonner";
import {
  AdminRequiredError,
  fetchScoringConfig,
  updateScoringConfig,
  type ScoringConfig,
} from "@/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

const SUGGESTED_MODELS = [
  "",
  "anthropic/claude-sonnet-4-5",
  "anthropic/claude-haiku-4-5",
  "openai/gpt-4o-mini",
];

const onAdminLost = () => {
  toast.error("管理员权限已失效，请刷新或重新登录");
};

export function ConfigTab() {
  const [config, setConfig] = useState<ScoringConfig | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let active = true;
    fetchScoringConfig()
      .then((cfg) => {
        if (active) setConfig(cfg);
      })
      .catch((e) => {
        if (e instanceof AdminRequiredError) onAdminLost();
        else toast.error(e instanceof Error ? e.message : String(e));
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  const update = (patch: Partial<ScoringConfig>) => {
    if (!config) return;
    setConfig({ ...config, ...patch });
  };

  const save = async () => {
    if (!config) return;
    setSaving(true);
    try {
      await updateScoringConfig(config);
      toast.success("评分配置已保存");
    } catch (e) {
      if (e instanceof AdminRequiredError) onAdminLost();
      else toast.error(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  };

  if (loading || !config) {
    return (
      <Card>
        <CardContent className="px-6 py-5 text-sm text-muted-foreground">
          加载中…
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardContent className="space-y-5 px-6 py-5">
        {/* Toggle (inline, no big card) */}
        <div className="flex items-start gap-3">
          <input
            id="scoring-enabled"
            type="checkbox"
            checked={config.enabled}
            onChange={(e) => update({ enabled: e.target.checked })}
            className="mt-1"
          />
          <label htmlFor="scoring-enabled" className="flex-1 cursor-pointer">
            <span className="block text-sm font-semibold text-[var(--text)]">
              评分功能总开关
            </span>
            <span className="mt-0.5 block text-xs text-[var(--text-mute)]">
              关闭后 finished 不再触发评分（已生成的不删除）
            </span>
          </label>
        </div>

        {/* Visibility — collapsed to a compact select */}
        <div className="grid gap-2 md:grid-cols-[160px_1fr] md:items-center">
          <Label htmlFor="scoring-visibility" className="text-sm">
            评分结果可见范围
          </Label>
          <div className="flex items-center gap-3">
            <select
              id="scoring-visibility"
              value={config.visibility}
              onChange={(e) =>
                update({ visibility: e.target.value as ScoringConfig["visibility"] })
              }
              className="h-9 rounded-[var(--r-sm)] border border-[var(--line)] bg-[var(--surface)] px-2 text-sm"
            >
              <option value="admin_only">仅管理员（v1 默认）</option>
              <option value="subjects" disabled>
                仅本人和管理员（v1 暂不开放）
              </option>
              <option value="all" disabled>
                全员可见（v1 暂不开放）
              </option>
            </select>
          </div>
        </div>

        {/* Model + timeout in two cols */}
        <div className="grid gap-4 md:grid-cols-2">
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
                update({ timeout_seconds: Number(e.target.value) || 300 })
              }
            />
            <p className="text-xs text-muted-foreground">
              推荐 300 秒（≈5 分钟），范围 1-600。AI 调用超时后 run 标 failed
            </p>
          </div>
        </div>

        <div className="flex justify-end border-t pt-4">
          <Button onClick={save} disabled={saving}>
            {saving ? "保存中…" : "保存配置"}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
