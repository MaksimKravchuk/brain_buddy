import { useId, useRef, useState, type FormEvent } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { useAgentConnections, useAgentKeys } from "../../api/agentHooks";
import { useRelayMutation, useRelayOnline } from "../../api/agentLifecycle";
import type { AgentConnectionResponse } from "../../api/agentTypes";
import { ApiError, apiClient } from "../../api/client";
import { useProjects, useTags, useTaskList } from "../../api/taskHooks";
import type { TaskCounts } from "../../api/taskTypes";
import { AppShell } from "../../components/shell/AppShell";
import { Button } from "../../components/ui/Button";
import { Overlay, OverlayHeader } from "../../components/ui/Overlay";
import { Feedback, Field, SectionCard } from "../../components/ui/SettingsSection";
import { getErrorMessage } from "../../utils/error";
import { definitivelyRejected, useIntentKey, type IntentKey } from "../../utils/idempotency";
import type { AgentAuthScheme } from "../../api/agentTypes";
import {
  authSchemeLabel,
  capabilityDisclosure,
  connectionStatusDetail,
  connectionStatusLabel,
  formatDuration,
  formatTimestamp,
  rateLimitRetryCopy
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
export function AgentSettingsPage({ rolloutEnabled }: { rolloutEnabled: boolean }): React.JSX.Element {
  const countsQuery = useTaskList({ state: "next", limit: 1 });
  const projectsQuery = useProjects();
  const tagsQuery = useTags();
  const connectionsQuery = useAgentConnections(true);
  const browserOnline = useRelayOnline();
  const [addOpen, setAddOpen] = useState(false);
  const [addNotice, setAddNotice] = useState<string | null>(null);
  const [hiddenConnectionIds, setHiddenConnectionIds] = useState<Set<string>>(() => new Set());
  const addTrigger = useRef<HTMLButtonElement | null>(null);

  const connectionTransportOnline =
    browserOnline && (!connectionsQuery.isError || connectionsQuery.error instanceof ApiError);

  return (
    <AppShell
      counts={countsQuery.data?.counts_by_state ?? emptyCounts}
      projects={projectsQuery.data ?? []}
      tags={tagsQuery.data ?? []}
    >
      <div className="mx-auto flex max-w-[1120px] flex-col gap-5 pb-12">
        <header className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
          <div className="max-w-[720px]">
            <h1 className="text-title font-semibold text-slate-900">Connected agents</h1>
            <p className="mt-1 text-sm text-slate-500">
              Manage the agents BrainBuddy can hand reviewed work to. Test a connection before
              using it, and keep credentials with the agent you operate.
            </p>
          </div>
          {rolloutEnabled ? (
            <Button
              ref={addTrigger}
              type="button"
              variant="primary"
              size="md"
              className="shrink-0 self-start"
              onClick={() => setAddOpen(true)}
            >
              Add new agent
            </Button>
          ) : null}
        </header>
        {!rolloutEnabled ? (
          <section className="rounded-xl border border-needs-you-border bg-needs-you-bg p-4 text-sm text-needs-you-fg">
            The external-agent relay rollout is off. Existing connections remain visible and may be
            safely disconnected, and runs already handed over keep reporting, but adding, editing,
            testing, or replacing credentials is unavailable.
          </section>
        ) : null}
        <Feedback error={null} success={addNotice} />
        <SectionCard
          title="Your agents"
          description="Saved connection details and the latest result BrainBuddy observed."
        >
          {connectionsQuery.isError ? (
            <Feedback error={getErrorMessage(connectionsQuery.error)} success={null} />
          ) : connectionsQuery.isLoading ? (
            <p className="text-sm text-slate-500">Loading connections…</p>
          ) : connectionsQuery.data?.some((item) => !hiddenConnectionIds.has(item.id)) ? (
            <AgentRegistryTable
              connections={connectionsQuery.data.filter((item) => !hiddenConnectionIds.has(item.id))}
              online={connectionTransportOnline}
              mutationsEnabled={rolloutEnabled}
              onDeleted={(connectionId) => {
                setHiddenConnectionIds((current) => new Set(current).add(connectionId));
              }}
            />
          ) : (
            <p className="text-sm text-slate-500">
              No agents connected yet. Add one, then test it before handing over a task.
            </p>
          )}
        </SectionCard>
        {addOpen ? (
          <AddConnectionModal
            onClose={() => {
              setAddOpen(false);
              addTrigger.current?.focus();
            }}
            onAdded={(name) => {
              setAddNotice(`${name} was added. Test it before handing over a task.`);
              setAddOpen(false);
              addTrigger.current?.focus();
            }}
          />
        ) : null}
      </div>
    </AppShell>
  );
}

function AddConnectionModal({
  onClose,
  onAdded
}: {
  onClose: () => void;
  onAdded: (name: string) => void;
}): React.JSX.Element {
  const titleId = useId();
  const queryClient = useQueryClient();
  const keys = useAgentKeys();
  const online = useRelayOnline();
  const [name, setName] = useState("");
  const [agentAddress, setAgentAddress] = useState("");
  const [authScheme, setAuthScheme] = useState<AgentAuthScheme>("bearer");
  const [credential, setCredential] = useState("");
  const [currentPassword, setCurrentPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [ambiguous, setAmbiguous] = useState(false);
  const createKey = useIntentKey("agent-connection-create");

  const mutation = useRelayMutation({
    mutationKey: keys.mutation("connection-create"),
    mutationFn: () => {
      return apiClient.createAgentConnection(
        {
          name,
          agent_address: agentAddress,
          auth_scheme: authScheme,
          credential,
          current_password: currentPassword
        },
        createKey.current(
          JSON.stringify([name, agentAddress, authScheme, credential, currentPassword])
        )
      );
    },
    onSuccess: (created) => {
      createKey.settle();
      setAmbiguous(false);
      setError(null);
      setName("");
      setAgentAddress("");
      setAuthScheme("bearer");
      setCredential("");
      setCurrentPassword("");
      void queryClient.invalidateQueries({ queryKey: keys.connections() });
      onAdded(created.name);
    },
    onError: (caught: unknown) => {
      if (definitivelyRejected(caught)) {
        createKey.settle();
      }
      setAmbiguous(!definitivelyRejected(caught));
      setError(getErrorMessage(caught));
    }
  });

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault();
    mutation.mutate();
  };

  return (
    <Overlay labelledBy={titleId} size="narrow" onClose={mutation.isPending || ambiguous ? undefined : onClose}>
      <OverlayHeader
        titleId={titleId}
        eyebrow="Connected agents"
        title="Add new agent"
        onClose={mutation.isPending || ambiguous ? undefined : onClose}
      />
      <form aria-label="Add an agent" className="flex flex-col gap-3 overflow-y-auto px-5 py-5 sm:px-6" onSubmit={handleSubmit}>
        <p className="text-sm text-slate-500">
          BrainBuddy stores the credential sealed and never shows it again. Adding an agent re-checks your password.
        </p>
        <Field label="Agent name" name="agent_name" type="text" value={name} onChange={setName} />
        <Field
          label="Agent address"
          name="agent_address"
          type="url"
          value={agentAddress}
          onChange={setAgentAddress}
          placeholder="https://agent.example.com"
          hint="BrainBuddy fetches the agent card from this address's standard well-known location. The deployment decides which destinations are allowed. Loopback, link-local, metadata and private-network addresses are refused unless your deployment enables them."
        />
        <AuthSchemeChoice value={authScheme} onChange={setAuthScheme} />
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
        <div className="flex justify-end gap-2 border-t border-slate-100 pt-4">
          <Button
            type="button"
            variant="secondary"
            size="md"
            onClick={() => {
              createKey.settle();
              setCredential("");
              setCurrentPassword("");
              onClose();
            }}
            disabled={mutation.isPending}
          >
            {ambiguous ? "Discard and close" : "Cancel"}
          </Button>
          <Button type="submit" variant="primary" size="md" isLoading={mutation.isPending} disabled={!online}>
            Add agent
          </Button>
        </div>
      </form>
    </Overlay>
  );
}

/**
 * The two credential schemes, and the header name the card decides (D-01-S08/S09).
 *
 * The header field is read-only on purpose. It is discovery output, not user
 * input: a typed value could point the credential at a header the agent never
 * asked for, and the owner has no way to know which one it wants until the card
 * has been read.
 */
function AuthSchemeChoice({
  value,
  onChange,
  headerName = null
}: {
  value: AgentAuthScheme;
  onChange: (scheme: AgentAuthScheme) => void;
  headerName?: string | null;
}): React.JSX.Element {
  const groupId = useId();
  return (
    <fieldset className="flex flex-col gap-2" aria-describedby={`${groupId}-hint`}>
      <legend className="text-xs font-medium text-slate-700">Credential scheme</legend>
      <div className="flex flex-wrap gap-4">
        <label className="flex items-center gap-2 text-sm text-slate-700">
          <input
            type="radio"
            name={`${groupId}-scheme`}
            value="bearer"
            checked={value === "bearer"}
            onChange={() => onChange("bearer")}
          />
          Bearer token
        </label>
        <label className="flex items-center gap-2 text-sm text-slate-700">
          <input
            type="radio"
            name={`${groupId}-scheme`}
            value="api_key"
            checked={value === "api_key"}
            onChange={() => onChange("api_key")}
          />
          API key
        </label>
      </div>
      {value === "api_key" ? (
        <label className="flex flex-col gap-1 text-xs text-slate-700">
          Header name
          <input
            type="text"
            readOnly
            aria-readonly="true"
            value={headerName ?? "Read from the agent card when you test"}
            className="rounded-md border border-slate-200 bg-surface-sunken px-3 py-2 text-sm text-slate-600"
          />
          <span className="text-slate-500">
            Read from the agent card after discovery. You do not type it.
          </span>
        </label>
      ) : null}
      <p id={`${groupId}-hint`} className="text-xs text-slate-500">
        BrainBuddy supports a bearer token or an API key the card names, and nothing else.
      </p>
    </fieldset>
  );
}

function AgentRegistryTable({
  connections,
  online,
  mutationsEnabled,
  onDeleted
}: {
  connections: AgentConnectionResponse[];
  online: boolean;
  mutationsEnabled: boolean;
  onDeleted: (connectionId: string) => void;
}): React.JSX.Element {
  return (
    <div className="min-w-0">
      <table aria-label="Your agents" className="block w-full border-separate border-spacing-0 md:table">
        <thead className="sr-only md:not-sr-only md:table-header-group">
          <tr>
            {['Agent', 'Version', 'Protocol', 'Interface', 'Status', 'Actions'].map((heading) => (
              <th
                key={heading}
                scope="col"
                className="border-b border-slate-200 px-3 py-2 text-left text-[11px] font-semibold uppercase tracking-[0.06em] text-slate-500 first:pl-0 last:pr-0"
              >
                {heading}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="block space-y-3 md:table-row-group md:space-y-0">
          {connections.map((connection) => (
            <ConnectionRow
              key={connection.id}
              connection={connection}
              online={online}
              mutationsEnabled={mutationsEnabled}
              onDeleted={() => onDeleted(connection.id)}
            />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function mobileLabel(label: string): React.JSX.Element {
  return (
    <span className="text-[10px] font-semibold uppercase tracking-[0.06em] text-slate-400 md:hidden">
      {label}
    </span>
  );
}

function safeAgentAddress(address: string): boolean {
  try {
    const parsed = new URL(address);
    return parsed.protocol === "https:" || parsed.protocol === "http:";
  } catch {
    return false;
  }
}

function ConnectionRow({
  connection,
  online,
  mutationsEnabled,
  onDeleted
}: {
  connection: AgentConnectionResponse;
  online: boolean;
  mutationsEnabled: boolean;
  onDeleted: () => void;
}): React.JSX.Element {
  const editTitleId = useId();
  const queryClient = useQueryClient();
  const keys = useAgentKeys();
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [disconnectOpen, setDisconnectOpen] = useState(false);
  const [editing, setEditing] = useState(false);
  const disconnectKey = useIntentKey(`agent-disconnect-${connection.id}`);
  // Where focus goes when the confirmation closes: back to the control that
  // opened it, so a keyboard user is never dropped at the top of the page
  // wondering what happened to their decision.
  const disconnectTrigger = useRef<HTMLButtonElement | null>(null);
  const editTrigger = useRef<HTMLButtonElement | null>(null);
  const closeDisconnect = () => {
    setDisconnectOpen(false);
    disconnectTrigger.current?.focus();
  };

  const refresh = (message: string) => {
    setError(null);
    setSuccess(message);
    void queryClient.invalidateQueries({ queryKey: keys.connections() });
  };

  const testMutation = useRelayMutation({
    mutationKey: keys.mutation("connection-test", connection.id),
    mutationFn: () => {
      return apiClient.testAgentConnection(connection.id);
    },
    onSuccess: (tested) => refresh(`Test finished: ${connectionStatusLabel(tested).toLowerCase()}.`),
    onError: (caught: unknown) => {
      setSuccess(null);
      setError(getErrorMessage(caught));
    }
  });

  const isDisconnected = connection.status === "disconnected";
  const version = connection.card?.version ?? "Not tested";
  const protocol = connection.card?.protocol_version ?? "Not tested";
  const interfaceUrl = connection.card?.interface_url ?? "Not tested";

  return (
    <>
      <tr aria-label={connection.name}>
        <td colSpan={6} className="border-b border-slate-100 p-0">
        <article
          aria-label={connection.name}
          className="grid grid-cols-1 gap-3 rounded-xl border border-slate-200 p-4 md:grid-cols-[minmax(160px,1.25fr)_minmax(70px,.55fr)_minmax(70px,.55fr)_minmax(150px,1fr)_minmax(150px,1fr)_auto] md:rounded-none md:border-0 md:px-0 md:py-4"
        >
        <div className="min-w-0 align-top md:px-3 md:pl-0">
          {mobileLabel("Agent")}
          <strong className="mt-0.5 block text-sm font-semibold text-slate-900">{connection.name}</strong>
          {safeAgentAddress(connection.agent_address) ? (
            <a
              className="mt-0.5 block break-all text-xs text-sky-700 underline decoration-sky-200 underline-offset-2 hover:text-sky-900"
              href={connection.agent_address}
              target="_blank"
              rel="noopener noreferrer"
            >
              {connection.agent_address}
            </a>
          ) : (
            <span className="mt-0.5 block break-all text-xs text-slate-500">{connection.agent_address}</span>
          )}
        </div>
        <div className="min-w-0 align-top text-sm text-slate-700 md:px-3">
          {mobileLabel("Version")}
          <span className="mt-0.5 block break-words">{version}</span>
        </div>
        <div className="min-w-0 align-top text-sm text-slate-700 md:px-3">
          {mobileLabel("Protocol")}
          <span className="mt-0.5 block break-words">{protocol}</span>
        </div>
        <div className="min-w-0 align-top text-xs text-slate-600 md:max-w-[220px] md:px-3">
          {mobileLabel("Interface")}
          <span className="mt-0.5 block break-all font-mono" title={interfaceUrl}>{interfaceUrl}</span>
        </div>
        <div className="min-w-0 align-top md:px-3">
          {mobileLabel("Status")}
          <div className="mt-1 flex flex-col items-start gap-1 md:mt-0">
            <StatusBadge connection={connection} />
            <span className="text-xs text-slate-500">{connectionStatusDetail(connection)}</span>
          </div>
          <Feedback error={error} success={success} />
        </div>
        <div className="align-top md:px-3 md:pr-0">
          {mobileLabel("Actions")}
          <div className="mt-1 flex flex-wrap gap-2 md:mt-0 md:justify-end">
            {mutationsEnabled ? (
              <Button
                type="button"
                variant="secondary"
                size="sm"
                aria-label={`Test ${connection.name}`}
                isLoading={testMutation.isPending}
                disabled={isDisconnected || !online}
                onClick={() => testMutation.mutate()}
              >
                Test
              </Button>
            ) : null}
            <Button
              ref={editTrigger}
              type="button"
              variant="secondary"
              size="sm"
              aria-label={`Edit ${connection.name}`}
              disabled={isDisconnected}
              onClick={() => setEditing(true)}
            >
              Edit
            </Button>
            <Button
              type="button"
              ref={disconnectTrigger}
              variant="danger"
              size="sm"
              aria-label={`Delete ${connection.name}`}
              disabled={isDisconnected || !online}
              onClick={() => setDisconnectOpen(true)}
            >
              Delete
            </Button>
          </div>
        </div>

        <details className="md:col-span-6 rounded-lg border border-slate-100 bg-surface-sunken px-3 py-2">
          <summary className="cursor-pointer text-xs font-medium text-slate-600">Connection details</summary>
          <ConnectionDetails connection={connection} className="mt-3" />
        </details>

      {editing ? (
        <Overlay
          labelledBy={editTitleId}
          size="wide"
          onClose={() => {
            setEditing(false);
            editTrigger.current?.focus();
          }}
        >
          <OverlayHeader
            titleId={editTitleId}
            eyebrow="Connected agents"
            title={`Edit ${connection.name}`}
            onClose={() => {
              setEditing(false);
              editTrigger.current?.focus();
            }}
          />
          <div className="flex flex-col gap-4 overflow-y-auto px-5 py-5 sm:px-6">
            <ConnectionDetails connection={connection} />
            {mutationsEnabled ? (
              <>
                <UpdateConnectionForm
                  connection={connection}
                  online={online}
                  onDone={(message) => {
                    setEditing(false);
                    refresh(message);
                    editTrigger.current?.focus();
                  }}
                />
                <RotateCredentialForm connection={connection} online={online} onDone={refresh} onFailed={setError} />
              </>
            ) : (
              <p className="rounded-lg border border-needs-you-border bg-needs-you-bg p-3 text-sm text-needs-you-fg">
                Editing and credential replacement are unavailable while rollout is off.
              </p>
            )}
          </div>
        </Overlay>
      ) : null}

      {disconnectOpen ? (
        <DisconnectDialog
          connection={connection}
          intentKey={disconnectKey}
          online={online}
          onClose={closeDisconnect}
          onDisconnected={() => {
            setDisconnectOpen(false);
            void queryClient.invalidateQueries({ queryKey: keys.connections() });
            onDeleted();
          }}
        />
      ) : null}
        </article>
        </td>
      </tr>
    </>
  );
}

function ConnectionDetails({
  connection,
  className = ""
}: {
  connection: AgentConnectionResponse;
  className?: string;
}): React.JSX.Element {
  return (
    <div className={`flex flex-col gap-3 ${className}`}>
      <p className={`text-xs font-medium ${connection.ready_for_handoff ? "text-ai-fg" : "text-needs-you-fg"}`}>
        {connection.ready_for_handoff ? "Ready to receive a hand-off." : "Cannot receive a hand-off yet."}
      </p>
      {connection.last_test_error_code === "a2a_rate_limited" ? (
        <p className="text-xs text-needs-you-fg">{rateLimitRetryCopy(connection)}</p>
      ) : connection.last_test_error_code === "legacy_invalid_auth_header_requires_reconfiguration" ? (
        <p className="text-xs text-needs-you-fg">Enter a replacement credential, then test the connection.</p>
      ) : null}
      {connection.agent_changed ? <AgentChangedComparison connection={connection} /> : null}
      <DiscoveryResult connection={connection} />
      {connection.tier_disclosure ? <TierDisclosure connection={connection} /> : null}
      <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs text-slate-500">
        <dt>Credential</dt><dd>{authSchemeLabel(connection)}</dd>
        <dt>Last contact</dt><dd>{formatTimestamp(connection.last_contact_at)}</dd>
        <dt>Last tested</dt><dd>{formatTimestamp(connection.last_tested_at)}</dd>
        <dt>Staleness threshold</dt><dd>Goes stale after {formatDuration(connection.stale_after_seconds)} without contact</dd>
      </dl>
      <section aria-label="Capabilities" className="flex flex-col gap-1.5">
        <h3 className="text-xs font-semibold text-slate-700">What this agent can do</h3>
        <ul className="grid gap-1 text-xs text-slate-600 sm:grid-cols-2">
          {capabilityDisclosure(connection.capabilities).map((capability) => (
            <li key={capability.label} className="flex items-center justify-between gap-3 rounded-md bg-white px-3 py-2">
              <span>{capability.label}</span>
              <span className={capability.supported ? "text-ai-fg" : "text-slate-400"}>
                {capability.supported ? "Supported" : "Not supported"}
              </span>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}

/**
 * The tested destination beside the one the card now advertises (D-01-S20).
 *
 * Both are card text, so both render as plain text: making either navigable is
 * exactly the mistake the warning exists to prevent (AC-031).
 */
function AgentChangedComparison({
  connection
}: {
  connection: AgentConnectionResponse;
}): React.JSX.Element {
  const detail = connection.last_test_error_detail;
  const current = detail && "interface_url" in detail ? detail.interface_url : null;
  return (
    <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 rounded-lg border border-needs-you-border bg-needs-you-bg p-3 text-xs text-needs-you-fg">
      <dt>Tested interface</dt>
      <dd className="break-all font-mono">{connection.card?.interface_url ?? "Unknown"}</dd>
      <dt>Card now says</dt>
      <dd className="break-all font-mono">{current ?? "Unknown"}</dd>
    </dl>
  );
}

/**
 * What the agent's published card says about itself (D-01-S10/S11).
 *
 * Every value here is untrusted agent text and is rendered as plain text: no
 * anchor, no markup interpretation, no auto-linking, whatever scheme the agent
 * chose for its interface (FR-016, AC-031). `interface_url` in particular is
 * shown so the owner can see where their content would go — which is the reason
 * it must never become something a stray click can follow.
 */
function DiscoveryResult({
  connection
}: {
  connection: AgentConnectionResponse;
}): React.JSX.Element {
  const card = connection.card;
  return (
    <section aria-label="Discovery result" className="flex flex-col gap-1.5">
      <p className="text-[10px] font-semibold uppercase tracking-[0.06em] text-slate-500">
        Read from the agent card
      </p>
      <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs text-slate-600">
        <dt>Name</dt>
        <dd className="break-words">{card?.name ?? "Not stated"}</dd>
        <dt>Version</dt>
        <dd className="break-words">{card?.version ?? "Not stated"}</dd>
        <dt>Description</dt>
        <dd className="break-words">{card?.description ?? "Not stated"}</dd>
        <dt>Protocol version</dt>
        <dd className="break-words">{card?.protocol_version ?? "Not stated"}</dd>
        <dt>Interface</dt>
        <dd className="break-all font-mono">{card?.interface_url ?? "Not stated"}</dd>
      </dl>
      {card && card.skills.length > 0 ? (
        <ul aria-label="Skills" className="flex flex-wrap gap-1.5">
          {card.skills.map((skill, index) => (
            <li
              key={`${skill.id ?? "skill"}-${index}`}
              className="rounded-full border border-slate-200 px-2 py-[2px] text-[11px] text-slate-600"
            >
              {skill.name ?? skill.id ?? "Unnamed skill"}
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}

/**
 * The server-owned tier sentence, rendered verbatim (FR-014).
 *
 * The link to the published extension specification is the only navigable thing
 * on the row, and it is BrainBuddy's own address: it opens on an explicit click,
 * in a new context, and says so.
 */
function TierDisclosure({
  connection
}: {
  connection: AgentConnectionResponse;
}): React.JSX.Element {
  const guaranteed = connection.guarantee_tier === "guaranteed";
  return (
    <section
      aria-label="Guarantee"
      className={`flex flex-col gap-1 rounded-lg border p-3 text-xs ${
        guaranteed
          ? "border-ai-border bg-ai-bg text-ai-fg"
          : "border-needs-you-border bg-needs-you-bg text-needs-you-fg"
      }`}
    >
      <p>{connection.tier_disclosure}</p>
      {!guaranteed && connection.tier_disclosure_url ? (
        <p>
          <a
            className="underline"
            href={connection.tier_disclosure_url}
            target="_blank"
            rel="noopener noreferrer"
          >
            Read the single-start extension specification
          </a>{" "}
          <span className="text-slate-500">
            Opens the published specification outside BrainBuddy, so you can ask your
            agent&apos;s operator to declare it.
          </span>
        </p>
      ) : null}
      {connection.cancellation_disclosure ? (
        <p>{connection.cancellation_disclosure}</p>
      ) : null}
    </section>
  );
}

function StatusBadge({ connection }: { connection: AgentConnectionResponse }): React.JSX.Element {
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

function UpdateConnectionForm({
  connection,
  online,
  onDone
}: {
  connection: AgentConnectionResponse;
  online: boolean;
  onDone: (message: string) => void;
}): React.JSX.Element {
  const [name, setName] = useState(connection.name);
  const [agentAddress, setAgentAddress] = useState(connection.agent_address);
  const [authScheme, setAuthScheme] = useState<AgentAuthScheme>(connection.auth_scheme);
  const [currentPassword, setCurrentPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [ambiguous, setAmbiguous] = useState(false);
  const keys = useAgentKeys();
  const intentKey = useIntentKey(`agent-connection-update-${connection.id}`);
  // The exact request an ambiguous failure left in flight. It decides whether
  // the retry control renders, so it is state rather than a ref.
  const [frozen, setFrozen] = useState<{
    body: {
      name?: string;
      agent_address?: string;
      auth_scheme?: AgentAuthScheme;
      expected_revision: number;
      current_password?: string;
    };
    idempotencyKey: string;
  } | null>(null);
  // A scheme change is a scope change exactly as an address change is: the same
  // secret presented differently may reach a different agent (FR-004).
  const scopeChanged =
    agentAddress.trim() !== connection.agent_address || authScheme !== connection.auth_scheme;

  const mutation = useRelayMutation({
    mutationKey: keys.mutation("connection-update", connection.id),
    mutationFn: (input: NonNullable<typeof frozen>) =>
      apiClient.updateAgentConnection(connection.id, input.body, input.idempotencyKey),
    onSuccess: (_, input) => {
      intentKey.settle();
      setFrozen(null);
      setAmbiguous(false);
      onDone(
        input.body.agent_address || input.body.auth_scheme
          ? "Connection updated. Test it again before handing off new work."
          : "Connection name updated."
      );
    },
    onError: (caught: unknown) => {
      const definitive = definitivelyRejected(caught);
      if (definitive) {
        intentKey.settle();
        setFrozen(null);
      }
      setAmbiguous(!definitive);
      setError(getErrorMessage(caught));
    }
  });

  const submit = (input: NonNullable<typeof frozen>) => {
    setError(null);
    setAmbiguous(false);
    mutation.mutate(input);
    // Reauthentication material never remains in rendered component state.
    setCurrentPassword("");
  };

  return (
    <form
      aria-label="Edit connection"
      className="flex flex-col gap-2 border-t border-slate-200 pt-3"
      onSubmit={(event) => {
        event.preventDefault();
        const body = {
          ...(name.trim() !== connection.name ? { name: name.trim() } : {}),
          ...(scopeChanged
            ? {
                ...(agentAddress.trim() !== connection.agent_address
                  ? { agent_address: agentAddress.trim() }
                  : {}),
                ...(authScheme !== connection.auth_scheme ? { auth_scheme: authScheme } : {}),
                current_password: currentPassword
              }
            : {}),
          expected_revision: connection.revision
        };
        const snapshot = {
          body,
          idempotencyKey: intentKey.current(JSON.stringify([connection.id, body]))
        };
        setFrozen(snapshot);
        submit(snapshot);
      }}
    >
      <p className="text-[10px] font-semibold uppercase tracking-[0.06em] text-slate-500">Edit connection</p>
      <Field label="Agent name" name={`update_name_${connection.id}`} type="text" value={name} onChange={setName} />
      <Field
        label="Agent address"
        name={`update_address_${connection.id}`}
        type="url"
        value={agentAddress}
        onChange={setAgentAddress}
      />
      <AuthSchemeChoice
        value={authScheme}
        onChange={setAuthScheme}
        headerName={connection.auth_header_name}
      />
      {scopeChanged ? (
        <>
          <p className="text-xs text-needs-you-fg">
            Changing the address or the credential scheme resets readiness. Reauthenticate now, then test the new destination before another hand-off.
          </p>
          <Field
            label="Current password"
            name={`update_password_${connection.id}`}
            type="password"
            value={currentPassword}
            onChange={setCurrentPassword}
            autoComplete="current-password"
          />
        </>
      ) : null}
      <Feedback error={error} success={null} />
      <div className="flex gap-2">
        <Button type="submit" variant="secondary" size="sm" isLoading={mutation.isPending} disabled={!online}>
          Save connection
        </Button>
        {ambiguous && frozen ? (
          <Button
            type="button"
            variant="secondary"
            size="sm"
            disabled={!online}
            onClick={() => submit(frozen)}
          >
            Retry exact update
          </Button>
        ) : null}
      </div>
    </form>
  );
}

function RotateCredentialForm({
  connection,
  online,
  onDone,
  onFailed
}: {
  connection: AgentConnectionResponse;
  online: boolean;
  onDone: (message: string) => void;
  onFailed: (message: string) => void;
}): React.JSX.Element {
  const [credential, setCredential] = useState("");
  const [currentPassword, setCurrentPassword] = useState("");
  const keys = useAgentKeys();
  const intentKey = useIntentKey(`agent-credential-rotate-${connection.id}`);

  const mutation = useRelayMutation({
    mutationKey: keys.mutation("credential-rotate", connection.id),
    mutationFn: (input: {
      body: { credential: string; current_password: string; expected_revision: number };
      idempotencyKey: string;
    }) => {
      return apiClient.rotateAgentCredential(connection.id, input.body, input.idempotencyKey);
    },
    onSuccess: () => {
      intentKey.settle();
      setCredential("");
      setCurrentPassword("");
      onDone("Credential replaced. Test the connection again to confirm the agent accepts it.");
    },
    onError: (caught: unknown) => {
      if (definitivelyRejected(caught)) {
        intentKey.settle();
      }
      onFailed(getErrorMessage(caught));
    }
  });

  return (
    <form
      className="flex flex-col gap-2 border-t border-slate-200 pt-3"
      onSubmit={(event) => {
        event.preventDefault();
        const body = {
          credential,
          current_password: currentPassword,
          expected_revision: connection.revision
        };
        mutation.mutate({
          body,
          idempotencyKey: intentKey.current(JSON.stringify([connection.id, body]))
        });
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
        <Button type="submit" variant="secondary" size="sm" isLoading={mutation.isPending} disabled={!online}>
          Replace credential
        </Button>
      </div>
    </form>
  );
}

function DisconnectDialog({
  connection,
  intentKey,
  online,
  onClose,
  onDisconnected
}: {
  connection: AgentConnectionResponse;
  intentKey: IntentKey;
  online: boolean;
  onClose: () => void;
  onDisconnected: () => void;
}): React.JSX.Element {
  const titleId = useId();
  const keys = useAgentKeys();
  const [currentPassword, setCurrentPassword] = useState("");
  const [error, setError] = useState<string | null>(null);

  const mutation = useRelayMutation({
    mutationKey: keys.mutation("disconnect", connection.id),
    mutationFn: (input: {
      body: { current_password: string; expected_revision: number };
      idempotencyKey: string;
    }) => {
      return apiClient.disconnectAgentConnection(connection.id, input.body, input.idempotencyKey);
    },
    onSuccess: () => {
      intentKey.settle();
      onDisconnected();
    },
    onError: (caught: unknown) => {
      if (definitivelyRejected(caught)) {
        intentKey.settle();
      }
      setError(getErrorMessage(caught));
    }
  });

  return (
    // Deliberately not dismissible by Escape or by the scrim, and with no close
    // control in the header: this dialog destroys a credential, and a stray key
    // or a misplaced click must not be readable as that decision. It is
    // dismissed by its own **Keep it connected** action (design.md, Escape).
    <Overlay labelledBy={titleId} size="narrow">
      <OverlayHeader
        titleId={titleId}
        eyebrow="Delete connection"
        title={`Delete ${connection.name}?`}
      />
      <form
        className="flex flex-col gap-4 px-5 py-5 sm:px-6"
        onSubmit={(event) => {
          event.preventDefault();
          const body = { current_password: currentPassword, expected_revision: connection.revision };
          mutation.mutate({
            body,
            idempotencyKey: intentKey.current(JSON.stringify([connection.id, body]))
          });
        }}
      >
        <ul className="list-disc space-y-1 pl-5 text-sm text-slate-600">
          <li>
            Deleting this connection does not cancel work this agent has already accepted. If you want it
            stopped, request cancellation first and wait for the agent to confirm it.
          </li>
          <li>
            The stored credential and the agent-card summary BrainBuddy discovered — its name,
            version, description, skills and interface — are erased together, along with the card
            fingerprint. New hand-offs and replies through this agent are blocked.
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
        {/* Safe first, destructive last — which is also what makes **Delete**
            the focus trap's wrap boundary, so tabbing to the end of the dialog
            never lands anywhere but on the decision the user came to make. */}
        <div className="flex justify-end gap-2">
          <Button type="button" variant="secondary" size="md" onClick={onClose}>
            Cancel
          </Button>
          <Button
            type="submit"
            variant="danger"
            size="md"
            isLoading={mutation.isPending}
            disabled={!online}
          >
            Delete
          </Button>
        </div>
      </form>
    </Overlay>
  );
}
