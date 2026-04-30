const MESSAGES: Record<string, { title: string; body: string; tone: "info" | "warn" | "danger" }> = {
  submitted: {
    title: "申请已提交",
    body: "你的加入申请已提交，请等待管理员审批。审批通过后会从飞书 DM 收到通知。",
    tone: "info",
  },
  pending_approval: {
    title: "等待审批",
    body: "你之前的加入申请正在等待管理员处理。请联系管理员加快审批，或耐心等待。",
    tone: "info",
  },
  rejected: {
    title: "申请未通过",
    body: "你的加入申请已被拒绝。如需复议请联系管理员。",
    tone: "danger",
  },
  suspended: {
    title: "账号已暂停",
    body: "账号已被管理员暂停，登录入口已关闭。请联系管理员了解详情。",
    tone: "warn",
  },
  deleted: {
    title: "账号已停用",
    body: "账号已被管理员标记为已停用，登录入口已关闭。",
    tone: "danger",
  },
};

const TONE_COLOR: Record<"info" | "warn" | "danger", string> = {
  info: "var(--accent)",
  warn: "var(--warning-500, #d97706)",
  danger: "var(--danger-500)",
};

export function PendingApproval({ reason }: { reason: string }) {
  const m = MESSAGES[reason];
  if (!m) {
    return (
      <Banner
        title="访问受限"
        body="未授权访问该页面。请联系管理员。"
        accent="var(--text-mute)"
      />
    );
  }
  return <Banner title={m.title} body={m.body} accent={TONE_COLOR[m.tone]} />;
}

function Banner({
  title,
  body,
  accent,
}: {
  title: string;
  body: string;
  accent: string;
}) {
  return (
    <div
      className="mb-5 rounded-[var(--r-sm)] p-4"
      style={{
        background: "var(--surface-alt)",
        border: `1px solid ${accent}`,
      }}
      role="alert"
    >
      <div
        className="text-[10.5px] font-bold uppercase tracking-[0.18em] font-meta"
        style={{ color: accent }}
      >
        {title}
      </div>
      <p
        className="mt-2 text-[13.5px] leading-[1.65]"
        style={{
          fontFamily: "var(--font-serif)",
          color: "var(--text-soft)",
          margin: 0,
        }}
      >
        {body}
      </p>
    </div>
  );
}

/** Pull a `reason` value out of the current URL's query string. Returns
 *  null if absent. SSR-safe: returns null when window is undefined. */
export function reasonFromQuery(): string | null {
  if (typeof window === "undefined") return null;
  const sp = new URLSearchParams(window.location.search);
  return sp.get("reason");
}
