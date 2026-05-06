import { useEffect, useState } from "react";
import { Pencil, Plus, Trash2, Users2 } from "lucide-react";
import { toast } from "sonner";
import {
  AdminRequiredError,
  deleteCommenterWeight,
  listCommenterWeights,
  type CommenterWeight,
} from "@/api";
import { AddCommenterWeightDialog } from "@/components/admin/scoring/AddCommenterWeightDialog";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";

const onAdminLost = () => {
  toast.error("管理员权限已失效，请刷新或重新登录");
};

export function WeightsTab() {
  const [weights, setWeights] = useState<CommenterWeight[]>([]);
  const [loading, setLoading] = useState(true);
  const [addDialogOpen, setAddDialogOpen] = useState(false);
  const [editingWeight, setEditingWeight] = useState<CommenterWeight | null>(null);

  useEffect(() => {
    let active = true;
    listCommenterWeights()
      .then((r) => {
        if (active) setWeights(r.items);
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

  const onDeleted = async (userId: string) => {
    try {
      await deleteCommenterWeight(userId);
      toast.success("已移除");
      setWeights((prev) => prev.filter((w) => w.pivot_user_id !== userId));
    } catch (e) {
      if (e instanceof AdminRequiredError) onAdminLost();
      else toast.error(e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <Card>
      <CardContent className="space-y-4 px-6 py-5">
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
          这些人的评论会被 AI 视为更强的信号（影响 confidence + 微调分数 ±0.5）。不在表里的人默认权重 1.0。
        </p>
        {loading ? (
          <p className="text-sm text-muted-foreground">加载中…</p>
        ) : weights.length === 0 ? (
          <p className="text-xs text-muted-foreground italic">
            （未配置高权重发言人）
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
                  onClick={() => onDeleted(w.pivot_user_id)}
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </li>
            ))}
          </ul>
        )}

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
      </CardContent>
    </Card>
  );
}

function formatWeight(w: number): string {
  return Number.isInteger(w) ? String(w) : w.toFixed(1);
}
