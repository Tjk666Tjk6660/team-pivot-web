import { describe, expect, it } from "vitest";
import {
  isNearScrollBottom,
  shouldNotifyBackgroundAIComplete,
  shouldNotifyBackgroundAIOnClose,
  shouldShowBackgroundAIControl,
} from "./aiPanelState";

describe("shouldShowBackgroundAIControl", () => {
  it("shows the background control only when this thread is streaming and the pane is closed", () => {
    expect(
      shouldShowBackgroundAIControl({
        activeThreadKey: "category/matter-1",
        currentThreadKey: "category/matter-1",
        aiOpen: false,
      }),
    ).toBe(true);

    expect(
      shouldShowBackgroundAIControl({
        activeThreadKey: "category/matter-1",
        currentThreadKey: "category/matter-1",
        aiOpen: true,
      }),
    ).toBe(false);

    expect(
      shouldShowBackgroundAIControl({
        activeThreadKey: "category/matter-2",
        currentThreadKey: "category/matter-1",
        aiOpen: false,
      }),
    ).toBe(false);

    expect(
      shouldShowBackgroundAIControl({
        activeThreadKey: null,
        currentThreadKey: "category/matter-1",
        aiOpen: false,
      }),
    ).toBe(false);
  });
});

describe("shouldNotifyBackgroundAIOnClose", () => {
  it("notifies only when closing this thread while it is streaming", () => {
    expect(
      shouldNotifyBackgroundAIOnClose({
        activeThreadKey: "category/matter-1",
        currentThreadKey: "category/matter-1",
      }),
    ).toBe(true);

    expect(
      shouldNotifyBackgroundAIOnClose({
        activeThreadKey: "category/matter-2",
        currentThreadKey: "category/matter-1",
      }),
    ).toBe(false);

    expect(
      shouldNotifyBackgroundAIOnClose({
        activeThreadKey: null,
        currentThreadKey: "category/matter-1",
      }),
    ).toBe(false);
  });
});

describe("shouldNotifyBackgroundAIComplete", () => {
  it("notifies when a background stream for this thread is no longer active", () => {
    expect(
      shouldNotifyBackgroundAIComplete({
        backgroundThreadKey: "category/matter-1",
        activeThreadKey: null,
        currentThreadKey: "category/matter-1",
        aiOpen: false,
      }),
    ).toBe(true);

    expect(
      shouldNotifyBackgroundAIComplete({
        backgroundThreadKey: "category/matter-1",
        activeThreadKey: "category/matter-2",
        currentThreadKey: "category/matter-1",
        aiOpen: false,
      }),
    ).toBe(true);
  });

  it("does not notify while the stream is still active, the pane is open, or the user left the thread", () => {
    expect(
      shouldNotifyBackgroundAIComplete({
        backgroundThreadKey: "category/matter-1",
        activeThreadKey: "category/matter-1",
        currentThreadKey: "category/matter-1",
        aiOpen: false,
      }),
    ).toBe(false);

    expect(
      shouldNotifyBackgroundAIComplete({
        backgroundThreadKey: "category/matter-1",
        activeThreadKey: null,
        currentThreadKey: "category/matter-1",
        aiOpen: true,
      }),
    ).toBe(false);

    expect(
      shouldNotifyBackgroundAIComplete({
        backgroundThreadKey: "category/matter-2",
        activeThreadKey: null,
        currentThreadKey: "category/matter-1",
        aiOpen: false,
      }),
    ).toBe(false);
  });
});

describe("isNearScrollBottom", () => {
  it("treats the pane as sticky only when it is near the bottom", () => {
    expect(
      isNearScrollBottom({
        scrollTop: 693,
        clientHeight: 300,
        scrollHeight: 1000,
      }),
    ).toBe(true);

    expect(
      isNearScrollBottom({
        scrollTop: 500,
        clientHeight: 300,
        scrollHeight: 1000,
      }),
    ).toBe(false);
  });
});
