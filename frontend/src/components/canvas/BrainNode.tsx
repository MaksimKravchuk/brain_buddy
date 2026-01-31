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
  const activeTreeId = useTreeStore((state) => state.activeTreeId);
  const pushSnapshot = useTreeStore((state) => state.pushSnapshot);
  const upsertNode = useTreeStore((state) => state.upsertNode);
  const beginOptimisticChange = useTreeStore((state) => state.beginOptimisticChange);
  const resolveOptimisticChange = useTreeStore((state) => state.resolveOptimisticChange);
  const rollbackOptimisticChange = useTreeStore((state) => state.rollbackOptimisticChange);
  const select = useTreeStore((state) => state.select);

  const updateNodeMutation = useUpdateNode(activeTreeId ?? "");
  const pushToast = useUiStore((state) => state.pushToast);

  const [isHovered, setIsHovered] = useState(false);
  const [isEditing, setIsEditing] = useState(false);
  const [draftLabel, setDraftLabel] = useState(node.label);
  const inputRef = useRef<HTMLTextAreaElement | null>(null);
  const showControls = selected || isHovered;

  const linkHandleClass = (position: "top" | "bottom") =>
    twMerge(
      "pointer-events-auto absolute left-1/2 z-10 h-3 w-16 -translate-x-1/2 rounded-full border border-slate-300 bg-white/80 shadow-sm transition-opacity duration-150",
      position === "top" ? "-top-3" : "-bottom-3",
      showControls ? "opacity-80" : "opacity-0"
    );

  const linkTargetClass = (position: "top" | "bottom") =>
    twMerge(
      "pointer-events-auto absolute left-1/2 z-0 h-4 w-24 -translate-x-1/2 rounded-full border border-slate-200 bg-surface-sunken/60 transition-opacity duration-150",
      position === "top" ? "-top-4" : "-bottom-4",
      showControls ? "opacity-40" : "opacity-0"
    );

  useEffect(() => {
    setDraftLabel(node.label);
  }, [node.label]);

  useEffect(() => {
    if (isEditing) {
      inputRef.current?.focus();
      inputRef.current?.select();
    }
  }, [isEditing]);

  const lineHeight = 1.1;

  const fontSize = useMemo(() => {
    const label = isEditing ? draftLabel : node.label;
    const length = label.length || 1;
    const maxFont = 20;
    const minFont = 8;
    const baseWidth = 200;
    const baseHeight = 100;
    const innerPaddingX = isEditing ? 24 : 0;
    const innerPaddingY = isEditing ? 16 : 0;
    const contentWidth = Math.max(1, baseWidth - innerPaddingX - 4);
    const contentHeight = Math.max(1, baseHeight - innerPaddingY - 4);
    const avgCharWidth = 0.62;

    for (let size = maxFont; size >= minFont; size -= 1) {
      const charsPerLine = Math.max(1, Math.floor(contentWidth / (size * avgCharWidth)));
      const lineCount = Math.ceil(length / charsPerLine);
      const estimatedHeight = lineCount * size * lineHeight;
      if (estimatedHeight <= contentHeight) {
        return size;
      }
    }

    return minFont;
  }, [draftLabel, isEditing, lineHeight, node.label]);

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
        "group relative h-[132px] w-[240px] rounded-l-2xl rounded-r-xl border border-slate-200 bg-white/90 text-left shadow-sm transition-all duration-150",
        selected ? "ring-2 ring-brand-primary/30 shadow-glow" : "ring-1 ring-transparent"
      )}
      onMouseDown={() => select({ type: "node", id: node.id })}
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
    >
      <Handle
        id="link-up-source"
        type="source"
        position={Position.Top}
        className={linkHandleClass("top")}
        aria-label="Start link from this node (source)"
      />
      <Handle
        id="link-up-target"
        type="target"
        position={Position.Top}
        isConnectableStart={false}
        className={linkTargetClass("top")}
        aria-label="Accept link to this node (target)"
      />
      <Handle
        id="link-down-source"
        type="source"
        position={Position.Bottom}
        className={linkHandleClass("bottom")}
        aria-label="Start link from this node (source)"
      />
      <Handle
        id="link-down-target"
        type="target"
        position={Position.Bottom}
        isConnectableStart={false}
        className={linkTargetClass("bottom")}
        aria-label="Accept link to this node (target)"
      />

      <div className="pointer-events-none absolute inset-y-0 left-0 w-2 rounded-l-2xl bg-brand-primary/10" />

      <button
        type="button"
        aria-label="Create upstream node"
        onClick={onCreateParent}
        className={twMerge(
          "absolute left-1/2 top-0 z-10 h-4 w-4 -translate-x-1/2 -translate-y-1/2 rounded-full border border-slate-300 bg-white shadow-sm transition-opacity",
          showControls ? "opacity-100" : "opacity-0"
        )}
      />

      <button
        type="button"
        aria-label="Create right sibling"
        onClick={onCreateRightSibling}
        className={twMerge(
          "absolute right-0 top-1/2 z-10 h-4 w-4 translate-x-1/2 -translate-y-1/2 rounded-full border border-slate-300 bg-white shadow-sm transition-opacity",
          showControls ? "opacity-100" : "opacity-0"
        )}
      />

      <button
        type="button"
        aria-label="Create downstream node"
        onClick={onCreateChild}
        className={twMerge(
          "absolute bottom-0 left-1/2 z-10 h-4 w-4 -translate-x-1/2 translate-y-1/2 rounded-full border border-slate-300 bg-white shadow-sm transition-opacity",
          showControls ? "opacity-100" : "opacity-0"
        )}
      />

      <button
        type="button"
        aria-label="Create left sibling"
        onClick={onCreateLeftSibling}
        className={twMerge(
          "absolute left-0 top-1/2 z-10 h-4 w-4 -translate-x-1/2 -translate-y-1/2 rounded-full border border-slate-300 bg-white shadow-sm transition-opacity",
          showControls ? "opacity-100" : "opacity-0"
        )}
      />

      <div className="flex h-full w-full items-center justify-center overflow-hidden px-5 py-4">
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
            className="h-full w-full max-h-full resize-none rounded-md border border-slate-200 bg-white px-3 py-2 text-center text-slate-900 shadow-sm focus:border-brand-primary focus:outline-none focus:ring-2 focus:ring-brand-primary/20"
            style={{ fontSize, lineHeight }}
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
            className="max-h-full w-full break-words overflow-y-auto text-center font-semibold leading-tight tracking-tight text-slate-900 focus:outline-none"
            style={{ fontSize, lineHeight }}
          >
            {node.label}
          </button>
        )}
      </div>
    </div>
  );
}
