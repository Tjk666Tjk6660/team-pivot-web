import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

export function Login() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-muted/30 px-4">
      <Card className="w-full max-w-sm">
        <CardHeader>
          <CardTitle>team-pivot</CardTitle>
          <CardDescription>
            邮件客户端式的团队讨论工具。用飞书账号登录继续。
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Button asChild className="w-full">
            <a href="/login">用飞书登录</a>
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}
