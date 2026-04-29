/**
 * Body-source state machine: tracks whether the current draft body came from
 * AI collaboration or manual input. Drives the publish-time quality gate.
 *
 * Single-direction rule:
 *   - The ONLY way to enter "ai" is via applyAIDraft() — i.e. the AI <draft>
 *     protocol explicitly wrote the body. Pasting AI-like external text never
 *     upgrades a manual body to "ai".
 *   - From "ai", user edits can downgrade to "manual" when the LCS similarity
 *     against the AI snapshot drops below SIM_THRESHOLD, or when the body
 *     shrinks below SHRINK_THRESHOLD of the snapshot length.
 *   - "manual" is sticky: any user edit (typing, pasting) keeps it "manual".
 *
 * LCS similarity is only computed when the current state is "ai" (cheap path
 * for the common manual case). The expensive O(n*m) compare runs at most once
 * per onUserEdit invocation, and again at computeAtPublish as a final guard.
 */

export type BodySource = "ai" | "manual";

export type BodySourceState = {
  body_source: BodySource;
  body_source_snapshot?: string;
};

export const SIM_THRESHOLD = 0.5;
export const SHRINK_THRESHOLD = 0.3;

const EMPTY_MANUAL: BodySourceState = { body_source: "manual" };

export function applyAIDraft(aiBody: string): BodySourceState {
  return { body_source: "ai", body_source_snapshot: aiBody };
}

export function onUserEdit(
  state: BodySourceState,
  newBody: string,
): BodySourceState {
  if (state.body_source !== "ai") return state;
  const snap = state.body_source_snapshot ?? "";
  if (newBody.length === 0) return EMPTY_MANUAL;
  if (snap.length > 0 && newBody.length < snap.length * SHRINK_THRESHOLD) {
    return EMPTY_MANUAL;
  }
  if (similarity(newBody, snap) < SIM_THRESHOLD) return EMPTY_MANUAL;
  return state;
}

export function computeAtPublish(
  state: BodySourceState,
  currentBody: string,
): BodySource {
  if (state.body_source !== "ai") return "manual";
  const snap = state.body_source_snapshot ?? "";
  if (currentBody.length === 0) return "manual";
  if (snap.length > 0 && currentBody.length < snap.length * SHRINK_THRESHOLD) {
    return "manual";
  }
  return similarity(currentBody, snap) >= SIM_THRESHOLD ? "ai" : "manual";
}

export function similarity(a: string, b: string): number {
  if (a.length === 0 || b.length === 0) return 0;
  if (a === b) return 1;
  const lcs = lcsLength(a, b);
  return lcs / Math.max(a.length, b.length);
}

function lcsLength(a: string, b: string): number {
  const m = a.length;
  const n = b.length;
  // Rolling 1D DP: O(min(m,n)) memory.
  let prev = new Uint32Array(n + 1);
  let curr = new Uint32Array(n + 1);
  for (let i = 1; i <= m; i++) {
    const ai = a.charCodeAt(i - 1);
    for (let j = 1; j <= n; j++) {
      curr[j] =
        ai === b.charCodeAt(j - 1)
          ? prev[j - 1] + 1
          : Math.max(prev[j], curr[j - 1]);
    }
    [prev, curr] = [curr, prev];
    curr.fill(0);
  }
  return prev[n];
}
