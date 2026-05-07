import type { AuthorView } from "@/api";

type Props = {
  view?: AuthorView | null;
  name: string;
  size?: number;
};

export function InlineUserAvatar({ view, name, size = 14 }: Props) {
  const px = `${size}px`;
  const fallback = (name || "?").trim().charAt(0) || "?";
  const url = view?.avatar_url ?? null;
  if (url) {
    return (
      <img
        src={url}
        alt=""
        className="inline-block shrink-0 rounded-full object-cover align-[-2px]"
        style={{ width: px, height: px }}
      />
    );
  }
  return (
    <span
      className="inline-flex shrink-0 items-center justify-center rounded-full bg-[var(--surface-alt)] font-semibold text-[var(--text-soft)] ring-1 ring-[var(--line)] align-[-2px]"
      style={{ width: px, height: px, fontSize: Math.max(8, size - 5) }}
    >
      {fallback}
    </span>
  );
}
