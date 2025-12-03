import { useEffect, useRef, useState } from "react";
import { ReactFlowProvider } from "reactflow";
import "reactflow/dist/style.css";

import { ApiError } from "./api/client";
import type { TreeDetailResponse } from "./api/types";
import { useTree, useTrees, useTreeDownload, useTreeImportWithToasts } from "./api/hooks";
import { TreeCanvas, type TreeCanvasHandle } from "./components/canvas/TreeCanvas";
import { CanvasShell } from "./components/layout/CanvasShell";
import { Layout } from "./components/layout/Layout";
import { SidePanel } from "./components/layout/SidePanel";
import { TopBar } from "./components/layout/TopBar";
import { CreateTreeModal } from "./components/modals/CreateTreeModal";
import { NodeInspector } from "./components/panels/NodeInspector";
import { RelationInspector } from "./components/panels/RelationInspector";
import { InspectorTabs } from "./components/panels/InspectorTabs";
import { VersionPanel } from "./components/panels/VersionPanel";
import { TreeSelector } from "./components/topbar/TreeSelector";
import { ToastStack } from "./components/ui/ToastStack";
import { useTreeStore } from "./stores/treeStore";
import { useUiStore } from "./stores/uiStore";
import { getErrorMessage } from "./utils/error";

export default function App(): JSX.Element {
  const [selectedTreeId, setSelectedTreeId] = useState<string | null>(null);
  const canvasRef = useRef<TreeCanvasHandle | null>(null);

  const {
    data: trees,
    isLoading: isTreesLoading,
    error: treesError,
    refetch: refetchTrees
  } = useTrees();
  const setTree = useTreeStore((state) => state.setTree);
  const resetTree = useTreeStore((state) => state.reset);
  const metadata = useTreeStore((state) => state.metadata);
  const activeTreeId = useTreeStore((state) => state.activeTreeId);
  const flushPendingPersistence = useTreeStore((state) => state.flushPendingPersistence);
  const pendingSync = useTreeStore((state) => state.pendingSync);
  const inspectorTab = useUiStore((state) => state.inspectorTab);
  const pushToast = useUiStore((state) => state.pushToast);

  const treeQuery = useTree(selectedTreeId);
  const { error: treeError, refetch: refetchTree } = treeQuery;
  const { download, isDownloading } = useTreeDownload(selectedTreeId);
  const { importFromFile, isImporting } = useTreeImportWithToasts((tree) => {
    setSelectedTreeId(tree.id);
    setTree(tree);
  });
  const [isSaving, setIsSaving] = useState(false);

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

  const handleTreeChange = (treeId: string) => {
    resetTree();
    setSelectedTreeId(treeId);
  };

  const isTreeLoading = treeQuery.isLoading || treeQuery.isFetching;

  const inspectorTitle =
    inspectorTab === "node" ? "Node Inspector" : inspectorTab === "relation" ? "Relation Inspector" : "Versions";

  const handleZoomIn = () => canvasRef.current?.zoomIn();
  const handleZoomOut = () => canvasRef.current?.zoomOut();
  const handleCenter = () => canvasRef.current?.centerOnSelection();

  const handleSave = async () => {
    if (!activeTreeId || !metadata) {
      pushToast({
        title: "Nothing to save",
        description: "Select or create a tree before saving.",
        variant: "warning",
        duration: 4000
      });
      return;
    }

    setIsSaving(true);
    const toastId = pushToast({
      title: pendingSync ? "Saving changes…" : "Syncing draft…",
      description: metadata.name,
      variant: "info",
      duration: 0
    });

    await flushPendingPersistence();
    setIsSaving(false);
    const state = useTreeStore.getState();

    if (state.pendingSync || state.lastSyncError) {
      pushToast({
        id: toastId,
        title: "Save incomplete",
        description: state.lastSyncError ?? "Still pending sync, will retry automatically.",
        variant: "warning",
        duration: 6000
      });
      return;
    }

    pushToast({
      id: toastId,
      title: "Saved",
      description: `${metadata.name} updated`,
      variant: "success",
      duration: 3500
    });
  };

  return (
    <ReactFlowProvider>
      <Layout
        header={
          <TopBar
            title={metadata?.name ?? "Brain Buddy Canvas"}
            subtitle="Select a tree or create a new one to begin mapping."
            rightSlot={
              <TreeSelector
                trees={trees}
                value={selectedTreeId}
                onChange={handleTreeChange}
                isLoading={isTreesLoading}
                onSave={handleSave}
                isSaving={isSaving}
                onDownload={download}
                isDownloading={isDownloading}
                onImport={importFromFile}
                isImporting={isImporting}
              />
            }
          />
        }
        sidebar={
          <SidePanel title={inspectorTitle} toolbar={<InspectorTabs />}>
            {inspectorTab === "node" ? (
              <NodeInspector />
            ) : inspectorTab === "relation" ? (
              <RelationInspector />
            ) : (
              <VersionPanel />
            )}
          </SidePanel>
        }
        footer="Use ⌘Z / Ctrl+Z to undo and Shift+⌘Z / Shift+Ctrl+Z to redo changes."
      >
        <CanvasShell
          toolbar={
            <CanvasToolbar onZoomIn={handleZoomIn} onZoomOut={handleZoomOut} onCenter={handleCenter} />
          }
        >
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
        </CanvasShell>
      </Layout>

      <ToastStack />
      <CreateTreeModal onCreated={handleTreeCreated} />
    </ReactFlowProvider>
  );
}

function CanvasToolbar({
  onZoomIn,
  onZoomOut,
  onCenter
}: {
  onZoomIn: () => void;
  onZoomOut: () => void;
  onCenter: () => void;
}): JSX.Element {
  return (
    <div className="flex items-center gap-2 text-xs text-slate-200">
      <button
        type="button"
        onClick={onZoomOut}
        className="rounded-md border border-slate-700 bg-surface-sunken px-2 py-1 font-semibold transition hover:border-slate-500 hover:text-white"
      >
        Zoom out
      </button>
      <button
        type="button"
        onClick={onZoomIn}
        className="rounded-md border border-slate-700 bg-surface-sunken px-2 py-1 font-semibold transition hover:border-slate-500 hover:text-white"
      >
        Zoom in
      </button>
      <button
        type="button"
        onClick={onCenter}
        className="rounded-md border border-slate-700 bg-surface-sunken px-2 py-1 font-semibold transition hover:border-slate-500 hover:text-white"
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
    <div className="flex h-full flex-col items-center justify-center gap-3 text-center text-sm text-slate-400">
      <p>{hasTrees ? "Select a tree from the dropdown to visualize it." : "Create your first tree to get started."}</p>
      <p className="text-xs text-slate-500">Need help? Start by outlining the core problem in the first root node.</p>
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
