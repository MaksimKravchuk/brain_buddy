import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { adminKeysFor, useAdminAccounts } from "../../api/adminHooks";
import { ApiError, apiClient } from "../../api/client";
import type { AdminAccountResponse } from "../../api/adminTypes";
import { useAuthStore } from "../../stores/authStore";
import { Button } from "../../components/ui/Button";
import { Field } from "../../components/ui/SettingsSection";

function errorMessage(error: unknown, action: string): string {
  const suffix = error instanceof ApiError && error.correlationId ? ` (reference ${error.correlationId})` : "";
  return `Could not ${action}. Check the account and try again${suffix}.`;
}

export function AdminUsersSection(): React.JSX.Element {
  const queryClient = useQueryClient();
  const ownerId = useAuthStore((state) => state.user?.id ?? null);
  const accounts = useAdminAccounts();
  const [editing, setEditing] = useState<AdminAccountResponse | null>(null);
  const [deleting, setDeleting] = useState<AdminAccountResponse | null>(null);
  const [revoking, setRevoking] = useState<AdminAccountResponse | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [focusCreateAfterClose, setFocusCreateAfterClose] = useState(false);
  const triggerRefs = useRef(new Map<string, HTMLButtonElement>());
  const rowRefs = useRef(new Map<string, HTMLTableRowElement>());
  const [focusAfterRefresh, setFocusAfterRefresh] = useState<string | null>(null);
  useEffect(() => {
    if (!focusAfterRefresh) return;
    const row = rowRefs.current.get(focusAfterRefresh);
    if (row) { row.tabIndex = -1; row.focus(); setFocusAfterRefresh(null); }
  }, [accounts.data, focusAfterRefresh]);
  useEffect(() => {
    if (!showCreate && focusCreateAfterClose) {
      triggerRefs.current.get("create")?.focus();
      setFocusCreateAfterClose(false);
    }
  }, [showCreate, focusCreateAfterClose]);
  const refresh = () => queryClient.invalidateQueries({ queryKey: adminKeysFor(ownerId).accounts() });
  const deleteMutation = useMutation({
    mutationFn: (id: string) => apiClient.deleteAdminAccount(id),
    onSuccess: async () => { setDeleting(null); setMessage("Account permanently deleted."); await refresh(); setFocusAfterRefresh(focusAfterDelete.current); },
    onError: (error) => { setDeleting(null); refresh(); setMessage(errorMessage(error, "delete the account")); triggerRefs.current.get(`delete:${deleting?.id ?? ""}`)?.focus(); }
  });
  const focusAfterDelete = useRef<string | null>(null);
  const revokeMutation = useMutation({
    mutationFn: (id: string) => apiClient.revokeAdminAccountSessions(id),
    onSuccess: (result) => { setRevoking(null); setMessage(`Revoked ${result.revoked_count} session${result.revoked_count === 1 ? "" : "s"}.`); triggerRefs.current.get(revoking?.id ?? "")?.focus(); },
    onError: (error) => { setRevoking(null); setMessage(errorMessage(error, "revoke sessions")); triggerRefs.current.get(revoking?.id ?? "")?.focus(); }
  });

  return (
    <section className="w-full">
      <h2 className="text-subtitle font-semibold text-slate-900">Users</h2>
      <p className="mt-1 text-sm text-slate-500">Create, edit, revoke, or permanently delete member accounts.</p>
      <div className="mt-4 flex flex-col gap-4">
        {!showCreate ? <Button type="button" variant="primary" ref={(button) => { if (button) triggerRefs.current.set("create", button); else triggerRefs.current.delete("create"); }} onClick={() => setShowCreate(true)}>Create user</Button> : <AdminCreateForm onCreated={(account) => { setShowCreate(false); setMessage("Account created."); void refresh().then(() => setFocusAfterRefresh(account.id)); }} onError={(error) => setMessage(errorMessage(error, "create the account"))} onCancel={() => { setFocusCreateAfterClose(true); setShowCreate(false); }} />}
        {message ? <p role="status" className="text-sm text-slate-600">{message}</p> : null}
        {accounts.isPending ? <p role="status">Loading users…</p> : null}
        {accounts.isError ? (
          <div role="alert" className="flex flex-wrap items-center gap-3">
            <span>
              {accounts.error instanceof ApiError && accounts.error.correlationId
                ? `Couldn't load users. Ref: ${accounts.error.correlationId}`
                : "Couldn't load users."}
            </span>
          </div>
        ) : null}
        {(accounts.isError || accounts.data) && !accounts.isFetching ? (
          <Button type="button" variant="secondary" size="sm" onClick={() => void accounts.refetch()}>
            Retry
          </Button>
        ) : null}
        {accounts.data?.accounts.length === 0 && !accounts.isError ? (
          <p role="status">No accounts to manage yet.</p>
        ) : null}
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <caption className="sr-only">Admin users</caption>
            <thead><tr><th className="py-2">Email</th><th>Name</th><th>Deletion requested</th><th>Actions</th></tr></thead>
            <tbody>{accounts.data?.accounts.map((account) => (
              <tr key={account.id} ref={(row) => { if (row) rowRefs.current.set(account.id, row); else rowRefs.current.delete(account.id); }} className="border-t border-slate-200">
                <td className="py-2">{account.email}</td><td>{account.display_name ?? "—"}</td><td>{account.deletion_requested ? "Yes" : "No"}</td>
                <td className="flex flex-wrap gap-2 py-2">
                  <Button type="button" size="sm" variant="secondary" aria-label={`Edit ${account.id} (${account.email})`} ref={(button) => { if (button) triggerRefs.current.set(`edit:${account.id}`, button); }} onClick={() => setEditing(account)}>Edit</Button>
                  <Button type="button" size="sm" variant="secondary" aria-label={`Revoke sessions for ${account.id} (${account.email})`} ref={(button) => { if (button) triggerRefs.current.set(account.id, button); }} onClick={() => setRevoking(account)}>Revoke sessions</Button>
                  {account.id !== ownerId ? <Button type="button" size="sm" variant="danger" aria-label={`Delete ${account.id} (${account.email})`} ref={(button) => { if (button) triggerRefs.current.set(`delete:${account.id}`, button); }} onClick={() => { const index = (accounts.data?.accounts ?? []).findIndex((candidate) => candidate.id === account.id); const next = (accounts.data?.accounts ?? [])[index + 1] ?? (accounts.data?.accounts ?? [])[index - 1]; focusAfterDelete.current = next?.id ?? null; setDeleting(account); }}>Delete</Button> : null}
                </td>
              </tr>
            ))}</tbody>
          </table>
        </div>
        {editing ? <AdminEditForm account={editing} onSaved={() => { setEditing(null); setMessage("Account updated."); void refresh(); triggerRefs.current.get(`edit:${editing.id}`)?.focus(); }} onError={(error) => setMessage(errorMessage(error, "update the account"))} onCancel={() => { setEditing(null); triggerRefs.current.get(`edit:${editing.id}`)?.focus(); }} /> : null}
        {revoking ? <ConfirmDialog title={`Revoke sessions for ${revoking.id} (${revoking.email})`} description={`This signs out ${revoking.id} (${revoking.email}) on every device.`} confirmLabel="Revoke sessions" isLoading={revokeMutation.isPending} onCancel={() => { setRevoking(null); triggerRefs.current.get(revoking.id)?.focus(); }} onConfirm={() => revokeMutation.mutate(revoking.id)} /> : null}
        {deleting ? <ConfirmDialog title={`Delete account ${deleting.id} (${deleting.email})`} description={`This permanently deletes ${deleting.id} (${deleting.email}) and all data they own. This cannot be undone.`} confirmLabel="Delete permanently" isLoading={deleteMutation.isPending} onCancel={() => { setDeleting(null); triggerRefs.current.get(`delete:${deleting.id}`)?.focus(); }} onConfirm={() => deleteMutation.mutate(deleting.id)} /> : null}
      </div>
    </section>
  );
}

function ConfirmDialog({ title, description, confirmLabel, isLoading, onCancel, onConfirm }: { title: string; description: string; confirmLabel: string; isLoading: boolean; onCancel: () => void; onConfirm: () => void }): React.JSX.Element {
  const dialogRef = useRef<HTMLDivElement | null>(null);
  const cancelRef = useRef<HTMLButtonElement | null>(null);
  useEffect(() => { cancelRef.current?.focus(); }, []);
  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === "Escape") { event.preventDefault(); onCancel(); return; }
    if (event.key !== "Tab" || !dialogRef.current) return;
    const focusable = Array.from(dialogRef.current.querySelectorAll<HTMLElement>("button:not([disabled]), [href], input, select, textarea, [tabindex]:not([tabindex='-1'])"));
    if (!focusable.length) return;
    const first = focusable[0]; const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
  };
  return <div ref={dialogRef} role="dialog" aria-modal="true" aria-label={title} tabIndex={-1} onKeyDown={onKeyDown} className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/40 p-4">
    <div className="w-full max-w-md rounded-lg bg-white p-5 shadow-xl">
      <h2 id="admin-confirm-title" className="text-lg font-semibold">{title}</h2>
      <p className="mt-3 text-sm text-slate-600">{description}</p>
      <div className="mt-5 flex justify-end gap-2"><Button type="button" variant="secondary" ref={cancelRef} onClick={onCancel}>Cancel</Button><Button type="button" variant="danger" isLoading={isLoading} onClick={onConfirm}>{confirmLabel}</Button></div>
    </div>
  </div>;
}

function AdminCreateForm({ onCreated, onError, onCancel }: { onCreated: (account: AdminAccountResponse) => void; onError: (error: unknown) => void; onCancel: () => void }): React.JSX.Element {
  const [email, setEmail] = useState(""); const [name, setName] = useState(""); const [password, setPassword] = useState("");
  const mutation = useMutation({ mutationFn: () => apiClient.createAdminAccount({ email, display_name: name || null, password }), onSuccess: (account) => { setEmail(""); setName(""); setPassword(""); onCreated(account); }, onError });
  const cancel = () => { setEmail(""); setName(""); setPassword(""); onCancel(); };
  const onKeyDown = (event: KeyboardEvent<HTMLFormElement>) => { if (event.key === "Escape") { event.preventDefault(); cancel(); } };
  return <form onKeyDown={onKeyDown} onSubmit={(event: FormEvent) => { event.preventDefault(); mutation.mutate(); }} className="grid gap-3 rounded-md border border-slate-200 p-3 sm:grid-cols-2" aria-label="Create user">
    <Field label="Email" name="new_user_email" value={email} onChange={setEmail} type="email" />
    <Field label="Display name (optional)" name="new_user_name" value={name} onChange={setName} type="text" />
    <Field label="Initial password" name="new_user_password" value={password} onChange={setPassword} type="password" />
    <div className="flex gap-2 self-end"><Button type="submit" size="md" variant="primary" isLoading={mutation.isPending}>Create user</Button><Button type="button" size="md" variant="secondary" onClick={cancel}>Cancel</Button></div>
  </form>;
}

function AdminEditForm({ account, onSaved, onError, onCancel }: { account: AdminAccountResponse; onSaved: () => void; onError: (error: unknown) => void; onCancel: () => void }): React.JSX.Element {
  const [email, setEmail] = useState(account.email); const [name, setName] = useState(account.display_name ?? "");
  const mutation = useMutation({ mutationFn: () => apiClient.updateAdminAccount(account.id, { email, display_name: name || null }), onSuccess: onSaved, onError });
  const onKeyDown = (event: KeyboardEvent<HTMLFormElement>) => { if (event.key === "Escape") { event.preventDefault(); onCancel(); } };
  return <form onKeyDown={onKeyDown} onSubmit={(event) => { event.preventDefault(); mutation.mutate(); }} className="grid gap-3 rounded-md border border-slate-200 p-3 sm:grid-cols-2" aria-label={`Edit ${account.email}`}>
    <Field label="Email" name="edit_user_email" value={email} onChange={setEmail} type="email" />
    <Field label="Display name" name="edit_user_name" value={name} onChange={setName} type="text" />
    <div className="flex gap-2"><Button type="submit" size="md" variant="primary" isLoading={mutation.isPending}>Save</Button><Button type="button" size="md" variant="secondary" onClick={onCancel}>Cancel</Button></div>
  </form>;
}
