import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { postInitComplete } from "@/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

const WARNING = `如果你要初始化这个系统，你将成为当前 Pivot 的管理员。
请确认你有权限执行初始化操作后再继续。
否则请联系系统管理员或你的上级。`;

const PINYIN_RE = /^[a-z][a-z0-9._-]+$/;

export function Init() {
  const nav = useNavigate();
  const [confirmed, setConfirmed] = useState(false);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [pinyin, setPinyin] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  if (!confirmed) {
    return (
      <Shell>
        <div
          className="mb-3 text-[10.5px] font-bold uppercase tracking-[0.22em] font-meta"
          style={{ color: "var(--danger-500)" }}
        >
          初次部署
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
          初始化 Pivot
        </h2>
        <pre
          className="mt-5 whitespace-pre-wrap rounded-[var(--r-sm)] p-4 text-[13.5px] leading-[1.65]"
          style={{
            fontFamily: "var(--font-serif)",
            background: "var(--surface-alt)",
            border: "1px solid var(--line)",
            color: "var(--text-soft)",
          }}
        >
          {WARNING}
        </pre>
        <div className="mt-6 flex justify-end gap-2">
          <Button
            type="button"
            onClick={() => setConfirmed(true)}
            className="h-10 rounded-[var(--r-sm)] px-5 text-[14px] font-semibold shadow-none"
            style={{
              background: "var(--accent)",
              color: "var(--accent-ink)",
              border: "1px solid var(--accent)",
            }}
          >
            我已确认权限，继续初始化
          </Button>
        </div>
      </Shell>
    );
  }

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    if (!PINYIN_RE.test(pinyin)) {
      setError("拼音格式：以小写字母开头，仅含 a-z / 0-9 / . _ -");
      return;
    }
    if (password.length < 6) {
      setError("密码至少 6 位");
      return;
    }
    setSubmitting(true);
    try {
      await postInitComplete({
        method: "email_password",
        email: email.trim(),
        password,
        display_name: displayName.trim(),
        pinyin: pinyin.trim(),
      });
      nav("/", { replace: true });
      // 让 App 重新读 /me — 简单粗暴但稳定
      window.location.reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setSubmitting(false);
    }
  };

  return (
    <Shell>
      <div
        className="mb-3 text-[10.5px] font-bold uppercase tracking-[0.22em] font-meta"
        style={{ color: "var(--accent)" }}
      >
        Step 2 · 创建首个管理员
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
        设置初始管理员
      </h2>
      <p
        className="mt-3 text-[14px] leading-[1.65]"
        style={{
          fontFamily: "var(--font-serif)",
          color: "var(--text-soft)",
        }}
      >
        这个账号会成为系统的第一个管理员，今后可在 /admin
        管理用户、邀请、申请。
      </p>

      <form onSubmit={submit} className="mt-6 flex flex-col gap-4">
        <Field
          id="email"
          label="邮箱"
          required
          input={
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
          }
        />
        <Field
          id="password"
          label="密码"
          hint="至少 6 位，仅作为后台登录凭据，不会在 git 历史里出现"
          required
          input={
            <Input
              id="password"
              type="password"
              autoComplete="new-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              minLength={6}
              className="h-10 rounded-[var(--r-sm)] text-[14px]"
              style={inputStyle}
            />
          }
        />
        <Field
          id="display_name"
          label="显示名"
          required
          input={
            <Input
              id="display_name"
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              required
              className="h-10 rounded-[var(--r-sm)] text-[14px]"
              style={inputStyle}
            />
          }
        />
        <Field
          id="pinyin"
          label="拼音名"
          hint="用作 git author 和分支名。例：dengke / keller.koh"
          required
          input={
            <Input
              id="pinyin"
              value={pinyin}
              onChange={(e) => setPinyin(e.target.value)}
              required
              pattern="^[a-z][a-z0-9._-]+$"
              placeholder="dengke"
              className="h-10 rounded-[var(--r-sm)] font-mono text-[14px]"
              style={{
                ...inputStyle,
                border: "1.5px solid var(--accent)",
              }}
            />
          }
        />
        {error && (
          <p className="text-[12px]" style={{ color: "var(--danger-500)" }}>
            {error}
          </p>
        )}
        <div className="flex justify-end pt-2">
          <Button
            type="submit"
            disabled={
              submitting || !email || !password || !displayName || !pinyin
            }
            className="h-10 rounded-[var(--r-sm)] px-5 text-[14px] font-semibold shadow-none"
            style={{
              background: "var(--accent)",
              color: "var(--accent-ink)",
              border: "1px solid var(--accent)",
            }}
          >
            {submitting ? "初始化中…" : "完成初始化"}
          </Button>
        </div>
      </form>
    </Shell>
  );
}

const inputStyle: React.CSSProperties = {
  background: "var(--surface-alt)",
  border: "1px solid var(--line)",
  color: "var(--text)",
};

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div
      className="grid min-h-screen place-items-center px-4 py-10"
      style={{ background: "var(--bg-alt)" }}
    >
      <div
        className="w-full max-w-[520px] rounded-[var(--r-lg)] p-9 sm:p-11"
        style={{
          background: "var(--surface)",
          border: "1px solid var(--line)",
          boxShadow: "var(--shadow-md)",
        }}
      >
        {children}
      </div>
    </div>
  );
}

function Field({
  id,
  label,
  hint,
  required,
  input,
}: {
  id: string;
  label: string;
  hint?: string;
  required?: boolean;
  input: React.ReactNode;
}) {
  return (
    <div className="grid gap-1.5">
      <Label
        htmlFor={id}
        className="flex items-center gap-2 text-[13px] font-semibold"
        style={{ color: "var(--text)" }}
      >
        {label}
        {required && (
          <span
            className="text-[10px] font-bold tracking-[0.08em] font-meta"
            style={{ color: "var(--danger-500)" }}
          >
            必填
          </span>
        )}
      </Label>
      {input}
      {hint && (
        <p
          className="text-[11.5px] font-meta leading-[1.5]"
          style={{ color: "var(--text-mute)" }}
        >
          {hint}
        </p>
      )}
    </div>
  );
}
