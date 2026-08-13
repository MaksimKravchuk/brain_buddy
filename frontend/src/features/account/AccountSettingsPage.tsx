import { useState, type FormEvent } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { Download } from "lucide-react";

import { downloadAccountExport } from "../../api/account";
import { accountKeys, useAccountQuery } from "../../api/accountHooks";
import type { AccountResponse } from "../../api/accountTypes";
import { apiClient } from "../../api/client";
import { useProjects, useTags, useTaskList } from "../../api/taskHooks";
import type { TaskCounts } from "../../api/taskTypes";
import { AppShell } from "../../components/shell/AppShell";
import { Button } from "../../components/ui/Button";
import { Overlay, OverlayHeader } from "../../components/ui/Overlay";
import { Feedback, Field, SectionCard } from "../../components/ui/SettingsSection";
import { useAuthStore } from "../../stores/authStore";
import { getErrorMessage } from "../../utils/error";

const emptyCounts: TaskCounts = { inbox: 0, next: 0, waiting: 0, someday: 0 };

/** Mirror a fresh account payload into the query cache and auth store. */
function useAccountSync() {
  const queryClient = useQueryClient();
  return (account: AccountResponse) => {
    queryClient.setQueryData(accountKeys.detail(), account);
    const { user } = useAuthStore.getState();
    if (user) {
      useAuthStore.setState({
        user: { ...user, email: account.email, display_name: account.display_name }
      });
    }
  };
}

export function AccountSettingsPage(): React.JSX.Element {
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
        <EmailSection />
        <PasswordSection />
        <DataSection />
        <DangerZone />
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
    </SectionCard>
  );
}

function EmailSection(): React.JSX.Element {
  const account = useAccountQuery();
  const syncAccount = useAccountSync();
  const [newEmail, setNewEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: () => apiClient.changeEmail({ new_email: newEmail, current_password: password }),
    onSuccess: (updated) => {
      syncAccount(updated);
      setNewEmail("");
      setPassword("");
      setError(null);
      setSuccess(`Email changed to ${updated.email}.`);
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
      title="Email address"
      description={`You currently sign in as ${account.data?.email ?? "…"}. Changing it takes effect immediately — there is no confirmation email.`}
    >
      <form className="flex flex-col gap-3" onSubmit={handleSubmit}>
        <Field
          label="New email"
          name="new_email"
          type="email"
          value={newEmail}
          onChange={setNewEmail}
          autoComplete="email"
        />
        <Field
          label="Current password"
          name="current_password"
          type="password"
          value={password}
          onChange={setPassword}
          autoComplete="current-password"
        />
        <Feedback error={error} success={success} />
        <div>
          <Button type="submit" variant="primary" size="md" isLoading={mutation.isPending}>
            Change email
          </Button>
        </div>
      </form>
    </SectionCard>
  );
}

function PasswordSection(): React.JSX.Element {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: () => apiClient.changePassword({ current_password: current, new_password: next }),
    onSuccess: () => {
      setCurrent("");
      setNext("");
      setConfirm("");
      setError(null);
      setSuccess("Password changed. Other devices have been signed out.");
    },
    onError: (caught: unknown) => {
      setSuccess(null);
      setError(getErrorMessage(caught));
    }
  });

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault();
    if (next !== confirm) {
      setSuccess(null);
      setError("New passwords don't match.");
      return;
    }
    mutation.mutate();
  };

  return (
    <SectionCard
      title="Password"
      description="At least 12 characters. Changing it signs out every other device."
    >
      <form className="flex flex-col gap-3" onSubmit={handleSubmit}>
        <Field
          label="Current password"
          name="current_password"
          type="password"
          value={current}
          onChange={setCurrent}
          autoComplete="current-password"
        />
        <Field
          label="New password"
          name="new_password"
          type="password"
          value={next}
          onChange={setNext}
          autoComplete="new-password"
        />
        <Field
          label="Confirm new password"
          name="confirm_password"
          type="password"
          value={confirm}
          onChange={setConfirm}
          autoComplete="new-password"
        />
        <Feedback error={error} success={success} />
        <div>
          <Button type="submit" variant="primary" size="md" isLoading={mutation.isPending}>
            Change password
          </Button>
        </div>
      </form>
    </SectionCard>
  );
}

function DataSection(): React.JSX.Element {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const handleDownload = async () => {
    setBusy(true);
    setError(null);
    setSuccess(null);
    try {
      const filename = await downloadAccountExport();
      setSuccess(`Download started: ${filename}`);
    } catch (caught) {
      setError(getErrorMessage(caught));
    } finally {
      setBusy(false);
    }
  };

  return (
    <SectionCard
      title="Your data"
      description="Download everything your account owns — trees with their history, tasks, and voice notes — as one ZIP of JSON files plus any still-retained audio."
    >
      <div className="flex flex-col gap-3">
        <Feedback error={error} success={success} />
        <div>
          <Button type="button" variant="secondary" size="md" isLoading={busy} onClick={handleDownload}>
            <Download className="h-4 w-4" aria-hidden /> Download my data (.zip)
          </Button>
        </div>
      </div>
    </SectionCard>
  );
}

function DangerZone(): React.JSX.Element {
  const [dialogOpen, setDialogOpen] = useState(false);

  return (
    <SectionCard
      tone="danger"
      title="Danger zone"
      description="Deleting your account deactivates it immediately and permanently erases all of your data after 14 days."
    >
      <Button type="button" variant="danger" size="md" onClick={() => setDialogOpen(true)}>
        Delete account…
      </Button>
      {dialogOpen ? <DeleteAccountDialog onClose={() => setDialogOpen(false)} /> : null}
    </SectionCard>
  );
}

function DeleteAccountDialog({ onClose }: { onClose: () => void }): React.JSX.Element {
  const navigate = useNavigate();
  const clearSession = useAuthStore((state) => state.clearSession);
  const scheduleDeletionNotice = useAuthStore((state) => state.scheduleDeletionNotice);
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: () => apiClient.requestAccountDeletion({ current_password: password }),
    onSuccess: (scheduled) => {
      // Stash the purge date in the store before clearing the session:
      // ProtectedRoute races us to /login and would drop router state.
      scheduleDeletionNotice(scheduled.purge_at);
      clearSession();
      navigate("/login", { replace: true, state: { deletionScheduled: scheduled.purge_at } });
    },
    onError: (caught: unknown) => setError(getErrorMessage(caught))
  });

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault();
    mutation.mutate();
  };

  return (
    <Overlay labelledBy="delete-account-title" onClose={onClose} size="narrow">
      <OverlayHeader
        titleId="delete-account-title"
        eyebrow="Danger zone"
        title="Delete your account?"
        onClose={onClose}
      />
      <form className="flex flex-col gap-4 px-5 py-5 sm:px-6" onSubmit={handleSubmit}>
        <ul className="list-disc space-y-1 pl-5 text-sm text-slate-600">
          <li>Your account is deactivated immediately and you are signed out everywhere.</li>
          <li>After 14 days, all trees, tasks, and voice notes are permanently erased.</li>
          <li>Signing back in before then cancels the deletion.</li>
        </ul>
        <Field
          label="Confirm with your password"
          name="current_password"
          type="password"
          value={password}
          onChange={setPassword}
          autoComplete="current-password"
        />
        <Feedback error={error} success={null} />
        <div className="flex justify-end gap-2">
          <Button type="button" variant="secondary" size="md" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" variant="danger" size="md" isLoading={mutation.isPending}>
            Delete my account
          </Button>
        </div>
      </form>
    </Overlay>
  );
}
