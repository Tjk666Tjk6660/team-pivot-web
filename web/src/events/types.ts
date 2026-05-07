export type MatterChangeReason =
  | "created"
  | "file_appended"
  | "mention_appended"
  | "annotation_appended"
  | "owner_changed"
  // Invalidation/restoration event appended to the timeline. Subscribers
  // should refetch matter detail to pick up the new event entry + the
  // reverse-written invalidated_* fields on the target file. See
  // AI-docs/invalidate-self/product-design.md §5.1 (thin SSE).
  | "event_appended";

export type MatterEvent =
  | {
      type: "matter.created" | "matter.updated";
      matter_id: string;
      reason: MatterChangeReason;
      actor: string | null;
      at: string;
    }
  | {
      type: "resume";
    };

export type MatterEventListener = (event: MatterEvent) => void;
