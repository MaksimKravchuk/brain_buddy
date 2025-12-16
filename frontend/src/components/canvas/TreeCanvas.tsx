import { forwardRef, useCallback, useEffect, useImperativeHandle, useMemo, useRef, useState } from "react";
import type {
  Connection,
  Edge,
  EdgeMouseHandler,
  Node,
  NodeMouseHandler,
  OnConnect,
  OnEdgesDelete,
  OnNodesDelete,
  OnSelectionChangeFunc,
  ReactFlowInstance
} from "reactflow";
import ReactFlow, { Background, MarkerType } from "reactflow";

import {
  mapNodeResponse,
  mapRelationResponse,
  useTreeStore,
  type GraphNode,
  type GraphRelation
} from "../../stores/treeStore";
import { useUiStore } from "../../stores/uiStore";
import {
  useCreateNode,
  useCreateRelation,
  useDeleteNode,
  useDeleteRelation,
  useUpdateNode
} from "../../api/hooks";
import type { RelationResponse } from "../../api/types";
import { getErrorMessage } from "../../utils/error";
import { useGraphProfiler } from "../../hooks/useGraphProfiler";
import { BrainNode } from "./BrainNode";

type NodeType = Node<{ node: GraphNode }>;
type EdgeType = Edge<{ relation: GraphRelation }>;

const nodeTypes = {
  brainNode: BrainNode
};

const defaultEdgeOptions: Partial<Edge> = {
  type: "smoothstep",
  animated: false,
  style: {
    stroke: "rgba(56,189,248,0.35)",
    strokeWidth: 2
  }
};

interface TreeCanvasProps {
  treeId: string;
  isLoading: boolean;
}

export interface TreeCanvasHandle {
  zoomIn(): void;
  zoomOut(): void;
  centerOnSelection(): void;
}

function createPlaceholderNode(type: GraphNode["type"], label: string): GraphNode {
  return {
    id: `tmp-${Math.random().toString(36).slice(2, 9)}`,
    label,
    position: { x: 0, y: 0 },
    type,
    highlightState: "none",
    relationCounts: { up: 0, down: 0 }
  };
}

function relationFromResponse(response: RelationResponse): GraphRelation {
  return mapRelationResponse(response);
}

export const TreeCanvas = forwardRef<TreeCanvasHandle, TreeCanvasProps>(function TreeCanvas(
  { treeId, isLoading }: TreeCanvasProps,
  ref
): JSX.Element {
  const nodes = useTreeStore((state) => state.nodes);
  const relations = useTreeStore((state) => state.relations);
  const selection = useTreeStore((state) => state.selection);
  const select = useTreeStore((state) => state.select);
  const upsertNode = useTreeStore((state) => state.upsertNode);
  const removeNode = useTreeStore((state) => state.removeNode);
  const upsertRelation = useTreeStore((state) => state.upsertRelation);
  const removeRelation = useTreeStore((state) => state.removeRelation);
  const pushSnapshot = useTreeStore((state) => state.pushSnapshot);
  const beginOptimisticChange = useTreeStore((state) => state.beginOptimisticChange);
  const resolveOptimisticChange = useTreeStore((state) => state.resolveOptimisticChange);
  const rollbackOptimisticChange = useTreeStore((state) => state.rollbackOptimisticChange);
  const undo = useTreeStore((state) => state.undo);
  const redo = useTreeStore((state) => state.redo);
  const pushToast = useUiStore((state) => state.pushToast);
  const registerHotkey = useUiStore((state) => state.registerHotkey);
  const unregisterHotkey = useUiStore((state) => state.unregisterHotkey);
  const triggerHotkey = useUiStore((state) => state.triggerHotkey);

  const createNodeMutation = useCreateNode(treeId);
  const updateNodeMutation = useUpdateNode(treeId);
  const deleteNodeMutation = useDeleteNode(treeId);
  const createRelationMutation = useCreateRelation(treeId);
  const deleteRelationMutation = useDeleteRelation(treeId);

  const [reactFlowInstance, setReactFlowInstance] = useState<ReactFlowInstance | null>(null);
  const hasCreatedDefaultNode = useRef(false);
  const canvasRef = useRef<HTMLDivElement | null>(null);

  useGraphProfiler({
    nodeCount: nodes.length,
    edgeCount: relations.length
  });
  const [linkSourceId, setLinkSourceId] = useState<string | null>(null);

  const handleUndo = useCallback(() => {
    undo();
  }, [undo]);

  const handleRedo = useCallback(() => {
    redo();
  }, [redo]);

  const handleZoomIn = useCallback(() => {
    if (!reactFlowInstance) return;
    reactFlowInstance.zoomIn({ duration: 150 });
  }, [reactFlowInstance]);

  const handleZoomOut = useCallback(() => {
    if (!reactFlowInstance) return;
    reactFlowInstance.zoomOut({ duration: 150 });
  }, [reactFlowInstance]);

  const handleCenterOnSelection = useCallback(() => {
    if (!reactFlowInstance) return;
    if (selection.type === "node") {
      const node = nodes.find((item) => item.id === selection.id);
      if (!node) {
        return;
      }
      reactFlowInstance.setCenter(node.position.x, node.position.y, { zoom: 1.1, duration: 250 });
    } else {
      reactFlowInstance.fitView({ padding: 0.2, duration: 250 });
    }
  }, [nodes, reactFlowInstance, selection]);

  useImperativeHandle(
    ref,
    () => ({
      zoomIn: handleZoomIn,
      zoomOut: handleZoomOut,
      centerOnSelection: handleCenterOnSelection
    }),
    [handleCenterOnSelection, handleZoomIn, handleZoomOut]
  );

  const flowNodes = useMemo<NodeType[]>(() => {
    return nodes.map((node) => ({
      id: node.id,
      type: "brainNode",
      position: node.position,
      data: { node },
      selected: selection.type === "node" && selection.id === node.id
    }));
  }, [nodes, selection]);

  const flowEdges = useMemo<EdgeType[]>(() => {
    return relations.map((relation) => ({
      id: relation.id,
      source: relation.fromId,
      target: relation.toId,
      data: { relation },
      label: relation.kind.toUpperCase(),
      selected: selection.type === "relation" && selection.id === relation.id,
      type: "smoothstep",
      animated: false,
      style: {
        stroke: selection.type === "relation" && selection.id === relation.id ? "rgba(129,140,248,0.95)" : "rgba(56,189,248,0.55)",
        strokeWidth: selection.type === "relation" && selection.id === relation.id ? 3 : 2
      },
      markerEnd: {
        type: MarkerType.ArrowClosed,
        color: selection.type === "relation" && selection.id === relation.id ? "#a5b4fc" : "rgba(56,189,248,0.75)",
        width: 18,
        height: 18
      },
      labelStyle: {
        fill: "#cbd5f5",
        fontSize: 12,
        fontWeight: 500
      }
    }));
  }, [relations, selection]);

  const handleNodeClick = useCallback<NodeMouseHandler>(
    (_, node) => {
      select({ type: "node", id: node.id });
    },
    [select]
  );

  const handleNodeDoubleClick = useCallback<NodeMouseHandler>(
    (_, node) => {
      const graphNode = nodes.find((item) => item.id === node.id);
      if (!graphNode) {
        return;
      }

      const nextLabel = window.prompt("Rename node", graphNode.label);
      if (nextLabel === null) {
        return;
      }

      const trimmed = nextLabel.trim();
      if (!trimmed || trimmed === graphNode.label) {
        return;
      }

      pushSnapshot();
      const token = beginOptimisticChange("rename-node-inline");
      upsertNode({
        ...graphNode,
        label: trimmed
      });

      updateNodeMutation.mutate(
        { nodeId: graphNode.id, payload: { label: trimmed } },
        {
          onSuccess: () => {
            resolveOptimisticChange(token);
            pushToast({
              title: "Node renamed",
              description: "Label updated inline.",
              variant: "success",
              duration: 2500
            });
          },
          onError: (error) => {
            rollbackOptimisticChange(token);
            pushToast({
              title: "Failed to update node",
              description: getErrorMessage(error),
              variant: "error",
              duration: 6000
            });
          }
        }
      );
    },
    [
      beginOptimisticChange,
      nodes,
      pushSnapshot,
      pushToast,
      resolveOptimisticChange,
      rollbackOptimisticChange,
      select,
      updateNodeMutation,
      upsertNode
    ]
  );

  const handleNodesDelete = useCallback<OnNodesDelete>(
    (nodesToDelete) => {
      if (!nodesToDelete.length) {
        return;
      }

      nodesToDelete.forEach((node) => {
        pushSnapshot();
        const token = beginOptimisticChange("delete-node");
        removeNode(node.id);

        deleteNodeMutation.mutate(
          { nodeId: node.id, cascade: true },
          {
            onSuccess: () => {
              resolveOptimisticChange(token);
              pushToast({
                title: "Node deleted",
                description: `Removed ${node.data?.node?.label ?? "node"}.`,
                variant: "info",
                duration: 3000
              });
            },
            onError: (error) => {
              rollbackOptimisticChange(token);
              pushToast({
                title: "Failed to delete node",
                description: getErrorMessage(error),
                variant: "error",
                action: {
                  label: "Retry",
                  onClick: () => handleNodesDelete([node])
                }
              });
            }
          }
        );
      });
    },
    [
      beginOptimisticChange,
      deleteNodeMutation,
      pushSnapshot,
      pushToast,
      removeNode,
      resolveOptimisticChange,
      rollbackOptimisticChange
    ]
  );

  const handleNodeContextMenu = useCallback<NodeMouseHandler>(
    (event, node) => {
      event.preventDefault();
      select({ type: "node", id: node.id });
      const graphNode = nodes.find((item) => item.id === node.id);
      if (!graphNode) {
        return;
      }

      const shouldDelete = window.confirm(`Delete "${graphNode.label}" and its relations?`);
      if (!shouldDelete) {
        return;
      }

      handleNodesDelete([node]);
    },
    [handleNodesDelete, nodes, select]
  );

  const handleEdgeClick = useCallback<EdgeMouseHandler>(
    (_, edge) => {
      select({ type: "relation", id: edge.id });
    },
    [select]
  );

  const handlePaneClick = useCallback(() => {
    select({ type: null, id: null });
  }, [select]);

  const handleSelectionChange = useCallback<OnSelectionChangeFunc>(
    ({ nodes: selectedNodes, edges: selectedEdges }) => {
      if (selectedNodes?.length) {
        select({ type: "node", id: selectedNodes[0].id });
        return;
      }

      if (selectedEdges?.length) {
        select({ type: "relation", id: selectedEdges[0].id });
        return;
      }

      select({ type: null, id: null });
    },
    [select]
  );

  const handleNodeDragStop = useCallback<NodeMouseHandler>(
    (_, node) => {
      const graphNode = nodes.find((item) => item.id === node.id);
      if (!graphNode) {
        return;
      }

      pushSnapshot();
      const token = beginOptimisticChange("move-node");
      upsertNode({
        ...graphNode,
        position: { ...node.position }
      });

      updateNodeMutation.mutate(
        { nodeId: node.id, payload: { position: node.position } },
        {
          onSuccess: () => {
            resolveOptimisticChange(token);
          },
          onError: (error) => {
            rollbackOptimisticChange(token);
            pushToast({
              title: "Unable to update node position",
              description: getErrorMessage(error),
              variant: "error",
              duration: 6000
            });
          }
        }
      );
    },
    [
      beginOptimisticChange,
      nodes,
      pushSnapshot,
      pushToast,
      resolveOptimisticChange,
      rollbackOptimisticChange,
      updateNodeMutation,
      upsertNode
    ]
  );

  const handleConnect = useCallback<OnConnect>(
    (connection: Connection) => {
      if (!connection.source || !connection.target) {
        return;
      }

      const retryConnection: Connection = { ...connection };
      const now = new Date().toISOString();
      pushSnapshot();
      const token = beginOptimisticChange("create-relation");
      const tempRelation: GraphRelation = {
        id: `tmp-rel-${Math.random().toString(36).slice(2, 9)}`,
        fromId: connection.source,
        toId: connection.target,
        kind: "why",
        createdAt: now
      };

      upsertRelation(tempRelation);
      createRelationMutation.mutate(
        {
          from_id: connection.source,
          to_id: connection.target,
          kind: "why"
        },
        {
          onSuccess: (relation) => {
            resolveOptimisticChange(token);
            removeRelation(tempRelation.id);
            upsertRelation(relationFromResponse(relation));
            pushToast({
              title: "Relation created",
              description: "Connection established successfully.",
              variant: "success",
              duration: 3000
            });
          },
          onError: (error) => {
            rollbackOptimisticChange(token);
            removeRelation(tempRelation.id);
            pushToast({
              title: "Failed to create relation",
              description: getErrorMessage(error),
              variant: "error",
              action: {
                label: "Retry",
                onClick: () => handleConnect(retryConnection)
              }
            });
          }
        }
      );
    },
    [
      beginOptimisticChange,
      createRelationMutation,
      pushSnapshot,
      pushToast,
      removeRelation,
      resolveOptimisticChange,
      rollbackOptimisticChange,
      upsertRelation
    ]
  );

  const handleLinkNodes = useCallback(() => {
    const selectedNodeId = selection.type === "node" ? selection.id : null;
    if (!selectedNodeId) {
      pushToast({
        title: "Select a node first",
        description: "Choose a node to start linking.",
        variant: "warning",
        duration: 3500
      });
      return;
    }

    if (!linkSourceId) {
      setLinkSourceId(selectedNodeId);
      pushToast({
        title: "Link mode",
        description: "Select a target node to finish the link.",
        variant: "info",
        duration: 3000
      });
      return;
    }

    if (linkSourceId === selectedNodeId) {
      pushToast({
        title: "Pick a different node",
        description: "Choose another node to create a relation.",
        variant: "warning",
        duration: 3000
      });
      return;
    }

    handleConnect({
      source: linkSourceId,
      target: selectedNodeId
    } as Connection);
    setLinkSourceId(null);
  }, [handleConnect, linkSourceId, pushToast, selection]);

  const handleEdgesDelete = useCallback<OnEdgesDelete>(
    (edgesToDelete) => {
      if (!edgesToDelete.length) {
        return;
      }

      edgesToDelete.forEach((edge) => {
        pushSnapshot();
        const token = beginOptimisticChange("delete-relation");
        removeRelation(edge.id);
        const retryDelete = () => handleEdgesDelete([edge]);

        deleteRelationMutation.mutate(edge.id, {
          onSuccess: () => {
            resolveOptimisticChange(token);
          },
          onError: (error) => {
            rollbackOptimisticChange(token);
            pushToast({
              title: "Failed to delete relation",
              description: getErrorMessage(error),
              variant: "error",
              action: {
                label: "Retry",
                onClick: retryDelete
              }
            });
          }
        });
      });
    },
    [
      beginOptimisticChange,
      deleteRelationMutation,
      pushSnapshot,
      pushToast,
      removeRelation,
      resolveOptimisticChange,
      rollbackOptimisticChange
    ]
  );

  const handleCreateNode = useCallback(
    (input?: { label?: string; type?: GraphNode["type"] }) => {
      const type = input?.type ?? "regular";
      const label =
        input?.label?.trim() ||
        (type === "undesired_effect" ? "Undesired effect" : type === "cause" ? "Cause" : "New idea");
      const placeholder = createPlaceholderNode(type, label);
      const bounds = canvasRef.current?.getBoundingClientRect();
      const viewportCenter = reactFlowInstance
        ? reactFlowInstance.screenToFlowPosition({
            x: bounds ? bounds.left + bounds.width / 2 : window.innerWidth / 2,
            y: bounds ? bounds.top + bounds.height / 2 : window.innerHeight / 2
          })
        : { x: Math.random() * 200, y: Math.random() * 200 };

      placeholder.position = viewportCenter;

      pushSnapshot();
      const token = beginOptimisticChange("create-node");
      upsertNode(placeholder);

      createNodeMutation.mutate(
        {
          label: placeholder.label,
          position: viewportCenter,
          type,
          highlight_state: "none"
        },
        {
          onSuccess: (nodeResponse) => {
            resolveOptimisticChange(token);
            removeNode(placeholder.id);
            upsertNode(mapNodeResponse(nodeResponse));
            select({ type: "node", id: nodeResponse.id });
            pushToast({
              title: "Node created",
              description: "Node added to the canvas.",
              variant: "success",
              duration: 3000
            });
          },
          onError: (error) => {
            rollbackOptimisticChange(token);
            removeNode(placeholder.id);
            pushToast({
              title: "Failed to create node",
              description: getErrorMessage(error),
              variant: "error",
              action: {
                label: "Retry",
                onClick: handleCreateNode
              }
            });
          }
        }
      );
    },
    [
      beginOptimisticChange,
      createNodeMutation,
      pushSnapshot,
      pushToast,
      canvasRef,
      reactFlowInstance,
      removeNode,
      resolveOptimisticChange,
      rollbackOptimisticChange,
      select,
      upsertNode
    ]
  );

  useEffect(() => {
    hasCreatedDefaultNode.current = false;
  }, [treeId]);

  useEffect(() => {
    if (isLoading || nodes.length > 0 || !reactFlowInstance || hasCreatedDefaultNode.current) {
      return;
    }

    hasCreatedDefaultNode.current = true;
    handleCreateNode({ type: "undesired_effect", label: "Undesired effect" });
  }, [handleCreateNode, isLoading, nodes.length, reactFlowInstance]);

  const buildCombo = useCallback((event: KeyboardEvent) => {
    const target = event.target as HTMLElement | null;
    if (target) {
      const tag = target.tagName?.toLowerCase();
      if (
        tag === "input" ||
        tag === "textarea" ||
        target.isContentEditable ||
        tag === "select" ||
        target.getAttribute("role") === "textbox"
      ) {
        return null;
      }
    }

    const parts: string[] = [];
    if (event.metaKey) parts.push("meta");
    if (event.ctrlKey) parts.push("ctrl");
    if (event.altKey) parts.push("alt");
    if (event.shiftKey) parts.push("shift");

    const key = event.key.toLowerCase();
    parts.push(key);

    return parts.join("+");
  }, []);

  useEffect(() => {
    const bindings = [
      { id: "create-node-meta", combo: "meta+shift+n", description: "Create node", handler: handleCreateNode },
      { id: "create-node-ctrl", combo: "ctrl+shift+n", description: "Create node", handler: handleCreateNode },
      { id: "link-nodes-meta", combo: "meta+shift+l", description: "Link nodes", handler: handleLinkNodes },
      { id: "link-nodes-ctrl", combo: "ctrl+shift+l", description: "Link nodes", handler: handleLinkNodes },
      { id: "zoom-in-meta", combo: "meta+=", description: "Zoom in", handler: handleZoomIn },
      { id: "zoom-in-ctrl", combo: "ctrl+=", description: "Zoom in", handler: handleZoomIn },
      { id: "zoom-in-meta-shift", combo: "meta+shift+=", description: "Zoom in", handler: handleZoomIn },
      { id: "zoom-in-ctrl-shift", combo: "ctrl+shift+=", description: "Zoom in", handler: handleZoomIn },
      { id: "zoom-out-meta", combo: "meta+-", description: "Zoom out", handler: handleZoomOut },
      { id: "zoom-out-ctrl", combo: "ctrl+-", description: "Zoom out", handler: handleZoomOut },
      { id: "center-meta", combo: "meta+shift+c", description: "Center on selection", handler: handleCenterOnSelection },
      { id: "center-ctrl", combo: "ctrl+shift+c", description: "Center on selection", handler: handleCenterOnSelection },
      { id: "undo-meta", combo: "meta+z", description: "Undo", handler: handleUndo },
      { id: "undo-ctrl", combo: "ctrl+z", description: "Undo", handler: handleUndo },
      { id: "redo-meta", combo: "meta+shift+z", description: "Redo", handler: handleRedo },
      { id: "redo-ctrl", combo: "ctrl+shift+z", description: "Redo", handler: handleRedo }
    ];

    bindings.forEach((binding) => registerHotkey(binding));
    return () => {
      bindings.forEach((binding) => unregisterHotkey(binding.id));
    };
  }, [
    handleCenterOnSelection,
    handleCreateNode,
    handleLinkNodes,
    handleRedo,
    handleUndo,
    handleZoomIn,
    handleZoomOut,
    registerHotkey,
    unregisterHotkey
  ]);

  useEffect(() => {
    const listener = (event: KeyboardEvent) => {
      const combo = buildCombo(event);
      if (!combo) return;
      const triggered = triggerHotkey(combo);
      if (triggered) {
        event.preventDefault();
      }
    };

    window.addEventListener("keydown", listener);
    return () => {
      window.removeEventListener("keydown", listener);
    };
  }, [buildCombo, triggerHotkey]);

  const hasContent = nodes.length > 0 || relations.length > 0;

  return (
    <div ref={canvasRef} className="relative h-full w-full">
      <ReactFlow
        aria-label="Current reality tree canvas"
        nodes={flowNodes}
        edges={flowEdges}
        nodeTypes={nodeTypes}
        defaultEdgeOptions={defaultEdgeOptions}
        fitView
        onInit={setReactFlowInstance}
        minZoom={0.1}
        maxZoom={1.5}
        onNodeClick={handleNodeClick}
        onNodeDoubleClick={handleNodeDoubleClick}
        onNodeContextMenu={handleNodeContextMenu}
        onEdgeClick={handleEdgeClick}
        onPaneClick={handlePaneClick}
        onSelectionChange={handleSelectionChange}
        onNodeDragStop={handleNodeDragStop}
        onConnect={handleConnect as OnConnect}
        onNodesDelete={handleNodesDelete as OnNodesDelete}
        onEdgesDelete={handleEdgesDelete as OnEdgesDelete}
        selectionOnDrag
        panOnDrag
        panOnScroll
        className="brain-buddy-canvas"
        deleteKeyCode={["Backspace", "Delete"]}
        snapToGrid
        snapGrid={[16, 16]}
        onlyRenderVisibleElements
        proOptions={{ hideAttribution: true }}
      >
        <Background gap={24} size={1} color="rgba(59,130,246,0.1)" />
      </ReactFlow>

      {!hasContent && !isLoading ? (
        <div className="pointer-events-none absolute inset-0 flex items-center justify-center text-sm text-slate-400">
          <p>No nodes yet. Start with the default undesired effect and grow connections from it.</p>
        </div>
      ) : null}

      {isLoading ? (
        <div className="pointer-events-none absolute inset-0 flex items-center justify-center bg-surface-base/60 text-sm text-slate-400 backdrop-blur">
          Loading tree…
        </div>
      ) : null}
    </div>
  );
});
