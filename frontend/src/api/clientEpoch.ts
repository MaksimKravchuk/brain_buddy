// Release epoch (027-FR-018): a constant bumped only when the server raises its
// minimum. `X-Client` is logging-only and never used for admission.
export const CLIENT_EPOCH = 1;

const BUILD = (import.meta.env.VITE_APP_BUILD as string | undefined) || "dev";

export const CLIENT_HEADER_VALUE = `brainbuddy-web/${BUILD}`;

export function clientEpochHeaders(): Record<string, string> {
  return { "X-Client-Epoch": String(CLIENT_EPOCH), "X-Client": CLIENT_HEADER_VALUE };
}
