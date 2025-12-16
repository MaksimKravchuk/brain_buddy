import { useMemo, useState } from "react";
import { twMerge } from "tailwind-merge";

import type { GraphNode } from "../stores/treeStore";
import { buttonVariants } from "../styles/buttonVariants";

interface CreateNodeButtonProps {
  disabled?: boolean;
  onCreate: (input: { type: GraphNode["type"]; label: string }) => void;
}

const typeOptions: { value: GraphNode["type"]; label: string; accent: string }[] = [
  { value: "parent", label: "Parent", accent: "bg-slate-200/10 text-slate-50" },
  { value: "child", label: "Child", accent: "bg-slate-200/10 text-slate-50" }
];

export function CreateNodeButton({ onCreate, disabled }: CreateNodeButtonProps): JSX.Element {
  const [nodeType, setNodeType] = useState<GraphNode["type"]>("child");
  const [label, setLabel] = useState("");

  const activeAccent = useMemo(() => typeOptions.find((item) => item.value === nodeType)?.accent, [nodeType]);

  const handleSubmit = () => {
    const trimmed = label.trim();
    onCreate({
      type: nodeType,
      label: trimmed || (nodeType === "parent" ? "Parent" : "Child")
    });
    setLabel("");
  };

  return (
    <div className="flex w-full flex-col gap-2">
      <div className="flex gap-2">
        {typeOptions.map((option) => (
          <button
            key={option.value}
            type="button"
            onClick={() => setNodeType(option.value)}
            className={twMerge(
              "flex-1 rounded-md border border-slate-700 px-2 py-1 text-xs font-semibold transition hover:border-slate-500",
              nodeType === option.value ? `${option.accent} ring-1 ring-offset-2 ring-offset-slate-900` : "text-slate-200"
            )}
          >
            {option.label}
          </button>
        ))}
      </div>

      <div className="flex gap-2">
        <input
          value={label}
          onChange={(event) => setLabel(event.target.value)}
          placeholder="Node label"
          className="w-full rounded-md border border-slate-700 bg-surface-sunken px-3 py-2 text-sm text-slate-100 outline-none transition focus:border-slate-400"
        />
        <button
          type="button"
          disabled={disabled}
          onClick={handleSubmit}
          className={twMerge(
            buttonVariants({ intent: "primary" }),
            "shrink-0 px-4",
            activeAccent,
            disabled ? "cursor-not-allowed opacity-70" : ""
          )}
        >
          Add
        </button>
      </div>
    </div>
  );
}
