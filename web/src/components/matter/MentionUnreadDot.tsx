/**
 * Tiny red dot rendered on a comment row when the current user is
 * @-mentioned in that specific comment AND has not yet read the host
 * file (POST /matters/{id}/files/{f}/read clears it).
 *
 * Renders nothing when `show` is false/undefined so callers can drop
 * this into JSX unconditionally.
 */
export function MentionUnreadDot({ show }: { show?: boolean }) {
  if (!show) return null;
  return (
    <span
      className="ml-1 inline-block h-1.5 w-1.5 shrink-0 rounded-full bg-[var(--danger-500)] align-middle"
      title="@ 你 · 未读"
      aria-label="未读 @"
    />
  );
}
