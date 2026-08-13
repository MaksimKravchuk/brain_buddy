import { useState, type FormEvent } from "react";
import { useMutation } from "@tanstack/react-query";

import { useAdminStatus } from "../../api/adminHooks";
import { ApiError, apiClient } from "../../api/client";
import type { AdminAccountResponse } from "../../api/adminTypes";
import { useProjects, useTags, useTaskList } from "../../api/taskHooks";
import type { TaskCounts } from "../../api/taskTypes";
import { AppShell } from "../../components/shell/AppShell";
import { Button } from "../../components/ui/Button";
import { Overlay, OverlayHeader } from "../../components/ui/Overlay";
import { Feedback, Field, SectionCard } from "../../components/ui/SettingsSection";
import { getErrorMessage } from "../../utils/error";

const emptyCounts: TaskCounts = { inbox: 0, next: 0, waiting: 0, someday: 0 };

const EMAIL_PATTERN = /^\S+@\S+\.\S+$/;

// 009-FR-005: the /admin route renders only for a signed-in caller the server
// confirms is an operator, and only the four AdminAccountResponse fields for
// a found account -- everywhere else it shows a loading or denied state.
export function AdminPage(): React.JSX.Element {
  const countsQuery = useTaskList({ state: "next", limit: 1 });
  const projectsQuery = useProjects();
  const tagsQuery = useTags();
  const adminStatus = useAdminStatus();
  const isOperator = adminStatus.isSuccess && adminStatus.data?.is_operator === true;

  return (
    <AppShell
      counts={countsQuery.data?.counts_by_state ?? emptyCounts}
      projects={projectsQuery.data ?? []}
      tags={tagsQuery.data ?? []}
    >
      <div className="mx-auto flex max-w-[680px] flex-col gap-5 pb-12">
        <header>
          <h1 className="text-title font-semibold text-slate-900">Admin</h1>
          <p className="mt-1 text-sm text-slate-500">
            Look up one member account by ID or email, and revoke its sessions.
          </p>
        </header>
        {adminStatus.isPending ? (
          <p role="status" className="text-sm text-slate-500">
            Checking access…
          </p>
        ) : isOperator ? (
          <AdminLookup />
        ) : (
          <AccessDenied />
        )}
      </div>
    </AppShell>
  );
}

function AccessDenied(): React.JSX.Element {
  return (
    <SectionCard
      tone="danger"
      title="Access denied"
      description="This account is not authorized for the admin portal."
    >
      {null}
    </SectionCard>
  );
}

function AdminLookup(): React.JSX.Element {
  const [query, setQuery] = useState("");
  const [account, setAccount] = useState<AdminAccountResponse | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [revokeMessage, setRevokeMessage] = useState<string | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);

  const lookupMutation = useMutation({
    mutationFn: (trimmed: string) =>
      apiClient.lookupAdminAccount(
        EMAIL_PATTERN.test(trimmed) ? { email: trimmed } : { account_id: trimmed }
      ),
    onSuccess: (found) => {
      setAccount(found);
      setNotFound(false);
      setError(null);
    },
    onError: (caught: unknown) => {
      if (caught instanceof ApiError && caught.status === 404) {
        setNotFound(true);
        setError(null);
      } else {
        setNotFound(false);
        setError(getErrorMessage(caught));
      }
    }
  });

  const revokeMutation = useMutation({
    mutationFn: (accountId: string) => apiClient.revokeAdminAccountSessions(accountId),
    onSuccess: (result) => {
      setConfirmOpen(false);
      setError(null);
      setRevokeMessage(`Revoked ${result.revoked_count} session${result.revoked_count === 1 ? "" : "s"}.`);
    },
    onError: (caught: unknown) => {
      setConfirmOpen(false);
      setError(getErrorMessage(caught));
    }
  });

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault();
    const trimmed = query.trim();
    if (!trimmed) {
      return;
    }
    // A new lookup always starts from a clean slate: a stale account or
    // revoke result must never linger under a different query.
    setAccount(null);
    setNotFound(false);
    setError(null);
    setRevokeMessage(null);
    lookupMutation.mutate(trimmed);
  };

  return (
    <>
      <SectionCard title="Find account" description="Enter an exact account ID or canonical email.">
        <form className="flex flex-col gap-3" onSubmit={handleSubmit}>
          <Field
            label="Account ID or email"
            name="admin_lookup_query"
            type="text"
            value={query}
            onChange={setQuery}
          />
          <Feedback error={error} success={null} />
          {notFound ? (
            <p role="status" className="rounded-md border border-slate-200 bg-surface-sunken px-3 py-2 text-sm text-slate-600">
              No account found.
            </p>
          ) : null}
          <div>
            <Button type="submit" variant="primary" size="md" isLoading={lookupMutation.isPending}>
              Look up
            </Button>
          </div>
        </form>
      </SectionCard>

      {account ? (
        <SectionCard title="Account" description="Only these fields are ever shown here.">
          <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-2 text-sm">
            <dt className="font-medium text-slate-500">Account ID</dt>
            <dd className="text-slate-900">{account.id}</dd>
            <dt className="font-medium text-slate-500">Email</dt>
            <dd className="text-slate-900">{account.email}</dd>
            <dt className="font-medium text-slate-500">Display name</dt>
            <dd className="text-slate-900">{account.display_name ?? "—"}</dd>
            <dt className="font-medium text-slate-500">Deletion requested</dt>
            <dd className="text-slate-900">{account.deletion_requested ? "Yes" : "No"}</dd>
          </dl>
          <div className="mt-4 flex flex-col gap-3">
            <Feedback error={null} success={revokeMessage} />
            <div>
              <Button type="button" variant="danger" size="md" onClick={() => setConfirmOpen(true)}>
                Revoke sessions
              </Button>
            </div>
          </div>
        </SectionCard>
      ) : null}

      {confirmOpen && account ? (
        <RevokeConfirmDialog
          account={account}
          isLoading={revokeMutation.isPending}
          onCancel={() => setConfirmOpen(false)}
          onConfirm={() => revokeMutation.mutate(account.id)}
        />
      ) : null}
    </>
  );
}

function RevokeConfirmDialog({
  account,
  isLoading,
  onCancel,
  onConfirm
}: {
  account: AdminAccountResponse;
  isLoading: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}): React.JSX.Element {
  return (
    <Overlay labelledBy="revoke-sessions-title" onClose={onCancel} size="narrow">
      <OverlayHeader
        titleId="revoke-sessions-title"
        eyebrow="Confirm"
        title={`Revoke sessions for ${account.id}?`}
        onClose={onCancel}
      />
      <div className="flex flex-col gap-4 px-5 py-5 sm:px-6">
        <p className="text-sm text-slate-600">
          Every current session for account <strong>{account.id}</strong> ({account.email}) will be
          signed out immediately.
        </p>
        <div className="flex justify-end gap-2">
          <Button type="button" variant="secondary" size="md" onClick={onCancel}>
            Cancel
          </Button>
          <Button type="button" variant="danger" size="md" isLoading={isLoading} onClick={onConfirm}>
            Revoke sessions
          </Button>
        </div>
      </div>
    </Overlay>
  );
}
