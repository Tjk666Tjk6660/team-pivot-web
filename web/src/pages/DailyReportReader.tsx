import { useEffect, useMemo, useState } from "react";
import { ArrowLeft, CalendarDays } from "lucide-react";
import { Link, useParams } from "react-router-dom";
import { fetchDailyReportRun, type DailyReportRunDetail } from "@/api";

type ReportCard = {
  header?: { title?: { content?: string } };
  body?: { elements?: Array<{ tag?: string; content?: string }> };
};

type ReaderTab = "boss" | "timeline";

export function DailyReportReader() {
  const { runId } = useParams();
  const [run, setRun] = useState<DailyReportRunDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState<ReaderTab>("boss");

  useEffect(() => {
    if (!runId) return;
    setLoading(true);
    fetchDailyReportRun(Number(runId))
      .then(setRun)
      .catch((e) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }, [runId]);

  const card = useMemo(() => extractCard(run?.debug_json), [run?.debug_json]);
  const markdown = useMemo(() => cardMarkdown(card), [card]);
  const title = card?.header?.title?.content || "日报";
  const titleParts = useMemo(() => splitReportTitle(title), [title]);
  const outline = useMemo(() => reportOutline(markdown), [markdown]);

  if (loading) {
    return <ReaderShell title="日报加载中" subtitle="正在读取日报运行记录…" />;
  }
  if (error || !run) {
    return (
      <ReaderShell
        title="日报暂时不可用"
        subtitle={error || "没有找到这次日报运行记录"}
      />
    );
  }

  return (
    <div className="min-h-screen bg-[#f5f1e8] text-[#1d2525]">
      <div className="mx-auto flex w-full max-w-6xl flex-col gap-6 px-4 py-5 sm:px-6 lg:px-8">
        <header className="relative overflow-hidden border border-[#d9d0bf] bg-[#fffaf0] px-5 py-5 shadow-[0_18px_60px_rgba(55,45,25,0.10)] sm:px-8 sm:py-7">
          <div className="absolute inset-x-0 top-0 h-1 bg-[#2d6f73]" />
          <div className="flex flex-col gap-4">
            <div className="max-w-5xl">
              <Link
                to="/"
                className="mb-5 inline-flex items-center gap-2 text-xs font-semibold text-[#6c665c] hover:text-[#1d2525]"
              >
                <ArrowLeft className="h-3.5 w-3.5" />
                返回首页
              </Link>
              <h1 className="max-w-5xl text-2xl font-semibold leading-tight text-[#182425] sm:text-3xl">
                <span className="inline-flex items-center gap-2">
                  <span>{titleParts.name}</span>
                  {titleParts.range ? <span className="hidden sm:inline">·</span> : null}
                </span>
                {titleParts.range ? (
                  <span className="mt-1 block text-xl leading-snug sm:mt-0 sm:inline sm:text-3xl">
                    {titleParts.range}
                  </span>
                ) : null}
              </h1>
            </div>
          </div>
        </header>

        <ReportTabs active={activeTab} onChange={setActiveTab} />

        {activeTab === "boss" && <BossView markdown={markdown} />}
        {activeTab === "timeline" && <IndustrialTimelineView outline={outline} />}
      </div>
    </div>
  );
}

function ReaderShell({ title, subtitle }: { title: string; subtitle: string }) {
  return (
    <div className="flex min-h-screen items-center justify-center bg-[#f5f1e8] px-4">
      <div className="border border-[#d9d0bf] bg-[#fffaf0] p-6 text-center shadow-sm">
        <h1 className="text-lg font-semibold text-[#1d2525]">{title}</h1>
        <p className="mt-2 text-sm text-[#6c665c]">{subtitle}</p>
      </div>
    </div>
  );
}

function keepDateTimeTogether(value: string) {
  return value.replace(/(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2})/g, "$1\u00a0$2");
}

function splitReportTitle(value: string) {
  const normalized = value.trim();
  const match = normalized.match(/^(.*?)\s*[·・]\s*(.+)$/);
  if (!match) return { name: normalized, range: "" };
  return { name: match[1].trim(), range: keepDateTimeTogether(match[2].trim()) };
}

function ReportTabs({
  active,
  onChange,
}: {
  active: ReaderTab;
  onChange: (tab: ReaderTab) => void;
}) {
  const tabs: Array<{ id: ReaderTab; label: string; desc: string }> = [
    { id: "boss", label: "完整日报", desc: "图表 + 正文" },
    { id: "timeline", label: "路线图", desc: "方向推进视图" },
  ];
  return (
    <div className="hidden gap-2 sm:grid sm:grid-cols-2">
      {tabs.map((tab) => {
        const selected = active === tab.id;
        return (
          <button
            key={tab.id}
            type="button"
            onClick={() => onChange(tab.id)}
            className={[
              "border px-4 py-3 text-left transition",
              selected
                ? "border-[#2d6f73] bg-[#1f3030] text-[#fffaf0] shadow-[0_12px_34px_rgba(31,48,48,0.18)]"
                : "border-[#d9d0bf] bg-[#fffaf0] text-[#1f3030] hover:border-[#9eb3a0]",
            ].join(" ")}
          >
            <div className="text-sm font-semibold">{tab.label}</div>
            <div className={selected ? "mt-1 text-xs text-[#d8e0d6]" : "mt-1 text-xs text-[#8a8173]"}>
              {tab.desc}
            </div>
          </button>
        );
      })}
    </div>
  );
}

function BossView({ markdown }: { markdown: string }) {
  return (
    <main className="grid gap-5 lg:grid-cols-[220px_minmax(0,1fr)]">
        <aside className="hidden self-start border border-[#d9d0bf] bg-[#fffaf0] p-4 lg:block">
          <div className="mb-3 flex items-center gap-2 text-xs font-semibold text-[#6c665c]">
            <CalendarDays className="h-3.5 w-3.5" />
            阅读目录
          </div>
          <nav className="space-y-2">
            {extractHeadings(markdown).map((h) => (
              <a
                key={h.id}
                href={`#${h.id}`}
                className="block border-l-2 border-[#d8b56d] pl-3 text-sm text-[#2d4544] hover:border-[#2d6f73] hover:text-[#143130]"
              >
                {h.text}
              </a>
            ))}
          </nav>
        </aside>

        <article className="border border-[#d9d0bf] bg-[#fffdf7] p-5 shadow-[0_18px_60px_rgba(55,45,25,0.08)] sm:p-8">
          {markdown ? (
            <ReportMarkdown markdown={markdown} />
          ) : (
            <div className="text-sm text-[#6c665c]">
              这次运行没有保存日报正文。请重新触发一次日报生成。
            </div>
          )}
        </article>
    </main>
  );
}

function IndustrialTimelineView({ outline }: { outline: OutlineSection[] }) {
  const [expandedGroup, setExpandedGroup] = useState<OutlineGroup | null>(null);
  const grouped = useMemo(() => outline.slice(0, 6), [outline]);

  return (
    <section className="overflow-hidden border border-[#d7dee8] bg-white shadow-[0_18px_50px_rgba(20,30,45,0.08)]">
      <div className="bg-[#f4f6f8] p-4 sm:p-6">
        <div className="border border-[#d7dee8] bg-white">
          <div className="grid min-h-11 grid-cols-[132px_minmax(0,1fr)] border-b border-[#d7dee8] bg-[rgba(248,250,252,0.96)]">
            <div className="border-r border-[#d7dee8] px-4 py-3 text-xs font-black text-[#667085]">
              方向
            </div>
            <div className="grid grid-cols-3 text-xs font-black text-[#667085]">
              <div className="border-r border-[#d7dee8] px-4 py-3">已完成 / 收口</div>
              <div className="border-r border-[#d7dee8] px-4 py-3">推进 / 验证</div>
              <div className="px-4 py-3">风险 / 暂缓</div>
            </div>
          </div>

          {grouped.length ? grouped.map((section, sectionIndex) => (
            <div key={section.title} className="grid grid-cols-[132px_minmax(0,1fr)] border-b border-[#d7dee8] last:border-b-0">
              <div className="border-r border-[#d7dee8] bg-[rgba(248,250,252,0.86)] px-4 py-5">
                <div className="text-[11px] font-black uppercase text-[#667085]">
                  Phase {sectionIndex + 1}
                </div>
                <div className="mt-2 text-sm font-black leading-5 text-[#17202a]">
                  {section.title}
                </div>
              </div>
              <div className="grid gap-3 p-3 lg:grid-cols-3">
                {timelineBuckets(section.groups).map((bucket) => (
                  <div key={bucket.label} className="space-y-3">
                    {bucket.groups.length ? bucket.groups.map((group) => (
                      <ReadableTimelineCard
                        key={group.title}
                        group={group}
                        onExpand={() => setExpandedGroup(group)}
                      />
                    )) : (
                      <div className="min-h-[90px] border border-dashed border-[#d7dee8] bg-[rgba(238,242,247,0.42)] p-3 text-xs font-semibold text-[#98a2b3]">
                        暂无
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )) : (
            <div className="p-5 text-sm text-[#667085]">暂无可生成路线图的方向结构</div>
          )}
        </div>
      </div>

      {expandedGroup && (
        <TimelineItemsDialog group={expandedGroup} onClose={() => setExpandedGroup(null)} />
      )}
    </section>
  );
}

function ReadableTimelineCard({
  group,
  onExpand,
}: {
  group: OutlineGroup;
  onExpand: () => void;
}) {
  const tone = timelineTone(group.title);
  const title = stripOutlineNumber(group.title);
  return (
    <article className={`border bg-white p-4 shadow-[0_10px_26px_rgba(20,30,45,0.07)] ${tone.border}`}>
      <div className="mb-2 flex items-center justify-between gap-2">
        <span className={`rounded-full px-2 py-0.5 text-[11px] font-black ${tone.badge}`}>
          {timelineLabel(group.title)}
        </span>
        <span className="text-[11px] font-black text-[#667085]">{group.items.length} 项</span>
      </div>
      <h3 className={`text-sm font-black leading-5 ${tone.text}`}>{title}</h3>
      <ul className="mt-3 space-y-2 text-sm leading-6 text-[#344054]">
        {group.items.slice(0, 3).map((item, index) => (
          <li key={item} className="grid grid-cols-[20px_minmax(0,1fr)] gap-2">
            <span className="mt-0.5 flex h-5 w-5 items-center justify-center rounded-full border border-[#d7dee8] bg-[#f8fbfd] text-[10px] font-black leading-none text-[#667085]">
              {index + 1}
            </span>
            <span>{item}</span>
          </li>
        ))}
      </ul>
      {group.items.length > 3 && (
        <button
          type="button"
          onClick={onExpand}
          className="mt-3 rounded-md border border-[#cbd7e4] bg-[#f8fbfd] px-3 py-1.5 text-xs font-black text-[#174f7a] hover:border-[#9fb5ca] hover:bg-white"
        >
          查看全部 {group.items.length} 项
        </button>
      )}
    </article>
  );
}

function TimelineItemsDialog({
  group,
  onClose,
}: {
  group: OutlineGroup;
  onClose: () => void;
}) {
  const tone = timelineTone(group.title);
  const title = stripOutlineNumber(group.title);
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/35 px-4 py-6">
      <div className="max-h-[86vh] w-full max-w-3xl overflow-hidden border border-[#cbd7e4] bg-white shadow-[0_30px_90px_rgba(20,30,45,0.28)]">
        <div className="flex items-start justify-between gap-4 border-b border-[#d7dee8] bg-[#f8fbfd] px-5 py-4">
          <div>
            <span className={`inline-flex rounded-full px-2 py-0.5 text-[11px] font-black ${tone.badge}`}>
              {timelineLabel(group.title)}
            </span>
            <h3 className={`mt-2 text-lg font-black leading-7 ${tone.text}`}>{title}</h3>
            <p className="mt-1 text-xs font-bold text-[#667085]">共 {group.items.length} 项</p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md border border-[#cbd7e4] bg-white px-3 py-1.5 text-xs font-black text-[#344054] hover:bg-[#f4f6f8]"
          >
            关闭
          </button>
        </div>
        <div className="max-h-[62vh] overflow-y-auto px-5 py-4">
          <ol className="space-y-3">
            {group.items.map((item, index) => (
              <li key={`${index}-${item}`} className="grid grid-cols-[34px_minmax(0,1fr)] gap-3 border-b border-[#eef2f7] pb-3 last:border-b-0">
                <span className="flex h-7 w-7 items-center justify-center rounded-full bg-[#eef2f7] text-xs font-black text-[#344054]">
                  {index + 1}
                </span>
                <span className="text-sm leading-7 text-[#273547]">{item}</span>
              </li>
            ))}
          </ol>
        </div>
      </div>
    </div>
  );
}

function ReportMarkdown({ markdown }: { markdown: string }) {
  const lines = markdown.split("\n");
  const nodes: JSX.Element[] = [];
  let currentSection: { id: string; title: JSX.Element[]; body: JSX.Element[] } | null = null;
  let list: JSX.Element[] = [];
  let autoKey = 0;

  const addNode = (node: JSX.Element) => {
    if (currentSection) {
      currentSection.body.push(node);
    } else {
      nodes.push(node);
    }
  };

  const flushSection = () => {
    if (!currentSection) return;
    const section = currentSection;
    nodes.push(
      <section
        id={section.id}
        key={`section-${section.id}-${nodes.length}`}
        className="my-6 border border-[#dfd6c6] bg-[#fffdf8] px-5 py-5 first:mt-4 sm:px-6"
      >
        <h2 className="border-b border-[#e1c989] pb-3 text-xl font-semibold leading-snug text-[#1f6a73]">
          {section.title}
        </h2>
        <div className="mt-4 space-y-1">{section.body}</div>
      </section>,
    );
    currentSection = null;
  };

  const flushList = () => {
    if (!list.length) return;
    addNode(
      <ul key={`ul-${autoKey++}`} className="my-3 space-y-2 pl-5">
        {list}
      </ul>,
    );
    list = [];
  };

  lines.forEach((raw, i) => {
    const line = raw.trim();
    if (!line) {
      flushList();
      return;
    }
    if (line === "---") {
      flushList();
      addNode(<hr key={`hr-${i}`} className="my-7 border-[#e5dbc8]" />);
      return;
    }
    if (line.startsWith("## ")) {
      flushList();
      flushSection();
      const text = stripInline(line.slice(3));
      const id = headingId(text);
      currentSection = { id, title: renderInline(line.slice(3)), body: [] };
      return;
    }
    const plain = stripInline(line);
    if (/^\(\d+\)\s+/.test(plain)) {
      flushList();
      addNode(
        <p key={`sub-${i}`} className={`my-4 font-semibold leading-7 ${semanticReportColorClass(plain)}`}>
          {renderInline(line)}
        </p>,
      );
      return;
    }
    if (line.startsWith("- ")) {
      list.push(
        <li key={`li-${i}`} className="leading-7 text-[#2f3838]">
          {renderInline(line.slice(2))}
        </li>,
      );
      return;
    }
    flushList();
    addNode(
      <p key={`p-${i}`} className="my-3 leading-8 text-[#2f3838]">
        {renderInline(line)}
      </p>,
    );
  });
  flushList();
  flushSection();
  return <div className="report-reader">{nodes}</div>;
}

function renderInline(input: string): JSX.Element[] {
  const pieces: JSX.Element[] = [];
  const fontRe = /<font color="([^"]+)">([\s\S]*?)<\/font>/g;
  let last = 0;
  let match: RegExpExecArray | null;
  while ((match = fontRe.exec(input))) {
    if (match.index > last) pieces.push(...renderBold(input.slice(last, match.index)));
    pieces.push(
      <span key={`font-${pieces.length}`} className={colorClass(match[1])}>
        {renderBold(match[2])}
      </span>,
    );
    last = match.index + match[0].length;
  }
  if (last < input.length) pieces.push(...renderBold(input.slice(last)));
  return pieces;
}

function renderBold(input: string): JSX.Element[] {
  const out: JSX.Element[] = [];
  const re = /\*\*([^*]+)\*\*/g;
  let last = 0;
  let match: RegExpExecArray | null;
  while ((match = re.exec(input))) {
    if (match.index > last) out.push(...renderPinyinFallback(input.slice(last, match.index)));
    out.push(<strong key={`b-${out.length}`} className="font-semibold">{match[1]}</strong>);
    last = match.index + match[0].length;
  }
  if (last < input.length) out.push(...renderPinyinFallback(input.slice(last)));
  return out;
}

function renderPinyinFallback(input: string): JSX.Element[] {
  const pieces: JSX.Element[] = [];
  const re = /\b[a-z][a-z.]{2,}\b/g;
  let last = 0;
  let match: RegExpExecArray | null;
  while ((match = re.exec(input))) {
    if (match.index > last) pieces.push(<span key={`t-${pieces.length}`}>{input.slice(last, match.index)}</span>);
    const token = match[0];
    if (isLikelyPinyin(token)) {
      pieces.push(<strong key={`py-${pieces.length}`} className="font-semibold">{token}</strong>);
    } else {
      pieces.push(<span key={`t-${pieces.length}`}>{token}</span>);
    }
    last = match.index + token.length;
  }
  if (last < input.length) pieces.push(<span key={`t-${pieces.length}`}>{input.slice(last)}</span>);
  return pieces;
}

function isLikelyPinyin(token: string) {
  const normalized = token.toLowerCase();
  const excluded = new Set([
    "matter", "owner", "comments", "comment", "mentions", "annotations",
    "markdown", "mcp", "api", "ai", "ui", "im", "html", "saas", "phase",
    "dev", "debug", "schema", "id", "run",
  ]);
  return normalized.length >= 4 && !excluded.has(normalized);
}

function semanticReportColorClass(text: string) {
  if (/(需要关注|需关注|风险|失败|未过|卡住|暂停)/.test(text)) return "text-[#b8332f]";
  if (/(完成|完毕|收口|闭环|通过|定稿|落地|上线|关闭)/.test(text)) return "text-[#28724f]";
  if (/(待验证|验收|评审|确认)/.test(text)) return "text-[#a35d18]";
  return "text-[#1f6a73]";
}

function colorClass(color: string) {
  if (color === "green") return "text-[#28724f]";
  if (color === "orange") return "text-[#a35d18]";
  if (color === "red") return "text-[#b8332f]";
  return "text-[#1f6a73]";
}

function stripInline(input: string) {
  return input
    .replace(/<font color="[^"]+">([\s\S]*?)<\/font>/g, "$1")
    .replace(/\*\*([^*]+)\*\*/g, "$1");
}

function extractHeadings(markdown: string) {
  return markdown
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line.startsWith("## "))
    .map((line) => {
      const text = stripInline(line.slice(3));
      return { text, id: headingId(text) };
    });
}

function headingId(text: string) {
  return text.replace(/\s+/g, "-").replace(/[^\w\u4e00-\u9fa5-]/g, "");
}

type OutlineGroup = {
  title: string;
  items: string[];
};

type OutlineSection = {
  title: string;
  groups: OutlineGroup[];
};

function reportOutline(markdown: string): OutlineSection[] {
  const sections: OutlineSection[] = [];
  let currentSection: OutlineSection | null = null;
  let currentGroup: OutlineGroup | null = null;

  markdown.split("\n").forEach((raw) => {
    const line = raw.trim();
    if (!line || line === "---") return;

    if (line.startsWith("## ")) {
      currentSection = { title: stripInline(line.slice(3)), groups: [] };
      sections.push(currentSection);
      currentGroup = null;
      return;
    }

    const plain = stripInline(line);
    if (/^\(\d+\)\s+/.test(plain)) {
      if (!currentSection) {
        currentSection = { title: "未分类", groups: [] };
        sections.push(currentSection);
      }
      currentGroup = { title: plain, items: [] };
      currentSection.groups.push(currentGroup);
      return;
    }

    if (line.startsWith("- ")) {
      if (!currentSection) {
        currentSection = { title: "未分类", groups: [] };
        sections.push(currentSection);
      }
      if (!currentGroup) {
        currentGroup = { title: "事项", items: [] };
        currentSection.groups.push(currentGroup);
      }
      currentGroup.items.push(stripInline(line.slice(2)));
      return;
    }

    if (currentSection && !currentGroup && !line.startsWith("_")) {
      currentGroup = { title: "概况", items: [plain] };
      currentSection.groups.push(currentGroup);
    }
  });

  return sections;
}

function timelineLabel(text: string) {
  if (/(需要关注|需关注|风险|失败|未过|卡住)/.test(text)) return "Risk";
  if (/(暂停|暂缓|挂起)/.test(text)) return "Paused";
  if (/(完成|完毕|收口|闭环|通过|定稿|上线)/.test(text)) return "Done";
  if (/(待验证|验收|评审|确认)/.test(text)) return "Verify";
  if (/(启动|排期|推进|执行|联调)/.test(text)) return "Act";
  return "Think";
}

function stripOutlineNumber(text: string) {
  return text.replace(/^\(\d+\)\s*/, "");
}

function timelineBuckets(groups: OutlineGroup[]) {
  const buckets: Array<{ label: string; groups: OutlineGroup[] }> = [
    { label: "done", groups: [] },
    { label: "active", groups: [] },
    { label: "risk", groups: [] },
  ];
  groups.forEach((group) => {
    if (/(需要关注|需关注|风险|失败|未过|卡住|暂停|暂缓|挂起)/.test(group.title)) {
      buckets[2].groups.push(group);
    } else if (/(完成|完毕|收口|闭环|通过|定稿|上线)/.test(group.title)) {
      buckets[0].groups.push(group);
    } else {
      buckets[1].groups.push(group);
    }
  });
  return buckets;
}

function timelineTone(text: string) {
  if (/(需要关注|需关注|风险|失败|未过|卡住)/.test(text)) {
    return {
      border: "border-[#d69a9a]",
      badge: "bg-[#f9e8e8] text-[#b8332f]",
      text: "text-[#b8332f]",
    };
  }
  if (/(暂停|暂缓|挂起)/.test(text)) {
    return {
      border: "border-[#c9ced6]",
      badge: "bg-[#eceff3] text-[#475467]",
      text: "text-[#475467]",
    };
  }
  if (/(完成|完毕|收口|闭环|通过|定稿|上线)/.test(text)) {
    return {
      border: "border-[#9fcab8]",
      badge: "bg-[#e6f4f1] text-[#0d6b68]",
      text: "text-[#0d6b68]",
    };
  }
  if (/(待验证|验收|评审|确认)/.test(text)) {
    return {
      border: "border-[#e5c891]",
      badge: "bg-[#fff3dc] text-[#8b5a16]",
      text: "text-[#8b5a16]",
    };
  }
  return {
    border: "border-[#aac4dc]",
    badge: "bg-[#e8f1fb] text-[#174f7a]",
    text: "text-[#174f7a]",
  };
}

function extractCard(raw: string | null | undefined): ReportCard | null {
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw);
    return parsed.full_card || parsed.card || null;
  } catch {
    return null;
  }
}

function cardMarkdown(card: ReportCard | null): string {
  const el = card?.body?.elements?.find((item) => item.tag === "markdown");
  return el?.content || "";
}
