// Shared frame for Thinking Mode's full-screen state cards (access checks,
// empty, load and recovery errors), so every state centres, sizes and spaces
// its card the same way. The card tone (border colour) is added per state.
export const stateScreenClass =
  "relative flex min-h-screen items-center justify-center bg-ground px-6 py-16 text-center";
export const stateExitClass = "absolute left-5 top-2.5";
export const stateCardClass = "w-full max-w-md rounded-card bg-card px-8 py-10";
export const stateEyebrowClass = "text-co-meta font-semibold text-ink-muted";
export const stateTitleClass = "mt-2 text-balance font-voice text-co-title font-semibold text-ink-muted";
export const stateBodyClass = "mx-auto mt-2 max-w-sm text-co-meta text-ink-muted";
