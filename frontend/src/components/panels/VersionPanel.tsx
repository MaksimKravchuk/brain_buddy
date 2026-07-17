import { useMemo, useState } from "react";
import { Download, History, RotateCcw, Save, Trash2 } from "lucide-react";
import { twMerge } from "tailwind-merge";

import { useCreateVersion, useDeleteVersion, useExportTree, useRestoreVersion } from "../../api/hooks";
import type { VersionListItem } from "../../api/types";
import { useDelayedUnmount } from "../../hooks/useDelayedUnmount";
import { mapVersionResponse, useTreeStore, type GraphVersion } from "../../stores/treeStore";
import { useUiStore } from "../../stores/uiStore";
import { getErrorMessage } from "../../utils/error";
import { Button } from "../ui/Button";
import { InspectorPlaceholder } from "./InspectorPlaceholder";

interface ConfirmState {
  action: "restore" | "delete";
  version: GraphVersion;
}

export function VersionPanel(): JSX.Element {
  const activeTreeId = useTreeStore((state) => state.activeTreeId);
  const versions = useTreeStore((state) => state.versions);
  const setVersions = useTreeStore((state) => state.setVersions);
  const setTree = useTreeStore((state) => state.setTree);
  const metadata = useTreeStore((state) => state.metadata);
  const pushSnapshot = useTreeStore((state) => state.pushSnapshot);
  const pushToast = useUiStore((state) => state.pushToast);

  const [label, setLabel] = useState("");
  const [author, setAuthor] = useState("");
  const [notes, setNotes] = useState("");
  const [confirmState, setConfirmState] = useState<ConfirmState | null>(null);

  const isReady = Boolean(activeTreeId && metadata);
  const treeIdForMutations = activeTreeId ?? "";

  const createVersionMutation = useCreateVersion(treeIdForMutations);
  const deleteVersionMutation = useDeleteVersion(treeIdForMutations);
  const restoreVersionMutation = useRestoreVersion(treeIdForMutations);
  const exportTreeMutation = useExportTree(treeIdForMutations);

  const sortedVersions = useMemo(
    () => [...versions].sort((a, b) => (a.createdAt > b.createdAt ? -1 : 1)),
    [versions]
  );
  const { shouldRender: shouldRenderConfirm, isAnimatingOut: isConfirmAnimatingOut } = useDelayedUnmount(
    confirmState !== null,
    200
  );

  if (!isReady || !metadata) {
    return (
      <InspectorPlaceholder icon={History} message="Select a tree to manage versions." />
    );
  }

  const handleCreate = () => {
    const trimmedLabel = label.trim();
    const trimmedAuthor = author.trim();
    const trimmedNotes = notes.trim();

    const toastId = pushToast({
      title: "Capturing snapshot…",
      description: trimmedLabel || undefined,
      variant: "info",
      duration: 0
    });

    createVersionMutation.mutate(
      {
        label: trimmedLabel || null,
        author: trimmedAuthor || null,
        notes: trimmedNotes || null
      },
      {
        onSuccess: (payload) => {
          const mapped = mapVersionResponse(payload);
          setLabel("");
          setAuthor("");
          setNotes("");
          const currentVersions = useTreeStore.getState().versions;
          setVersions(addVersion(currentVersions, payload));
          pushToast({
            id: toastId,
            title: "Snapshot captured",
            description: formatDiffSummary(mapped.diffSummary),
            variant: "success",
            duration: 3000
          });
        },
        onError: (error) => {
          pushToast({
            id: toastId,
            title: "Failed to create snapshot",
            description: getErrorMessage(error),
            variant: "error",
            duration: 6000
          });
        }
      }
    );
  };

  const handleDeleteConfirmed = (version: GraphVersion) => {
    setConfirmState(null);
    const toastId = pushToast({
      title: "Deleting snapshot…",
      description: version.label,
      variant: "info",
      duration: 0
    });

    deleteVersionMutation.mutate(version.id, {
      onSuccess: () => {
        const currentVersions = useTreeStore.getState().versions;
        setVersions(removeVersion(currentVersions, version.id));
        pushToast({
          id: toastId,
          title: "Snapshot deleted",
          description: `${version.label} removed.`,
          variant: "success",
          duration: 2500
        });
      },
      onError: (error) => {
        pushToast({
          id: toastId,
          title: "Failed to delete snapshot",
          description: getErrorMessage(error),
          variant: "error",
          duration: 6000
        });
      }
    });
  };

  const handleRestoreConfirmed = (version: GraphVersion) => {
    setConfirmState(null);
    pushSnapshot();
    const toastId = pushToast({
      title: "Restoring snapshot…",
      description: version.label,
      variant: "info",
      duration: 0
    });

    restoreVersionMutation.mutate(version.id, {
      onSuccess: (tree) => {
        setTree(tree, { restoreSafe: true });
        pushToast({
          id: toastId,
          title: "Version restored",
          description: `${version.label} applied.`,
          variant: "success",
          duration: 3000
        });
      },
      onError: (error) => {
        pushToast({
          id: toastId,
          title: "Failed to restore version",
          description: getErrorMessage(error),
          variant: "error",
          duration: 6000
        });
      }
    });
  };

  const handleExport = () => {
    const toastId = pushToast({
      title: "Preparing export…",
      variant: "info",
      duration: 0
    });

    exportTreeMutation.mutate(undefined, {
      onSuccess: ({ tree }) => {
        const filename = `${tree.name}-${tree.metadata.updated_at.replace(/[:]/g, "")}.json`;
        const content = JSON.stringify(tree, null, 2);
        if (typeof window !== "undefined") {
          const blob = new Blob([content], { type: "application/json" });
          const url = URL.createObjectURL(blob);
          const anchor = document.createElement("a");
          anchor.href = url;
          anchor.download = filename;
          document.body.appendChild(anchor);
          anchor.click();
          anchor.remove();
          window.setTimeout(() => URL.revokeObjectURL(url), 0);
        }
        pushToast({
          id: toastId,
          title: "Export ready",
          description: filename,
          variant: "success",
          duration: 4000
        });
      },
      onError: (error) => {
        pushToast({
          id: toastId,
          title: "Export failed",
          description: getErrorMessage(error),
          variant: "error",
          duration: 6000
        });
      }
    });
  };

  const isDeleting = deleteVersionMutation.isPending && confirmState?.action === "delete";
  const isRestoring = restoreVersionMutation.isPending && confirmState?.action === "restore";
  return (
    <>
      <div className="space-y-4 animate-fade-in">
        <div className="rounded-xl border border-slate-200 bg-surface-sunken/60 p-3 text-xs text-slate-500">
          <p className="font-semibold text-slate-800">{metadata.name}</p>
          <p className="mt-1">Last updated {new Date(metadata.updatedAt).toLocaleString()}</p>
        </div>

        <div className="flex items-center justify-between gap-3 rounded-xl border border-slate-200 bg-surface-sunken/60 p-3 text-xs text-slate-600">
          <div className="min-w-0">
            <p className="text-sm font-semibold text-slate-800">Export current state</p>
            <p className="mt-1 text-[11px] text-slate-500">
              Download a JSON export of the live canvas or any stored snapshot.
            </p>
          </div>
          <Button
            variant="secondary"
            size="sm"
            leftIcon={<Download />}
            onClick={() => handleExport()}
            isLoading={exportTreeMutation.isPending}
          >
            Export
          </Button>
        </div>

        <div className="space-y-2">
          <label htmlFor="snapshot-label" className="text-xs font-semibold uppercase tracking-wide text-slate-500">
            Snapshot label
          </label>
          <input
            id="snapshot-label"
            value={label}
            onChange={(event) => setLabel(event.target.value)}
            placeholder="e.g. Pre-interview notes"
            className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900 shadow-soft transition-colors duration-200 ease-smooth focus:border-brand-primary focus:outline-none"
          />

          <div className="grid gap-2 sm:grid-cols-2">
            <div className="space-y-2">
              <label htmlFor="snapshot-author" className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                Author <span className="text-[10px] text-slate-500">(optional)</span>
              </label>
              <input
                id="snapshot-author"
                value={author}
                onChange={(event) => setAuthor(event.target.value)}
                placeholder="e.g. Taylor"
                className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900 shadow-soft transition-colors duration-200 ease-smooth focus:border-brand-primary focus:outline-none"
              />
            </div>
            <div className="space-y-2">
              <label htmlFor="snapshot-notes" className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                Notes <span className="text-[10px] text-slate-500">(optional)</span>
              </label>
              <input
                id="snapshot-notes"
                value={notes}
                onChange={(event) => setNotes(event.target.value)}
                placeholder="Why are you capturing this snapshot?"
                className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900 shadow-soft transition-colors duration-200 ease-smooth focus:border-brand-primary focus:outline-none"
              />
            </div>
          </div>

          <Button
            variant="primary"
            size="md"
            leftIcon={<Save />}
            onClick={handleCreate}
            isLoading={createVersionMutation.isPending}
            className="w-full"
          >
            Capture snapshot
          </Button>
        </div>

        <ul className="space-y-3">
          {sortedVersions.length === 0 ? (
            <li className="flex items-center gap-3 rounded-xl border border-dashed border-slate-200 bg-surface-sunken/40 p-3 text-sm text-slate-500">
              <History className="h-4 w-4 text-slate-400" />
              No versions captured yet.
            </li>
          ) : (
            sortedVersions.map((version) => (
              <li key={version.id} className="rounded-xl border border-slate-200 bg-surface-sunken/60 p-3">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="truncate text-sm font-semibold text-slate-800">{version.label}</p>
                    <p className="text-xs text-slate-500">
                      {new Date(version.createdAt).toLocaleString()}
                      {version.author ? <span className="ml-2 text-slate-500">• {version.author}</span> : null}
                    </p>
                    {version.notes ? (
                      <p className="mt-1 text-xs italic text-slate-500">"{version.notes}"</p>
                    ) : null}
                  </div>
                  <div className="flex flex-wrap justify-end gap-2">
                    <Button
                      variant="ghost"
                      size="sm"
                      leftIcon={<Download />}
                      onClick={() => handleExport()}
                      isLoading={exportTreeMutation.isPending}
                    >
                      Export
                    </Button>
                    <Button
                      variant="secondary"
                      size="sm"
                      leftIcon={<RotateCcw />}
                      onClick={() => setConfirmState({ action: "restore", version })}
                    >
                      Restore
                    </Button>
                    <Button
                      variant="danger"
                      size="sm"
                      leftIcon={<Trash2 />}
                      onClick={() => setConfirmState({ action: "delete", version })}
                    >
                      Delete
                    </Button>
                  </div>
                </div>

                {version.diffSummary ? (
                  <DiffSummary diff={version.diffSummary} />
                ) : (
                  <p className="mt-3 text-[11px] text-slate-500">Initial snapshot of this tree.</p>
                )}

                {version.conflictCount > 0 ? (
                  <p className="mt-2 text-[11px] font-semibold text-amber-700">
                    {version.conflictCount} potential conflicts detected when this snapshot was saved.
                  </p>
                ) : null}
              </li>
            ))
          )}
        </ul>
      </div>

      {shouldRenderConfirm && confirmState ? (
        <ConfirmDialog
          state={confirmState}
          onCancel={() => setConfirmState(null)}
          onConfirm={() => {
            if (!confirmState) {
              return;
            }
            if (confirmState.action === "restore") {
              handleRestoreConfirmed(confirmState.version);
            } else {
              handleDeleteConfirmed(confirmState.version);
            }
          }}
          isLoading={confirmState.action === "restore" ? isRestoring : isDeleting}
          isAnimatingOut={isConfirmAnimatingOut}
        />
      ) : null}
    </>
  );
}

function DiffSummary({ diff }: { diff: NonNullable<GraphVersion["diffSummary"]> }): JSX.Element {
  return (
    <div className="mt-3 grid grid-cols-2 gap-2 text-[11px] text-slate-500">
      <div className="rounded-md border border-slate-200 bg-white/80 p-2">
        <p className="font-semibold uppercase tracking-wide text-[10px] text-slate-500">Nodes</p>
        <div className="mt-1 flex gap-3 font-mono">
          <span className="text-emerald-600">+{diff.nodesAdded}</span>
          <span className="text-rose-600">-{diff.nodesRemoved}</span>
          <span className="text-amber-600">~{diff.nodesModified}</span>
        </div>
      </div>
      <div className="rounded-md border border-slate-200 bg-white/80 p-2">
        <p className="font-semibold uppercase tracking-wide text-[10px] text-slate-500">Relations</p>
        <div className="mt-1 flex gap-3 font-mono">
          <span className="text-emerald-600">+{diff.relationsAdded}</span>
          <span className="text-rose-600">-{diff.relationsRemoved}</span>
          <span className="text-amber-600">~{diff.relationsModified}</span>
        </div>
      </div>
    </div>
  );
}

interface ConfirmDialogProps {
  state: ConfirmState;
  onConfirm: () => void;
  onCancel: () => void;
  isLoading: boolean;
  isAnimatingOut: boolean;
}

function ConfirmDialog({ state, onConfirm, onCancel, isLoading, isAnimatingOut }: ConfirmDialogProps): JSX.Element {
  const { action, version } = state;
  const isRestore = action === "restore";
  const title = isRestore ? "Restore snapshot" : "Delete snapshot";

  const baseDescription = isRestore
    ? `Restoring "${version.label}" will replace the current canvas with the snapshot captured on ${new Date(
        version.createdAt
      ).toLocaleString()}.`
    : `Delete "${version.label}"? This permanently removes the snapshot but keeps the tree intact.`;

  const conflictNotice =
    isRestore && version.conflictCount > 0
      ? ` ${version.conflictCount} potential conflicts will be overwritten.`
      : "";

  return (
    <div
      className={twMerge(
        "fixed inset-0 z-50 flex items-center justify-center backdrop-blur transition-all duration-200 ease-smooth",
        isAnimatingOut ? "bg-transparent opacity-0" : "bg-surface-base/80 opacity-100"
      )}
    >
      <div
        className={twMerge(
          "w-full max-w-sm space-y-4 rounded-2xl border border-slate-200 bg-white/95 p-5 shadow-floating transition-all duration-200 ease-smooth",
          isAnimatingOut ? "scale-95 opacity-0" : "animate-scale-fade-in"
        )}
      >
        <header className="flex items-start gap-3">
          <div
            className={twMerge(
              "flex h-10 w-10 shrink-0 items-center justify-center rounded-xl",
              isRestore ? "bg-brand-primary/10 text-brand-primary" : "bg-rose-100 text-rose-600"
            )}
          >
            {isRestore ? <RotateCcw className="h-5 w-5" /> : <Trash2 className="h-5 w-5" />}
          </div>
          <div className="flex-1 space-y-1">
            <h3 className="text-title font-semibold text-slate-900">{title}</h3>
            <p className="text-sm text-slate-600">
              {baseDescription}
              {conflictNotice}
            </p>
          </div>
        </header>

        <div className="flex items-center justify-end gap-2">
          <Button
            variant="secondary"
            size="md"
            onClick={onCancel}
            disabled={isLoading}
          >
            Cancel
          </Button>
          <Button
            variant={isRestore ? "primary" : "danger"}
            size="md"
            leftIcon={isRestore ? <RotateCcw /> : <Trash2 />}
            onClick={onConfirm}
            isLoading={isLoading}
          >
            {isRestore ? "Restore" : "Delete"}
          </Button>
        </div>
      </div>
    </div>
  );
}

function formatDiffSummary(diff: GraphVersion["diffSummary"] | null | undefined): string {
  if (!diff) {
    return "Initial snapshot captured.";
  }

  const nodeSummary = `Nodes +${diff.nodesAdded}/-${diff.nodesRemoved}/~${diff.nodesModified}`;
  const relationSummary = `Relations +${diff.relationsAdded}/-${diff.relationsRemoved}/~${diff.relationsModified}`;
  return `${nodeSummary}, ${relationSummary}`;
}

function addVersion(current: GraphVersion[], payload: VersionListItem) {
  const next = current.filter((item) => item.id !== payload.id);
  next.push(mapVersionResponse(payload));
  return next;
}

function removeVersion(current: GraphVersion[], versionId: string) {
  return current.filter((item) => item.id !== versionId);
}
