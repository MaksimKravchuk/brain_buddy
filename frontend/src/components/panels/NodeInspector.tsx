import { useLayoutEffect, useState } from "react";
import { twMerge } from "tailwind-merge";

import { useDeleteNode, useUpdateNode, useValidation, useValidationHistory } from "../../api/hooks";
import type { ValidationResponse } from "../../api/types";
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
  const [nodeType, setNodeType] = useState(node?.type ?? "regular");
  const [highlightState, setHighlightState] = useState(node?.highlightState ?? "none");

  useLayoutEffect(() => {
    setLabel(node?.label ?? "");
    setNodeType(node?.type ?? "regular");
    setHighlightState(node?.highlightState ?? "none");
  }, [node?.id, node?.label, node?.type, node?.highlightState]);

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
            <option value="undesired_effect">Undesired effect</option>
            <option value="cause">Cause</option>
            <option value="regular">Regular</option>
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
