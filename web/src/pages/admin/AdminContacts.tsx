import { toast } from "sonner";
import { SyncContactsSection } from "@/pages/AdminPage";
import { PageShell } from "./_PageShell";

export function AdminContacts() {
  const onAdminLost = () =>
    toast.error("管理员权限已失效，请刷新或重新登录");
  return (
    <PageShell
      title="联系人同步"
      description="从飞书通讯录拉取名单，刷新本地联系人镜像（用于 @-mention 名字解析）。"
    >
      <SyncContactsSection onAdminLost={onAdminLost} />
    </PageShell>
  );
}
