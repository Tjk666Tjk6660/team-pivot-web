import { toast } from "sonner";
import { WorkspaceConfigSection } from "@/pages/AdminPage";
import { PageShell } from "./_PageShell";

export function AdminWorkspace() {
  const onAdminLost = () =>
    toast.error("管理员权限已失效，请刷新或重新登录");
  return (
    <PageShell
      title="数据仓库"
      description="同一套仓库配置同时服务服务器工作区和 VS Code 客户端 mirror。"
    >
      <WorkspaceConfigSection onAdminLost={onAdminLost} />
    </PageShell>
  );
}
