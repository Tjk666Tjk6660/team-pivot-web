import type { InvalidationReason } from "@/api";

const REASON_LABEL: Record<InvalidationReason, string> = {
  misposted: "误发",
  inaccurate: "信息有误",
  // restored never appears as a current invalidated_reason, but keep the key
  // for type-safety so callers don't have to narrow.
  restored: "恢复",
};

/** Tag shown at the top of a file card when item.invalidated === true.
 *
 * Per AI-docs/invalidate-self/product-design.md §四:
 *   失效是声明式撤回,不是隐藏机制。原文仍展示,UI 仅渲染层标记"已失效(理由)"。
 */
export function InvalidatedBadge({
  reason,
  by,
}: {
  reason?: InvalidationReason | null;
  by?: string | null;
}) {
  const label = reason ? REASON_LABEL[reason] : null;
  return (
    <span
      className="inline-flex items-center gap-1 rounded-md bg-[color-mix(in_srgb,var(--warn-500)_12%,var(--surface))] px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide text-[var(--warn-700)] ring-1 ring-[color-mix(in_srgb,var(--warn-500)_24%,var(--line))]"
      title={
        by
          ? `已失效${label ? `(${label})` : ""}・由 ${by} 撤回`
          : `已失效${label ? `(${label})` : ""}`
      }
    >
      <span aria-hidden>⊘</span>
      <span>已失效{label ? `（${label}）` : ""}</span>
    </span>
  );
}
