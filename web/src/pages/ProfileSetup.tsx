import { useState } from "react";
import { updateProfile, type Me } from "@/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export function ProfileSetup({ me, onDone }: { me: Me; onDone: (m: Me) => void }) {
  const [pinyin, setPinyin] = useState("");
  const [github, setGithub] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const updated = await updateProfile({
        pinyin: pinyin.trim(),
        github_username: github.trim() || null,
      });
      onDone(updated);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-muted/30 px-4">
      <Card className="w-full max-w-md">
        <CardHeader>
          <CardTitle>欢迎，{me.name}</CardTitle>
          <CardDescription>
            一次性设置。用作 git author 和分支名。
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={submit} className="flex flex-col gap-4">
            <div className="grid gap-2">
              <Label htmlFor="pinyin">拼音名（必填）</Label>
              <Input
                id="pinyin"
                value={pinyin}
                onChange={(e) => setPinyin(e.target.value)}
                placeholder="dengke / keller.koh"
                required
              />
              <p className="text-xs text-muted-foreground">
                小写字母、数字和 <code>. _ -</code>，以字母开头。
              </p>
            </div>
            <div className="grid gap-2">
              <Label htmlFor="github">GitHub 用户名（可选）</Label>
              <Input
                id="github"
                value={github}
                onChange={(e) => setGithub(e.target.value)}
                placeholder="your-github-handle"
              />
            </div>
            {error && <p className="text-sm text-destructive">{error}</p>}
            <Button type="submit" disabled={submitting || !pinyin.trim()}>
              {submitting ? "保存中…" : "Continue"}
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
