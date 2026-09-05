import { useEffect, useId, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { useAgentConnections, useAgentKeys } from "../../api/agentHooks";
import { useRelayMutation, useRelayOnline } from "../../api/agentLifecycle";
import type {
  AgentConnectionResponse,
  AgentContextItem,
  AgentRunResponse
} from "../../api/agentTypes";
import { ApiError, apiClient } from "../../api/client";
import { Button } from "../../components/ui/Button";
import { Overlay, OverlayHeader } from "../../components/ui/Overlay";
import { Feedback, Field } from "../../components/ui/SettingsSection";
import { getErrorMessage } from "../../utils/error";
import { connectionStatusDetail, connectionStatusLabel } from "./agentCopy";

/** The server's own machine-readable refusal reason, or nothing. */
function refusalReason(caught: unknown): string | null {
  if (!(caught instanceof ApiError) || typeof caught.payload !== "object" || caught.payload === null) {
    return null;
  }
  const detail = (caught.payload as { detail?: unknown }).detail;
  if (typeof detail !== "object" || detail === null) {
    return null;
  }
  const reason = (detail as { reason?: unknown }).reason;
  return typeof reason === "string" ? reason : null;
}

/**
 * A connection the server refuses for no reason it was willing to name.
 *
 * Every condition BrainBuddy actually knows about — untested, unreachable,
 * invalid credentials, unsupported, disconnected, stale, changed — carries its
 * own sentence. A row that matches none of them and is still not offered is one
 * whose current state could not be refreshed, and partial knowledge fails
 * closed: it is shown, named honestly, and never selectable (D-02-S07).
 */
function statusUnknown(connection: AgentConnectionResponse): boolean {
  return (
    !connection.ready_for_handoff &&
    connection.status === "ready" &&
    !connection.stale &&
    !connection.agent_changed
  );
}

/**
 * A server reason that means "what you reviewed is no longer what would be
 * sent". The only safe response is to fetch a fresh manifest and make the user
 * look at it again — never to retry the confirmation behind their back.
 */
function needsReReview(caught: unknown): boolean {
  const reason = refusalReason(caught);
  return reason === "manifest_token_mismatch" || reason === "manifest_not_reserved";
}

/**
 * Hand-off review.
 *
 * The consent boundary for the whole feature: nothing leaves BrainBuddy until
 * the user has seen the server's manifest — every field, verbatim — and named
 * its token back on confirmation. Editing the payload discards the reviewed
 * manifest and fetches a new one, so a confirmation can never carry values the
 * user did not see.
 */
/**
 * The reviewed payload of a hand-off that never left, replayed exactly.
 *
 * Seeding the review from a run's frozen manifest is what makes **Try this
 * hand-off again** a *retry* rather than a second hand-off: the server rebuilds
 * the same manifest, returns the same token, and the token is the idempotency
 * key — so the same run ID and message ID are reused precisely when the user
 * changed nothing.
 */
export interface AgentHandoffSeed {
  connectionId: string;
  includeDetails: boolean;
  supportingItems: AgentContextItem[];
}

export function AgentHandoffOverlay({
  taskId,
  taskTitle,
  seed = null,
  onClose,
  onDispatched
}: {
  taskId: string;
  taskTitle: string;
  seed?: AgentHandoffSeed | null;
  onClose: () => void;
  onDispatched: (run: AgentRunResponse) => void;
}): React.JSX.Element {
  const titleId = useId();
  const reviewId = useId();
  const queryClient = useQueryClient();
  const keys = useAgentKeys();
  const online = useRelayOnline();
  const connectionsQuery = useAgentConnections(true);
  const [connectionId, setConnectionId] = useState<string | null>(seed?.connectionId ?? null);
  const [includeDetails, setIncludeDetails] = useState(seed?.includeDetails ?? true);
  const [contextItems, setContextItems] = useState<AgentContextItem[]>(seed?.supportingItems ?? []);
  const [contextLabel, setContextLabel] = useState("");
  const [contextBody, setContextBody] = useState("");
  const [currentPassword, setCurrentPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [reReviewNotice, setReReviewNotice] = useState<string | null>(null);
  // Asked once per connection, and again whenever its verified scope resets.
  // Held here rather than derived, because the user's tick is the thing being
  // recorded — a value read back off the manifest would tick itself.
  const [acknowledged, setAcknowledged] = useState(false);
  // The card moved between the review and the confirmation. Nothing left, and
  // the next step costs a password, so the refusal says both (D-02-S09).
  const [agentChanged, setAgentChanged] = useState(false);

  // Captured during render, before the dialog's own mount effect moves focus to
  // the panel: this is the control the user was on when the review opened, and
  // it is where the keyboard goes back when the review closes.
  const [invoker] = useState<HTMLElement | null>(() =>
    document.activeElement instanceof HTMLElement ? document.activeElement : null
  );
  useEffect(() => () => invoker?.focus(), [invoker]);

  const previewQuery = useQuery({
    enabled: Boolean(connectionId),
    // Every reviewable value is part of the key, so changing one can never leave
    // a stale manifest on screen.
    queryKey: keys.handoffPreview(taskId, connectionId, includeDetails, contextItems),
    queryFn: ({ signal }) =>
      apiClient.previewAgentHandoff(
        taskId,
        {
          connection_id: connectionId ?? "",
          include_details: includeDetails,
          supporting_items: contextItems
        },
        signal
      ),
    retry: false,
    staleTime: Infinity
  });

  const manifest = previewQuery.data;

  const confirmMutation = useRelayMutation({
    mutationKey: keys.mutation("handoff", taskId),
    mutationFn: () => {
      if (!manifest) {
        throw new Error("Review the hand-off before sending it.");
      }
      return apiClient.confirmAgentHandoff(
        taskId,
        {
          connection_id: manifest.connection_id,
          include_details: includeDetails,
          supporting_items: contextItems,
          manifest_token: manifest.token,
          current_password: manifest.reauthentication_required ? currentPassword : null,
          // Sent whenever the review asked for it, so the confirmation that
          // reaches the server is exactly the one the user agreed to. It is
          // part of the request identity, so a replay carries it too (AC-026).
          acknowledge_duplicate_risk: manifest.acknowledgement_required
            ? acknowledged
            : false
        },
        // Derived from the reviewed token, not from the clock: retrying the same
        // reviewed hand-off must return the original run, never start a second.
        `agent-handoff-${manifest.token}`
      );
    },
    onSuccess: (run) => {
      setError(null);
      setReReviewNotice(null);
      setAgentChanged(false);
      void queryClient.invalidateQueries({ queryKey: keys.runs(taskId) });
      onDispatched(run);
    },
    onError: (caught: unknown) => {
      setError(getErrorMessage(caught));
      setAgentChanged(refusalReason(caught) === "agent_card_changed");
      if (needsReReview(caught)) {
        setReReviewNotice("What would be sent has changed. Review it again before confirming.");
        void previewQuery.refetch();
      } else {
        setReReviewNotice(null);
      }
    }
  });

  const connections = connectionsQuery.data ?? [];
  const contextFromManifest = manifest?.supporting_items ?? contextItems;
  // A confirmation in flight has no exit at all: an interrupted one must not be
  // able to come back as a second hand-off (D-02-S12).
  const sending = confirmMutation.isPending;
  const dismiss = sending ? undefined : onClose;
  const noneEligible =
    connections.length > 0 && connections.every((candidate) => !candidate.ready_for_handoff);


  const replaceContext = (next: AgentContextItem[]) => {
    setReReviewNotice(null);
    setContextItems(next);
  };

  return (
    <Overlay labelledBy={titleId} onClose={dismiss} size="wide">
      <OverlayHeader
        titleId={titleId}
        eyebrow="Review before sending"
        title="Hand this task to an agent"
        meta={taskTitle}
        closeLabel="Close the review"
        onClose={dismiss}
      />
      <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto px-5 py-5 sm:px-6">
        <fieldset className="flex flex-col gap-2">
          <legend className="text-[10px] font-semibold uppercase tracking-[0.06em] text-slate-500">
            Choose an agent
          </legend>
          {connectionsQuery.isError ? (
            <Feedback error={getErrorMessage(connectionsQuery.error)} success={null} />
          ) : connectionsQuery.isPending ? (
            // Distinct from the empty state on purpose: "no agents connected"
            // is a claim about the account, and must never be shown for what is
            // really an unfinished request.
            <p className="text-sm text-slate-500">Loading your connected agents…</p>
          ) : connections.length === 0 ? (
            <p className="text-sm text-slate-500">
              No agents connected yet. Add one under Connected agents, then test it.
            </p>
          ) : (
            <>
              {/* Not the same claim as "no agents connected": the account has
                  agents, and the user needs the reason each one is out. */}
              {noneEligible ? (
                <p className="text-sm font-medium text-slate-900">
                  None of your agents can take this hand-off
                </p>
              ) : null}
              {connections.map((connection) => (
                <div key={connection.id} className="rounded-xl border border-slate-200 p-3">
                  <label className="flex items-center gap-2 text-sm text-slate-800">
                    <input
                      type="radio"
                      name="agent-connection"
                      value={connection.id}
                      checked={connectionId === connection.id}
                      disabled={!connection.ready_for_handoff}
                      onChange={() => {
                        setError(null);
                        setReReviewNotice(null);
                        // The tick is consent for one specific agent. Carrying
                        // it across a change of selection would arm Send for an
                        // agent the user never acknowledged (AC-026).
                        setAcknowledged(false);
                        setConnectionId(connection.id);
                      }}
                    />
                    <span className="font-medium">{connection.name}</span>
                    <span className="text-xs text-slate-500">
                      {statusUnknown(connection) ? "Status unknown" : connectionStatusLabel(connection)}
                    </span>
                  </label>
                  {connection.ready_for_handoff ? null : (
                    <p className="mt-1 pl-6 text-xs text-slate-500">
                      {statusUnknown(connection)
                        ? "BrainBuddy could not refresh this connection just now, so it is not offered. Test it from Connected agents."
                        : connectionStatusDetail(connection)}
                    </p>
                  )}
                </div>
              ))}
            </>
          )}
        </fieldset>

        {previewQuery.isError ? <Feedback error={getErrorMessage(previewQuery.error)} success={null} /> : null}
        {previewQuery.isFetching && !manifest ? (
          <div className="flex flex-col gap-1">
            <p className="text-sm text-slate-500">Building the hand-off preview…</p>
            {/* The moment a user is likeliest to assume something already left.
                It has not, and the wait says so (D-02-S03). */}
            <p className="text-xs text-slate-500">
              BrainBuddy is only assembling the review — no task content has been sent.
            </p>
          </div>
        ) : null}

        {manifest ? (
          <>
            <section aria-labelledby={reviewId} className="flex flex-col gap-3 rounded-xl border border-slate-200 p-4">
              <h3 id={reviewId} className="text-sm font-semibold text-slate-900">
                What will be sent
              </h3>

              <ReviewRow label="Task title">
                <p className="text-sm text-slate-800">{manifest.title}</p>
              </ReviewRow>

              <div className="flex flex-col gap-1">
                <label className="flex items-center gap-2 text-xs font-medium text-slate-600">
                  <input
                    type="checkbox"
                    checked={includeDetails}
                    onChange={(event) => {
                      setReReviewNotice(null);
                      setIncludeDetails(event.currentTarget.checked);
                    }}
                  />
                  Include task details
                </label>
                {manifest.details ? (
                  <p className="whitespace-pre-wrap text-sm text-slate-800">{manifest.details}</p>
                ) : (
                  <p className="text-sm text-slate-500">No task details will be sent.</p>
                )}
              </div>

              <ReviewRow label="Supporting items">
                {contextFromManifest.length === 0 ? (
                  <p className="text-sm text-slate-500">No supporting items will be sent.</p>
                ) : (
                  <ul className="flex flex-col gap-2">
                    {contextFromManifest.map((item, index) => (
                      <li
                        key={`${item.label}-${index}`}
                        className="flex items-start gap-2 rounded-lg border border-slate-200 p-2"
                      >
                        <div className="min-w-0 flex-1">
                          <p className="text-xs font-medium text-slate-600">{item.label}</p>
                          <p className="whitespace-pre-wrap text-sm text-slate-800">{item.body}</p>
                        </div>
                        <Button
                          type="button"
                          variant="ghost"
                          size="sm"
                          aria-label={`Remove ${item.label}`}
                          onClick={() =>
                            replaceContext(contextItems.filter((_candidate, candidateIndex) => candidateIndex !== index))
                          }
                        >
                          Remove
                        </Button>
                      </li>
                    ))}
                  </ul>
                )}
              </ReviewRow>

              <ReviewRow label="Task ID">
                <p className="font-mono text-xs text-slate-700">{manifest.task_id}</p>
              </ReviewRow>
              <ReviewRow label="Run ID">
                <p className="font-mono text-xs text-slate-700">{manifest.run_id}</p>
              </ReviewRow>
              <ReviewRow label="Correlation ID">
                <p className="font-mono text-xs text-slate-700">{manifest.correlation_id}</p>
              </ReviewRow>
              <ReviewRow label="Destination">
                {/* Card-sourced, so inert: shown so the owner can see where
                    their content would go, which is exactly why it must not be
                    something a stray click can follow (AC-031). */}
                <p className="break-all font-mono text-xs text-slate-700">
                  {manifest.destination_interface}
                </p>
              </ReviewRow>
              {manifest.push_callback?.registered ? (
                <ReviewRow label="Push callback">
                  <p className="break-all font-mono text-xs text-slate-700">
                    {manifest.push_callback.url_preview}
                  </p>
                  <p className="mt-1 text-sm text-slate-600">
                    {manifest.push_callback.disclosure}
                  </p>
                </ReviewRow>
              ) : null}
            </section>

            <section
              aria-label="Guarantee"
              className={`flex flex-col gap-2 rounded-xl border px-3 py-2 text-sm ${
                manifest.guarantee_tier === "guaranteed"
                  ? "border-ai-border bg-ai-bg text-ai-fg"
                  : "border-needs-you-border bg-needs-you-bg text-needs-you-fg"
              }`}
            >
              <p>{manifest.tier_disclosure}</p>
              {manifest.guarantee_tier === "best_effort" ? (
                <p>
                  <a
                    className="underline"
                    href={manifest.tier_disclosure_url}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    Read the single-start extension specification
                  </a>{" "}
                  <span className="text-slate-500">
                    Opens the published specification outside BrainBuddy.
                  </span>
                </p>
              ) : null}
              {manifest.acknowledgement_required ? (
                <>
                  <label className="flex items-start gap-2 text-sm">
                    <input
                      type="checkbox"
                      checked={acknowledged}
                      onChange={(event) => setAcknowledged(event.currentTarget.checked)}
                    />
                    <span>
                      I understand that a duplicate task is possible with this agent
                      <span className="block text-xs text-slate-500">
                        Asked once, on your first hand-off to this agent.
                      </span>
                    </span>
                  </label>
                  {acknowledged ? (
                    <p className="text-xs text-slate-500">
                      Acknowledged. BrainBuddy will not ask again for this agent.
                    </p>
                  ) : null}
                </>
              ) : manifest.guarantee_tier === "best_effort" ? (
                <p className="text-xs text-slate-500">
                  You acknowledged the duplicate risk for this agent on your first hand-off, so
                  BrainBuddy does not ask again.
                </p>
              ) : null}
            </section>

            <p
              aria-label="Cancellation"
              className="rounded-xl border border-slate-200 px-3 py-2 text-sm text-slate-600"
            >
              {manifest.cancellation_disclosure}
            </p>

            <p className="rounded-xl border border-needs-you-border bg-needs-you-bg px-3 py-2 text-sm text-needs-you-fg">
              {manifest.external_copy_notice}
            </p>

            <form
              className="flex flex-col gap-2 rounded-xl border border-slate-200 p-3"
              onSubmit={(event) => {
                event.preventDefault();
                if (!contextLabel.trim() || !contextBody.trim()) {
                  return;
                }
                replaceContext([
                  ...contextItems,
                  { label: contextLabel.trim(), body: contextBody.trim() }
                ]);
                setContextLabel("");
                setContextBody("");
              }}
            >
              <p className="text-[10px] font-semibold uppercase tracking-[0.06em] text-slate-500">
                Add context to send
              </p>
              <Field
                label="Context label"
                name="context_label"
                type="text"
                value={contextLabel}
                onChange={setContextLabel}
              />
              <Field
                label="Context body"
                name="context_body"
                type="text"
                value={contextBody}
                onChange={setContextBody}
              />
              <div>
                <Button type="submit" variant="secondary" size="sm">
                  Add context
                </Button>
              </div>
            </form>

            {manifest.reauthentication_required ? (
              <Field
                label="Current password"
                name="handoff_password"
                type="password"
                value={currentPassword}
                onChange={setCurrentPassword}
                autoComplete="current-password"
                hint="This is the first content-bearing send to this destination, so BrainBuddy re-checks your password."
              />
            ) : null}
          </>
        ) : null}

        {manifest && !online ? (
          <p className="rounded-xl border border-slate-200 px-3 py-2 text-sm text-slate-600">
            Sending is unavailable and nothing is queued.
          </p>
        ) : null}
        {sending ? (
          <p role="status" className="text-sm text-slate-600">
            Confirming again while this is in flight returns the same run.
          </p>
        ) : null}
        {reReviewNotice ? (
          <p role="status" className="text-sm text-needs-you-fg">
            {reReviewNotice}
          </p>
        ) : null}
        <Feedback error={error} success={null} />
        {agentChanged ? (
          <p className="text-sm text-needs-you-fg">
            Test this connection again from Connected agents. You will be asked for your password,
            because a new destination is a new content-bearing send.
          </p>
        ) : null}
      </div>
      <footer className="flex shrink-0 justify-end gap-2 border-t border-slate-100 px-5 py-4 sm:px-6">
        <Button type="button" variant="secondary" size="md" disabled={sending} onClick={onClose}>
          Cancel
        </Button>
        {manifest ? (
          <Button
            type="button"
            variant="primary"
            size="md"
            isLoading={sending}
            // The acknowledgement gates the send, and it gates it *here* rather
            // than only at the server: the user has to be able to see that
            // ticking the box is what unlocks the action they are about to
            // take (AC-026, D-02-S13/S14).
            disabled={!online || (manifest?.acknowledgement_required === true && !acknowledged)}
            onClick={() => confirmMutation.mutate()}
          >
            Send to agent
          </Button>
        ) : null}
      </footer>
    </Overlay>
  );
}

function ReviewRow({ label, children }: { label: string; children: React.ReactNode }): React.JSX.Element {
  return (
    <div className="flex flex-col gap-1">
      <p className="text-xs font-medium text-slate-600">{label}</p>
      {children}
    </div>
  );
}
