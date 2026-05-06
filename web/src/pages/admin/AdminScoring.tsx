import { NavLink, Outlet } from "react-router-dom";
import { Toaster } from "sonner";
import { PageShell } from "./_PageShell";

/** Top-level shell for /admin/scoring/*.
 *
 *  Three tabs (path-based, bookmarkable):
 *    /admin/scoring           → 评分     (RunsListTab, default landing)
 *    /admin/scoring/config    → 配置     (ConfigTab)
 *    /admin/scoring/weights   → 权重     (WeightsTab)
 *
 *  Default = runs list because admin's daily use case is monitoring task
 *  status / re-running failed runs, not adjusting config.
 */
const TABS: { to: string; label: string; end?: boolean }[] = [
  { to: ".", label: "评分", end: true },
  { to: "config", label: "配置" },
  { to: "weights", label: "权重" },
];

export function AdminScoring() {
  return (
    <PageShell
      title="Matter 评分"
      description="Matter 进入 finished 后由 AI 基于时间线生成 owner 评分。v1 仅 admin 可见。"
      wide
    >
      <Toaster position="top-center" richColors />
      <nav
        className="-mt-2 mb-5 flex gap-1 border-b"
        style={{ borderColor: "var(--line)" }}
      >
        {TABS.map((t) => (
          <NavLink
            key={t.to}
            to={t.to}
            end={t.end}
            className={({ isActive }) =>
              [
                "-mb-px border-b-2 px-3 py-2 text-sm transition-colors",
                isActive
                  ? "border-[var(--accent)] font-semibold text-[var(--accent)]"
                  : "border-transparent text-[var(--text-mute)] hover:text-[var(--text)]",
              ].join(" ")
            }
          >
            {t.label}
          </NavLink>
        ))}
      </nav>
      <Outlet />
    </PageShell>
  );
}
