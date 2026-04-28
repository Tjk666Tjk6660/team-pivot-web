import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowLeft, Bot, FolderGit2, Lock, Palette, ShieldCheck, Users } from "lucide-react";
import { toast, Toaster } from "sonner";
import {
  AdminRequiredError,
  clearAdminPassword,
  fetchAdminMarkdownSettings,
  fetchAISettings,
  fetchWorkspaceAdminConfig,
  setAdminPassword,
  syncContacts,
  updateAdminMarkdownSettings,
  updateAISettings,
  updateWorkspaceAdminConfig,
  type MarkdownStyleMeta,
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

const SUGGESTED_MODELS = [
  "anthropic/claude-sonnet-4-5",
  "anthropic/claude-haiku-4-5",
  "openai/gpt-4o-mini",
  "openai/gpt-4o",
  "google/gemini-flash-1.5",
];

const MARKDOWN_STYLE_SWATCHES: Record<string, { bg: string; accent: string; code: string }> = {
  "code-light": { bg: "#ffffff", accent: "#0969da", code: "#f6f8fa" },
  "collab-blue": { bg: "#f3f7ff", accent: "#3370ff", code: "#dbe8ff" },
  "page-brown": { bg: "#fffdf7", accent: "#9b3f1b", code: "#2e241b" },
  "solarized-light": { bg: "#fdf6e3", accent: "#cb4b16", code: "#073642" },
  "neon-dark": { bg: "#282a36", accent: "#ff79c6", code: "#191a21" },
  "nord-dark": { bg: "#2e3440", accent: "#88c0d0", code: "#242933" },
};

export function AdminPage() {
  const [unlocked, setUnlocked] = useState(false);

  useEffect(() => {
    clearAdminPassword();
    setUnlocked(false);
  }, []);

  return (
    <div className="min-h-screen" style={{ background: "var(--bg)" }}>
      <Toaster position="top-center" richColors />
      <header
        className="px-6 py-4 backdrop-blur"
        style={{
          borderBottom: "1px solid var(--line)",
          background: "rgba(255, 253, 248, 0.94)",
        }}
      >
        <div className="mx-auto flex max-w-7xl items-center gap-4">
          <Button
            asChild
            variant="ghost"
            size="sm"
            className="h-8 rounded-md hover:bg-[var(--surface-alt)]"
            style={{ color: "var(--text-soft)" }}
          >
            <Link to="/"><ArrowLeft className="h-4 w-4" /> 返回</Link>
          </Button>
          <div className="min-w-0">
            <h1
              className="text-[16px] font-semibold"
              style={{
                fontFamily: "var(--font-serif)",
                letterSpacing: "var(--letter-tight)",
                color: "var(--text)",
              }}
            >
              管理员设置
            </h1>
            <p
              className="mt-0.5 text-[11.5px] font-meta"
              style={{ color: "var(--text-mute)" }}
            >
              管理数据仓库 · AI 助手 · 联系人同步
            </p>
          </div>
          <div className="ml-auto hidden items-center gap-2 lg:flex">
            <InfoChip icon={<FolderGit2 className="h-3.5 w-3.5" />} label="Repo + Token" />
            <InfoChip icon={<Bot className="h-3.5 w-3.5" />} label="AI Model + Key" />
            <InfoChip icon={<ShieldCheck className="h-3.5 w-3.5" />} label="Admin Session" />
          </div>
        </div>
      </header>

      {!unlocked ? (
        <AdminGate onUnlock={() => setUnlocked(true)} />
      ) : (
        <main className="mx-auto max-w-7xl px-6 py-8">
          <AdminIntro />
          <div className="mt-6 grid gap-6 lg:grid-cols-[minmax(0,1.2fr)_minmax(360px,0.8fr)]">
            <div className="space-y-6">
              <WorkspaceConfigSection onAdminLost={() => setUnlocked(false)} />
              <SyncContactsSection onAdminLost={() => setUnlocked(false)} />
            </div>
            <div className="space-y-6">
              <MarkdownSettingsSection onAdminLost={() => setUnlocked(false)} />
              <AISettingsSection onAdminLost={() => setUnlocked(false)} />
            </div>
          </div>
        </main>
      )}
    </div>
  );
}

function InfoChip({ icon, label }: { icon: React.ReactNode; label: string }) {
  return (
    <div
      className="flex items-center gap-2 rounded-full px-3 py-1 text-[11.5px] font-meta tracking-wide"
      style={{
        background: "var(--surface-alt)",
        border: "1px solid var(--line)",
        color: "var(--text-mute)",
      }}
    >
      {icon}
      <span>{label}</span>
    </div>
  );
}

function AdminIntro() {
  return (
    <Card
      className="shadow-none"
      style={{
        background: "linear-gradient(135deg, var(--bg-alt) 0%, var(--surface) 100%)",
        border: "1px solid var(--line)",
      }}
    >
      <CardContent className="grid gap-4 p-6 lg:grid-cols-[minmax(0,1.4fr)_minmax(280px,0.6fr)] lg:items-start">
        <div>
          <div
            className="mb-2 text-[11px] font-bold uppercase tracking-[0.18em] font-meta"
            style={{ color: "var(--accent)" }}
          >
            管理面板
          </div>
          <h2
            className="text-[22px] font-semibold"
            style={{
              fontFamily: "var(--font-serif)",
              letterSpacing: "var(--letter-tight)",
              color: "var(--text)",
            }}
          >
            这里控制"写进哪个仓库"和"AI 用什么模型"。
          </h2>
          <p
            className="mt-3 max-w-3xl text-[14px] leading-[1.65]"
            style={{ fontFamily: "var(--font-serif)", color: "var(--text-soft)" }}
          >
            左侧处理数据仓库与同步动作，右侧集中管理 AI 助手参数。数据仓库配置保存后会同时影响服务器工作区与 VS Code 客户端 mirror。
          </p>
        </div>
        <div className="grid gap-3 sm:grid-cols-3 lg:grid-cols-1">
          <QuickFact title="主分支固定" value="main" />
          <QuickFact title="客户端镜像" value="readonly token" />
          <QuickFact title="管理员权限" value="进入本页需重新输入" />
        </div>
      </CardContent>
    </Card>
  );
}

function QuickFact({ title, value }: { title: string; value: string }) {
  return (
    <div className="rounded-[var(--r-md)] border border-[var(--line)] bg-[var(--surface)]/80 p-4">
      <div className="text-xs font-medium uppercase tracking-wide text-[var(--text-mute)]">{title}</div>
      <div className="mt-1 text-sm font-semibold text-[var(--text)]">{value}</div>
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
    <main className="mx-auto max-w-5xl px-6 py-12">
      <Card className="overflow-hidden border-[var(--line)] shadow-[var(--shadow-sm)]">
        <div className="grid lg:grid-cols-[minmax(0,1.1fr)_420px]">
          <div className="border-b border-[var(--line)] bg-[var(--surface-alt)] p-8 lg:border-b-0 lg:border-r">
            <div className="mb-3 flex items-center gap-2 text-sm font-medium text-[var(--text-soft)]">
              <Lock className="h-4 w-4 text-[var(--warn-600)]" />
              需要管理员密码
            </div>
            <h2 className="text-2xl font-semibold tracking-tight text-[var(--text)]">
              解锁管理面板
            </h2>
            <p className="mt-3 max-w-xl text-sm leading-6 text-[var(--text-soft)]">
              此页面包含数据仓库连接信息、AI 配置以及联系人同步动作。每次进入本页都需要重新输入管理员密码。
            </p>
          </div>
          <div className="p-8">
            <form onSubmit={submit} className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="admin-password">管理员密码</Label>
                <Input
                  id="admin-password"
                  type="password"
                  placeholder="输入管理员密码"
                  value={pw}
                  onChange={(e) => setPw(e.target.value)}
                  autoFocus
                />
              </div>
              <Button type="submit" className="w-full" disabled={!pw}>
                进入管理员设置
              </Button>
            </form>
          </div>
        </div>
      </Card>
    </main>
  );
}

function WorkspaceConfigSection({ onAdminLost }: { onAdminLost: () => void }) {
  const [repoUrl, setRepoUrl] = useState("");
  const [visibility, setVisibility] = useState<"public" | "private">("private");
  const [writeToken, setWriteToken] = useState("");
  const [readonlyToken, setReadonlyToken] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    fetchWorkspaceAdminConfig()
      .then((cfg) => {
        setRepoUrl(cfg.repo_url);
        if (cfg.visibility === "public" || cfg.visibility === "private") {
          setVisibility(cfg.visibility);
        }
        setWriteToken(cfg.write_token);
        setReadonlyToken(cfg.readonly_token);
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
    if (!repoUrl.trim()) return toast.error("Repo URL 必填");
    if (!writeToken.trim()) return toast.error("服务器写入 Token 必填");
    if (visibility === "private" && !readonlyToken.trim()) {
      return toast.error("私有仓库必须填写客户端只读 Token");
    }
    setSaving(true);
    try {
      await updateWorkspaceAdminConfig({
        repo_url: repoUrl.trim(),
        visibility,
        write_token: writeToken.trim(),
        readonly_token: visibility === "private" ? readonlyToken.trim() : "",
      });
      toast.success("数据仓库配置已保存");
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
      <Card className="shadow-[var(--shadow-sm)]">
        <CardHeader className="pb-4">
          <CardTitle className="flex items-center gap-2 text-base">
            <FolderGit2 className="h-4 w-4" />
            数据仓库配置
          </CardTitle>
          <CardDescription>
            同一套仓库配置会同时服务服务器工作区和 VS Code 客户端 mirror。
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-6">
        {loading ? (
          <p className="text-sm text-muted-foreground">加载中…</p>
        ) : (
          <>
            <div className="grid gap-5 lg:grid-cols-2">
              <div className="space-y-2 lg:col-span-2">
                <Label htmlFor="repo-url">Repo URL</Label>
                <Input
                  id="repo-url"
                  placeholder="https://github.com/org/repo.git"
                  value={repoUrl}
                  onChange={(e) => setRepoUrl(e.target.value)}
                />
                <p className="text-xs text-muted-foreground">
                  branch 固定为 <code>main</code>，服务器与客户端共用同一个仓库地址。
                </p>
              </div>

              <div className="space-y-2">
                <Label htmlFor="repo-visibility">仓库可见性</Label>
                <select
                  id="repo-visibility"
                  value={visibility}
                  onChange={(e) => setVisibility(e.target.value as "public" | "private")}
                  className="flex h-10 w-full rounded-[var(--r-sm)] border border-[var(--line-strong)] bg-[var(--surface)] px-3 py-2 text-sm"
                >
                  <option value="private">private</option>
                  <option value="public">public</option>
                </select>
              </div>

              <div className="rounded-[var(--r-md)] border bg-muted/25 p-4 text-sm text-muted-foreground">
                <div className="font-medium text-foreground">使用说明</div>
                <p className="mt-2 leading-6">
                  `write token` 给服务器 pull / push 用；`readonly token` 只给 VS Code 客户端 clone / pull 用。
                </p>
              </div>

              <div className="space-y-2">
                <Label htmlFor="write-token">服务器写入 Token</Label>
                <Input
                  id="write-token"
                  type="password"
                  placeholder="服务器 pull / push 使用"
                  value={writeToken}
                  onChange={(e) => setWriteToken(e.target.value)}
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="readonly-token">
                  客户端只读 Token
                  {visibility === "public" && (
                    <span className="ml-2 text-xs text-muted-foreground">（public 仓库可留空）</span>
                  )}
                </Label>
                <Input
                  id="readonly-token"
                  type="password"
                  placeholder="VS Code 插件 clone / pull 使用"
                  value={readonlyToken}
                  onChange={(e) => setReadonlyToken(e.target.value)}
                />
              </div>
            </div>

            <div className="flex justify-end border-t pt-4">
              <Button onClick={save} disabled={saving}>
                {saving ? "保存中…" : "保存"}
              </Button>
            </div>
          </>
        )}
        </CardContent>
      </Card>
    </section>
  );
}

// ── AI settings ──────────────────────────────────────────────────────────────

function MarkdownSettingsSection({ onAdminLost }: { onAdminLost: () => void }) {
  const [styles, setStyles] = useState<MarkdownStyleMeta[]>([]);
  const [systemDefaultStyle, setSystemDefaultStyle] = useState("");
  const [effectiveStyle, setEffectiveStyle] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);

  useEffect(() => {
    fetchAdminMarkdownSettings()
      .then((s) => {
        setStyles(s.styles);
        setSystemDefaultStyle(
          s.system_default_style || s.effective_system_default_style,
        );
        setEffectiveStyle(s.effective_system_default_style);
      })
      .catch((e) => {
        if (e instanceof AdminRequiredError) {
          toast.error("管理员密码已失效，请重新输入");
          onAdminLost();
        } else {
          toast.error(e instanceof Error ? e.message : String(e));
        }
      })
      .finally(() => setLoading(false));
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const save = async () => {
    if (!systemDefaultStyle) {
      toast.error("请选择系统默认 Markdown 主题");
      return;
    }
    setSaving(true);
    try {
      await updateAdminMarkdownSettings({
        system_default_style: systemDefaultStyle,
      });
      setEffectiveStyle(systemDefaultStyle);
      toast.success("Markdown 默认主题已保存");
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

  const selectedStyle = styles.find((s) => s.id === systemDefaultStyle);

  return (
    <section>
      <Card className="shadow-[var(--shadow-sm)]">
        <CardHeader className="pb-4">
          <CardTitle className="flex items-center gap-2 text-base">
            <Palette className="h-4 w-4" />
            Markdown 正文主题
          </CardTitle>
          <CardDescription>
            设置 matter 文档正文的系统默认 Markdown 渲染主题；用户个人选择优先。
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-5">
          {loading ? (
            <p className="text-sm text-muted-foreground">加载中...</p>
          ) : (
            <>
              <div className="space-y-2">
                <Label htmlFor="markdown-default-style">系统默认主题</Label>
                <div className="relative">
                  <button
                    id="markdown-default-style"
                    type="button"
                    onClick={() => setMenuOpen((v) => !v)}
                    className="flex min-h-12 w-full items-center gap-3 rounded-[var(--r-md)] border border-[var(--line)] bg-[var(--surface-alt)] px-3 py-2 text-left transition hover:border-[var(--accent-soft)] hover:bg-[var(--surface)]"
                  >
                    {selectedStyle && <MarkdownAdminSwatch style={selectedStyle} />}
                    <span className="min-w-0 flex-1">
                      <span className="block text-sm font-semibold text-[var(--text)]">
                        {selectedStyle?.label ?? "未选择"}
                        {selectedStyle && (
                          <span className="ml-2 rounded-full bg-[var(--surface)] px-1.5 py-0.5 text-[10px] font-medium text-[var(--text-mute)] ring-1 ring-[var(--line)]">
                            {selectedStyle.tone === "dark" ? "暗色" : "亮色"}
                          </span>
                        )}
                      </span>
                      {selectedStyle && (
                        <span className="mt-0.5 block truncate text-xs text-[var(--text-mute)]">
                          {selectedStyle.description}
                        </span>
                      )}
                    </span>
                    <span className="text-[11px] text-[var(--text-mute)]">▼</span>
                  </button>

                  {menuOpen && (
                    <div className="absolute left-0 right-0 top-full z-50 mt-2 max-h-80 overflow-y-auto rounded-[var(--r-md)] border border-[var(--line-strong)] bg-[var(--surface)] p-2 shadow-[var(--shadow-lg)]">
                      {styles.map((style) => (
                        <button
                          key={style.id}
                          type="button"
                          onClick={() => {
                            setSystemDefaultStyle(style.id);
                            setMenuOpen(false);
                          }}
                          className={`flex w-full items-center gap-3 rounded-[var(--r-sm)] px-2.5 py-2.5 text-left transition ${
                            systemDefaultStyle === style.id
                              ? "bg-[color-mix(in_srgb,var(--accent-bg)_62%,var(--surface))] ring-1 ring-[var(--accent-soft)]"
                              : "hover:bg-[var(--surface-alt)]"
                          }`}
                        >
                          <MarkdownAdminSwatch style={style} />
                          <span className="min-w-0 flex-1">
                            <span className="flex items-center gap-1.5 text-[12.5px] font-semibold text-[var(--text)]">
                              {style.label}
                              <span className="rounded-full bg-[var(--surface)] px-1.5 py-0.5 text-[10px] font-medium text-[var(--text-mute)] ring-1 ring-[var(--line)]">
                                {style.tone === "dark" ? "暗色" : "亮色"}
                              </span>
                              {systemDefaultStyle === style.id && (
                                <span className="rounded-full bg-[var(--surface)] px-1.5 py-0.5 text-[10px] font-medium text-[var(--accent)] ring-1 ring-[var(--accent-soft)]">
                                  已选
                                </span>
                              )}
                            </span>
                            <span className="mt-0.5 block text-[11px] leading-4 text-[var(--text-mute)]">
                              {style.description}
                            </span>
                          </span>
                        </button>
                      ))}
                    </div>
                  )}
                </div>
                <p className="text-xs text-muted-foreground">
                  当前生效系统默认：
                  {styles.find((s) => s.id === effectiveStyle)?.label ?? effectiveStyle}
                </p>
              </div>
              <div className="flex justify-end border-t pt-4">
                <Button onClick={save} disabled={saving}>
                  {saving ? "保存中..." : "保存"}
                </Button>
              </div>
            </>
          )}
        </CardContent>
      </Card>
    </section>
  );
}

function MarkdownAdminSwatch({ style }: { style: MarkdownStyleMeta }) {
  const swatch = MARKDOWN_STYLE_SWATCHES[style.id] ?? {
    bg: "#ffffff",
    accent: "var(--accent)",
    code: "var(--surface-alt)",
  };
  return (
    <span
      className="relative h-9 w-11 shrink-0 overflow-hidden rounded-[7px] ring-1 ring-[var(--line)]"
      style={{ background: swatch.bg }}
      aria-hidden
    >
      <span
        className="absolute left-2 right-2 top-2 h-1 rounded-full"
        style={{ background: swatch.accent }}
      />
      <span
        className="absolute left-2 top-[17px] h-1 w-4 rounded-full opacity-80"
        style={{ background: swatch.accent }}
      />
      <span
        className="absolute bottom-2 left-2 right-2 h-2 rounded-[4px]"
        style={{ background: swatch.code }}
      />
    </span>
  );
}

function AISettingsSection({ onAdminLost }: { onAdminLost: () => void }) {
  const [baseUrl, setBaseUrl] = useState("");
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
        setBaseUrl(s.base_url);
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
        base_url: baseUrl.trim() || "https://openrouter.ai/api/v1",
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
      <Card className="shadow-[var(--shadow-sm)]">
        <CardHeader className="pb-4">
          <CardTitle className="flex items-center gap-2 text-base">
            <Bot className="h-4 w-4" />
            AI 助手配置
          </CardTitle>
          <CardDescription>
            管理 OpenAI-compatible API 地址、凭据、默认模型以及对话历史截断参数。
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-6">
        {loading ? (
          <p className="text-sm text-muted-foreground">加载中…</p>
        ) : (
          <>
            <div className="grid gap-5 xl:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor="ai-base-url">API Base URL</Label>
                <Input
                  id="ai-base-url"
                  placeholder="https://openrouter.ai/api/v1"
                  value={baseUrl}
                  onChange={(e) => setBaseUrl(e.target.value)}
                />
                <p className="text-xs text-muted-foreground">
                  兼容 OpenAI Chat Completions 的服务地址，例如 OpenRouter 或 DashScope。
                </p>
              </div>

              <div className="space-y-2">
                <Label htmlFor="ai-key">
                  AI API Key
                  {hasKey && <span className="ml-2 text-xs text-[var(--ok-600)]">（已配置）</span>}
                </Label>
                <Input
                  id="ai-key"
                  type="password"
                  placeholder={hasKey ? "留空保持不变" : "sk-or-…"}
                  value={apiKey}
                  onChange={(e) => setApiKey(e.target.value)}
                />
                <p className="text-xs text-muted-foreground">
                  留空表示保持现有 Key 不变。
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
                          ? "bg-[var(--accent-bg)] text-[var(--accent)]"
                          : "bg-[var(--surface-alt)] text-[var(--text-mute)] hover:bg-[var(--accent-bg)]"
                      }`}
                    >
                      {m}
                    </button>
                  ))}
                </div>
              </div>
            </div>

            <div className="space-y-3 rounded-lg border bg-muted/20 p-4">
              <p className="text-xs font-semibold text-muted-foreground">对话历史截断参数</p>
              <div className="grid gap-3 md:grid-cols-3">
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

            <div className="flex justify-end border-t pt-4">
              <Button onClick={save} disabled={saving}>
                {saving ? "保存中…" : "保存"}
              </Button>
            </div>
          </>
        )}
        </CardContent>
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
      <Card className="shadow-[var(--shadow-sm)]">
        <CardHeader className="pb-4">
          <CardTitle className="flex items-center gap-2 text-base">
            <Users className="h-4 w-4" />
            联系人同步
          </CardTitle>
          <CardDescription>
            从飞书通讯录拉取联系人，供 @ 提及功能使用。该操作只需要偶尔执行。
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          <p className="max-w-2xl text-sm leading-6 text-muted-foreground">
            同步会访问飞书 API，并刷新本地联系人缓存。推荐在新增成员、改名或组织架构调整后执行。
          </p>
          <Button size="sm" onClick={onSync} disabled={syncing} className="shrink-0">
            <Users className={`mr-1.5 h-4 w-4 ${syncing ? "animate-spin" : ""}`} />
            {syncing ? "同步中…" : "立即同步联系人"}
          </Button>
        </CardContent>
      </Card>
    </section>
  );
}

export { clearAdminPassword };
