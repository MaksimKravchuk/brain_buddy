import { authError, useAuthOperation } from "./authOperation";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { modernAuthApi, type AuthAction, type AccountMethods, type Methods, type RecentProof, type Challenge, type ClientProof } from "../../api/modernAuth";
import { ApiError } from "../../api/client";
import { Button } from "../../components/ui/Button";
import { SectionCard } from "../../components/ui/SettingsSection";
import { Overlay, OverlayHeader } from "../../components/ui/Overlay";
import { useAuthStore } from "../../stores/authStore";
import { AuthField, CodeStep, authButtonClass } from "./AuthControls";
import { ConfirmAccount } from "./ConfirmAccount";
import { assertActingOwner, createClientProof, startBrowserProvider, takeConfirmation } from "./authFlow";

export function AccountSecurity({ directDelete = false, onUpdated }: { directDelete?: boolean; onUpdated?: () => void }): React.JSX.Element {
  const [owner] = useState(useAuthStore.getState().user?.id ?? "");
  const currentOwner = useAuthStore(state => state.user?.id);
  const [methods, setMethods] = useState<AccountMethods | null>(null);
  const [availability, setAvailability] = useState<Methods | null>(null);
  const [loadError, setLoadError] = useState(false);
  const [action, setAction] = useState<AuthAction | null>(directDelete ? "delete" : null);
  const [notice, setNotice] = useState<string | null>(null);
  const opener = useRef<HTMLElement | null>(null);
  const choose = (next: AuthAction) => { opener.current = document.activeElement instanceof HTMLElement ? document.activeElement : null; setAction(next); };
  const close = () => { setAction(null); opener.current?.focus(); };
  const load = async () => {
    setLoadError(false);
    try { assertActingOwner(owner); const next = await modernAuthApi.accountMethods(); assertActingOwner(owner); if (next.account_id !== owner) throw new Error("Wrong account"); setMethods(next); }
    catch { setMethods(null); setLoadError(true); }
  };
  useEffect(() => { let active = true; void modernAuthApi.accountMethods().then(next => { if (active && next.account_id === owner && useAuthStore.getState().user?.id === owner) setMethods(next); else if (active) setLoadError(true); }).catch(() => { if (active) setLoadError(true); }); void modernAuthApi.methods().then(next => { if (active) setAvailability(next); }).catch(() => { /* existing connected metadata remains authoritative */ }); return () => { active = false; }; }, [owner]);
  const changed = async (message: string) => { close(); setNotice(message); await load(); onUpdated?.(); };
  if (!owner || currentOwner !== owner) return <p role="alert">Use the account linked to this action. Sign in again before continuing.</p>;
  return <>
    <SectionCard title="Account security" description="Choose how you sign in. Your current email stays in use until both ownership and the new address are confirmed.">
      {notice ? <p role="status" className="mb-4 text-sm text-emerald-800">{notice}</p> : null}
      {loadError ? <p role="alert">Couldn't load all your sign-in methods. Retry before changing them. <Button className={authButtonClass} onClick={() => void load()}>Retry</Button></p> : !methods ? <p role="status">Loading sign-in methods…</p> : <div className="flex flex-col gap-4">
        <p>You currently sign in as {methods.email}. <strong>{methods.email_verified ? "Verified" : "Unverified"}</strong></p>
        <div className="flex flex-wrap gap-2"><Button className={authButtonClass} onClick={() => choose("change_email")}>Change email</Button>{!methods.email_verified ? <Button className={authButtonClass} disabled={!availability?.email} onClick={() => choose("verify_email")}>Verify email</Button> : null}</div>
        <h3 className="font-semibold">Ways to sign in</h3>
        {(["google", "apple"] as const).map(provider => { const connected = methods.methods.find(method => method.method === provider); const label = provider === "google" ? "Google" : "Apple"; const active = connected?.state === "active"; return <div key={provider} className="flex items-center justify-between gap-3 border-b border-slate-200 py-3"><div><p className="font-medium">{label}</p><p className="text-sm text-slate-600">{connected ? connected.usable ? "Connected to your account" : "Connected · unavailable" : "Not connected"}</p></div><Button className={authButtonClass} disabled={!active && !availability?.[provider]} onClick={() => choose(`${active ? "unlink" : "link"}:${provider}`)}>{active ? "Remove" : connected ? "Reconnect" : "Connect"} {label}</Button></div>; })}
        <div className="flex items-center justify-between gap-3"><div><p className="font-medium">Password</p><p className="text-sm text-slate-600">{methods.has_password ? "Set" : "Not set"} · also used for Mac sign-in</p></div><Button className={authButtonClass} onClick={() => choose("password")}>{methods.has_password ? "Change password" : "Add password"}</Button></div>
        <p className="text-sm text-slate-600">Email codes: {methods.email_verified && methods.email_delivery === "available" ? "Ready" : "Verify your email or use another connected method"}</p>
      </div>}
    </SectionCard>
    <SectionCard title="Your data" description="Export a safe copy of your account data, or request deletion after the existing 14-day grace period."><div className="flex flex-wrap gap-3"><Button className={authButtonClass} disabled={!methods} onClick={() => choose("export")}>Export</Button><Button variant="danger" className={authButtonClass} disabled={!methods} onClick={() => choose("delete")}>Delete account…</Button></div></SectionCard>
    {methods && action ? <AccountActionDialog key={action} action={action} owner={owner} methods={methods} availability={availability} onClose={close} onChanged={changed} onRefresh={async () => { close(); await load(); onUpdated?.(); }} /> : null}
  </>;
}

function AccountActionDialog({ action, owner, methods, availability, onClose, onChanged, onRefresh }: { action: AuthAction; owner: string; methods: AccountMethods; availability: Methods | null; onClose: () => void; onChanged: (message: string) => Promise<void>; onRefresh: () => Promise<void> }): React.JSX.Element {
  const navigate = useNavigate();
  const [confirming, setConfirming] = useState(action === "export" || action === "verify_email" || action.startsWith("link:"));
  const [nextEmail, setNextEmail] = useState("");
  const [password, setPassword] = useState("");
  const [repeat, setRepeat] = useState("");
  const [unknown, setUnknown] = useState(false);
  const [code, setCode] = useState<{ challenge: Challenge; client: ClientProof; proof: RecentProof } | null>(null);
  const [renewing, setRenewing] = useState(false);
  const keepAccount = useRef<HTMLButtonElement>(null);
  const fields = useRef<HTMLDivElement>(null);
  const op = useAuthOperation();
  useEffect(() => { if (action === "delete" && !confirming) keepAccount.current?.focus(); else fields.current?.querySelector("input")?.focus(); }, [action, confirming]);
  const label = action.endsWith(":google") ? "Google" : "Apple";
  const perform = async (proof: RecentProof) => {
    assertActingOwner(owner);
    if (Date.parse(proof.expires_at) <= Date.now()) throw new Error("Confirmation expired");
    if (renewing && code) { setCode({ ...code, proof }); setRenewing(false); setConfirming(false); return; }
    const body = { recent_proof: proof.recent_proof, expected_account_id: owner };
    setConfirming(false);
    try {
      if (action === "change_email" || action === "verify_email") {
        const client = await createClientProof();
        const challenge = await modernAuthApi.requestEmail({ email: action === "change_email" ? nextEmail : methods.email, purpose: action, action, client: "web", client_challenge: client.challenge, ...body });
        assertActingOwner(owner); setCode({ challenge, client, proof });
      } else if (action === "password") {
        await modernAuthApi.setPassword({ ...body, new_password: password }); assertActingOwner(owner); setPassword(""); setRepeat(""); await onChanged("Password saved. Other devices have been signed out.");
      } else if (action.startsWith("link:")) {
        await startBrowserProvider(action === "link:google" ? "google" : "apple", { purpose: "link", action, ...body }, `/settings/account?expected_owner=${encodeURIComponent(owner)}`);
      } else if (action.startsWith("unlink:")) {
        const result = await modernAuthApi.unlink(action === "unlink:google" ? "google" : "apple", body);
        assertActingOwner(owner);
        if (result.methods.account_id !== owner) throw new Error("Wrong account");
        if (result.signed_out) {
          const remaining = result.methods.methods.filter(method => method.usable).map(method => ({ password: "your password", email: "an email code", google: "Google", apple: "Apple" })[method.method]).join(" or ");
          useAuthStore.getState().clearSession(); navigate("/login", { replace: true, state: { authNotice: `${label} was removed. Sign in again with ${remaining || "a remaining method"}.${label === "Apple" ? " Apple cleanup may still be pending or unconfirmed." : ""}` } });
        } else await onChanged(`${label} was removed. ${label === "Apple" ? "BrainBuddy access ended; Apple cleanup may still be pending or unconfirmed." : "Affected sessions have ended."}`);
      } else if (action === "export") { await modernAuthApi.exportAccount(body); assertActingOwner(owner); await onChanged("Download started. Auth secrets are excluded."); }
      else if (action === "delete") {
        const scheduled = await modernAuthApi.deleteAccount(body); assertActingOwner(owner);
        useAuthStore.getState().scheduleDeletionNotice(scheduled.purge_at);
        const cleaned = await useAuthStore.getState().clearSessionAfterCleanup();
        if (!cleaned) useAuthStore.getState().clearSession();
        navigate("/login", { replace: true, state: { deletionScheduled: scheduled.purge_at, authNotice: cleaned ? undefined : "Account deletion was requested. We couldn't clear this browser's local data; sign-in will check cleanup again." } });
      }
    } catch (caught) {
      if (action.startsWith("link:") && !(caught instanceof ApiError)) { op.setError("Couldn't start linking. Reconnect and try again with fresh confirmation. Your current methods stay connected."); return; }
      if (!(caught instanceof ApiError)) { setUnknown(true); setPassword(""); setRepeat(""); }
      op.setError(authError(caught));
    }
  };
  const beginConfirmation = (event?: FormEvent) => {
    event?.preventDefault();
    if (action === "password" && password !== repeat) { op.setError("New passwords don't match."); return; }
    const saved = takeConfirmation(owner, action);
    if (saved) void op.run(() => perform(saved)); else setConfirming(true);
  };
  useEffect(() => {
    if (action === "export" || action === "verify_email" || action.startsWith("link:")) {
      const saved = takeConfirmation(owner, action);
      if (saved) void op.run(() => perform(saved));
    }
    // The saved grant belongs to the action chosen at this dialog's opening.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return <Overlay labelledBy="account-action-title" onClose={op.busy ? undefined : onClose} size="narrow"><div className="[&_button]:min-h-11 [&_button]:min-w-11"><OverlayHeader titleId="account-action-title" title={action === "delete" ? "Delete your account?" : action.startsWith("unlink:") ? `Remove ${label}?` : action === "password" ? methods.has_password ? "Change password" : "Add password" : action === "change_email" ? "Change your email" : "Confirm account action"} onClose={op.busy ? undefined : onClose} /></div><div ref={fields} className="flex flex-col gap-4 px-5 py-5 sm:px-6" aria-busy={op.busy}>
    {unknown ? <><p role="alert">We couldn't confirm whether this finished. Reconnect and check your account before trying again. Use fresh proof if the action is still needed.</p><Button className={authButtonClass} onClick={() => void onRefresh()}>Check account</Button></> : confirming ? <ConfirmAccount owner={owner} action={action} methods={methods} availability={availability} onConfirm={async proof => { await op.run(() => perform(proof)); }} onCancel={onClose} /> : code && !renewing ? <><CodeStep challenge={code.challenge} verifier={code.client.verifier} email={action === "change_email" ? nextEmail : methods.email} recentProof={code.proof.recent_proof} onCancel={onClose} onComplete={async result => { assertActingOwner(owner); if (!(result.status === "changed_email" || result.status === "verified_email") || result.user.id !== owner) throw new Error("Wrong account result"); const current = useAuthStore.getState().user; if (current?.id === owner) useAuthStore.setState({ user: { ...current, email: result.user.email } }); await onChanged(result.status === "changed_email" ? `Email changed to ${result.user.email}.` : "Email verified. Email codes and password recovery are enabled."); }} /><Button className={authButtonClass} onClick={() => { setRenewing(true); setConfirming(true); }}>Confirm again for this email change</Button></> : <>
      {op.error ? <p role="alert" className="text-sm text-rose-700">{op.error}</p> : null}
      {action === "password" || action === "change_email" ? <form className="flex flex-col gap-4" onSubmit={beginConfirmation}>{action === "password" ? <><AuthField label="New password" type="password" value={password} onChange={setPassword} autoComplete="new-password" minLength={12} /><AuthField label="Repeat password" type="password" value={repeat} onChange={setRepeat} autoComplete="new-password" minLength={12} /><p>At least 12 characters. Longer is better.</p></> : <><AuthField label="New email" type="email" value={nextEmail} onChange={setNextEmail} autoComplete="email" /><p>Your current email stays in use until both steps succeed.</p></>}<Button className={authButtonClass} variant="primary" type="submit" isLoading={op.busy}>{action === "password" ? "Confirm and save" : "Continue"}</Button></form> : action.startsWith("unlink:") ? <><p>You won't be able to sign in with {label}. Sessions started with it will end, including this one if you used {label} here. Sign in again with a remaining method if this session ends.</p><Button className={authButtonClass} onClick={onClose}>Keep method</Button><Button className={authButtonClass} variant="danger" onClick={() => beginConfirmation()}>Confirm removal</Button></> : action === "delete" ? <><p>Your sessions will end now. Your account and data will be permanently removed after 14 days. Signing in during those 14 days cancels deletion. Local unsent changes on your devices remain there until you sign out of each device.</p><Button className={authButtonClass} ref={keepAccount} onClick={onClose}>Keep account</Button><Button className={authButtonClass} variant="danger" onClick={() => beginConfirmation()}>Confirm and delete</Button></> : <Button className={authButtonClass} onClick={() => beginConfirmation()}>Confirm again</Button>}
    </>}
  </div></Overlay>;
}
