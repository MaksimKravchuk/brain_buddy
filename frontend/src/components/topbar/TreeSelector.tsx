import type { ChangeEvent } from "react";

import type { TreeListItem } from "../../api/types";
import { useUiStore } from "../../stores/uiStore";

interface TreeSelectorProps {
  trees: TreeListItem[] | undefined;
  value: string | null;
  onChange: (treeId: string) => void;
  isLoading?: boolean;
  onSave?: () => void;
  isSaving?: boolean;
  onDownload?: () => void;
  isDownloading?: boolean;
  onImport?: (file: File) => void;
  isImporting?: boolean;
}

export function TreeSelector({
  trees,
  value,
  onChange,
  isLoading,
  onSave,
  isSaving,
  onDownload,
  isDownloading,
  onImport,
  isImporting
}: TreeSelectorProps): JSX.Element {
  const openModal = useUiStore((state) => state.openModal);
  const importInputId = "tree-import-input";

  const handleChange = (event: ChangeEvent<HTMLSelectElement>) => {
    onChange(event.target.value);
  };

  return (
    <div className="flex items-center gap-3">
      <div className="flex items-center gap-2">
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
              {tree.name}
            </option>
          ))}
        </select>
        <button
          type="button"
          onClick={() => openModal("createTree")}
          className="rounded-md border border-slate-600 px-3 py-2 text-sm font-medium text-slate-200 transition hover:border-brand-primary hover:text-brand-primary"
        >
          New
        </button>
      </div>

      <div className="flex items-center gap-2 text-xs text-slate-200">
        <button
          type="button"
          onClick={onSave}
          disabled={!onSave || isSaving}
          className="rounded-md border border-slate-700 bg-surface-sunken px-3 py-2 font-semibold transition hover:border-brand-primary hover:text-brand-primary disabled:cursor-not-allowed disabled:opacity-50"
        >
          {isSaving ? "Saving…" : "Save"}
        </button>
        <button
          type="button"
          onClick={onDownload}
          disabled={!onDownload || isDownloading}
          className="rounded-md border border-slate-700 bg-surface-sunken px-3 py-2 font-semibold transition hover:border-slate-500 hover:text-white disabled:cursor-not-allowed disabled:opacity-50"
        >
          {isDownloading ? "Preparing…" : "Download"}
        </button>
        <div>
          <input
            id={importInputId}
            type="file"
            accept="application/json"
            className="hidden"
            onChange={(event) => {
              const file = event.target.files?.[0];
              if (file && onImport) {
                onImport(file);
              }
              event.target.value = "";
            }}
          />
          <label
            htmlFor={importInputId}
            className={`cursor-pointer rounded-md border border-slate-700 bg-surface-sunken px-3 py-2 font-semibold transition hover:border-slate-500 hover:text-white ${
              isImporting || !onImport ? "pointer-events-none opacity-50" : ""
            }`}
          >
            {isImporting ? "Importing…" : "Import"}
          </label>
        </div>
      </div>
    </div>
  );
}
