import { describe, expect, it } from "vitest";
import {
  applyAIDraft,
  computeAtPublish,
  onUserEdit,
  similarity,
  type BodySourceState,
} from "./bodySource";

describe("similarity", () => {
  it("returns 0 when either string is empty", () => {
    expect(similarity("", "abc")).toBe(0);
    expect(similarity("abc", "")).toBe(0);
    expect(similarity("", "")).toBe(0);
  });

  it("returns 1 for identical strings", () => {
    expect(similarity("hello", "hello")).toBe(1);
    expect(similarity("你好世界", "你好世界")).toBe(1);
  });

  it("computes LCS-based ratio for partial overlap", () => {
    // LCS('你好世界', '你好') = 2; max len = 4 → 0.5
    expect(similarity("你好世界", "你好")).toBe(0.5);
  });

  it("handles long-vs-short asymmetry by max length", () => {
    // LCS('abcdef', 'abc') = 3; max = 6 → 0.5
    expect(similarity("abcdef", "abc")).toBe(0.5);
  });
});

describe("applyAIDraft", () => {
  it("always produces ai state with snapshot equal to input", () => {
    const s = applyAIDraft("AI generated body");
    expect(s.body_source).toBe("ai");
    expect(s.body_source_snapshot).toBe("AI generated body");
  });

  it("treats empty AI body as ai (caller decides whether to skip)", () => {
    const s = applyAIDraft("");
    expect(s.body_source).toBe("ai");
    expect(s.body_source_snapshot).toBe("");
  });
});

describe("onUserEdit (manual is sticky)", () => {
  const manual: BodySourceState = { body_source: "manual" };

  it("keeps manual when user types from scratch", () => {
    expect(onUserEdit(manual, "anything").body_source).toBe("manual");
  });

  it("paste-bypass: pasting an exact AI-style snapshot still stays manual", () => {
    // Critical anti-bypass test. Manual state never upgrades regardless of
    // what the user pastes.
    const aiText =
      "这是一段看起来非常像 AI 生成的草稿，结构清晰、有思考沉淀。";
    expect(onUserEdit(manual, aiText).body_source).toBe("manual");
  });
});

describe("onUserEdit (ai → maybe downgrade)", () => {
  const aiBody =
    "Pivot 的 AI 助手应当默认鼓励协作，但允许跳过；发布前对未经协作内容弹质量提示。";
  const ai = applyAIDraft(aiBody);

  it("keeps ai when body is unchanged", () => {
    expect(onUserEdit(ai, aiBody).body_source).toBe("ai");
  });

  it("keeps ai for small edits above similarity threshold", () => {
    // Append a short clarifying sentence; LCS still high.
    const tweaked = aiBody + " 同时记录质量责任。";
    expect(onUserEdit(ai, tweaked).body_source).toBe("ai");
  });

  it("downgrades to manual when body shrinks below 30% of snapshot", () => {
    const tiny = aiBody.slice(0, 5);
    expect(onUserEdit(ai, tiny).body_source).toBe("manual");
  });

  it("downgrades to manual when similarity drops below 0.5", () => {
    // A completely different body of comparable length.
    const replaced =
      "团队需要一个统一的协作平台，关注点是可追溯、可索引、可复盘。";
    expect(onUserEdit(ai, replaced).body_source).toBe("manual");
  });

  it("clearing the body downgrades to manual", () => {
    expect(onUserEdit(ai, "").body_source).toBe("manual");
  });
});

describe("computeAtPublish", () => {
  it("manual state stays manual regardless of similarity", () => {
    const manual: BodySourceState = { body_source: "manual" };
    expect(computeAtPublish(manual, "any text")).toBe("manual");
  });

  it("ai with intact body returns ai", () => {
    const body = "AI generated body content used at publish time";
    const s = applyAIDraft(body);
    expect(computeAtPublish(s, body)).toBe("ai");
  });

  it("ai with mostly-rewritten body returns manual", () => {
    const body = "原始 AI 草稿内容，会被用户大幅改写。";
    const s = applyAIDraft(body);
    expect(computeAtPublish(s, "完全不同的话题，完全不同的句子结构")).toBe(
      "manual",
    );
  });

  it("ai with empty current body returns manual", () => {
    const s = applyAIDraft("anything");
    expect(computeAtPublish(s, "")).toBe("manual");
  });
});

describe("paste-bypass scenario (end-to-end through state transitions)", () => {
  it("manual → paste AI-like long text → still manual at publish", () => {
    const aiLikeText =
      "本次方案要点：1) 默认鼓励 AI 协作；2) 允许直接发布；3) 弹窗不阻塞。";
    let state: BodySourceState = { body_source: "manual" };
    state = onUserEdit(state, aiLikeText);
    expect(state.body_source).toBe("manual");
    expect(computeAtPublish(state, aiLikeText)).toBe("manual");
  });
});
