import type { FileRelevanceReason } from "@/api";

const REASON_LABEL: Record<FileRelevanceReason, string> = {
  owner_assigned: "你被设为 owner",
  reply_to_my_file: "回复你创建的文件",
  reply_to_my_owned: "回复你负责的文件",
  verify_my_file: "verify 你的文件",
  in_my_matter: "你创建的 matter",
  in_my_owned_matter: "你负责的 matter",
};

/**
 * Small inline chip on a FileCard header indicating the file is
 * file-level relevant to the current user, with the reason rendered as
 * a short Chinese label. Renders nothing when reason is null/undefined
 * (file is not relevant) — callers can drop this into a JSX list
 * without conditionals.
 *
 * Comment-level @-mentions are tracked separately via MentionUnreadDot;
 * this chip never shows a `comment_mention` reason — the file row's
 * relevance_reason only carries the 5 file-level reasons.
 */
export function RelevanceChip({
  reason,
}: {
  reason?: FileRelevanceReason | null;
}) {
  if (!reason) return null;
  const label = REASON_LABEL[reason];
  if (!label) return null;
  return (
    <span
      className="inline-flex items-center rounded-full bg-[color-mix(in_srgb,var(--danger-500)_12%,var(--surface))] px-2 py-0.5 text-[11px] font-semibold text-[var(--danger-600)] ring-1 ring-[color-mix(in_srgb,var(--danger-500)_24%,var(--line))]"
      title="跟我相关"
    >
      ★ {label}
    </span>
  );
}
