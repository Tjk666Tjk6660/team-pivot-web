import { describe, expect, it } from "vitest";
import {
  DEFAULT_MARKDOWN_STYLE,
  MARKDOWN_STYLES,
  getMarkdownStyleClass,
  isMarkdownStyleId,
} from "./markdownStyles";

describe("markdownStyles", () => {
  it("defines six built-in themes with a valid default", () => {
    expect(MARKDOWN_STYLES).toHaveLength(6);
    expect(MARKDOWN_STYLES.some((style) => style.id === DEFAULT_MARKDOWN_STYLE))
      .toBe(true);
  });

  it("validates known and unknown style ids", () => {
    expect(isMarkdownStyleId("code-light")).toBe(true);
    expect(isMarkdownStyleId("neon-dark")).toBe(true);
    expect(isMarkdownStyleId("unknown")).toBe(false);
    expect(isMarkdownStyleId(null)).toBe(false);
  });

  it("maps style ids to prose modifier classes", () => {
    expect(getMarkdownStyleClass("code-light")).toBe("prose-pivot--code-light");
    expect(getMarkdownStyleClass("nord-dark")).toBe("prose-pivot--nord-dark");
  });
});
