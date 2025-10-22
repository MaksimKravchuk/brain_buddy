import type { ChangeEvent } from "react";

import type { TreeListItem } from "../../api/types";
import { useUiStore } from "../../stores/uiStore";

interface TreeSelectorProps {
  trees: TreeListItem[] | undefined;
  value: string | null;
  onChange: (treeId: string) => void;
  isLoading?: boolean;
}

export function TreeSelector({ trees, value, onChange, isLoading }: TreeSelectorProps): JSX.Element {
  const openModal = useUiStore((state) => state.openModal);

  const handleChange = (event: ChangeEvent<HTMLSelectElement>) => {
    onChange(event.target.value);
  };

  return (
    <div className="flex items-center gap-3">
      <select
        value={value ?? ""}
        onChange={handleChange}
        disabled={isLoading || !trees?.length}
        className="rounded-lg border border-slate-700 bg-surface-base px-3 py-2 text-sm text-slate-100 shadow-inner focus:border-brand-primary focus:outline-none disabled:cursor-not-allowed disabled:opacity-50"
      >
        <option value="" disabled>
          {isLoading ? "Loading trees…" : "Select tree"}
        </option>
        {trees?.map((tree) => (
          <option key={tree.id} value={tree.id}>
            {tree.title}
          </option>
        ))}
      </select>
      <button
        type="button"
        onClick={() => openModal("createTree")}
        className="rounded-md border border-slate-600 px-3 py-2 text-sm font-medium text-slate-200 transition hover:border-brand-primary hover:text-brand-primary"
      >
        New Tree
      </button>
    </div>
  );
}
