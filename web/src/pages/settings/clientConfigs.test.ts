import { describe, it, expect } from "vitest";
import {
  claudeCodePrompt,
  cursorDeepLink,
  codexCliCommand,
  claudeDesktopJsonSnippet,
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

  it("codex prompt instructs the AI to register the MCP via env-var bearer token", () => {
    const prompt = codexCliCommand("pvt_xxx");
    // Prompt must carry the actual codex CLI invocation for the AI to run.
    expect(prompt).toMatch(/codex mcp add pivot/);
    expect(prompt).toContain("--bearer-token-env-var PIVOT_TOKEN");
    // Token reaches the AI so it can plug it into the env-var step.
    expect(prompt).toContain('export PIVOT_TOKEN="pvt_xxx"');
  });

  it("codex prompt orchestrates the persistence step interactively", () => {
    const prompt = codexCliCommand("pvt_xxx");
    // AI must ASK before persisting (don't silently mutate the user's profile).
    expect(prompt).toMatch(/要不要让 PIVOT_TOKEN 永久生效/);
    // All three shell options must be available for the AI to pick from after detection.
    expect(prompt).toContain("~/.bashrc");
    expect(prompt).toContain("~/.zshrc");
    expect(prompt).toContain("SetEnvironmentVariable");
    // Plain-text storage warning must be present so the AI surfaces it.
    expect(prompt).toContain("明文");
  });

  it("claude desktop snippet embeds mcp-remote bridge, token, and url; hint points to config file", () => {
    const snippet = claudeDesktopJsonSnippet("pvt_xxx");
    // Must be valid JSON the user can paste straight into claude_desktop_config.json.
    const parsed = JSON.parse(snippet);
    expect(parsed.mcpServers.pivot.command).toBe("npx");
    expect(parsed.mcpServers.pivot.args).toContain("mcp-remote");
    expect(parsed.mcpServers.pivot.args).toContain(
      "Authorization: Bearer pvt_xxx",
    );
    expect(parsed.mcpServers.pivot.args.some((a: string) => a.includes("/mcp")))
      .toBe(true);
    // Hint must steer users to the config file path, NOT the OAuth Connectors UI.
    expect(CLAUDE_DESKTOP_UI_HINT).toContain("claude_desktop_config.json");
    expect(CLAUDE_DESKTOP_UI_HINT).not.toContain("Connectors");
  });
});
