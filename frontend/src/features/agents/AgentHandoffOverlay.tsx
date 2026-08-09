import { useId, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { agentKeys, useAgentConnections } from "../../api/agentHooks";
import type { AgentContextItem, AgentRunResponse } from "../../api/agentTypes";
import { ApiError, apiClient } from "../../api/client";
import { Button } from "../../components/ui/Button";
import { Overlay, OverlayHeader } from "../../components/ui/Overlay";
import { Feedback, Field } from "../../components/ui/SettingsSection";
import { getErrorMessage } from "../../utils/error";
import { connectionStatusDetail, connectionStatusLabel } from "./agentCopy";

/**
 * A server reason that means "what you reviewed is no longer what would be
 * sent". The only safe response is to fetch a fresh manifest and make the user
 * look at it again — never to retry the confirmation behind their back.
 */
function needsReReview(caught: unknown): boolean {
  if (!(caught instanceof ApiError) || typeof caught.payload !== "object" || caught.payload === null) {
    return false;
  }
  const detail = (caught.payload as { detail?: unknown }).detail;
  if (typeof detail !== "object" || detail === null) {
    return false;
  }
  const reason = (detail as { reason?: unknown }).reason;
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
export function AgentHandoffOverlay({
  taskId,
  taskTitle,
  onClose,
  onDispatched
}: {
  taskId: string;
  taskTitle: string;
  onClose: () => void;
  onDispatched: (run: AgentRunResponse) => void;
}): JSX.Element {
  const titleId = useId();
  const reviewId = useId();
  const queryClient = useQueryClient();
  const connectionsQuery = useAgentConnections(true);
  const [connectionId, setConnectionId] = useState<string | null>(null);
  const [includeDetails, setIncludeDetails] = useState(true);
  const [contextItems, setContextItems] = useState<AgentContextItem[]>([]);
  const [contextLabel, setContextLabel] = useState("");
  const [contextBody, setContextBody] = useState("");
  const [currentPassword, setCurrentPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [reReviewNotice, setReReviewNotice] = useState<string | null>(null);

  const previewQuery = useQuery({
    enabled: Boolean(connectionId),
    // Every reviewable value is part of the key, so changing one can never leave
    // a stale manifest on screen.
    queryKey: [...agentKeys.all, "handoff-preview", taskId, connectionId, includeDetails, contextItems],
    queryFn: ({ signal }) =>
      apiClient.previewAgentHandoff(
        taskId,
        {
          connection_id: connectionId ?? "",
          include_details: includeDetails,
          context_items: contextItems
        },
        signal
      ),
    retry: false,
    staleTime: Infinity
  });

  const manifest = previewQuery.data;

  const confirmMutation = useMutation({
    mutationFn: () => {
      if (!manifest) {
        throw new Error("Review the hand-off before sending it.");
      }
      return apiClient.confirmAgentHandoff(
        taskId,
        {
          connection_id: manifest.connection_id,
          include_details: includeDetails,
          context_items: contextItems,
          manifest_token: manifest.token,
          current_password: manifest.reauthentication_required ? currentPassword : null
        },
        // Derived from the reviewed token, not from the clock: retrying the same
        // reviewed hand-off must return the original run, never start a second.
        `agent-handoff-${manifest.token}`
      );
    },
    onSuccess: (run) => {
      setError(null);
      setReReviewNotice(null);
      void queryClient.invalidateQueries({ queryKey: agentKeys.runs(taskId) });
      onDispatched(run);
    },
    onError: (caught: unknown) => {
      setError(getErrorMessage(caught));
      if (needsReReview(caught)) {
        setReReviewNotice("What would be sent has changed. Review it again before confirming.");
        void previewQuery.refetch();
      } else {
        setReReviewNotice(null);
      }
    }
  });

  const connections = connectionsQuery.data ?? [];
  const contextFromManifest = manifest?.context_items ?? contextItems;


  const replaceContext = (next: AgentContextItem[]) => {
    setReReviewNotice(null);
    setContextItems(next);
  };

  return (
    <Overlay labelledBy={titleId} onClose={onClose} size="wide">
      <OverlayHeader
        titleId={titleId}
        eyebrow="Review before sending"
        title="Hand this task to an agent"
        meta={taskTitle}
        onClose={onClose}
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
            connections.map((connection) => (
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
                      setConnectionId(connection.id);
                    }}
                  />
                  <span className="font-medium">{connection.name}</span>
                  <span className="text-xs text-slate-500">{connectionStatusLabel(connection)}</span>
                </label>
                {connection.ready_for_handoff ? null : (
                  <p className="mt-1 pl-6 text-xs text-slate-500">{connectionStatusDetail(connection)}</p>
                )}
              </div>
            ))
          )}
        </fieldset>

        {previewQuery.isError ? <Feedback error={getErrorMessage(previewQuery.error)} success={null} /> : null}
        {previewQuery.isFetching && !manifest ? (
          <p className="text-sm text-slate-500">Building the hand-off preview…</p>
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

              <ReviewRow label="Context items">
                {contextFromManifest.length === 0 ? (
                  <p className="text-sm text-slate-500">No context items will be sent.</p>
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
                            replaceContext(contextItems.filter((candidate) => candidate.label !== item.label))
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
              <ReviewRow label="Destination">
                <p className="break-all font-mono text-xs text-slate-700">{manifest.destination_endpoint}</p>
              </ReviewRow>
              <ReviewRow
                label={`Reporting instructions (v${manifest.instructions_version}, protocol ${manifest.protocol_version})`}
              >
                <p className="whitespace-pre-wrap text-sm text-slate-800">{manifest.reporting_instructions}</p>
              </ReviewRow>
            </section>

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

        {reReviewNotice ? (
          <p role="status" className="text-sm text-needs-you-fg">
            {reReviewNotice}
          </p>
        ) : null}
        <Feedback error={error} success={null} />
      </div>
      <footer className="flex shrink-0 justify-end gap-2 border-t border-slate-100 px-5 py-4 sm:px-6">
        <Button type="button" variant="secondary" size="md" onClick={onClose}>
          Cancel
        </Button>
        {manifest ? (
          <Button
            type="button"
            variant="primary"
            size="md"
            isLoading={confirmMutation.isPending}
            onClick={() => confirmMutation.mutate()}
          >
            Send to agent
          </Button>
        ) : null}
      </footer>
    </Overlay>
  );
}

function ReviewRow({ label, children }: { label: string; children: React.ReactNode }): JSX.Element {
  return (
    <div className="flex flex-col gap-1">
      <p className="text-xs font-medium text-slate-600">{label}</p>
      {children}
    </div>
  );
}
