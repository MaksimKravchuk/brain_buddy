import { useMemo } from "react";
import { Trash2 } from "lucide-react";
import { twMerge } from "tailwind-merge";

import { useDeleteTree } from "../../api/hooks";
import type { TreeListItem } from "../../api/types";
import { useDelayedUnmount } from "../../hooks/useDelayedUnmount";
import { useTreeStore } from "../../stores/treeStore";
import { useUiStore } from "../../stores/uiStore";
import { getErrorMessage } from "../../utils/error";
import { Button } from "../ui/Button";

interface DeleteTreeModalProps {
  trees: TreeListItem[] | undefined;
  onDeleted: (treeId: string) => void;
}

export function DeleteTreeModal({ trees, onDeleted }: DeleteTreeModalProps): JSX.Element | null {
  const isOpen = useUiStore((state) => state.modals.deleteTree);
  const closeModal = useUiStore((state) => state.closeModal);
  const pushToast = useUiStore((state) => state.pushToast);
  const activeTreeId = useTreeStore((state) => state.activeTreeId);
  const activeTree = useMemo(() => trees?.find((tree) => tree.id === activeTreeId), [trees, activeTreeId]);

  const deleteTree = useDeleteTree();
  const { shouldRender, isAnimatingOut } = useDelayedUnmount(isOpen && !!activeTree, 200);

  if (!shouldRender || !activeTree) {
    return null;
  }

  const handleConfirm = () => {
    deleteTree.mutate(activeTree.id, {
      onSuccess: () => {
        pushToast({
          title: "Tree deleted",
          description: `“${activeTree.name}” was removed.`,
          variant: "success",
          duration: 3500
        });
        onDeleted(activeTree.id);
        closeModal("deleteTree");
      },
      onError: (error) => {
        pushToast({
          title: "Failed to delete tree",
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
      <div
        className={twMerge(
          "w-full max-w-md space-y-5 rounded-2xl border border-slate-200 bg-white/95 p-6 shadow-floating transition-all duration-200 ease-smooth",
          isAnimatingOut ? "scale-95 opacity-0" : "animate-scale-fade-in"
        )}
      >
        <header className="flex items-start gap-3">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-rose-100 text-rose-600">
            <Trash2 className="h-5 w-5" />
          </div>
          <div className="flex-1 space-y-1">
            <h2 className="text-title font-semibold text-slate-900">Delete tree</h2>
            <p className="text-sm text-slate-600">
              This will permanently delete “{activeTree.name}” including its nodes,
              relations, and versions. This action cannot be undone.
            </p>
          </div>
        </header>

        <div className="rounded-lg border border-amber-200 bg-amber-50/80 p-3 text-xs text-amber-800">
          Consider exporting a copy before deleting if you might need it later.
        </div>

        <div className="flex items-center justify-end gap-2">
          <Button
            variant="secondary"
            size="md"
            onClick={() => closeModal("deleteTree")}
            disabled={deleteTree.isPending}
          >
            Cancel
          </Button>
          <Button
            variant="danger"
            size="md"
            onClick={handleConfirm}
            isLoading={deleteTree.isPending}
            leftIcon={<Trash2 />}
          >
            Delete
          </Button>
        </div>
      </div>
    </div>
  );
}
