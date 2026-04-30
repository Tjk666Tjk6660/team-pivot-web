import { toast } from "sonner";
import { MarkdownSettingsSection } from "@/pages/AdminPage";
import { PageShell } from "./_PageShell";

export function AdminMarkdown() {
  const onAdminLost = () =>
    toast.error("管理员权限已失效，请刷新或重新登录");
  return (
    <PageShell
      title="正文主题"
      description="设置全员默认的 Markdown 渲染主题；用户也可在个人设置里覆盖。"
    >
      <MarkdownSettingsSection onAdminLost={onAdminLost} />
    </PageShell>
  );
}
