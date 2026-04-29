import { describe, expect, it } from "vitest";
import {
  COPY_FOR_AI_GUIDE_KEY_PREFIX,
  copyForAIGuideStorageKey,
  shouldShowCopyForAIGuide,
} from "./copyForAIGuide";

describe("copyForAIGuideStorageKey", () => {
  it("scopes the guide state to the current user when open_id is available", () => {
    expect(copyForAIGuideStorageKey("ou_xxx")).toBe(
      `${COPY_FOR_AI_GUIDE_KEY_PREFIX}:ou_xxx`,
    );
  });

  it("falls back to a browser-level key when the current user cannot be loaded", () => {
    expect(copyForAIGuideStorageKey(null)).toBe(
      `${COPY_FOR_AI_GUIDE_KEY_PREFIX}:anonymous`,
    );
  });
});

describe("shouldShowCopyForAIGuide", () => {
  it("shows the guide until the scoped key has been stored", () => {
    expect(shouldShowCopyForAIGuide(null)).toBe(true);
    expect(shouldShowCopyForAIGuide("1")).toBe(false);
  });
});
