export type MatterChangeReason =
  | "created"
  | "file_appended"
  | "comment_appended"
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
