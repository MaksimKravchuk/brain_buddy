import type { NodeProps } from "reactflow";
import { Handle, Position } from "reactflow";
import { twMerge } from "tailwind-merge";

import type { GraphNode } from "../../stores/treeStore";

export interface BrainNodeData {
  node: GraphNode;
}

export function BrainNode({ data, selected }: NodeProps<BrainNodeData>): JSX.Element {
  const { node } = data;
  const typeStyles =
    node.type === "undesired_effect"
      ? {
          badge: "bg-rose-500/20 text-rose-200 border border-rose-500/50",
          container: "border-rose-500/30 bg-gradient-to-b from-rose-900/40 to-surface-raised"
        }
      : node.type === "cause"
        ? {
            badge: "bg-amber-500/20 text-amber-200 border border-amber-500/40",
            container: "border-amber-500/30 bg-gradient-to-b from-amber-900/30 to-surface-raised"
          }
        : {
            badge: "bg-sky-500/20 text-sky-200 border border-sky-500/40",
            container: "border-sky-500/30 bg-gradient-to-b from-sky-900/30 to-surface-raised"
          };
  const highlightRing =
    node.highlightState === "cause_candidate"
      ? "ring-2 ring-amber-400/70 shadow-[0_0_0_6px_rgba(251,191,36,0.25)]"
      : node.highlightState === "effect_spanning"
        ? "ring-2 ring-rose-400/70 shadow-[0_0_0_6px_rgba(248,113,113,0.25)]"
        : "";

  return (
    <div
      className={twMerge(
        "group relative rounded-xl border px-4 py-3 text-left shadow-lg ring-1 ring-transparent transition-all duration-150",
        typeStyles.container,
        selected ? "border-brand-primary/80 shadow-glow ring-brand-primary/50" : "",
        highlightRing
      )}
    >
      <Handle
        type="target"
        position={Position.Top}
        className="h-2 w-2 rounded-full bg-brand-secondary ring-2 ring-slate-900"
      />
      <Handle
        type="source"
        position={Position.Bottom}
        className="h-2 w-2 rounded-full bg-brand-primary ring-2 ring-slate-900"
      />

      <div className="flex items-start justify-between gap-3">
        <p className="max-w-[180px] break-words text-sm font-medium text-slate-100">{node.label}</p>
        <span className={twMerge("rounded-full px-2 py-0.5 text-[11px] font-semibold", typeStyles.badge)}>
          {node.type.replace("_", " ")}
        </span>
      </div>

      <div className="mt-3 flex items-center gap-3 text-xs text-slate-400">
        <span className="flex items-center gap-1">
          <span className="inline-flex h-2 w-2 rounded-full bg-brand-secondary/80" /> {node.relationCounts.up}
        </span>
        <span className="flex items-center gap-1">
          <span className="inline-flex h-2 w-2 rounded-full bg-brand-primary/80" /> {node.relationCounts.down}
        </span>
      </div>
    </div>
  );
}
