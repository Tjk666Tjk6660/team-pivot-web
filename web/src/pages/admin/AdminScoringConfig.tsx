import { toast } from "sonner";
import { ScoringConfigSection } from "@/components/admin/scoring/ScoringConfigSection";
import { PageShell } from "./_PageShell";

export function AdminScoringConfig() {
  const onAdminLost = () =>
    toast.error("管理员权限已失效，请刷新或重新登录");
  return (
    <PageShell
      title="Matter 评分"
      description="配置 Matter 评分的开关、可见范围、模型和超时时间。"
    >
      <ScoringConfigSection onAdminLost={onAdminLost} />
    </PageShell>
  );
}
