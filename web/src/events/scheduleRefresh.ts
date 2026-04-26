const DEFAULT_DEBOUNCE_MS = 300;

const timers = new Map<string, ReturnType<typeof setTimeout>>();

export function scheduleRefresh(
  key: string,
  fn: () => void | Promise<void>,
  debounceMs: number = DEFAULT_DEBOUNCE_MS,
): void {
  const existing = timers.get(key);
  if (existing) clearTimeout(existing);
  const handle = setTimeout(() => {
    timers.delete(key);
    void fn();
  }, debounceMs);
  timers.set(key, handle);
}

export function cancelScheduledRefresh(key: string): void {
  const existing = timers.get(key);
  if (existing) {
    clearTimeout(existing);
    timers.delete(key);
  }
}
