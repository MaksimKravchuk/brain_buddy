// Shared frame for Thinking Mode's full-screen state cards (access checks,
// empty, load and recovery errors), so every state centres, sizes and spaces
// its card the same way. The card tone (border colour) is added per state.
export const stateScreenClass =
  "relative flex min-h-screen items-center justify-center bg-surface-base px-6 py-16 text-center";
export const stateExitClass = "absolute left-5 top-2.5";
export const stateCardClass = "w-full max-w-md rounded-[20px] border bg-white px-8 py-10 shadow-raised";
export const stateEyebrowClass = "text-[10px] font-semibold uppercase tracking-[0.06em] text-sky-700";
export const stateTitleClass = "mt-2 text-balance text-title font-semibold text-slate-900";
export const stateBodyClass = "mx-auto mt-2 max-w-sm text-sm text-slate-600";
