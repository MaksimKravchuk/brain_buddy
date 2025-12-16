import { useLayoutEffect, useMemo, useState } from "react";
import { twMerge } from "tailwind-merge";

import { hasApiKey } from "../../api/client";
import { useAiFeedback, useDeleteNode, useUpdateNode, useValidation, useValidationHistory } from "../../api/hooks";
import type { AiFeedbackResponse, ValidationResponse } from "../../api/types";
import { useTreeStore } from "../../stores/treeStore";
import { useUiStore } from "../../stores/uiStore";
import { getErrorMessage } from "../../utils/error";

export function NodeInspector(): JSX.Element {
  const activeTreeId = useTreeStore((state) => state.activeTreeId);
  const selection = useTreeStore((state) => state.selection);
  const node = useTreeStore((state) =>
    selection.type === "node" ? state.nodes.find((item) => item.id === selection.id) : undefined
  );
  const pushSnapshot = useTreeStore((state) => state.pushSnapshot);
  const upsertNode = useTreeStore((state) => state.upsertNode);
  const removeNode = useTreeStore((state) => state.removeNode);
  const beginOptimisticChange = useTreeStore((state) => state.beginOptimisticChange);
  const resolveOptimisticChange = useTreeStore((state) => state.resolveOptimisticChange);
  const rollbackOptimisticChange = useTreeStore((state) => state.rollbackOptimisticChange);
  const select = useTreeStore((state) => state.select);

  const pushToast = useUiStore((state) => state.pushToast);

  const [label, setLabel] = useState(node?.label ?? "");
  const [nodeType, setNodeType] = useState(node?.type ?? "child");
  const [highlightState, setHighlightState] = useState(node?.highlightState ?? "none");
  const [consent, setConsent] = useState(false);
  const [feedback, setFeedback] = useState<AiFeedbackResponse | null>(null);

  useLayoutEffect(() => {
    setLabel(node?.label ?? "");
    setNodeType(node?.type ?? "child");
    setHighlightState(node?.highlightState ?? "none");
    setFeedback(null);
  }, [node?.id, node?.label, node?.type, node?.highlightState]);

  const isSignedIn = useMemo(() => hasApiKey(), []);

  if (!activeTreeId) {
    return <InspectorPlaceholder message="Select a tree to inspect nodes." />;
  }

  if (!node) {
    return <InspectorPlaceholder message="Select a node on the canvas to view its details." />;
  }

  const updateNodeMutation = useUpdateNode(activeTreeId);
  const deleteNodeMutation = useDeleteNode(activeTreeId);
  const validationMutation = useValidation(activeTreeId);
  const historyQuery = useValidationHistory(activeTreeId, node.id);
  const aiFeedbackMutation = useAiFeedback(activeTreeId);

  const handleLabelSubmit = () => {
    const trimmed = label.trim();
    if (trimmed.length === 0 || trimmed === node.label) {
      setLabel(node.label);
      return;
    }

    pushSnapshot();
    const token = beginOptimisticChange("rename-node");
    upsertNode({
      ...node,
      label: trimmed
    });

    updateNodeMutation.mutate(
      { nodeId: node.id, payload: { label: trimmed } },
      {
        onSuccess: () => {
          resolveOptimisticChange(token);
          pushToast({
            title: "Node updated",
            description: "Label saved.",
            variant: "success",
            duration: 2500
          });
        },
        onError: (error) => {
          rollbackOptimisticChange(token);
          setLabel(node.label);
          pushToast({
            title: "Failed to update node",
            description: getErrorMessage(error),
            variant: "error",
            duration: 6000
          });
        }
      }
    );
  };

  const handleTypeChange = (nextType: typeof nodeType) => {
    setNodeType(nextType);
    pushSnapshot();
    const token = beginOptimisticChange("update-node-type");
    upsertNode({ ...node, type: nextType });
    updateNodeMutation.mutate(
      { nodeId: node.id, payload: { type: nextType } },
      {
        onSuccess: () => {
          resolveOptimisticChange(token);
          pushToast({
            title: "Node updated",
            description: "Type saved.",
            variant: "success",
            duration: 2000
          });
        },
        onError: (error) => {
          rollbackOptimisticChange(token);
          setNodeType(node.type);
          pushToast({
            title: "Failed to update node",
            description: getErrorMessage(error),
            variant: "error",
            duration: 6000
          });
        }
      }
    );
  };

  const handleHighlightChange = (next: typeof highlightState) => {
    setHighlightState(next);
    pushSnapshot();
    const token = beginOptimisticChange("update-highlight");
    upsertNode({ ...node, highlightState: next });
    updateNodeMutation.mutate(
      { nodeId: node.id, payload: { highlight_state: next } },
      {
        onSuccess: () => {
          resolveOptimisticChange(token);
        },
        onError: (error) => {
          rollbackOptimisticChange(token);
          setHighlightState(node.highlightState);
          pushToast({
            title: "Failed to update highlight",
            description: getErrorMessage(error),
            variant: "error",
            duration: 5000
          });
        }
      }
    );
  };

  const handleDelete = () => {
    pushSnapshot();
    const token = beginOptimisticChange("delete-node");
    removeNode(node.id);

    deleteNodeMutation.mutate(
      { nodeId: node.id, cascade: true },
      {
        onSuccess: () => {
          resolveOptimisticChange(token);
          select({ type: null, id: null });
          pushToast({
            title: "Node removed",
            description: "Node deleted from the tree.",
            variant: "info",
            duration: 3000
          });
        },
        onError: (error) => {
          rollbackOptimisticChange(token);
          pushToast({
            title: "Failed to delete node",
            description: getErrorMessage(error),
            variant: "error",
            duration: 6000
          });
        }
      }
    );
  };

  const handleTriggerValidation = () => {
    validationMutation.mutate(
      { nodeId: node.id, payload: {} },
      {
        onSuccess: (result) => {
          pushToast({
            title: "Validation updated",
            description: result.summary,
            variant: "success",
            duration: 3500
          });
          historyQuery.refetch();
        },
        onError: (error) => {
          pushToast({
            title: "Validation failed",
            description: getErrorMessage(error),
            variant: "error",
            duration: 6000
          });
        }
      }
    );
  };

  const handleAiFeedback = () => {
    if (!isSignedIn) {
      pushToast({
        title: "Sign in required",
        description: "Add your API key to request AI feedback.",
        variant: "warning",
        duration: 5000
      });
      return;
    }

    if (!consent) {
      pushToast({
        title: "Consent required",
        description: "Confirm consent before sending your tree to the AI provider.",
        variant: "warning",
        duration: 4500
      });
      return;
    }

    aiFeedbackMutation.mutate(
      { consent: true, request_id: `req-${activeTreeId}` },
      {
        onSuccess: (result) => {
          setFeedback(result);
          pushToast({
            title: "AI feedback ready",
            description: result.summary ?? "Summary available",
            variant: "success",
            duration: 4000
          });
        }
      }
    );
  };

  return (
    <div className="space-y-6">
      <div className="space-y-2">
        <label htmlFor="node-label" className="text-xs font-semibold uppercase tracking-wide text-slate-400">
          Node Label
        </label>
        <input
          id="node-label"
          value={label}
          onChange={(event) => setLabel(event.target.value)}
          onBlur={handleLabelSubmit}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              event.preventDefault();
              handleLabelSubmit();
            }
          }}
          className="w-full rounded-lg border border-slate-700 bg-surface-base px-3 py-2 text-sm text-slate-100 shadow-inner focus:border-brand-primary focus:outline-none"
        />
        <p className="text-xs text-slate-500">
          Incoming relations: <strong>{node.relationCounts.up}</strong>, Outgoing relations: <strong>{node.relationCounts.down}</strong>
        </p>
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        <div className="space-y-2 rounded-lg border border-slate-800 bg-surface-sunken/60 p-3">
          <label htmlFor="node-type" className="text-xs font-semibold uppercase tracking-wide text-slate-400">
            Node Type
          </label>
          <select
            id="node-type"
            value={nodeType}
            onChange={(event) => handleTypeChange(event.target.value as typeof nodeType)}
            className="w-full rounded-md border border-slate-700 bg-surface-base px-3 py-2 text-sm text-slate-100 shadow-inner focus:border-brand-primary focus:outline-none"
          >
            <option value="parent">Parent</option>
            <option value="child">Child</option>
          </select>
        </div>

        <div className="space-y-2 rounded-lg border border-slate-800 bg-surface-sunken/60 p-3">
          <label htmlFor="node-highlight" className="text-xs font-semibold uppercase tracking-wide text-slate-400">
            Highlight State
          </label>
          <select
            id="node-highlight"
            value={highlightState}
            onChange={(event) => handleHighlightChange(event.target.value as typeof highlightState)}
            className="w-full rounded-md border border-slate-700 bg-surface-base px-3 py-2 text-sm text-slate-100 shadow-inner focus:border-brand-primary focus:outline-none"
          >
            <option value="none">None</option>
            <option value="cause_candidate">Cause candidate</option>
            <option value="effect_spanning">Effect spanning</option>
          </select>
        </div>
      </div>

      <div className="space-y-2 rounded-lg border border-slate-800 bg-surface-sunken/60 p-3">
        <span className="text-sm font-medium text-slate-200">Validation</span>
        <p className="text-xs text-slate-500">Run validation against the selected provider and review history.</p>
        <div className="flex items-center gap-2 pt-2">
          <button
            type="button"
            onClick={handleTriggerValidation}
            disabled={validationMutation.isPending}
            className={twMerge(
              "rounded-md bg-brand-primary/90 px-3 py-2 text-xs font-semibold text-slate-950 transition",
              validationMutation.isPending ? "pointer-events-none opacity-70" : "hover:bg-brand-primary"
            )}
          >
            {validationMutation.isPending ? "Running…" : "Run Validation"}
          </button>
          <span className="text-[11px] text-slate-500">
            Uses the mock provider when none configured.
          </span>
        </div>
        <ValidationHistory
          isLoading={historyQuery.isLoading}
          items={historyQuery.data?.items ?? []}
          refetch={historyQuery.refetch}
        />
      </div>

      <div className="space-y-2 rounded-lg border border-emerald-900/60 bg-emerald-950/40 p-3">
        <div className="flex items-center justify-between gap-3">
          <div>
            <span className="text-sm font-semibold text-emerald-100">AI Feedback</span>
            <p className="text-xs text-emerald-200/80">Request a quick summary and recommendations.</p>
          </div>
          {!isSignedIn && <span className="rounded-full bg-amber-500/20 px-2 py-1 text-[10px] font-semibold text-amber-200">Requires API key</span>}
        </div>

        <label className="flex cursor-pointer items-start gap-2 text-xs text-emerald-50/90">
          <input
            type="checkbox"
            checked={consent}
            onChange={(event) => setConsent(event.target.checked)}
            className="mt-1 h-4 w-4 rounded border-emerald-700 bg-emerald-950 text-emerald-400 focus:ring-emerald-400"
          />
          <span>I consent to send the current tree to the AI provider for analysis.</span>
        </label>

        <div className="flex items-center gap-2 pt-2">
          <button
            type="button"
            onClick={handleAiFeedback}
            disabled={!consent || aiFeedbackMutation.isPending}
            className={twMerge(
              "rounded-md bg-emerald-500/90 px-3 py-2 text-xs font-semibold text-emerald-950 transition",
              (!consent || aiFeedbackMutation.isPending) && "pointer-events-none opacity-60",
              aiFeedbackMutation.isPending ? "animate-pulse" : "hover:bg-emerald-400"
            )}
          >
            {aiFeedbackMutation.isPending ? "Requesting…" : "Request Feedback"}
          </button>
          {feedback?.status === "success" && (
            <span className="text-[11px] text-emerald-200/80">{feedback.recommendations.length} tips ready</span>
          )}
        </div>

        {feedback && (
          <div className="rounded-md border border-emerald-800/60 bg-emerald-950/70 p-3 text-sm text-emerald-50">
            {feedback.summary && <p className="text-emerald-100">{feedback.summary}</p>}
            {feedback.recommendations.length > 0 && (
              <ul className="mt-2 list-disc space-y-1 pl-5 text-emerald-100/90">
                {feedback.recommendations.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            )}
          </div>
        )}
      </div>

      <div className="flex gap-3">
        <button
          type="button"
          onClick={handleDelete}
          className="flex-1 rounded-md border border-red-500/40 bg-red-500/10 px-3 py-2 text-sm font-semibold text-red-200 transition hover:border-red-400 hover:text-red-100"
        >
          Delete Node
        </button>
      </div>
    </div>
  );
}

function InspectorPlaceholder({ message }: { message: string }): JSX.Element {
  return (
    <div className="rounded-lg border border-dashed border-slate-700 bg-surface-sunken/40 p-4 text-sm text-slate-500">
      {message}
    </div>
  );
}

function ValidationHistory({
  isLoading,
  items,
  refetch
}: {
  isLoading: boolean;
  items: ValidationResponse[];
  refetch: () => Promise<unknown>;
}): JSX.Element {
  if (isLoading) {
    return <p className="text-xs text-slate-500">Loading validation history…</p>;
  }

  if (!items.length) {
    return (
      <div className="rounded-md border border-dashed border-slate-700/80 bg-surface-base/60 p-3 text-xs text-slate-500">
        No previous validations recorded.
        <button
          type="button"
          onClick={() => void refetch()}
          className="ml-2 inline-flex items-center text-[11px] font-semibold text-brand-primary hover:underline"
        >
          Refresh
        </button>
      </div>
    );
  }

  return (
    <div className="space-y-2 pt-2">
      <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">History</p>
      <ul className="space-y-2 text-xs text-slate-400">
        {items
          .slice()
          .reverse()
          .slice(0, 5)
          .map((item, index) => (
            <li key={`${item.checked_at}-${index}`} className="rounded-md border border-slate-800/70 bg-surface-base px-3 py-2">
              <div className="flex items-center justify-between gap-2">
                <span className="font-semibold text-slate-200">{item.confidence}%</span>
                <span className="text-[11px] text-slate-500">
                  {new Date(item.checked_at).toLocaleString()}
                </span>
              </div>
              <p className="mt-1 text-slate-300">{item.summary}</p>
              <p className="mt-1 text-[11px] text-slate-500">Provider: {item.provider}</p>
            </li>
          ))}
      </ul>
    </div>
  );
}
