import { useEffect, useMemo, useRef, useState } from "react";
import type { NodeProps } from "reactflow";
import { Handle, Position } from "reactflow";
import { twMerge } from "tailwind-merge";

import type { GraphNode } from "../../stores/treeStore";
import { useTreeStore } from "../../stores/treeStore";
import { useUpdateNode } from "../../api/hooks";

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
  const updateNodeMutation = useUpdateNode(activeTreeId ?? "");
  const [isHovered, setIsHovered] = useState(false);
  const [isEditing, setIsEditing] = useState(false);
  const [draftLabel, setDraftLabel] = useState(node.label);
  const inputRef = useRef<HTMLInputElement>(null);
  const showControls = selected || isHovered;

  const linkHandleClass = (position: "top" | "bottom") =>
    twMerge(
      "pointer-events-auto absolute left-1/2 z-10 h-3 w-16 -translate-x-1/2 rounded-full border border-slate-500/70 bg-slate-100/80 shadow-sm transition-opacity duration-150",
      position === "top" ? "-top-3" : "-bottom-3",
      showControls ? "opacity-80" : "opacity-0"
    );

  const linkTargetClass = (position: "top" | "bottom") =>
    twMerge(
      "pointer-events-auto absolute left-1/2 z-0 h-4 w-24 -translate-x-1/2 rounded-full border border-slate-400/40 bg-slate-100/30 transition-opacity duration-150",
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

  const handleSubmitLabel = () => {
    const trimmedLabel = draftLabel.trim();
    setIsEditing(false);

    if (!activeTreeId || !trimmedLabel || trimmedLabel === node.label) {
      return;
    }

    updateNodeMutation.mutate({ nodeId: node.id, payload: { label: trimmedLabel } });
  };

  const lineHeight = 1.1;
  const fontSize = useMemo(() => {
    const length = (isEditing ? draftLabel : node.label).length || 1;
    const clamped = Math.max(11, 20 - length * 0.25);
    return Math.min(20, clamped);
  }, [draftLabel, isEditing, node.label]);

  return (
    <div
      className={twMerge(
        "group relative h-full min-h-[96px] min-w-[200px] max-w-[280px] rounded-l-2xl rounded-r-xl border border-slate-600/60 bg-slate-900/70 text-left shadow-lg transition-all duration-150",
        selected ? "ring-2 ring-slate-200/60 shadow-glow" : "ring-1 ring-transparent"
      )}
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
    >
      <Handle
        id="link-up-source"
        type="source"
        position={Position.Top}
        className={linkHandleClass("top")}
        aria-label="Link to parent"
      />
      <Handle
        id="link-up-target"
        type="target"
        position={Position.Top}
        isConnectableStart={false}
        className={linkTargetClass("top")}
        aria-label="Accept parent link"
      />
      <Handle
        id="link-down-source"
        type="source"
        position={Position.Bottom}
        className={linkHandleClass("bottom")}
        aria-label="Link to child"
      />
      <Handle
        id="link-down-target"
        type="target"
        position={Position.Bottom}
        isConnectableStart={false}
        className={linkTargetClass("bottom")}
        aria-label="Accept child link"
      />

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

      <div className="flex h-full w-full items-center justify-center px-5 py-4" onDoubleClick={() => setIsEditing(true)}>
        {isEditing ? (
          <input
            ref={inputRef}
            value={draftLabel}
            onChange={(event) => setDraftLabel(event.target.value)}
            onBlur={handleSubmitLabel}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.preventDefault();
                handleSubmitLabel();
              } else if (event.key === "Escape") {
                event.preventDefault();
                setDraftLabel(node.label);
                setIsEditing(false);
              }
            }}
            className="w-full rounded-lg border border-slate-400/50 bg-slate-900/70 px-2 py-1 text-center text-slate-50 shadow-inner outline-none ring-1 ring-slate-500/40 focus:ring-2 focus:ring-brand-primary"
            style={{ fontSize, lineHeight }}
          />
        ) : (
          <p
            className="w-full break-words text-center font-semibold leading-tight tracking-tight text-slate-50"
            style={{ fontSize, lineHeight }}
          >
            {node.label}
          </p>
        )}
      </div>
    </div>
  );
}
