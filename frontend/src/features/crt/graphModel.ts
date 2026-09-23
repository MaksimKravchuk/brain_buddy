export type Point = Readonly<{
  x: number;
  y: number;
}>;

export type GraphNode = Readonly<{
  id: string;
  label: string;
  position: Point;
}>;

export type GraphRelation = Readonly<{
  id: string;
  sourceId: string;
  targetId: string;
}>;

export type GraphState = Readonly<{
  nodes: readonly GraphNode[];
  relations: readonly GraphRelation[];
  selectedNodeId: string | null;
  editingNodeId: string | null;
  selectedRelationId: string | null;
  viewportCenter: Point;
  viewportZoom: number;
  hasPersistedViewport?: boolean;
}>;

export type GraphCommandErrorCode =
  | "missing-selection"
  | "missing-node"
  | "missing-endpoint"
  | "self-link"
  | "duplicate-relation"
  | "cycle"
  | "duplicate-id"
  | "confirmation-required";

export type GraphCommandError = Readonly<{
  code: GraphCommandErrorCode;
  message: string;
}>;

export type GraphCommandFeedback = Readonly<{
  code: "no-qualifying-effect";
  message: string;
}>;

export type GraphCommandResult = Readonly<{
  state: GraphState;
  changed: boolean;
  focusNodeId?: string;
  editingNodeId?: string;
  createdNodeId?: string;
  createdRelationId?: string;
  deletedNodeId?: string;
  deletedRelationId?: string;
  error?: GraphCommandError;
  feedback?: GraphCommandFeedback;
}>;

export type NewNodeIds = Readonly<{
  nodeId: string;
  relationId: string;
}>;

export type HistoryState = Readonly<{
  past: readonly GraphState[];
  present: GraphState;
  future: readonly GraphState[];
}>;

export const CAUSE_VERTICAL_OFFSET = 180;
export const SIBLING_HORIZONTAL_OFFSET = 280;
const CARD_WIDTH = 220;
const CARD_HEIGHT = 92;
const CARD_PLACEMENT_GAP = 24;
const ROUTE_SAMPLE_COUNT = 24;

export type CrtEdgePathInput = Readonly<{
  sourceX: number;
  sourceY: number;
  targetX: number;
  targetY: number;
  routeOffset?: number;
}>;

type CrtEdgeGeometry = Readonly<{
  sourceX: number;
  sourceY: number;
  targetX: number;
  targetY: number;
  controlOneX: number;
  controlY: number;
  controlTwoX: number;
}>;

function crtEdgeGeometry({ sourceX, sourceY, targetX, targetY, routeOffset = 0 }: CrtEdgePathInput): CrtEdgeGeometry {
  const midpointY = (sourceY + targetY) / 2;
  const bend = Math.min(72, Math.max(32, Math.abs(sourceY - targetY) * 0.12));
  const bendDirection = sourceX <= targetX ? 1 : -1;
  return {
    sourceX,
    sourceY,
    targetX,
    targetY,
    controlOneX: sourceX + bend * bendDirection + routeOffset,
    controlY: midpointY,
    controlTwoX: targetX + bend * bendDirection + routeOffset
  };
}

export function buildCrtEdgePath(input: CrtEdgePathInput): string {
  const { sourceX, sourceY, targetX, targetY, controlOneX, controlY, controlTwoX } = crtEdgeGeometry(input);
  return `M${sourceX},${sourceY} C${controlOneX},${controlY} ${controlTwoX},${controlY} ${targetX},${targetY}`;
}

export function createGraphState(input: {
  nodes?: readonly GraphNode[];
  relations?: readonly GraphRelation[];
  selectedNodeId?: string | null;
  editingNodeId?: string | null;
  selectedRelationId?: string | null;
  viewportCenter?: Point;
  viewportZoom?: number;
  hasPersistedViewport?: boolean;
} = {}): GraphState {
  return {
    nodes: input.nodes ? [...input.nodes] : [],
    relations: input.relations ? [...input.relations] : [],
    selectedNodeId: input.selectedNodeId ?? null,
    editingNodeId: input.editingNodeId ?? null,
    selectedRelationId: input.selectedRelationId ?? null,
    viewportCenter: input.viewportCenter ?? { x: 0, y: 0 },
    viewportZoom: input.viewportZoom ?? 1,
    ...(input.hasPersistedViewport ?? (input.viewportCenter !== undefined || input.viewportZoom !== undefined)
      ? { hasPersistedViewport: true }
      : {})
  };
}

function commandState(state: GraphState, nodeId: string): GraphCommandResult {
  return {
    state: {
      ...state,
      selectedNodeId: nodeId,
      editingNodeId: nodeId,
      selectedRelationId: null
    },
    changed: true,
    focusNodeId: nodeId,
    editingNodeId: nodeId
  };
}

type PlacementOptions = Readonly<{
  preferSameRow?: boolean;
  routeTarget?: GraphNode;
}>;

function routeIntersectsNode(candidate: Point, target: GraphNode, obstacle: GraphNode): boolean {
  const sourceX = candidate.x + CARD_WIDTH / 2;
  const sourceY = candidate.y;
  const targetX = target.position.x + CARD_WIDTH / 2;
  const targetY = target.position.y + CARD_HEIGHT;
  const { controlOneX, controlY, controlTwoX } = crtEdgeGeometry({ sourceX, sourceY, targetX, targetY });
  const left = obstacle.position.x - CARD_PLACEMENT_GAP;
  const right = obstacle.position.x + CARD_WIDTH + CARD_PLACEMENT_GAP;
  const top = obstacle.position.y - CARD_PLACEMENT_GAP;
  const bottom = obstacle.position.y + CARD_HEIGHT + CARD_PLACEMENT_GAP;

  for (let index = 0; index <= ROUTE_SAMPLE_COUNT; index += 1) {
    const t = index / ROUTE_SAMPLE_COUNT;
    const inverse = 1 - t;
    const x =
      inverse ** 3 * sourceX +
      3 * inverse ** 2 * t * controlOneX +
      3 * inverse * t ** 2 * controlTwoX +
      t ** 3 * targetX;
    const y =
      inverse ** 3 * sourceY +
      3 * inverse ** 2 * t * controlY +
      3 * inverse * t ** 2 * controlY +
      t ** 3 * targetY;
    if (x >= left && x <= right && y >= top && y <= bottom) return true;
  }
  return false;
}

function findFreePosition(state: GraphState, desired: Point, options: PlacementOptions = {}): Point {
  const occupied = (candidate: Point) => state.nodes.some((node) => {
    const horizontallyOverlaps =
      candidate.x < node.position.x + CARD_WIDTH + CARD_PLACEMENT_GAP &&
      candidate.x + CARD_WIDTH + CARD_PLACEMENT_GAP > node.position.x;
    const verticallyOverlaps =
      candidate.y < node.position.y + CARD_HEIGHT + CARD_PLACEMENT_GAP &&
      candidate.y + CARD_HEIGHT + CARD_PLACEMENT_GAP > node.position.y;
    return horizontallyOverlaps && verticallyOverlaps;
  });
  const routeBlocked = (candidate: Point) => {
    const routeTarget = options.routeTarget;
    if (!routeTarget) return false;
    return state.nodes.some(
      (node) => node.id !== routeTarget.id && routeIntersectsNode(candidate, routeTarget, node)
    );
  };
  const available = (candidate: Point) => !occupied(candidate) && !routeBlocked(candidate);

  if (options.preferSameRow) {
    for (let radius = 0; ; radius += 1) {
      const columns = radius === 0 ? [0] : [radius, -radius];
      for (const column of columns) {
        const candidate = { x: desired.x + column * SIBLING_HORIZONTAL_OFFSET, y: desired.y };
        if (available(candidate)) return candidate;
      }
    }
  }

  for (let radius = 0; ; radius += 1) {
    const offsets = [0, ...Array.from({ length: radius }, (_, index) => index + 1),
      ...Array.from({ length: radius }, (_, index) => -(index + 1))];
    for (const row of offsets) {
      for (const column of offsets) {
        const candidate = {
          x: desired.x + column * SIBLING_HORIZONTAL_OFFSET,
          y: desired.y + row * CAUSE_VERTICAL_OFFSET
        };
        if (available(candidate)) return candidate;
      }
    }
  }
}

function createUnlinkedAtCenter(state: GraphState, ids: NewNodeIds): GraphCommandResult {
  if (state.nodes.some((node) => node.id === ids.nodeId)) {
    return {
      state,
      changed: false,
      error: { code: "duplicate-id", message: "The new card ID is already in use." }
    };
  }
  const node: GraphNode = {
    id: ids.nodeId,
    label: "",
    position: findFreePosition(state, state.viewportCenter)
  };
  return {
    ...commandState({ ...state, nodes: [...state.nodes, node] }, node.id),
    createdNodeId: node.id
  };
}

export function enterCreate(state: GraphState, ids: NewNodeIds): GraphCommandResult {
  if (!state.selectedNodeId) return createUnlinkedAtCenter(state, ids);

  const effect = state.nodes.find((node) => node.id === state.selectedNodeId);
  if (!effect) {
    return {
      state,
      changed: false,
      error: { code: "missing-node", message: "The selected card no longer exists." }
    };
  }
  if (state.nodes.some((node) => node.id === ids.nodeId)) {
    return {
      state,
      changed: false,
      error: { code: "duplicate-id", message: "The new card ID is already in use." }
    };
  }
  if (state.relations.some((relation) => relation.id === ids.relationId)) {
    return {
      state,
      changed: false,
      error: { code: "duplicate-id", message: "The new relation ID is already in use." }
    };
  }

  const cause: GraphNode = {
    id: ids.nodeId,
    label: "",
    position: findFreePosition(state, {
      x: effect.position.x,
      y: effect.position.y + CAUSE_VERTICAL_OFFSET
    })
  };
  const relation: GraphRelation = {
    id: ids.relationId,
    sourceId: cause.id,
    targetId: effect.id
  };
  return {
    ...commandState(
      { ...state, nodes: [...state.nodes, cause], relations: [...state.relations, relation] },
      cause.id
    ),
    createdNodeId: cause.id,
    createdRelationId: relation.id
  };
}

function uniqueNearestUpwardEffect(state: GraphState, selected: GraphNode): GraphNode | undefined {
  const candidates = state.relations
    .filter((relation) => relation.sourceId === selected.id)
    .map((relation) => state.nodes.find((node) => node.id === relation.targetId))
    .filter((node): node is GraphNode => node !== undefined && node.position.y < selected.position.y)
    .map((node) => ({
      node,
      distance: (node.position.x - selected.position.x) ** 2 + (node.position.y - selected.position.y) ** 2
    }));
  if (candidates.length === 0) return undefined;
  const nearestDistance = Math.min(...candidates.map(({ distance }) => distance));
  const nearest = candidates.filter(({ distance }) => distance === nearestDistance);
  return nearest.length === 1 ? nearest[0]?.node : undefined;
}

export function tabCreate(state: GraphState, ids: NewNodeIds): GraphCommandResult {
  if (!state.selectedNodeId) return createUnlinkedAtCenter(state, ids);

  const selected = state.nodes.find((node) => node.id === state.selectedNodeId);
  if (!selected) {
    return {
      state,
      changed: false,
      error: { code: "missing-node", message: "The selected card no longer exists." }
    };
  }
  if (state.nodes.some((node) => node.id === ids.nodeId)) {
    return {
      state,
      changed: false,
      error: { code: "duplicate-id", message: "The new card ID is already in use." }
    };
  }

  const inheritedEffect = uniqueNearestUpwardEffect(state, selected);
  const sibling: GraphNode = {
    id: ids.nodeId,
    label: "",
    position: findFreePosition(state, {
      x: selected.position.x + SIBLING_HORIZONTAL_OFFSET,
      y: selected.position.y
    }, {
      preferSameRow: true,
      routeTarget: inheritedEffect
    })
  };
  const relation = inheritedEffect
    ? { id: ids.relationId, sourceId: sibling.id, targetId: inheritedEffect.id }
    : undefined;
  if (relation && state.relations.some((existing) => existing.id === relation.id)) {
    return {
      state,
      changed: false,
      error: { code: "duplicate-id", message: "The new relation ID is already in use." }
    };
  }

  const nextState: GraphState = {
    ...state,
    nodes: [...state.nodes, sibling],
    relations: relation ? [...state.relations, relation] : [...state.relations]
  };
  return {
    ...commandState(nextState, sibling.id),
    createdNodeId: sibling.id,
    ...(relation ? { createdRelationId: relation.id } : {}),
    ...(!relation
      ? {
          feedback: {
            code: "no-qualifying-effect" as const,
            message: "No unique upward effect was available; the sibling was left unlinked."
          }
        }
      : {})
  };
}

function hasPath(state: GraphState, fromId: string, targetId: string, visited = new Set<string>()): boolean {
  if (fromId === targetId) return true;
  if (visited.has(fromId)) return false;
  visited.add(fromId);
  return state.relations
    .filter((relation) => relation.sourceId === fromId)
    .some((relation) => hasPath(state, relation.targetId, targetId, visited));
}

export function connectRelation(state: GraphState, relation: GraphRelation): GraphCommandResult {
  const sourceExists = state.nodes.some((node) => node.id === relation.sourceId);
  const targetExists = state.nodes.some((node) => node.id === relation.targetId);
  if (!sourceExists || !targetExists) {
    return {
      state,
      changed: false,
      error: { code: "missing-endpoint", message: "Connect two cards that both exist in this tree." }
    };
  }
  if (relation.sourceId === relation.targetId) {
    return {
      state,
      changed: false,
      error: { code: "self-link", message: "A card cannot be connected to itself." }
    };
  }
  if (state.relations.some((existing) => existing.id === relation.id)) {
    return {
      state,
      changed: false,
      error: { code: "duplicate-id", message: "The relation ID is already in use." }
    };
  }
  if (
    state.relations.some(
      (existing) => existing.sourceId === relation.sourceId && existing.targetId === relation.targetId
    )
  ) {
    return {
      state,
      changed: false,
      error: { code: "duplicate-relation", message: "That directed relation already exists." }
    };
  }
  if (hasPath(state, relation.targetId, relation.sourceId)) {
    return {
      state,
      changed: false,
      error: { code: "cycle", message: "That relation would create a causal cycle." }
    };
  }
  return {
    state: {
      ...state,
      relations: [...state.relations, relation],
      selectedNodeId: null,
      editingNodeId: null,
      selectedRelationId: relation.id
    },
    changed: true,
    createdRelationId: relation.id
  };
}

export function deleteRelation(state: GraphState, relationId: string): GraphCommandResult {
  if (!state.relations.some((relation) => relation.id === relationId)) {
    return {
      state,
      changed: false,
      error: { code: "missing-endpoint", message: "The relation to delete no longer exists." }
    };
  }
  return {
    state: {
      ...state,
      relations: state.relations.filter((relation) => relation.id !== relationId),
      selectedRelationId: state.selectedRelationId === relationId ? null : state.selectedRelationId
    },
    changed: true,
    deletedRelationId: relationId
  };
}

export function deleteNode(
  state: GraphState,
  nodeId: string,
  options: { confirmed: boolean }
): GraphCommandResult {
  if (!state.nodes.some((node) => node.id === nodeId)) {
    return {
      state,
      changed: false,
      error: { code: "missing-node", message: "The card to delete no longer exists." }
    };
  }
  const incidentRelationIds = new Set(
    state.relations
      .filter((relation) => relation.sourceId === nodeId || relation.targetId === nodeId)
      .map((relation) => relation.id)
  );
  if (incidentRelationIds.size > 0 && !options.confirmed) {
    return {
      state,
      changed: false,
      error: {
        code: "confirmation-required",
        message: "Confirm cascade deletion before removing a connected card."
      }
    };
  }
  return {
    state: {
      ...state,
      nodes: state.nodes.filter((node) => node.id !== nodeId),
      relations: state.relations.filter((relation) => !incidentRelationIds.has(relation.id)),
      selectedNodeId: state.selectedNodeId === nodeId ? null : state.selectedNodeId,
      editingNodeId: state.editingNodeId === nodeId ? null : state.editingNodeId,
      selectedRelationId:
        state.selectedRelationId && incidentRelationIds.has(state.selectedRelationId)
          ? null
          : state.selectedRelationId
    },
    changed: true,
    deletedNodeId: nodeId
  };
}

export function createHistory(state: GraphState): HistoryState {
  return { past: [], present: state, future: [] };
}

export function commitHistory(history: HistoryState, next: GraphState): HistoryState {
  if (next === history.present) return history;
  return { past: [...history.past, history.present], present: next, future: [] };
}

export function undo(history: HistoryState): HistoryState {
  const previous = history.past[history.past.length - 1];
  if (!previous) return history;
  return {
    past: history.past.slice(0, -1),
    present: previous,
    future: [history.present, ...history.future]
  };
}

export function redo(history: HistoryState): HistoryState {
  const next = history.future[0];
  if (!next) return history;
  return {
    past: [...history.past, history.present],
    present: next,
    future: history.future.slice(1)
  };
}
