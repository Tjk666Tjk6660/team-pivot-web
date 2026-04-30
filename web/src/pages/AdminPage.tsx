import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  ArrowLeft,
  Bot,
  FileText,
  FolderGit2,
  Lock,
  Menu,
  Palette,
  ShieldCheck,
  Users,
  X,
} from "lucide-react";
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
  type WorkspaceAdminConfig,
} from "@/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card } from "@/components/ui/card";
import { DailyReportSection } from "./admin/DailyReportSection";

const SUGGESTED_MODELS: Array<{ id: string; vendor: string; tag?: string }> = [
  { id: "anthropic/claude-sonnet-4-5", vendor: "Anthropic", tag: "推荐" },
  { id: "anthropic/claude-haiku-4-5",  vendor: "Anthropic", tag: "快速" },
  { id: "openai/gpt-4o-mini",          vendor: "OpenAI",    tag: "经济" },
  { id: "openai/gpt-4o",               vendor: "OpenAI",    tag: "通用" },
  { id: "google/gemini-flash-1.5",     vendor: "Google",    tag: "高速" },
];

const MARKDOWN_STYLE_SWATCHES: Record<string, { bg: string; accent: string; code: string; text: string }> = {
  "code-light":      { bg: "#ffffff", accent: "#0969da", code: "#f6f8fa", text: "#1f2328" },
  "collab-blue":     { bg: "#f3f7ff", accent: "#3370ff", code: "#dbe8ff", text: "#1d2433" },
  "page-brown":      { bg: "#fffdf7", accent: "#9b3f1b", code: "#efe7d8", text: "#2e241b" },
  "solarized-light": { bg: "#fdf6e3", accent: "#cb4b16", code: "#eee8d5", text: "#586e75" },
  "neon-dark":       { bg: "#282a36", accent: "#ff79c6", code: "#191a21", text: "#f8f8f2" },
  "nord-dark":       { bg: "#2e3440", accent: "#88c0d0", code: "#242933", text: "#d8dee9" },
};

type SectionKey = "repository" | "ai" | "markdown" | "reports" | "contacts";

const SECTIONS: Array<{
  key: SectionKey;
  label: string;
  icon: React.ReactNode;
  sub: string;
}> = [
  { key: "repository", label: "数据仓库",     icon: <FolderGit2 className="h-4 w-4" />, sub: "服务器与客户端共用同一仓库地址" },
  { key: "ai",         label: "AI 助手",      icon: <Bot        className="h-4 w-4" />, sub: "API 端点 / 模型 / 对话历史" },
  { key: "markdown",   label: "Markdown 主题", icon: <Palette    className="h-4 w-4" />, sub: "matter 文档正文渲染主题" },
  { key: "reports",    label: "日报配置",      icon: <FileText   className="h-4 w-4" />, sub: "多任务调度 · 系统通知 · 手动触发" },
  { key: "contacts",   label: "联系人同步",    icon: <Users      className="h-4 w-4" />, sub: "从飞书通讯录拉取" },
];

export function AdminPage() {
  const [unlocked, setUnlocked] = useState(false);

  useEffect(() => {
    clearAdminPassword();
    setUnlocked(false);
  }, []);

  return (
    <div
      className="min-h-screen"
      style={{ background: "var(--bg)", color: "var(--text)" }}
    >
      <Toaster position="top-center" richColors />
      {!unlocked ? (
        <>
          <SimpleHeader />
          <AdminGate onUnlock={() => setUnlocked(true)} />
        </>
      ) : (
        <AdminShell onAdminLost={() => setUnlocked(false)} />
      )}
    </div>
  );
}

function SimpleHeader() {
  return (
    <header
      className="sticky top-0 z-40 backdrop-blur"
      style={{
        height: 64,
        background: "color-mix(in srgb, var(--bg) 85%, transparent)",
        borderBottom: "1px solid var(--line)",
      }}
    >
      <div className="mx-auto flex h-full max-w-[1200px] items-center gap-4 px-7">
        <Button
          asChild
          variant="ghost"
          size="sm"
          className="h-8 rounded-md hover:bg-[var(--surface-alt)]"
          style={{ color: "var(--text-soft)" }}
        >
          <Link to="/">
            <ArrowLeft className="h-4 w-4" /> 返回
          </Link>
        </Button>
        <div className="min-w-0">
          <div className="text-[15px] font-semibold leading-tight" style={{ color: "var(--text)" }}>
            管理员设置
          </div>
          <div className="text-[12px] leading-tight" style={{ color: "var(--text-mute)" }}>
            管理数据仓库 · AI 助手 · 日报 · 联系人
          </div>
        </div>
      </div>
    </header>
  );
}

// ── Shell with sticky left nav + scroll-spy ─────────────────────────────────

function AdminShell({ onAdminLost }: { onAdminLost: () => void }) {
  const [active, setActive] = useState<SectionKey>("repository");
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [navMeta, setNavMeta] = useState<{
    branch: string;
    repoVisibility: string;
    session: string;
  }>({ branch: "main", repoVisibility: "—", session: "active" });
  const sectionRefs = useRef<Record<SectionKey, HTMLElement | null>>({
    repository: null,
    ai: null,
    markdown: null,
    reports: null,
    contacts: null,
  });

  useEffect(() => {
    const onScroll = () => {
      const headerH = 64;
      const probeY = headerH + 40;
      let bestKey: SectionKey = "repository";
      let bestDist = Infinity;
      for (const s of SECTIONS) {
        const el = sectionRefs.current[s.key];
        if (!el) continue;
        const rect = el.getBoundingClientRect();
        if (rect.top - probeY <= 0) {
          const dist = Math.abs(rect.top - probeY);
          if (dist < bestDist) {
            bestDist = dist;
            bestKey = s.key;
          }
        }
      }
      setActive(bestKey);
    };
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  const goto = (key: SectionKey) => {
    const el = sectionRefs.current[key];
    if (el) {
      const headerH = 64;
      const top = el.getBoundingClientRect().top + window.scrollY - headerH - 16;
      window.scrollTo({ top, behavior: "smooth" });
    }
    setDrawerOpen(false);
  };

  useEffect(() => {
    fetchWorkspaceAdminConfig()
      .then((cfg) => {
        setNavMeta((prev) => ({
          ...prev,
          repoVisibility: cfg.visibility || "—",
        }));
      })
      .catch(() => {});
  }, []);

  return (
    <>
      <ShellHeader onMenu={() => setDrawerOpen(true)} active={active} />

      <div
        onClick={() => setDrawerOpen(false)}
        className={`fixed inset-0 z-50 transition-opacity duration-200 lg:hidden ${
          drawerOpen ? "opacity-100" : "pointer-events-none opacity-0"
        }`}
        style={{ background: "rgba(31,26,20,.4)" }}
      />

      <div
        className="mx-auto grid max-w-[1200px] gap-9 px-7 pb-20 pt-7 lg:grid-cols-[244px_minmax(0,1fr)]"
      >
        <SideNav
          active={active}
          drawerOpen={drawerOpen}
          onClose={() => setDrawerOpen(false)}
          onSelect={goto}
          navMeta={navMeta}
        />
        <main className="flex min-w-0 flex-col gap-9">
          <PageHead />

          <SectionBlock
            id="repository"
            setRef={(el) => (sectionRefs.current.repository = el)}
            icon={<FolderGit2 className="h-4 w-4" />}
            title="数据仓库配置"
            sub="服务器与客户端共用同一个仓库地址"
          >
            <WorkspaceConfigSection
              onAdminLost={onAdminLost}
              onChange={(v) =>
                setNavMeta((prev) => ({ ...prev, repoVisibility: v.visibility }))
              }
            />
          </SectionBlock>

          <SectionBlock
            id="ai"
            setRef={(el) => (sectionRefs.current.ai = el)}
            icon={<Bot className="h-4 w-4" />}
            title="AI 助手配置"
            sub="API 端点 · 模型 · 对话历史截断"
          >
            <AISettingsSection onAdminLost={onAdminLost} />
          </SectionBlock>

          <SectionBlock
            id="markdown"
            setRef={(el) => (sectionRefs.current.markdown = el)}
            icon={<Palette className="h-4 w-4" />}
            title="Markdown 主题"
            sub="matter 文档正文渲染默认主题"
          >
            <MarkdownSettingsSection onAdminLost={onAdminLost} />
          </SectionBlock>

          <SectionBlock
            id="reports"
            setRef={(el) => (sectionRefs.current.reports = el)}
            icon={<FileText className="h-4 w-4" />}
            title="日报配置"
            sub="多任务调度 · 系统通知 · 手动触发"
          >
            <DailyReportSection onAdminLost={onAdminLost} />
          </SectionBlock>

          <SectionBlock
            id="contacts"
            setRef={(el) => (sectionRefs.current.contacts = el)}
            icon={<Users className="h-4 w-4" />}
            title="联系人同步"
            sub="从飞书通讯录拉取"
          >
            <SyncContactsSection onAdminLost={onAdminLost} />
          </SectionBlock>
        </main>
      </div>
    </>
  );
}

function ShellHeader({ onMenu, active }: { onMenu: () => void; active: SectionKey }) {
  const activeLabel = SECTIONS.find((s) => s.key === active)?.label ?? "";
  return (
    <header
      className="sticky top-0 z-40 backdrop-blur"
      style={{
        height: 64,
        background: "color-mix(in srgb, var(--bg) 85%, transparent)",
        borderBottom: "1px solid var(--line)",
      }}
    >
      <div className="mx-auto flex h-full max-w-[1200px] items-center gap-4 px-7">
        <button
          type="button"
          onClick={onMenu}
          aria-label="打开菜单"
          className="hidden h-10 w-10 items-center justify-center rounded-[10px] max-lg:inline-flex"
          style={{
            background: "var(--surface)",
            border: "1px solid var(--line-strong, var(--line))",
            color: "var(--text-soft)",
          }}
        >
          <Menu className="h-4 w-4" />
        </button>
        <Button
          asChild
          variant="ghost"
          size="sm"
          className="h-8 rounded-md hover:bg-[var(--surface-alt)] max-lg:hidden"
          style={{ color: "var(--text-soft)" }}
        >
          <Link to="/">
            <ArrowLeft className="h-4 w-4" /> 返回
          </Link>
        </Button>
        <div className="min-w-0 flex items-center gap-1.5 text-[13px]">
          <span style={{ color: "var(--text-mute)" }}>管理员设置</span>
          <span style={{ color: "var(--text-mute)" }}>/</span>
          <span className="font-semibold truncate" style={{ color: "var(--text)" }}>
            {activeLabel}
          </span>
        </div>
        <div className="flex-1" />
        <div className="hidden items-center gap-2 lg:flex">
          <HeaderPill icon={<FolderGit2 className="h-3.5 w-3.5" />} label="Repo + Token" />
          <HeaderPill icon={<Bot className="h-3.5 w-3.5" />} label="AI Model + Key" />
          <HeaderPill icon={<ShieldCheck className="h-3.5 w-3.5" />} label="Admin Session" muted />
        </div>
      </div>
    </header>
  );
}

function HeaderPill({
  icon,
  label,
  muted,
}: {
  icon: React.ReactNode;
  label: string;
  muted?: boolean;
}) {
  return (
    <span
      className="inline-flex h-7 items-center gap-1.5 rounded-full px-2.5 text-[12px]"
      style={{
        background: "var(--surface)",
        border: "1px solid var(--line)",
        color: muted ? "var(--text-mute)" : "var(--text-soft)",
      }}
    >
      <span
        className="h-1.5 w-1.5 rounded-full"
        style={{ background: muted ? "var(--text-mute)" : "var(--ok-600, #2F7A4D)" }}
      />
      {icon}
      <span>{label}</span>
    </span>
  );
}

function SideNav({
  active,
  drawerOpen,
  onClose,
  onSelect,
  navMeta,
}: {
  active: SectionKey;
  drawerOpen: boolean;
  onClose: () => void;
  onSelect: (k: SectionKey) => void;
  navMeta: { branch: string; repoVisibility: string; session: string };
}) {
  return (
    <aside
      className={`max-lg:fixed max-lg:left-0 max-lg:top-0 max-lg:z-[60] max-lg:h-[100dvh] max-lg:w-[280px] max-lg:max-w-[86vw] max-lg:overflow-y-auto max-lg:p-5 max-lg:transition-transform max-lg:duration-200 max-lg:border-r max-lg:shadow-[4px_0_24px_rgba(0,0,0,0.08)] ${
        drawerOpen ? "max-lg:translate-x-0" : "max-lg:-translate-x-full"
      } lg:sticky lg:top-[92px] lg:self-start lg:max-h-[calc(100vh-108px)] lg:overflow-y-auto`}
      style={{ background: "var(--bg)", borderColor: "var(--line)" }}
    >
      <div className="flex items-center justify-between lg:hidden">
        <div
          className="text-[11px] font-semibold uppercase tracking-[0.08em]"
          style={{ color: "var(--text-mute)" }}
        >
          设置
        </div>
        <button
          type="button"
          aria-label="关闭"
          onClick={onClose}
          className="inline-flex h-8 w-8 items-center justify-center rounded-md"
          style={{ color: "var(--text-soft)" }}
        >
          <X className="h-4 w-4" />
        </button>
      </div>
      <div
        className="px-2.5 pb-2 text-[11px] font-semibold uppercase tracking-[0.08em] max-lg:hidden"
        style={{ color: "var(--text-mute)" }}
      >
        设置
      </div>
      <nav className="flex flex-col gap-px">
        {SECTIONS.map((s) => {
          const isActive = active === s.key;
          return (
            <button
              key={s.key}
              type="button"
              onClick={() => onSelect(s.key)}
              className="flex h-9 items-center gap-2.5 rounded-lg px-2.5 text-left text-[13px] transition-colors max-lg:h-10 max-lg:text-[14px]"
              style={{
                background: isActive ? "var(--surface)" : "transparent",
                color: isActive ? "var(--text)" : "var(--text-soft)",
                fontWeight: isActive ? 600 : 400,
                border: `1px solid ${isActive ? "var(--line)" : "transparent"}`,
                boxShadow: isActive ? "0 1px 2px rgba(31,26,20,.04)" : "none",
              }}
            >
              <span
                className="flex h-4 w-4 flex-none items-center justify-center"
                style={{ color: isActive ? "var(--accent)" : "var(--text-mute)" }}
              >
                {s.icon}
              </span>
              <span>{s.label}</span>
            </button>
          );
        })}
      </nav>
      <div
        className="my-3 h-px"
        style={{ background: "var(--line)", marginInline: 6 }}
      />
      <div
        className="flex flex-col gap-1.5 px-2.5 text-[12px]"
        style={{ color: "var(--text-mute)" }}
      >
        <NavMetaRow label="主分支" value={navMeta.branch} />
        <NavMetaRow label="仓库可见性" value={navMeta.repoVisibility} />
        <NavMetaRow label="Session" value={navMeta.session} />
      </div>
    </aside>
  );
}

function NavMetaRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-2">
      <span>{label}</span>
      <span
        style={{
          color: "var(--text-soft)",
          fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
          fontSize: 11,
        }}
      >
        {value}
      </span>
    </div>
  );
}

function PageHead() {
  return (
    <div
      className="flex flex-col items-start gap-2 border-b pb-4 lg:flex-row lg:items-end lg:justify-between"
      style={{ borderColor: "var(--line)" }}
    >
      <div>
        <h1
          className="m-0 text-[22px] font-bold"
          style={{
            color: "var(--text)",
            letterSpacing: "-0.01em",
          }}
        >
          管理员设置
        </h1>
        <p
          className="mt-1 text-[13px]"
          style={{ color: "var(--text-mute)" }}
        >
          这里控制 <strong style={{ color: "var(--text-soft)" }}>"写进哪个仓库"</strong> 和{" "}
          <strong style={{ color: "var(--text-soft)" }}>"AI 用什么模型"</strong>。
          数据仓库配置保存后会同时影响服务器工作区与 VS Code 客户端 mirror。
        </p>
      </div>
    </div>
  );
}

const SectionBlock = ({
  id,
  setRef,
  icon,
  title,
  sub,
  children,
}: {
  id: string;
  setRef: (el: HTMLElement | null) => void;
  icon: React.ReactNode;
  title: string;
  sub: string;
  children: React.ReactNode;
}) => (
  <section
    ref={setRef}
    id={id}
    className="scroll-mt-20"
    style={{ scrollMarginTop: "calc(64px + 16px)" }}
  >
    <div className="mb-3.5 flex items-center gap-2.5">
      <span
        className="inline-flex h-7 w-7 flex-none items-center justify-center rounded-lg"
        style={{ background: "var(--accent-bg)", color: "var(--accent)" }}
      >
        {icon}
      </span>
      <h2
        className="m-0 text-[15px] font-semibold"
        style={{ color: "var(--text)", letterSpacing: "-0.005em" }}
      >
        {title}
      </h2>
      <span className="text-[12px] max-md:hidden" style={{ color: "var(--text-mute)" }}>
        · {sub}
      </span>
    </div>
    {children}
  </section>
);

// ── Card primitives ─────────────────────────────────────────────────────────

export function ACard({
  children,
  className = "",
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <Card
      className={`overflow-hidden ${className}`}
      style={{
        background: "var(--surface)",
        border: "1px solid var(--line)",
        borderRadius: 14,
        boxShadow: "0 1px 0 rgba(31,26,20,.04), 0 1px 2px rgba(31,26,20,.04)",
      }}
    >
      {children}
    </Card>
  );
}

export function CardHead({
  title,
  desc,
  trailing,
}: {
  title: string;
  desc?: string;
  trailing?: React.ReactNode;
}) {
  return (
    <div
      className="flex items-center justify-between gap-3 px-5 py-4"
      style={{ borderBottom: "1px solid var(--line)" }}
    >
      <div className="min-w-0">
        <h3 className="m-0 text-[14px] font-semibold" style={{ color: "var(--text)" }}>
          {title}
        </h3>
        {desc && (
          <div className="mt-0.5 text-[12px]" style={{ color: "var(--text-mute)" }}>
            {desc}
          </div>
        )}
      </div>
      {trailing}
    </div>
  );
}

export function Subsection({
  title,
  children,
  first,
}: {
  title: string;
  children: React.ReactNode;
  first?: boolean;
}) {
  return (
    <div
      className="px-5 py-4"
      style={
        first
          ? undefined
          : { borderTop: "1px solid var(--line)" }
      }
    >
      <div
        className="mb-3 flex items-center gap-2 text-[12px] font-semibold"
        style={{ color: "var(--text-soft)" }}
      >
        <span
          className="h-1 w-1 rounded-full"
          style={{ background: "var(--accent)" }}
        />
        {title}
      </div>
      {children}
    </div>
  );
}

export function CardFoot({
  hint,
  children,
}: {
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <div
      className="flex items-center justify-between gap-3 px-5 py-3.5 max-sm:flex-col-reverse max-sm:items-stretch"
      style={{
        borderTop: "1px solid var(--line)",
        background:
          "linear-gradient(to bottom, transparent, color-mix(in srgb, var(--bg) 50%, transparent))",
      }}
    >
      <div className="text-[12px]" style={{ color: "var(--text-mute)" }}>
        {hint}
      </div>
      <div className="flex items-center gap-2 max-sm:w-full max-sm:[&>button]:flex-1">{children}</div>
    </div>
  );
}

export function FieldLabel({
  htmlFor,
  children,
  required,
  badge,
}: {
  htmlFor?: string;
  children: React.ReactNode;
  required?: boolean;
  badge?: string;
}) {
  return (
    <Label
      htmlFor={htmlFor}
      className="flex items-center gap-1.5 text-[12px] font-medium"
      style={{ color: "var(--text-soft)" }}
    >
      {children}
      {required && <span style={{ color: "var(--warn-600, #B43E3E)" }}>*</span>}
      {badge && (
        <span
          className="rounded px-1.5 text-[10px]"
          style={{ background: "var(--surface-alt)", color: "var(--text-mute)" }}
        >
          {badge}
        </span>
      )}
    </Label>
  );
}

export function FieldHelp({ children }: { children: React.ReactNode }) {
  return (
    <p
      className="m-0 text-[11.5px] leading-[1.45]"
      style={{ color: "var(--text-mute)" }}
    >
      {children}
    </p>
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
      <ACard>
        <div className="grid lg:grid-cols-[minmax(0,1.1fr)_420px]">
          <div
            className="border-b p-8 lg:border-b-0 lg:border-r"
            style={{ borderColor: "var(--line)", background: "var(--surface-alt)" }}
          >
            <div
              className="mb-3 flex items-center gap-2 text-sm font-medium"
              style={{ color: "var(--text-soft)" }}
            >
              <Lock className="h-4 w-4" style={{ color: "var(--warn-600)" }} />
              需要管理员密码
            </div>
            <h2
              className="text-2xl font-semibold tracking-tight"
              style={{ color: "var(--text)" }}
            >
              解锁管理面板
            </h2>
            <p
              className="mt-3 max-w-xl text-sm leading-6"
              style={{ color: "var(--text-soft)" }}
            >
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
      </ACard>
    </main>
  );
}

// ── Workspace section ───────────────────────────────────────────────────────

function WorkspaceConfigSection({
  onAdminLost,
  onChange,
}: {
  onAdminLost: () => void;
  onChange?: (cfg: WorkspaceAdminConfig) => void;
}) {
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
      const body = {
        repo_url: repoUrl.trim(),
        visibility,
        write_token: writeToken.trim(),
        readonly_token: visibility === "private" ? readonlyToken.trim() : "",
      };
      await updateWorkspaceAdminConfig(body);
      toast.success("数据仓库配置已保存");
      onChange?.({
        repo_url: body.repo_url,
        visibility: body.visibility,
        write_token: body.write_token,
        readonly_token: body.readonly_token,
        branch: "main",
      });
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
    <ACard>
      {loading ? (
        <div className="px-5 py-6 text-sm" style={{ color: "var(--text-mute)" }}>
          加载中…
        </div>
      ) : (
        <>
          <Subsection title="仓库地址" first>
            <div className="grid gap-4 lg:grid-cols-2">
              <div className="lg:col-span-2 flex flex-col gap-1.5">
                <FieldLabel htmlFor="repo-url" required>
                  Repo URL
                </FieldLabel>
                <Input
                  id="repo-url"
                  placeholder="https://github.com/org/repo.git"
                  value={repoUrl}
                  onChange={(e) => setRepoUrl(e.target.value)}
                />
                <FieldHelp>
                  分支固定为 <code>main</code>,服务器与客户端共用同一个仓库地址。
                </FieldHelp>
              </div>
              <div className="flex flex-col gap-1.5">
                <FieldLabel htmlFor="repo-visibility">仓库可见性</FieldLabel>
                <select
                  id="repo-visibility"
                  value={visibility}
                  onChange={(e) =>
                    setVisibility(e.target.value as "public" | "private")
                  }
                  className="h-[34px] rounded-md border bg-white px-3 text-[13px]"
                  style={{
                    borderColor: "var(--line-strong, var(--line))",
                    color: "var(--text)",
                  }}
                >
                  <option value="private">private</option>
                  <option value="public">public</option>
                </select>
              </div>
            </div>
          </Subsection>

          <Subsection title="访问凭证">
            <div className="grid gap-4 lg:grid-cols-2">
              <div className="flex flex-col gap-1.5">
                <FieldLabel htmlFor="write-token" required>
                  服务器写入 Token
                </FieldLabel>
                <Input
                  id="write-token"
                  type="password"
                  placeholder="服务器 pull / push 使用"
                  value={writeToken}
                  onChange={(e) => setWriteToken(e.target.value)}
                />
                <FieldHelp>给主服务 git pull / push 用</FieldHelp>
              </div>
              <div className="flex flex-col gap-1.5">
                <FieldLabel htmlFor="readonly-token" badge={visibility === "public" ? "public 可留空" : undefined}>
                  客户端只读 Token
                </FieldLabel>
                <Input
                  id="readonly-token"
                  type="password"
                  placeholder="VS Code 插件 clone / pull 使用"
                  value={readonlyToken}
                  onChange={(e) => setReadonlyToken(e.target.value)}
                />
                <FieldHelp>只给 VS Code 客户端 clone / pull 用</FieldHelp>
              </div>
            </div>
          </Subsection>

          <CardFoot hint="保存后立即影响新的 git 操作。">
            <Button onClick={save} disabled={saving}>
              {saving ? "保存中…" : "保存"}
            </Button>
          </CardFoot>
        </>
      )}
    </ACard>
  );
}

// ── AI section ──────────────────────────────────────────────────────────────

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
    <ACard>
      {loading ? (
        <div className="px-5 py-6 text-sm" style={{ color: "var(--text-mute)" }}>
          加载中…
        </div>
      ) : (
        <>
          <Subsection title="API 端点" first>
            <div className="grid gap-4 lg:grid-cols-2">
              <div className="flex flex-col gap-1.5">
                <FieldLabel htmlFor="ai-base-url">API Base URL</FieldLabel>
                <Input
                  id="ai-base-url"
                  placeholder="https://openrouter.ai/api/v1"
                  value={baseUrl}
                  onChange={(e) => setBaseUrl(e.target.value)}
                />
                <FieldHelp>兼容 OpenAI Chat Completions 的服务地址。</FieldHelp>
              </div>
              <div className="flex flex-col gap-1.5">
                <FieldLabel htmlFor="ai-key" badge={hasKey ? "已配置" : undefined}>
                  AI API Key
                </FieldLabel>
                <Input
                  id="ai-key"
                  type="password"
                  placeholder={hasKey ? "留空保持不变" : "sk-or-…"}
                  value={apiKey}
                  onChange={(e) => setApiKey(e.target.value)}
                />
                <FieldHelp>留空表示保持现有 Key 不变。</FieldHelp>
              </div>
            </div>
          </Subsection>

          <Subsection title="默认模型">
            <div className="flex flex-col gap-3">
              <div className="flex flex-col gap-1.5">
                <FieldLabel htmlFor="ai-model">模型 ID</FieldLabel>
                <Input
                  id="ai-model"
                  placeholder="anthropic/claude-sonnet-4-5"
                  value={model}
                  onChange={(e) => setModel(e.target.value)}
                  style={{ fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace" }}
                />
              </div>
              <div className="flex flex-col gap-1.5">
                <span className="text-[11.5px]" style={{ color: "var(--text-mute)" }}>
                  常用模型（点击直接应用）
                </span>
                <div className="grid gap-2 sm:grid-cols-2">
                  {SUGGESTED_MODELS.map((m) => {
                    const [, name] = m.id.split("/");
                    const isActive = model === m.id;
                    return (
                      <button
                        key={m.id}
                        type="button"
                        onClick={() => setModel(m.id)}
                        className="flex items-center gap-3 rounded-[10px] px-3.5 py-2.5 text-left transition-all"
                        style={{
                          background: isActive
                            ? "color-mix(in srgb, var(--accent-bg) 60%, var(--surface))"
                            : "var(--surface)",
                          border: `1px solid ${isActive ? "var(--accent)" : "var(--line)"}`,
                          boxShadow: isActive
                            ? "0 0 0 3px color-mix(in srgb, var(--accent) 12%, transparent)"
                            : "none",
                        }}
                      >
                        <span
                          className="h-4 w-4 flex-none rounded-full"
                          style={{
                            border: `${isActive ? 5 : 1.5}px solid ${
                              isActive ? "var(--accent)" : "var(--line-strong, var(--line))"
                            }`,
                            transition: "border-width .12s, border-color .12s",
                          }}
                        />
                        <span className="min-w-0 flex-1">
                          <span
                            className="block truncate text-[13px] font-medium"
                            style={{
                              color: "var(--text)",
                              fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
                            }}
                          >
                            {name}
                          </span>
                          <span className="block text-[11.5px]" style={{ color: "var(--text-mute)" }}>
                            {m.vendor}
                          </span>
                        </span>
                        {m.tag && (
                          <span
                            className="rounded px-1.5 py-0.5 text-[10px] flex-none"
                            style={{
                              background: isActive ? "var(--surface)" : "var(--surface-alt)",
                              color: isActive ? "var(--accent)" : "var(--text-mute)",
                            }}
                          >
                            {m.tag}
                          </span>
                        )}
                      </button>
                    );
                  })}
                </div>
              </div>
            </div>
          </Subsection>

          <Subsection title="对话历史截断">
            <div className="grid gap-3.5 md:grid-cols-3">
              <div className="flex flex-col gap-1.5">
                <FieldLabel htmlFor="ai-max-tokens">最大上下文 Token</FieldLabel>
                <Input
                  id="ai-max-tokens"
                  type="number"
                  min={1000} max={200000} step={1000}
                  value={maxContextTokens}
                  onChange={(e) => setMaxContextTokens(Number(e.target.value))}
                  style={{ fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace" }}
                />
                <FieldHelp>
                  ≈ {(maxContextTokens * 4 / 1000).toFixed(0)}k 字符
                </FieldHelp>
              </div>
              <div className="flex flex-col gap-1.5">
                <FieldLabel htmlFor="ai-min-rounds">最少保留轮数</FieldLabel>
                <Input
                  id="ai-min-rounds"
                  type="number"
                  min={1} max={50}
                  value={minRounds}
                  onChange={(e) => setMinRounds(Number(e.target.value))}
                  style={{ fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace" }}
                />
                <FieldHelp>超限也强制带上</FieldHelp>
              </div>
              <div className="flex flex-col gap-1.5">
                <FieldLabel htmlFor="ai-max-rounds">最多保留轮数</FieldLabel>
                <Input
                  id="ai-max-rounds"
                  type="number"
                  min={1} max={200}
                  value={maxRounds}
                  onChange={(e) => setMaxRounds(Number(e.target.value))}
                  style={{ fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace" }}
                />
                <FieldHelp>超出即截断</FieldHelp>
              </div>
            </div>
          </Subsection>

          <CardFoot hint="保存后下一次对话起生效。">
            <Button onClick={save} disabled={saving}>
              {saving ? "保存中…" : "保存"}
            </Button>
          </CardFoot>
        </>
      )}
    </ACard>
  );
}

// ── Markdown section ────────────────────────────────────────────────────────

function MarkdownSettingsSection({ onAdminLost }: { onAdminLost: () => void }) {
  const [styles, setStyles] = useState<MarkdownStyleMeta[]>([]);
  const [systemDefaultStyle, setSystemDefaultStyle] = useState("");
  const [effectiveStyle, setEffectiveStyle] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

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

  return (
    <ACard>
      {loading ? (
        <div className="px-5 py-6 text-sm" style={{ color: "var(--text-mute)" }}>
          加载中…
        </div>
      ) : (
        <>
          <Subsection title="系统默认主题" first>
            <div className="grid gap-2.5 sm:grid-cols-2 lg:grid-cols-3">
              {styles.map((style) => {
                const active = systemDefaultStyle === style.id;
                return (
                  <button
                    key={style.id}
                    type="button"
                    onClick={() => setSystemDefaultStyle(style.id)}
                    className="overflow-hidden rounded-[10px] text-left transition-all"
                    style={{
                      background: "var(--surface)",
                      border: `1px solid ${active ? "var(--accent)" : "var(--line)"}`,
                      boxShadow: active
                        ? "0 0 0 3px color-mix(in srgb, var(--accent) 14%, transparent)"
                        : "none",
                    }}
                  >
                    <MarkdownAdminPreview style={style} />
                    <div
                      className="flex items-center justify-between gap-2 px-2.5 py-2"
                      style={{ borderTop: "1px solid var(--line)" }}
                    >
                      <div
                        className="truncate text-[12px] font-medium"
                        style={{ color: "var(--text)" }}
                      >
                        {style.label}
                      </div>
                      <span
                        className="text-[11px]"
                        style={{ color: "var(--text-mute)" }}
                      >
                        {style.tone === "dark" ? "暗色" : "亮色"}
                      </span>
                    </div>
                  </button>
                );
              })}
            </div>
            <FieldHelp>
              当前生效系统默认:
              {styles.find((s) => s.id === effectiveStyle)?.label ?? effectiveStyle}
            </FieldHelp>
          </Subsection>
          <CardFoot hint="用户个人选择优先于系统默认。">
            <Button onClick={save} disabled={saving}>
              {saving ? "保存中…" : "保存"}
            </Button>
          </CardFoot>
        </>
      )}
    </ACard>
  );
}

function MarkdownAdminPreview({ style }: { style: MarkdownStyleMeta }) {
  const swatch = MARKDOWN_STYLE_SWATCHES[style.id] ?? {
    bg: "#ffffff",
    accent: "var(--accent)",
    code: "#f0eee8",
    text: "#333",
  };
  return (
    <div
      className="relative h-[96px] p-3"
      style={{ background: swatch.bg }}
      aria-hidden
    >
      {/* Title block */}
      <div className="mb-2 flex items-center gap-1.5">
        <div
          className="h-1.5 w-1.5 rounded-full"
          style={{ background: swatch.accent }}
        />
        <div
          className="h-1.5 rounded-full"
          style={{ width: 56, background: swatch.accent, opacity: 0.85 }}
        />
      </div>
      {/* Body lines */}
      <div className="mb-1 h-1 rounded-full" style={{ width: "92%", background: swatch.text, opacity: 0.35 }} />
      <div className="mb-1 h-1 rounded-full" style={{ width: "78%", background: swatch.text, opacity: 0.35 }} />
      <div className="mb-2 h-1 rounded-full" style={{ width: "55%", background: swatch.text, opacity: 0.35 }} />
      {/* Code block */}
      <div className="flex gap-1">
        <div className="h-2.5 rounded" style={{ width: "30%", background: swatch.code }} />
        <div className="h-2.5 rounded" style={{ width: "20%", background: swatch.code, opacity: 0.7 }} />
        <div className="h-2.5 rounded" style={{ width: "15%", background: swatch.code, opacity: 0.5 }} />
      </div>
    </div>
  );
}

// ── Contacts section ────────────────────────────────────────────────────────

function SyncContactsSection({ onAdminLost }: { onAdminLost: () => void }) {
  const [syncing, setSyncing] = useState(false);
  const [lastSyncedAt, setLastSyncedAt] = useState<string | null>(null);

  const onSync = async () => {
    setSyncing(true);
    try {
      const r = await syncContacts();
      toast.success(`同步完成:共 ${r.total} 位联系人(刷新 ${r.synced})`);
      setLastSyncedAt(new Date().toLocaleString("zh-CN"));
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
    <ACard>
      <div className="px-5 py-5">
        <p
          className="m-0 max-w-2xl text-[13px] leading-6"
          style={{ color: "var(--text-soft)" }}
        >
          从飞书通讯录拉取联系人,供 @ 提及功能使用。该操作只需要偶尔执行 ——
          推荐在新增成员、改名或组织架构调整后执行。
        </p>
      </div>
      <CardFoot hint={lastSyncedAt ? `上次同步:${lastSyncedAt}` : "尚未在本会话同步过"}>
        <Button onClick={onSync} disabled={syncing} size="sm">
          <Users className={`mr-1.5 h-4 w-4 ${syncing ? "animate-spin" : ""}`} />
          {syncing ? "同步中…" : "立即同步联系人"}
        </Button>
      </CardFoot>
    </ACard>
  );
}

// ── Re-export for ProtectedRoute use ────────────────────────────────────────

export { clearAdminPassword };
