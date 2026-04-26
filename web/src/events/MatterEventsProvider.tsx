import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  type PropsWithChildren,
} from "react";
import type {
  MatterEvent,
  MatterEventListener,
  MatterChangeReason,
} from "./types";

type Subscribe = (listener: MatterEventListener) => () => void;

const Ctx = createContext<{ subscribe: Subscribe } | null>(null);

const SSE_ENDPOINT = "/api/matters/events";

interface ServerEventPayload {
  matter_id: string;
  reason: MatterChangeReason;
  actor: string | null;
  at: string;
}

function parsePayload(raw: string): ServerEventPayload | null {
  try {
    const parsed = JSON.parse(raw);
    if (parsed && typeof parsed.matter_id === "string") {
      return parsed as ServerEventPayload;
    }
  } catch {
    // fall through
  }
  return null;
}

export function MatterEventsProvider({ children }: PropsWithChildren) {
  // Listeners are stored in a ref so the provider does not re-render on
  // subscribe/unsubscribe; the dispatch path stays a stable reference.
  const listenersRef = useRef<Set<MatterEventListener>>(new Set());

  const dispatch = useCallback((event: MatterEvent) => {
    listenersRef.current.forEach((listener) => {
      try {
        listener(event);
      } catch (err) {
        // A faulty listener must not break the dispatch loop for others.
        console.error("matter event listener error", err);
      }
    });
  }, []);

  // SSE connection. EventSource handles auto-reconnect and Last-Event-ID
  // automatically; we only forward connection-restored signals as `resume`
  // so subscribers can do a full refetch to cover any missed events.
  useEffect(() => {
    const es = new EventSource(SSE_ENDPOINT, { withCredentials: true });
    let hasOpenedOnce = false;

    const onPayload = (
      type: "matter.created" | "matter.updated",
    ) => (ev: MessageEvent<string>) => {
      const payload = parsePayload(ev.data);
      if (!payload) return;
      dispatch({ type, ...payload });
    };

    es.addEventListener("matter.created", onPayload("matter.created"));
    es.addEventListener("matter.updated", onPayload("matter.updated"));

    const onOpen = () => {
      // First successful open is just initial connect; only treat subsequent
      // opens (i.e. reconnects) as resume signals so subscribers do not
      // double-fetch on initial mount.
      if (hasOpenedOnce) {
        dispatch({ type: "resume" });
      } else {
        hasOpenedOnce = true;
      }
    };
    es.addEventListener("open", onOpen);

    return () => {
      es.removeEventListener("open", onOpen);
      es.close();
    };
  }, [dispatch]);

  // Resume on tab visibility / focus / BFCache restore. These cover the
  // gap when SSE was paused (mobile background, Feishu WebView freeze, etc.)
  // but the EventSource has not yet visibly reconnected.
  useEffect(() => {
    const fire = () => dispatch({ type: "resume" });
    const onVis = () => {
      if (document.visibilityState === "visible") fire();
    };
    const onPageShow = (e: PageTransitionEvent) => {
      if (e.persisted) fire();
    };
    document.addEventListener("visibilitychange", onVis);
    window.addEventListener("focus", fire);
    window.addEventListener("pageshow", onPageShow);
    return () => {
      document.removeEventListener("visibilitychange", onVis);
      window.removeEventListener("focus", fire);
      window.removeEventListener("pageshow", onPageShow);
    };
  }, [dispatch]);

  const value = useMemo(
    () => ({
      subscribe: ((listener: MatterEventListener) => {
        listenersRef.current.add(listener);
        return () => {
          listenersRef.current.delete(listener);
        };
      }) satisfies Subscribe,
    }),
    [],
  );

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useMatterEvents(handler: MatterEventListener): void {
  const ctx = useContext(Ctx);
  if (!ctx) {
    throw new Error("useMatterEvents must be used within <MatterEventsProvider>");
  }
  useEffect(() => ctx.subscribe(handler), [ctx, handler]);
}
