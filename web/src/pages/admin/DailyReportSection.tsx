import { useEffect, useRef, useState } from "react";
import {
  Bell,
  ChevronRight,
  Clock,
  History,
  MoreHorizontal,
  Pause,
  Pencil,
  Play,
  Plus,
  Trash2,
  X,
} from "lucide-react";
import { toast } from "sonner";
import {
  AdminRequiredError,
  createDailyReportJob,
  deleteDailyReportJob,
  fetchAdminNotifyConfig,
  fetchContactsByIds,
  fetchDailyReportJobs,
  fetchDailyReportRun,
  fetchDailyReportRunsPage,
  fetchFeishuChats,
  manualTriggerDailyReport,
  runDailyReportJobNow,
  searchContacts,
  setDailyReportJobStatus,
  updateAdminNotifyConfig,
  updateDailyReportJob,
  type AdminNotifyConfig,
  type Contact,
  type DailyReportJob,
  type DailyReportJobIn,
  type DailyReportJobUpdate,
  type DailyReportPushFreq,
  type DailyReportRun,
  type DailyReportRunDetail,
  type FeishuChat,
} from "@/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  ACard,
  CardFoot,
  CardHead,
  FieldHelp,
  FieldLabel,
} from "../AdminPage";

// --------------------------------------------------------------------------
// Top-level — order: 定时任务(主) → 立即触发 → 系统通知(折叠)
// --------------------------------------------------------------------------

export function DailyReportSection({
  onAdminLost,
}: {
  onAdminLost: () => void;
}) {
  const [jobs, setJobs] = useState<DailyReportJob[]>([]);
  const [chats, setChats] = useState<FeishuChat[]>([]);
  const [loading, setLoading] = useState(true);
  const [editingJob, setEditingJob] = useState<DailyReportJob | "new" | null>(
    null,
  );
  const [historyJob, setHistoryJob] = useState<DailyReportJob | null>(null);

  const refresh = async () => {
    try {
      const [j, c] = await Promise.all([
        fetchDailyReportJobs(),
        fetchFeishuChats().catch(() => []),
      ]);
      setJobs(j);
      setChats(c);
    } catch (e) {
      if (e instanceof AdminRequiredError) {
        onAdminLost();
      } else {
        toast.error(e instanceof Error ? e.message : String(e));
      }
    }
  };

  useEffect(() => {
    setLoading(true);
    refresh().finally(() => setLoading(false));
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="flex flex-col gap-4">
      <ACard>
        <CardHead
          title="定时任务"
          desc="每个任务独立配置视角 / 时间窗口 / 推送时刻 / 接收人"
          trailing={
            <Button
              size="sm"
              onClick={() => setEditingJob("new")}
              className="h-8"
            >
              <Plus className="mr-1 h-3.5 w-3.5" />
              新建任务
            </Button>
          }
        />
        <div className="flex flex-col">
          {loading ? (
            <div className="px-5 py-6 text-sm" style={{ color: "var(--text-mute)" }}>
              加载中…
            </div>
          ) : jobs.length === 0 ? (
            <EmptyJobs />
          ) : (
            jobs.map((job, i) => (
              <JobRow
                key={job.id}
                job={job}
                chats={chats}
                first={i === 0}
                onAdminLost={onAdminLost}
                onChange={refresh}
                onEdit={() => setEditingJob(job)}
                onShowHistory={() => setHistoryJob(job)}
              />
            ))
          )}
        </div>
      </ACard>

      <ManualTriggerCard onAdminLost={onAdminLost} chats={chats} />

      <SystemNotifyCard onAdminLost={onAdminLost} chats={chats} />

      {editingJob && (
        <JobEditDrawer
          job={editingJob === "new" ? null : editingJob}
          chats={chats}
          onClose={() => setEditingJob(null)}
          onSaved={() => {
            setEditingJob(null);
            refresh();
          }}
          onAdminLost={onAdminLost}
        />
      )}
      {historyJob && (
        <RunHistoryDrawer
          job={historyJob}
          onClose={() => setHistoryJob(null)}
          onAdminLost={onAdminLost}
        />
      )}
    </div>
  );
}

function EmptyJobs() {
  return (
    <div
      className="flex flex-col items-center gap-2 px-5 py-10 text-center"
      style={{ color: "var(--text-mute)" }}
    >
      <div className="text-[13px]">还没有定时任务</div>
      <div className="text-[12px]">点击右上角"新建任务"添加第一条</div>
    </div>
  );
}

// --------------------------------------------------------------------------
// SystemNotifyCard — collapsible, secondary
// --------------------------------------------------------------------------

function SystemNotifyCard({
  onAdminLost,
  chats,
}: {
  onAdminLost: () => void;
  chats: FeishuChat[];
}) {
  const [open, setOpen] = useState(false);
  const [config, setConfig] = useState<AdminNotifyConfig>({
    chat_ids: [],
    open_ids: [],
  });
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [openIdNames, setOpenIdNames] = useState<Record<string, string>>({});

  useEffect(() => {
    fetchAdminNotifyConfig()
      .then(setConfig)
      .catch((e) => {
        if (e instanceof AdminRequiredError) onAdminLost();
        else toast.error(e instanceof Error ? e.message : String(e));
      })
      .finally(() => setLoading(false));
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const save = async () => {
    setSaving(true);
    try {
      await updateAdminNotifyConfig(config);
      toast.success("系统通知接收人已保存");
    } catch (e) {
      if (e instanceof AdminRequiredError) onAdminLost();
      else toast.error(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  };

  const summary =
    config.chat_ids.length + config.open_ids.length === 0
      ? "未配置 · fallback 广播全部 bot 群"
      : `${config.chat_ids.length} 群 · ${config.open_ids.length} 人`;

  return (
    <ACard>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center justify-between gap-3 px-5 py-4 text-left transition-colors hover:bg-[var(--surface-alt)]"
      >
        <div className="min-w-0">
          <h3 className="m-0 text-[14px] font-semibold" style={{ color: "var(--text)" }}>
            系统通知接收人
          </h3>
          <div className="mt-0.5 text-[12px]" style={{ color: "var(--text-mute)" }}>
            日报漏跑 / 失败 / 重试到上限时给这里发卡 · {summary}
          </div>
        </div>
        <ChevronRight
          className="h-4 w-4 flex-none transition-transform"
          style={{
            color: "var(--text-mute)",
            transform: open ? "rotate(90deg)" : undefined,
          }}
        />
      </button>
      {open && (
        <>
          <div
            className="px-5 py-4 flex flex-col gap-4"
            style={{ borderTop: "1px solid var(--line)" }}
          >
            {loading ? (
              <div className="text-sm" style={{ color: "var(--text-mute)" }}>
                加载中…
              </div>
            ) : (
              <>
                <div className="flex flex-col gap-2">
                  <FieldLabel>接收群</FieldLabel>
                  <FeishuChatMultiPick
                    chats={chats}
                    value={config.chat_ids}
                    onChange={(v) => setConfig({ ...config, chat_ids: v })}
                  />
                </div>
                <div className="flex flex-col gap-2">
                  <FieldLabel>接收个人(DM)</FieldLabel>
                  <OpenIdMultiPick
                    value={config.open_ids}
                    onChange={(v) => setConfig({ ...config, open_ids: v })}
                    resolvedNames={openIdNames}
                    setResolvedNames={setOpenIdNames}
                  />
                </div>
                <div
                  className="rounded-md border px-3 py-2.5 text-[12px] leading-[1.55]"
                  style={{
                    background: "var(--surface-alt)",
                    color: "var(--text-mute)",
                    borderColor: "var(--line)",
                  }}
                >
                  未配置任何接收人时,系统通知 fallback 广播到所有 bot 所在的飞书群。
                </div>
              </>
            )}
          </div>
          <CardFoot hint="">
            <Button onClick={save} disabled={saving || loading} size="sm">
              {saving ? "保存中…" : "保存"}
            </Button>
          </CardFoot>
        </>
      )}
    </ACard>
  );
}

// --------------------------------------------------------------------------
// JobRow — primary actions inline + secondary in overflow menu
// --------------------------------------------------------------------------

function JobRow({
  job,
  chats,
  first,
  onAdminLost,
  onChange,
  onEdit,
  onShowHistory,
}: {
  job: DailyReportJob;
  chats: FeishuChat[];
  first: boolean;
  onAdminLost: () => void;
  onChange: () => void | Promise<void>;
  onEdit: () => void;
  onShowHistory: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!menuOpen) return;
    const onClick = (e: MouseEvent) => {
      if (!menuRef.current?.contains(e.target as Node)) setMenuOpen(false);
    };
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, [menuOpen]);

  const togglePause = async () => {
    setBusy(true);
    setMenuOpen(false);
    try {
      const newStatus = job.status === "active" ? "paused" : "active";
      await setDailyReportJobStatus(job.id, newStatus);
      toast.success(newStatus === "active" ? "任务已恢复" : "任务已暂停");
      await onChange();
    } catch (e) {
      if (e instanceof AdminRequiredError) onAdminLost();
      else toast.error(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const runNow = async () => {
    setBusy(true);
    try {
      await runDailyReportJobNow(job.id, { dry_run: false, no_ai: false });
      toast.success("已开始,可在历史中查看结果");
      await onChange();
    } catch (e) {
      if (e instanceof AdminRequiredError) onAdminLost();
      else toast.error(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    setMenuOpen(false);
    if (!confirm(`确认归档任务"${job.name}"?(可在归档列表恢复)`)) return;
    setBusy(true);
    try {
      await deleteDailyReportJob(job.id);
      toast.success("任务已归档");
      await onChange();
    } catch (e) {
      if (e instanceof AdminRequiredError) onAdminLost();
      else toast.error(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const viewLabel = job.view === "company" ? "公司视角" : "个人视角";
  const freqLabel = formatPushFreq(job.push_freq);
  const statusColor = {
    active: "var(--ok-600, #2F7A4D)",
    paused: "var(--text-mute)",
    archived: "var(--text-mute)",
  }[job.status];
  const lastBadge = lastStatusBadge(job.last_status);

  return (
    <div
      className="flex flex-col gap-2.5 px-5 py-4"
      style={{ borderTop: first ? "none" : "1px solid var(--line)" }}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex flex-col gap-1.5">
          <div className="flex items-center gap-2 flex-wrap">
            <span
              className="text-[14px] font-semibold"
              style={{ color: "var(--text)" }}
            >
              {job.name}
            </span>
            <span
              className="rounded-full px-1.5 py-0.5 text-[10px]"
              style={{ background: "var(--accent-bg)", color: "var(--accent)" }}
            >
              {viewLabel}
            </span>
            <span
              className="inline-flex items-center gap-1 rounded-full px-1.5 py-0.5 text-[10px]"
              style={{ color: statusColor, background: "var(--surface-alt)" }}
            >
              <span
                className="h-1.5 w-1.5 rounded-full"
                style={{ background: statusColor }}
              />
              {job.status === "active"
                ? "运行中"
                : job.status === "paused"
                ? "已暂停"
                : "已归档"}
            </span>
            {lastBadge && (
              <span
                className="rounded px-1.5 py-0.5 text-[10px]"
                style={{ background: lastBadge.bg, color: lastBadge.color }}
              >
                上次:{lastBadge.text}
              </span>
            )}
          </div>
          <div
            className="flex items-center gap-x-3 gap-y-1 text-[12px] flex-wrap"
            style={{ color: "var(--text-mute)" }}
          >
            <span className="inline-flex items-center gap-1">
              <Clock className="h-3 w-3" />
              {job.push_time} · {freqLabel}
            </span>
            <span aria-hidden>·</span>
            <span>窗口 {job.window_hours}h</span>
            <span aria-hidden>·</span>
            <span className="truncate">
              {receiverSummary(job, chats)}
            </span>
            {job.next_run_at && (
              <>
                <span aria-hidden>·</span>
                <span style={{ fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace" }}>
                  下次 {fmtTime(job.next_run_at)}
                </span>
              </>
            )}
          </div>
        </div>
        <div className="flex items-center gap-1.5 flex-none">
          <IconBtn
            label="立即运行"
            onClick={runNow}
            disabled={busy}
            icon={<Play className="h-3.5 w-3.5" />}
          />
          <IconBtn
            label="编辑"
            onClick={onEdit}
            disabled={busy}
            icon={<Pencil className="h-3.5 w-3.5" />}
          />
          <div ref={menuRef} className="relative">
            <IconBtn
              label="更多"
              onClick={() => setMenuOpen((v) => !v)}
              disabled={busy}
              icon={<MoreHorizontal className="h-3.5 w-3.5" />}
            />
            {menuOpen && (
              <div
                className="absolute right-0 top-[calc(100%+4px)] z-20 min-w-[140px] overflow-hidden rounded-md border shadow-lg"
                style={{ background: "var(--surface)", borderColor: "var(--line)" }}
              >
                <MenuItem
                  icon={<History className="h-3.5 w-3.5" />}
                  label="查看历史"
                  onClick={() => {
                    setMenuOpen(false);
                    onShowHistory();
                  }}
                />
                <MenuItem
                  icon={
                    job.status === "active" ? (
                      <Pause className="h-3.5 w-3.5" />
                    ) : (
                      <Play className="h-3.5 w-3.5" />
                    )
                  }
                  label={job.status === "active" ? "暂停任务" : "恢复任务"}
                  onClick={togglePause}
                />
                <MenuItem
                  icon={<Trash2 className="h-3.5 w-3.5" />}
                  label="归档任务"
                  onClick={remove}
                  danger
                />
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function MenuItem({
  icon,
  label,
  onClick,
  danger,
}: {
  icon: React.ReactNode;
  label: string;
  onClick: () => void;
  danger?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="flex w-full items-center gap-2 px-3 py-2 text-left text-[13px] transition-colors hover:bg-[var(--surface-alt)]"
      style={{
        color: danger ? "var(--warn-600, #B43E3E)" : "var(--text)",
      }}
    >
      <span style={{ color: danger ? "var(--warn-600, #B43E3E)" : "var(--text-mute)" }}>
        {icon}
      </span>
      {label}
    </button>
  );
}

function IconBtn({
  label,
  onClick,
  disabled,
  icon,
  danger,
}: {
  label: string;
  onClick: () => void;
  disabled?: boolean;
  icon: React.ReactNode;
  danger?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      title={label}
      aria-label={label}
      className="inline-flex h-7 w-7 items-center justify-center rounded-md text-[12px] transition-colors disabled:opacity-40 hover:bg-[var(--surface-alt)]"
      style={{
        background: "var(--surface)",
        border: "1px solid var(--line)",
        color: danger ? "var(--warn-600, #B43E3E)" : "var(--text-soft)",
      }}
    >
      {icon}
    </button>
  );
}

function lastStatusBadge(s: string | null): {
  text: string;
  color: string;
  bg: string;
} | null {
  if (!s) return null;
  if (s === "succeeded")
    return { text: "成功", color: "var(--ok-600, #2F7A4D)", bg: "color-mix(in srgb, var(--ok-600, #2F7A4D) 10%, var(--surface))" };
  if (s === "failed")
    return { text: "失败", color: "var(--warn-600, #B43E3E)", bg: "color-mix(in srgb, var(--warn-600, #B43E3E) 10%, var(--surface))" };
  if (s === "partial")
    return { text: "部分", color: "var(--warn-600, #B5764A)", bg: "var(--accent-bg)" };
  if (s === "skipped")
    return { text: "跳过", color: "var(--text-mute)", bg: "var(--surface-alt)" };
  if (s === "running")
    return { text: "运行中", color: "var(--accent)", bg: "var(--accent-bg)" };
  return { text: s, color: "var(--text-mute)", bg: "var(--surface-alt)" };
}

function receiverSummary(job: DailyReportJob, chats: FeishuChat[]): string {
  if (job.receiver_type === "groups") {
    if (!job.receiver_ids || job.receiver_ids.length === 0) {
      return "→ 全部 bot 群";
    }
    const names = job.receiver_ids
      .map((id) => chats.find((c) => c.chat_id === id)?.name || id)
      .slice(0, 2);
    const rest = job.receiver_ids.length - names.length;
    return `→ ${names.join(", ")}${rest > 0 ? ` 等 ${job.receiver_ids.length} 群` : ""}`;
  }
  return `→ ${job.receiver_ids?.length ?? 0} 人 DM`;
}

const PUSH_FREQ_LABELS: Record<DailyReportPushFreq, string> = {
  daily: "每天",
  weekdays: "仅工作日",
  mon: "每周一",
  tue: "每周二",
  wed: "每周三",
  thu: "每周四",
  fri: "每周五",
  sat: "每周六",
  sun: "每周日",
  month_start: "每月 1 号",
  month_end: "每月最后一天",
};

function formatPushFreq(freq: string): string {
  return PUSH_FREQ_LABELS[freq as DailyReportPushFreq] ?? freq;
}

function fmtTime(iso: string): string {
  try {
    const d = new Date(iso);
    return d.toLocaleString("zh-CN", {
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

// 把 Date 转成 datetime-local input 接受的字符串(本地时区,YYYY-MM-DDTHH:mm)
function toLocalInputValue(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

// --------------------------------------------------------------------------
// JobEditDrawer
// --------------------------------------------------------------------------

function JobEditDrawer({
  job,
  chats,
  onClose,
  onSaved,
  onAdminLost,
}: {
  job: DailyReportJob | null;
  chats: FeishuChat[];
  onClose: () => void;
  onSaved: () => void;
  onAdminLost: () => void;
}) {
  const isNew = job === null;
  const [name, setName] = useState(job?.name ?? "");
  const [view, setView] = useState<"company" | "personal">(job?.view ?? "company");
  const [pushTime, setPushTime] = useState(job?.push_time ?? "09:30");
  const [pushFreq, setPushFreq] = useState<DailyReportPushFreq>(
    job?.push_freq ?? "weekdays",
  );
  const [windowHours, setWindowHours] = useState<number | null>(
    job?.window_hours ?? 24,
  );
  const [receiverType, setReceiverType] = useState<"groups" | "users">(
    job?.receiver_type ?? "groups",
  );
  const [receiverIds, setReceiverIds] = useState<string[]>(
    job?.receiver_ids ?? [],
  );
  const [paused, setPaused] = useState(job?.status === "paused");
  const [openIdNames, setOpenIdNames] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);

  const submit = async () => {
    if (!name.trim()) return toast.error("任务名必填");
    if (receiverType === "users" && receiverIds.length === 0) {
      return toast.error("接收类型为个人时,至少选 1 个 open_id");
    }

    setSaving(true);
    try {
      if (isNew) {
        const body: DailyReportJobIn = {
          name: name.trim(),
          view,
          push_time: pushTime,
          push_freq: pushFreq,
          window_hours: windowHours ?? 24,
          receiver_type: receiverType,
          receiver_ids: receiverIds.length > 0 ? receiverIds : null,
          status: paused ? "paused" : "active",
        };
        await createDailyReportJob(body);
        toast.success("任务已创建");
      } else {
        const body: DailyReportJobUpdate = {
          name: name.trim(),
          view,
          push_time: pushTime,
          push_freq: pushFreq,
          window_hours: windowHours ?? 24,
          receiver_type: receiverType,
          receiver_ids: receiverIds.length > 0 ? receiverIds : null,
        };
        await updateDailyReportJob(job!.id, body);
        const desired = paused ? "paused" : "active";
        if (job!.status !== desired) {
          await setDailyReportJobStatus(job!.id, desired);
        }
        toast.success("任务已更新");
      }
      onSaved();
    } catch (e) {
      if (e instanceof AdminRequiredError) onAdminLost();
      else toast.error(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Drawer onClose={onClose} title={isNew ? "新建任务" : `编辑 · ${job?.name}`}>
      <div className="flex flex-col gap-4 px-5 py-5 overflow-y-auto flex-1">
        <div className="flex flex-col gap-1.5">
          <FieldLabel htmlFor="job-name" required>任务名称</FieldLabel>
          <Input
            id="job-name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="如:公司视角早报"
          />
        </div>

        <div className="grid grid-cols-2 gap-4">
          <div className="flex flex-col gap-1.5">
            <FieldLabel>视角</FieldLabel>
            <select
              value={view}
              onChange={(e) => setView(e.target.value as "company" | "personal")}
              className="h-[34px] rounded-md border bg-white px-3 text-[13px]"
              style={{ borderColor: "var(--line-strong, var(--line))" }}
            >
              <option value="company">公司视角</option>
              <option value="personal">个人视角</option>
            </select>
          </div>
          <div className="flex flex-col gap-1.5">
            <FieldLabel>频率</FieldLabel>
            <select
              value={pushFreq}
              onChange={(e) =>
                setPushFreq(e.target.value as DailyReportPushFreq)
              }
              className="h-[34px] rounded-md border bg-white px-3 text-[13px]"
              style={{ borderColor: "var(--line-strong, var(--line))" }}
            >
              <optgroup label="每天 / 工作日">
                <option value="daily">每天</option>
                <option value="weekdays">仅工作日</option>
              </optgroup>
              <optgroup label="每周固定一天">
                <option value="mon">每周一</option>
                <option value="tue">每周二</option>
                <option value="wed">每周三</option>
                <option value="thu">每周四</option>
                <option value="fri">每周五</option>
                <option value="sat">每周六</option>
                <option value="sun">每周日</option>
              </optgroup>
              <optgroup label="月度">
                <option value="month_start">每月 1 号</option>
                <option value="month_end">每月最后一天</option>
              </optgroup>
            </select>
          </div>
        </div>

        <div className="grid grid-cols-2 gap-4">
          <div className="flex flex-col gap-1.5">
            <FieldLabel htmlFor="job-time">推送时刻 (HH:MM)</FieldLabel>
            <Input
              id="job-time"
              type="time"
              value={pushTime}
              onChange={(e) => setPushTime(e.target.value || "09:30")}
            />
            <FieldHelp>Asia/Shanghai</FieldHelp>
          </div>
          <div className="flex flex-col gap-1.5">
            <FieldLabel htmlFor="job-window">统计窗口(小时)</FieldLabel>
            <Input
              id="job-window"
              type="number"
              min={1}
              max={168}
              value={windowHours ?? ""}
              onChange={(e) => {
                const v = e.target.value;
                if (v === "") {
                  setWindowHours(null);
                  return;
                }
                const n = Number(v);
                if (!Number.isNaN(n)) setWindowHours(n);
              }}
              onBlur={() => {
                if (windowHours === null || windowHours < 1)
                  setWindowHours(24);
              }}
            />
            <FieldHelp>1–168 小时</FieldHelp>
          </div>
        </div>

        <div className="flex flex-col gap-2.5">
          <FieldLabel>接收类型</FieldLabel>
          <div className="grid grid-cols-2 gap-2">
            <RadioCard
              active={receiverType === "groups"}
              onClick={() => {
                setReceiverType("groups");
                setReceiverIds([]);
              }}
              title="飞书群"
              hint="不选群 = 默认全部 bot 群"
            />
            <RadioCard
              active={receiverType === "users"}
              onClick={() => {
                setReceiverType("users");
                setReceiverIds([]);
              }}
              title="个人 DM"
              hint="必须至少选 1 人"
            />
          </div>
        </div>

        {receiverType === "groups" ? (
          <div className="flex flex-col gap-2">
            <FieldLabel>群组(可多选,留空 = 全部 bot 群)</FieldLabel>
            <FeishuChatMultiPick
              chats={chats}
              value={receiverIds}
              onChange={setReceiverIds}
            />
          </div>
        ) : (
          <div className="flex flex-col gap-2">
            <FieldLabel>个人(open_id 列表)</FieldLabel>
            <OpenIdMultiPick
              value={receiverIds}
              onChange={setReceiverIds}
              resolvedNames={openIdNames}
              setResolvedNames={setOpenIdNames}
            />
          </div>
        )}

        <div
          className="flex items-center justify-between rounded-md border px-3 py-2.5"
          style={{
            background: "var(--surface-alt)",
            borderColor: "var(--line)",
          }}
        >
          <div>
            <div
              className="text-[13px] font-medium"
              style={{ color: "var(--text)" }}
            >
              创建后立即启用
            </div>
            <div className="text-[12px]" style={{ color: "var(--text-mute)" }}>
              关闭则保存为已暂停状态,稍后再恢复
            </div>
          </div>
          <button
            type="button"
            onClick={() => setPaused((v) => !v)}
            className="relative h-5 w-9 rounded-full transition-colors flex-none"
            style={{ background: paused ? "var(--surface-strong, var(--line))" : "var(--accent)" }}
            aria-pressed={!paused}
          >
            <span
              className="absolute top-0.5 h-4 w-4 rounded-full bg-white shadow"
              style={{
                left: paused ? 2 : 18,
                transition: "left .15s",
              }}
            />
          </button>
        </div>
      </div>
      <CardFoot hint="">
        <Button variant="ghost" onClick={onClose} disabled={saving}>
          取消
        </Button>
        <Button onClick={submit} disabled={saving}>
          {saving ? "保存中…" : isNew ? "创建" : "保存"}
        </Button>
      </CardFoot>
    </Drawer>
  );
}

function RadioCard({
  active,
  onClick,
  title,
  hint,
}: {
  active: boolean;
  onClick: () => void;
  title: string;
  hint: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="text-left rounded-md px-3 py-2.5 transition-all"
      style={{
        background: active ? "color-mix(in srgb, var(--accent-bg) 50%, var(--surface))" : "var(--surface)",
        border: `1px solid ${active ? "var(--accent)" : "var(--line)"}`,
        boxShadow: active
          ? "0 0 0 3px color-mix(in srgb, var(--accent) 12%, transparent)"
          : "none",
      }}
    >
      <div
        className="text-[13px] font-semibold"
        style={{ color: "var(--text)" }}
      >
        {title}
      </div>
      <div className="text-[11.5px] mt-0.5" style={{ color: "var(--text-mute)" }}>
        {hint}
      </div>
    </button>
  );
}

// --------------------------------------------------------------------------
// RunHistoryDrawer
// --------------------------------------------------------------------------

function RunHistoryDrawer({
  job,
  onClose,
  onAdminLost,
}: {
  job: DailyReportJob;
  onClose: () => void;
  onAdminLost: () => void;
}) {
  const [items, setItems] = useState<DailyReportRun[]>([]);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [size] = useState(20);
  const [loading, setLoading] = useState(false);
  const [openRunId, setOpenRunId] = useState<number | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    fetchDailyReportRunsPage(job.id, page, size)
      .then((p) => {
        if (cancelled) return;
        setItems(p.items);
        setTotal(p.total);
      })
      .catch((e) => {
        if (e instanceof AdminRequiredError) onAdminLost();
        else toast.error(e instanceof Error ? e.message : String(e));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [job.id, page, size, onAdminLost]);

  const totalPages = Math.max(1, Math.ceil(total / size));

  return (
    <Drawer onClose={onClose} title={`历史记录 · ${job.name}`}>
      <div className="flex-1 overflow-y-auto">
        {loading ? (
          <div className="px-5 py-8 text-center text-sm" style={{ color: "var(--text-mute)" }}>
            加载中…
          </div>
        ) : items.length === 0 ? (
          <div className="px-5 py-10 text-center text-sm" style={{ color: "var(--text-mute)" }}>
            暂无历史
          </div>
        ) : (
          items.map((r) => (
            <RunRow
              key={r.id}
              run={r}
              isOpen={openRunId === r.id}
              onToggle={() => setOpenRunId(openRunId === r.id ? null : r.id)}
              onAdminLost={onAdminLost}
            />
          ))
        )}
      </div>
      <div
        className="flex items-center justify-between gap-2 border-t px-5 py-3"
        style={{ borderColor: "var(--line)" }}
      >
        <span className="text-[12px]" style={{ color: "var(--text-mute)" }}>
          共 {total} 条 · 第 {page}/{totalPages} 页
        </span>
        <div className="flex items-center gap-1.5">
          <Button
            size="sm"
            variant="ghost"
            disabled={page <= 1 || loading}
            onClick={() => setPage(page - 1)}
          >
            上一页
          </Button>
          <Button
            size="sm"
            variant="ghost"
            disabled={page >= totalPages || loading}
            onClick={() => setPage(page + 1)}
          >
            下一页
          </Button>
        </div>
      </div>
    </Drawer>
  );
}

function RunRow({
  run,
  isOpen,
  onToggle,
  onAdminLost,
}: {
  run: DailyReportRun;
  isOpen: boolean;
  onToggle: () => void;
  onAdminLost: () => void;
}) {
  const [detail, setDetail] = useState<DailyReportRunDetail | null>(null);
  const [loadingDetail, setLoadingDetail] = useState(false);

  useEffect(() => {
    if (!isOpen || detail) return;
    setLoadingDetail(true);
    fetchDailyReportRun(run.id)
      .then(setDetail)
      .catch((e) => {
        if (e instanceof AdminRequiredError) onAdminLost();
        else toast.error(e instanceof Error ? e.message : String(e));
      })
      .finally(() => setLoadingDetail(false));
  }, [isOpen, detail, run.id, onAdminLost]);

  const badge = lastStatusBadge(run.status);
  const trigger = {
    scheduled: "定时",
    manual: "手动",
    retry: "立即/重试",
    makeup: "补跑",
  }[run.trigger_type];

  return (
    <div
      className="border-t first:border-t-0"
      style={{ borderColor: "var(--line)" }}
    >
      <button
        type="button"
        onClick={onToggle}
        className="flex w-full items-center justify-between gap-3 px-5 py-3 text-left transition-colors hover:bg-[var(--surface-alt)]"
      >
        <div className="flex min-w-0 flex-1 flex-col gap-0.5">
          <div className="flex items-center gap-2 flex-wrap">
            <span
              className="text-[12px] font-mono"
              style={{ color: "var(--text)" }}
            >
              {fmtFullTime(run.started_at)}
            </span>
            {badge && (
              <span
                className="rounded px-1.5 py-0.5 text-[10px]"
                style={{ background: badge.bg, color: badge.color }}
              >
                {badge.text}
              </span>
            )}
            <span
              className="text-[10px] rounded px-1.5 py-0.5"
              style={{ background: "var(--surface-alt)", color: "var(--text-mute)" }}
            >
              {trigger}
            </span>
            {run.cards_total !== null && (
              <span
                className="text-[11px]"
                style={{ color: "var(--text-mute)" }}
              >
                {run.cards_sent ?? 0}/{run.cards_total} 卡片
              </span>
            )}
          </div>
          {run.error && (
            <div
              className="truncate text-[11.5px]"
              style={{ color: "var(--warn-600, #B43E3E)" }}
            >
              {run.error}
            </div>
          )}
        </div>
        <ChevronRight
          className="h-4 w-4 flex-none transition-transform"
          style={{
            color: "var(--text-mute)",
            transform: isOpen ? "rotate(90deg)" : undefined,
          }}
        />
      </button>
      {isOpen && (
        <div
          className="px-5 pb-4"
          style={{ borderTop: "1px dashed var(--line)" }}
        >
          {loadingDetail || !detail ? (
            <div className="py-2 text-[12px]" style={{ color: "var(--text-mute)" }}>
              加载详情…
            </div>
          ) : (
            <div className="flex flex-col gap-1.5 py-2">
              <DetailRow k="run_id" v={String(detail.id)} />
              <DetailRow k="started" v={fmtFullTime(detail.started_at)} />
              <DetailRow k="finished" v={detail.finished_at ? fmtFullTime(detail.finished_at) : "—"} />
              <DetailRow k="rc" v={detail.rc !== null ? String(detail.rc) : "—"} />
              {detail.debug_json && (
                <details className="mt-1.5">
                  <summary
                    className="cursor-pointer text-[11.5px]"
                    style={{ color: "var(--accent)" }}
                  >
                    debug payload
                  </summary>
                  <pre
                    className="mt-1.5 max-h-60 overflow-auto rounded p-2.5 text-[11px]"
                    style={{
                      background: "var(--surface-alt)",
                      color: "var(--text-soft)",
                      fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
                    }}
                  >
                    {pretty(detail.debug_json)}
                  </pre>
                </details>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function DetailRow({ k, v }: { k: string; v: string }) {
  return (
    <div className="flex gap-2 text-[11.5px]">
      <span style={{ color: "var(--text-mute)", minWidth: 56 }}>{k}</span>
      <span
        style={{
          color: "var(--text-soft)",
          fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
        }}
      >
        {v}
      </span>
    </div>
  );
}

function pretty(json: string): string {
  try {
    return JSON.stringify(JSON.parse(json), null, 2);
  } catch {
    return json;
  }
}

function fmtFullTime(iso: string): string {
  try {
    return new Date(iso).toLocaleString("zh-CN");
  } catch {
    return iso;
  }
}

// --------------------------------------------------------------------------
// ManualTriggerCard — 紧凑布局,接收人折叠
// --------------------------------------------------------------------------

function ManualTriggerCard({
  onAdminLost,
  chats,
}: {
  onAdminLost: () => void;
  chats: FeishuChat[];
}) {
  const [view, setView] = useState<"company" | "personal">("company");
  const [windowMode, setWindowMode] = useState<"hours" | "range">("hours");
  const [windowHours, setWindowHours] = useState<number | null>(24);
  // datetime-local input 值(无时区,后端按 Asia/Shanghai 解释)
  const [sinceLocal, setSinceLocal] = useState<string>("");
  const [untilLocal, setUntilLocal] = useState<string>("");
  const [receiverType, setReceiverType] = useState<"groups" | "users">("groups");
  const [receiverIds, setReceiverIds] = useState<string[]>([]);
  const [openIdNames, setOpenIdNames] = useState<Record<string, string>>({});
  const [receiverOpen, setReceiverOpen] = useState(false);
  const [pollingRunId, setPollingRunId] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [lastRun, setLastRun] = useState<DailyReportRunDetail | null>(null);

  useEffect(() => {
    if (!pollingRunId) return;
    let cancelled = false;
    const tick = async () => {
      try {
        const r = await fetchDailyReportRun(pollingRunId);
        if (cancelled) return;
        setLastRun(r);
        if (r.finished_at) {
          setPollingRunId(null);
          if (r.status === "succeeded") {
            toast.success(`运行成功 (run_id ${r.id})`);
          } else if (r.status === "partial") {
            toast.warning(`部分成功 (run_id ${r.id})`);
          } else {
            toast.error(`运行失败 (run_id ${r.id}): ${r.error || "—"}`);
          }
        }
      } catch {
        /* ignore polling error */
      }
    };
    const t = window.setInterval(tick, 2500);
    return () => {
      cancelled = true;
      window.clearInterval(t);
    };
  }, [pollingRunId]);

  // 切到"时间区间"模式时,如果还没填,默认填过去 24h
  useEffect(() => {
    if (windowMode !== "range") return;
    if (sinceLocal || untilLocal) return;
    const now = new Date();
    const past = new Date(now.getTime() - 24 * 3600 * 1000);
    setSinceLocal(toLocalInputValue(past));
    setUntilLocal(toLocalInputValue(now));
  }, [windowMode, sinceLocal, untilLocal]);

  const trigger = async () => {
    if (receiverType === "users" && receiverIds.length === 0) {
      return toast.error("接收类型为个人时,至少选 1 个 open_id");
    }
    // 构造 body —— 按窗口模式分支
    const body: Parameters<typeof manualTriggerDailyReport>[0] = {
      view,
      receiver_type: receiverType,
      receiver_ids: receiverIds.length > 0 ? receiverIds : null,
    };
    if (windowMode === "range") {
      if (!sinceLocal || !untilLocal) {
        return toast.error("时间区间模式需要填写起止时间");
      }
      if (sinceLocal >= untilLocal) {
        return toast.error("起始时间必须早于结束时间");
      }
      // datetime-local 给的是 YYYY-MM-DDTHH:mm,补 :00 凑成完整 ISO
      body.since = `${sinceLocal}:00`;
      body.until = `${untilLocal}:00`;
    } else {
      body.window_hours = windowHours ?? 24;
    }
    setBusy(true);
    try {
      const r = await manualTriggerDailyReport(body);
      toast.message(`已开始 run_id=${r.run_id}`);
      setPollingRunId(r.run_id);
      setLastRun(null);
    } catch (e) {
      if (e instanceof AdminRequiredError) onAdminLost();
      else toast.error(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const receiverSummaryText =
    receiverType === "groups"
      ? receiverIds.length === 0
        ? "全部 bot 群"
        : `${receiverIds.length} 个群`
      : `${receiverIds.length} 人 DM`;

  return (
    <ACard>
      <CardHead
        title="手动触发"
        desc="不绑定时任务,用于补发 / 排查 / 单次执行"
        trailing={
          <span
            className="inline-flex items-center gap-1.5 text-[12px]"
            style={{ color: "var(--text-mute)" }}
          >
            <Bell className="h-3.5 w-3.5" />
            异步运行
          </span>
        }
      />
      <div className="px-5 py-4 flex flex-col gap-3.5">
        {/* 视角 + 窗口模式选择 */}
        <div className="grid gap-3 sm:grid-cols-2">
          <div className="flex flex-col gap-1.5">
            <FieldLabel>视角</FieldLabel>
            <select
              value={view}
              onChange={(e) => setView(e.target.value as "company" | "personal")}
              className="h-[34px] rounded-md border bg-white px-3 text-[13px]"
              style={{ borderColor: "var(--line-strong, var(--line))" }}
            >
              <option value="company">公司视角</option>
              <option value="personal">个人视角</option>
            </select>
          </div>
          <div className="flex flex-col gap-1.5">
            <FieldLabel>窗口模式</FieldLabel>
            <div
              className="flex h-[34px] items-center gap-4 rounded-md border bg-white px-3 text-[13px]"
              style={{ borderColor: "var(--line-strong, var(--line))" }}
            >
              <label className="inline-flex items-center gap-1.5 cursor-pointer">
                <input
                  type="radio"
                  name="manual-window-mode"
                  checked={windowMode === "hours"}
                  onChange={() => setWindowMode("hours")}
                />
                <span>统计窗口</span>
              </label>
              <label className="inline-flex items-center gap-1.5 cursor-pointer">
                <input
                  type="radio"
                  name="manual-window-mode"
                  checked={windowMode === "range"}
                  onChange={() => setWindowMode("range")}
                />
                <span>时间区间</span>
              </label>
            </div>
          </div>
        </div>

        {/* 窗口具体输入 — 按模式分支 */}
        {windowMode === "hours" ? (
          <div className="flex flex-col gap-1.5">
            <FieldLabel htmlFor="manual-window">统计窗口(小时)</FieldLabel>
            <Input
              id="manual-window"
              type="number"
              min={1}
              max={168}
              value={windowHours ?? ""}
              onChange={(e) => {
                const v = e.target.value;
                if (v === "") {
                  setWindowHours(null);
                  return;
                }
                const n = Number(v);
                if (!Number.isNaN(n)) setWindowHours(n);
              }}
              onBlur={() => {
                if (windowHours === null || windowHours < 1)
                  setWindowHours(24);
              }}
            />
            <FieldHelp>1–168 小时,从当前时间倒推</FieldHelp>
          </div>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="flex flex-col gap-1.5">
              <FieldLabel htmlFor="manual-since">起始时间</FieldLabel>
              <Input
                id="manual-since"
                type="datetime-local"
                value={sinceLocal}
                onChange={(e) => setSinceLocal(e.target.value)}
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <FieldLabel htmlFor="manual-until">结束时间</FieldLabel>
              <Input
                id="manual-until"
                type="datetime-local"
                value={untilLocal}
                onChange={(e) => setUntilLocal(e.target.value)}
              />
            </div>
            <div className="sm:col-span-2">
              <FieldHelp>
                区间最长 168 小时(7 天),时区为 Asia/Shanghai
              </FieldHelp>
            </div>
          </div>
        )}

        {/* 接收人 — 折叠 */}
        <div
          className="rounded-md border"
          style={{ borderColor: "var(--line)", background: "var(--surface)" }}
        >
          <button
            type="button"
            onClick={() => setReceiverOpen((v) => !v)}
            className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left text-[13px] transition-colors hover:bg-[var(--surface-alt)]"
          >
            <span style={{ color: "var(--text-soft)" }}>
              接收人 · <span style={{ color: "var(--text)", fontWeight: 500 }}>{receiverSummaryText}</span>
            </span>
            <ChevronRight
              className="h-3.5 w-3.5 flex-none transition-transform"
              style={{
                color: "var(--text-mute)",
                transform: receiverOpen ? "rotate(90deg)" : undefined,
              }}
            />
          </button>
          {receiverOpen && (
            <div
              className="px-3 py-3 flex flex-col gap-2.5"
              style={{ borderTop: "1px solid var(--line)" }}
            >
              <div className="grid grid-cols-2 gap-2">
                <RadioCard
                  active={receiverType === "groups"}
                  onClick={() => {
                    setReceiverType("groups");
                    setReceiverIds([]);
                  }}
                  title="飞书群"
                  hint="不选群 = 全部 bot 群"
                />
                <RadioCard
                  active={receiverType === "users"}
                  onClick={() => {
                    setReceiverType("users");
                    setReceiverIds([]);
                  }}
                  title="个人 DM"
                  hint="必须至少选 1 人"
                />
              </div>
              {receiverType === "groups" ? (
                <FeishuChatMultiPick
                  chats={chats}
                  value={receiverIds}
                  onChange={setReceiverIds}
                />
              ) : (
                <OpenIdMultiPick
                  value={receiverIds}
                  onChange={setReceiverIds}
                  resolvedNames={openIdNames}
                  setResolvedNames={setOpenIdNames}
                />
              )}
            </div>
          )}
        </div>
      </div>
      <CardFoot
        hint={
          lastRun
            ? `上次:run_id=${lastRun.id} · ${lastRun.status}${lastRun.error ? " · " + lastRun.error : ""}`
            : pollingRunId
            ? `运行中:run_id=${pollingRunId} ...`
            : ""
        }
      >
        <Button
          onClick={trigger}
          disabled={busy || pollingRunId !== null}
          size="sm"
        >
          <Play className="mr-1.5 h-3.5 w-3.5" />
          {busy
            ? "启动中…"
            : pollingRunId
            ? "运行中…"
            : "立即触发"}
        </Button>
      </CardFoot>
    </ACard>
  );
}


// --------------------------------------------------------------------------
// Drawer (right-side slide-in)
// --------------------------------------------------------------------------

function Drawer({
  title,
  onClose,
  children,
}: {
  title: string;
  onClose: () => void;
  children: React.ReactNode;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-[70]">
      <div
        className="absolute inset-0"
        style={{ background: "rgba(31,26,20,.4)" }}
        onClick={onClose}
      />
      <div
        className="absolute right-0 top-0 flex h-[100dvh] w-[480px] max-w-[92vw] flex-col"
        style={{
          background: "var(--surface)",
          boxShadow: "-8px 0 32px rgba(0,0,0,.18)",
          borderLeft: "1px solid var(--line)",
        }}
      >
        <div
          className="flex items-center justify-between px-5 py-4"
          style={{ borderBottom: "1px solid var(--line)" }}
        >
          <h3
            className="m-0 truncate text-[14px] font-semibold"
            style={{ color: "var(--text)" }}
          >
            {title}
          </h3>
          <button
            type="button"
            onClick={onClose}
            aria-label="关闭"
            className="inline-flex h-7 w-7 items-center justify-center rounded-md"
            style={{ color: "var(--text-soft)" }}
          >
            <X className="h-4 w-4" />
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}

// --------------------------------------------------------------------------
// FeishuChatMultiPick
// --------------------------------------------------------------------------

function FeishuChatMultiPick({
  chats,
  value,
  onChange,
}: {
  chats: FeishuChat[];
  value: string[];
  onChange: (v: string[]) => void;
}) {
  const [open, setOpen] = useState(false);
  const [filter, setFilter] = useState("");
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onClick = (e: MouseEvent) => {
      if (!ref.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, [open]);

  const remove = (id: string) => onChange(value.filter((x) => x !== id));
  const toggle = (id: string) => {
    if (value.includes(id)) remove(id);
    else onChange([...value, id]);
  };

  const filtered = chats.filter((c) =>
    !filter ||
    c.name.toLowerCase().includes(filter.toLowerCase()) ||
    c.chat_id.toLowerCase().includes(filter.toLowerCase()),
  );

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex min-h-[34px] w-full flex-wrap items-center gap-1.5 rounded-md border bg-white px-2 py-1.5 text-left transition-colors"
        style={{ borderColor: "var(--line-strong, var(--line))" }}
      >
        {value.length === 0 ? (
          <span className="px-1 text-[12px]" style={{ color: "var(--text-mute)" }}>
            未选群组(默认 = 全部 bot 群)
          </span>
        ) : (
          value.map((id) => {
            const chat = chats.find((c) => c.chat_id === id);
            return (
              <span
                key={id}
                className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[11.5px]"
                style={{ background: "var(--accent-bg)", color: "var(--accent)" }}
              >
                <span>{chat?.name || id}</span>
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    remove(id);
                  }}
                  className="hover:opacity-70"
                >
                  <X className="h-3 w-3" />
                </button>
              </span>
            );
          })
        )}
      </button>
      {open && (
        <div
          className="absolute left-0 right-0 z-10 mt-1 max-h-72 overflow-hidden rounded-md border bg-white shadow-lg"
          style={{ borderColor: "var(--line)" }}
        >
          <div
            className="border-b p-1.5"
            style={{ borderColor: "var(--line)" }}
          >
            <Input
              placeholder="搜索群名 / chat_id"
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              autoFocus
            />
          </div>
          <div className="max-h-56 overflow-y-auto">
            {filtered.length === 0 ? (
              <div
                className="px-3 py-3 text-center text-[12px]"
                style={{ color: "var(--text-mute)" }}
              >
                {chats.length === 0 ? "未拉到 bot 群列表" : "无匹配"}
              </div>
            ) : (
              filtered.map((c) => {
                const sel = value.includes(c.chat_id);
                return (
                  <button
                    key={c.chat_id}
                    type="button"
                    onClick={() => toggle(c.chat_id)}
                    className="flex w-full items-center justify-between px-3 py-2 text-left text-[13px] transition-colors hover:bg-[var(--surface-alt)]"
                    style={{ color: "var(--text)" }}
                  >
                    <span className="truncate">{c.name || c.chat_id}</span>
                    <span
                      className="ml-2 h-4 w-4 flex-none rounded border"
                      style={{
                        borderColor: sel ? "var(--accent)" : "var(--line-strong, var(--line))",
                        background: sel ? "var(--accent)" : "transparent",
                      }}
                    >
                      {sel && (
                        <svg
                          viewBox="0 0 16 16"
                          width="14"
                          height="14"
                          style={{ color: "white" }}
                        >
                          <path
                            d="M3.5 8l3 3 6-6"
                            stroke="currentColor"
                            strokeWidth="2"
                            fill="none"
                            strokeLinecap="round"
                            strokeLinejoin="round"
                          />
                        </svg>
                      )}
                    </span>
                  </button>
                );
              })
            )}
          </div>
        </div>
      )}
    </div>
  );
}

// --------------------------------------------------------------------------
// OpenIdMultiPick
// --------------------------------------------------------------------------

function OpenIdMultiPick({
  value,
  onChange,
  resolvedNames,
  setResolvedNames,
}: {
  value: string[];
  onChange: (v: string[]) => void;
  resolvedNames: Record<string, string>;
  setResolvedNames: (v: Record<string, string>) => void;
}) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<Contact[]>([]);
  const [focused, setFocused] = useState(false);
  const [loading, setLoading] = useState(false);
  const debounceRef = useRef<number | null>(null);

  // 编辑已有 receiver_ids 时,把还没解析过的 open_id 批量查名字
  useEffect(() => {
    const missing = value.filter((id) => !resolvedNames[id]);
    if (missing.length === 0) return;
    let cancelled = false;
    fetchContactsByIds(missing)
      .then((contacts) => {
        if (cancelled) return;
        const next: Record<string, string> = { ...resolvedNames };
        for (const c of contacts) next[c.open_id] = c.name;
        setResolvedNames(next);
      })
      .catch(() => {
        /* swallow — 失败时降级显示 open_id */
      });
    return () => {
      cancelled = true;
    };
    // resolvedNames 故意不进 deps:它在解析后会被 setResolvedNames 更新,
    // 进 deps 会导致循环触发。value 变化才是真正的触发条件。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value]);

  useEffect(() => {
    if (debounceRef.current) window.clearTimeout(debounceRef.current);
    if (!focused) return;
    debounceRef.current = window.setTimeout(async () => {
      setLoading(true);
      try {
        setResults(await searchContacts(query));
      } catch {
        setResults([]);
      } finally {
        setLoading(false);
      }
    }, 250);
    return () => {
      if (debounceRef.current) window.clearTimeout(debounceRef.current);
    };
  }, [query, focused]);

  const add = (c: Contact) => {
    if (value.includes(c.open_id)) return;
    onChange([...value, c.open_id]);
    setResolvedNames({ ...resolvedNames, [c.open_id]: c.name });
    setQuery("");
  };
  const remove = (oid: string) => onChange(value.filter((x) => x !== oid));

  return (
    <div
      className="rounded-md border p-2"
      style={{ background: "var(--surface)", borderColor: "var(--line)" }}
    >
      <div
        className="flex min-h-[28px] flex-wrap items-center gap-1.5 rounded-md border bg-white p-1.5"
        style={{ borderColor: "var(--line-strong, var(--line))" }}
      >
        {value.map((oid) => (
          <span
            key={oid}
            className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[11.5px]"
            style={{ background: "var(--accent-bg)", color: "var(--accent)" }}
          >
            <span>{resolvedNames[oid] || oid}</span>
            <button
              type="button"
              onClick={() => remove(oid)}
              className="hover:opacity-70"
            >
              <X className="h-3 w-3" />
            </button>
          </span>
        ))}
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onFocus={() => setFocused(true)}
          onBlur={() => setTimeout(() => setFocused(false), 150)}
          placeholder={value.length === 0 ? "搜索成员姓名…" : ""}
          className="flex-1 bg-transparent text-[13px] outline-none min-w-[120px]"
          style={{ color: "var(--text)" }}
        />
      </div>
      {focused && (
        <div
          className="mt-1 max-h-48 overflow-y-auto rounded-md border"
          style={{ background: "var(--surface)", borderColor: "var(--line)" }}
        >
          {loading ? (
            <div
              className="px-3 py-2 text-[12px]"
              style={{ color: "var(--text-mute)" }}
            >
              搜索中…
            </div>
          ) : results.length === 0 ? (
            <div
              className="px-3 py-2 text-[12px]"
              style={{ color: "var(--text-mute)" }}
            >
              {query ? "无匹配" : "请输入姓名"}
            </div>
          ) : (
            results.map((c) => (
              <button
                key={c.open_id}
                type="button"
                onMouseDown={(e) => {
                  e.preventDefault();
                  add(c);
                }}
                className="flex w-full items-center justify-between px-3 py-2 text-left text-[13px] hover:bg-[var(--surface-alt)]"
              >
                <span style={{ color: "var(--text)" }}>{c.name}</span>
                {value.includes(c.open_id) && (
                  <span
                    className="text-[11px]"
                    style={{ color: "var(--accent)" }}
                  >
                    已选
                  </span>
                )}
              </button>
            ))
          )}
        </div>
      )}
    </div>
  );
}
