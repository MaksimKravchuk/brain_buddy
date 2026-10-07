import { useAuthOperation } from "./authOperation";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { ApiError } from "../../api/client";
import { modernAuthApi, type Methods, type Completion, type Challenge, type ClientProof } from "../../api/modernAuth";
import { Button } from "../../components/ui/Button";
import { useAuthStore } from "../../stores/authStore";
import { createClientProof, startBrowserProvider, acceptSignedIn, safeAuthDestination } from "./authFlow";
import { AuthField, CodeStep, authButtonClass } from "./AuthControls";

export function AuthEntry({ destination, initialCode, beforeSignIn }: { destination: string; initialCode?: { challenge: Challenge; verifier: string }; beforeSignIn?: () => Promise<void> }): React.JSX.Element {
  const navigate = useNavigate();
  const [methods, setMethods] = useState<Methods | null>(null);
  const [availabilityError, setAvailabilityError] = useState(false);
  const [mode, setMode] = useState<"choice" | "password" | "recover" | "reset" | "collision" | "code">(initialCode ? "code" : "choice");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [repeat, setRepeat] = useState("");
  const [notice, setNotice] = useState<string | null>(null);
  const [proof, setProof] = useState<ClientProof | null>(initialCode ? { verifier: initialCode.verifier, challenge: "" } : null);
  const [challenge, setChallenge] = useState<Challenge | null>(initialCode?.challenge ?? null);
  const [codePurpose, setCodePurpose] = useState<"login" | "recover">("login");
  const [reset, setReset] = useState<{ grant: string; expires: string } | null>(null);
  const op = useAuthOperation();
  const fields = useRef<HTMLDivElement>(null);
  useEffect(() => { fields.current?.querySelector("input")?.focus(); }, [mode, methods?.email]);
  const loadMethods = () => { setAvailabilityError(false); void modernAuthApi.methods().then(setMethods).catch(() => { setMethods(null); setAvailabilityError(true); }); };
  useEffect(() => { let active = true; void modernAuthApi.methods().then(result => { if (active) setMethods(result); }).catch(() => { if (active) setAvailabilityError(true); }); return () => { active = false; }; }, []);
  const back = () => { setMode("choice"); setPassword(""); setRepeat(""); setProof(null); setChallenge(null); setReset(null); op.setError(null); };
  const complete = async (result: Completion) => {
    if (result.status === "signed_in" && codePurpose === "login") { await acceptSignedIn(result); setProof(null); navigate(safeAuthDestination(destination), { replace: true }); }
    else if (result.status === "existing_account_required" && codePurpose === "login") { setMode("collision"); setProof(null); setChallenge(null); }
    else if (result.status === "reset_ready" && codePurpose === "recover") { setReset({ grant: result.reset_grant, expires: result.expires_at }); setMode("reset"); }
    else throw new Error("Unexpected authentication result");
  };
  const requestCode = (event: FormEvent) => { event.preventDefault(); void op.run(async () => {
    const client = await createClientProof();
    await beforeSignIn?.();
    const result = await modernAuthApi.requestEmail({ email, purpose: mode === "recover" ? "recover" : "login", client: "web", client_challenge: client.challenge });
    setCodePurpose(mode === "recover" ? "recover" : "login"); setProof(client); setChallenge(result); setMode("code");
  }, "If the code doesn't arrive, wait and use another method."); };
  const passwordLogin = (event: FormEvent) => { event.preventDefault(); void op.run(async () => {
    await beforeSignIn?.();
    try { await useAuthStore.getState().login({ email, password }); setPassword(""); navigate(safeAuthDestination(destination), { replace: true }); }
    catch (caught) { if (caught instanceof ApiError && caught.status === 429) throw caught; op.setError("Invalid email or password."); }
  }); };
  const savePassword = (event: FormEvent) => { event.preventDefault(); void op.run(async () => {
    if (password !== repeat) { op.setError("New passwords don't match."); return; }
    if (!reset || !proof || Date.parse(reset.expires) <= Date.now()) { setReset(null); setMode("recover"); throw new Error("Expired reset"); }
    const saved = reset; setReset(null);
    try { await modernAuthApi.resetPassword({ reset_grant: saved.grant, client_verifier: proof.verifier, new_password: password }); back(); setNotice("Password reset. Sign in with your new password."); }
    catch (caught) { setPassword(""); setRepeat(""); setMode("password"); setProof(null); throw caught; }
  }, "We couldn't confirm the reset. Sign in again to check; request fresh recovery if needed."); };
  if (mode === "code" && challenge && proof) return <CodeStep challenge={challenge} verifier={proof.verifier} email={email} onComplete={complete} onCancel={back} beforeSubmit={beforeSignIn} />;
  if (mode === "collision") return <div className="flex flex-col gap-4"><h2 className="text-subtitle font-semibold">Connect to your existing account</h2><p>Sign in to your existing account, then connect this method in Settings. Matching email addresses don't automatically connect accounts.</p><Button className={authButtonClass} onClick={() => { setMode("choice"); }}>Sign in to existing account</Button><Button className={authButtonClass} disabled={op.busy} onClick={back}>Cancel</Button></div>;
  return <div ref={fields} className="flex flex-col gap-4">
    {notice ? <p role="status" className="text-sm text-emerald-800">{notice}</p> : null}
    {op.error ? <p role="alert" className="text-sm text-rose-700">{op.error}</p> : null}
    {mode === "choice" ? <>
      {availabilityError ? <p role="alert">Couldn't load sign-in methods. Retry or use your password. <Button className={authButtonClass} onClick={loadMethods}>Retry</Button></p> : null}
      {!methods && !availabilityError ? <p className="text-sm text-slate-600">Loading sign-in methods…</p> : null}
      {(["google", "apple"] as const).filter(provider => methods?.[provider]).map(provider => <Button key={provider} className={authButtonClass} disabled={op.busy} onClick={() => void op.run(() => startBrowserProvider(provider, { purpose: "login" }, destination, beforeSignIn))}>{op.busy ? "Please wait…" : `Sign in with ${provider === "google" ? "Google" : "Apple"}`}</Button>)}
      {methods?.email ? <form className="flex flex-col gap-4" onSubmit={requestCode} aria-busy={op.busy}><AuthField label="Email address" type="email" value={email} onChange={setEmail} autoComplete="email" /><Button type="submit" variant="primary" className={authButtonClass} isLoading={op.busy}>{op.busy ? "Please wait…" : "Continue with email"}</Button></form> : null}
      <Button className={authButtonClass} disabled={op.busy} onClick={() => { setMode("password"); op.setError(null); }}>Use your password</Button>
    </> : mode === "password" ? <>
      <form className="flex flex-col gap-4" onSubmit={passwordLogin} aria-busy={op.busy}><AuthField label="Email address" type="email" value={email} onChange={setEmail} autoComplete="username" /><AuthField label="Password" type="password" value={password} onChange={setPassword} autoComplete="current-password" /><Button className={authButtonClass} type="submit" variant="primary" isLoading={op.busy}>Sign in</Button></form>
      <Button className={authButtonClass} disabled={op.busy} onClick={() => { setPassword(""); setMode("recover"); op.setError(null); }}>Forgot password?</Button>
      <Button className={authButtonClass} disabled={op.busy} onClick={back}>Use another method</Button>
    </> : mode === "recover" ? <>
      <h2 className="text-subtitle font-semibold">Reset your password</h2><p>We'll send a code if this email has a verified account that can reset its password.</p>
      <form className="flex flex-col gap-4" onSubmit={requestCode} aria-busy={op.busy}><AuthField label="Email address" type="email" value={email} onChange={setEmail} autoComplete="email" /><Button className={authButtonClass} type="submit" variant="primary" isLoading={op.busy}>{op.busy ? "Please wait…" : "Send a recovery code"}</Button></form><Button className={authButtonClass} disabled={op.busy} onClick={back}>Back to sign in</Button>
    </> : <form className="flex flex-col gap-4" onSubmit={savePassword} aria-busy={op.busy}><AuthField label="New password" type="password" value={password} onChange={setPassword} autoComplete="new-password" minLength={12} /><AuthField label="Repeat password" type="password" value={repeat} onChange={setRepeat} autoComplete="new-password" minLength={12} /><p className="text-sm">At least 12 characters. Your other sessions will end after the reset.</p><Button className={authButtonClass} type="submit" variant="primary" isLoading={op.busy}>Save password</Button><Button className={authButtonClass} disabled={op.busy} onClick={back}>Cancel</Button></form>}
  </div>;
}
