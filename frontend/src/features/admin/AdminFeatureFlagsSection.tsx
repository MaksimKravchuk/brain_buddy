import { useEffect, useRef, useState, type FormEvent } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { adminKeysFor, useAdminFeatureFlags } from "../../api/adminHooks";
import { ApiError, apiClient } from "../../api/client";
import type {
  AdminFeatureFlagMode,
  AdminFeatureFlagState,
  AdminFeatureFlagsResponse
} from "../../api/adminTypes";
import { useAuthStore } from "../../stores/authStore";
import { Button } from "../../components/ui/Button";
import { Overlay, OverlayHeader } from "../../components/ui/Overlay";
import { Feedback, SectionCard } from "../../components/ui/SettingsSection";
import { getErrorContext } from "../../utils/error";
import { focusFirstAvailable } from "./flagFocus";

/**
 * Runtime feature-flag control, the second section on `/admin` (010-FR-010).
 *
 * Realizes design states `F-01`…`F-13`. Three properties are load-bearing and
 * easy to lose in a refactor:
 *
 * * **Deploy-default inheritance is not a fourth mode.** While `source` is
 *   `deploy_default` the radio group has *no* checked input and the baseline is
 *   shown as its own value in the source note (DD-3). Mapping an inherited
 *   `internal` onto one of the three override radios is the specific
 *   contradiction DD-3 exists to close.
 * * **Confirmation is a fixed three-operation allowlist** (DD-12): setting a
 *   flag OFF, removing the *last* cohort member, and clearing an override.
 *   Not a computed "does this zero the population" rule — that is unenforceable
 *   against a concurrent edit from another tab, and this feature deliberately
 *   ships no revision protocol.
 * * **Every result is rendered from the server's returned state**, never from
 *   what the operator clicked: each mutation returns the full post-mutation
 *   document and that response replaces the cached read.
 */

// Identical to feature 009's client contract, deliberately: at least as
// permissive as what the server accepts, so `admin@localhost` classifies as an
// email rather than being reported missing as an account ID.
const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+$/;

const MODE_LABELS: ReadonlyArray<{ mode: AdminFeatureFlagMode; label: string }> = [
  { mode: "off", label: "Off" },
  { mode: "on", label: "On" },
  { mode: "selected_users", label: "Selected users" }
];

/** No response was received at all, so there is no correlation ID to show. */
const UNREACHABLE_COPY = "Could not reach the server. Check your connection and try again.";

const TAP_TARGET = "min-h-[44px]";

type ConfirmKind = "mode-off" | "clear-override" | "remove-last";

/**
 * A discriminated union deliberately: only `remove-last` names an account, so
 * modelling `accountId` as optional on every kind would create a "confirmed a
 * removal with no target" branch that cannot happen and cannot be tested.
 */
type PendingConfirm =
  | { kind: "mode-off"; restoreFocus: () => void }
  | { kind: "clear-override"; restoreFocus: () => void }
  | { kind: "remove-last"; accountId: string; restoreFocus: () => void };

/**
 * Where focus goes once a mutation's response has been rendered (`F-09`).
 *
 * Requested rather than applied inline: at `onSuccess` time the row is still
 * showing its saving state, so every control the target could be is disabled
 * and `focus()` on it is a no-op. Applying it from an effect means the target
 * is the re-rendered, enabled control the operator can actually use.
 */
type FocusRequest =
  | { kind: "mode"; mode: AdminFeatureFlagMode }
  | { kind: "clear" }
  | { kind: "add" }
  | { kind: "after-remove"; removed: string };

export function AdminFeatureFlagsSection(): React.JSX.Element {
  const query = useAdminFeatureFlags();

  if (query.isPending) {
    return (
      <SectionCard
        title="Feature flags"
        description="Runtime rollout control for the flags that can be managed here."
      >
        <p role="status" className="text-sm text-slate-500">
          Loading feature flags…
        </p>
      </SectionCard>
    );
  }

  if (query.isError) {
    // F-13: the request itself never completed. Distinct from F-11, which is a
    // successful answer reporting that the stored document is unreadable — a
    // retry can plausibly fix this one and cannot fix that one.
    const { message, referenceId } = getErrorContext(query.error, UNREACHABLE_COPY);
    return (
      <SectionCard
        title="Feature flags"
        description="Runtime rollout control for the flags that can be managed here."
      >
        <div className="flex flex-col gap-3">
          <p className="text-sm text-slate-600">Couldn&apos;t load feature flags.</p>
          <Feedback error={referenceId ? `${message} (ref: ${referenceId})` : message} success={null} />
          <div>
            <Button
              type="button"
              variant="secondary"
              size="md"
              className={TAP_TARGET}
              onClick={() => void query.refetch()}
            >
              Retry
            </Button>
          </div>
        </div>
      </SectionCard>
    );
  }

  const { degraded, flags } = query.data;

  return (
    <SectionCard
      title="Feature flags"
      description="Runtime rollout control for the flags that can be managed here."
    >
      <div className="flex flex-col gap-5">
        {degraded ? (
          // F-11: no retry and no reset affordance. The degradation is a
          // property of the stored document, not of this request, and a repair
          // subsystem is deliberately out of scope.
          <p
            role="alert"
            className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800"
          >
            Runtime flag state could not be read. Every flag is resolving from the deploy
            default, and changes are disabled until this is repaired.
          </p>
        ) : null}
        {flags.map((flag) => (
          <FlagRow key={flag.name} flag={flag} disabled={degraded} />
        ))}
      </div>
    </SectionCard>
  );
}

function FlagRow({
  flag,
  disabled
}: {
  flag: AdminFeatureFlagState;
  disabled: boolean;
}): React.JSX.Element {
  const queryClient = useQueryClient();
  const ownerId = useAuthStore((state) => state.user?.id ?? null);
  const [query, setQuery] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [notFound, setNotFound] = useState(false);
  const [confirm, setConfirm] = useState<PendingConfirm | null>(null);
  const [focusRequest, setFocusRequest] = useState<FocusRequest | null>(null);

  const radioRefs = useRef(new Map<AdminFeatureFlagMode, HTMLInputElement | null>());
  const clearRef = useRef<HTMLButtonElement | null>(null);
  const addInputRef = useRef<HTMLInputElement | null>(null);
  const removeRefs = useRef(new Map<string, HTMLButtonElement | null>());
  const countRef = useRef<HTMLParagraphElement | null>(null);

  const headingId = `flag-${flag.name}-heading`;
  const isCohortMode = flag.override_mode === "selected_users";

  const adopt = (data: AdminFeatureFlagsResponse) => {
    queryClient.setQueryData(adminKeysFor(ownerId).featureFlags(), data);
  };

  const beginMutation = () => {
    setError(null);
    setSaved(false);
    setNotFound(false);
  };

  const fail = (caught: unknown) => {
    if (!(caught instanceof ApiError)) {
      // F-10: no status line ever arrived, so there is no correlation ID to
      // show and no server message to quote — only the named fallback copy.
      setError(UNREACHABLE_COPY);
      return;
    }
    if (caught.status === 404) {
      setNotFound(true);
      return;
    }
    const { message, referenceId } = getErrorContext(caught, UNREACHABLE_COPY);
    setError(referenceId ? `${message} (ref: ${referenceId})` : message);
  };

  const modeMutation = useMutation({
    mutationFn: (mode: AdminFeatureFlagMode) =>
      apiClient.setAdminFeatureFlagMode(flag.name, mode),
    onMutate: beginMutation,
    onSuccess: (data, mode) => {
      adopt(data);
      setSaved(true);
      setFocusRequest({ kind: "mode", mode });
    },
    onError: fail
  });

  const clearMutation = useMutation({
    mutationFn: () => apiClient.clearAdminFeatureFlagOverride(flag.name),
    onMutate: beginMutation,
    onSuccess: (data) => {
      adopt(data);
      setSaved(true);
      setFocusRequest({ kind: "clear" });
    },
    onError: fail
  });

  const addMutation = useMutation({
    // Sent as typed and never trimmed: trimming a whitespace variant into the
    // canonical address would manufacture a match the server must refuse.
    mutationFn: (value: string) =>
      apiClient.addAdminFeatureFlagUser(
        flag.name,
        EMAIL_PATTERN.test(value) ? { email: value } : { account_id: value }
      ),
    onMutate: beginMutation,
    onSuccess: (data) => {
      adopt(data);
      setSaved(true);
      setQuery("");
      setFocusRequest({ kind: "add" });
    },
    onError: fail
  });

  const removeMutation = useMutation({
    mutationFn: (accountId: string) =>
      apiClient.removeAdminFeatureFlagUser(flag.name, accountId),
    onMutate: beginMutation,
    onSuccess: (data, accountId) => {
      adopt(data);
      setSaved(true);
      setFocusRequest({ kind: "after-remove", removed: accountId });
    },
    onError: fail
  });

  /**
   * `F-09`'s defined focus target, applied after the server's answer has been
   * rendered. Never dropped to the document body.
   */
  useEffect(() => {
    if (!focusRequest) {
      return;
    }
    if (focusRequest.kind === "mode") {
      focusFirstAvailable([radioRefs.current.get(focusRequest.mode)]);
    } else if (focusRequest.kind === "clear") {
      // The clear action disappears with the override it removed, so the mode
      // group the flag now inherits is the defined target.
      focusFirstAvailable([clearRef.current, radioRefs.current.get("off")]);
    } else if (focusRequest.kind === "add") {
      focusFirstAvailable([addInputRef.current]);
    } else {
      const removed = focusRequest.removed;
      const next = flag.selected_users
        .filter((member) => member.account_id !== removed)
        .map((member) => removeRefs.current.get(member.account_id))
        .find((node) => Boolean(node));
      focusFirstAvailable([next ?? null, addInputRef.current, countRef.current]);
    }
    setFocusRequest(null);
  }, [focusRequest, flag]);

  const busy =
    modeMutation.isPending ||
    clearMutation.isPending ||
    addMutation.isPending ||
    removeMutation.isPending;
  const locked = disabled || busy;

  const onModeChange = (mode: AdminFeatureFlagMode) => {
    if (mode === "off") {
      setConfirm({
        kind: "mode-off",
        restoreFocus: () => radioRefs.current.get("off")?.focus()
      });
      return;
    }
    modeMutation.mutate(mode);
  };

  const onRemove = (accountId: string) => {
    if (flag.selected_users.length === 1) {
      setConfirm({
        kind: "remove-last",
        accountId,
        restoreFocus: () => removeRefs.current.get(accountId)?.focus()
      });
      return;
    }
    removeMutation.mutate(accountId);
  };

  const onSubmitAdd = (event: FormEvent) => {
    event.preventDefault();
    if (query.length === 0) {
      return;
    }
    addMutation.mutate(query);
  };

  const dismissConfirm = (pending: PendingConfirm) => {
    setConfirm(null);
    pending.restoreFocus();
  };

  const runConfirm = (pending: PendingConfirm) => {
    setConfirm(null);
    if (pending.kind === "mode-off") {
      modeMutation.mutate("off");
    } else if (pending.kind === "clear-override") {
      clearMutation.mutate();
    } else {
      removeMutation.mutate(pending.accountId);
    }
  };

  return (
    <article aria-labelledby={headingId} className="flex flex-col gap-3 border-t border-slate-100 pt-4 first:border-0 first:pt-0">
      <h3 id={headingId} className="text-sm font-semibold text-slate-900">
        {flag.name}
      </h3>

      <fieldset
        className="flex flex-col flex-wrap gap-2 border-0 p-0 sm:flex-row sm:items-center"
        disabled={locked}
      >
        <legend className="text-xs font-medium uppercase tracking-wide text-slate-500">
          {flag.name} mode
        </legend>
        {MODE_LABELS.map(({ mode, label }) => (
          <label key={mode} className={`inline-flex items-center gap-2 text-sm text-slate-700 ${TAP_TARGET}`}>
            <input
              type="radio"
              name={`mode-${flag.name}`}
              value={mode}
              checked={flag.override_mode === mode}
              disabled={locked}
              ref={(node) => {
                radioRefs.current.set(mode, node);
              }}
              onChange={() => onModeChange(mode)}
            />
            {label}
          </label>
        ))}
      </fieldset>

      <div
        data-testid={`source-note-${flag.name}`}
        className="flex flex-col gap-2 text-sm text-slate-500 sm:flex-row sm:items-center sm:justify-between"
      >
        <span>
          {flag.source === "runtime"
            ? `Runtime override · Deploy default: ${flag.deploy_default_state}`
            : `Deploy default (${flag.deploy_default_state})`}
        </span>
        {flag.source === "runtime" ? (
          <Button
            type="button"
            variant="secondary"
            size="md"
            className={TAP_TARGET}
            ref={clearRef}
            disabled={locked}
            onClick={() =>
              setConfirm({
                kind: "clear-override",
                restoreFocus: () => clearRef.current?.focus()
              })
            }
          >
            Use deploy default
          </Button>
        ) : null}
      </div>

      <p
        ref={countRef}
        tabIndex={-1}
        data-testid={`cohort-count-${flag.name}`}
        className="text-sm text-slate-600"
      >
        {flag.selected_users.length} selected
      </p>

      {isCohortMode ? (
        <>
          {flag.selected_users.length === 0 ? (
            <p className="text-sm text-slate-500">
              No users selected — this flag is off for everyone.
            </p>
          ) : (
            <ul className="flex flex-col gap-2">
              {flag.selected_users.map((member) => (
                <li
                  key={member.account_id}
                  data-testid={`cohort-row-${member.account_id}`}
                  className="flex flex-col gap-1 rounded-md border border-slate-200 px-3 py-2 text-sm sm:flex-row sm:items-center sm:justify-between"
                >
                  <span className="font-mono text-xs text-slate-500">{member.account_id}</span>
                  <span className="flex items-center justify-between gap-3">
                    <span className="text-slate-700">{member.email ?? "Account not found"}</span>
                    <Button
                      type="button"
                      variant="secondary"
                      size="md"
                      className={TAP_TARGET}
                      aria-label={`Remove ${member.email ?? member.account_id}`}
                      disabled={locked}
                      ref={(node) => {
                        removeRefs.current.set(member.account_id, node);
                      }}
                      onClick={() => onRemove(member.account_id)}
                    >
                      Remove
                    </Button>
                  </span>
                </li>
              ))}
            </ul>
          )}

          <form
            data-testid={`add-form-${flag.name}`}
            className="flex flex-col gap-2 sm:flex-row sm:items-end"
            onSubmit={onSubmitAdd}
          >
            <label className="flex flex-1 flex-col gap-1 text-sm">
              <span className="font-medium text-slate-700">Account ID or email</span>
              <input
                type="text"
                name={`add-user-${flag.name}`}
                value={query}
                ref={addInputRef}
                disabled={locked}
                onChange={(event) => setQuery(event.target.value)}
                className="rounded-md border border-slate-200 bg-white px-3 py-2 text-slate-900 shadow-soft"
              />
            </label>
            <Button
              type="submit"
              variant="primary"
              size="md"
              className={TAP_TARGET}
              disabled={locked}
              isLoading={addMutation.isPending}
            >
              Add
            </Button>
          </form>
        </>
      ) : null}

      {notFound ? (
        <p role="status" className="rounded-md border border-slate-200 bg-surface-sunken px-3 py-2 text-sm text-slate-600">
          No account found.
        </p>
      ) : null}
      <Feedback error={error} success={saved ? "Saved." : null} />

      {confirm ? (
        <ConfirmStep
          flag={flag}
          kind={confirm.kind}
          onCancel={() => dismissConfirm(confirm)}
          onConfirm={() => runConfirm(confirm)}
        />
      ) : null}
    </article>
  );
}

const CONFIRM_COPY: Record<ConfirmKind, { title: string; action: string }> = {
  "mode-off": { title: "Turn off", action: "Turn off" },
  "remove-last": { title: "Remove the last selected user?", action: "Remove user" },
  "clear-override": { title: "Use deploy default", action: "Use deploy default" }
};

function ConfirmStep({
  flag,
  kind,
  onCancel,
  onConfirm
}: {
  flag: AdminFeatureFlagState;
  kind: ConfirmKind;
  onCancel: () => void;
  onConfirm: () => void;
}): React.JSX.Element {
  const titleId = `confirm-${flag.name}-title`;
  const body =
    kind === "mode-off"
      ? `Turn ${flag.name} off for everyone?`
      : kind === "remove-last"
        ? `Remove the last selected user? ${flag.name} will be off for everyone.`
        : `Use the deploy default for ${flag.name}? It currently ships ${flag.deploy_default_state} and this clears the runtime override.`;

  return (
    <Overlay labelledBy={titleId} onClose={onCancel} size="narrow">
      <OverlayHeader
        titleId={titleId}
        eyebrow="Confirm"
        title={CONFIRM_COPY[kind].title}
        onClose={onCancel}
      />
      <div className="flex flex-col gap-4 px-5 py-5 sm:px-6">
        <p className="text-sm text-slate-600">{body}</p>
        <div
          data-testid="confirm-actions"
          className="flex flex-col gap-2 sm:flex-row sm:justify-end"
        >
          <Button type="button" variant="secondary" size="md" className={TAP_TARGET} onClick={onCancel}>
            Cancel
          </Button>
          <Button type="button" variant="danger" size="md" className={TAP_TARGET} onClick={onConfirm}>
            {CONFIRM_COPY[kind].action}
          </Button>
        </div>
      </div>
    </Overlay>
  );
}
