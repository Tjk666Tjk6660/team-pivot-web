import { useEffect, useRef, useState } from "react";
import { createDraft, updateDraft, type Draft, type MentionBlock } from "../api";

export type SaveStatus = "idle" | "saving" | "saved" | "error";

export function useDraftAutosave(params: {
  draftId: string | null;
  setDraftId: (id: string) => void;
  type: "proposal" | "reply";
  payload: () => {
    title?: string | null;
    category?: string | null;
    body_md: string;
    thread_key?: string | null;
    mentions?: MentionBlock | null;
    reply_to?: string | null;
    references?: string[];
  };
  enabled: boolean;
  debounceMs?: number;
  deps: unknown[];
}): { status: SaveStatus; error: string | null; saveNow: () => Promise<string | null> } {
  const { draftId, setDraftId, type, payload, enabled, debounceMs = 2000, deps } = params;
  const [status, setStatus] = useState<SaveStatus>("idle");
  const [error, setError] = useState<string | null>(null);
  const timer = useRef<number | null>(null);
  const inFlight = useRef<Promise<string | null> | null>(null);

  // Use a ref so that delayed timers always read the latest draftId. Without this,
  // a timer scheduled when draftId=null can fire after a parent has set draftId=X
  // and create a duplicate draft (its captured `save` still saw draftId=null).
  const draftIdRef = useRef(draftId);
  useEffect(() => { draftIdRef.current = draftId; }, [draftId]);

  const save = async (): Promise<string | null> => {
    setStatus("saving");
    setError(null);
    try {
      const p = payload();
      const currentId = draftIdRef.current;
      if (currentId === null) {
        const d = await createDraft({ type, ...p });
        draftIdRef.current = d.id;
        setDraftId(d.id);
        setStatus("saved");
        return d.id;
      }
      const d = await updateDraft(currentId, p);
      setStatus("saved");
      return d.id;
    } catch (e) {
      setStatus("error");
      setError(e instanceof Error ? e.message : String(e));
      return null;
    }
  };

  useEffect(() => {
    if (!enabled) return;
    if (timer.current) window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => {
      if (!inFlight.current) {
        inFlight.current = save().finally(() => {
          inFlight.current = null;
        });
      }
    }, debounceMs);
    return () => {
      if (timer.current) window.clearTimeout(timer.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  const saveNow = async (): Promise<string | null> => {
    if (timer.current) window.clearTimeout(timer.current);
    if (inFlight.current) return inFlight.current;
    inFlight.current = save().finally(() => {
      inFlight.current = null;
    });
    return inFlight.current;
  };

  return { status, error, saveNow };
}

export function formatSaveStatus(s: SaveStatus, updatedAt?: number | null): string {
  switch (s) {
    case "saving": return "Saving…";
    case "saved": return updatedAt ? "Draft saved" : "Draft saved";
    case "error": return "Save failed";
    default: return "";
  }
}

export type { Draft };
