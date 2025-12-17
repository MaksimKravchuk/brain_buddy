import { useMemo, useState } from "react";
import type { NodeProps } from "reactflow";
import { Handle, Position } from "reactflow";
import { twMerge } from "tailwind-merge";

import type { GraphNode } from "../../stores/treeStore";

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

  const fontSize = useMemo(() => {
    const length = node.label.length || 1;
    const clamped = Math.max(11, 20 - length * 0.25);
    return Math.min(20, clamped);
  }, [node.label.length]);

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

      <div className="flex h-full w-full items-center justify-center px-5 py-4">
        <p
          className="w-full break-words text-center font-semibold leading-tight tracking-tight text-slate-50"
          style={{ fontSize }}
        >
          {node.label}
        </p>
      </div>
    </div>
  );
}
