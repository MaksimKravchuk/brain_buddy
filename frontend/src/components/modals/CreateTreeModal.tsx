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
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");

  const createTreeMutation = useCreateTree();

  if (!isOpen) {
    return null;
  }

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();

    if (!title.trim()) {
      pushToast({
        title: "Title required",
        description: "Please provide a name for the tree.",
        variant: "warning",
        duration: 4000
      });
      return;
    }

    createTreeMutation.mutate(
      { title: title.trim(), description: description.trim() || null },
      {
        onSuccess: (tree) => {
          pushToast({
            title: "Tree created",
            description: "A new tree is ready to edit.",
            variant: "success",
            duration: 3000
          });
          setTitle("");
          setDescription("");
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
          <p className="text-sm text-slate-400">Provide a title and optional description to get started.</p>
        </header>

        <div className="space-y-2">
          <label htmlFor="new-tree-title" className="text-xs font-semibold uppercase tracking-wide text-slate-400">
            Title
          </label>
          <input
            id="new-tree-title"
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            placeholder="Customer research tree"
            className="w-full rounded-lg border border-slate-700 bg-surface-base px-3 py-2 text-sm text-slate-100 shadow-inner focus:border-brand-primary focus:outline-none"
          />
        </div>

        <div className="space-y-2">
          <label
            htmlFor="new-tree-description"
            className="text-xs font-semibold uppercase tracking-wide text-slate-400"
          >
            Description <span className="text-[10px] text-slate-500">(optional)</span>
          </label>
          <textarea
            id="new-tree-description"
            value={description}
            onChange={(event) => setDescription(event.target.value)}
            rows={3}
            placeholder="Outline the goal or hypothesis."
            className="w-full resize-none rounded-lg border border-slate-700 bg-surface-base px-3 py-2 text-sm text-slate-100 shadow-inner focus:border-brand-primary focus:outline-none"
          />
        </div>

        <div className="flex items-center justify-end gap-2">
          <button
            type="button"
            onClick={() => {
              closeModal("createTree");
              setTitle("");
              setDescription("");
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
