import { useRef, useState, type FormEvent } from "react";
import { useMutation } from "@tanstack/react-query";

import { useAdminStatus } from "../../api/adminHooks";
import { ApiError, apiClient } from "../../api/client";
import type { AdminAccountResponse } from "../../api/adminTypes";
import { useProjects, useTags, useTaskList } from "../../api/taskHooks";
import { useAuthStore } from "../../stores/authStore";
import type { TaskCounts } from "../../api/taskTypes";
import { AppShell } from "../../components/shell/AppShell";
import { Button } from "../../components/ui/Button";
import { Overlay, OverlayHeader } from "../../components/ui/Overlay";
import { Feedback, Field, SectionCard } from "../../components/ui/SettingsSection";
import { getErrorMessage } from "../../utils/error";
import { AdminFeatureFlagsSection } from "./AdminFeatureFlagsSection";

const emptyCounts: TaskCounts = { inbox: 0, next: 0, waiting: 0, someday: 0 };

// At least as permissive as what the server accepts, deliberately: `seed_admin`
// and `AdminSettings` admit any normalized address containing "@", including
// `admin@localhost`, so a pattern requiring a dotted domain would classify a
// real (possibly operator) account as an account ID and report it missing.
// Malformed email-like input (`a@`, `@b`) still falls through to account_id
// and yields D-04, which is the design's stated behaviour.
const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+$/;

// 009-FR-005: the /admin route renders only for a signed-in caller the server
// confirms is an operator, and only the four AdminAccountResponse fields for
// a found account -- everywhere else it shows a loading or denied state.
export function AdminPage(): React.JSX.Element {
  const countsQuery = useTaskList({ state: "next", limit: 1 });
  const projectsQuery = useProjects();
  const tagsQuery = useTags();
  const adminStatus = useAdminStatus();
  // Null-safe and fail-closed: an unexpected/empty body is not an operator.
  const isOperator = adminStatus.isSuccess && adminStatus.data?.is_operator === true;
  // D-08 vs D-09. A *confirmed* answer from the server — 403 (not an operator)
  // or 404 (the rollout flag is not effective, 009-FR-013) — is a settled
  // denial. Anything else (network, timeout, 5xx) means the check itself never
  // completed, and telling a legitimate operator they are unauthorized because
  // a request failed would be wrong.
  const denialStatus =
    adminStatus.error instanceof ApiError ? adminStatus.error.status : null;
  const isConfirmedDenial = denialStatus === 403 || denialStatus === 404;
  const couldNotVerify = adminStatus.isError && !isConfirmedDenial;

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
          // 010: the runtime flag section lives inside the operator-confirmed
          // branch only. An operator denied at D-08, unverified at D-09 or still
          // checking at D-01 never sees it, so this feature adds no new denial
          // state and no new way to observe the operator allow-list.
          <>
            <AdminLookup />
            <AdminFeatureFlagsSection />
          </>
        ) : couldNotVerify ? (
          <AccessUnverified onRetry={() => void adminStatus.refetch()} />
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

function AccessUnverified({ onRetry }: { onRetry: () => void }): React.JSX.Element {
  return (
    <SectionCard
      title="Couldn't verify access"
      description="Couldn't verify access. Try again."
    >
      <div>
        <Button type="button" variant="secondary" size="md" onClick={onRetry}>
          Try again
        </Button>
      </div>
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
  const signedInUserId = useAuthStore((state) => state.user?.id ?? null);
  // Focus restoration is kept local to this dialog on purpose: `Overlay` is
  // shared by the capture and task screens, and changing its unmount behaviour
  // app-wide is a regression surface this bounded slice has no evidence for.
  const revokeTriggerRef = useRef<HTMLButtonElement | null>(null);
  const restoreFocus = () => revokeTriggerRef.current?.focus();

  const lookupMutation = useMutation({
    // The submitted value is sent as typed. Trimming would turn a whitespace
    // variant of a real address into the canonical one and produce a match the
    // server is required to refuse (009-FR-003) — the client must not repair
    // an identifier into a hit.
    mutationFn: (value: string) =>
      apiClient.lookupAdminAccount(
        EMAIL_PATTERN.test(value) ? { email: value } : { account_id: value }
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
      restoreFocus();
      setError(null);
      setRevokeMessage(`Revoked ${result.revoked_count} session${result.revoked_count === 1 ? "" : "s"}.`);
    },
    onError: (caught: unknown) => {
      setConfirmOpen(false);
      restoreFocus();
      if (caught instanceof ApiError && caught.status === 404) {
        // The target was purged between lookup and confirm: D-04 copy, not a
        // raw error banner (design D-07).
        setAccount(null);
        setNotFound(true);
        setError(null);
        return;
      }
      setError(getErrorMessage(caught));
    }
  });

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault();
    if (!query.trim()) {
      return;
    }
    // A new lookup always starts from a clean slate: a stale account or
    // revoke result must never linger under a different query.
    setAccount(null);
    setNotFound(false);
    setError(null);
    setRevokeMessage(null);
    lookupMutation.mutate(query);
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
              <Button
                type="button"
                variant="danger"
                size="md"
                ref={revokeTriggerRef}
                onClick={() => setConfirmOpen(true)}
              >
                Revoke sessions
              </Button>
            </div>
          </div>
        </SectionCard>
      ) : null}

      {confirmOpen && account ? (
        <RevokeConfirmDialog
          account={account}
          isSelf={signedInUserId !== null && signedInUserId === account.id}
          isLoading={revokeMutation.isPending}
          onCancel={() => {
            setConfirmOpen(false);
            restoreFocus();
          }}
          onConfirm={() => revokeMutation.mutate(account.id)}
        />
      ) : null}
    </>
  );
}

function RevokeConfirmDialog({
  account,
  isSelf,
  isLoading,
  onCancel,
  onConfirm
}: {
  account: AdminAccountResponse;
  /** The target is the signed-in operator's own account — read from the
   *  existing auth store, so no auth payload grows for this. */
  isSelf: boolean;
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
        {isSelf ? (
          <p className="text-sm font-medium text-slate-900">
            This is your own account — you will be signed out everywhere, including
            this tab.
          </p>
        ) : null}
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
