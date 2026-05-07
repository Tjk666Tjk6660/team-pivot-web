import { toast } from "sonner";
import { DailyReportSection } from "./DailyReportSection";
import { PageShell } from "./_PageShell";

export function AdminDailyReport() {
  const onAdminLost = () =>
    toast.error("管理员权限已失效，请刷新或重新登录");
  return (
    <PageShell
      title="日报"
      description="配置每日 / 每周报告的时间窗口、内容与推送目标。"
    >
      <DailyReportSection onAdminLost={onAdminLost} />
    </PageShell>
  );
}
