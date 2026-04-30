import { UserRound } from "lucide-react";
import type { AuthorView } from "@/api";
import { cn } from "@/lib/utils";
import {
  userClassName,
  userInlineStyle,
  userTooltip,
} from "@/lib/displayUser";

export function OwnerChip({
  name,
  avatarUrl,
  view,
  unassigned = false,
  size = "sm",
  className,
  asButton = false,
  onClick,
}: {
  name?: string | null;
  avatarUrl?: string | null;
  view?: AuthorView | null;
  unassigned?: boolean;
  size?: "sm" | "md";
  className?: string;
  asButton?: boolean;
  onClick?: () => void;
}) {
  const label = name || "未分配";
  const status = view?.status ?? "active";
  const statusTooltip = userTooltip(status);
  const avatarSize = size === "md" ? "h-6 w-6" : "h-4 w-4";
  const textSize = size === "md" ? "text-xs" : "text-[11px]";
  const Comp = asButton ? "button" : "span";

  return (
    <Comp
      type={asButton ? "button" : undefined}
      title={
        asButton
          ? `更改负责人：${label}${statusTooltip ? `（${statusTooltip}）` : ""}`
          : statusTooltip ?? label
      }
      onClick={onClick}
      className={cn(
        "inline-flex min-w-[5rem] max-w-[8rem] shrink-0 items-center gap-1.5 rounded-[var(--r-sm)] border border-[var(--line)] bg-[var(--surface-alt)] px-1.5 py-0.5",
        unassigned && "border-dashed text-[var(--text-fade)]",
        size === "md" && "min-w-[6rem] px-2 py-1",
        asButton && "cursor-pointer transition-colors hover:border-[var(--accent-soft)] hover:bg-[var(--accent-bg)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]",
        className,
      )}
    >
      {avatarUrl ? (
        <img
          src={avatarUrl}
          alt=""
          className={cn("shrink-0 rounded-full object-cover", avatarSize)}
        />
      ) : (
        <span
          className={cn(
            "flex shrink-0 items-center justify-center rounded-full bg-[var(--line)] text-[var(--text-fade)]",
            avatarSize,
          )}
        >
          <UserRound className={size === "md" ? "h-3.5 w-3.5" : "h-3 w-3"} />
        </span>
      )}
      <span
        className={cn(
          "min-w-0 truncate font-medium leading-none text-[var(--text-mute)]",
          textSize,
          unassigned && "text-[var(--text-fade)]",
          userClassName(status),
        )}
        style={userInlineStyle(status)}
      >
        {label}
      </span>
    </Comp>
  );
}
