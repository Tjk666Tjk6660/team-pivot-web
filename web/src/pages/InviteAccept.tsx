import { useEffect, useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import { getInvite, startInvite, type InvitePreview } from "@/api";
import { Button } from "@/components/ui/button";

export function InviteAccept() {
  const { token = "" } = useParams<{ token: string }>();
  const [searchParams] = useSearchParams();
  const denied = searchParams.get("reason") === "feishu_denied";

  const [invite, setInvite] = useState<InvitePreview | null | undefined>(undefined);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(
    denied ? "你刚才在飞书页面取消了授权。可以重新点击下面的按钮再试一次。" : null,
  );

  useEffect(() => {
    let alive = true;
    getInvite(token)
      .then((r) => {
        if (!alive) return;
        setInvite(r);
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

  const goFeishu = async () => {
    setSubmitError(null);
    setSubmitting(true);
    try {
      const { redirect_url } = await startInvite(token);
      window.location.href = redirect_url;
    } catch (err) {
      const code = err instanceof Error ? err.message : String(err);
      setSubmitError(
        code === "invite_unusable" ? "邀请已失效（过期或已使用）" :
        code === "invite_not_found" ? "邀请链接无效" :
        `跳转失败：${code}`
      );
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
        管理员邀请你加入 Pivot。点下面的按钮用飞书账号登录；登录后会进入
        管理员审核队列，审核通过后即可访问。
      </p>

      <Button
        type="button"
        onClick={goFeishu}
        disabled={submitting}
        className="mt-6 h-11 w-full rounded-[var(--r-sm)] text-[14px] font-semibold shadow-none"
        style={{
          background: "var(--accent)",
          color: "var(--accent-ink)",
          border: "1px solid var(--accent)",
        }}
      >
        {submitting ? "正在跳转飞书…" : "用飞书账号登录"}
      </Button>

      {submitError && (
        <p className="mt-3 text-[12px]" style={{ color: "var(--danger-500)" }}>
          {submitError}
        </p>
      )}

      <p
        className="mt-4 text-[11.5px] font-meta"
        style={{ color: "var(--text-mute)" }}
      >
        {expiresLabel}
      </p>
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
