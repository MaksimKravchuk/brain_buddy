import { FormEvent, useState } from "react";

import { useCreateTree } from "../../api/hooks";
import type { TreeDetailResponse } from "../../api/types";
import { useUiStore } from "../../stores/uiStore";
import { getErrorMessage } from "../../utils/error";

interface CreateTreeModalProps {
  onCreated: (tree: TreeDetailResponse) => void;
}

export function CreateTreeModal({ onCreated }: CreateTreeModalProps): JSX.Element | null {
  const isOpen = useUiStore((state) => state.modals.createTree);
  const closeModal = useUiStore((state) => state.closeModal);
  const pushToast = useUiStore((state) => state.pushToast);
  const [name, setName] = useState("");

  const createTreeMutation = useCreateTree();

  if (!isOpen) {
    return null;
  }

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();

    if (!name.trim()) {
      pushToast({
        title: "Name required",
        description: "Please provide a name for the tree.",
        variant: "warning",
        duration: 4000
      });
      return;
    }

    createTreeMutation.mutate(
      { name: name.trim() },
      {
        onSuccess: (tree) => {
          pushToast({
            title: "Tree created",
            description: "A new tree is ready to edit.",
            variant: "success",
            duration: 3000
          });
          setName("");
          onCreated(tree);
          closeModal("createTree");
        },
        onError: (error) => {
          pushToast({
            title: "Failed to create tree",
            description: getErrorMessage(error),
            variant: "error",
            duration: 6000
          });
        }
      }
    );
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-surface-base/80 backdrop-blur">
      <form
        onSubmit={handleSubmit}
        className="w-full max-w-md space-y-5 rounded-2xl border border-slate-700 bg-surface-sunken/90 p-6 shadow-2xl"
      >
        <header className="space-y-1">
          <h2 className="text-lg font-semibold text-slate-100">Create a new tree</h2>
          <p className="text-sm text-slate-400">Provide a name to get started.</p>
        </header>

        <div className="space-y-2">
          <label htmlFor="new-tree-name" className="text-xs font-semibold uppercase tracking-wide text-slate-400">
            Name
          </label>
          <input
            id="new-tree-name"
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="Current reality tree"
            className="w-full rounded-lg border border-slate-700 bg-surface-base px-3 py-2 text-sm text-slate-100 shadow-inner focus:border-brand-primary focus:outline-none"
          />
        </div>

        <div className="flex items-center justify-end gap-2">
          <button
            type="button"
            onClick={() => {
              closeModal("createTree");
              setName("");
            }}
            className="rounded-md border border-slate-600 px-4 py-2 text-sm font-medium text-slate-300 transition hover:border-slate-400 hover:text-slate-100"
          >
            Cancel
          </button>
          <button
            type="submit"
            className="rounded-md bg-brand-primary/90 px-4 py-2 text-sm font-semibold text-slate-950 transition hover:bg-brand-primary disabled:cursor-not-allowed disabled:opacity-60"
            disabled={createTreeMutation.isPending}
          >
            {createTreeMutation.isPending ? "Creating…" : "Create tree"}
          </button>
        </div>
      </form>
    </div>
  );
}
