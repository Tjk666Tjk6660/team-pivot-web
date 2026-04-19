import { Badge } from "@/components/ui/badge";

const LABELS: Record<string, { text: string; variant: "blue" | "green" | "purple" | "gray" | "amber" }> = {
  open: { text: "讨论中", variant: "blue" },
  concluded: { text: "已达成结论", variant: "green" },
  produced: { text: "已转为项目", variant: "purple" },
  closed: { text: "已关闭", variant: "gray" },
  pending: { text: "暂时搁置", variant: "amber" },
};

export function StatusBadge({ status }: { status: string | null }) {
  if (!status) return null;
  const s = LABELS[status];
  if (!s) return <Badge variant="outline">{status}</Badge>;
  return <Badge variant={s.variant}>{s.text}</Badge>;
}
