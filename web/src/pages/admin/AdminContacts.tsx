import { useEffect, useState } from "react";
import { toast } from "sonner";
import { fetchMe, type Me } from "@/api";
import { SyncContactsSection } from "@/pages/AdminPage";
import { PageShell } from "./_PageShell";

export function AdminContacts() {
  const [me, setMe] = useState<Me | null | undefined>(undefined);
  useEffect(() => {
    fetchMe().then(setMe).catch(() => setMe(null));
  }, []);

  const onAdminLost = () =>
    toast.error("管理员权限已失效，请刷新或重新登录");

  // Direct-URL guard：侧栏已经按 me.providers 隐藏了这个菜单条目，
  // 但 admin 直接输 /admin/contacts 仍会进来。给个兜底提示而不是
  // 让 SyncContactsSection 跑出 403 toast。
  if (me === undefined) {
    return <PageShell title="联系人同步"><p>加载中…</p></PageShell>;
  }
  if (me && !me.providers.includes("feishu")) {
    return (
      <PageShell
        title="联系人同步"
        description="从飞书通讯录拉取名单，刷新本地联系人镜像（用于 @-mention 名字解析）。"
      >
        <p
          className="rounded-[var(--r-sm)] p-4 text-[13px]"
          style={{
            background: "var(--surface-alt)",
            border: "1px solid var(--line)",
            color: "var(--text-soft)",
          }}
        >
          你当前的账号没有绑定飞书，无法触发同步。请用飞书登录后再访问此页，
          或让另一位绑了飞书的管理员来执行同步。
        </p>
      </PageShell>
    );
  }

  return (
    <PageShell
      title="联系人同步"
      description="从飞书通讯录拉取名单，刷新本地联系人镜像（用于 @-mention 名字解析）。"
    >
      <SyncContactsSection onAdminLost={onAdminLost} />
    </PageShell>
  );
}
