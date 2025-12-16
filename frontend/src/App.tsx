import { useEffect, useMemo, useRef, useState } from "react";
import { ReactFlowProvider } from "reactflow";
import "reactflow/dist/style.css";

import { ApiError } from "./api/client";
import type { TreeDetailResponse } from "./api/types";
import { useTree, useTrees, useTreeDownload, useTreeImportWithToasts } from "./api/hooks";
import { TreeCanvas, type TreeCanvasHandle } from "./components/canvas/TreeCanvas";
import { CreateTreeModal } from "./components/modals/CreateTreeModal";
import { ToastStack } from "./components/ui/ToastStack";
import { useTreeStore } from "./stores/treeStore";
import { useUiStore } from "./stores/uiStore";
import { getErrorMessage } from "./utils/error";

export default function App(): JSX.Element {
  const [selectedTreeId, setSelectedTreeId] = useState<string | null>(null);
  const canvasRef = useRef<TreeCanvasHandle | null>(null);

  const {
    data: trees,
    error: treesError,
    refetch: refetchTrees
  } = useTrees();
  const setTree = useTreeStore((state) => state.setTree);
  const resetTree = useTreeStore((state) => state.reset);
  const metadata = useTreeStore((state) => state.metadata);
  const activeTreeId = useTreeStore((state) => state.activeTreeId);
  const openModal = useUiStore((state) => state.openModal);
  const pushToast = useUiStore((state) => state.pushToast);

  const treeQuery = useTree(selectedTreeId);
  const { error: treeError, refetch: refetchTree } = treeQuery;
  const { download, isDownloading } = useTreeDownload(selectedTreeId);
  const { importFromFile, isImporting } = useTreeImportWithToasts((tree) => {
    setSelectedTreeId(tree.id);
    setTree(tree);
  });

  useEffect(() => {
    if (!selectedTreeId && trees?.length) {
      setSelectedTreeId(trees[0].id);
    }
  }, [selectedTreeId, trees]);

  useEffect(() => {
    if (treeQuery.data) {
      setTree(treeQuery.data);
    }
  }, [treeQuery.data, setTree]);

  useEffect(() => {
    if (!selectedTreeId) {
      resetTree();
    }
  }, [selectedTreeId, resetTree]);

  useEffect(() => {
    if (!treesError) {
      return;
    }
    pushToast({
      id: "tree-list-error",
      title: "Unable to load trees",
      description: getErrorMessage(treesError),
      variant: "error",
      action: {
        label: "Retry",
        onClick: () => {
          refetchTrees();
        }
      }
    });
  }, [treesError, pushToast, refetchTrees]);

  useEffect(() => {
    if (!treeError || !selectedTreeId) {
      return;
    }
    pushToast({
      id: `tree-detail-error-${selectedTreeId}`,
      title: "Unable to load tree",
      description: getErrorMessage(treeError),
      variant: "error",
      action: {
        label: "Retry",
        onClick: () => {
          refetchTree();
        }
      }
    });
  }, [treeError, pushToast, refetchTree, selectedTreeId]);

  const handleTreeCreated = (tree: TreeDetailResponse) => {
    setSelectedTreeId(tree.id);
    setTree(tree);
  };

  const isTreeLoading = treeQuery.isLoading || treeQuery.isFetching;

  const handleZoomIn = () => canvasRef.current?.zoomIn();
  const handleZoomOut = () => canvasRef.current?.zoomOut();
  const handleCenter = () => canvasRef.current?.centerOnSelection();

  const treeName = useMemo(() => metadata?.name ?? "Untitled tree", [metadata?.name]);

  return (
    <ReactFlowProvider>
      <div className="flex min-h-screen flex-col bg-surface-base text-slate-100">
        <header className="border-b border-slate-800 bg-surface-sunken/80 px-6 py-3 shadow-inset backdrop-blur">
          <div className="flex items-center gap-4">
            <div className="flex items-center gap-3">
              <input
                type="text"
                value={treeName}
                readOnly
                className="w-56 rounded-md border border-slate-800 bg-surface-base px-3 py-2 text-sm shadow-inner focus:border-brand-primary focus:outline-none"
                aria-label="Tree name"
              />

              <div className="flex items-center gap-2 text-xs text-slate-200">
                <button
                  type="button"
                  onClick={() => openModal("createTree")}
                  className="rounded-md border border-slate-700 bg-surface-sunken px-3 py-2 text-xs font-semibold transition hover:border-brand-primary hover:text-brand-primary"
                >
                  New tree
                </button>
                <button
                  type="button"
                  onClick={download}
                  disabled={isDownloading}
                  className="rounded-md border border-slate-700 bg-surface-sunken px-3 py-2 text-xs font-semibold transition hover:border-slate-500 hover:text-white disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {isDownloading ? "Preparing…" : "Download"}
                </button>
                <label
                  className={`cursor-pointer rounded-md border border-slate-700 bg-surface-sunken px-3 py-2 text-xs font-semibold transition hover:border-slate-500 hover:text-white ${
                    isImporting ? "pointer-events-none opacity-60" : ""
                  }`}
                >
                  <span>{isImporting ? "Importing…" : "Import"}</span>
                  <input
                    type="file"
                    accept="application/json"
                    className="hidden"
                    onChange={(event) => {
                      const file = event.target.files?.[0];
                      if (file) {
                        importFromFile(file);
                      }
                      event.target.value = "";
                    }}
                    aria-label="Import tree"
                  />
                </label>
              </div>
            </div>
          </div>
        </header>

        <main className="relative flex flex-1 overflow-hidden">
          <div className="absolute inset-0">
            {treeError ? (
              <ErrorCanvasState
                message={getErrorMessage(treeError)}
                correlationId={treeError instanceof ApiError ? treeError.correlationId ?? undefined : undefined}
                isRetrying={treeQuery.isFetching}
                onRetry={() => refetchTree()}
              />
            ) : activeTreeId ? (
              <TreeCanvas ref={canvasRef} treeId={activeTreeId} isLoading={isTreeLoading} />
            ) : (
              <EmptyCanvasState isLoading={isTreeLoading} hasTrees={Boolean(trees?.length)} />
            )}
          </div>

          <FloatingZoomControls onZoomIn={handleZoomIn} onZoomOut={handleZoomOut} onCenter={handleCenter} />
        </main>
      </div>

      <ToastStack />
      <CreateTreeModal onCreated={handleTreeCreated} />
    </ReactFlowProvider>
  );
}

function FloatingZoomControls({
  onZoomIn,
  onZoomOut,
  onCenter
}: {
  onZoomIn: () => void;
  onZoomOut: () => void;
  onCenter: () => void;
}): JSX.Element {
  return (
    <div className="pointer-events-none absolute right-6 bottom-6 z-20 flex flex-col items-center gap-2">
      <button
        type="button"
        onClick={onZoomIn}
        className="pointer-events-auto h-9 w-9 rounded-lg border border-slate-800 bg-surface-sunken text-lg font-semibold text-slate-100 shadow-inner transition hover:border-brand-primary hover:text-brand-primary"
        aria-label="Zoom in"
      >
        +
      </button>
      <button
        type="button"
        onClick={onZoomOut}
        className="pointer-events-auto h-9 w-9 rounded-lg border border-slate-800 bg-surface-sunken text-lg font-semibold text-slate-100 shadow-inner transition hover:border-brand-primary hover:text-brand-primary"
        aria-label="Zoom out"
      >
        −
      </button>
      <div className="h-10 w-px bg-slate-700" aria-hidden />
      <button
        type="button"
        onClick={onCenter}
        className="pointer-events-auto h-9 w-9 rounded-lg border border-slate-800 bg-surface-sunken text-xs font-semibold text-slate-100 shadow-inner transition hover:border-brand-primary hover:text-brand-primary"
      >
        Center
      </button>
    </div>
  );
}

function EmptyCanvasState({ isLoading, hasTrees }: { isLoading: boolean; hasTrees: boolean }): JSX.Element {
  if (isLoading) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-slate-400">
        Loading tree…
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col items-center justify-center gap-2 text-center text-sm text-slate-300">
      <p className="text-lg font-semibold text-slate-100">Start with your first undesired effect</p>
      <p className="max-w-lg text-slate-400">
        {hasTrees
          ? "Your most recent tree loads automatically. Continue mapping or start a new one."
          : "Create a new tree to drop in your initial thought and build from there."}
      </p>
    </div>
  );
}

function ErrorCanvasState({
  message,
  correlationId,
  onRetry,
  isRetrying
}: {
  message: string;
  correlationId?: string;
  onRetry: () => void;
  isRetrying: boolean;
}): JSX.Element {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-3 text-center text-sm text-red-200">
      <p className="max-w-md text-balance">{message}</p>
      {correlationId ? <p className="text-xs text-slate-500">Reference: {correlationId}</p> : null}
      <button
        type="button"
        onClick={onRetry}
        disabled={isRetrying}
        className="rounded-md border border-red-500/60 px-3 py-1 text-xs font-semibold text-red-100 transition hover:border-red-400 hover:text-white disabled:cursor-not-allowed disabled:border-slate-600 disabled:text-slate-400"
      >
        {isRetrying ? "Retrying…" : "Retry"}
      </button>
    </div>
  );
}
