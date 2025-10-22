import { useMemo, useState } from "react";

import { useCreateVersion, useDeleteVersion, useExportTree, useRestoreVersion } from "../../api/hooks";
import type { VersionListItem } from "../../api/types";
import { mapVersionResponse, useTreeStore, type GraphVersion } from "../../stores/treeStore";
import { useUiStore } from "../../stores/uiStore";
import { getErrorMessage } from "../../utils/error";

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

  if (!activeTreeId || !metadata) {
    return (
      <div className="rounded-lg border border-dashed border-slate-700 bg-surface-sunken/40 p-4 text-sm text-slate-500">
        Select a tree to manage versions.
      </div>
    );
  }

  const createVersionMutation = useCreateVersion(activeTreeId);
  const deleteVersionMutation = useDeleteVersion(activeTreeId);
  const restoreVersionMutation = useRestoreVersion(activeTreeId);
  const exportTreeMutation = useExportTree(activeTreeId);

  const sortedVersions = useMemo(
    () => [...versions].sort((a, b) => (a.createdAt > b.createdAt ? -1 : 1)),
    [versions]
  );

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
        setTree(tree);
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

  const handleExport = (version?: GraphVersion) => {
    const toastId = pushToast({
      title: version ? `Preparing “${version.label}”` : "Preparing export…",
      description: version ? new Date(version.createdAt).toLocaleString() : undefined,
      variant: "info",
      duration: 0
    });

    exportTreeMutation.mutate(
      { versionId: version?.id },
      {
        onSuccess: ({ filename, blob }) => {
          if (typeof window !== "undefined") {
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
      }
    );
  };

  const isDeleting = deleteVersionMutation.isPending && confirmState?.action === "delete";
  const isRestoring = restoreVersionMutation.isPending && confirmState?.action === "restore";

  return (
    <>
      <div className="space-y-4">
        <div className="rounded-lg border border-slate-800 bg-surface-sunken/60 p-3 text-xs text-slate-400">
          <p className="font-semibold text-slate-200">{metadata.title}</p>
          <p className="mt-1">
            Last updated {new Date(metadata.updatedAt).toLocaleString()}
            {metadata.description ? (
              <span className="mt-1 block text-[11px] text-slate-500">{metadata.description}</span>
            ) : null}
          </p>
        </div>

        <div className="flex items-center justify-between gap-3 rounded-lg border border-slate-800 bg-surface-sunken/60 p-3 text-xs text-slate-300">
          <div>
            <p className="text-sm font-semibold text-slate-100">Export current state</p>
            <p className="mt-1 text-[11px] text-slate-500">
              Download a JSON export of the live canvas or any stored snapshot.
            </p>
          </div>
          <button
            type="button"
            onClick={() => handleExport()}
            className="rounded-md border border-brand-primary/60 px-3 py-2 text-xs font-semibold text-brand-primary transition hover:border-brand-primary hover:bg-brand-primary/10 disabled:cursor-not-allowed disabled:opacity-50"
            disabled={exportTreeMutation.isPending}
          >
            {exportTreeMutation.isPending ? "Preparing…" : "Export current"}
          </button>
        </div>

        <div className="space-y-2">
          <label htmlFor="snapshot-label" className="text-xs font-semibold uppercase tracking-wide text-slate-400">
            Snapshot label
          </label>
          <input
            id="snapshot-label"
            value={label}
            onChange={(event) => setLabel(event.target.value)}
            placeholder="e.g. Pre-interview notes"
            className="w-full rounded-lg border border-slate-700 bg-surface-base px-3 py-2 text-sm text-slate-100 shadow-inner focus:border-brand-primary focus:outline-none"
          />

          <div className="grid gap-2 sm:grid-cols-2">
            <div className="space-y-2">
              <label htmlFor="snapshot-author" className="text-xs font-semibold uppercase tracking-wide text-slate-400">
                Author <span className="text-[10px] text-slate-500">(optional)</span>
              </label>
              <input
                id="snapshot-author"
                value={author}
                onChange={(event) => setAuthor(event.target.value)}
                placeholder="e.g. Taylor"
                className="w-full rounded-lg border border-slate-700 bg-surface-base px-3 py-2 text-sm text-slate-100 shadow-inner focus:border-brand-primary focus:outline-none"
              />
            </div>
            <div className="space-y-2">
              <label htmlFor="snapshot-notes" className="text-xs font-semibold uppercase tracking-wide text-slate-400">
                Notes <span className="text-[10px] text-slate-500">(optional)</span>
              </label>
              <input
                id="snapshot-notes"
                value={notes}
                onChange={(event) => setNotes(event.target.value)}
                placeholder="Why are you capturing this snapshot?"
                className="w-full rounded-lg border border-slate-700 bg-surface-base px-3 py-2 text-sm text-slate-100 shadow-inner focus:border-brand-primary focus:outline-none"
              />
            </div>
          </div>

          <button
            type="button"
            onClick={handleCreate}
            className="w-full rounded-md bg-brand-secondary/80 px-3 py-2 text-sm font-semibold text-slate-950 transition hover:bg-brand-secondary disabled:cursor-not-allowed disabled:opacity-60"
            disabled={createVersionMutation.isPending}
          >
            {createVersionMutation.isPending ? "Capturing…" : "Capture snapshot"}
          </button>
        </div>

        <ul className="space-y-3">
          {sortedVersions.length === 0 ? (
            <li className="rounded-lg border border-dashed border-slate-700 bg-surface-sunken/40 p-3 text-sm text-slate-500">
              No versions captured yet.
            </li>
          ) : (
            sortedVersions.map((version) => (
              <li key={version.id} className="rounded-lg border border-slate-800 bg-surface-sunken/60 p-3">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <p className="text-sm font-semibold text-slate-200">{version.label}</p>
                    <p className="text-xs text-slate-500">
                      {new Date(version.createdAt).toLocaleString()}
                      {version.author ? <span className="ml-2 text-slate-400">• {version.author}</span> : null}
                    </p>
                    {version.notes ? (
                      <p className="mt-1 text-xs italic text-slate-400">“{version.notes}”</p>
                    ) : null}
                  </div>
                  <div className="flex flex-wrap justify-end gap-2">
                    <button
                      type="button"
                      onClick={() => handleExport(version)}
                      className="rounded-md border border-slate-600 px-3 py-1 text-xs font-semibold text-slate-200 transition hover:border-slate-400 hover:text-slate-100 disabled:cursor-not-allowed disabled:opacity-60"
                      disabled={exportTreeMutation.isPending}
                    >
                      {exportTreeMutation.isPending ? "Exporting…" : "Export"}
                    </button>
                    <button
                      type="button"
                      onClick={() => setConfirmState({ action: "restore", version })}
                      className="rounded-md border border-brand-primary/50 px-3 py-1 text-xs font-semibold text-brand-primary transition hover:border-brand-primary hover:bg-brand-primary/10"
                    >
                      Restore
                    </button>
                    <button
                      type="button"
                      onClick={() => setConfirmState({ action: "delete", version })}
                      className="rounded-md border border-red-500/40 px-3 py-1 text-xs font-semibold text-red-200 transition hover:border-red-400 hover:text-red-100"
                    >
                      Delete
                    </button>
                  </div>
                </div>

                {version.diffSummary ? (
                  <DiffSummary diff={version.diffSummary} />
                ) : (
                  <p className="mt-3 text-[11px] text-slate-500">Initial snapshot of this tree.</p>
                )}

                {version.conflictCount > 0 ? (
                  <p className="mt-2 text-[11px] font-semibold text-amber-300">
                    {version.conflictCount} potential conflicts detected when this snapshot was saved.
                  </p>
                ) : null}
              </li>
            ))
          )}
        </ul>
      </div>

      {confirmState ? (
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
        />
      ) : null}
    </>
  );
}

function DiffSummary({ diff }: { diff: NonNullable<GraphVersion["diffSummary"]> }): JSX.Element {
  return (
    <div className="mt-3 grid grid-cols-2 gap-2 text-[11px] text-slate-300">
      <div className="rounded-md border border-slate-700 bg-slate-900/60 p-2">
        <p className="font-semibold uppercase tracking-wide text-[10px] text-slate-400">Nodes</p>
        <div className="mt-1 flex gap-3 font-mono">
          <span className="text-emerald-300">+{diff.nodesAdded}</span>
          <span className="text-rose-300">-{diff.nodesRemoved}</span>
          <span className="text-amber-300">~{diff.nodesModified}</span>
        </div>
      </div>
      <div className="rounded-md border border-slate-700 bg-slate-900/60 p-2">
        <p className="font-semibold uppercase tracking-wide text-[10px] text-slate-400">Relations</p>
        <div className="mt-1 flex gap-3 font-mono">
          <span className="text-emerald-300">+{diff.relationsAdded}</span>
          <span className="text-rose-300">-{diff.relationsRemoved}</span>
          <span className="text-amber-300">~{diff.relationsModified}</span>
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
}

function ConfirmDialog({ state, onConfirm, onCancel, isLoading }: ConfirmDialogProps): JSX.Element {
  const { action, version } = state;
  const isRestore = action === "restore";
  const title = isRestore ? "Restore snapshot" : "Delete snapshot";

  const baseDescription = isRestore
    ? `Restoring “${version.label}” will replace the current canvas with the snapshot captured on ${new Date(
        version.createdAt
      ).toLocaleString()}.`
    : `Delete “${version.label}”? This permanently removes the snapshot but keeps the tree intact.`;

  const conflictNotice =
    isRestore && version.conflictCount > 0
      ? ` ${version.conflictCount} potential conflicts will be overwritten.`
      : "";

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-surface-base/80 backdrop-blur">
      <div className="w-full max-w-sm space-y-4 rounded-2xl border border-slate-700 bg-surface-sunken/90 p-5 shadow-2xl">
        <header className="space-y-1">
          <h3 className="text-base font-semibold text-slate-100">{title}</h3>
          <p className="text-sm text-slate-300">
            {baseDescription}
            {conflictNotice}
          </p>
        </header>

        <div className="flex items-center justify-end gap-2">
          <button
            type="button"
            onClick={onCancel}
            className="rounded-md border border-slate-600 px-4 py-2 text-sm font-medium text-slate-300 transition hover:border-slate-400 hover:text-slate-100 disabled:cursor-not-allowed disabled:opacity-60"
            disabled={isLoading}
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={onConfirm}
            className={`rounded-md px-4 py-2 text-sm font-semibold transition disabled:cursor-not-allowed disabled:opacity-60 ${
              isRestore
                ? "bg-brand-primary/90 text-slate-950 hover:bg-brand-primary"
                : "bg-red-500/80 text-slate-900 hover:bg-red-500"
            }`}
            disabled={isLoading}
          >
            {isLoading ? "Working…" : isRestore ? "Restore" : "Delete"}
          </button>
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
