import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowLeft, Lock, Users } from "lucide-react";
import { toast, Toaster } from "sonner";
import {
  AdminRequiredError,
  clearAdminPassword,
  fetchAISettings,
  getAdminPassword,
  setAdminPassword,
  syncContacts,
  updateAISettings,
} from "@/api";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

const SUGGESTED_MODELS = [
  "anthropic/claude-sonnet-4-5",
  "anthropic/claude-haiku-4-5",
  "openai/gpt-4o-mini",
  "openai/gpt-4o",
  "google/gemini-flash-1.5",
];

export function AdminPage() {
  const [unlocked, setUnlocked] = useState<boolean>(!!getAdminPassword());

  return (
    <div className="min-h-screen bg-background">
      <Toaster position="top-center" richColors />
      <header className="border-b px-6 py-3">
        <div className="mx-auto flex max-w-3xl items-center gap-3">
          <Button asChild variant="ghost" size="sm">
            <Link to="/"><ArrowLeft className="h-4 w-4" /> 返回</Link>
          </Button>
          <h1 className="text-lg font-semibold">管理员设置</h1>
        </div>
      </header>

      {!unlocked ? (
        <AdminGate onUnlock={() => setUnlocked(true)} />
      ) : (
        <main className="mx-auto max-w-3xl space-y-8 px-6 py-8">
          <AISettingsSection onAdminLost={() => setUnlocked(false)} />
          <SyncContactsSection onAdminLost={() => setUnlocked(false)} />
        </main>
      )}
    </div>
  );
}

// ── Admin password gate ──────────────────────────────────────────────────────

function AdminGate({ onUnlock }: { onUnlock: () => void }) {
  const [pw, setPw] = useState("");

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!pw) return;
    setAdminPassword(pw);
    onUnlock();
  };

  return (
    <main className="mx-auto max-w-md px-6 py-12">
      <Card className="p-6">
        <div className="mb-4 flex items-center gap-2">
          <Lock className="h-5 w-5 text-amber-500" />
          <h2 className="text-base font-semibold">需要管理员密码</h2>
        </div>
        <p className="mb-4 text-sm text-muted-foreground">
          管理员设置（AI 配置、联系人同步）由管理员密码保护。密码仅在本浏览器会话中保留，关闭浏览器后清除。
        </p>
        <form onSubmit={submit} className="space-y-3">
          <Input
            type="password"
            placeholder="管理员密码"
            value={pw}
            onChange={(e) => setPw(e.target.value)}
            autoFocus
          />
          <Button type="submit" className="w-full" disabled={!pw}>
            进入管理员设置
          </Button>
        </form>
      </Card>
    </main>
  );
}

// ── AI settings ──────────────────────────────────────────────────────────────

function AISettingsSection({ onAdminLost }: { onAdminLost: () => void }) {
  const [model, setModel] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [hasKey, setHasKey] = useState(false);
  const [maxContextTokens, setMaxContextTokens] = useState(5000);
  const [minRounds, setMinRounds] = useState(3);
  const [maxRounds, setMaxRounds] = useState(20);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    fetchAISettings()
      .then((s) => {
        setModel(s.model);
        setHasKey(s.has_key);
        setMaxContextTokens(s.max_context_tokens);
        setMinRounds(s.min_rounds);
        setMaxRounds(s.max_rounds);
      })
      .catch((e) => {
        if (e instanceof AdminRequiredError) {
          toast.error("管理员密码已失效，请重新输入");
          onAdminLost();
        } else {
          toast.error(e.message);
        }
      })
      .finally(() => setLoading(false));
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const save = async () => {
    if (minRounds > maxRounds) {
      toast.error("最少轮数不能大于最多轮数");
      return;
    }
    setSaving(true);
    try {
      const body: Parameters<typeof updateAISettings>[0] = {
        model: model.trim() || undefined,
        max_context_tokens: maxContextTokens,
        min_rounds: minRounds,
        max_rounds: maxRounds,
      };
      if (apiKey.trim()) body.api_key = apiKey.trim();
      await updateAISettings(body);
      toast.success("AI 设置已保存");
      setApiKey("");
      setHasKey(true);
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
    <section>
      <h2 className="mb-3 text-sm font-semibold">AI 助手配置</h2>
      <Card className="space-y-5 p-6">
        {loading ? (
          <p className="text-sm text-muted-foreground">加载中…</p>
        ) : (
          <>
            <div className="space-y-2">
              <Label htmlFor="ai-key">
                OpenRouter API Key
                {hasKey && <span className="ml-2 text-xs text-green-600">（已配置）</span>}
              </Label>
              <Input
                id="ai-key"
                type="password"
                placeholder={hasKey ? "留空保持不变" : "sk-or-…"}
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
              />
              <p className="text-xs text-muted-foreground">
                在{" "}
                <a href="https://openrouter.ai/keys" target="_blank" rel="noreferrer" className="underline">
                  openrouter.ai/keys
                </a>{" "}
                获取
              </p>
            </div>

            <div className="space-y-2">
              <Label htmlFor="ai-model">模型</Label>
              <Input
                id="ai-model"
                placeholder="anthropic/claude-sonnet-4-5"
                value={model}
                onChange={(e) => setModel(e.target.value)}
              />
              <div className="flex flex-wrap gap-1.5">
                {SUGGESTED_MODELS.map((m) => (
                  <button
                    key={m}
                    type="button"
                    onClick={() => setModel(m)}
                    className={`rounded px-2 py-0.5 text-xs transition-colors ${
                      model === m
                        ? "bg-blue-100 text-blue-700 dark:bg-blue-950 dark:text-blue-300"
                        : "bg-muted text-muted-foreground hover:bg-zinc-200 dark:hover:bg-zinc-700"
                    }`}
                  >
                    {m}
                  </button>
                ))}
              </div>
            </div>

            <div className="space-y-3 rounded-lg border p-4">
              <p className="text-xs font-semibold text-muted-foreground">对话历史截断参数</p>
              <div className="grid grid-cols-3 gap-3">
                <div className="space-y-1">
                  <Label htmlFor="ai-max-tokens" className="text-xs">最大上下文 Token</Label>
                  <Input
                    id="ai-max-tokens"
                    type="number"
                    min={1000} max={200000} step={1000}
                    value={maxContextTokens}
                    onChange={(e) => setMaxContextTokens(Number(e.target.value))}
                    className="text-sm"
                  />
                  <p className="text-xs text-muted-foreground">
                    ≈ {(maxContextTokens * 4 / 1000).toFixed(0)}k 字符
                  </p>
                </div>
                <div className="space-y-1">
                  <Label htmlFor="ai-min-rounds" className="text-xs">最少保留轮数</Label>
                  <Input
                    id="ai-min-rounds" type="number" min={1} max={50}
                    value={minRounds}
                    onChange={(e) => setMinRounds(Number(e.target.value))}
                    className="text-sm"
                  />
                  <p className="text-xs text-muted-foreground">超限也强制带上</p>
                </div>
                <div className="space-y-1">
                  <Label htmlFor="ai-max-rounds" className="text-xs">最多保留轮数</Label>
                  <Input
                    id="ai-max-rounds" type="number" min={1} max={200}
                    value={maxRounds}
                    onChange={(e) => setMaxRounds(Number(e.target.value))}
                    className="text-sm"
                  />
                  <p className="text-xs text-muted-foreground">超出即截断</p>
                </div>
              </div>
            </div>

            <div className="flex justify-end">
              <Button onClick={save} disabled={saving}>
                {saving ? "保存中…" : "保存"}
              </Button>
            </div>
          </>
        )}
      </Card>
    </section>
  );
}

// ── Sync Contacts ─────────────────────────────────────────────────────────────

function SyncContactsSection({ onAdminLost }: { onAdminLost: () => void }) {
  const [syncing, setSyncing] = useState(false);

  const onSync = async () => {
    setSyncing(true);
    try {
      const r = await syncContacts();
      toast.success(`同步完成：共 ${r.total} 位联系人（刷新 ${r.synced}）`);
    } catch (e) {
      if (e instanceof AdminRequiredError) {
        onAdminLost();
      } else {
        toast.error(e instanceof Error ? e.message : String(e));
      }
    } finally {
      setSyncing(false);
    }
  };

  return (
    <section>
      <h2 className="mb-3 text-sm font-semibold">联系人同步</h2>
      <Card className="p-6">
        <p className="mb-4 text-xs text-muted-foreground">
          从飞书通讯录拉取最新联系人列表，供 @提及 功能使用。此操作会访问飞书 API，仅管理员需要定期执行。
        </p>
        <Button size="sm" onClick={onSync} disabled={syncing}>
          <Users className={`mr-1.5 h-4 w-4 ${syncing ? "animate-spin" : ""}`} />
          {syncing ? "同步中…" : "立即同步联系人"}
        </Button>
      </Card>
    </section>
  );
}

export { clearAdminPassword };
