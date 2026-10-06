import { ApiError, getApiBaseUrl } from "../../api/client";

export interface AuthorizationRequest {
  user_code: string; client_name: string; created_at: string; expires_at: string;
  state: "pending" | "approved" | "denied" | "consumed";
}
async function post<T>(path: string, body: object, signal: AbortSignal): Promise<T> {
  const controller = new AbortController();
  const abort = () => controller.abort();
  if (signal.aborted) abort();
  signal.addEventListener("abort", abort, { once: true });
  const timer = setTimeout(abort, 30000);
  try {
    const response = await fetch(getApiBaseUrl() + "/auth/device/" + path, {
      method: "POST", headers: { "Content-Type": "application/json" },
      credentials: "include", redirect: "error", cache: "no-store",
      signal: controller.signal, body: JSON.stringify(body)
    });
    if (!response.ok) {
      const reference = response.headers.get("X-Correlation-ID");
      const safeReference = reference && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(reference) ? reference : undefined;
      throw new ApiError("CLI authorization could not complete.", response.status, null, safeReference);
    }
    return await response.json() as T;
  } finally { clearTimeout(timer); signal.removeEventListener("abort", abort); }
}
export const cliAuthApi = {
  request: (userCode: string, signal: AbortSignal) => post<AuthorizationRequest>("request", { user_code: userCode }, signal),
  decision: (userCode: string, decision: "approve" | "deny", signal: AbortSignal) => post<{ state: "approved" | "denied" }>("decision", { user_code: userCode, decision }, signal)
};
