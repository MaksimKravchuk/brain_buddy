import { useRef, useState, useEffect, type FormEvent } from "react";
import { Button } from "../../components/ui/Button";
import { ApiError } from "../../api/client";
import { useAuthOperation } from "./authOperation";
import { modernAuthApi, type Challenge, type Completion } from "../../api/modernAuth";

export const authInputClass = "min-h-11 w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-base text-slate-900 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-sky-700";
export const authButtonClass = "min-h-11 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-sky-700";
export function AuthField({ label, value, onChange, type = "text", autoComplete, minLength }: { label: string; value: string; onChange: (value: string) => void; type?: string; autoComplete?: string; minLength?: number }): React.JSX.Element {
  return <label className="flex flex-col gap-1 text-sm font-medium text-slate-700">{label}<input className={authInputClass} required type={type} value={value} onChange={event => onChange(event.target.value)} autoComplete={autoComplete} minLength={minLength} maxLength={type === "password" ? 128 : 320} /></label>;
}
export function CodeStep({ challenge, verifier, email, onComplete, onCancel, recentProof }: { challenge: Challenge; verifier: string; email: string; onComplete: (completion: Completion) => Promise<void> | void; onCancel: () => void; recentProof?: string }): React.JSX.Element {
  const [current, setCurrent] = useState(challenge);
  const [code, setCode] = useState("");
  const [clock, setClock] = useState(() => Date.now());
  const [unknown, setUnknown] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const op = useAuthOperation();
  useEffect(() => { input.current?.focus(); const timer = setInterval(() => setClock(Date.now()), 1000); return () => clearInterval(timer); }, []);
  const remaining = Math.max(0, Math.ceil((Date.parse(current.expires_at) - clock) / 1000));
  const resendWait = Math.max(0, Math.ceil((Date.parse(current.resend_at) - clock) / 1000));
  const submit = (event: FormEvent) => {
    event.preventDefault();
    void op.run(async () => {
      if (unknown || !remaining || !/^[0-9]{6}$/.test(code)) throw new Error("Invalid code");
      try {
        const result = await modernAuthApi.verifyEmail({ challenge_id: current.challenge_id, code, client_verifier: verifier, ...(recentProof ? { recent_proof: recentProof } : {}) });
        setCode(""); await onComplete(result);
      } catch (caught) { if (!(caught instanceof ApiError)) setUnknown(true); throw caught; }
    }, "That code isn't valid or has expired. Check it or request another.");
  };
  return <div className="flex flex-col gap-4">
    <p>If this address can be used, you will receive a six-digit code at <strong>{email || "your provider email"}</strong>.</p>
    <form className="flex flex-col gap-4" onSubmit={submit} aria-busy={op.busy}>
      <label className="flex flex-col gap-1 font-medium text-slate-700">Email code<input ref={input} className={`${authInputClass} tracking-[.28em]`} value={code} onChange={event => setCode(event.target.value.replace(/[^0-9]/g, "").slice(0, 6))} autoComplete="one-time-code" inputMode="numeric" pattern="[0-9]{6}" maxLength={6} required aria-describedby="code-expiry" /></label>
      <p id="code-expiry" className="text-sm text-slate-600">Code expires in {Math.floor(remaining / 60)}:{String(remaining % 60).padStart(2, "0")}. Use the most recent code.</p>
      {op.error && !unknown ? <p role="alert" className="text-sm text-rose-700">{op.error}</p> : null}
      {unknown ? <p role="alert">We couldn't confirm whether this finished. Check your account or sign in again with a fresh proof. Your tasks are kept.</p> : null}
      <Button type="submit" variant="primary" className={authButtonClass} isLoading={op.busy} disabled={!remaining || unknown}>{op.busy ? "Checking…" : "Verify and continue"}</Button>
    </form>
    <Button className={authButtonClass} disabled={op.busy || resendWait > 0 || !remaining || unknown} onClick={() => void op.run(async () => { setCurrent(await modernAuthApi.resendEmail({ challenge_id: current.challenge_id, client_verifier: verifier })); setCode(""); input.current?.focus(); }, "If the code doesn't arrive, wait and try another method.")}>{resendWait ? `Send another code in ${resendWait}s` : "Send another code"}</Button>
    <p className="text-sm text-slate-600">If nothing arrives, use another connected method. Older password accounts must first verify their email from account settings.</p>
    <Button className={authButtonClass} disabled={op.busy} onClick={onCancel}>Use another email or method</Button>
  </div>;
}
