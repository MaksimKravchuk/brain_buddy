import {
  applyNodeChanges,
  Background,
  BaseEdge,
  MarkerType,
  Position,
  ReactFlow,
  ReactFlowProvider,
  useReactFlow,
  useUpdateNodeInternals,
  type Connection,
  type Edge,
  type EdgeProps,
  type Node,
  type NodeChange,
  type Viewport
} from "@xyflow/react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  commitHistory,
  connectRelation,
  createHistory,
  deleteNode,
  deleteRelation,
  enterCreate,
  redo,
  tabCreate,
  undo,
  type GraphNode,
  type GraphRelation,
  type GraphState,
  type NewNodeIds,
  buildCrtEdgePath
} from "./graphModel";
import { CrtCardNode, type CrtCard, type CrtCardBadge } from "./CrtCardNode";
import { CrtCardDeleteConfirmation } from "./CrtCardDeleteConfirmation";
import "@xyflow/react/dist/style.css";
import "./crtCanvas.css";

type CrtCanvasProps = {
  graph: GraphState;
  onChange: (next: GraphState) => void;
  historyKey?: string;
  saveStatus?: "Saved" | "Unsaved changes";
  createIds?: () => NewNodeIds;
  idFactory?: () => NewNodeIds;
  confirmDelete?: (node: GraphNode) => boolean | Promise<boolean>;
};

type CrtEdge = Edge<{
  sourceLabel: string;
  targetLabel: string;
  routeOffset: number;
  selected: boolean;
  onSelect?: (relationId: string) => void;
  onDelete?: (relationId: string) => void;
}, "crt-edge">;

const MAX_CANVAS_ZOOM = 1;
const MIN_CANVAS_ZOOM = 0.25;
const CRT_CARD_WIDTH = 220;
const CRT_EDGE_ENDPOINT_INSET = 24;
const CRT_EDGE_MAX_ENDPOINT_OFFSET = CRT_CARD_WIDTH / 2 - CRT_EDGE_ENDPOINT_INSET;
const NODE_TYPES = { "crt-card": CrtCardNode };
const EDGE_TYPES = { "crt-edge": CrtEdgeComponent };
const CRT_EDGE_MARKER = {
  type: MarkerType.ArrowClosed,
  color: "#64748b",
  width: 18,
  height: 18,
  markerUnits: "strokeWidth",
  orient: "auto-start-reverse"
} as const;

function graphsAreEquivalent(left: GraphState, right: GraphState): boolean {
  if (
    left.selectedNodeId !== right.selectedNodeId ||
    left.editingNodeId !== right.editingNodeId ||
    left.selectedRelationId !== right.selectedRelationId ||
    left.viewportCenter.x !== right.viewportCenter.x ||
    left.viewportCenter.y !== right.viewportCenter.y ||
    left.viewportZoom !== right.viewportZoom ||
    left.nodes.length !== right.nodes.length ||
    left.relations.length !== right.relations.length
  ) return false;

  const rightNodes = new Map(right.nodes.map((node) => [node.id, node]));
  if (!left.nodes.every((node) => {
    const candidate = rightNodes.get(node.id);
    return candidate !== undefined &&
      candidate.label === node.label &&
      candidate.position.x === node.position.x &&
      candidate.position.y === node.position.y;
  })) return false;

  const rightRelations = new Map(right.relations.map((relation) => [relation.id, relation]));
  return left.relations.every((relation) => {
    const candidate = rightRelations.get(relation.id);
    return candidate !== undefined &&
      candidate.sourceId === relation.sourceId &&
      candidate.targetId === relation.targetId;
  });
}

function badgeForNode(nodeId: string, relations: readonly GraphRelation[]): CrtCardBadge | undefined {
  const hasIncoming = relations.some((relation) => relation.targetId === nodeId);
  const hasOutgoing = relations.some((relation) => relation.sourceId === nodeId);
  if (!hasIncoming && !hasOutgoing) return undefined;
  if (!hasIncoming) return "Root cause";
  if (!hasOutgoing) return "Effect";
  return "Intermediate";
}

function CrtEdgeComponent({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  style,
  selected,
  data,
  markerEnd
}: EdgeProps<CrtEdge>): React.JSX.Element {
  const routeOffset = data?.routeOffset ?? 0;
  const endpointOffset = Math.max(
    -CRT_EDGE_MAX_ENDPOINT_OFFSET,
    Math.min(CRT_EDGE_MAX_ENDPOINT_OFFSET, routeOffset)
  );
  const path = buildCrtEdgePath({
    sourceX,
    sourceY,
    targetX: targetX + endpointOffset,
    targetY,
    routeOffset: endpointOffset
  });
  const relationLabel = `Relation from ${data?.sourceLabel ?? "Untitled card"} to ${data?.targetLabel ?? "Untitled card"}`;
  return (
    <g
      data-testid={`crt-edge-${id}`}
      aria-label={relationLabel}
      role="button"
      tabIndex={0}
      aria-pressed={selected}
      onFocus={() => data?.onSelect?.(id)}
      onClick={() => data?.onSelect?.(id)}
      onKeyDown={(event) => {
        if (event.key === "Delete") {
          event.preventDefault();
          event.stopPropagation();
          data?.onDelete?.(id);
        }
      }}
    >
      <BaseEdge
        id={id}
        path={path}
        markerEnd={markerEnd}
        role="img"
        aria-label="Directed relation"
        style={{ ...style, stroke: selected ? "#0284c7" : "#64748b", strokeWidth: selected ? 3 : 2 }}
      />
    </g>
  );
}

function defaultIdsFactory(): () => NewNodeIds {
  return () => ({
    nodeId: `node_${globalThis.crypto.randomUUID()}`,
    relationId: `relation_${globalThis.crypto.randomUUID()}`
  });
}

function isNativeControl(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  if (target.closest("[data-crt-card='true']")) return false;
  return Boolean(target.closest("input, textarea, select, button, [role='dialog'], [role='alertdialog'], [role='menu'], [data-crt-native='true']"));
}

function CrtCanvasInner({ graph, onChange, historyKey, saveStatus = "Saved", createIds, idFactory, confirmDelete }: CrtCanvasProps): React.JSX.Element {
  const reactFlow = useReactFlow();
  const setFlowEdges = reactFlow.setEdges;
  const updateNodeInternals = useUpdateNodeInternals();
  const [history, setHistory] = useState(() => createHistory(graph));
  const [compositeMode, setCompositeMode] = useState(false);
  const [connectMode, setConnectMode] = useState(false);
  const [panMode, setPanMode] = useState(false);
  const [spacePressed, setSpacePressed] = useState(false);
  const [zoom, setZoom] = useState(graph.viewportZoom);
  const [pendingDelete, setPendingDelete] = useState<{
    node: GraphNode;
    relationConsequences: readonly string[];
  } | null>(null);
  const [shortcutsOpen, setShortcutsOpen] = useState(false);
  const shortcutModeClosedRef = useRef(false);
  const shouldFitInitialViewport =
    graph.hasPersistedViewport !== true && graph.viewportZoom === 1 && graph.viewportCenter.x === 0 && graph.viewportCenter.y === 0;

  const [announcement, setAnnouncement] = useState("Canvas ready. Select a card to begin.");
  const fallbackFactory = useMemo(() => defaultIdsFactory(), []);
  const makeIds = createIds ?? idFactory ?? fallbackFactory;
  const graphRef = useRef(graph);
  const onChangeRef = useRef(onChange);
  const historyRef = useRef(history);
  const historyKeyRef = useRef(historyKey);
  const canvasRef = useRef<HTMLElement>(null);
  const flowRegionRef = useRef<HTMLDivElement>(null);
  const pendingConnectionRef = useRef<{ nodeId: string; side: "source" | "target" } | null>(null);
  const pointerConnectionRef = useRef<{
    nodeId: string;
    side: "source" | "target";
    startX: number;
    startY: number;
    dragging: boolean;
  } | null>(null);
  const pendingCompositeEntryRef = useRef(false);
  const programmaticFocusRef = useRef(false);
  onChangeRef.current = onChange;

  useEffect(() => {
    const current = historyRef.current;
    const historyKeyChanged = historyKeyRef.current !== historyKey;
    if (historyKeyChanged || current.present !== graph) {
      const nextHistory = !historyKeyChanged && graphsAreEquivalent(current.present, graph)
        ? { ...current, present: graph }
        : createHistory(graph);
      historyRef.current = nextHistory;
      setHistory(nextHistory);
    }
    historyKeyRef.current = historyKey;
    graphRef.current = graph;
    setZoom(graph.viewportZoom);
  }, [graph, historyKey]);

  useEffect(() => {
    const frame = window.requestAnimationFrame(() => {
      updateNodeInternals(graph.nodes.map((node) => node.id));
    });
    return () => window.cancelAnimationFrame(frame);
  }, [graph.nodes, updateNodeInternals]);

  useEffect(() => {
    historyRef.current = history;
  }, [history]);

  const emit = useCallback(
    (next: GraphState, options: { history?: boolean; message?: string }) => {
      graphRef.current = next;
      if (options.history !== false) {
        setHistory((current) => {
          const updated = commitHistory(current, next);
          historyRef.current = updated;
          return updated;
        });
      } else {
        setHistory((current) => {
          const updated = { ...current, present: next };
          historyRef.current = updated;
          return updated;
        });
      }
      if (options.message) setAnnouncement(options.message);
      onChangeRef.current(next);
    },
    []
  );

  const applyCommand = useCallback(
    (result: ReturnType<typeof enterCreate>, successMessage: string) => {
      if (result.error) {
        setAnnouncement(result.error.message);
        return;
      }
      if (!result.changed) return;
      emit(result.state, { message: successMessage });
      if (result.focusNodeId || result.editingNodeId) {
        window.requestAnimationFrame(() => {
          window.requestAnimationFrame(() => {
            void reactFlow.fitView({ duration: 160, padding: 0.2, maxZoom: MAX_CANVAS_ZOOM });
            const editor = result.editingNodeId
              ? document.querySelector<HTMLInputElement>(`[data-card-editor-id="${result.editingNodeId}"]`)
              : null;
            editor?.focus();
            if (!editor && result.focusNodeId) {
              document.querySelector<HTMLButtonElement>(`[data-node-id="${result.focusNodeId}"]`)?.focus();
            }
          });
        });
      }
    },
    [emit, reactFlow]
  );

  const commitCardLabel = useCallback(
    (nodeId: string, label: string): boolean => {
      if (!label.trim()) {
        setAnnouncement("Card labels cannot be blank.");
        return false;
      }
      const current = graphRef.current.nodes.find((node) => node.id === nodeId);
      if (!current) return false;
      emit(
        {
          ...graphRef.current,
          nodes: graphRef.current.nodes.map((node) => (node.id === nodeId ? { ...node, label } : node)),
          editingNodeId: null
        },
        { history: false, message: "Card label updated." }
      );
      return true;
    },
    [emit]
  );

  const cancelCardLabel = useCallback(
    (nodeId: string) => {
      emit({ ...graphRef.current, editingNodeId: graphRef.current.editingNodeId === nodeId ? null : graphRef.current.editingNodeId }, { history: false, message: "Card editing cancelled." });
    },
    [emit]
  );

  const editCardLabel = useCallback(
    (nodeId: string) => {
      emit(
        { ...graphRef.current, selectedNodeId: nodeId, selectedRelationId: null, editingNodeId: nodeId },
        { history: false, message: "Editing card label." }
      );
    },
    [emit]
  );

  const draftCardLabelChange = useCallback(
    (nodeId: string, label: string) => {
      emit(
        { ...graphRef.current, nodes: graphRef.current.nodes.map((node) => node.id === nodeId ? { ...node, label } : node) },
        { history: false }
      );
    },
    [emit]
  );

  const activateConnector = useCallback(
    (nodeId: string, side: "source" | "target") => {
      const pending = pendingConnectionRef.current;
      if (!pending || pending.side === side) {
        pendingConnectionRef.current = { nodeId, side };
        setAnnouncement(side === "source" ? "Source selected. Choose an effect connector." : "Target selected. Choose a cause connector.");
        return;
      }
      const sourceId = side === "target" ? pending.nodeId : nodeId;
      const targetId = side === "target" ? nodeId : pending.nodeId;
      pendingConnectionRef.current = null;
      const result = connectRelation(graphRef.current, { id: makeIds().relationId, sourceId, targetId });
      if (result.error) {
        setAnnouncement(result.error.message);
      } else if (result.changed) {
        emit(result.state, { message: "Directed relation added." });
      }
    },
    [emit, makeIds]
  );

  const startPointerConnection = useCallback((nodeId: string, side: "source" | "target", event: React.PointerEvent<HTMLButtonElement>) => {
    pointerConnectionRef.current = { nodeId, side, startX: event.clientX, startY: event.clientY, dragging: false };
  }, []);

  const finishPointerConnection = useCallback((destination: { nodeId: string; side: "source" | "target" } | null) => {
    const pointerConnection = pointerConnectionRef.current;
    pointerConnectionRef.current = null;
    if (!pointerConnection?.dragging) return;
    // A drag is a complete connection gesture, independent of any earlier
    // click-to-connect selection. Never leave that older selection armed.
    pendingConnectionRef.current = null;
    if (!destination || destination.side === pointerConnection.side) return;
    const sourceId = pointerConnection.side === "source" ? pointerConnection.nodeId : destination.nodeId;
    const targetId = pointerConnection.side === "source" ? destination.nodeId : pointerConnection.nodeId;
    const result = connectRelation(graphRef.current, { id: makeIds().relationId, sourceId, targetId });
    if (result.error) setAnnouncement(result.error.message);
    else if (result.changed) emit(result.state, { message: "Directed relation added." });
  }, [emit, makeIds]);

  useEffect(() => {
    const onPointerMove = (event: PointerEvent): void => {
      const current = pointerConnectionRef.current;
      if (!current || current.dragging) return;
      if (Math.hypot(event.clientX - current.startX, event.clientY - current.startY) < 4) return;
      pointerConnectionRef.current = { ...current, dragging: true };
    };
    const onPointerUp = (event: PointerEvent): void => {
      const current = pointerConnectionRef.current;
      if (!current) return;
      if (!current.dragging) {
        pointerConnectionRef.current = null;
        return;
      }
      const element = document.elementFromPoint(event.clientX, event.clientY);
      const button = element?.closest<HTMLButtonElement>(".crt-card-connector[data-connector-node-id]");
      finishPointerConnection(button ? {
        nodeId: button.dataset.connectorNodeId ?? "",
        side: button.dataset.connectorSide as "source" | "target"
      } : null);
    };
    window.addEventListener("pointermove", onPointerMove);
    window.addEventListener("pointerup", onPointerUp);
    return () => {
      window.removeEventListener("pointermove", onPointerMove);
      window.removeEventListener("pointerup", onPointerUp);
    };
  }, [finishPointerConnection]);

  const handleCardFocus = useCallback((nodeId: string) => {
    if (graphRef.current.selectedNodeId !== nodeId) return;
    if (programmaticFocusRef.current) {
      programmaticFocusRef.current = false;
      return;
    }
    pendingCompositeEntryRef.current = true;
    setCompositeMode(true);
  }, []);

  const selectRelation = useCallback(
    (relationId: string) => {
      setCompositeMode(true);
      emit({ ...graphRef.current, selectedRelationId: relationId, selectedNodeId: null, editingNodeId: null }, { history: false, message: "Relation selected." });
    },
    [emit]
  );

  const removeRelation = useCallback(
    (relationId: string) => {
      const result = deleteRelation(graphRef.current, relationId);
      if (result.error) {
        setAnnouncement(result.error.message);
      } else if (result.changed) {
        emit(result.state, { message: "Relation deleted." });
      }
    },
    [emit]
  );

  const derivedFlowNodes = useMemo<CrtCard[]>(
    () =>
      graph.nodes.map((node) => ({
        id: node.id,
        type: "crt-card",
        position: node.position,
        width: 220,
        height: 92,
        handles: [
          { type: "target", position: Position.Bottom, x: 105, y: 82, width: 10, height: 10 },
          { type: "source", position: Position.Top, x: 105, y: 0, width: 10, height: 10 }
        ],
        sourcePosition: Position.Top,
        targetPosition: Position.Bottom,
        selected: graph.selectedNodeId === node.id,
        data: {
          label: node.label,
          badge: badgeForNode(node.id, graph.relations),
          selected: graph.selectedNodeId === node.id,
          editing: graph.editingNodeId === node.id,
          connectionMode: connectMode,
          onFocusCard: handleCardFocus,
          onCommitLabel: commitCardLabel,
          onCancelLabel: cancelCardLabel,
          onEditCard: editCardLabel,
          onDraftLabelChange: draftCardLabelChange,
          onConnectorActivate: activateConnector,
          onConnectorPointerDown: startPointerConnection
        }
      })),
    [
      activateConnector,
      cancelCardLabel,
      commitCardLabel,
      connectMode,
      draftCardLabelChange,
      editCardLabel,
      graph.editingNodeId,
      graph.nodes,
      graph.relations,
      graph.selectedNodeId,
      handleCardFocus,
      startPointerConnection
    ]
  );

  const [flowNodes, setFlowNodes] = useState<CrtCard[]>(derivedFlowNodes);

  useEffect(() => {
    setFlowNodes(derivedFlowNodes);
  }, [derivedFlowNodes]);

  const handleNodeChanges = useCallback((changes: NodeChange<CrtCard>[]) => {
    const positionChanges = changes.filter((change) => change.type === "position");
    if (positionChanges.length === 0) return;
    setFlowNodes((current) => applyNodeChanges(positionChanges, current));
  }, []);

  const flowEdges = useMemo<CrtEdge[]>(
    () => {
      const incomingRelations = new Map<string, string[]>();
      for (const relation of graph.relations) {
        const relations = incomingRelations.get(relation.targetId) ?? [];
        relations.push(relation.id);
        incomingRelations.set(relation.targetId, relations);
      }

      return graph.relations.map((relation) => {
        const targetRelations = incomingRelations.get(relation.targetId) ?? [relation.id];
        const routeIndex = targetRelations.indexOf(relation.id);
        const routeSpacing = Math.min(48, 192 / Math.max(1, targetRelations.length - 1));
        const routeOffset = (routeIndex - (targetRelations.length - 1) / 2) * routeSpacing;
        return {
          id: relation.id,
          type: "crt-edge",
          source: relation.sourceId,
          target: relation.targetId,
          selected: graph.selectedRelationId === relation.id,
          data: {
            sourceLabel: graph.nodes.find((node) => node.id === relation.sourceId)?.label || "Untitled card",
            targetLabel: graph.nodes.find((node) => node.id === relation.targetId)?.label || "Untitled card",
            routeOffset,
            selected: graph.selectedRelationId === relation.id,
            onSelect: selectRelation,
            onDelete: removeRelation
          },
          markerEnd: CRT_EDGE_MARKER
        };
      });
    },
    [graph.nodes, graph.relations, graph.selectedRelationId, removeRelation, selectRelation]
  );

  useEffect(() => {
    setFlowEdges(flowEdges);
  }, [flowEdges, setFlowEdges]);

  const selectNode = useCallback(
    (nodeId: string) => {
      const next = { ...graphRef.current, selectedNodeId: nodeId, editingNodeId: null, selectedRelationId: null };
      emit(next, { history: false, message: "Card selected." });
      pendingCompositeEntryRef.current = false;
      setCompositeMode(true);
    },
    [emit]
  );

  const navigateSelectedRelation = useCallback(
    (endpoint: "cause" | "effect") => {
      const relation = graphRef.current.relations.find((candidate) => candidate.id === graphRef.current.selectedRelationId);
      if (!relation) return;
      const nodeId = endpoint === "cause" ? relation.sourceId : relation.targetId;
      if (!graphRef.current.nodes.some((node) => node.id === nodeId)) {
        setAnnouncement(`Cannot navigate to the relation ${endpoint}; card is missing.`);
        return;
      }
      selectNode(nodeId);
    },
    [selectNode]
  );

  const focusRelated = useCallback(
    (direction: "up" | "down" | "left" | "right") => {
      const current = graphRef.current.nodes.find((node) => node.id === graphRef.current.selectedNodeId);
      if (!current) return;
      const related = graphRef.current.relations.flatMap((relation) => {
        const relatedId = relation.sourceId === current.id ? relation.targetId : relation.targetId === current.id ? relation.sourceId : null;
        if (!relatedId) return [];
        const relatedNode = graphRef.current.nodes.find((node) => node.id === relatedId);
        if (!relatedNode) return [];
        if (direction === "up" && !(relation.sourceId === current.id && relatedNode.position.y < current.position.y)) return [];
        if (direction === "down" && !(relation.targetId === current.id && relatedNode.position.y > current.position.y)) return [];
        if (direction === "left" && relatedNode.position.x >= current.position.x) return [];
        if (direction === "right" && relatedNode.position.x <= current.position.x) return [];
        return [relatedId];
      });
      const candidate = graphRef.current.nodes
        .filter((node) => related.includes(node.id))
        .sort((left, right) => {
          const leftDistance = (left.position.x - current.position.x) ** 2 + (left.position.y - current.position.y) ** 2;
          const rightDistance = (right.position.x - current.position.x) ** 2 + (right.position.y - current.position.y) ** 2;
          return leftDistance - rightDistance;
        })[0];
      if (!candidate) return;
      selectNode(candidate.id);
      window.requestAnimationFrame(() => {
        const destination = document.querySelector<HTMLButtonElement>(`[data-node-id="${candidate.id}"]`);
        if (!destination) {
          programmaticFocusRef.current = false;
          return;
        }
        programmaticFocusRef.current = true;
        destination.focus();
      });
    },
    [selectNode]
  );

  const commitZoom = useCallback((nextZoom: number) => {
    const boundedZoom = Math.min(MAX_CANVAS_ZOOM, Math.max(MIN_CANVAS_ZOOM, nextZoom));
    setZoom(boundedZoom);
    if (graphRef.current.viewportZoom === boundedZoom) return;
    emit({ ...graphRef.current, viewportZoom: boundedZoom, hasPersistedViewport: true }, { history: false });
  }, [emit]);

  const persistViewport = useCallback((nextViewport: Viewport) => {
    setZoom(nextViewport.zoom);
    const bounds = flowRegionRef.current?.getBoundingClientRect();
    const width = bounds?.width ?? 0;
    const height = bounds?.height ?? 0;
    const viewportCenter = width > 0 && height > 0
      ? { x: (width / 2 - nextViewport.x) / nextViewport.zoom, y: (height / 2 - nextViewport.y) / nextViewport.zoom }
      : graphRef.current.viewportCenter;
    if (
      graphRef.current.viewportZoom === nextViewport.zoom &&
      graphRef.current.viewportCenter.x === viewportCenter.x &&
      graphRef.current.viewportCenter.y === viewportCenter.y
    ) return;
    emit({ ...graphRef.current, viewportCenter, viewportZoom: nextViewport.zoom, hasPersistedViewport: true }, { history: false });
  }, [emit]);

  const fitAll = useCallback(() => {
    const fitting = reactFlow.fitView({ duration: 160, padding: 0.2, maxZoom: MAX_CANVAS_ZOOM });
    if (fitting) void fitting.then(() => persistViewport(reactFlow.getViewport()));
    setAnnouncement("All cards fit in view.");
  }, [persistViewport, reactFlow]);

  const confirmPendingDelete = useCallback(async (): Promise<boolean> => {
    const pending = pendingDelete;
    if (!pending) return false;
    const current = graphRef.current.nodes.find((node) => node.id === pending.node.id);
    if (!current) {
      setAnnouncement("The card to delete no longer exists.");
      return false;
    }
    const approved = confirmDelete ? await confirmDelete(current) : true;
    if (!approved) {
      setAnnouncement("Delete cancelled.");
      return false;
    }
    const result = deleteNode(graphRef.current, current.id, { confirmed: true });
    if (result.error) {
      setAnnouncement(result.error.message);
      return false;
    }
    if (result.changed) emit(result.state, { message: "Card deleted." });
    return result.changed;
  }, [confirmDelete, emit, pendingDelete]);

  const handleKeyDown = useCallback(
    (event: React.KeyboardEvent<HTMLElement>) => {
      if (isNativeControl(event.target)) return;
      const key = event.key;
      if (key === " ") {
        event.preventDefault();
        setSpacePressed(true);
        return;
      }
      if (key === "Delete" && graphRef.current.selectedRelationId) {
        event.preventDefault();
        removeRelation(graphRef.current.selectedRelationId);
        return;
      }
      if (pendingCompositeEntryRef.current && key === "Tab") {
        pendingCompositeEntryRef.current = false;
        setCompositeMode(false);
        return;
      }
      if (key === "Escape") {
        event.preventDefault();
        pendingCompositeEntryRef.current = false;
        shortcutModeClosedRef.current = true;
        setCompositeMode(false);
        setAnnouncement("Canvas shortcut mode closed. Tab now follows normal page navigation.");
        return;
      }
      if (key === "Tab" && shortcutModeClosedRef.current) {
        shortcutModeClosedRef.current = false;
        return;
      }
      if ((event.metaKey || event.ctrlKey) && key.toLowerCase() === "z") {
        event.preventDefault();
        const nextHistory = event.shiftKey ? redo(historyRef.current) : undo(historyRef.current);
        if (nextHistory.present !== historyRef.current.present) {
          historyRef.current = nextHistory;
          setHistory(nextHistory);
          graphRef.current = nextHistory.present;
          onChange(nextHistory.present);
          setAnnouncement(event.shiftKey ? "Redo complete." : "Undo complete.");
        }
        return;
      }
      if ((event.metaKey || event.ctrlKey) && key.toLowerCase() === "y") {
        event.preventDefault();
        const nextHistory = redo(historyRef.current);
        if (nextHistory.present !== historyRef.current.present) {
          historyRef.current = nextHistory;
          setHistory(nextHistory);
          graphRef.current = nextHistory.present;
          onChange(nextHistory.present);
          setAnnouncement("Redo complete.");
        }
        return;
      }
      if (key === "ArrowUp" || key === "ArrowDown" || key === "ArrowLeft" || key === "ArrowRight") {
        event.preventDefault();
        focusRelated(key.slice(5).toLowerCase() as "up" | "down" | "left" | "right");
        return;
      }
      if (key === "+" || key === "=") {
        event.preventDefault();
        void reactFlow.zoomIn({ duration: 120 });
        commitZoom(zoom + 0.1);
        return;
      }
      if (key === "-") {
        event.preventDefault();
        void reactFlow.zoomOut({ duration: 120 });
        commitZoom(zoom - 0.1);
        return;
      }
      if (key === "0") {
        event.preventDefault();
        fitAll();
        return;
      }
      if (!compositeMode) {
        if (key === "Enter") {
          event.preventDefault();
          setCompositeMode(true);
          pendingCompositeEntryRef.current = false;
          applyCommand(enterCreate(graphRef.current, makeIds()), "Cause added below the selected card.");
          return;
        }
        if (key === "Tab" && !graphRef.current.selectedNodeId) {
          event.preventDefault();
          setCompositeMode(true);
          pendingCompositeEntryRef.current = false;
          applyCommand(tabCreate(graphRef.current, makeIds()), "Card added.");
          return;
        }
        if (key !== "Delete" || !graphRef.current.selectedNodeId) return;
        setCompositeMode(true);
      }
      if (key === "Enter") {
        event.preventDefault();
        applyCommand(enterCreate(graphRef.current, makeIds()), "Cause added below the selected card.");
        return;
      }
      if (key === "Tab") {
        event.preventDefault();
        applyCommand(tabCreate(graphRef.current, makeIds()), "Sibling card added.");
        return;
      }
      if (key === "Delete" && graphRef.current.selectedNodeId) {
        event.preventDefault();
        const selected = graphRef.current.nodes.find((node) => node.id === graphRef.current.selectedNodeId);
        if (!selected) return;
        const connectedRelations = graphRef.current.relations.filter((relation) => relation.sourceId === selected.id || relation.targetId === selected.id);
        if (connectedRelations.length === 0) {
          const result = deleteNode(graphRef.current, selected.id, { confirmed: false });
          if (result.changed) emit(result.state, { message: "Card deleted." });
          return;
        }
        setPendingDelete({
          node: selected,
          relationConsequences: connectedRelations.map((relation) => {
            const source = graphRef.current.nodes.find((node) => node.id === relation.sourceId)?.label || "Untitled card";
            const target = graphRef.current.nodes.find((node) => node.id === relation.targetId)?.label || "Untitled card";
            return `${source} → ${target}`;
          })
        });
      }
    },
    [applyCommand, commitZoom, compositeMode, emit, fitAll, focusRelated, makeIds, onChange, reactFlow, removeRelation, zoom]
  );

  const updatePosition = useCallback(
    (_event: unknown, node: Node) => {
      const existing = graphRef.current.nodes.find((candidate) => candidate.id === node.id);
      if (!existing || (existing.position.x === node.position.x && existing.position.y === node.position.y)) return;
      emit(
        {
          ...graphRef.current,
          nodes: graphRef.current.nodes.map((candidate) => (candidate.id === node.id ? { ...candidate, position: node.position } : candidate))
        },
        { message: "Card moved." }
      );
    },
    [emit]
  );

  const handleConnection = useCallback(
    (connection: Connection) => {
      if (!connection.source || !connection.target) return;
      const result = connectRelation(graphRef.current, {
        id: makeIds().relationId,
        sourceId: connection.source,
        targetId: connection.target
      });
      if (result.error) {
        setAnnouncement(result.error.message);
      } else {
        emit(result.state, { message: "Directed relation added." });
      }
    },
    [emit, makeIds]
  );


  const updateViewport = useCallback((event: unknown, nextViewport: Viewport) => {
    // React Flow emits a programmatic move without an input event during its
    // initial fit. Only pointer/touch moves update the persisted pan.
    if (event) persistViewport(nextViewport);
    else setZoom(nextViewport.zoom);
  }, [persistViewport]);

  const selectedRelationId = graph.selectedRelationId;

  return (
    <section
      ref={canvasRef}
      className="crt-canvas-shell"
      role="group"
      aria-label="Current Reality Tree canvas"
      tabIndex={graph.selectedNodeId ? -1 : 0}
      onKeyDown={handleKeyDown}
      onKeyUp={(event) => {
        if (event.key === " ") setSpacePressed(false);
      }}
      onBlur={() => setSpacePressed(false)}
    >
      <header className="crt-canvas-toolbar">
        <h1 className="sr-only">Current Reality Tree</h1>
        <div className="crt-canvas-toolbar-actions">
          <span className="crt-save-status" role="status">{saveStatus}</span>
          <button
            type="button"
            data-crt-native="true"
            aria-expanded={shortcutsOpen}
            aria-controls="crt-shortcut-disclosure"
            onClick={() => {
              setShortcutsOpen((open) => !open);
              setAnnouncement("Shortcuts: Enter adds a cause; Tab adds a sibling; Escape exits canvas mode.");
            }}
          >
            Shortcuts
          </button>
        </div>
      </header>
      {shortcutsOpen ? (
        <aside id="crt-shortcut-disclosure" className="crt-shortcut-disclosure" role="region" aria-label="Canvas keyboard shortcuts">
          <h2>Canvas keyboard shortcuts</h2>
          <ul>
            <li><kbd>Enter</kbd> adds a cause below the selected card.</li>
            <li><kbd>Tab</kbd> adds a sibling only in shortcut mode; otherwise it follows normal page navigation.</li>
            <li><kbd>Escape</kbd> closes shortcut mode; it never cancels an async action.</li>
            <li><kbd>ArrowUp</kbd>/<kbd>ArrowDown</kbd> follows causal links.</li>
            <li><kbd>ArrowLeft</kbd>/<kbd>ArrowRight</kbd> follows spatially left/right related cards.</li>
            <li><kbd>Delete</kbd> deletes the selected card or relation.</li>
            <li><kbd>Ctrl/Cmd+Z</kbd> undoes; <kbd>Ctrl/Cmd+Shift+Z</kbd> and <kbd>Ctrl/Cmd+Y</kbd> redo.</li>
            <li><kbd>+</kbd>/<kbd>-</kbd> zoom; <kbd>0</kbd> fits all cards; <kbd>Space</kbd> pans while held.</li>
            <li><strong>Native controls:</strong> their text editing and ordinary <kbd>Tab</kbd> navigation are preserved.</li>
          </ul>
        </aside>
      ) : null}
      <div className="crt-canvas-workspace">
        <nav className="crt-tool-rail" aria-label="Canvas tools">
          <button type="button" data-crt-native="true" aria-label="Select tool" title="Select cards and relations" onClick={() => { setPanMode(false); setAnnouncement("Select tool active."); }}>Select</button>
          <button type="button" data-crt-native="true" aria-label="Add card" title="Add a cause card" onClick={() => applyCommand(enterCreate(graphRef.current, makeIds()), "Card added.")}>Add</button>
          <button type="button" data-crt-native="true" aria-label="Connect cards" title="Connect cause and effect cards" aria-pressed={connectMode} onClick={() => { setConnectMode((active) => !active); setAnnouncement(connectMode ? "Connect mode closed." : "Connect mode active. Drag from a cause handle to an effect handle."); }}>Connect</button>
          <button type="button" data-crt-native="true" aria-label="Pan canvas" title="Pan the canvas" aria-pressed={panMode} onClick={() => { setPanMode((active) => !active); setAnnouncement(panMode ? "Pan mode closed." : "Pan mode active."); }}>Pan</button>
        </nav>
        <div ref={flowRegionRef} className="crt-flow-region" data-testid="crt-flow-region" data-pan-active={panMode || spacePressed ? "true" : "false"}>
          <ReactFlow
            nodes={flowNodes}
            edges={flowEdges}
            nodeTypes={NODE_TYPES}
            edgeTypes={EDGE_TYPES}
            fitView={shouldFitInitialViewport}
            fitViewOptions={{ padding: 0.2, maxZoom: MAX_CANVAS_ZOOM }}
            panOnDrag={panMode || spacePressed}
            nodesConnectable={connectMode}
            nodesFocusable={false}
            edgesFocusable
            minZoom={MIN_CANVAS_ZOOM}
            maxZoom={MAX_CANVAS_ZOOM}
            onNodesChange={handleNodeChanges}
            onNodeClick={(_, node) => selectNode(node.id)}
            onNodeDragStop={updatePosition}
            onConnect={handleConnection}
            onInit={(instance) => {
              if (shouldFitInitialViewport) return;
              window.requestAnimationFrame(() => {
                const bounds = flowRegionRef.current?.getBoundingClientRect();
                const width = bounds?.width ?? 0;
                const height = bounds?.height ?? 0;
                void instance.setViewport({
                  x: width / 2 - graph.viewportCenter.x * graph.viewportZoom,
                  y: height / 2 - graph.viewportCenter.y * graph.viewportZoom,
                  zoom: graph.viewportZoom
                }, { duration: 0 });
              });
            }}
            onEdgeClick={(_, edge) => selectRelation(edge.id)}
            onMove={updateViewport}
            onPaneClick={() => emit({ ...graphRef.current, selectedNodeId: null, editingNodeId: null, selectedRelationId: null }, { history: false, message: "No card selected." })}
            deleteKeyCode={null}
            selectionOnDrag={!panMode && !spacePressed}
          >
            <Background color="#dbe4ee" gap={24} size={1} />
          </ReactFlow>

          {selectedRelationId ? (
            <div
              className="crt-relation-action-toolbar"
              data-testid="crt-relation-action-toolbar"
              role="toolbar"
              aria-label="Selected relation actions"
              onClick={(event) => event.stopPropagation()}
            >
              <button
                type="button"
                data-crt-native="true"
                onClick={() => navigateSelectedRelation("cause")}
              >
                Go to Cause
              </button>
              <button
                type="button"
                data-crt-native="true"
                onClick={() => navigateSelectedRelation("effect")}
              >
                Go to Effect
              </button>
              <button
                type="button"
                data-crt-native="true"
                onClick={() => removeRelation(selectedRelationId)}
              >
                Delete relation
              </button>
            </div>
          ) : null}

          <div className="crt-zoom-controls" aria-label="Canvas zoom controls">
            <button type="button" data-crt-native="true" aria-label="Fit all cards" onClick={fitAll}>⌗</button>
            <button type="button" data-crt-native="true" aria-label="Zoom out" onClick={() => { void reactFlow.zoomOut({ duration: 120 }); commitZoom(zoom - 0.1); }}>−</button>
            <span aria-label="Zoom level">{Math.round(zoom * 100)}%</span>
            <button type="button" data-crt-native="true" aria-label="Zoom in" onClick={() => { void reactFlow.zoomIn({ duration: 120 }); commitZoom(zoom + 0.1); }}>＋</button>
          </div>
        </div>
      </div>
      <p className="crt-canvas-announcement" role="status" aria-live="polite" aria-atomic="true">{announcement}</p>
      {pendingDelete ? (
        <CrtCardDeleteConfirmation
          cardLabel={pendingDelete.node.label || "this card"}
          relationConsequences={pendingDelete.relationConsequences}
          onCancel={() => setPendingDelete(null)}
          onConfirm={confirmPendingDelete}
        />
      ) : null}
    </section>
  );
}

export function CrtCanvas(props: CrtCanvasProps): React.JSX.Element {
  return (
    <ReactFlowProvider>
      <CrtCanvasInner {...props} />
    </ReactFlowProvider>
  );
}
