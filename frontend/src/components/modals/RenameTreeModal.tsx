import { FormEvent, useEffect, useState } from "react";
import { Pencil } from "lucide-react";
import { twMerge } from "tailwind-merge";

import { useRenameTree } from "../../api/hooks";
import { useDelayedUnmount } from "../../hooks/useDelayedUnmount";
import { useTreeStore } from "../../stores/treeStore";
import { useUiStore } from "../../stores/uiStore";
import { getErrorMessage } from "../../utils/error";
import { Button } from "../ui/Button";

export function RenameTreeModal(): JSX.Element | null {
  const isOpen = useUiStore((state) => state.modals.renameTree);
  const closeModal = useUiStore((state) => state.closeModal);
  const pushToast = useUiStore((state) => state.pushToast);
  const activeTreeId = useTreeStore((state) => state.activeTreeId);
  const currentName = useTreeStore((state) => state.metadata?.name ?? "");
  const [name, setName] = useState(currentName);
  const { shouldRender, isAnimatingOut } = useDelayedUnmount(isOpen, 200);

  const renameMutation = useRenameTree(activeTreeId);

  // Reset the input whenever the modal opens so it reflects the latest name.
  useEffect(() => {
    if (isOpen) {
      setName(currentName);
    }
  }, [isOpen, currentName]);

  if (!shouldRender) {
    return null;
  }

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const trimmed = name.trim();

    if (!trimmed) {
      pushToast({
        title: "Name required",
        description: "Please provide a name for the tree.",
        variant: "warning",
        duration: 4000
      });
      return;
    }

    if (trimmed === currentName) {
      closeModal("renameTree");
      return;
    }

    renameMutation.mutate(trimmed, {
      onSuccess: () => {
        pushToast({
          title: "Tree renamed",
          description: `Now called “${trimmed}”.`,
          variant: "success",
          duration: 3000
        });
        closeModal("renameTree");
      },
      onError: (error) => {
        pushToast({
          title: "Failed to rename tree",
          description: getErrorMessage(error),
          variant: "error",
          duration: 6000
        });
      }
    });
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
            <Pencil className="h-5 w-5" />
          </div>
          <div className="flex-1 space-y-1">
            <h2 className="text-title font-semibold text-slate-900">Rename tree</h2>
            <p className="text-sm text-slate-500">Give this tree a new name.</p>
          </div>
        </header>

        <div className="space-y-2">
          <label
            htmlFor="rename-tree-name"
            className="text-xs font-semibold uppercase tracking-wide text-slate-500"
          >
            Name
          </label>
          <input
            id="rename-tree-name"
            value={name}
            onChange={(event) => setName(event.target.value)}
            autoFocus
            className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900 shadow-soft transition-colors duration-200 ease-smooth focus:border-brand-primary focus:outline-none"
          />
        </div>

        <div className="flex items-center justify-end gap-2">
          <Button
            variant="secondary"
            size="md"
            onClick={() => closeModal("renameTree")}
            disabled={renameMutation.isPending}
          >
            Cancel
          </Button>
          <Button
            type="submit"
            variant="primary"
            size="md"
            isLoading={renameMutation.isPending}
          >
            Save name
          </Button>
        </div>
      </form>
    </div>
  );
}
