import { useEffect, useMemo, useRef, useState } from "react";
import type { NodeProps } from "reactflow";
import { Handle, Position } from "reactflow";
import { twMerge } from "tailwind-merge";

import type { GraphNode } from "../../stores/treeStore";
import { useTreeStore } from "../../stores/treeStore";
import { useUpdateNode } from "../../api/hooks";
import { useUiStore } from "../../stores/uiStore";
import { getErrorMessage } from "../../utils/error";

export interface BrainNodeData {
  node: GraphNode;
  onCreateParent(): void;
  onCreateChild(): void;
  onCreateLeftSibling(): void;
  onCreateRightSibling(): void;
}

export function BrainNode({ data, selected }: NodeProps<BrainNodeData>): JSX.Element {
  const { node, onCreateParent, onCreateChild, onCreateLeftSibling, onCreateRightSibling } = data;
  const [isHovered, setIsHovered] = useState(false);
  const [isEditing, setIsEditing] = useState(false);
  const [draftLabel, setDraftLabel] = useState(node.label);
  const inputRef = useRef<HTMLTextAreaElement | null>(null);

  const activeTreeId = useTreeStore((state) => state.activeTreeId);
  const pushSnapshot = useTreeStore((state) => state.pushSnapshot);
  const upsertNode = useTreeStore((state) => state.upsertNode);
  const beginOptimisticChange = useTreeStore((state) => state.beginOptimisticChange);
  const resolveOptimisticChange = useTreeStore((state) => state.resolveOptimisticChange);
  const rollbackOptimisticChange = useTreeStore((state) => state.rollbackOptimisticChange);

  const pushToast = useUiStore((state) => state.pushToast);

  const updateNodeMutation = useUpdateNode(activeTreeId ?? "");
  const showControls = selected || isHovered;

  useEffect(() => {
    setDraftLabel(node.label);
  }, [node.label]);

  useEffect(() => {
    if (isEditing) {
      inputRef.current?.focus();
      inputRef.current?.select();
    }
  }, [isEditing]);

  const fontSize = useMemo(() => {
    const length = node.label.length || 1;
    const clamped = Math.max(11, 20 - length * 0.25);
    return Math.min(20, clamped);
  }, [node.label.length]);

  const handleSubmitLabel = () => {
    const trimmed = draftLabel.trim();
    setIsEditing(false);

    if (!activeTreeId) {
      setDraftLabel(node.label);
      return;
    }

    if (!trimmed || trimmed === node.label) {
      setDraftLabel(node.label);
      return;
    }

    pushSnapshot();
    const token = beginOptimisticChange("rename-node-inline");
    upsertNode({ ...node, label: trimmed });

    updateNodeMutation.mutate(
      { nodeId: node.id, payload: { label: trimmed } },
      {
        onSuccess: () => {
          resolveOptimisticChange(token);
        },
        onError: (error) => {
          rollbackOptimisticChange(token);
          setDraftLabel(node.label);
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

  const handleCancelEdit = () => {
    setDraftLabel(node.label);
    setIsEditing(false);
  };

  return (
    <div
      className={twMerge(
        "group relative h-full min-h-[96px] min-w-[200px] max-w-[280px] rounded-l-2xl rounded-r-xl border border-slate-600/60 bg-slate-900/70 text-left shadow-lg transition-all duration-150",
        selected ? "ring-2 ring-slate-200/60 shadow-glow" : "ring-1 ring-transparent"
      )}
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
    >
      <Handle type="source" position={Position.Top} className="pointer-events-none invisible" isConnectable={false} />
      <Handle type="target" position={Position.Bottom} className="pointer-events-none invisible" isConnectable={false} />

      <div className="pointer-events-none absolute inset-y-0 left-0 w-2 rounded-l-2xl bg-slate-200/10" />

      <button
        type="button"
        aria-label="Create parent"
        onClick={onCreateParent}
        className={twMerge(
          "absolute left-1/2 top-0 z-10 h-4 w-4 -translate-x-1/2 -translate-y-1/2 rounded-full border border-slate-500/70 bg-slate-100 shadow-sm transition-opacity",
          showControls ? "opacity-100" : "opacity-0"
        )}
      />

      <button
        type="button"
        aria-label="Create right sibling"
        onClick={onCreateRightSibling}
        className={twMerge(
          "absolute right-0 top-1/2 z-10 h-4 w-4 translate-x-1/2 -translate-y-1/2 rounded-full border border-slate-500/70 bg-slate-100 shadow-sm transition-opacity",
          showControls ? "opacity-100" : "opacity-0"
        )}
      />

      <button
        type="button"
        aria-label="Create child"
        onClick={onCreateChild}
        className={twMerge(
          "absolute bottom-0 left-1/2 z-10 h-4 w-4 -translate-x-1/2 translate-y-1/2 rounded-full border border-slate-500/70 bg-slate-100 shadow-sm transition-opacity",
          showControls ? "opacity-100" : "opacity-0"
        )}
      />

      <button
        type="button"
        aria-label="Create left sibling"
        onClick={onCreateLeftSibling}
        className={twMerge(
          "absolute left-0 top-1/2 z-10 h-4 w-4 -translate-x-1/2 -translate-y-1/2 rounded-full border border-slate-500/70 bg-slate-100 shadow-sm transition-opacity",
          showControls ? "opacity-100" : "opacity-0"
        )}
      />

      <div className="flex h-full w-full items-center justify-center px-5 py-4">
        {isEditing ? (
          <textarea
            ref={inputRef}
            value={draftLabel}
            onChange={(event) => setDraftLabel(event.target.value)}
            onBlur={handleSubmitLabel}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                handleSubmitLabel();
              }
              if (event.key === "Escape") {
                event.preventDefault();
                handleCancelEdit();
              }
            }}
            className="w-full resize-none rounded-md border border-slate-700 bg-slate-950/70 px-3 py-2 text-center text-slate-50 shadow-inner focus:border-brand-primary focus:outline-none"
            style={{ fontSize }}
            rows={2}
          />
        ) : (
          <button
            type="button"
            onDoubleClick={() => setIsEditing(true)}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.preventDefault();
                setIsEditing(true);
              }
            }}
            className="w-full break-words text-center font-semibold leading-tight tracking-tight text-slate-50 focus:outline-none"
            style={{ fontSize }}
          >
            {node.label}
          </button>
        )}
      </div>
    </div>
  );
}
