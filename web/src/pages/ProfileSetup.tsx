import { useState } from "react";
import { updateProfile, type Me } from "@/api";
import { Button } from "@/components/ui/button";
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

  const initial = me.name.slice(0, 1);

  return (
    <div
      className="grid min-h-screen place-items-center px-4 py-10"
      style={{ background: "var(--bg-alt)" }}
    >
      <div
        className="w-full max-w-[520px] rounded-[var(--r-lg)] p-9 sm:p-11"
        style={{
          background: "var(--surface)",
          border: "1px solid var(--line)",
          boxShadow: "var(--shadow-md)",
        }}
      >
        <div className="mb-5 flex items-center gap-3.5">
          {me.avatar_url ? (
            <img src={me.avatar_url} alt="" className="h-12 w-12 rounded-full" />
          ) : (
            <span
              className="flex h-12 w-12 items-center justify-center rounded-full text-[18px] font-semibold uppercase"
              style={{ background: "var(--accent-bg)", color: "var(--accent)" }}
            >
              {initial}
            </span>
          )}
          <div>
            <div
              className="text-[10.5px] font-bold uppercase tracking-[0.18em] font-meta"
              style={{ color: "var(--text-mute)" }}
            >
              一次性设置
            </div>
            <h2
              className="m-0 mt-1 text-[24px]"
              style={{
                fontFamily: "var(--font-serif)",
                fontWeight: 600,
                letterSpacing: "var(--letter-tight)",
                color: "var(--text)",
              }}
            >
              欢迎，{me.name}。
            </h2>
          </div>
        </div>
        <p
          className="m-0 text-[14px] leading-[1.65]"
          style={{ fontFamily: "var(--font-serif)", color: "var(--text-soft)" }}
        >
          用作 git author 和分支名。之后可以在个人设置里改。
        </p>

        <form onSubmit={submit} className="mt-6 flex flex-col gap-5">
          <div className="grid gap-1.5">
            <Label
              htmlFor="pinyin"
              className="flex items-center gap-2 text-[13px] font-semibold"
              style={{ color: "var(--text)" }}
            >
              拼音名
              <span
                className="text-[10px] font-bold tracking-[0.08em] font-meta"
                style={{ color: "var(--danger-500)" }}
              >
                必填
              </span>
            </Label>
            <Input
              id="pinyin"
              value={pinyin}
              onChange={(e) => setPinyin(e.target.value)}
              placeholder="dengke / keller.koh"
              required
              className="h-10 rounded-[var(--r-sm)] font-mono text-[14px]"
              style={{
                background: "var(--surface-alt)",
                border: "1.5px solid var(--accent)",
                color: "var(--text)",
              }}
            />
            <p
              className="text-[11.5px] font-meta leading-[1.5]"
              style={{ color: "var(--text-mute)" }}
            >
              小写字母、数字和{" "}
              <code
                className="rounded px-1 py-0.5 font-mono"
                style={{ background: "var(--surface-alt)", border: "1px solid var(--line)" }}
              >
                . _ -
              </code>
              ，以字母开头。
            </p>
          </div>
          <div className="grid gap-1.5">
            <Label
              htmlFor="github"
              className="flex items-center gap-2 text-[13px] font-semibold"
              style={{ color: "var(--text)" }}
            >
              GitHub 用户名
              <span
                className="text-[10px] font-meta"
                style={{ color: "var(--text-mute)" }}
              >
                可选
              </span>
            </Label>
            <Input
              id="github"
              value={github}
              onChange={(e) => setGithub(e.target.value)}
              placeholder="your-github-handle"
              className="h-10 rounded-[var(--r-sm)] font-mono text-[14px]"
              style={{
                background: "var(--surface-alt)",
                border: "1px solid var(--line)",
                color: "var(--text)",
              }}
            />
          </div>
          {error && (
            <p className="text-[12px]" style={{ color: "var(--danger-500)" }}>
              {error}
            </p>
          )}
          <div className="flex justify-end pt-2">
            <Button
              type="submit"
              disabled={submitting || !pinyin.trim()}
              className="h-10 rounded-[var(--r-sm)] px-5 text-[14px] font-semibold shadow-none"
              style={{
                background: "var(--accent)",
                color: "var(--accent-ink)",
                border: "1px solid var(--accent)",
              }}
            >
              {submitting ? "保存中…" : "Continue"}
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
}
