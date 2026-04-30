import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowLeft } from "lucide-react";
import {
  createInvite,
  listInvites,
  revokeInvite,
  type AdminInvite,
  type CreatedInvite,
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

export function AdminInvites() {
  const [items, setItems] = useState<AdminInvite[]>([]);
  const [includeUsed, setIncludeUsed] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [createdInvite, setCreatedInvite] = useState<CreatedInvite | null>(null);

  const reload = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const r = await listInvites(includeUsed);
      setItems(r.items);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [includeUsed]);

  useEffect(() => {
    void reload();
  }, [reload]);

  return (
    <div className="mx-auto max-w-3xl p-6">
      <header className="mb-5 flex items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <Link
            to="/admin"
            className="inline-flex items-center gap-1 text-[12.5px] font-meta hover:text-[var(--text)]"
            style={{ color: "var(--text-mute)" }}
          >
            <ArrowLeft className="h-3.5 w-3.5" /> 返回
          </Link>
          <h1 className="m-0 text-[22px]" style={titleStyle}>
            邀请管理
          </h1>
        </div>
        <div className="flex items-center gap-3">
          <label
            className="flex items-center gap-1.5 text-[12.5px] font-meta"
            style={{ color: "var(--text-mute)" }}
          >
            <input
              type="checkbox"
              checked={includeUsed}
              onChange={(e) => setIncludeUsed(e.target.checked)}
            />
            含已使用
          </label>
          <Button
            onClick={() => setCreateOpen(true)}
            className="h-9 rounded-[var(--r-sm)] px-4 text-[13px] font-semibold shadow-none"
            style={{
              background: "var(--accent)",
              color: "var(--accent-ink)",
              border: "1px solid var(--accent)",
            }}
          >
            创建邀请
          </Button>
        </div>
      </header>

      {loading && <p style={mutedStyle}>加载中…</p>}
      {error && (
        <p className="text-[13px]" style={{ color: "var(--danger-500)" }}>
          {error}
        </p>
      )}
      {!loading && !error && items.length === 0 && (
        <p style={mutedStyle}>没有邀请记录。</p>
      )}

      <ul className="flex flex-col gap-2">
        {items.map((i) => (
          <InviteRow key={i.id} invite={i} onChanged={reload} />
        ))}
      </ul>

      <CreateInviteDialog
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        onCreated={(inv) => {
          setCreatedInvite(inv);
          setCreateOpen(false);
          void reload();
        }}
      />

      <CreatedTokenDialog
        invite={createdInvite}
        onClose={() => setCreatedInvite(null)}
      />
    </div>
  );
}

function InviteRow({
  invite,
  onChanged,
}: {
  invite: AdminInvite;
  onChanged: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const used = invite.used_at !== null;
  const expired = invite.expires_at * 1000 < Date.now();

  const tag: { label: string; color: string } = used
    ? { label: "已使用", color: "var(--text-mute)" }
    : expired
      ? { label: "已过期", color: "var(--danger-500)" }
      : { label: "待使用", color: "var(--accent)" };

  const revoke = async () => {
    setBusy(true);
    setError(null);
    try {
      await revokeInvite(invite.id);
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <li
      className="rounded-[var(--r-md)] p-3.5"
      style={{
        background: "var(--surface)",
        border: "1px solid var(--line)",
        opacity: used || expired ? 0.6 : 1,
      }}
    >
      <div className="flex items-center justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span
              className="truncate text-[14px] font-semibold"
              style={{ color: "var(--text)" }}
            >
              {invite.email}
            </span>
            <span
              className="rounded-full px-2 py-0.5 text-[10.5px] font-bold tracking-wider font-meta"
              style={{
                background: "var(--surface-alt)",
                color: tag.color,
                border: `1px solid ${tag.color}`,
              }}
            >
              {tag.label}
            </span>
          </div>
          <div className="mt-0.5 truncate text-[12px] font-meta" style={mutedStyle}>
            {invite.display_name ? `${invite.display_name} · ` : ""}
            创建于 {new Date(invite.created_at * 1000).toLocaleString()}
            {!used && !expired && (
              <> · {formatExpires(invite.expires_at)}</>
            )}
            {used && invite.used_at && (
              <> · 使用于 {new Date(invite.used_at * 1000).toLocaleString()}</>
            )}
          </div>
        </div>

        {!used && !expired && (
          <Button
            variant="ghost"
            size="sm"
            disabled={busy}
            onClick={revoke}
            style={{ color: "var(--danger-500)" }}
          >
            撤销
          </Button>
        )}
      </div>
      {error && (
        <p className="mt-2 text-[12px]" style={{ color: "var(--danger-500)" }}>
          {error}
        </p>
      )}
    </li>
  );
}

function CreateInviteDialog({
  open,
  onClose,
  onCreated,
}: {
  open: boolean;
  onClose: () => void;
  onCreated: (i: CreatedInvite) => void;
}) {
  const [email, setEmail] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [ttlDays, setTtlDays] = useState(7);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) {
      setEmail("");
      setDisplayName("");
      setTtlDays(7);
      setError(null);
    }
  }, [open]);

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      const inv = await createInvite(
        email.trim(),
        displayName.trim() || undefined,
        ttlDays,
      );
      onCreated(inv);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>创建邀请</DialogTitle>
          <DialogDescription>
            生成一条用于邮箱密码登录的一次性邀请链接。链接里的 token 仅会展示
            一次，请尽快复制发给被邀请人。
          </DialogDescription>
        </DialogHeader>
        <div className="grid gap-3">
          <div>
            <Label className="text-[12.5px]">邮箱</Label>
            <Input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="alice@company.com"
              autoFocus
            />
          </div>
          <div>
            <Label className="text-[12.5px]">显示名（可选）</Label>
            <Input
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              placeholder="Alice"
            />
          </div>
          <div>
            <Label className="text-[12.5px]">有效期（天）</Label>
            <Input
              type="number"
              min={1}
              max={90}
              value={ttlDays}
              onChange={(e) => setTtlDays(Number(e.target.value) || 7)}
            />
          </div>
          {error && (
            <p className="text-[12px]" style={{ color: "var(--danger-500)" }}>
              {error}
            </p>
          )}
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={onClose}>
            取消
          </Button>
          <Button
            disabled={busy || !email}
            onClick={submit}
            style={{
              background: "var(--accent)",
              color: "var(--accent-ink)",
              border: "1px solid var(--accent)",
            }}
          >
            {busy ? "生成中…" : "生成邀请链接"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function CreatedTokenDialog({
  invite,
  onClose,
}: {
  invite: CreatedInvite | null;
  onClose: () => void;
}) {
  const [copied, setCopied] = useState(false);

  if (!invite) return null;

  const link = `${window.location.origin}${invite.link_path}`;

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(link);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // 忽略，让用户手动复制
    }
  };

  return (
    <Dialog open={true} onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>邀请已创建</DialogTitle>
          <DialogDescription>
            <strong>这条链接只展示一次。</strong>关闭后无法再次取得 token，
            如果忘了请撤销重建。
          </DialogDescription>
        </DialogHeader>
        <div
          className="rounded-[var(--r-sm)] p-3 text-[12.5px] font-mono break-all"
          style={{
            background: "var(--surface-alt)",
            border: "1px solid var(--accent)",
            color: "var(--text)",
          }}
        >
          {link}
        </div>
        <p className="text-[12px] font-meta" style={{ color: "var(--text-mute)" }}>
          邀请发给 <strong>{invite.email}</strong>，
          {formatExpires(invite.expires_at)}。
        </p>
        <DialogFooter>
          <Button variant="ghost" onClick={onClose}>
            我已保存，关闭
          </Button>
          <Button
            onClick={copy}
            style={{
              background: copied ? "var(--accent-bg)" : "var(--accent)",
              color: copied ? "var(--accent)" : "var(--accent-ink)",
              border: "1px solid var(--accent)",
            }}
          >
            {copied ? "已复制 ✓" : "复制链接"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function formatExpires(expiresAt: number): string {
  const ms = expiresAt * 1000 - Date.now();
  if (ms <= 0) return "已过期";
  const hours = ms / 1000 / 3600;
  if (hours < 24) return `${Math.max(1, Math.round(hours))} 小时后过期`;
  return `${Math.round(hours / 24)} 天后过期`;
}

const titleStyle: React.CSSProperties = {
  fontFamily: "var(--font-serif)",
  fontWeight: 600,
  letterSpacing: "var(--letter-tight)",
  color: "var(--text)",
};

const mutedStyle: React.CSSProperties = {
  color: "var(--text-mute)",
  fontSize: "13px",
};
