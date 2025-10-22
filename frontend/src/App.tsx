import { useEffect, useState } from "react";
import { ReactFlowProvider } from "reactflow";
import "reactflow/dist/style.css";

import type { TreeDetailResponse } from "./api/types";
import { useTree, useTrees } from "./api/hooks";
import { TreeCanvas } from "./components/canvas/TreeCanvas";
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

export default function App(): JSX.Element {
  const [selectedTreeId, setSelectedTreeId] = useState<string | null>(null);

  const { data: trees, isLoading: isTreesLoading } = useTrees();
  const setTree = useTreeStore((state) => state.setTree);
  const resetTree = useTreeStore((state) => state.reset);
  const metadata = useTreeStore((state) => state.metadata);
  const activeTreeId = useTreeStore((state) => state.activeTreeId);
  const inspectorTab = useUiStore((state) => state.inspectorTab);

  const treeQuery = useTree(selectedTreeId);

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

  return (
    <ReactFlowProvider>
      <Layout
        header={
          <TopBar
            title={metadata?.title ?? "Brain Buddy Canvas"}
            subtitle={metadata?.description ?? "Select a tree or create a new one to begin mapping."}
            rightSlot={
              <TreeSelector
                trees={trees}
                value={selectedTreeId}
                onChange={handleTreeChange}
                isLoading={isTreesLoading}
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
        <CanvasShell>
          {activeTreeId ? (
            <TreeCanvas treeId={activeTreeId} isLoading={isTreeLoading} />
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
