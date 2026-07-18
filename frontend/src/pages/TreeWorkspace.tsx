import { useEffect, useMemo, useRef, useState } from "react";
import { ReactFlowProvider } from "reactflow";
import "reactflow/dist/style.css";
import {
  AlertTriangle,
  LogOut,
  Maximize2,
  Minus,
  Plus,
  RotateCcw,
  Sparkles,
  Sprout
} from "lucide-react";

import { ApiError } from "../api/client";
import type { TreeDetailResponse } from "../api/types";
import {
  useTree,
  useTrees,
  useTreeDownload,
  useTreeImportWithToasts
} from "../api/hooks";
import { Button } from "../components/ui/Button";
import { TreeCanvas, type TreeCanvasHandle } from "../components/canvas/TreeCanvas";
import { PlannedWorkflowNavigation } from "../components/layout/PlannedWorkflowNavigation";
import { TreeMenu } from "../components/layout/TreeMenu";
import { CreateTreeModal } from "../components/modals/CreateTreeModal";
import { DeleteTreeModal } from "../components/modals/DeleteTreeModal";
import { RenameTreeModal } from "../components/modals/RenameTreeModal";
import { InspectorTabs } from "../components/panels/InspectorTabs";
import { NodeInspector } from "../components/panels/NodeInspector";
import { RelationInspector } from "../components/panels/RelationInspector";
import { VersionPanel } from "../components/panels/VersionPanel";
import { ToastStack } from "../components/ui/ToastStack";
import { useAuthStore } from "../stores/authStore";
import { useTreeStore } from "../stores/treeStore";
import { useUiStore } from "../stores/uiStore";
import { getErrorMessage } from "../utils/error";

export default function TreeWorkspace(): JSX.Element {
  const [selectedTreeId, setSelectedTreeId] = useState<string | null>(null);
  const canvasRef = useRef<TreeCanvasHandle | null>(null);
  const importInputRef = useRef<HTMLInputElement | null>(null);

  const { data: trees, error: treesError, refetch: refetchTrees } = useTrees();
  const setTree = useTreeStore((state) => state.setTree);
  const resetTree = useTreeStore((state) => state.reset);
  const metadata = useTreeStore((state) => state.metadata);
  const activeTreeId = useTreeStore((state) => state.activeTreeId);
  const openModal = useUiStore((state) => state.openModal);
  const pushToast = useUiStore((state) => state.pushToast);
  const inspectorTab = useUiStore((state) => state.inspectorTab);

  const user = useAuthStore((state) => state.user);
  const logout = useAuthStore((state) => state.logout);

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
    if (!treeQuery.data) {
      return;
    }
    setTree(treeQuery.data);
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

  const handleTreeDeleted = async (deletedId: string) => {
    const refreshed = await refetchTrees();
    const remaining = refreshed.data ?? trees?.filter((tree) => tree.id !== deletedId) ?? [];

    if (selectedTreeId === deletedId) {
      const nextId = remaining[0]?.id ?? null;
      setSelectedTreeId(nextId);
      if (!nextId) {
        resetTree();
      }
    }
  };

  const isTreeLoading = treeQuery.isLoading;
  const handleZoomIn = () => canvasRef.current?.zoomIn();
  const handleZoomOut = () => canvasRef.current?.zoomOut();
  const handleCenter = () => canvasRef.current?.centerOnSelection();

  const treeName = useMemo(() => metadata?.name ?? "Untitled tree", [metadata?.name]);

  return (
    <ReactFlowProvider>
      <div className="flex min-h-screen flex-col bg-surface-base text-slate-900">
        <header className="relative z-30 border-b border-slate-200 bg-surface-raised/90 px-6 py-3 shadow-floating backdrop-blur">
          <div className="flex items-center gap-4">
            <TreeMenu
              treeName={treeName}
              activeTreeId={activeTreeId}
              trees={trees}
              isDownloading={isDownloading}
              isImporting={isImporting}
              onCreateTree={() => openModal("createTree")}
              onRenameTree={() => openModal("renameTree")}
              onDownload={download}
              onImportClick={() => importInputRef.current?.click()}
              onDeleteTree={() => openModal("deleteTree")}
              onSwitchTree={(treeId) => setSelectedTreeId(treeId)}
            />
            <PlannedWorkflowNavigation />
            <input
              ref={importInputRef}
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
            <div className="ml-auto flex items-center gap-2">
              {user ? (
                <span className="hidden truncate text-xs text-slate-500 sm:inline" title={user.email}>
                  {user.email}
                </span>
              ) : null}
              <Button
                variant="secondary"
                size="sm"
                leftIcon={<LogOut />}
                onClick={() => {
                  void logout();
                }}
              >
                Sign out
              </Button>
            </div>
          </div>
        </header>

        <main className="relative flex flex-1 overflow-hidden">
          <div className="relative flex-1">
            {treeError ? (
              <ErrorCanvasState
                message={getErrorMessage(treeError)}
                correlationId={
                  treeError instanceof ApiError
                    ? treeError.correlationId ?? undefined
                    : undefined
                }
                isRetrying={treeQuery.isFetching}
                onRetry={() => refetchTree()}
              />
            ) : activeTreeId ? (
              <TreeCanvas
                ref={canvasRef}
                treeId={activeTreeId}
                isLoading={isTreeLoading}
              />
            ) : (
              <EmptyCanvasState
                isLoading={isTreeLoading}
                hasTrees={Boolean(trees?.length)}
                onCreate={() => openModal("createTree")}
              />
            )}

            <FloatingZoomControls
              onZoomIn={handleZoomIn}
              onZoomOut={handleZoomOut}
              onCenter={handleCenter}
            />
          </div>
          <aside
            aria-label="Tree inspector"
            className="hidden w-96 shrink-0 overflow-y-auto border-l border-slate-200 bg-surface-sunken/80 px-4 py-5 shadow-soft xl:block"
          >
            <div className="space-y-5">
              <InspectorTabs />
              {inspectorTab === "node" ? <NodeInspector /> : null}
              {inspectorTab === "relation" ? <RelationInspector /> : null}
              {inspectorTab === "versions" ? <VersionPanel /> : null}
            </div>
          </aside>
        </main>
      </div>

      <ToastStack />
      <CreateTreeModal onCreated={handleTreeCreated} />
      <RenameTreeModal />
      <DeleteTreeModal trees={trees} onDeleted={handleTreeDeleted} />
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
    <div
      className="pointer-events-auto absolute right-6 bottom-6 z-20 flex items-center gap-1 rounded-xl border border-slate-200 bg-white/90 p-1 shadow-floating backdrop-blur animate-fade-in-up"
    >
      <Button
        variant="icon"
        size="sm"
        leftIcon={<Plus />}
        aria-label="Zoom in"
        onClick={onZoomIn}
      />
      <Button
        variant="icon"
        size="sm"
        leftIcon={<Minus />}
        aria-label="Zoom out"
        onClick={onZoomOut}
      />
      <div className="mx-0.5 h-5 w-px bg-slate-200" aria-hidden />
      <Button
        variant="icon"
        size="sm"
        leftIcon={<Maximize2 />}
        aria-label="Center on selection"
        onClick={onCenter}
      />
    </div>
  );
}

function EmptyCanvasState({
  isLoading,
  hasTrees,
  onCreate
}: {
  isLoading: boolean;
  hasTrees: boolean;
  onCreate: () => void;
}): JSX.Element {
  if (isLoading) {
    return (
      <div className="flex h-full items-center justify-center gap-3 text-sm text-slate-500 animate-fade-in">
        <Sparkles className="h-5 w-5 animate-pulse text-brand-primary" />
        <span>Loading tree…</span>
      </div>
    );
  }

  return (
    <div className="flex h-full items-center justify-center p-10 animate-fade-in-up">
      <div className="flex max-w-md flex-col items-center gap-4 text-center">
        <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-brand-primary/10 text-brand-primary shadow-soft">
          <Sprout className="h-7 w-7" />
        </div>
        <div className="space-y-1">
          <p className="text-display font-semibold text-slate-900">
            Start with your first undesired effect
          </p>
          <p className="text-sm text-slate-500">
            {hasTrees
              ? "Your most recent tree loads automatically. Continue mapping or start a new one."
              : "Create a new tree to drop in your initial thought and build from there."}
          </p>
        </div>
        <Button
          variant="primary"
          size="md"
          leftIcon={<Plus />}
          onClick={onCreate}
        >
          Create a new tree
        </Button>
      </div>
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
    <div className="flex h-full items-center justify-center p-10 animate-fade-in-up">
      <div className="flex max-w-md flex-col items-center gap-4 rounded-2xl border border-slate-200 bg-surface-raised p-6 text-center shadow-raised">
        <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-rose-50 text-rose-600">
          <AlertTriangle className="h-6 w-6" />
        </div>
        <div className="space-y-1">
          <p className="text-title font-semibold text-slate-900">
            We couldn't load this tree
          </p>
          <p className="text-sm text-slate-500">{message}</p>
          {correlationId ? (
            <p className="text-xs text-slate-400">Reference: {correlationId}</p>
          ) : null}
        </div>
        <Button
          variant="secondary"
          size="sm"
          leftIcon={<RotateCcw />}
          onClick={onRetry}
          isLoading={isRetrying}
        >
          Retry
        </Button>
      </div>
    </div>
  );
}
