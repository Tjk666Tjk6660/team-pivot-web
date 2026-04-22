import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { ArrowUpRight, BookOpenText, Rocket, ShieldCheck, Sparkles } from "lucide-react";
import { fetchAppHome, type AppHomePayload } from "@/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

export function HomeWelcomePane() {
  const [data, setData] = useState<AppHomePayload | null | undefined>(undefined);

  useEffect(() => {
    fetchAppHome()
      .then(setData)
      .catch(() => setData(null));
  }, []);

  if (data === undefined) {
    return (
      <div className="mx-auto max-w-6xl px-4 py-6 sm:px-6 lg:px-8 lg:py-8">
        <Card>
          <CardContent className="p-6 text-sm text-muted-foreground">Loading…</CardContent>
        </Card>
      </div>
    );
  }

  if (data === null) {
    return (
      <div className="mx-auto max-w-6xl px-4 py-6 sm:px-6 lg:px-8 lg:py-8">
        <Card>
          <CardContent className="p-6 text-sm text-muted-foreground">
            首页信息暂时不可用。你可以直接从左侧选择讨论，或点击顶部 `新讨论` 开始工作。
          </CardContent>
        </Card>
      </div>
    );
  }

  const latest = data.latest_release;

  return (
    <div className="mx-auto max-w-6xl px-0 py-4 sm:px-6 sm:py-8 lg:px-10 lg:py-10">
      <div className="grid gap-4 sm:gap-8 xl:grid-cols-[minmax(0,1.7fr)_minmax(320px,0.82fr)]">
        <div className="space-y-6">
          <section className="workbench-panel overflow-hidden rounded-[1.2rem] border sm:rounded-[1.75rem]">
            <div className="grid gap-6 px-4 py-5 sm:gap-10 sm:px-8 sm:py-10 xl:grid-cols-[minmax(0,1.45fr)_minmax(250px,0.72fr)]">
              <div className="space-y-6 sm:space-y-8">
                <div className="flex flex-wrap items-center gap-3">
                  <Badge variant="green">Pivot {data.app.version}</Badge>
                  {data.app.head && <Badge variant="outline">HEAD {data.app.head}</Badge>}
                </div>
                <div className="space-y-4">
                  <div className="section-kicker">Knowledge Workbench</div>
                  <h1 className="max-w-4xl text-3xl font-semibold tracking-[-0.03em] text-slate-950 sm:text-5xl">
                    {data.welcome.title}
                  </h1>
                  <p className="max-w-3xl text-[15px] leading-8 text-slate-600">
                    这里是团队进入 Pivot 后的工作入口。讨论、结论、上下文和更新记录都在同一块工作台里展开，不需要先穿过一个仪表盘再去找内容。
                  </p>
                </div>
                <div className="grid gap-4 sm:grid-cols-3">
                  <div className="paper-panel rounded-2xl border p-4">
                    <div className="section-kicker">工作方式</div>
                    <div className="mt-2 text-lg font-semibold text-slate-900">先读上下文，再行动</div>
                    <p className="mt-2 text-sm leading-6 text-slate-600">
                      左侧按分类和 thread 组织，右侧是阅读与回复区，适合连续推进讨论。
                    </p>
                  </div>
                  <div className="paper-panel rounded-2xl border p-4">
                    <div className="section-kicker">内容来源</div>
                    <div className="mt-2 text-lg font-semibold text-slate-900">仓库即事实源</div>
                    <p className="mt-2 text-sm leading-6 text-slate-600">
                      首页说明、版本记录和讨论内容都直接来自仓库，方便追溯和沉淀。
                    </p>
                  </div>
                  <div className="paper-panel rounded-2xl border p-4">
                    <div className="section-kicker">下一步</div>
                    <div className="mt-2 text-lg font-semibold text-slate-900">从 thread 开始</div>
                    <p className="mt-2 text-sm leading-6 text-slate-600">
                      你可以从左侧继续已有讨论，也可以直接发起一个新的提案 thread。
                    </p>
                  </div>
                </div>
                <div className="flex flex-wrap gap-3">
                  <Button asChild size="lg" className="h-11 rounded-xl px-5">
                    <Link to="/new">
                      <Rocket className="h-4 w-4" />
                      发起新讨论
                    </Link>
                  </Button>
                  <Button asChild variant="outline" size="lg" className="h-11 rounded-xl border-slate-300 bg-slate-100/85 px-5">
                    <Link to="/admin">
                      <ShieldCheck className="h-4 w-4" />
                      管理员设置
                    </Link>
                  </Button>
                </div>
              </div>
              <div className="space-y-4">
                <div className="ink-panel rounded-[1.25rem] border p-4 sm:rounded-[1.5rem] sm:p-5">
                  <div className="section-kicker">当前实例</div>
                  <div className="mt-4 space-y-4 text-sm">
                    <div className="flex items-center justify-between gap-3">
                      <span className="text-slate-500">Version</span>
                      <span className="font-semibold text-slate-900">{data.app.version}</span>
                    </div>
                    <div className="flex items-center justify-between gap-3">
                      <span className="text-slate-500">Git HEAD</span>
                      <span className="font-mono text-xs text-slate-700">{data.app.head || "N/A"}</span>
                    </div>
                    <div className="editor-divider border-t pt-4 text-sm leading-6 text-slate-600">
                      当前实例的欢迎信息、变更记录和使用说明都来自仓库内容本身，适合拿它当工作环境的入口说明。
                    </div>
                  </div>
                </div>
                <div className="paper-panel rounded-[1.25rem] border p-4 sm:rounded-[1.5rem] sm:p-5">
                  <div className="section-kicker">进入方式</div>
                  <div className="mt-3 space-y-3 text-sm text-slate-600">
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <div className="font-medium text-slate-900">继续一个 thread</div>
                        <div className="mt-1 leading-6">从左侧分类树进入上下文，适合连续推进已有讨论。</div>
                      </div>
                      <ArrowUpRight className="mt-0.5 h-4 w-4 text-slate-400" />
                    </div>
                    <div className="editor-divider border-t pt-3" />
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <div className="font-medium text-slate-900">发起新的提案</div>
                        <div className="mt-1 leading-6">直接进入右侧表单页，从标题、分类和正文开始。</div>
                      </div>
                      <ArrowUpRight className="mt-0.5 h-4 w-4 text-slate-400" />
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </section>

          <Card className="paper-panel rounded-[1.25rem] border bg-slate-100/80 sm:rounded-[1.5rem]">
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <BookOpenText className="h-5 w-5" />
                使用指南
              </CardTitle>
              <CardDescription>来自仓库根目录的 HOME.md</CardDescription>
            </CardHeader>
            <CardContent>
              <div className="prose-pivot text-sm">
                <Markdown remarkPlugins={[remarkGfm]}>{data.welcome.body_md}</Markdown>
              </div>
            </CardContent>
          </Card>
        </div>

        <div className="space-y-6">
          <Card className="paper-panel rounded-[1.25rem] border bg-slate-100/80 sm:rounded-[1.5rem]">
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Sparkles className="h-5 w-5" />
                当前版本
              </CardTitle>
              <CardDescription>当前登录实例的产品版本信息</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3 text-sm">
              <div className="flex items-center justify-between">
                <span className="text-muted-foreground">Version</span>
                <span className="font-semibold">{data.app.version}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-muted-foreground">Git HEAD</span>
                <span className="font-mono text-xs">{data.app.head || "N/A"}</span>
              </div>
            </CardContent>
          </Card>

          <Card className="paper-panel rounded-[1.25rem] border bg-slate-100/80 sm:rounded-[1.5rem]">
            <CardHeader>
              <CardTitle>最新更新</CardTitle>
              <CardDescription>
                {latest ? `${latest.version} · ${latest.date}` : "暂无更新记录"}
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              {latest ? (
                <>
                  <div className="text-base font-semibold text-slate-900">{latest.title}</div>
                  <div className="prose-pivot text-sm">
                    <Markdown remarkPlugins={[remarkGfm]}>{latest.body_md}</Markdown>
                  </div>
                </>
              ) : (
                <div className="text-sm text-muted-foreground">CHANGELOG.md 还没有可展示的版本节。</div>
              )}
            </CardContent>
          </Card>

          <Card className="paper-panel rounded-[1.5rem] border bg-slate-100/80">
            <CardHeader>
              <CardTitle>最近版本</CardTitle>
              <CardDescription>用于快速了解近期功能演进</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              {data.recent_releases.length > 0 ? data.recent_releases.map((release) => (
                <div key={`${release.version}-${release.date}`} className="rounded-lg border border-slate-200/80 bg-slate-100/75 p-3">
                  <div className="flex items-center justify-between gap-3">
                    <div className="font-medium text-slate-900">{release.title}</div>
                    <Badge variant="secondary">{release.version}</Badge>
                  </div>
                  <div className="mt-1 text-xs text-muted-foreground">{release.date}</div>
                </div>
              )) : (
                <div className="text-sm text-muted-foreground">暂无版本记录。</div>
              )}
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
