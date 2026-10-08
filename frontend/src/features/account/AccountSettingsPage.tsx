import { useState, type FormEvent } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { accountKeys, useAccountQuery } from "../../api/accountHooks";
import type { AccountResponse } from "../../api/accountTypes";
import { apiClient } from "../../api/client";
import { useProjects, useTags, useTaskList } from "../../api/taskHooks";
import type { TaskCounts } from "../../api/taskTypes";
import { AppShell } from "../../components/shell/AppShell";
import { Button } from "../../components/ui/Button";
import { Feedback, Field, SectionCard } from "../../components/ui/SettingsSection";
import { useAuthStore } from "../../stores/authStore";
import { getErrorContext, getErrorMessage } from "../../utils/error";
import { ReviewSettingsSection } from "../review/ReviewSettingsSection";

import { AccountSecurity } from "../auth/AccountSecurity";

const emptyCounts: TaskCounts = { inbox: 0, next: 0, waiting: 0, someday: 0 };

/** Mirror a fresh account payload into the query cache and auth store. */
function useAccountSync() {
  const queryClient = useQueryClient();
  return (account: AccountResponse) => {
    queryClient.setQueryData(accountKeys.detail(), account);
    const { user } = useAuthStore.getState();
    if (user?.id === account.id) {
      useAuthStore.setState({
        user: { ...user, email: account.email, display_name: account.display_name }
      });
    }
  };
}

export function AccountSettingsPage({ directDelete = false }: { directDelete?: boolean }): React.JSX.Element {
  const queryClient = useQueryClient();
  const countsQuery = useTaskList({ state: "next", limit: 1 });
  const projectsQuery = useProjects();
  const tagsQuery = useTags();

  return (
    <AppShell
      counts={countsQuery.data?.counts_by_state ?? emptyCounts}
      projects={projectsQuery.data ?? []}
      tags={tagsQuery.data ?? []}
    >
      <div className="mx-auto flex max-w-[680px] flex-col gap-5 pb-12">
        <header>
          <h1 className="text-title font-semibold text-slate-900">Account settings</h1>
          <p className="mt-1 text-sm text-slate-500">
            Manage your profile, credentials, and data. Export and deletion are
            always available — they are your data rights, not features.
          </p>
        </header>
        <ProfileSection />
        {/* Spec 020 D-04; renders nothing while weekly_review is off. */}
        <ReviewSettingsSection />
        <AccountSecurity directDelete={directDelete} onUpdated={() => { void queryClient.invalidateQueries({ queryKey: accountKeys.detail() }); }} />
      </div>
    </AppShell>
  );
}

function ProfileSection(): React.JSX.Element {
  const account = useAccountQuery();
  const syncAccount = useAccountSync();
  const [draft, setDraft] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const displayName = draft ?? account.data?.display_name ?? "";
  const countError = account.error
    ? getErrorContext(account.error, "Completed tasks unavailable.")
    : null;

  const mutation = useMutation({
    mutationFn: () => apiClient.updateProfile({ display_name: displayName }),
    onSuccess: (updated) => {
      syncAccount(updated);
      setDraft(null);
      setError(null);
      setSuccess("Profile saved.");
    },
    onError: (caught: unknown) => {
      setSuccess(null);
      setError(getErrorMessage(caught));
    }
  });

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault();
    mutation.mutate();
  };

  return (
    <SectionCard
      title="Profile"
      description="The name shown in the app. Leave it empty to go by your email."
    >
      <div className="flex flex-col gap-4">
        {countError ? (
          <p role="alert" className="text-sm text-red-700">
            Completed tasks unavailable. Refresh the page to try again.
            {countError.referenceId ? ` (ref: ${countError.referenceId})` : ""}
          </p>
        ) : account.data ? (
          <p aria-live="polite" aria-atomic="true" className="text-sm text-slate-600">
            Completed tasks: {account.data.completed_task_count}
          </p>
        ) : (
          <p role="status" aria-live="polite" className="text-sm text-slate-600">
            Completed tasks: …
          </p>
        )}
        <form className="flex flex-col gap-3" onSubmit={handleSubmit}>
          <Field
            label="Display name"
            name="display_name"
            type="text"
            value={displayName}
            onChange={(value) => setDraft(value)}
            autoComplete="name"
          />
          <Feedback error={error} success={success} />
          <div>
            <Button type="submit" variant="primary" size="md" isLoading={mutation.isPending}>
              Save profile
            </Button>
          </div>
        </form>
      </div>
    </SectionCard>
  );
}
