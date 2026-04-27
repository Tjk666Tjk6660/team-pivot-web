import { describe, it, expect } from "vitest";
import {
  claudeCodePrompt,
  cursorDeepLink,
  codexCliCommand,
  claudeDesktopConnectionInfo,
  CLAUDE_DESKTOP_UI_HINT,
} from "./clientConfigs";

describe("clientConfigs", () => {
  it("claude code prompt embeds token and type:http hint", () => {
    const p = claudeCodePrompt("pvt_xxx");
    expect(p).toContain("Bearer pvt_xxx");
    expect(p).toContain('"type":"http"');
  });

  it("cursor deep link is well-formed and contains no 'type' field", () => {
    const link = cursorDeepLink("pvt_xxx");
    expect(link.startsWith("cursor://")).toBe(true);
    expect(link).toContain("pvt_xxx");
    // Must NOT embed a type:sse or type:http — Cursor schema doesn't use it.
    const payload = decodeURIComponent(link.split("config=")[1]);
    const cfg = JSON.parse(payload);
    expect("type" in cfg).toBe(false);
  });

  it("codex cli command uses bearer-token-env-var", () => {
    const cmd = codexCliCommand("pvt_xxx");
    expect(cmd).toMatch(/codex mcp add pivot/);
    expect(cmd).toContain("--bearer-token-env-var PIVOT_TOKEN");
    // Token goes into env var, not onto the command line.
    expect(cmd).toContain('export PIVOT_TOKEN="pvt_xxx"');
  });

  it("claude desktop info has url+token and hint tells users to use UI", () => {
    const info = claudeDesktopConnectionInfo("pvt_xxx");
    expect(info).toContain("Bearer pvt_xxx");
    expect(info).toContain("/mcp");
    expect(CLAUDE_DESKTOP_UI_HINT).toContain("Settings");
    expect(CLAUDE_DESKTOP_UI_HINT).toContain("Connectors");
  });
});
