/** Admin sections library.
 *
 * Originally this file owned the whole /admin shell + every sub-section.
 * After the sidebar refactor (commit X), the shell moved to
 * pages/admin/AdminLayout.tsx; the per-section pages live as their own
 * routes (pages/admin/AdminWorkspace.tsx, AdminAI.tsx, etc.) and import
 * the section component from this file. The dispatcher / RoleDeniedNotice /
 * AdminIntro / QuickFact were deleted — AdminLayout + AdminHome cover them.
 */
import { useEffect, useState } from "react";
import { Bot, FileText, FolderGit2, Palette, Play } from "lucide-react";
import { toast } from "sonner";
import {
  AdminRequiredError,
  fetchAdminMarkdownSettings,
  fetchAISettings,
  fetchDailyReportConfig,
  fetchDailyReportLastRun,
  fetchWorkspaceAdminConfig,
  triggerDailyReport,
  updateAdminMarkdownSettings,
  updateAISettings,
  updateDailyReportConfig,
  updateWorkspaceAdminConfig,
  type DailyReportConfig,
  type DailyReportLastRun,
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

export function WorkspaceConfigSection({ onAdminLost }: { onAdminLost: () => void }) {
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

export function MarkdownSettingsSection({ onAdminLost }: { onAdminLost: () => void }) {
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

export function MarkdownAdminSwatch({ style }: { style: MarkdownStyleMeta }) {
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

export function AISettingsSection({ onAdminLost }: { onAdminLost: () => void }) {
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

// ── Daily Report (Phase 5) ────────────────────────────────────────────────────

export function DailyReportSection({ onAdminLost }: { onAdminLost: () => void }) {
  const [cfg, setCfg] = useState<DailyReportConfig | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [triggering, setTriggering] = useState(false);
  const [dryRun, setDryRun] = useState(true);
  const [noAi, setNoAi] = useState(false);
  const [lastRun, setLastRun] = useState<DailyReportLastRun | null>(null);
  const [pollingRunId, setPollingRunId] = useState<string | null>(null);

  useEffect(() => {
    fetchDailyReportConfig()
      .then(setCfg)
      .catch((e) => {
        if (e instanceof AdminRequiredError) {
          toast.error("管理员密码已失效，请重新输入");
          onAdminLost();
        } else {
          toast.error(e instanceof Error ? e.message : String(e));
        }
      })
      .finally(() => setLoading(false));
    fetchDailyReportLastRun().then(setLastRun).catch(() => {});
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // poll last-run when a trigger has just kicked off
  useEffect(() => {
    if (!pollingRunId) return;
    let cancelled = false;
    const tick = async () => {
      try {
        const lr = await fetchDailyReportLastRun();
        if (cancelled) return;
        setLastRun(lr);
        if (lr.run_id === pollingRunId && lr.finished_at) {
          setPollingRunId(null);
          if (lr.error) {
            toast.error(`触发失败：${lr.error}`);
          } else if (lr.rc === 0) {
            toast.success("日报已生成");
          } else {
            toast.error(`运行结束 rc=${lr.rc}`);
          }
        }
      } catch {
        /* ignore polling error */
      }
    };
    const t = window.setInterval(tick, 3000);
    return () => {
      cancelled = true;
      window.clearInterval(t);
    };
  }, [pollingRunId]);

  const save = async () => {
    if (!cfg) return;
    setSaving(true);
    try {
      await updateDailyReportConfig(cfg);
      toast.success("日报配置已保存");
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

  const trigger = async () => {
    if (!cfg) return;
    if (!cfg.enabled) {
      toast.error("总开关 enabled=false，请先打开后保存再触发");
      return;
    }
    setTriggering(true);
    try {
      const r = await triggerDailyReport({ dry_run: dryRun, no_ai: noAi });
      toast.message(`已开始：${r.run_id}`);
      setPollingRunId(r.run_id);
    } catch (e) {
      if (e instanceof AdminRequiredError) {
        onAdminLost();
      } else {
        toast.error(e instanceof Error ? e.message : String(e));
      }
    } finally {
      setTriggering(false);
    }
  };

  const update = (patch: Partial<DailyReportConfig>) => {
    if (!cfg) return;
    setCfg({ ...cfg, ...patch });
  };

  return (
    <section>
      <Card className="shadow-[var(--shadow-sm)]">
        <CardHeader className="pb-4">
          <CardTitle className="flex items-center gap-2 text-base">
            <FileText className="h-4 w-4" />
            日报配置 · 公司视角 / 个人视角
          </CardTitle>
          <CardDescription>
            两份独立报告（公司视角 + 个人视角）的开关、推送窗口、触发方式与手动执行入口。
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-6">
          {loading || !cfg ? (
            <p className="text-sm text-muted-foreground">加载中…</p>
          ) : (
            <>
              <div className="grid gap-4 lg:grid-cols-2">
                <ToggleRow
                  label="总开关"
                  checked={cfg.enabled}
                  onChange={(v) => update({ enabled: v })}
                  hint="关闭后定时调度和手动触发都跳过"
                />
                <ToggleRow
                  label="仅工作日推送"
                  checked={cfg.push_freq === "weekdays"}
                  onChange={(v) =>
                    update({ push_freq: v ? "weekdays" : "daily" })
                  }
                  hint="开启时周末跳过(避免空卡噪音);关闭则每天发"
                />

                <ToggleRow
                  label="公司视角报告"
                  checked={cfg.company_enabled}
                  onChange={(v) => update({ company_enabled: v })}
                  hint="一段叙事 + 整体节奏定性（积极/平稳/偏停滞）"
                />
                <ToggleRow
                  label="个人视角报告"
                  checked={cfg.personal_enabled}
                  onChange={(v) => update({ personal_enabled: v })}
                  hint="逐人输入/输出叙述，无活动者合并到一行"
                />

                <div className="space-y-2 rounded-[var(--r-md)] border border-[var(--line)] bg-[var(--surface)] p-3">
                  <Label htmlFor="dr-window-hours" className="text-sm font-semibold">
                    统计时间窗口（小时）
                  </Label>
                  <Input
                    id="dr-window-hours"
                    type="number"
                    min={1}
                    max={168}
                    value={cfg.time_window_hours}
                    onChange={(e) =>
                      update({ time_window_hours: Number(e.target.value) || 24 })
                    }
                  />
                  <p className="text-xs text-muted-foreground">
                    默认 24 小时;范围 1-168
                  </p>
                </div>
                <div className="space-y-2 rounded-[var(--r-md)] border border-[var(--line)] bg-[var(--surface)] p-3">
                  <Label htmlFor="dr-push-time" className="text-sm font-semibold">
                    每日推送时刻 (HH:MM)
                  </Label>
                  <Input
                    id="dr-push-time"
                    type="time"
                    value={cfg.push_time}
                    onChange={(e) =>
                      update({ push_time: e.target.value || "09:30" })
                    }
                  />
                  <p className="text-xs text-muted-foreground">
                    Asia/Shanghai,主服务进程内置定时
                  </p>
                </div>
              </div>

              <div className="flex justify-end border-t pt-4">
                <Button onClick={save} disabled={saving}>
                  {saving ? "保存中…" : "保存配置"}
                </Button>
              </div>

              <div className="rounded-[var(--r-md)] border border-[var(--line)] bg-[var(--surface-alt)] p-4 space-y-3">
                <div className="text-sm font-semibold text-[var(--text)]">
                  立即手动触发一次
                </div>
                <div className="flex flex-wrap items-center gap-4 text-sm">
                  <label className="flex items-center gap-2">
                    <input
                      type="checkbox"
                      checked={dryRun}
                      onChange={(e) => setDryRun(e.target.checked)}
                    />
                    Dry-run（不发飞书）
                  </label>
                  <label className="flex items-center gap-2">
                    <input
                      type="checkbox"
                      checked={noAi}
                      onChange={(e) => setNoAi(e.target.checked)}
                    />
                    No AI（fallback 文案）
                  </label>
                </div>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={trigger}
                  disabled={triggering || pollingRunId !== null}
                >
                  <Play className="mr-1.5 h-3.5 w-3.5" />
                  {triggering
                    ? "启动中…"
                    : pollingRunId
                    ? "运行中…"
                    : "立即触发"}
                </Button>
                {lastRun && (lastRun.started_at || lastRun.run_id) && (
                  <div className="rounded border bg-[var(--surface)] p-3 text-xs space-y-1">
                    <div>
                      <span className="font-medium">run_id:</span>{" "}
                      {lastRun.run_id ?? "-"}
                    </div>
                    <div>
                      <span className="font-medium">started:</span>{" "}
                      {lastRun.started_at ?? "-"}
                    </div>
                    <div>
                      <span className="font-medium">finished:</span>{" "}
                      {lastRun.finished_at ?? "(running…)"}
                    </div>
                    {lastRun.rc !== null && (
                      <div>
                        <span className="font-medium">rc:</span>{" "}
                        <span
                          style={{
                            color:
                              lastRun.rc === 0
                                ? "var(--ok-600)"
                                : "var(--warn-600)",
                          }}
                        >
                          {lastRun.rc}
                        </span>
                      </div>
                    )}
                    {lastRun.error && (
                      <div className="text-[var(--warn-600)]">
                        error: {lastRun.error}
                      </div>
                    )}
                  </div>
                )}
              </div>
            </>
          )}
        </CardContent>
      </Card>
    </section>
  );
}

export function ToggleRow({
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

// SyncContactsSection 已下线（圈人候选不再查 contacts 表，admin 主动同步
// 失去意义；contacts 表的填充改由 /auth/callback 飞书登录时
// `contacts.upsert_from_login` 单条更新负责）。删除 import + 函数本体；
// AdminContacts 页面 + /admin/contacts 路由 + /api/contacts/sync 端点
// 一并下线（同 commit）。
