import { useMemo, useState } from "react";
import { twMerge } from "tailwind-merge";

import type { GraphNode } from "../stores/treeStore";
import { buttonVariants } from "../styles/buttonVariants";

interface CreateNodeButtonProps {
  disabled?: boolean;
  onCreate: (input: { type: GraphNode["type"]; label: string }) => void;
}

const typeOptions: { value: GraphNode["type"]; label: string; accent: string }[] = [
  { value: "effect", label: "Effect", accent: "bg-sky-100 text-slate-900" },
  { value: "cause", label: "Cause", accent: "bg-sky-100 text-slate-900" }
];

export function CreateNodeButton({ onCreate, disabled }: CreateNodeButtonProps): JSX.Element {
  const [nodeType, setNodeType] = useState<GraphNode["type"]>("cause");
  const [label, setLabel] = useState("");

  const activeAccent = useMemo(() => typeOptions.find((item) => item.value === nodeType)?.accent, [nodeType]);

  const handleSubmit = () => {
    const trimmed = label.trim();
    onCreate({
      type: nodeType,
      label: trimmed || (nodeType === "effect" ? "Effect" : "Cause")
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
              "flex-1 rounded-md border border-slate-200 px-2 py-1 text-xs font-semibold text-slate-600 transition hover:border-slate-300",
              nodeType === option.value ? `${option.accent} ring-1 ring-offset-2 ring-offset-white` : ""
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
          className="w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900 outline-none transition focus:border-brand-primary focus:ring-2 focus:ring-brand-primary/20"
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
