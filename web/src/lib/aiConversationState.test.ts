import { describe, expect, it } from "vitest";
import {
  mergeLoadedAIConversation,
  setAIReplyTarget,
} from "./aiConversationState";

describe("mergeLoadedAIConversation", () => {
  it("keeps a locally selected reply target when a stale load returns null", () => {
    const next = mergeLoadedAIConversation(
      {
        loaded: false,
        loading: false,
        messages: [],
        replyTarget: "001_xiongjianping_think_279dd3.md",
        input: "",
        streaming: false,
        nextId: 1,
      },
      {
        messages: [],
        reply_target: null,
      },
    );

    expect(next.replyTarget).toBe("001_xiongjianping_think_279dd3.md");
  });

  it("uses the loaded reply target when there is no local target", () => {
    const next = mergeLoadedAIConversation(
      {
        loaded: false,
        loading: false,
        messages: [],
        replyTarget: null,
        input: "",
        streaming: false,
        nextId: 1,
      },
      {
        messages: [],
        reply_target: "002_followup_act_abc123.md",
      },
    );

    expect(next.replyTarget).toBe("002_followup_act_abc123.md");
  });

  it("keeps a locally selected reply target when a stale load returns an older target", () => {
    const next = mergeLoadedAIConversation(
      {
        loaded: false,
        loading: false,
        messages: [],
        replyTarget: "003_new_target_verify_def456.md",
        input: "",
        streaming: false,
        nextId: 1,
      },
      {
        messages: [],
        reply_target: "001_old_target_think_279dd3.md",
      },
    );

    expect(next.replyTarget).toBe("003_new_target_verify_def456.md");
  });
});

describe("setAIReplyTarget", () => {
  const baseState = {
    loaded: true,
    loading: false,
    messages: [],
    replyTarget: "001_xiongjianping_think_279dd3.md",
    input: "",
    streaming: false,
    nextId: 1,
  };

  it("does not mark the state changed when the reply target is unchanged", () => {
    const result = setAIReplyTarget(
      baseState,
      "001_xiongjianping_think_279dd3.md",
    );

    expect(result.changed).toBe(false);
    expect(result.state).toBe(baseState);
  });

  it("marks the state changed when the reply target changes", () => {
    const result = setAIReplyTarget(
      baseState,
      "002_followup_act_abc123.md",
    );

    expect(result.changed).toBe(true);
    expect(result.state.replyTarget).toBe("002_followup_act_abc123.md");
  });
});
