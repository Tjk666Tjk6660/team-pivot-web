export type MatterChangeReason =
  | "created"
  | "file_appended"
  | "mention_appended"
  | "annotation_appended"
  | "owner_changed";

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
