import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Plus, ShieldCheck, User } from "lucide-react";
import { fetchAppHome, fetchMe, type AppHomePayload, type Me } from "@/api";

export function HomeWelcomePane() {
  const [data, setData] = useState<AppHomePayload | null | undefined>(undefined);
  const [me, setMe] = useState<Me | null>(null);

  useEffect(() => {
    fetchAppHome()
      .then(setData)
      .catch(() => setData(null));
    fetchMe().then(setMe).catch(() => setMe(null));
  }, []);

  const isAdmin = !!me?.roles?.includes("admin");

  if (data === undefined) {
    return (
      <div
        className="grid h-full place-items-center"
        style={{ color: "var(--text-mute)", fontFamily: "var(--font-meta)" }}
      >
        加载中…
      </div>
    );
  }

  if (data === null) {
    return (
      <div
        className="grid h-full place-items-center px-6 text-center text-[14px] leading-[1.7]"
        style={{ color: "var(--text-mute)", fontFamily: "var(--font-serif)" }}
      >
        首页信息暂时不可用。<br />
        从左侧目录选择一个讨论，或点顶栏的「+ 新讨论」开始一个。
      </div>
    );
  }

  const latest = data.latest_release;

  return (
    <div className="mx-auto w-full max-w-[1240px] px-6 py-10 sm:px-2 sm:py-12">
      {/* Top badges row */}
      <div className="mb-5 flex flex-wrap items-center gap-2">
        <span
          className="inline-flex items-center rounded-full px-2.5 py-0.5 text-[11px] font-bold tracking-[0.04em] font-meta"
          style={{
            background: "var(--status-concluded-bg)",
            color: "var(--status-concluded-fg)",
          }}
        >
          Pivot {data.app.version}
        </span>
        {data.app.head && (
          <span
            className="inline-flex items-center rounded-full px-2.5 py-0.5 text-[11px] font-mono"
            style={{
              border: "1px solid var(--line)",
              color: "var(--text-mute)",
            }}
          >
            HEAD {data.app.head}
          </span>
        )}
        <span
          className="ml-auto text-[11px] font-meta tracking-[0.04em]"
          style={{ color: "var(--text-mute)" }}
        >
          Workspace · {data.app.name}
        </span>
      </div>

      {/* Editorial kicker */}
      <div
        className="mb-3 text-[10.5px] font-bold uppercase tracking-[0.22em] font-meta"
        style={{ color: "var(--accent)" }}
      >
        Knowledge Workbench
      </div>

      {/* Headline */}
      <h1
        className="m-0 text-[34px] sm:text-[44px]"
        style={{
          fontFamily: "var(--font-serif)",
          fontWeight: 500,
          letterSpacing: "var(--letter-tight)",
          lineHeight: 1.15,
          color: "var(--text)",
        }}
      >
        {data.welcome.title}
      </h1>

      {/* Hero lead — short static intro per high-fidelity design. The full
          HOME.md content is rendered further down in a dedicated section. */}
      <p
        className="mt-5 max-w-[680px] text-[15px] leading-[1.75]"
        style={{ fontFamily: "var(--font-serif)", color: "var(--text-soft)" }}
      >
        团队进入 Pivot 后的讨论入口。想法、行动、验证、洞察和结果都在同一条时间线里展开；
        左侧按分类组织讨论，右侧是阅读、推进与收口区。
      </p>

      {/* 3 guide cards */}
      <div className="mt-8 grid gap-4 sm:grid-cols-3">
        <GuideCard
          kicker="工作方式"
          title="先读上下文，再行动"
          body="左侧按分类组织讨论，右侧是阅读、推进与收口区。"
        />
        <GuideCard
          kicker="内容来源"
          title="仓库即事实源"
          body="首页说明、版本记录、讨论内容都直接来自仓库。"
        />
        <GuideCard
          kicker="下一步"
          title="从一个讨论开始"
          body="从左侧继续已有讨论，或者直接发起一个新的讨论。"
        />
      </div>

      {/* Latest release + Quick actions */}
      <div className="mt-8 grid gap-5 lg:grid-cols-[1.5fr_1fr]">
        <section
          className="rounded-[var(--r-lg)] p-6"
          style={{
            background: "var(--surface)",
            border: "1px solid var(--line)",
            boxShadow: "var(--shadow-sm)",
          }}
        >
          {latest ? (
            <>
              <div className="flex items-baseline gap-3">
                <h2
                  className="m-0 text-[20px]"
                  style={{
                    fontFamily: "var(--font-serif)",
                    fontWeight: 600,
                    letterSpacing: "var(--letter-tight)",
                    color: "var(--text)",
                  }}
                >
                  最新发布 · {latest.version}
                </h2>
                <span
                  className="text-[11.5px] font-meta tracking-[0.04em]"
                  style={{ color: "var(--text-mute)" }}
                >
                  {latest.date}
                </span>
              </div>
              <div
                className="mt-1 text-[15px]"
                style={{
                  fontFamily: "var(--font-serif)",
                  fontWeight: 600,
                  color: "var(--text)",
                }}
              >
                {latest.title}
              </div>
              <div className="prose-pivot mt-3 text-[14px] leading-[1.75]">
                <Markdown remarkPlugins={[remarkGfm]}>{latest.body_md}</Markdown>
              </div>
            </>
          ) : (
            <div className="text-[13.5px]" style={{ color: "var(--text-mute)" }}>
              CHANGELOG.md 还没有可展示的版本节。
            </div>
          )}
        </section>

        <aside
          className="rounded-[var(--r-lg)] p-6"
          style={{
            background: "var(--surface-alt)",
            border: "1px dashed var(--line-strong)",
          }}
        >
          <div
            className="mb-3 text-[10.5px] font-bold uppercase tracking-[0.22em] font-meta"
            style={{ color: "var(--text-mute)" }}
          >
            快速入口
          </div>
          <div className="flex flex-col gap-1.5">
            <QuickLink to="/new" label="发起新讨论" icon={<Plus className="h-3.5 w-3.5" />} />
            {isAdmin && (
              <QuickLink
                to="/admin"
                label="管理员设置"
                icon={<ShieldCheck className="h-3.5 w-3.5" />}
              />
            )}
            <QuickLink
              to="/settings"
              label="个人设置"
              icon={<User className="h-3.5 w-3.5" />}
            />
          </div>

          {data.recent_releases.length > 0 && (
            <>
              <div
                className="mt-6 mb-3 text-[10.5px] font-bold uppercase tracking-[0.22em] font-meta"
                style={{ color: "var(--text-mute)" }}
              >
                最近版本
              </div>
              <div className="flex flex-col gap-1">
                {data.recent_releases.map((r) => (
                  <div
                    key={`${r.version}-${r.date}`}
                    className="flex items-baseline gap-2 rounded-[var(--r-sm)] px-2 py-1.5"
                  >
                    <span
                      className="font-mono text-[11px]"
                      style={{ color: "var(--text-mute)" }}
                    >
                      {r.version}
                    </span>
                    <span
                      className="truncate text-[12.5px]"
                      style={{
                        fontFamily: "var(--font-serif)",
                        color: "var(--text)",
                      }}
                    >
                      {r.title}
                    </span>
                    <span
                      className="ml-auto shrink-0 text-[10.5px] font-meta"
                      style={{ color: "var(--text-fade)" }}
                    >
                      {r.date}
                    </span>
                  </div>
                ))}
              </div>
            </>
          )}
        </aside>
      </div>

      {/* HOME.md full guide — moved here from the hero per design */}
      <section className="mt-10">
        <div className="mb-3 flex items-baseline gap-3">
          <span
            className="text-[10.5px] font-bold uppercase tracking-[0.22em] font-meta"
            style={{ color: "var(--accent)" }}
          >
            使用指南
          </span>
          <span
            className="text-[11px] font-meta tracking-[0.04em]"
            style={{ color: "var(--text-mute)" }}
          >
            来自仓库根目录的 HOME.md
          </span>
        </div>
        <div
          className="rounded-[var(--r-lg)] px-7 py-6 sm:px-9 sm:py-8"
          style={{
            background: "var(--surface)",
            border: "1px solid var(--line)",
            boxShadow: "var(--shadow-sm)",
          }}
        >
          <div className="prose-pivot max-w-[680px]">
            <Markdown
              remarkPlugins={[remarkGfm]}
              components={{ h1: () => null }}
            >
              {data.welcome.body_md}
            </Markdown>
          </div>
        </div>
      </section>
    </div>
  );
}

function GuideCard({
  kicker,
  title,
  body,
}: {
  kicker: string;
  title: string;
  body: string;
}) {
  return (
    <div
      className="rounded-[var(--r-lg)] p-5"
      style={{
        background: "var(--surface)",
        border: "1px solid var(--line)",
        boxShadow: "var(--shadow-sm)",
      }}
    >
      <div
        className="mb-2 text-[10.5px] font-bold uppercase tracking-[0.18em] font-meta"
        style={{ color: "var(--text-mute)" }}
      >
        {kicker}
      </div>
      <div
        className="mb-2 text-[16px]"
        style={{
          fontFamily: "var(--font-serif)",
          fontWeight: 600,
          letterSpacing: "var(--letter-tight)",
          color: "var(--text)",
        }}
      >
        {title}
      </div>
      <div
        className="text-[13px] leading-[1.6]"
        style={{ fontFamily: "var(--font-serif)", color: "var(--text-soft)" }}
      >
        {body}
      </div>
    </div>
  );
}

function QuickLink({
  to,
  label,
  icon,
}: {
  to: string;
  label: string;
  icon: React.ReactNode;
}) {
  return (
    <Link
      to={to}
      className="flex items-center gap-2.5 rounded-[var(--r-sm)] px-3 py-2.5 text-[13px] font-medium transition-colors hover:bg-[var(--surface)]"
      style={{
        background: "var(--surface)",
        border: "1px solid var(--line)",
        color: "var(--text)",
      }}
    >
      <span style={{ color: "var(--accent)" }}>{icon}</span>
      <span className="flex-1">{label}</span>
    </Link>
  );
}
