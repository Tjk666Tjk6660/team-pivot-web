export const COPY_FOR_AI_GUIDE_KEY_PREFIX = "pivot.copyForAI.mcpGuide.v1";

export function copyForAIGuideStorageKey(openId: string | null | undefined) {
  return `${COPY_FOR_AI_GUIDE_KEY_PREFIX}:${openId || "anonymous"}`;
}

export function shouldShowCopyForAIGuide(storedValue: string | null): boolean {
  return storedValue !== "1";
}
