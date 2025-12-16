import { useMemo, useState } from "react";
import type { NodeProps } from "reactflow";
import { Handle, NodeResizer, Position } from "reactflow";
import { twMerge } from "tailwind-merge";

import type { GraphNode } from "../../stores/treeStore";

export interface BrainNodeData {
  node: GraphNode;
}

const HANDLE_POSITIONS: { id: string; position: Position }[] = [
  { id: "top", position: Position.Top },
  { id: "right", position: Position.Right },
  { id: "bottom", position: Position.Bottom },
  { id: "left", position: Position.Left }
];

export function BrainNode({ data, selected }: NodeProps<BrainNodeData>): JSX.Element {
  const { node } = data;
  const [isHovered, setIsHovered] = useState(false);
  const showControls = selected || isHovered;

  const baseHandleClass = useMemo(
    () =>
      twMerge(
        "!h-3 !w-3 !rounded-full !border !border-slate-600/80 !bg-slate-100 shadow-sm transition-opacity duration-150",
        showControls ? "opacity-100" : "opacity-0 group-hover:opacity-100"
      ),
    [showControls]
  );

  return (
    <div
      className={twMerge(
        "group relative h-full min-h-[90px] min-w-[180px] rounded-l-2xl rounded-r-xl border border-slate-600/60 bg-slate-900/70 text-left shadow-lg transition-all duration-150",
        selected ? "ring-2 ring-slate-200/60 shadow-glow" : "ring-1 ring-transparent"
      )}
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
    >
      <NodeResizer
        minWidth={160}
        minHeight={80}
        isVisible={showControls}
        handleClassName="!h-2.5 !w-2.5 !rounded-full !border !border-slate-600/80 !bg-slate-100"
        lineClassName="!border-slate-600/50"
      />

      {HANDLE_POSITIONS.map((handle) => (
        <Handle
          key={`${handle.id}-source`}
          type="source"
          id={`${handle.id}-source`}
          position={handle.position}
          className={baseHandleClass}
        />
      ))}

      {HANDLE_POSITIONS.map((handle) => (
        <Handle
          key={`${handle.id}-target`}
          type="target"
          id={`${handle.id}-target`}
          position={handle.position}
          className={baseHandleClass}
        />
      ))}

      <div className="pointer-events-none absolute inset-y-0 left-0 w-2 rounded-l-2xl bg-slate-200/10" />

      <div className="flex h-full w-full items-center justify-center px-4 py-3">
        <p className="w-full break-words text-center font-medium leading-tight text-[clamp(12px,1.6vw,18px)] tracking-tight text-slate-50">
          {node.label}
        </p>
      </div>
    </div>
  );
}
