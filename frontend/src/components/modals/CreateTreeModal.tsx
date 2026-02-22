import { FormEvent, useState } from "react";
import { twMerge } from "tailwind-merge";

import { useCreateTree } from "../../api/hooks";
import type { TreeDetailResponse } from "../../api/types";
import { useDelayedUnmount } from "../../hooks/useDelayedUnmount";
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
  const { shouldRender, isAnimatingOut } = useDelayedUnmount(isOpen, 200);

  const createTreeMutation = useCreateTree();

  if (!shouldRender) {
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
    <div
      className={twMerge(
        "fixed inset-0 z-50 flex items-center justify-center backdrop-blur transition-all duration-200",
        isAnimatingOut ? "bg-transparent opacity-0" : "bg-surface-base/80 opacity-100"
      )}
    >
      <form
        onSubmit={handleSubmit}
        className={twMerge(
          "w-full max-w-md space-y-5 rounded-2xl border border-slate-200 bg-white/90 p-6 shadow-xl transition-all duration-200",
          isAnimatingOut ? "scale-95 opacity-0" : "animate-scale-fade-in"
        )}
      >
        <header className="space-y-1">
          <h2 className="text-lg font-semibold text-slate-900">Create a new tree</h2>
          <p className="text-sm text-slate-500">Provide a name to get started.</p>
        </header>

        <div className="space-y-2">
          <label htmlFor="new-tree-name" className="text-xs font-semibold uppercase tracking-wide text-slate-500">
            Name
          </label>
          <input
            id="new-tree-name"
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="Current reality tree"
            className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900 shadow-sm focus:border-brand-primary focus:outline-none focus:ring-2 focus:ring-brand-primary/20"
          />
        </div>

        <div className="flex items-center justify-end gap-2">
          <button
            type="button"
            onClick={() => {
              closeModal("createTree");
              setName("");
            }}
            className="rounded-md border border-slate-200 px-4 py-2 text-sm font-medium text-slate-600 transition hover:border-slate-300 hover:text-slate-800"
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
