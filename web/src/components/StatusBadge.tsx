import { Badge } from "@/components/ui/badge";
import type { MatterStatus } from "@/api";

const LABELS: Record<MatterStatus, {
  text: string;
  variant: "blue" | "amber" | "gray" | "green" | "purple";
}> = {
  planning:  { text: "规划中", variant: "blue" },
  executing: { text: "执行中", variant: "amber" },
  paused:    { text: "已暂停", variant: "gray" },
  finished:  { text: "已完成", variant: "green" },
  cancelled: { text: "已取消", variant: "gray" },
  reviewed:  { text: "已复盘", variant: "purple" },
};

export function StatusBadge({ status }: { status: MatterStatus | string | null | undefined }) {
  if (!status) return null;
  const cfg = LABELS[status as MatterStatus];
  if (!cfg) return <Badge variant="outline">{status}</Badge>;
  return <Badge variant={cfg.variant}>{cfg.text}</Badge>;
}

export const STATUS_LABELS = LABELS;
