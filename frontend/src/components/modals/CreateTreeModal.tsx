import { FormEvent, useState } from "react";
import { PlusCircle } from "lucide-react";
import { twMerge } from "tailwind-merge";

import { useCreateTree } from "../../api/hooks";
import type { TreeDetailResponse } from "../../api/types";
import { useDelayedUnmount } from "../../hooks/useDelayedUnmount";
import { useUiStore } from "../../stores/uiStore";
import { getErrorMessage } from "../../utils/error";
import { Button } from "../ui/Button";

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
          "w-full max-w-md space-y-5 rounded-2xl border border-slate-200 bg-white/95 p-6 shadow-floating transition-all duration-200 ease-smooth",
          isAnimatingOut ? "scale-95 opacity-0" : "animate-scale-fade-in"
        )}
      >
        <header className="flex items-start gap-3">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-brand-primary/10 text-brand-primary">
            <PlusCircle className="h-5 w-5" />
          </div>
          <div className="flex-1 space-y-1">
            <h2 className="text-title font-semibold text-slate-900">
              Create a new tree
            </h2>
            <p className="text-sm text-slate-500">Provide a name to get started.</p>
          </div>
        </header>

        <div className="space-y-2">
          <label
            htmlFor="new-tree-name"
            className="text-xs font-semibold uppercase tracking-wide text-slate-500"
          >
            Name
          </label>
          <input
            id="new-tree-name"
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="Current reality tree"
            autoFocus
            className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900 shadow-soft transition-colors duration-200 ease-smooth focus:border-brand-primary focus:outline-none"
          />
        </div>

        <div className="flex items-center justify-end gap-2">
          <Button
            variant="secondary"
            size="md"
            onClick={() => {
              closeModal("createTree");
              setName("");
            }}
          >
            Cancel
          </Button>
          <Button
            type="submit"
            variant="primary"
            size="md"
            isLoading={createTreeMutation.isPending}
          >
            Create tree
          </Button>
        </div>
      </form>
    </div>
  );
}
