import { useAuthOperation } from "./authOperation";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { modernAuthApi, type AuthAction, type AccountMethods, type Methods, type RecentProof, type ClientProof, type Challenge } from "../../api/modernAuth";
import { Button } from "../../components/ui/Button";
import { AuthField, CodeStep, authButtonClass } from "./AuthControls";
import { assertActingOwner, createClientProof, startBrowserProvider } from "./authFlow";

export function ConfirmAccount({ owner, action, methods, availability, onConfirm, onCancel }: { owner: string; action: AuthAction; methods: AccountMethods; availability: Methods | null; onConfirm: (proof: RecentProof) => Promise<void>; onCancel: () => void }): React.JSX.Element {
  const [password, setPassword] = useState("");
  const [code, setCode] = useState<{ challenge: Challenge; client: ClientProof } | null>(null);
  const op = useAuthOperation();
  const active = useRef(true);
  useEffect(() => { active.current = true; return () => { active.current = false; }; }, []);
  const confirm = async (proof: RecentProof) => {
    assertActingOwner(owner);
    if (!active.current) return;
    if (proof.status !== "reauthenticated" || typeof proof.recent_proof !== "string" || !Number.isFinite(Date.parse(proof.expires_at)) || Date.parse(proof.expires_at) <= Date.now()) throw new Error("Confirmation expired");
    setPassword(""); setCode(null); await onConfirm(proof);
  };
  const submit = (event: FormEvent) => { event.preventDefault(); void op.run(async () => {
    assertActingOwner(owner);
    const proof = await modernAuthApi.confirmPassword({ current_password: password, action, expected_account_id: owner });
    await confirm(proof);
  }, "Couldn't confirm this account. Try again with a connected method."); };
  if (code) return <CodeStep challenge={code.challenge} verifier={code.client.verifier} email={methods.email} onCancel={() => setCode(null)} onComplete={async result => { if (result.status !== "reauthenticated") throw new Error("Wrong confirmation purpose"); await confirm(result); }} />;
  return <div className="flex flex-col gap-4"><h3 className="text-subtitle font-semibold">Confirm it's you</h3><p>Continue as <strong>{methods.email}</strong>. Only methods already connected to this account can confirm it. Confirmation lasts five minutes.</p>
    {op.error ? <p role="alert" className="text-sm text-rose-700">{op.error}</p> : null}
    {methods.has_password ? <form onSubmit={submit} className="flex flex-col gap-3" aria-busy={op.busy}><AuthField label="Current password" type="password" autoComplete="current-password" value={password} onChange={setPassword} /><Button className={authButtonClass} variant="primary" type="submit" isLoading={op.busy}>{op.busy ? "Please wait…" : "Confirm"}</Button></form> : null}
    {methods.email_verified && methods.email_delivery === "available" && availability?.email && methods.methods.some(method => method.method === "email" && method.usable) ? <Button className={authButtonClass} disabled={op.busy} onClick={() => void op.run(async () => { assertActingOwner(owner); const client = await createClientProof(); const challenge = await modernAuthApi.requestEmail({ email: methods.email, purpose: "reauth", client: "web", client_challenge: client.challenge, action, expected_account_id: owner }); assertActingOwner(owner); setCode({ client, challenge }); })}>Send an email code</Button> : null}
    {(["google", "apple"] as const).filter(provider => availability?.[provider] && methods.methods.some(method => method.method === provider && method.usable)).map(provider => <Button key={provider} className={authButtonClass} disabled={op.busy} onClick={() => void op.run(async () => { assertActingOwner(owner); await startBrowserProvider(provider, { purpose: "reauth", action, expected_account_id: owner }, `/settings/account?expected_owner=${encodeURIComponent(owner)}`); })}>Confirm with {provider === "google" ? "Google" : "Apple"}</Button>)}
    <Button className={authButtonClass} disabled={op.busy} onClick={onCancel}>Cancel</Button><p className="text-sm text-slate-600">Your account and tasks stay unchanged if you cancel before submitting the action.</p>
  </div>;
}
