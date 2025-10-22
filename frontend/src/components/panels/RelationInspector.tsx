import { useEffect, useState } from "react";

import { useDeleteRelation, useUpdateRelation } from "../../api/hooks";
import { useTreeStore } from "../../stores/treeStore";
import { useUiStore } from "../../stores/uiStore";
import { getErrorMessage } from "../../utils/error";

export function RelationInspector(): JSX.Element {
  const activeTreeId = useTreeStore((state) => state.activeTreeId);
  const selection = useTreeStore((state) => state.selection);
  const relation = useTreeStore((state) =>
    selection.type === "relation" ? state.relations.find((item) => item.id === selection.id) : undefined
  );
  const upsertRelation = useTreeStore((state) => state.upsertRelation);
  const removeRelation = useTreeStore((state) => state.removeRelation);
  const pushSnapshot = useTreeStore((state) => state.pushSnapshot);
  const beginOptimisticChange = useTreeStore((state) => state.beginOptimisticChange);
  const resolveOptimisticChange = useTreeStore((state) => state.resolveOptimisticChange);
  const rollbackOptimisticChange = useTreeStore((state) => state.rollbackOptimisticChange);
  const select = useTreeStore((state) => state.select);

  const pushToast = useUiStore((state) => state.pushToast);

  const [questionLabel, setQuestionLabel] = useState(relation?.questionLabel ?? "WHY?");
  const [notes, setNotes] = useState(relation?.notes ?? "");

  useEffect(() => {
    setQuestionLabel(relation?.questionLabel ?? "WHY?");
    setNotes(relation?.notes ?? "");
  }, [relation?.id, relation?.questionLabel, relation?.notes]);

  if (!activeTreeId) {
    return <InspectorPlaceholder message="Select a tree to inspect relations." />;
  }

  if (!relation) {
    return <InspectorPlaceholder message="Select a relation by clicking an edge on the canvas." />;
  }

  const updateRelationMutation = useUpdateRelation(activeTreeId);
  const deleteRelationMutation = useDeleteRelation(activeTreeId);

  const handleSave = () => {
    const trimmedLabel = questionLabel.trim() || "WHY?";
    const trimmedNotes = notes.trim();

    if (trimmedLabel === relation.questionLabel && (trimmedNotes || "") === (relation.notes || "")) {
      return;
    }

    pushSnapshot();
    const token = beginOptimisticChange("update-relation");
    upsertRelation({
      ...relation,
      questionLabel: trimmedLabel,
      notes: trimmedNotes || null,
      metadata: {
        ...relation.metadata,
        updatedAt: new Date().toISOString()
      }
    });

    updateRelationMutation.mutate(
      {
        relationId: relation.id,
        payload: { question_label: trimmedLabel, notes: trimmedNotes || null }
      },
      {
        onSuccess: () => {
          resolveOptimisticChange(token);
          pushToast({
            title: "Relation updated",
            description: "Changes saved.",
            variant: "success",
            duration: 2500
          });
        },
        onError: (error) => {
          rollbackOptimisticChange(token);
          pushToast({
            title: "Failed to update relation",
            description: getErrorMessage(error),
            variant: "error",
            duration: 6000
          });
        }
      }
    );
  };

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
      <div className="space-y-2">
        <label htmlFor="relation-question" className="text-xs font-semibold uppercase tracking-wide text-slate-400">
          Question Label
        </label>
        <input
          id="relation-question"
          value={questionLabel}
          onChange={(event) => setQuestionLabel(event.target.value)}
          onBlur={handleSave}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              event.preventDefault();
              handleSave();
            }
          }}
          className="w-full rounded-lg border border-slate-700 bg-surface-base px-3 py-2 text-sm text-slate-100 shadow-inner focus:border-brand-primary focus:outline-none"
        />
      </div>

      <div className="space-y-2">
        <label htmlFor="relation-notes" className="text-xs font-semibold uppercase tracking-wide text-slate-400">
          Notes
        </label>
        <textarea
          id="relation-notes"
          value={notes}
          onChange={(event) => setNotes(event.target.value)}
          onBlur={handleSave}
          rows={4}
          className="w-full resize-none rounded-lg border border-slate-700 bg-surface-base px-3 py-2 text-sm text-slate-100 shadow-inner focus:border-brand-primary focus:outline-none"
        />
        <p className="text-xs text-slate-500">Describe how the source explains the target.</p>
      </div>

      <div className="space-y-2 rounded-lg border border-slate-800 bg-surface-sunken/60 p-3 text-xs text-slate-400">
        <MetadataRow label="Source node" value={relation.sourceId} />
        <MetadataRow label="Target node" value={relation.targetId} />
        <MetadataRow label="Updated" value={new Date(relation.metadata.updatedAt).toLocaleString()} />
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
