const KEY = "brainbuddy.cli.authorization";
const CODE = /^[A-HJ-NP-Z2-9]{4}-[A-HJ-NP-Z2-9]{4}$/;
export interface RetainedCode { userCode: string; expiresAt: number }

export function clearCode(): void {
  try { sessionStorage.removeItem(KEY); } catch { /* Blocked tab storage uses manual entry. */ }
}
export function retainedCode(): RetainedCode | null {
  try {
    const value: unknown = JSON.parse(sessionStorage.getItem(KEY) ?? "null");
    if (value && typeof value === "object" && "userCode" in value && "expiresAt" in value &&
      typeof value.userCode === "string" && CODE.test(value.userCode) &&
      typeof value.expiresAt === "number" && Number.isFinite(value.expiresAt) &&
      value.expiresAt > Date.now() && value.expiresAt <= Date.now() + 600000) {
      return { userCode: value.userCode, expiresAt: value.expiresAt };
    }
  } catch { /* Invalid or unavailable tab storage uses manual entry. */ }
  clearCode(); return null;
}
export function rememberCode(userCode: string, expiresAt = Date.now() + 600000): RetainedCode | null {
  if (!CODE.test(userCode) || !Number.isFinite(expiresAt) || expiresAt <= Date.now()) { clearCode(); return null; }
  const previous = retainedCode();
  const value = { userCode, expiresAt: Math.min(expiresAt, Date.now() + 600000, previous?.userCode === userCode ? previous.expiresAt : Infinity) };
  try { sessionStorage.setItem(KEY, JSON.stringify(value)); return value; } catch { return null; }
}
export function normalizeCode(input: string): string | null {
  const raw = input.trim().toUpperCase().replace(/-/g, "");
  const formatted = raw.slice(0, 4) + "-" + raw.slice(4);
  return CODE.test(formatted) ? formatted : null;
}
export function captureCode(fragment: string): RetainedCode | null {
  if (window.location.pathname === "/cli/authorize" && window.location.hash) {
    window.history.replaceState(window.history.state, "", "/cli/authorize");
  }
  if (!fragment) return retainedCode();
  const params = new URLSearchParams(fragment.replace(/^#/, ""));
  const entries = [...params.entries()];
  if (entries.length !== 1 || entries[0][0] !== "user_code" || !CODE.test(entries[0][1])) { clearCode(); return null; }
  return rememberCode(entries[0][1]);
}
