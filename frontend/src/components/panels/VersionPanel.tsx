import { useState } from "react";

import { useCreateVersion, useDeleteVersion, useRestoreVersion } from "../../api/hooks";
import type { VersionListItem } from "../../api/types";
import { mapVersionResponse, useTreeStore, type GraphVersion } from "../../stores/treeStore";
import { useUiStore } from "../../stores/uiStore";
import { getErrorMessage } from "../../utils/error";

export function VersionPanel(): JSX.Element {
  const activeTreeId = useTreeStore((state) => state.activeTreeId);
  const versions = useTreeStore((state) => state.versions);
  const setVersions = useTreeStore((state) => state.setVersions);
  const setTree = useTreeStore((state) => state.setTree);
  const metadata = useTreeStore((state) => state.metadata);
  const pushSnapshot = useTreeStore((state) => state.pushSnapshot);
  const pushToast = useUiStore((state) => state.pushToast);

  const [label, setLabel] = useState("");

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

  const handleCreate = () => {
    const trimmed = label.trim();
    createVersionMutation.mutate(
      { label: trimmed || null },
      {
        onSuccess: (version) => {
          setLabel("");
          setVersions(syncVersions(versions, version, "add"));
          pushToast({
            title: "Snapshot captured",
            description: "Version saved successfully.",
            variant: "success",
            duration: 3000
          });
        },
        onError: (error) => {
          pushToast({
            title: "Failed to create snapshot",
            description: getErrorMessage(error),
            variant: "error",
            duration: 6000
          });
        }
      }
    );
  };

  const handleDelete = (versionId: string) => {
    deleteVersionMutation.mutate(versionId, {
      onSuccess: () => {
        setVersions(syncVersions(versions, { id: versionId } as VersionListItem, "remove"));
        pushToast({
          title: "Snapshot deleted",
          description: "Version removed.",
          variant: "info",
          duration: 2500
        });
      },
      onError: (error) => {
        pushToast({
          title: "Failed to delete snapshot",
          description: getErrorMessage(error),
          variant: "error",
          duration: 6000
        });
      }
    });
  };

  const handleRestore = (versionId: string) => {
    pushSnapshot();
    restoreVersionMutation.mutate(versionId, {
      onSuccess: (tree) => {
        setTree(tree);
        pushToast({
          title: "Version restored",
          description: "Canvas updated to selected snapshot.",
          variant: "success",
          duration: 3000
        });
      },
      onError: (error) => {
        pushToast({
          title: "Failed to restore version",
          description: getErrorMessage(error),
          variant: "error",
          duration: 6000
        });
      }
    });
  };

  return (
    <div className="space-y-4">
      <div className="rounded-lg border border-slate-800 bg-surface-sunken/60 p-3 text-xs text-slate-400">
        <p>
          <span className="font-semibold text-slate-200">{metadata.title}</span>
          <br />
          Last updated {new Date(metadata.updatedAt).toLocaleString()}
        </p>
      </div>

      <div className="space-y-2">
        <label htmlFor="snapshot-label" className="text-xs font-semibold uppercase tracking-wide text-slate-400">
          Snapshot label
        </label>
        <div className="flex gap-2">
          <input
            id="snapshot-label"
            value={label}
            onChange={(event) => setLabel(event.target.value)}
            placeholder="e.g. Pre-interview notes"
            className="flex-1 rounded-lg border border-slate-700 bg-surface-base px-3 py-2 text-sm text-slate-100 shadow-inner focus:border-brand-primary focus:outline-none"
          />
          <button
            type="button"
            onClick={handleCreate}
            className="rounded-md bg-brand-secondary/80 px-3 py-2 text-sm font-semibold text-slate-950 transition hover:bg-brand-secondary"
          >
            Capture
          </button>
        </div>
      </div>

      <ul className="space-y-3">
        {versions.length === 0 ? (
          <li className="rounded-lg border border-dashed border-slate-700 bg-surface-sunken/40 p-3 text-sm text-slate-500">
            No versions captured yet.
          </li>
        ) : (
          versions
            .slice()
            .sort((a, b) => (a.createdAt > b.createdAt ? -1 : 1))
            .map((version) => (
              <li key={version.id} className="rounded-lg border border-slate-800 bg-surface-sunken/60 p-3">
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <p className="text-sm font-semibold text-slate-200">{version.label}</p>
                    <p className="text-xs text-slate-500">{new Date(version.createdAt).toLocaleString()}</p>
                  </div>
                  <div className="flex gap-2">
                    <button
                      type="button"
                      onClick={() => handleRestore(version.id)}
                      className="rounded-md border border-brand-primary/50 px-3 py-1 text-xs font-semibold text-brand-primary transition hover:border-brand-primary hover:bg-brand-primary/10"
                    >
                      Restore
                    </button>
                    <button
                      type="button"
                      onClick={() => handleDelete(version.id)}
                      className="rounded-md border border-red-500/40 px-3 py-1 text-xs font-semibold text-red-200 transition hover:border-red-400 hover:text-red-100"
                    >
                      Delete
                    </button>
                  </div>
                </div>
              </li>
            ))
        )}
      </ul>
    </div>
  );
}

function syncVersions(current: GraphVersion[], payload: VersionListItem, action: "add" | "remove") {
  if (action === "remove") {
    return current.filter((item) => item.id !== payload.id);
  }

  const next = current.filter((item) => item.id !== payload.id);
  next.push(mapVersionResponse(payload));
  return next;
}
