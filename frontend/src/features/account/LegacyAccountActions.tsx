import { useRef, useState, type FormEvent } from "react";
import { useMutation } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { Download } from "lucide-react";
import { downloadAccountExport } from "../../api/account";
import { apiClient } from "../../api/client";
import { Button } from "../../components/ui/Button";
import { Overlay, OverlayHeader } from "../../components/ui/Overlay";
import { Feedback, Field, SectionCard } from "../../components/ui/SettingsSection";
import { useAuthStore } from "../../stores/authStore";
import { getErrorMessage } from "../../utils/error";
import { assertActingOwner } from "../auth/authFlow";

/** Preserve password-account rights before optional auth origins/keys are configured. */
export function LegacyAccountActions({ owner, directDelete }: { owner: string; directDelete: boolean }): React.JSX.Element {
  return <div className="contents [&_button]:min-h-11 [&_input]:min-h-11 [&_input]:focus-visible:outline-2 [&_input]:focus-visible:outline-offset-2 [&_input]:focus-visible:outline-sky-700"><PasswordSection owner={owner} /><DataSection owner={owner} /><DangerZone owner={owner} directDelete={directDelete} /></div>;
}

function PasswordSection({ owner }: { owner: string }): React.JSX.Element {
  const submitting = useRef(false);
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const mutation = useMutation({
    onSettled: () => { submitting.current = false; },
    mutationFn: () => { assertActingOwner(owner); return apiClient.changePassword({ current_password: current, new_password: next }, owner); },
    onSuccess: () => {
      assertActingOwner(owner);
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
    if (submitting.current) return;
    if (next !== confirm) {
      setSuccess(null);
      setError("New passwords don't match.");
      return;
    }
    submitting.current = true;
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

function DataSection({ owner }: { owner: string }): React.JSX.Element {
  const submitting = useRef(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const handleDownload = async () => {
    if (submitting.current) return;
    submitting.current = true;
    setBusy(true);
    setError(null);
    setSuccess(null);
    try {
      const filename = await downloadAccountExport(owner, () => assertActingOwner(owner));
      setSuccess(`Download started: ${filename}`);
    } catch (caught) {
      setError(getErrorMessage(caught));
    } finally {
      submitting.current = false;
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

function DangerZone({ owner, directDelete }: { owner: string; directDelete: boolean }): React.JSX.Element {
  const [dialogOpen, setDialogOpen] = useState(directDelete);

  return (
    <SectionCard
      tone="danger"
      title="Danger zone"
      description="Deleting your account deactivates it immediately and permanently erases all of your data after 14 days."
    >
      <Button type="button" variant="danger" size="md" onClick={() => setDialogOpen(true)}>
        Delete account…
      </Button>
      {dialogOpen ? <DeleteAccountDialog owner={owner} onClose={() => setDialogOpen(false)} /> : null}
    </SectionCard>
  );
}

function DeleteAccountDialog({ owner, onClose }: { owner: string; onClose: () => void }): React.JSX.Element {
  const submitting = useRef(false);
  const navigate = useNavigate();
  const clearSessionAfterCleanup = useAuthStore((state) => state.clearSessionAfterCleanup);
  const scheduleDeletionNotice = useAuthStore((state) => state.scheduleDeletionNotice);
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);

  const mutation = useMutation({
    onSettled: () => { submitting.current = false; },
    mutationFn: () => { assertActingOwner(owner); return apiClient.requestAccountDeletion({ current_password: password }, owner); },
    onSuccess: async (scheduled) => {
      assertActingOwner(owner);
      // Cleanup must finish before the session is cleared: ProtectedRoute races
      // us to /login and the departing owner's browser-local keys must not be
      // carried into the next account.
      if (!(await clearSessionAfterCleanup())) {
        setError("We couldn't clear this browser's local CRT data. No account transition was made.");
        return;
      }
      scheduleDeletionNotice(scheduled.purge_at);
      navigate("/login", { replace: true, state: { deletionScheduled: scheduled.purge_at } });
    },
    onError: (caught: unknown) => setError(getErrorMessage(caught))
  });

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault();
    if (submitting.current) return;
    submitting.current = true;
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
      <form className="flex flex-col gap-4 px-5 py-5 sm:px-6 [&_button]:min-h-11 [&_input]:min-h-11 [&_input]:focus-visible:outline-2 [&_input]:focus-visible:outline-offset-2 [&_input]:focus-visible:outline-sky-700" onSubmit={handleSubmit}>
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
