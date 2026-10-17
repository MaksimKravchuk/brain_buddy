import { useEffect, useRef, useState, type FormEvent } from "react";
import { ApiError } from "../../api/client";
import { signupComplete } from "../../api/invite";
import type { Completion } from "../../api/modernAuth";
import { Button } from "../../components/ui/Button";
import { authInputClass } from "./AuthControls";
import { Spinner } from "../../components/ui/Spinner";

export const INVITE_INVALID = "That invite code isn't valid or has already been used. Check it and try again.";
export const INVITE_EXPIRED = "This sign-in has expired. Start again to create your account.";
export const INVITE_RATE_LIMITED = "Too many requests. Try again in a few minutes.";
const UPDATE_REQUIRED = "Carry On has been updated. Reload this page to continue. Nothing in your account was changed.";
const SPINNER_DELAY_MS = 300;
const withReference = (text: string, id?: string) => id ? `${text} Reference: ${id}` : text;

interface Props { pending: string; onSignedIn: (result: Completion) => Promise<void> | void; onRestart: () => void; onCancel: () => void }
type Failure = { invalid: boolean; text: string } | null;

function describe(caught: unknown): { expired: boolean; failure: Failure; blockMs?: number } {
  if (!(caught instanceof ApiError)) return { expired: false, failure: { invalid: false, text: "Couldn't reach Carry On. Check your connection and try again." } };
  if (caught.status === 410) return { expired: true, failure: null };
  if (caught.status === 400) return { expired: false, failure: { invalid: true, text: withReference(INVITE_INVALID, caught.correlationId) } };
  if (caught.status === 429) return { expired: false, failure: { invalid: false, text: INVITE_RATE_LIMITED }, blockMs: caught.retryAfterMs ?? Infinity };
  const message = (caught.payload as { message?: unknown } | null)?.message;
  const text = caught.status === 426 ? (typeof message === "string" ? message : UPDATE_REQUIRED) : "Couldn't create your account. Try again.";
  return { expired: false, failure: { invalid: false, text: withReference(text, caught.correlationId) } };
}

/** Design D-04: the invite step for a new identity (states .01-.08). */
export function InviteStep({ pending, onSignedIn, onRestart, onCancel }: Props): React.JSX.Element {
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [showSpinner, setShowSpinner] = useState(false);
  const [failure, setFailure] = useState<Failure>(null);
  const [expired, setExpired] = useState(false);
  const [blocked, setBlocked] = useState(false);
  const field = useRef<HTMLInputElement>(null);
  const restart = useRef<HTMLButtonElement>(null);
  const locked = useRef(false);
  const unblock = useRef<number | undefined>(undefined);
  useEffect(() => () => window.clearTimeout(unblock.current), []);
  // .01 focus lands on the field; .03/.05/.07 return it; .04 moves to the one action left.
  useEffect(() => { if (expired) restart.current?.focus(); else if (!busy) field.current?.focus(); }, [expired, busy, failure]);
  useEffect(() => {
    if (!busy) return;
    const id = window.setTimeout(() => setShowSpinner(true), SPINNER_DELAY_MS);
    return () => window.clearTimeout(id);
  }, [busy]);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const invite = code.trim();
    if (locked.current || blocked || !invite) return;
    locked.current = true; setBusy(true); setFailure(null);
    try {
      await onSignedIn(await signupComplete({ pending, invite_code: invite }));
    } catch (caught) {
      const outcome = describe(caught);
      setExpired(outcome.expired); setFailure(outcome.failure);
      if (outcome.blockMs !== undefined) {
        setBlocked(true);
        if (Number.isFinite(outcome.blockMs)) unblock.current = window.setTimeout(() => setBlocked(false), outcome.blockMs);
      }
    } finally { locked.current = false; setBusy(false); setShowSpinner(false); }
  };

  if (expired) return <div><p role="alert">{INVITE_EXPIRED}</p><Button ref={restart} variant="primary" className="mt-4 min-h-11 w-full" onClick={onRestart}>Back to sign in</Button></div>;
  return <form className="flex flex-col gap-3" onSubmit={submit} aria-labelledby="invite-step-title">
    <h2 id="invite-step-title" className="font-voice text-2xl text-ink">Enter your invite code</h2>
    <p id="invite-step-help" className="text-co-meta text-ink-muted">Carry On is invite-only. No account uses this sign-in yet. Enter your invite code to create one.</p>
    <label className="flex flex-col gap-1 text-co-meta">
      <span className="font-medium text-ink">Invite code</span>
      <input ref={field} type="text" value={code} readOnly={busy} autoComplete="off" autoCapitalize="off" spellCheck={false}
        aria-invalid={failure?.invalid ? true : undefined} aria-describedby={failure ? "invite-step-help invite-step-error" : "invite-step-help"}
        onChange={event => setCode(event.target.value)}
        className={`${authInputClass} font-mono`} />
    </label>
    {failure ? <p id="invite-step-error" role="alert" className="text-co-meta text-danger">{failure.text}</p> : null}
    <div className="flex flex-col gap-2 sm:flex-row">
      <Button type="submit" variant="primary" className="min-h-11 flex-1" disabled={busy || blocked}>{busy ? <>{showSpinner ? <Spinner size="sm" className="mr-2 border-current/30 border-t-current" /> : null}Please wait…</> : "Continue"}</Button>
      <Button variant="ghost" className="min-h-11 flex-1" disabled={busy} onClick={onCancel}>Cancel</Button>
    </div>
  </form>;
}
