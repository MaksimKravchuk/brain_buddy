import { useEffect, useId, useState, type FormEvent } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { agentKeys, useAgentConnections } from "../../api/agentHooks";
import type { AgentConnectionResponse } from "../../api/agentTypes";
import { ApiError, apiClient } from "../../api/client";
import { useProjects, useTags, useTaskList } from "../../api/taskHooks";
import type { TaskCounts } from "../../api/taskTypes";
import { AppShell } from "../../components/shell/AppShell";
import { Button } from "../../components/ui/Button";
import { Overlay, OverlayHeader } from "../../components/ui/Overlay";
import { Feedback, Field, SectionCard } from "../../components/ui/SettingsSection";
import { getErrorMessage } from "../../utils/error";
import { newIdempotencyKey, useIntentKey, type IntentKey } from "../../utils/idempotency";
import {
  capabilityDisclosure,
  connectionStatusDetail,
  connectionStatusLabel,
  formatDuration,
  formatTimestamp
} from "./agentCopy";

const emptyCounts: TaskCounts = { inbox: 0, next: 0, waiting: 0, someday: 0 };

/**
 * Connected agents.
 *
 * BrainBuddy owns dispatch and honest reporting; the user owns the agent. So the
 * page states what BrainBuddy actually observed (the last test, the last
 * contact, the disclosed capabilities) and never implies a connection works
 * before the server says `ready_for_handoff`.
 */
export function AgentSettingsPage(): JSX.Element {
  const countsQuery = useTaskList({ state: "next", limit: 1 });
  const projectsQuery = useProjects();
  const tagsQuery = useTags();
  const connectionsQuery = useAgentConnections(true);
  const [browserOnline, setBrowserOnline] = useState(() =>
    typeof navigator === "undefined" ? true : navigator.onLine
  );

  useEffect(() => {
    const online = () => setBrowserOnline(true);
    const offline = () => setBrowserOnline(false);
    window.addEventListener("online", online);
    window.addEventListener("offline", offline);
    return () => {
      window.removeEventListener("online", online);
      window.removeEventListener("offline", offline);
    };
  }, []);

  const connectionTransportOnline =
    browserOnline && (!connectionsQuery.isError || connectionsQuery.error instanceof ApiError);

  return (
    <AppShell
      counts={countsQuery.data?.counts_by_state ?? emptyCounts}
      projects={projectsQuery.data ?? []}
      tags={tagsQuery.data ?? []}
    >
      <div className="mx-auto flex max-w-[680px] flex-col gap-5 pb-12">
        <header>
          <h1 className="text-title font-semibold text-slate-900">Connected agents</h1>
          <p className="mt-1 text-sm text-slate-500">
            BrainBuddy relays one task at a time to an agent you operate. You own its hosting,
            tools, credentials, cost, and output quality. BrainBuddy sends only what you review and
            shows only what the agent reports back.
          </p>
        </header>
        <AddConnectionSection />
        <SectionCard
          title="Your agents"
          description="Status and capabilities come from the last connection test, not from BrainBuddy."
        >
          {connectionsQuery.isError ? (
            <Feedback error={getErrorMessage(connectionsQuery.error)} success={null} />
          ) : connectionsQuery.isLoading ? (
            <p className="text-sm text-slate-500">Loading connections…</p>
          ) : connectionsQuery.data?.length ? (
            <div className="flex flex-col gap-4">
              {connectionsQuery.data.map((connection) => (
                <ConnectionCard
                  key={connection.id}
                  connection={connection}
                  online={connectionTransportOnline}
                />
              ))}
            </div>
          ) : (
            <p className="text-sm text-slate-500">
              No agents connected yet. Add one above, then test it before handing over a task.
            </p>
          )}
        </SectionCard>
      </div>
    </AppShell>
  );
}

function AddConnectionSection(): JSX.Element {
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [endpointUrl, setEndpointUrl] = useState("");
  const [authHeaderName, setAuthHeaderName] = useState("Authorization");
  const [credential, setCredential] = useState("");
  const [currentPassword, setCurrentPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  // Held in component state on purpose: navigating away unmounts this and the
  // secret is gone for good, because the server will never return it again.
  const [signingSecret, setSigningSecret] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: () =>
      apiClient.createAgentConnection(
        {
          name,
          endpoint_url: endpointUrl,
          auth_header_name: authHeaderName,
          credential,
          current_password: currentPassword
        },
        newIdempotencyKey("agent-connection-create")
      ),
    onSuccess: (created) => {
      setError(null);
      setSigningSecret(created.inbound_signing_secret);
      setName("");
      setEndpointUrl("");
      setAuthHeaderName("Authorization");
      setCredential("");
      setCurrentPassword("");
      void queryClient.invalidateQueries({ queryKey: agentKeys.connections() });
    },
    onError: (caught: unknown) => {
      setSigningSecret(null);
      setError(getErrorMessage(caught));
    }
  });

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault();
    mutation.mutate();
  };

  return (
    <SectionCard
      title="Add an agent"
      description="BrainBuddy stores the credential sealed and never shows it again. Adding an agent re-checks your password."
    >
      <form aria-label="Add an agent" className="flex flex-col gap-3" onSubmit={handleSubmit}>
        <Field label="Agent name" name="agent_name" type="text" value={name} onChange={setName} />
        <Field
          label="Endpoint URL"
          name="endpoint_url"
          type="url"
          value={endpointUrl}
          onChange={setEndpointUrl}
          placeholder="https://agent.example.com/brain-buddy"
          hint="The deployment decides which destinations are allowed. Loopback, link-local, metadata and private-network addresses are refused unless your deployment enables them."
        />
        <Field
          label="Auth header name"
          name="auth_header_name"
          type="text"
          value={authHeaderName}
          onChange={setAuthHeaderName}
          hint="The header BrainBuddy puts the credential in when it calls your agent."
        />
        <Field
          label="Credential"
          name="agent_credential"
          type="password"
          value={credential}
          onChange={setCredential}
          autoComplete="off"
          hint="Sent to your agent on every request. It is never displayed again after saving."
        />
        <Field
          label="Current password"
          name="current_password"
          type="password"
          value={currentPassword}
          onChange={setCurrentPassword}
          autoComplete="current-password"
        />
        <Feedback error={error} success={null} />
        <div>
          <Button type="submit" variant="primary" size="md" isLoading={mutation.isPending}>
            Add agent
          </Button>
        </div>
      </form>
      {signingSecret ? (
        <SigningSecretPanel secret={signingSecret} onDismiss={() => setSigningSecret(null)} />
      ) : null}
    </SectionCard>
  );
}

/** The one and only render of the inbound signing secret. */
function SigningSecretPanel({
  secret,
  onDismiss,
  title = "Inbound signing secret",
  lead
}: {
  secret: string;
  onDismiss: () => void;
  title?: string;
  lead?: string;
}): JSX.Element {
  const titleId = useId();
  return (
    <section
      aria-labelledby={titleId}
      className="mt-4 flex flex-col gap-2 rounded-xl border border-needs-you-border bg-needs-you-bg p-4"
    >
      <h3 id={titleId} className="text-sm font-semibold text-needs-you-fg">
        {title}
      </h3>
      <p className="text-sm text-needs-you-fg">
        {lead ??
          "Copy this now — BrainBuddy will never show it again. Configure your agent to sign every report it sends back with this secret, or BrainBuddy will reject its events."}
      </p>
      <code className="break-all rounded-md border border-needs-you-border bg-white px-3 py-2 font-mono text-sm text-slate-900">
        {secret}
      </code>
      <div>
        <Button type="button" variant="secondary" size="sm" onClick={onDismiss}>
          I&apos;ve saved it
        </Button>
      </div>
    </section>
  );
}

function ConnectionCard({
  connection,
  online
}: {
  connection: AgentConnectionResponse;
  online: boolean;
}): JSX.Element {
  const titleId = useId();
  const queryClient = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [disconnectOpen, setDisconnectOpen] = useState(false);
  const [signingSecretOpen, setSigningSecretOpen] = useState(false);
  // Component state only, exactly like the create response: it is never written
  // to the query cache or storage, and unmounting this card loses it for good.
  const [replacementSecret, setReplacementSecret] = useState<string | null>(null);
  // Held on the card, not in the dialog: closing and reopening after a failure
  // the user cannot interpret is still the *same* attempt, so it must not mint
  // a second key and rotate twice.
  const signingSecretKey = useIntentKey("agent-signing-secret");

  const refresh = (message: string) => {
    setError(null);
    setSuccess(message);
    void queryClient.invalidateQueries({ queryKey: agentKeys.connections() });
  };

  const testMutation = useMutation({
    mutationFn: () => apiClient.testAgentConnection(connection.id),
    onSuccess: (tested) => refresh(`Test finished: ${connectionStatusLabel(tested).toLowerCase()}.`),
    onError: (caught: unknown) => {
      setSuccess(null);
      setError(getErrorMessage(caught));
    }
  });

  const isDisconnected = connection.status === "disconnected";

  return (
    <article
      aria-labelledby={titleId}
      className="flex flex-col gap-3 rounded-xl border border-slate-200 p-4"
    >
      <div className="flex flex-wrap items-start gap-2">
        <div className="min-w-0 flex-1">
          <h3 id={titleId} className="text-sm font-semibold text-slate-900">
            {connection.name}
          </h3>
          <p className="mt-0.5 break-all text-xs text-slate-500">{connection.endpoint_url}</p>
        </div>
        <StatusBadge connection={connection} />
      </div>

      <p className="text-sm text-slate-600">{connectionStatusDetail(connection)}</p>
      <p className={`text-xs font-medium ${connection.ready_for_handoff ? "text-ai-fg" : "text-needs-you-fg"}`}>
        {connection.ready_for_handoff
          ? "Ready to receive a hand-off."
          : "Cannot receive a hand-off yet."}
      </p>
      {connection.last_test_error_code ? (
        <p className="text-xs text-slate-500">Reported error code: {connection.last_test_error_code}</p>
      ) : null}

      <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs text-slate-500">
        <dt className="sr-only">Credential header</dt>
        <dd className="col-span-2">Credential header: {connection.auth_header_name}</dd>
        <dt className="sr-only">Last contact</dt>
        <dd className="col-span-2">Last contact: {formatTimestamp(connection.last_contact_at)}</dd>
        <dt className="sr-only">Last tested</dt>
        <dd className="col-span-2">Last tested: {formatTimestamp(connection.last_tested_at)}</dd>
        <dt className="sr-only">Staleness threshold</dt>
        <dd className="col-span-2">
          Goes stale after {formatDuration(connection.stale_after_seconds)} without contact
        </dd>
      </dl>

      <div className="flex flex-col gap-1.5">
        <p className="text-[10px] font-semibold uppercase tracking-[0.06em] text-slate-500">
          What this agent can do
        </p>
        <ul className="flex flex-col gap-1 text-xs text-slate-600">
          {capabilityDisclosure(connection.capabilities).map((capability) => (
            <li key={capability.label} className="flex items-center justify-between gap-3">
              <span>{capability.label}</span>
              <span className={capability.supported ? "text-ai-fg" : "text-slate-400"}>
                {capability.supported ? "Supported" : "Not supported"}
              </span>
            </li>
          ))}
        </ul>
        {connection.status === "untested" ? (
          <p className="text-xs text-slate-500">
            Capabilities are only known after a successful test.
          </p>
        ) : null}
      </div>

      <Feedback error={error} success={success} />

      <div className="flex flex-wrap gap-2">
        <Button
          type="button"
          variant="secondary"
          size="sm"
          isLoading={testMutation.isPending}
          disabled={isDisconnected}
          onClick={() => testMutation.mutate()}
        >
          Test connection
        </Button>
        <Button
          type="button"
          variant="secondary"
          size="sm"
          disabled={isDisconnected || !online}
          onClick={() => setSigningSecretOpen(true)}
        >
          Replace signing secret…
        </Button>
        <Button
          type="button"
          variant="danger"
          size="sm"
          disabled={isDisconnected}
          onClick={() => setDisconnectOpen(true)}
        >
          Disconnect…
        </Button>
      </div>

      {replacementSecret ? (
        <SigningSecretPanel
          secret={replacementSecret}
          title="Replacement signing secret"
          lead="Copy this now — BrainBuddy will never show it again. The previous signing secret has already stopped verifying reports, so configure your agent with this one before it reports again."
          onDismiss={() => setReplacementSecret(null)}
        />
      ) : null}

      {isDisconnected ? null : (
        <RotateCredentialForm connection={connection} onDone={refresh} onFailed={setError} />
      )}

      {signingSecretOpen && online ? (
        <ReplaceSigningSecretDialog
          connection={connection}
          intentKey={signingSecretKey}
          onClose={() => setSigningSecretOpen(false)}
          onReplaced={(secret) => {
            setSigningSecretOpen(false);
            setReplacementSecret(secret);
            refresh("Signing secret replaced. The previous one no longer verifies reports.");
          }}
        />
      ) : null}

      {disconnectOpen ? (
        <DisconnectDialog
          connection={connection}
          onClose={() => setDisconnectOpen(false)}
          onDisconnected={() => {
            setDisconnectOpen(false);
            refresh("Agent disconnected. Its credential was destroyed.");
          }}
        />
      ) : null}
    </article>
  );
}

function StatusBadge({ connection }: { connection: AgentConnectionResponse }): JSX.Element {
  const label = connectionStatusLabel(connection);
  const tone =
    label === "Tested ready"
      ? "border-ai-border bg-ai-bg text-ai-fg"
      : label === "Stale" || label === "Not tested"
        ? "border-needs-you-border bg-needs-you-bg text-needs-you-fg"
        : label === "Disconnected"
          ? "border-slate-200 bg-surface-sunken text-slate-600"
          : "border-rose-200 bg-rose-50 text-rose-700";
  return (
    <span
      className={`inline-flex shrink-0 items-center rounded-full border px-2 py-[2px] text-[11px] font-medium ${tone}`}
    >
      {label}
    </span>
  );
}

function RotateCredentialForm({
  connection,
  onDone,
  onFailed
}: {
  connection: AgentConnectionResponse;
  onDone: (message: string) => void;
  onFailed: (message: string) => void;
}): JSX.Element {
  const [credential, setCredential] = useState("");
  const [currentPassword, setCurrentPassword] = useState("");

  const mutation = useMutation({
    mutationFn: () =>
      apiClient.rotateAgentCredential(
        connection.id,
        {
          credential,
          current_password: currentPassword,
          expected_revision: connection.revision
        },
        newIdempotencyKey("agent-credential-rotate")
      ),
    onSuccess: () => {
      setCredential("");
      setCurrentPassword("");
      onDone("Credential replaced. Test the connection again to confirm the agent accepts it.");
    },
    onError: (caught: unknown) => onFailed(getErrorMessage(caught))
  });

  return (
    <form
      className="flex flex-col gap-2 border-t border-slate-200 pt-3"
      onSubmit={(event) => {
        event.preventDefault();
        mutation.mutate();
      }}
    >
      <p className="text-[10px] font-semibold uppercase tracking-[0.06em] text-slate-500">
        Replace the credential
      </p>
      <Field
        label="New credential"
        name={`new_credential_${connection.id}`}
        type="password"
        value={credential}
        onChange={setCredential}
        autoComplete="off"
      />
      <Field
        label="Current password"
        name={`rotate_password_${connection.id}`}
        type="password"
        value={currentPassword}
        onChange={setCurrentPassword}
        autoComplete="current-password"
      />
      <div>
        <Button type="submit" variant="secondary" size="sm" isLoading={mutation.isPending}>
          Replace credential
        </Button>
      </div>
    </form>
  );
}

/**
 * The only way back from a lost signing secret.
 *
 * Guarded like registration because it is the same act — issuing credential
 * material — and phrased so the user cannot mistake it for the outbound
 * credential: this replaces what their agent signs *reports* with, and the old
 * one dies immediately rather than at some later cutover.
 */
function ReplaceSigningSecretDialog({
  connection,
  intentKey,
  onClose,
  onReplaced
}: {
  connection: AgentConnectionResponse;
  intentKey: IntentKey;
  onClose: () => void;
  onReplaced: (secret: string) => void;
}): JSX.Element {
  const titleId = useId();
  const [currentPassword, setCurrentPassword] = useState("");
  const [error, setError] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: () =>
      apiClient.rotateAgentSigningSecret(
        connection.id,
        { current_password: currentPassword, expected_revision: connection.revision },
        // Same key on every retry of this attempt: a failure the client cannot
        // interpret may still have rotated, and a fresh key would rotate again
        // and strand the secret the first attempt issued.
        intentKey.current(`${connection.id}:${connection.revision}`)
      ),
    onSuccess: (replaced) => {
      intentKey.settle();
      setCurrentPassword("");
      onReplaced(replaced.inbound_signing_secret);
    },
    onError: (caught: unknown) => setError(getErrorMessage(caught))
  });

  return (
    <Overlay labelledBy={titleId} onClose={onClose} size="narrow">
      <OverlayHeader
        titleId={titleId}
        eyebrow="Signing secret"
        title={`Replace ${connection.name}'s signing secret?`}
        onClose={onClose}
      />
      <form
        className="flex flex-col gap-4 px-5 py-5 sm:px-6"
        onSubmit={(event) => {
          event.preventDefault();
          setError(null);
          mutation.mutate();
        }}
      >
        <ul className="list-disc space-y-1 pl-5 text-sm text-slate-600">
          <li>
            This is the secret your agent signs its reports with — not the credential BrainBuddy
            sends to your agent. Replacing one does not change the other.
          </li>
          <li>
            The current signing secret stops verifying reports the moment the replacement is
            issued, so a running agent&apos;s events will be rejected until you configure the new
            one.
          </li>
          <li>The replacement is shown once, here, and BrainBuddy cannot show it again.</li>
        </ul>
        <Field
          label="Confirm with your password"
          name={`signing_secret_password_${connection.id}`}
          type="password"
          value={currentPassword}
          onChange={setCurrentPassword}
          autoComplete="current-password"
        />
        <Feedback error={error} success={null} />
        <div className="flex justify-end gap-2">
          <Button type="button" variant="secondary" size="md" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" variant="primary" size="md" isLoading={mutation.isPending}>
            Replace signing secret
          </Button>
        </div>
      </form>
    </Overlay>
  );
}

function DisconnectDialog({
  connection,
  onClose,
  onDisconnected
}: {
  connection: AgentConnectionResponse;
  onClose: () => void;
  onDisconnected: () => void;
}): JSX.Element {
  const titleId = useId();
  const [currentPassword, setCurrentPassword] = useState("");
  const [error, setError] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: () =>
      apiClient.disconnectAgentConnection(
        connection.id,
        { current_password: currentPassword, expected_revision: connection.revision },
        newIdempotencyKey("agent-disconnect")
      ),
    onSuccess: onDisconnected,
    onError: (caught: unknown) => setError(getErrorMessage(caught))
  });

  return (
    <Overlay labelledBy={titleId} onClose={onClose} size="narrow">
      <OverlayHeader
        titleId={titleId}
        eyebrow="Disconnect"
        title={`Disconnect ${connection.name}?`}
        onClose={onClose}
      />
      <form
        className="flex flex-col gap-4 px-5 py-5 sm:px-6"
        onSubmit={(event) => {
          event.preventDefault();
          mutation.mutate();
        }}
      >
        <ul className="list-disc space-y-1 pl-5 text-sm text-slate-600">
          <li>
            Disconnecting does not cancel work this agent has already accepted. If you want it
            stopped, request cancellation first and wait for the agent to confirm it.
          </li>
          <li>
            The stored credential is destroyed. New hand-offs and replies through this agent are
            blocked, and later reports signed with it are rejected.
          </li>
          <li>
            Runs already attached to your tasks stay visible until they expire under the retention
            policy.
          </li>
        </ul>
        <Field
          label="Confirm with your password"
          name="disconnect_password"
          type="password"
          value={currentPassword}
          onChange={setCurrentPassword}
          autoComplete="current-password"
        />
        <Feedback error={error} success={null} />
        <div className="flex justify-end gap-2">
          <Button type="button" variant="secondary" size="md" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" variant="danger" size="md" isLoading={mutation.isPending}>
            Disconnect agent
          </Button>
        </div>
      </form>
    </Overlay>
  );
}
