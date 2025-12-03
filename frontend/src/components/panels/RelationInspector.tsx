import { useDeleteRelation } from "../../api/hooks";
import { useTreeStore } from "../../stores/treeStore";
import { useUiStore } from "../../stores/uiStore";
import { getErrorMessage } from "../../utils/error";

export function RelationInspector(): JSX.Element {
  const activeTreeId = useTreeStore((state) => state.activeTreeId);
  const selection = useTreeStore((state) => state.selection);
  const relation = useTreeStore((state) =>
    selection.type === "relation" ? state.relations.find((item) => item.id === selection.id) : undefined
  );
  const removeRelation = useTreeStore((state) => state.removeRelation);
  const pushSnapshot = useTreeStore((state) => state.pushSnapshot);
  const beginOptimisticChange = useTreeStore((state) => state.beginOptimisticChange);
  const resolveOptimisticChange = useTreeStore((state) => state.resolveOptimisticChange);
  const rollbackOptimisticChange = useTreeStore((state) => state.rollbackOptimisticChange);
  const select = useTreeStore((state) => state.select);

  const pushToast = useUiStore((state) => state.pushToast);
  if (!activeTreeId) {
    return <InspectorPlaceholder message="Select a tree to inspect relations." />;
  }

  if (!relation) {
    return <InspectorPlaceholder message="Select a relation by clicking an edge on the canvas." />;
  }

  const deleteRelationMutation = useDeleteRelation(activeTreeId);

  const handleDelete = () => {
    pushSnapshot();
    const token = beginOptimisticChange("delete-relation");
    removeRelation(relation.id);

    deleteRelationMutation.mutate(relation.id, {
      onSuccess: () => {
        resolveOptimisticChange(token);
        select({ type: null, id: null });
        pushToast({
          title: "Relation removed",
          description: "Relation deleted from the tree.",
          variant: "info",
          duration: 3000
        });
      },
      onError: (error) => {
        rollbackOptimisticChange(token);
        pushToast({
          title: "Failed to delete relation",
          description: getErrorMessage(error),
          variant: "error",
          duration: 6000
        });
      }
    });
  };

  return (
    <div className="space-y-6">
      <div className="space-y-2 rounded-lg border border-slate-800 bg-surface-sunken/60 p-3 text-xs text-slate-400">
        <MetadataRow label="From node" value={relation.fromId} />
        <MetadataRow label="To node" value={relation.toId} />
        <MetadataRow label="Kind" value={relation.kind.toUpperCase()} />
        <MetadataRow label="Created" value={new Date(relation.createdAt).toLocaleString()} />
      </div>

      <button
        type="button"
        onClick={handleDelete}
        className="w-full rounded-md border border-red-500/40 bg-red-500/10 px-3 py-2 text-sm font-semibold text-red-200 transition hover:border-red-400 hover:text-red-100"
      >
        Delete Relation
      </button>
    </div>
  );
}

function InspectorPlaceholder({ message }: { message: string }): JSX.Element {
  return (
    <div className="rounded-lg border border-dashed border-slate-700 bg-surface-sunken/40 p-4 text-sm text-slate-500">
      {message}
    </div>
  );
}

function MetadataRow({ label, value }: { label: string; value: string }): JSX.Element {
  return (
    <div className="flex justify-between gap-4">
      <span className="text-xs uppercase tracking-wide text-slate-500">{label}</span>
      <span className="text-xs text-slate-300">{value}</span>
    </div>
  );
}
