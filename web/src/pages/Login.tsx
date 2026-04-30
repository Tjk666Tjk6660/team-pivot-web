import { useState } from "react";
import { postEmailPasswordLogin } from "@/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { PendingApproval, reasonFromQuery } from "@/pages/PendingApproval";

type Mode = "feishu" | "email";

export function Login() {
  const reason = reasonFromQuery();
  const [mode, setMode] = useState<Mode>("feishu");
  return (
    <div
      className="grid min-h-screen lg:grid-cols-2"
      style={{ background: "var(--bg)" }}
    >
      {/* Left — editorial brand panel (hidden on small screens) */}
      <aside
        className="hidden flex-col justify-between p-12 lg:flex xl:p-16"
        style={{
          background:
            "linear-gradient(180deg, var(--bg) 0%, var(--bg-alt) 100%)",
          borderRight: "1px solid var(--line)",
        }}
      >
        <div className="flex items-center gap-3">
          <img
            src="/pivot-logo.png"
            alt="Pivot"
            className="h-10 w-10 shrink-0 rounded-[var(--r-md)] object-cover object-top"
            style={{
              background: "var(--surface-alt)",
              border: "1px solid var(--line)",
            }}
          />
          <div>
            <div
              className="text-[20px] font-semibold"
              style={{
                fontFamily: "var(--font-serif)",
                letterSpacing: "var(--letter-tight)",
                color: "var(--text)",
              }}
            >
              Pivot
            </div>
            <div
              className="text-[10.5px] font-bold uppercase tracking-[0.18em] font-meta"
              style={{ color: "var(--text-mute)" }}
            >
              Team Pivot · Knowledge Workbench
            </div>
          </div>
        </div>

        <div>
          <div
            className="mb-4 text-[11px] font-bold uppercase tracking-[0.22em] font-meta"
            style={{ color: "var(--accent)" }}
          >
            Issue №014 · 2025
          </div>
          <h1
            className="m-0 text-[44px] xl:text-[56px]"
            style={{
              fontFamily: "var(--font-serif)",
              fontWeight: 500,
              letterSpacing: "var(--letter-tight)",
              lineHeight: 1.1,
              color: "var(--text)",
            }}
          >
            像写信一样
            <br />
            讨论，
            <em
              className="italic"
              style={{ color: "var(--accent)", fontStyle: "italic" }}
            >
              得到结论。
            </em>
          </h1>
          <p
            className="mt-5 max-w-md text-[15px] leading-[1.7]"
            style={{
              fontFamily: "var(--font-serif)",
              color: "var(--text-soft)",
            }}
          >
            邮件客户端式的团队讨论工具。每个话题都有头有尾 ——
            写信、回信、达成结论、归档，或转成可执行的项目。
          </p>
        </div>

        <div
          className="flex gap-6 text-[11.5px] font-meta tracking-wider"
          style={{ color: "var(--text-mute)" }}
        >
          <span>Self-hosted</span>
          <span>仓库即事实源</span>
        </div>
      </aside>

      {/* Right — login card */}
      <main
        className="grid place-items-center p-6 sm:p-12"
        style={{ background: "var(--bg-alt)" }}
      >
        <div
          className="w-full max-w-[420px] rounded-[var(--r-lg)] p-9"
          style={{
            background: "var(--surface)",
            border: "1px solid var(--line)",
            boxShadow: "var(--shadow-md)",
          }}
        >
          {reason && <PendingApproval reason={reason} />}
          <div
            className="mb-3 text-[10.5px] font-bold uppercase tracking-[0.22em] font-meta"
            style={{ color: "var(--text-mute)" }}
          >
            登录
          </div>
          <h2
            className="m-0 text-[26px]"
            style={{
              fontFamily: "var(--font-serif)",
              fontWeight: 600,
              letterSpacing: "var(--letter-tight)",
              color: "var(--text)",
            }}
          >
            欢迎回来
          </h2>
          <p
            className="mt-3 text-[14px] leading-[1.65]"
            style={{
              fontFamily: "var(--font-serif)",
              color: "var(--text-soft)",
            }}
          >
            {mode === "feishu"
              ? "用飞书登录可保留与 @-mention 一致的身份。如果是用邀请码加入的同事，请用邮箱密码登录。"
              : "用管理员邀请你时填的邮箱 + 你接受邀请时设置的密码登录。"}
          </p>

          <div
            className="mt-5 flex rounded-[var(--r-sm)] p-1"
            style={{
              background: "var(--surface-alt)",
              border: "1px solid var(--line)",
            }}
            role="tablist"
          >
            <TabButton
              active={mode === "feishu"}
              onClick={() => setMode("feishu")}
            >
              飞书登录
            </TabButton>
            <TabButton
              active={mode === "email"}
              onClick={() => setMode("email")}
            >
              邮箱 / 密码
            </TabButton>
          </div>

          {mode === "feishu" ? <FeishuPanel /> : <EmailPasswordPanel />}

          <div
            className="mt-6 space-y-1.5 pt-5 text-[11.5px] leading-[1.6] font-meta"
            style={{
              borderTop: "1px solid var(--line)",
              color: "var(--text-mute)",
            }}
          >
            <div>
              · 首次登录需要补填
              <strong style={{ color: "var(--text-soft)" }}>拼音名</strong>
              （用作 git author 和分支名）
            </div>
            <div>
              · 管理员可在
              <code
                className="mx-1 rounded px-1.5 py-0.5 font-mono"
                style={{
                  background: "var(--surface-alt)",
                  border: "1px solid var(--line)",
                }}
              >
                /admin
              </code>
              管理用户与邀请
            </div>
            <div>· 自托管 · 数据仓库即事实源</div>
          </div>
        </div>
      </main>
    </div>
  );
}

function TabButton({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      role="tab"
      aria-selected={active}
      onClick={onClick}
      className="flex-1 rounded-[var(--r-sm)] py-2 text-[13px] font-semibold transition-colors"
      style={{
        background: active ? "var(--surface)" : "transparent",
        color: active ? "var(--text)" : "var(--text-mute)",
        border: active ? "1px solid var(--line)" : "1px solid transparent",
      }}
    >
      {children}
    </button>
  );
}

function FeishuPanel() {
  return (
    <a
      href="/login"
      className="mt-5 flex h-11 w-full items-center justify-center gap-2.5 rounded-[var(--r-sm)] text-[14px] font-semibold transition-opacity hover:opacity-90"
      style={{
        background: "var(--accent)",
        color: "var(--accent-ink)",
        border: "1px solid var(--accent)",
      }}
    >
      <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor" aria-hidden>
        <rect x="3" y="3" width="8" height="8" rx="1" />
        <rect x="13" y="3" width="8" height="8" rx="1" />
        <rect x="3" y="13" width="8" height="8" rx="1" />
        <rect x="13" y="13" width="8" height="8" rx="1" />
      </svg>
      用飞书登录
    </a>
  );
}

function EmailPasswordPanel() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await postEmailPasswordLogin({ email: email.trim(), password });
      // 服务端已写 sid cookie；reload 触发 fetchMe 拿到登录态。
      window.location.assign("/");
    } catch (err) {
      setError(
        err instanceof Error && err.message === "invalid_credentials"
          ? "邮箱或密码错误"
          : err instanceof Error
            ? err.message
            : String(err),
      );
      setSubmitting(false);
    }
  };

  const inputStyle: React.CSSProperties = {
    background: "var(--surface-alt)",
    border: "1px solid var(--line)",
    color: "var(--text)",
  };

  return (
    <form onSubmit={submit} className="mt-5 flex flex-col gap-3">
      <div className="grid gap-1.5">
        <Label
          htmlFor="email"
          className="text-[12.5px] font-semibold"
          style={{ color: "var(--text)" }}
        >
          邮箱
        </Label>
        <Input
          id="email"
          type="email"
          autoComplete="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          required
          className="h-10 rounded-[var(--r-sm)] text-[14px]"
          style={inputStyle}
        />
      </div>
      <div className="grid gap-1.5">
        <Label
          htmlFor="password"
          className="text-[12.5px] font-semibold"
          style={{ color: "var(--text)" }}
        >
          密码
        </Label>
        <Input
          id="password"
          type="password"
          autoComplete="current-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
          className="h-10 rounded-[var(--r-sm)] text-[14px]"
          style={inputStyle}
        />
      </div>
      {error && (
        <p className="text-[12px]" style={{ color: "var(--danger-500)" }}>
          {error}
        </p>
      )}
      <Button
        type="submit"
        disabled={submitting || !email || !password}
        className="mt-1 h-11 rounded-[var(--r-sm)] text-[14px] font-semibold shadow-none"
        style={{
          background: "var(--accent)",
          color: "var(--accent-ink)",
          border: "1px solid var(--accent)",
        }}
      >
        {submitting ? "登录中…" : "登录"}
      </Button>
    </form>
  );
}
