import type { Me } from "@/api";
import { Button } from "@/components/ui/button";

export function UserBar({ me, onLogout }: { me: Me; onLogout: () => void }) {
  return (
    <div className="flex items-center gap-3">
      {me.avatar_url && (
        <img src={me.avatar_url} alt="" className="h-10 w-10 rounded-full" />
      )}
      <div>
        <div className="font-medium">{me.name}</div>
        <div className="text-xs text-muted-foreground">
          {me.pinyin}
          {me.github_username ? ` · @${me.github_username}` : ""}
        </div>
      </div>
      <Button variant="ghost" size="sm" onClick={onLogout} className="ml-auto">
        Sign out
      </Button>
    </div>
  );
}
