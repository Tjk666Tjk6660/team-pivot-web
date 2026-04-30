import { toast } from "sonner";
import { AISettingsSection } from "@/pages/AdminPage";
import { PageShell } from "./_PageShell";

export function AdminAI() {
  const onAdminLost = () =>
    toast.error("管理员权限已失效，请刷新或重新登录");
  return (
    <PageShell
      title="AI 助手"
      description="配置 AI 模型 / API key / 上下文与轮次预算。"
    >
      <AISettingsSection onAdminLost={onAdminLost} />
    </PageShell>
  );
}
