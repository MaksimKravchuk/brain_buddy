import { ArrowRight, Tag, Trash2 } from "lucide-react";

import { useDeleteRelation } from "../../api/hooks";
import { useTreeStore } from "../../stores/treeStore";
import { useUiStore } from "../../stores/uiStore";
import { getErrorMessage } from "../../utils/error";
import { Button } from "../ui/Button";
import { InspectorPlaceholder } from "./InspectorPlaceholder";

export function RelationInspector(): JSX.Element {
  const activeTreeId = useTreeStore((state) => state.activeTreeId);
  const selection = useTreeStore((state) => state.selection);
  const relation = useTreeStore((state) =>
    selection.type === "relation"
      ? state.relations.find((item) => item.id === selection.id)
      : undefined
  );
  const removeRelation = useTreeStore((state) => state.removeRelation);
  const pushSnapshot = useTreeStore((state) => state.pushSnapshot);
  const beginOptimisticChange = useTreeStore(
    (state) => state.beginOptimisticChange
  );
  const resolveOptimisticChange = useTreeStore(
    (state) => state.resolveOptimisticChange
  );
  const rollbackOptimisticChange = useTreeStore(
    (state) => state.rollbackOptimisticChange
  );
  const select = useTreeStore((state) => state.select);

  const pushToast = useUiStore((state) => state.pushToast);

  // Keep the hook call order stable — the mutation is only triggered once a
  // relation is selected, so an empty tree id is harmless.
  const deleteRelationMutation = useDeleteRelation(activeTreeId ?? "");

  if (!activeTreeId) {
    return <InspectorPlaceholder message="Select a tree to inspect relations." />;
  }

  if (!relation) {
    return (
      <InspectorPlaceholder message="Select a relation by clicking an edge on the canvas." />
    );
  }

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
    <div className="space-y-5 animate-fade-in">
      <section className="space-y-3 rounded-xl border border-slate-200 bg-surface-sunken/60 p-3">
        <div className="inline-flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-slate-500">
          <Tag className="h-3.5 w-3.5" />
          Relation
        </div>
        <div className="flex items-center gap-2 rounded-lg bg-white px-3 py-2 text-xs text-slate-700 shadow-soft">
          <code className="truncate font-mono text-[11px] text-slate-600">
            {relation.fromId}
          </code>
          <ArrowRight className="h-3.5 w-3.5 shrink-0 text-brand-primary" />
          <code className="truncate font-mono text-[11px] text-slate-600">
            {relation.toId}
          </code>
        </div>
        <MetadataRow label="Kind" value={relation.kind.toUpperCase()} />
        <MetadataRow
          label="Created"
          value={new Date(relation.createdAt).toLocaleString()}
        />
      </section>

      <Button
        variant="danger"
        size="sm"
        leftIcon={<Trash2 />}
        onClick={handleDelete}
        isLoading={deleteRelationMutation.isPending}
        className="w-full"
      >
        Delete relation
      </Button>
    </div>
  );
}

function MetadataRow({ label, value }: { label: string; value: string }): JSX.Element {
  return (
    <div className="flex items-center justify-between gap-4 text-xs">
      <span className="uppercase tracking-wide text-slate-500">{label}</span>
      <span className="text-slate-700">{value}</span>
    </div>
  );
}
