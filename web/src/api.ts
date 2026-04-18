export type Me = {
  open_id: string;
  name: string;
  avatar_url: string;
  pinyin: string | null;
  github_username: string | null;
  needs_setup: boolean;
};

export async function fetchMe(): Promise<Me | null> {
  const r = await fetch("/me", { credentials: "include" });
  if (r.status === 401) return null;
  if (!r.ok) throw new Error(`/me failed: ${r.status}`);
  return (await r.json()) as Me;
}

export async function updateProfile(
  body: { pinyin?: string; github_username?: string | null },
): Promise<Me> {
  const r = await fetch("/me/profile", {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) {
    const detail = await r.json().catch(() => ({ detail: r.statusText }));
    throw new Error(detail.detail || `/me/profile failed: ${r.status}`);
  }
  return (await r.json()) as Me;
}

export async function logout(): Promise<void> {
  await fetch("/logout", { method: "POST", credentials: "include" });
}
