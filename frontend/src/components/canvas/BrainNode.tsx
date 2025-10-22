import type { NodeProps } from "reactflow";
import { Handle, Position } from "reactflow";
import { twMerge } from "tailwind-merge";

import type { GraphNode } from "../../stores/treeStore";

export interface BrainNodeData {
  node: GraphNode;
}

export function BrainNode({ data, selected }: NodeProps<BrainNodeData>): JSX.Element {
  const { node } = data;
  const isValidated = Boolean(node.validation);
  const validationBadge = node.validation ? `${node.validation.confidence}%` : "–";

  return (
    <div
      className={twMerge(
        "group relative rounded-xl border border-slate-800/80 bg-surface-raised px-4 py-3 text-left shadow-lg ring-1 ring-transparent transition-all duration-150",
        selected ? "border-brand-primary/80 shadow-glow ring-brand-primary/50" : "",
        node.visual?.highlight ? "ring-2 ring-brand-secondary/60" : ""
      )}
    >
      <Handle type="target" position={Position.Top} className="h-2 w-2 rounded-full bg-brand-secondary" />
      <Handle type="source" position={Position.Bottom} className="h-2 w-2 rounded-full bg-brand-primary" />

      <div className="flex items-start justify-between gap-3">
        <p className="max-w-[180px] break-words text-sm font-medium text-slate-100">{node.label}</p>
        <span
          className={twMerge(
            "rounded-full px-2 py-0.5 text-xs font-semibold",
            isValidated ? "bg-emerald-500/20 text-emerald-300" : "bg-slate-700/60 text-slate-300"
          )}
        >
          {validationBadge}
        </span>
      </div>

      <div className="mt-3 flex items-center gap-3 text-xs text-slate-400">
        <span className="flex items-center gap-1">
          <span className="inline-flex h-2 w-2 rounded-full bg-brand-secondary/80" /> {node.incomingCount}
        </span>
        <span className="flex items-center gap-1">
          <span className="inline-flex h-2 w-2 rounded-full bg-brand-primary/80" /> {node.outgoingCount}
        </span>
        {node.metadata.author ? <span className="truncate text-slate-500">by {node.metadata.author}</span> : null}
      </div>
    </div>
  );
}
