import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import {
  AdminRequiredError,
  searchScoringUsers,
  upsertCommenterWeight,
  type CommenterWeight,
  type ScoringUserSearchHit,
} from "@/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

const WEIGHT_PRESETS = [
  { value: 1.0, label: "1.0  默认" },
  { value: 1.3, label: "1.3  中权重（资深 reviewer）" },
  { value: 1.5, label: "1.5  中强权重（CTO 级）" },
  { value: 2.0, label: "2.0  强权重（CEO 级）" },
];

type Props = {
  editing: CommenterWeight | null;
  onClose: () => void;
  onSaved: (w: CommenterWeight) => void;
  onAdminLost: () => void;
};

export function AddCommenterWeightDialog({
  editing,
  onClose,
  onSaved,
  onAdminLost,
}: Props) {
  const isEdit = editing !== null;
  const [pivotUserId, setPivotUserId] = useState(editing?.pivot_user_id ?? "");
  const [pickedDisplay, setPickedDisplay] = useState(
    editing?.user_display ?? "",
  );
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState<ScoringUserSearchHit[]>([]);
  const [searching, setSearching] = useState(false);
  const [weight, setWeight] = useState(editing?.weight ?? 2.0);
  const [label, setLabel] = useState(editing?.label ?? "");
  const [note, setNote] = useState(editing?.note ?? "");
  const [saving, setSaving] = useState(false);

  const debounceRef = useRef<number | null>(null);

  useEffect(() => {
    if (isEdit) return;
    if (debounceRef.current !== null) {
      window.clearTimeout(debounceRef.current);
    }
    if (!searchQuery.trim()) {
      setSearchResults([]);
      return;
    }
    debounceRef.current = window.setTimeout(async () => {
      setSearching(true);
      try {
        const r = await searchScoringUsers(searchQuery.trim());
        setSearchResults(r.items);
      } catch (e) {
        if (e instanceof AdminRequiredError) {
          onAdminLost();
        } else {
          toast.error(e instanceof Error ? e.message : String(e));
        }
      } finally {
        setSearching(false);
      }
    }, 250);
    return () => {
      if (debounceRef.current !== null) {
        window.clearTimeout(debounceRef.current);
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchQuery, isEdit]);

  const onPick = (hit: ScoringUserSearchHit) => {
    setPivotUserId(hit.pivot_user_id);
    setPickedDisplay(hit.display_name);
    setSearchQuery("");
    setSearchResults([]);
  };

  const onSubmit = async () => {
    if (!pivotUserId) {
      toast.error("请先选择联系人");
      return;
    }
    if (!label.trim()) {
      toast.error("显示标签必填");
      return;
    }
    if (weight < 0.1 || weight > 5.0) {
      toast.error("权重必须在 0.1 - 5.0 之间");
      return;
    }
    setSaving(true);
    try {
      const w = await upsertCommenterWeight({
        pivot_user_id: pivotUserId,
        weight,
        label: label.trim(),
        note: note.trim() || null,
      });
      toast.success(isEdit ? "已更新" : "已添加");
      onSaved(w);
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
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onClick={onClose}
    >
      <div
        className="w-full max-w-md rounded-[var(--r-md)] bg-[var(--surface)] shadow-[var(--shadow-lg)]"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="border-b border-[var(--line)] px-5 py-3">
          <h3 className="text-base font-semibold">
            {isEdit ? "编辑高权重发言人" : "添加高权重发言人"}
          </h3>
        </div>

        <div className="space-y-4 px-5 py-4">
          <div className="space-y-2">
            <Label>联系人</Label>
            {isEdit ? (
              <div className="rounded-[var(--r-sm)] border border-[var(--line)] bg-[var(--surface-alt)] px-3 py-2 text-sm">
                {pickedDisplay}
                <span className="ml-2 text-xs text-[var(--text-mute)]">
                  （编辑模式不能改人）
                </span>
              </div>
            ) : pickedDisplay ? (
              <div className="flex items-center gap-2">
                <div className="flex-1 rounded-[var(--r-sm)] border border-[var(--line)] bg-[var(--surface-alt)] px-3 py-2 text-sm">
                  {pickedDisplay}
                </div>
                <button
                  type="button"
                  className="text-xs text-[var(--accent)] underline"
                  onClick={() => {
                    setPivotUserId("");
                    setPickedDisplay("");
                  }}
                >
                  重新选
                </button>
              </div>
            ) : (
              <div className="space-y-2">
                <Input
                  placeholder="搜索姓名 / pinyin / email…"
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                />
                {searching && (
                  <p className="text-xs text-[var(--text-mute)]">搜索中…</p>
                )}
                {searchResults.length > 0 && (
                  <div className="max-h-40 overflow-y-auto rounded-[var(--r-sm)] border border-[var(--line)] bg-[var(--surface)]">
                    {searchResults.map((hit) => (
                      <button
                        key={hit.pivot_user_id}
                        type="button"
                        className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm hover:bg-[var(--surface-alt)]"
                        onClick={() => onPick(hit)}
                      >
                        {hit.avatar_url ? (
                          <img
                            src={hit.avatar_url}
                            alt=""
                            className="h-6 w-6 rounded-full"
                          />
                        ) : (
                          <span className="h-6 w-6 rounded-full bg-[var(--surface-alt)]" />
                        )}
                        <span className="min-w-0 flex-1 truncate">
                          {hit.display_name}
                          {hit.pinyin && (
                            <span className="ml-2 text-xs text-[var(--text-mute)]">
                              {hit.pinyin}
                            </span>
                          )}
                        </span>
                        {hit.role === "admin" && (
                          <span className="rounded bg-[var(--accent-bg)] px-1.5 text-[10px] text-[var(--accent)]">
                            admin
                          </span>
                        )}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>

          <div className="space-y-2">
            <Label htmlFor="weight">权重</Label>
            <Input
              id="weight"
              type="number"
              min={0.1}
              max={5.0}
              step={0.1}
              value={weight}
              onChange={(e) => setWeight(Number(e.target.value) || 1.0)}
            />
            <div className="flex flex-wrap gap-1.5">
              {WEIGHT_PRESETS.map((p) => (
                <button
                  key={p.value}
                  type="button"
                  className={`rounded px-2 py-0.5 text-xs ${
                    weight === p.value
                      ? "bg-[var(--accent-bg)] text-[var(--accent)]"
                      : "bg-[var(--surface-alt)] text-[var(--text-mute)] hover:bg-[var(--accent-bg)]"
                  }`}
                  onClick={() => setWeight(p.value)}
                >
                  {p.label}
                </button>
              ))}
            </div>
          </div>

          <div className="space-y-2">
            <Label htmlFor="label-input">显示标签</Label>
            <Input
              id="label-input"
              placeholder="CEO / CTO / 技术负责人 等"
              value={label}
              onChange={(e) => setLabel(e.target.value)}
            />
            <p className="text-xs text-[var(--text-mute)]">
              会写入 prompt 注入：lisi (CTO, 权重 1.5x)
            </p>
          </div>

          <div className="space-y-2">
            <Label htmlFor="note-input">备注（可选）</Label>
            <Input
              id="note-input"
              placeholder="例：负责 Pivot 项目的 reviewer"
              value={note}
              onChange={(e) => setNote(e.target.value)}
            />
          </div>
        </div>

        <div className="flex justify-end gap-2 border-t border-[var(--line)] px-5 py-3">
          <Button variant="outline" onClick={onClose}>
            取消
          </Button>
          <Button onClick={onSubmit} disabled={saving || !pivotUserId}>
            {saving ? "保存中…" : isEdit ? "更新" : "添加"}
          </Button>
        </div>
      </div>
    </div>
  );
}
