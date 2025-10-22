import { useCallback, useEffect, useMemo, useState } from "react";
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
import ReactFlow, { Background, Controls, MiniMap, Panel } from "reactflow";
import { twMerge } from "tailwind-merge";

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

function createPlaceholderNode(): GraphNode {
  const now = new Date().toISOString();
  return {
    id: `tmp-${Math.random().toString(36).slice(2, 9)}`,
    label: "New node",
    position: { x: 0, y: 0 },
    metadata: {
      createdAt: now,
      updatedAt: now,
      author: "local"
    },
    visual: null,
    validation: null,
    incomingCount: 0,
    outgoingCount: 0
  };
}

function relationFromResponse(response: RelationResponse): GraphRelation {
  return mapRelationResponse(response);
}

export function TreeCanvas({ treeId, isLoading }: TreeCanvasProps): JSX.Element {
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

  const createNodeMutation = useCreateNode(treeId);
  const updateNodeMutation = useUpdateNode(treeId);
  const deleteNodeMutation = useDeleteNode(treeId);
  const createRelationMutation = useCreateRelation(treeId);
  const deleteRelationMutation = useDeleteRelation(treeId);

  const [reactFlowInstance, setReactFlowInstance] = useState<ReactFlowInstance | null>(null);

  useGraphProfiler({
    nodeCount: nodes.length,
    edgeCount: relations.length
  });

  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if (event.key.toLowerCase() === "z" && (event.metaKey || event.ctrlKey)) {
        event.preventDefault();
        if (event.shiftKey) {
          redo();
        } else {
          undo();
        }
      }
    };

    window.addEventListener("keydown", handler);
    return () => {
      window.removeEventListener("keydown", handler);
    };
  }, [undo, redo]);

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
      source: relation.sourceId,
      target: relation.targetId,
      data: { relation },
      label: relation.questionLabel,
      selected: selection.type === "relation" && selection.id === relation.id,
      type: "smoothstep",
      animated: false,
      style: {
        stroke: selection.type === "relation" && selection.id === relation.id ? "rgba(129,140,248,0.9)" : "rgba(56,189,248,0.35)",
        strokeWidth: selection.type === "relation" && selection.id === relation.id ? 3 : 2
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
        label: trimmed,
        metadata: { ...graphNode.metadata, updatedAt: new Date().toISOString() }
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
        position: { ...node.position },
        metadata: { ...graphNode.metadata, updatedAt: new Date().toISOString() }
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
        sourceId: connection.source,
        targetId: connection.target,
        questionLabel: "WHY?",
        notes: null,
        metadata: {
          createdAt: now,
          updatedAt: now,
          author: "local"
        }
      };

      upsertRelation(tempRelation);
      createRelationMutation.mutate(
        {
          source_id: connection.source,
          target_id: connection.target,
          question_label: "WHY?"
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

  const handleNodesDelete = useCallback<OnNodesDelete>(
    (nodesToDelete) => {
      if (!nodesToDelete.length) {
        return;
      }

      nodesToDelete.forEach((node) => {
        pushSnapshot();
        const token = beginOptimisticChange("delete-node");
        removeNode(node.id);
        const retryDelete = () => handleNodesDelete([node]);

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
                  onClick: retryDelete
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

  const [creatingNode, setCreatingNode] = useState(false);

  const handleCreateNode = useCallback(() => {
    const placeholder = createPlaceholderNode();
    const viewportCenter = reactFlowInstance
      ? reactFlowInstance.screenToFlowPosition({
          x: window.innerWidth / 2,
          y: window.innerHeight / 2
        })
      : { x: Math.random() * 200, y: Math.random() * 200 };

    placeholder.position = viewportCenter;

    pushSnapshot();
    const token = beginOptimisticChange("create-node");
    setCreatingNode(true);
    upsertNode(placeholder);

    createNodeMutation.mutate(
      {
        label: placeholder.label,
        position: viewportCenter
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
        },
        onSettled: () => {
          setCreatingNode(false);
        }
      }
    );
  }, [
    beginOptimisticChange,
    createNodeMutation,
    pushSnapshot,
    pushToast,
    reactFlowInstance,
    removeNode,
    setCreatingNode,
    resolveOptimisticChange,
    rollbackOptimisticChange,
    select,
    upsertNode
  ]);

  const hasContent = nodes.length > 0 || relations.length > 0;

  return (
    <div className="relative h-full w-full">
      <ReactFlow
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
      >
        <Background gap={24} size={1} color="rgba(59,130,246,0.1)" />
        <MiniMap
          className="!bg-surface-sunken/80"
          nodeColor={(node) => (node.data?.node?.validation ? "#22c55e" : "#38bdf8")}
        />
        <Controls className="rounded-lg border border-slate-700 bg-surface-sunken/90 text-slate-200" />
        <Panel position="top-left" className="rounded-lg border border-slate-800 bg-surface-sunken/80 px-3 py-2 text-xs shadow-lg">
          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={handleCreateNode}
              className={twMerge(
                "rounded-md bg-brand-primary/90 px-3 py-1 text-xs font-semibold text-slate-950 transition hover:bg-brand-primary",
                creatingNode ? "pointer-events-none opacity-75" : ""
              )}
            >
              {creatingNode ? "Creating..." : "Add Node"}
            </button>
            <button
              type="button"
              onClick={() => select({ type: null, id: null })}
              className="rounded-md border border-slate-700/80 px-2 py-1 text-xs text-slate-300 transition hover:border-slate-500 hover:text-slate-100"
            >
              Clear selection
            </button>
            <span className="hidden text-slate-500 md:inline">Drag nodes to reposition, connect to relate.</span>
          </div>
        </Panel>
      </ReactFlow>

      {!hasContent && !isLoading ? (
        <div className="pointer-events-none absolute inset-0 flex items-center justify-center text-sm text-slate-400">
          <p>No nodes yet. Use &ldquo;Add Node&rdquo; or click-and-drag between nodes once created.</p>
        </div>
      ) : null}

      {isLoading ? (
        <div className="pointer-events-none absolute inset-0 flex items-center justify-center bg-surface-base/60 text-sm text-slate-400 backdrop-blur">
          Loading tree…
        </div>
      ) : null}
    </div>
  );
}
