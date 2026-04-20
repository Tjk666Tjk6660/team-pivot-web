import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { BookOpenText, Rocket, ShieldCheck, Sparkles } from "lucide-react";
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
    <div className="mx-auto max-w-6xl px-4 py-6 sm:px-6 lg:px-8 lg:py-8">
      <div className="grid gap-6 xl:grid-cols-[minmax(0,1.6fr)_minmax(320px,0.9fr)]">
        <div className="space-y-6">
          <section className="overflow-hidden rounded-3xl border bg-gradient-to-br from-slate-50 via-white to-emerald-50 shadow-sm">
            <div className="space-y-6 px-5 py-7 sm:px-8 sm:py-10">
              <div className="flex flex-wrap items-center gap-3">
                <Badge variant="green">Pivot {data.app.version}</Badge>
                {data.app.head && <Badge variant="outline">HEAD {data.app.head}</Badge>}
              </div>
              <div className="space-y-3">
                <h1 className="text-2xl font-semibold tracking-tight text-slate-900 sm:text-3xl">
                  {data.welcome.title}
                </h1>
                <p className="max-w-3xl text-sm leading-7 text-slate-600">
                  这里是团队进入 Pivot 后的工作台首页。先读清楚当前版本和推荐工作流，再从讨论开始，把团队执行过程沉淀到文档流里。
                </p>
              </div>
              <div className="flex flex-wrap gap-3">
                <Button asChild size="lg" className="w-full sm:w-auto">
                  <Link to="/new">
                    <Rocket className="h-4 w-4" />
                    发起新讨论
                  </Link>
                </Button>
                <Button asChild variant="outline" size="lg" className="w-full sm:w-auto">
                  <Link to="/admin">
                    <ShieldCheck className="h-4 w-4" />
                    管理员设置
                  </Link>
                </Button>
              </div>
            </div>
          </section>

          <Card>
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
          <Card className="border-slate-200">
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

          <Card className="border-slate-200">
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

          <Card className="border-slate-200">
            <CardHeader>
              <CardTitle>最近版本</CardTitle>
              <CardDescription>用于快速了解近期功能演进</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              {data.recent_releases.length > 0 ? data.recent_releases.map((release) => (
                <div key={`${release.version}-${release.date}`} className="rounded-xl border p-3">
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
