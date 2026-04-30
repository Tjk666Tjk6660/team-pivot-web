import { useCallback, useEffect, useState } from "react";
import {
  approveApplication,
  getMatchCandidates,
  listAdminUsers,
  listApplications,
  rejectApplication,
  unblockApplication,
  type AdminUser,
  type Application,
  type ApplicationMergedInto,
  type MatchCandidate,
} from "@/api";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";

type Filter = "pending" | "rejected" | "approved";

export function AdminApplications() {
  const [filter, setFilter] = useState<Filter>("pending");
  const [items, setItems] = useState<Application[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const r = await listApplications(filter);
      setItems(r.items);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [filter]);

  useEffect(() => {
    void reload();
  }, [reload]);

  return (
    <div className="mx-auto max-w-4xl p-6">
      <header className="mb-5 flex items-baseline justify-between gap-4">
        <h1 className="m-0 text-[22px]" style={titleStyle}>
          申请审批
        </h1>
        <div className="flex gap-1 rounded-[var(--r-sm)] p-1" style={tabBarStyle}>
          {(["pending", "rejected", "approved"] as Filter[]).map((f) => (
            <button
              key={f}
              type="button"
              onClick={() => setFilter(f)}
              className="rounded-[var(--r-sm)] px-3 py-1.5 text-[12.5px] font-semibold"
              style={{
                background: filter === f ? "var(--surface)" : "transparent",
                color: filter === f ? "var(--text)" : "var(--text-mute)",
                border: filter === f ? "1px solid var(--line)" : "1px solid transparent",
              }}
            >
              {filter === f ? `${labelOf(f)}` : labelOf(f)}
            </button>
          ))}
        </div>
      </header>

      {loading && <p style={mutedStyle}>加载中…</p>}
      {error && (
        <p className="text-[13px]" style={{ color: "var(--danger-500)" }}>
          {error}
        </p>
      )}
      {!loading && !error && items.length === 0 && (
        <p style={mutedStyle}>没有 {labelOf(filter)} 的申请。</p>
      )}

      <ul className="flex flex-col gap-3">
        {items.map((a) => (
          <ApplicationRow key={a.id} app={a} onChanged={reload} />
        ))}
      </ul>
    </div>
  );
}

function labelOf(f: Filter): string {
  return { pending: "待审批", rejected: "已拒绝", approved: "已通过" }[f];
}

function ApplicationRow({
  app,
  onChanged,
}: {
  app: Application;
  onChanged: () => void;
}) {
  const profile = app.raw_profile as { name?: string; email?: string; avatar_url?: string };
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const guard = async (fn: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <li
      className="rounded-[var(--r-md)] p-4"
      style={{
        background: "var(--surface)",
        border: "1px solid var(--line)",
      }}
    >
      <div className="flex items-start justify-between gap-4">
        <div className="flex items-start gap-3">
          {profile.avatar_url ? (
            <img
              src={profile.avatar_url}
              alt=""
              className="h-10 w-10 rounded-full object-cover"
            />
          ) : (
            <div
              className="flex h-10 w-10 items-center justify-center rounded-full text-[13px] font-semibold uppercase"
              style={{ background: "var(--accent-bg)", color: "var(--accent)" }}
            >
              {(profile.name || "?").slice(0, 1)}
            </div>
          )}
          <div>
            <div className="text-[15px] font-semibold" style={{ color: "var(--text)" }}>
              {profile.name || "(未知)"}
            </div>
            <div className="mt-0.5 text-[12px] font-meta" style={mutedStyle}>
              {app.provider} · {new Date(app.applied_at * 1000).toLocaleString()}
            </div>
            {app.status === "rejected" && app.reject_reason && (
              <div
                className="mt-1.5 text-[12px]"
                style={{ color: "var(--danger-500)" }}
              >
                拒绝原因：{app.reject_reason}
              </div>
            )}
            {app.status === "approved" && app.merged_into && (
              <MergedIntoLine info={app.merged_into} />
            )}
          </div>
        </div>
        <div className="flex shrink-0 flex-col items-end gap-2">
          {app.status === "pending" && (
            <PendingActions app={app} busy={busy} guard={guard} />
          )}
          {app.status === "rejected" && (
            <Button
              variant="ghost"
              disabled={busy}
              onClick={() => guard(async () => {
                await unblockApplication(app.id);
              })}
              className="text-[12.5px]"
            >
              解封（允许重新申请）
            </Button>
          )}
        </div>
      </div>
      {error && (
        <p className="mt-2 text-[12px]" style={{ color: "var(--danger-500)" }}>
          {error}
        </p>
      )}
    </li>
  );
}

function PendingActions({
  app,
  busy,
  guard,
}: {
  app: Application;
  busy: boolean;
  guard: (fn: () => Promise<void>) => Promise<void>;
}) {
  const [rejectOpen, setRejectOpen] = useState(false);
  const [mergeOpen, setMergeOpen] = useState(false);

  return (
    <>
      <div className="flex flex-wrap justify-end gap-2">
        <Button
          disabled={busy}
          onClick={() => guard(async () => {
            await approveApplication(app.id);
          })}
          className="h-8 rounded-[var(--r-sm)] px-3 text-[12.5px]"
          style={{
            background: "var(--accent)",
            color: "var(--accent-ink)",
            border: "1px solid var(--accent)",
          }}
        >
          同意（新建账号）
        </Button>
        <Button
          variant="outline"
          disabled={busy}
          onClick={() => setMergeOpen(true)}
          className="h-8 rounded-[var(--r-sm)] px-3 text-[12.5px]"
        >
          合并到已有账号
        </Button>
        <Button
          variant="ghost"
          disabled={busy}
          onClick={() => setRejectOpen(true)}
          className="h-8 rounded-[var(--r-sm)] px-3 text-[12.5px]"
          style={{ color: "var(--danger-500)" }}
        >
          拒绝
        </Button>
      </div>
      <RejectDialog
        open={rejectOpen}
        onClose={() => setRejectOpen(false)}
        onConfirm={(reason) =>
          guard(async () => {
            await rejectApplication(app.id, reason);
            setRejectOpen(false);
          })
        }
      />
      <MergeDialog
        open={mergeOpen}
        onClose={() => setMergeOpen(false)}
        application={app}
        onConfirm={(targetId) =>
          guard(async () => {
            await approveApplication(app.id, targetId);
            setMergeOpen(false);
          })
        }
      />
    </>
  );
}

function RejectDialog({
  open,
  onClose,
  onConfirm,
}: {
  open: boolean;
  onClose: () => void;
  onConfirm: (reason: string) => void;
}) {
  const [reason, setReason] = useState("");
  useEffect(() => {
    if (!open) setReason("");
  }, [open]);
  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>拒绝申请</DialogTitle>
          <DialogDescription>
            可选填一条原因（≤ 500 字）。拒绝后申请人会收到飞书 DM 通知。
          </DialogDescription>
        </DialogHeader>
        <Textarea
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          maxLength={500}
          placeholder="例如：不在团队范围内"
          rows={4}
        />
        <DialogFooter>
          <Button variant="ghost" onClick={onClose}>
            取消
          </Button>
          <Button
            onClick={() => onConfirm(reason.trim())}
            style={{
              background: "var(--danger-500)",
              color: "white",
              border: "1px solid var(--danger-500)",
            }}
          >
            确认拒绝
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function MergeDialog({
  open,
  onClose,
  application,
  onConfirm,
}: {
  open: boolean;
  onClose: () => void;
  application: Application;
  onConfirm: (targetId: string) => void;
}) {
  const [candidates, setCandidates] = useState<MatchCandidate[]>([]);
  const [candidatesLoading, setCandidatesLoading] = useState(false);
  const [picked, setPicked] = useState<{ id: string; label: string } | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState<AdminUser[]>([]);
  const [searchLoading, setSearchLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Reset every time the dialog opens
  useEffect(() => {
    if (!open) {
      setPicked(null);
      setSearchQuery("");
      setSearchResults([]);
      setError(null);
      return;
    }
    setCandidatesLoading(true);
    setError(null);
    getMatchCandidates(application.id)
      .then((r) => setCandidates(r.candidates))
      .catch((err) => setError(err instanceof Error ? err.message : String(err)))
      .finally(() => setCandidatesLoading(false));
  }, [open, application.id]);

  // Debounced search via /api/admin/users?search=<q>
  useEffect(() => {
    if (!open) return;
    const q = searchQuery.trim();
    if (!q) {
      setSearchResults([]);
      return;
    }
    setSearchLoading(true);
    const handle = setTimeout(async () => {
      try {
        const r = await listAdminUsers({ search: q, include_deleted: false });
        // Hide users already shown as auto-candidate (avoid double-listing)
        const candIds = new Set(candidates.map((c) => c.user_id));
        const items = r.items.filter(
          (u) => !candIds.has(u.id) && u.status === "active",
        );
        setSearchResults(items);
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        setSearchLoading(false);
      }
    }, 250);
    return () => clearTimeout(handle);
  }, [open, searchQuery, candidates]);

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>合并到已有账号</DialogTitle>
          <DialogDescription>
            把这个申请的飞书身份绑定到现有 pivot_user。常用于"换工号 / 换设备"
            的同人重新登录。
          </DialogDescription>
        </DialogHeader>

        {candidatesLoading && <p style={mutedStyle}>正在搜同人候选…</p>}

        {!candidatesLoading && candidates.length > 0 && (
          <div>
            <Label className="text-[12.5px]" style={{ color: "var(--text-mute)" }}>
              建议候选（按相似度）
            </Label>
            <div className="mt-2 flex flex-wrap gap-2">
              {candidates.map((c) => {
                const isPicked = picked?.id === c.user_id;
                return (
                  <button
                    key={c.user_id}
                    type="button"
                    onClick={() =>
                      setPicked({ id: c.user_id, label: c.display_name })
                    }
                    className="rounded-full px-3 py-1.5 text-[12.5px] font-semibold transition-colors"
                    style={{
                      background: isPicked ? "var(--accent)" : "var(--surface-alt)",
                      color: isPicked ? "var(--accent-ink)" : "var(--text)",
                      border: "1px solid var(--line)",
                    }}
                  >
                    {c.display_name}
                    <span
                      className="ml-1.5 text-[10.5px]"
                      style={{
                        color: isPicked ? "var(--accent-ink)" : "var(--text-mute)",
                      }}
                    >
                      {reasonLabel(c.reason)}
                    </span>
                  </button>
                );
              })}
            </div>
          </div>
        )}

        <div className="grid gap-1.5 pt-2">
          <Label htmlFor="userSearch" className="text-[12.5px]">
            {candidates.length > 0 ? "或搜索其它已有用户" : "搜索已有用户"}
          </Label>
          <Input
            id="userSearch"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="按 display_name / email / pinyin"
            autoComplete="off"
          />
          {searchQuery.trim() && (
            <div
              className="mt-1 max-h-48 overflow-y-auto rounded-[var(--r-sm)]"
              style={{ border: "1px solid var(--line)" }}
            >
              {searchLoading && (
                <p className="px-3 py-2 text-[12.5px]" style={mutedStyle}>
                  搜索中…
                </p>
              )}
              {!searchLoading && searchResults.length === 0 && (
                <p className="px-3 py-2 text-[12.5px]" style={mutedStyle}>
                  没有匹配的用户。
                </p>
              )}
              {searchResults.map((u) => {
                const isPicked = picked?.id === u.id;
                return (
                  <button
                    key={u.id}
                    type="button"
                    onClick={() =>
                      setPicked({ id: u.id, label: u.display_name })
                    }
                    className="flex w-full items-center gap-2.5 px-3 py-2 text-left transition-colors"
                    style={{
                      background: isPicked
                        ? "var(--accent-bg)"
                        : "var(--surface)",
                    }}
                  >
                    {u.avatar_url ? (
                      <img
                        src={u.avatar_url}
                        alt=""
                        className="h-7 w-7 shrink-0 rounded-full object-cover"
                      />
                    ) : (
                      <div
                        className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-[11px] font-semibold uppercase"
                        style={{
                          background: "var(--surface-alt)",
                          color: "var(--accent)",
                        }}
                      >
                        {(u.display_name || "?").slice(0, 1)}
                      </div>
                    )}
                    <div className="min-w-0 flex-1">
                      <div
                        className="truncate text-[13px] font-semibold"
                        style={{ color: "var(--text)" }}
                      >
                        {u.display_name}
                      </div>
                      <div
                        className="truncate text-[11.5px] font-meta"
                        style={mutedStyle}
                      >
                        {u.email || "无邮箱"}
                        {u.pinyin && ` · ${u.pinyin}`}
                        {u.roles?.includes("admin") && " · ADMIN"}
                      </div>
                    </div>
                    {isPicked && (
                      <span
                        className="text-[11px] font-bold"
                        style={{ color: "var(--accent)" }}
                      >
                        ✓ 已选
                      </span>
                    )}
                  </button>
                );
              })}
            </div>
          )}
        </div>

        {picked && (
          <p
            className="text-[12px]"
            style={{ color: "var(--text-soft)" }}
          >
            已选目标：<strong>{picked.label}</strong>
          </p>
        )}

        {error && (
          <p className="text-[12px]" style={{ color: "var(--danger-500)" }}>
            {error}
          </p>
        )}

        <DialogFooter>
          <Button variant="ghost" onClick={onClose}>
            取消
          </Button>
          <Button
            disabled={!picked}
            onClick={() => picked && onConfirm(picked.id)}
            style={{
              background: "var(--accent)",
              color: "var(--accent-ink)",
              border: "1px solid var(--accent)",
            }}
          >
            确认合并
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function MergedIntoLine({ info }: { info: ApplicationMergedInto }) {
  // info.merged === true → 合并到了已有用户（同人换工号场景）
  // info.merged === false → 当时是"同意（新建账号）"，目标用户是新建的
  const verb = info.merged ? "合并到" : "新建为";
  return (
    <div
      className="mt-2 inline-flex items-center gap-2 rounded-[var(--r-sm)] px-2.5 py-1"
      style={{
        background: "var(--accent-bg)",
        border: "1px solid var(--accent)",
      }}
    >
      <span
        className="text-[10.5px] font-bold uppercase tracking-[0.18em] font-meta"
        style={{ color: "var(--accent)" }}
      >
        {info.merged ? "已合并" : "已通过"}
      </span>
      <span className="text-[12px]" style={{ color: "var(--text)" }}>
        {verb}{" "}
        <strong>{info.display_name}</strong>
        {info.email && (
          <span
            className="ml-1.5 font-meta"
            style={{ color: "var(--text-mute)" }}
          >
            ({info.email})
          </span>
        )}
      </span>
    </div>
  );
}

function reasonLabel(r: MatchCandidate["reason"]): string {
  return {
    email_exact: "邮箱一致",
    name_exact: "姓名完全一致",
    pinyin_full: "拼音一致",
    pinyin_initials: "拼音首字母一致",
  }[r];
}

const titleStyle: React.CSSProperties = {
  fontFamily: "var(--font-serif)",
  fontWeight: 600,
  letterSpacing: "var(--letter-tight)",
  color: "var(--text)",
};

const tabBarStyle: React.CSSProperties = {
  background: "var(--surface-alt)",
  border: "1px solid var(--line)",
};

const mutedStyle: React.CSSProperties = {
  color: "var(--text-mute)",
  fontSize: "13px",
};
