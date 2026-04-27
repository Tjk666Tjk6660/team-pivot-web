import { Badge } from "@/components/ui/badge";
import type { MatterStatus } from "@/api";
import { cn } from "@/lib/utils";

const LABELS: Record<
  MatterStatus,
  {
    text: string;
    variant: "blue" | "amber" | "gray" | "green" | "purple";
  }
> = {
  planning: { text: "讨论中", variant: "blue" },
  executing: { text: "执行中", variant: "amber" },
  paused: { text: "已暂停", variant: "gray" },
  finished: { text: "已完成", variant: "green" },
  cancelled: { text: "已取消", variant: "gray" },
  reviewed: { text: "已复盘", variant: "purple" },
};

type StatusVariant = "blue" | "amber" | "gray" | "green" | "purple";

const DOT_CLASS: Record<StatusVariant, string> = {
  blue: "bg-[var(--info-500)]",
  amber: "bg-[var(--warn-500)]",
  gray: "bg-[var(--text-fade)]",
  green: "bg-[var(--ok-500)]",
  purple: "bg-[var(--violet-600)]",
};

export function StatusBadge({
  status,
  className,
}: {
  status: MatterStatus | string | null | undefined;
  className?: string;
}) {
  if (!status) return null;
  const cfg = LABELS[status as MatterStatus];
  if (!cfg) return <Badge variant="outline">{status}</Badge>;
  return (
    <Badge
      variant={cfg.variant}
      className={cn(
        "gap-1.5 rounded-[var(--r-sm)] border px-2 py-1 text-[11px] font-semibold leading-none",
        cfg.variant === "blue" &&
          "border-[color-mix(in_srgb,var(--info-500)_36%,var(--line))] bg-[color-mix(in_srgb,var(--info-500)_12%,var(--surface))] text-[var(--info-500)]",
        className,
      )}
    >
      <span
        className={cn("h-1.5 w-1.5 rounded-full", DOT_CLASS[cfg.variant])}
      />
      {cfg.text}
    </Badge>
  );
}

export const STATUS_LABELS = LABELS;
