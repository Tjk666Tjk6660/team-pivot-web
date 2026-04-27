import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowLeft, Copy, KeyRound, Plus, Trash2 } from "lucide-react";
import { toast, Toaster } from "sonner";
import {
  createApiToken,
  deleteApiToken,
  fetchApiTokens,
  type ApiTokenCreated,
  type ApiTokenSummary,
} from "@/api";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export function SettingsPage() {
  return (
    <div className="min-h-screen" style={{ background: "var(--bg)" }}>
      <Toaster position="top-center" richColors />
      <header
        className="px-6 py-3"
        style={{
          borderBottom: "1px solid var(--line)",
          background: "var(--surface)",
        }}
      >
        <div className="mx-auto flex max-w-3xl items-center gap-3">
          <Button
            asChild
            variant="ghost"
            size="sm"
            className="h-8 rounded-md hover:bg-[var(--surface-alt)]"
            style={{ color: "var(--text-soft)" }}
          >
            <Link to="/"><ArrowLeft className="h-4 w-4" /> 返回</Link>
          </Button>
          <h1
            className="text-[16px] font-semibold"
            style={{
              fontFamily: "var(--font-serif)",
              letterSpacing: "var(--letter-tight)",
              color: "var(--text)",
            }}
          >
            个人设置
          </h1>
        </div>
      </header>
      <main className="mx-auto max-w-3xl space-y-8 px-6 py-8">
        <ApiTokensSection />
      </main>
    </div>
  );
}

// ── API Tokens ───────────────────────────────────────────────────────────────

function ApiTokensSection() {
  const [items, setItems] = useState<ApiTokenSummary[] | null>(null);
  const [creating, setCreating] = useState(false);
  const [newToken, setNewToken] = useState<ApiTokenCreated | null>(null);

  const load = async () => {
    try {
      setItems(await fetchApiTokens());
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
    }
  };

  useEffect(() => { load(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const onRevoke = async (id: string, name: string) => {
    if (!confirm(`撤销 token「${name}」？使用此 token 的客户端会立即失效。`)) return;
    try {
      await deleteApiToken(id);
      toast.success("已撤销");
      load();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <section>
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h2
            className="text-[20px] font-semibold"
            style={{
              fontFamily: "var(--font-serif)",
              letterSpacing: "var(--letter-tight)",
              color: "var(--text)",
            }}
          >
            API Token
          </h2>
          <p
            className="mt-1 text-[13px] leading-[1.6]"
            style={{ fontFamily: "var(--font-serif)", color: "var(--text-soft)" }}
          >
            个人访问令牌。给脚本或 CLI 用。撤销后即刻失效。
          </p>
        </div>
        <Button
          size="sm"
          onClick={() => setCreating(true)}
          className="h-8 rounded-md px-3 text-[12.5px] font-semibold shadow-none"
          style={{
            background: "var(--accent)",
            color: "var(--accent-ink)",
            border: "1px solid var(--accent)",
          }}
        >
          <Plus className="mr-1 h-3.5 w-3.5" />
          新建 Token
        </Button>
      </div>
      <Card className="p-6">
        <p className="mb-4 text-xs text-muted-foreground">
          供 Team Pivot VS Code 插件等外部 API 客户端使用。Token 拥有当前账号的全部 API 权限（不含设置页面），请妥善保管。
        </p>
        {items === null ? (
          <p className="text-sm text-muted-foreground">加载中…</p>
        ) : items.length === 0 ? (
          <p className="text-sm text-muted-foreground">还没有 token。点击右上角「新建 Token」开始。</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-left text-xs text-muted-foreground">
                <tr className="border-b">
                  <th className="py-2 pr-3">名称</th>
                  <th className="py-2 pr-3">创建</th>
                  <th className="py-2 pr-3">最后使用</th>
                  <th className="py-2 pr-3">过期</th>
                  <th className="py-2 pr-3 text-right">操作</th>
                </tr>
              </thead>
              <tbody>
                {items.map((t) => (
                  <tr key={t.id} className="border-b last:border-b-0">
                    <td className="py-2 pr-3">
                      <div className="font-medium">{t.name}</div>
                      <div className="font-mono text-xs text-muted-foreground">id {t.id}</div>
                    </td>
                    <td className="py-2 pr-3 text-xs">{fmtDate(t.created_at)}</td>
                    <td className="py-2 pr-3 text-xs">
                      {t.last_used_at ? fmtDate(t.last_used_at) : <span className="text-muted-foreground">从未</span>}
                    </td>
                    <td className="py-2 pr-3 text-xs">{fmtDate(t.expires_at)}</td>
                    <td className="py-2 pr-3 text-right">
                      <Button
                        size="sm" variant="ghost"
                        className="h-7 px-2 text-destructive"
                        onClick={() => onRevoke(t.id, t.name)}
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <CreateTokenDialog
        open={creating}
        onClose={() => setCreating(false)}
        onCreated={(t) => {
          setCreating(false);
          setNewToken(t);
          load();
        }}
      />

      <NewTokenDialog token={newToken} onClose={() => setNewToken(null)} />
    </section>
  );
}

function CreateTokenDialog({
  open, onClose, onCreated,
}: {
  open: boolean;
  onClose: () => void;
  onCreated: (t: ApiTokenCreated) => void;
}) {
  const [name, setName] = useState("");
  const [ttl, setTtl] = useState<number | "">(90);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (open) { setName(""); setTtl(90); }
  }, [open]);

  const submit = async () => {
    if (!name.trim()) return;
    setSubmitting(true);
    try {
      const t = await createApiToken(name.trim(), ttl === "" ? 90 : ttl);
      onCreated(t);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>新建 API Token</DialogTitle>
        </DialogHeader>
        <div className="space-y-4 py-2">
          <div className="space-y-1.5">
            <Label htmlFor="token-name">名称</Label>
            <Input
              id="token-name"
              placeholder="例如：MacBook Pro / VS Code"
              value={name}
              onChange={(e) => setName(e.target.value)}
              autoFocus
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="token-ttl">有效期（天）</Label>
            <Input
              id="token-ttl"
              type="number"
              min={1} max={365}
              value={ttl}
              onChange={(e) => {
                const v = e.target.value;
                setTtl(v === "" ? "" : Number(v));
              }}
            />
            <p className="text-xs text-muted-foreground">默认 90 天，最多 365 天</p>
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={submitting}>取消</Button>
          <Button onClick={submit} disabled={submitting || !name.trim()}>
            {submitting ? "创建中…" : "创建"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function NewTokenDialog({
  token, onClose,
}: {
  token: ApiTokenCreated | null;
  onClose: () => void;
}) {
  const open = token !== null;

  const copy = async () => {
    if (!token) return;
    try {
      await navigator.clipboard.writeText(token.token);
      toast.success("已复制到剪贴板");
    } catch {
      toast.error("复制失败，请手动选择文本");
    }
  };

  return (
    <Dialog open={open} onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <KeyRound className="h-5 w-5 text-[var(--warn-500)]" />
            Token 已创建
          </DialogTitle>
        </DialogHeader>
        {token && (
          <div className="space-y-3 py-2">
            <div className="rounded-[var(--r-sm)] border-2 border-[color-mix(in_srgb,var(--warn-500)_35%,var(--line))] bg-[color-mix(in_srgb,var(--warn-500)_10%,var(--surface))] p-3 text-xs text-[var(--warn-600)]">
              ⚠️ <strong>请立即复制并妥善保存。</strong>关闭此窗口后将无法再次查看。
            </div>
            <div className="rounded-md bg-muted p-3 font-mono text-xs break-all">
              {token.token}
            </div>
            <Button onClick={copy} className="w-full">
              <Copy className="mr-1.5 h-4 w-4" /> 复制 Token
            </Button>
            <p className="text-xs text-muted-foreground">
              在 VS Code 插件中粘贴此 token，或通过 <code>Authorization: Bearer &lt;token&gt;</code> 调用 API。
            </p>
          </div>
        )}
        <DialogFooter>
          <Button onClick={onClose}>我已保存，关闭</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function fmtDate(epoch: number): string {
  const d = new Date(epoch * 1000);
  return d.toLocaleString();
}

// Re-export for convenience
export { clearAdminPassword } from "@/api";
