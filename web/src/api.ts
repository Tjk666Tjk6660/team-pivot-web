export type Me = {
  open_id: string;
  name: string;
  avatar_url: string;
};

export async function fetchMe(): Promise<Me | null> {
  const r = await fetch("/me", { credentials: "include" });
  if (r.status === 401) return null;
  if (!r.ok) throw new Error(`/me failed: ${r.status}`);
  return (await r.json()) as Me;
}

export async function logout(): Promise<void> {
  await fetch("/logout", { method: "POST", credentials: "include" });
}
