import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  getInvite,
  postInviteAccept,
  type InvitePreview,
} from "@/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

const PINYIN_RE = /^[a-z][a-z0-9._-]+$/;

export function InviteAccept() {
  const { token = "" } = useParams<{ token: string }>();
  const nav = useNavigate();

  const [invite, setInvite] = useState<InvitePreview | null | undefined>(undefined);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [pinyin, setPinyin] = useState("");
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    let alive = true;
    getInvite(token)
      .then((r) => {
        if (!alive) return;
        setInvite(r);
        setDisplayName(r.display_name ?? "");
      })
      .catch((err) => {
        if (!alive) return;
        setInvite(null);
        setLoadError(err instanceof Error ? err.message : String(err));
      });
    return () => {
      alive = false;
    };
  }, [token]);

  if (invite === undefined) {
    return <Shell><Loading /></Shell>;
  }
  if (invite === null) {
    return (
      <Shell>
        <h2 className="m-0 text-[24px]" style={titleStyle}>
          邀请链接无效
        </h2>
        <p className="mt-3 text-[14px] leading-[1.65]" style={bodyTextStyle}>
          这条邀请链接已过期、已使用，或本就不存在。请联系给你发送邀请的管理员重新生成。
        </p>
        {loadError && (
          <p
            className="mt-3 text-[12px] font-meta"
            style={{ color: "var(--text-mute)" }}
          >
            ({loadError})
          </p>
        )}
      </Shell>
    );
  }

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitError(null);
    if (password.length < 6) {
      setSubmitError("密码至少 6 位");
      return;
    }
    if (!PINYIN_RE.test(pinyin)) {
      setSubmitError("拼音格式：以小写字母开头，仅含 a-z / 0-9 / . _ -");
      return;
    }
    setSubmitting(true);
    try {
      await postInviteAccept(token, {
        password,
        display_name: displayName.trim(),
        pinyin: pinyin.trim(),
      });
      nav("/", { replace: true });
      window.location.reload();
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : String(err));
      setSubmitting(false);
    }
  };

  const expiresLabel = formatExpires(invite.expires_at);

  return (
    <Shell>
      <div
        className="mb-3 text-[10.5px] font-bold uppercase tracking-[0.22em] font-meta"
        style={{ color: "var(--accent)" }}
      >
        加入 Pivot
      </div>
      <h2 className="m-0 text-[26px]" style={titleStyle}>
        欢迎加入
      </h2>
      <p className="mt-3 text-[14px] leading-[1.65]" style={bodyTextStyle}>
        管理员通过邀请链接邀请你加入 Pivot。设置好密码和拼音名后即可登录。
      </p>

      <form onSubmit={submit} className="mt-6 flex flex-col gap-4">
        <Field
          id="email"
          label="邮箱"
          hint="管理员预先指定，不可修改"
          input={
            <Input
              id="email"
              type="email"
              value={invite.email}
              readOnly
              disabled
              className="h-10 rounded-[var(--r-sm)] text-[14px]"
              style={{
                background: "var(--surface-alt)",
                border: "1px solid var(--line)",
                color: "var(--text-mute)",
              }}
            />
          }
        />
        <Field
          id="password"
          label="密码"
          hint="至少 6 位"
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
        {submitError && (
          <p className="text-[12px]" style={{ color: "var(--danger-500)" }}>
            {submitError}
          </p>
        )}
        <div
          className="flex items-center justify-between gap-3 pt-2"
          style={{ borderTop: "1px solid var(--line)", paddingTop: "1rem" }}
        >
          <span
            className="text-[11.5px] font-meta"
            style={{ color: "var(--text-mute)" }}
          >
            {expiresLabel}
          </span>
          <Button
            type="submit"
            disabled={submitting || !password || !displayName || !pinyin}
            className="h-10 rounded-[var(--r-sm)] px-5 text-[14px] font-semibold shadow-none"
            style={{
              background: "var(--accent)",
              color: "var(--accent-ink)",
              border: "1px solid var(--accent)",
            }}
          >
            {submitting ? "创建中…" : "创建账号"}
          </Button>
        </div>
      </form>
    </Shell>
  );
}

function formatExpires(expiresAt: number): string {
  const ms = expiresAt * 1000 - Date.now();
  if (ms <= 0) return "邀请已过期";
  const hours = ms / 1000 / 3600;
  if (hours < 24) return `${Math.max(1, Math.round(hours))} 小时后过期`;
  return `${Math.round(hours / 24)} 天后过期`;
}

function Loading() {
  return (
    <p className="text-[14px]" style={bodyTextStyle}>
      正在加载邀请…
    </p>
  );
}

const inputStyle: React.CSSProperties = {
  background: "var(--surface-alt)",
  border: "1px solid var(--line)",
  color: "var(--text)",
};

const titleStyle: React.CSSProperties = {
  fontFamily: "var(--font-serif)",
  fontWeight: 600,
  letterSpacing: "var(--letter-tight)",
  color: "var(--text)",
};

const bodyTextStyle: React.CSSProperties = {
  fontFamily: "var(--font-serif)",
  color: "var(--text-soft)",
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
