import { useMemo } from "react";

import { useDeleteTree } from "../../api/hooks";
import type { TreeListItem } from "../../api/types";
import { useTreeStore } from "../../stores/treeStore";
import { useUiStore } from "../../stores/uiStore";
import { getErrorMessage } from "../../utils/error";

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

  if (!isOpen || !activeTree) {
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
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-surface-base/80 backdrop-blur">
      <div className="w-full max-w-md space-y-4 rounded-2xl border border-slate-200 bg-white/90 p-6 shadow-xl">
        <header className="space-y-1">
          <h2 className="text-lg font-semibold text-slate-900">Delete tree</h2>
          <p className="text-sm text-slate-600">
            This will permanently delete “{activeTree.name}” including its nodes, relations, and versions. This action
            cannot be undone.
          </p>
        </header>

        <div className="rounded-lg border border-amber-200 bg-amber-50/80 p-3 text-xs text-amber-800">
          Consider exporting a copy before deleting if you might need it later.
        </div>

        <div className="flex items-center justify-end gap-2">
          <button
            type="button"
            onClick={() => closeModal("deleteTree")}
            className="rounded-md border border-slate-200 px-4 py-2 text-sm font-medium text-slate-700 transition hover:border-slate-300 hover:text-slate-900 disabled:cursor-not-allowed disabled:opacity-60"
            disabled={deleteTree.isPending}
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={handleConfirm}
            className="rounded-md bg-rose-500/90 px-4 py-2 text-sm font-semibold text-white shadow-sm transition hover:bg-rose-500 disabled:cursor-not-allowed disabled:opacity-60"
            disabled={deleteTree.isPending}
          >
            {deleteTree.isPending ? "Deleting…" : "Delete"}
          </button>
        </div>
      </div>
    </div>
  );
}
