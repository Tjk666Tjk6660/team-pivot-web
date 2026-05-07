/** Helpers for rendering a user reference with the right visual cue
 *  given the resolved status (mirrors server-side mentions.author_view).
 *
 *  - active   → no special styling
 *  - suspended → italic + muted
 *  - deleted   → gray (text-gray-400) + tooltip
 *  - unknown   → gray + tooltip explaining the user is unknown
 */

export type UserStatus = "active" | "suspended" | "deleted" | "unknown";

export interface DisplayInfo {
  user_id: string;
  open_id: string;
  display_name: string;
  avatar_url: string | null;
  status: UserStatus;
}

export function userClassName(status: UserStatus): string {
  switch (status) {
    case "deleted":
      return "text-gray-400 line-through decoration-gray-300";
    case "suspended":
      return "text-gray-500 italic";
    case "unknown":
      return "text-gray-400";
    default:
      return "";
  }
}

export function userTooltip(status: UserStatus): string | null {
  switch (status) {
    case "deleted":
      return "该用户已注销";
    case "suspended":
      return "该用户已暂停登录";
    case "unknown":
      return "该用户未在 Pivot 注册";
    default:
      return null;
  }
}

export function userInlineStyle(status: UserStatus): React.CSSProperties {
  // 行内 style fallback：当外层文字色经 CSS 变量主导、tailwind 类无法覆盖时使用。
  switch (status) {
    case "deleted":
      return { color: "var(--text-mute)", textDecoration: "line-through" };
    case "suspended":
      return { color: "var(--text-mute)", fontStyle: "italic" };
    case "unknown":
      return { color: "var(--text-mute)" };
    default:
      return {};
  }
}
