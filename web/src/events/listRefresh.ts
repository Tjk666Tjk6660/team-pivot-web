// Tiny in-app pub/sub for "request a silent matters-list refetch".
//
// When an action mutates server state in a way that affects the matter
// list's red/gray counts but doesn't emit an SSE event (mark-file-read
// being the canonical case — it intentionally does not broadcast so it
// doesn't clutter every subscriber's connection), the caller publishes
// here and Dashboard reacts. We deliberately do NOT route this through
// MatterEventsProvider's `resume` channel because that would also trigger
// MatterDetailPane to refetch its own detail, replacing FileCard's local
// optimistic state and bypassing the post-mark UI delays we just baked in.

const listeners = new Set<() => void>();
const draftListeners = new Set<() => void>();

export function publishListRefresh(): void {
  listeners.forEach((fn) => {
    try {
      fn();
    } catch (err) {
      console.error("listRefresh listener error", err);
    }
  });
}

export function subscribeListRefresh(fn: () => void): () => void {
  listeners.add(fn);
  return () => {
    listeners.delete(fn);
  };
}

export function publishDraftsRefresh(): void {
  draftListeners.forEach((fn) => {
    try {
      fn();
    } catch (err) {
      console.error("draftsRefresh listener error", err);
    }
  });
}

export function subscribeDraftsRefresh(fn: () => void): () => void {
  draftListeners.add(fn);
  return () => {
    draftListeners.delete(fn);
  };
}
