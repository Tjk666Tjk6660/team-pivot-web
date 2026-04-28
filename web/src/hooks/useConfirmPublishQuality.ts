import { useCallback, useRef, useState, createElement, type ReactElement } from "react";
import { PublishQualityConfirmDialog } from "@/components/PublishQualityConfirmDialog";
import type { BodySource } from "@/lib/bodySource";

export type GateResult = "go" | "send_to_ai" | "cancel";

type Pending = {
  resolve: (r: GateResult) => void;
  blockedByAIBusy: boolean;
  busyTitle?: string;
};

export function useConfirmPublishQuality(): {
  dialog: ReactElement;
  confirm: (args: {
    bodySource: BodySource;
    blockedByAIBusy: boolean;
    busyTitle?: string;
  }) => Promise<GateResult>;
} {
  const [pending, setPending] = useState<Pending | null>(null);
  // Guard against concurrent confirm() calls — only one dialog at a time.
  const inFlight = useRef<Pending | null>(null);

  const close = useCallback((result: GateResult) => {
    const p = inFlight.current;
    if (!p) return;
    inFlight.current = null;
    setPending(null);
    p.resolve(result);
  }, []);

  const confirm = useCallback(
    (args: {
      bodySource: BodySource;
      blockedByAIBusy: boolean;
      busyTitle?: string;
    }): Promise<GateResult> => {
      if (args.bodySource === "ai") {
        return Promise.resolve("go");
      }
      if (inFlight.current) {
        // A dialog is already up; resolve the new caller as cancel to avoid
        // double-publish / interleaved state.
        return Promise.resolve("cancel");
      }
      return new Promise<GateResult>((resolve) => {
        const p: Pending = {
          resolve,
          blockedByAIBusy: args.blockedByAIBusy,
          busyTitle: args.busyTitle,
        };
        inFlight.current = p;
        setPending(p);
      });
    },
    [],
  );

  const dialog = createElement(PublishQualityConfirmDialog, {
    open: pending !== null,
    blockedByAIBusy: pending?.blockedByAIBusy ?? false,
    busyTitle: pending?.busyTitle,
    onForcePublish: () => close("go"),
    onSendToAI: () => close("send_to_ai"),
    onCancel: () => close("cancel"),
  });

  return { dialog, confirm };
}
