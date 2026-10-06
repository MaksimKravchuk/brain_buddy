import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { ProtectedRoute } from "../../components/auth/ProtectedRoute";
import { Button } from "../../components/ui/Button";
import { authButtonClass, authInputClass } from "../auth/AuthControls";
import { useAuthStore } from "../../stores/authStore";
import { ApiError } from "../../api/client";
import { cliAuthApi, type AuthorizationRequest } from "./api";
import { captureCode, clearCode, normalizeCode, rememberCode, retainedCode } from "./code";

function failureCopy(failure: unknown, message: string): string {
  return message + (failure instanceof ApiError && failure.correlationId ? ` Reference: ${failure.correlationId}` : "");
}

export function CliAuthorizeEntry(): React.JSX.Element {
  const location = useLocation(); const navigate = useNavigate();
  useLayoutEffect(() => {
    captureCode(location.hash || window.location.hash);
    if (location.hash) navigate("/cli/authorize", { replace: true });
  }, [location.hash, navigate]);
  return <ProtectedRoute><CliAuthorizePage /></ProtectedRoute>;
}

export function CliAuthorizePage(): React.JSX.Element {
  const user = useAuthStore(state => state.user);
  const available = user?.feature_flags?.cli_auth === true;
  const [code, setCode] = useState(() => retainedCode()?.userCode ?? "");
  const [request, setRequest] = useState<AuthorizationRequest | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [terminal, setTerminal] = useState("");
  const controller = useRef<AbortController | null>(null);
  const result = useRef<HTMLDivElement | null>(null);
  const input = useRef<HTMLInputElement | null>(null);
  const approval = useRef<HTMLHeadingElement | null>(null);
  const expiry = useRef<number>(retainedCode()?.expiresAt ?? 0);

  const check = useCallback(async (input: string): Promise<void> => {
    const normalized = normalizeCode(input);
    if (!normalized) { setError("Enter the eight-character code shown by your CLI."); return; }
    controller.current?.abort(); const active = new AbortController(); controller.current = active;
    setBusy(true); setError(""); setTerminal(""); setRequest(null);
    try {
      const found = await cliAuthApi.request(normalized, active.signal);
      if (active.signal.aborted) return;
      const saved = retainedCode();
      const deadline = Math.min(Date.parse(found.expires_at), saved?.userCode === normalized ? saved.expiresAt : Date.now() + 600000);
      if (!Number.isFinite(deadline) || deadline <= Date.now() || found.user_code !== normalized || found.client_name !== "BrainBuddy CLI") throw new Error("Invalid authorization request.");
      setCode(normalized); expiry.current = deadline; rememberCode(normalized, deadline);
      if (found.state !== "pending") {
        clearCode(); setTerminal(found.state === "approved" || found.state === "consumed" ? "This request was already approved. Return to your CLI." : "Access denied. Start a new login in your CLI.");
      } else setRequest(found);
    } catch (failure) {
      if (!active.signal.aborted) {
        setError(failureCopy(failure, failure instanceof ApiError && failure.status === 404 ? "This code is unavailable or expired. Check your CLI and try again." : "We could not check this code. Check your connection and try again."));
        if (failure instanceof ApiError && failure.status === 404) clearCode();
      }
    } finally { if (!active.signal.aborted) setBusy(false); }
  }, []);
  async function decide(decision: "approve" | "deny"): Promise<void> {
    if (!request || expiry.current <= Date.now()) { expire(); return; }
    controller.current?.abort(); const active = new AbortController(); controller.current = active;
    setBusy(true); setError("");
    try {
      const answer = await cliAuthApi.decision(code, decision, active.signal);
      if (active.signal.aborted) return;
      if (answer.state !== "approved" && answer.state !== "denied") throw new Error("Invalid decision response.");
      clearCode(); setRequest(null);
      setTerminal(answer.state === "approved" ? "Access approved. Return to your CLI to finish signing in." : "Access denied. Start a new login in your CLI.");
    } catch (failure) {
      if (!active.signal.aborted) setError(failureCopy(failure, "We could not confirm your decision. Check this code again before retrying."));
    } finally { if (!active.signal.aborted) setBusy(false); }
  }
  function expire(): void {
    controller.current?.abort(); clearCode(); setRequest(null); setBusy(false);
    setTerminal("This code has expired. Start a new login in your CLI.");
  }
  function cancel(): void {
    controller.current?.abort(); setBusy(false); setRequest(null); setError("");
    if (request && busy) {
      setTerminal("");
      setError("We could not confirm your decision. Check this code again before retrying.");
    } else {
      clearCode(); setTerminal("Authorization cancelled. Start a new login in your CLI.");
    }
  }
  useEffect(() => {
    if (!available) { clearCode(); return; }
    const saved = retainedCode();
    const timer = saved ? setTimeout(() => void check(saved.userCode), 0) : null;
    return () => { if (timer !== null) clearTimeout(timer); controller.current?.abort(); };
  }, [user?.id, available, check]);
  useEffect(() => {
    if (!request) return;
    const timer = setTimeout(expire, Math.max(0, expiry.current - Date.now()));
    return () => clearTimeout(timer);
  }, [request]);
  useEffect(() => {
    if (error || terminal || !available) result.current?.focus();
    else if (request) approval.current?.focus();
    else if (!busy) input.current?.focus();
  }, [error, terminal, available, request, busy]);

  return <main className="flex min-h-screen items-center justify-center bg-surface-base p-4">
    <section className="w-full max-w-lg rounded-xl bg-white p-6 shadow-sm" aria-labelledby="cli-title">
      <h1 id="cli-title" className="text-xl font-semibold">Authorize BrainBuddy CLI</h1>
      {!available ? <div ref={result} tabIndex={-1} role="alert" className="mt-4">CLI sign in is not available for this account.</div> : <>
        <p className="mt-3">Signed in as <strong>{user?.email}</strong></p>
        <p className="mt-3">Approve only a code shown by your own CLI. Anyone with the resulting session can access your BrainBuddy account.</p>
        {!terminal && !request && <form className="mt-4" onSubmit={event => { event.preventDefault(); void check(code); }}>
          <label htmlFor="cli-code">Code from your CLI</label>
          <input ref={input} id="cli-code" className={"mt-1 " + authInputClass} value={code} onChange={event => setCode(event.target.value)} maxLength={9} autoComplete="off" autoCapitalize="characters" disabled={busy} />
          <Button type="submit" className={"mt-3 " + authButtonClass} disabled={busy}>Check code</Button>
        </form>}
        {request && <div className="mt-4">
          <h2 ref={approval} tabIndex={-1} className="font-semibold">Confirm this CLI request</h2>
          <p>Code: <strong className="font-mono">{request.user_code}</strong></p>
          <p className="mt-2">Expires at {new Date(expiry.current).toLocaleTimeString()}</p>
          <div className="mt-4 flex flex-wrap gap-3">
            <Button className={authButtonClass} disabled={busy || Boolean(error)} onClick={() => void decide("approve")}>Approve access</Button>
            <Button variant="secondary" className={authButtonClass} disabled={busy || Boolean(error)} onClick={() => void decide("deny")}>Deny access</Button>
          </div>
        </div>}
        {busy && <p className="mt-3" aria-live="polite">{request ? "Sending your decision…" : "Checking this code…"}</p>}
        {(error || terminal) && <div ref={result} tabIndex={-1} role={error ? "alert" : "status"} className="mt-4 rounded border border-slate-300 p-3">{error || terminal}</div>}
        {error && <Button variant="secondary" className={"mt-3 " + authButtonClass} disabled={busy} onClick={() => void check(code)}>Check code again</Button>}
        {!terminal && <Button variant="secondary" className={"mt-4 flex " + authButtonClass} onClick={cancel}>Cancel</Button>}
      </>}
      <Link className="mt-4 inline-block underline" to="/">Back to BrainBuddy</Link>
    </section>
  </main>;
}
