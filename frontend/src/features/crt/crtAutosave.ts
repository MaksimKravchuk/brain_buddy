import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { ApiError } from "../../api/client";
import { crtApi, type CrtTreeResponse, type CrtTreeUpdatePayload } from "../../api/crt";
import { nowMs, recordTelemetry } from "../../utils/telemetry";
import type { DraftFailureReason, DraftQueuedCommand } from "./draftStore";
import { createGraphState, type GraphState } from "./graphModel";

export const CRT_AUTOSAVE_DEBOUNCE_MS = 300;
export const CRT_MAX_QUEUED_COMMANDS = 100;
const DEFAULT_VIEWPORT_ZOOM = 1;
const MIN_VIEWPORT_ZOOM = 0.25;
const MAX_VIEWPORT_ZOOM = 1;
export type CrtSaveStatus = "Saved" | "Unsaved" | "Saving" | "Save failed" | "Conflict";

type SaveUpdate = typeof crtApi.updateCrtTree;
type StatusListener = (status: CrtSaveStatus, reference?: string) => void;
type CanonicalListener = (tree: CrtTreeResponse) => void | Promise<void>;

export type CrtPersistenceRequest = Readonly<{
  tree: CrtTreeResponse;
  graph: GraphState;
  payload: Readonly<CrtTreeUpdatePayload>;
  idempotencyKey: string;
  baseRevision: number;
  generation: number;
  retry: boolean;
}>;

export type CrtPersistenceResult = Readonly<{
  ok: true;
  generation: number;
  mode: "durable" | "online-only";
  online_only_risk: boolean;
}> | Readonly<{
  ok: false;
  reason: string;
  mode: "durable" | "online-only";
  online_only_risk: boolean;
}>;

export type CrtAutosavePersistence = Readonly<{
  persistBeforeSave: (request: CrtPersistenceRequest) => Promise<CrtPersistenceResult>;
  persistQueuedEdit?: (request: Readonly<{
    active: CrtPersistenceRequest;
    visibleGraph: GraphState;
    queuedCommands: readonly DraftQueuedCommand[];
  }>) => Promise<CrtPersistenceResult>;
  persistRetry?: (request: CrtPersistenceRequest) => Promise<CrtPersistenceResult>;
  clearAfterCanonicalApplied: (response: CrtTreeResponse, applied: true, expectedGeneration: number) => Promise<unknown>;
  onModeChange?: (mode: "durable" | "online-only", onlineOnlyRisk: boolean) => void;
}>;

type FrozenCommand = Readonly<{
  treeId: string;
  fingerprint: string;
  payload: Readonly<CrtTreeUpdatePayload>;
  idempotencyKey: string;
  signal: AbortSignal;
  graph: GraphState;
  generation: number;
}>;

type QueuedGraph = Readonly<{
  graph: GraphState;
  fingerprint: string;
  commands: readonly DraftQueuedCommand[];
}>;

export type CrtConflict = Readonly<{
  reason: "stale_revision" | "idempotency_conflict";
  reference?: string;
}>;

let randomIdempotencySequence = 0;
let queuedCommandSequence = 0;

function randomIdempotencyKey(): string {
  try {
    const cryptoApi = (globalThis as { crypto?: { randomUUID?: () => string } }).crypto;
    if (cryptoApi?.randomUUID) return cryptoApi.randomUUID();
  } catch { /* use the deterministic page-local fallback below */ }
  randomIdempotencySequence += 1;
  return `00000000-0000-4000-8000-${String(randomIdempotencySequence).padStart(12, "0")}`;
}

function randomCommandId(): string {
  try {
    const cryptoApi = (globalThis as { crypto?: { randomUUID?: () => string } }).crypto;
    if (cryptoApi?.randomUUID) return cryptoApi.randomUUID();
  } catch { /* use the deterministic page-local fallback below */ }
  queuedCommandSequence += 1;
  return `00000000-0000-4000-8000-${String(queuedCommandSequence).padStart(12, "0")}`;
}

/** Build bounded, stable-ID domain commands for replay on a newer graph base. */
export function deriveReplayableCommands(base: GraphState, next: GraphState, zoom?: number): readonly DraftQueuedCommand[] {
  const commands: DraftQueuedCommand[] = [];
  const baseNodes = new Map(base.nodes.map((node) => [node.id, node]));
  const nextNodes = new Map(next.nodes.map((node) => [node.id, node]));
  baseNodes.forEach((node) => {
    if (!nextNodes.has(node.id)) commands.push({ id: randomCommandId(), kind: "card-delete", payload: { node_id: node.id, confirmed: true } });
  });
  nextNodes.forEach((node) => {
    const previous = baseNodes.get(node.id);
    if (!previous) commands.push({ id: randomCommandId(), kind: "card-create", payload: { node_id: node.id, label: node.label, position: { ...node.position } } });
    else {
      if (previous.label !== node.label) commands.push({ id: randomCommandId(), kind: "label-edit", payload: { node_id: node.id, label: node.label } });
      if (previous.position.x !== node.position.x || previous.position.y !== node.position.y) {
        commands.push({ id: randomCommandId(), kind: "card-move", payload: { node_id: node.id, position: { ...node.position } } });
      }
    }
  });
  const baseRelations = new Map(base.relations.map((relation) => [relation.id, relation]));
  const nextRelations = new Map(next.relations.map((relation) => [relation.id, relation]));
  baseRelations.forEach((relation) => {
    if (!nextRelations.has(relation.id)) commands.push({ id: randomCommandId(), kind: "relation-delete", payload: { relation_id: relation.id } });
  });
  nextRelations.forEach((relation) => {
    if (!baseRelations.has(relation.id)) commands.push({ id: randomCommandId(), kind: "relation-create", payload: {
      relation_id: relation.id, source_node_id: relation.sourceId, target_node_id: relation.targetId
    } });
  });
  const nextZoom = zoom ?? next.viewportZoom;
  if (base.viewportCenter.x !== next.viewportCenter.x || base.viewportCenter.y !== next.viewportCenter.y || base.viewportZoom !== next.viewportZoom) {
    commands.push({ id: randomCommandId(), kind: "layout-change", payload: { layout: { center: { ...next.viewportCenter }, zoom: nextZoom } } });
  }
  return commands;
}

export function applyReplayableCommands(base: GraphState, commands: readonly DraftQueuedCommand[]): GraphState {
  const nodes = new Map(base.nodes.map((node) => [node.id, { ...node, position: { ...node.position } }]));
  const relations = new Map(base.relations.map((relation) => [relation.id, { ...relation }]));
  let viewportCenter = { ...base.viewportCenter };
  let viewportZoom = base.viewportZoom;
  commands.forEach((command) => {
    switch (command.kind) {
      case "card-create": nodes.set(command.payload.node_id, { id: command.payload.node_id, label: command.payload.label, position: { ...command.payload.position } }); break;
      case "label-edit": {
        const node = nodes.get(command.payload.node_id);
        if (node) nodes.set(node.id, { ...node, label: command.payload.label });
        break;
      }
      case "card-move": {
        const node = nodes.get(command.payload.node_id);
        if (node) nodes.set(node.id, { ...node, position: { ...command.payload.position } });
        break;
      }
      case "card-delete": nodes.delete(command.payload.node_id); break;
      case "relation-create": relations.set(command.payload.relation_id, { id: command.payload.relation_id, sourceId: command.payload.source_node_id, targetId: command.payload.target_node_id }); break;
      case "relation-delete": relations.delete(command.payload.relation_id); break;
      case "layout-change":
        viewportCenter = { ...command.payload.layout.center };
        viewportZoom = command.payload.layout.zoom;
        break;
      case "tree-rename": break;
    }
  });
  const validRelations = [...relations.values()].filter((relation) => nodes.has(relation.sourceId) && nodes.has(relation.targetId));
  return createGraphState({ nodes: [...nodes.values()], relations: validRelations, viewportCenter, viewportZoom });
}

function relationCounts(graph: GraphState, nodeId: string): { up_count: number; down_count: number } {
  return {
    up_count: graph.relations.filter((relation) => relation.sourceId === nodeId).length,
    down_count: graph.relations.filter((relation) => relation.targetId === nodeId).length
  };
}

/** Convert the presentation graph back to the complete CRT snapshot contract. */
export function graphToCrtUpdatePayload(
  tree: CrtTreeResponse,
  graph: GraphState,
  expectedRevision = tree.revision,
  relationCreatedAt = new Map<string, string>()
): CrtTreeUpdatePayload {
  const existingNodes = new Map(tree.nodes.map((node) => [node.id, node]));
  const existingRelations = new Map(tree.relations.map((relation) => [relation.id, relation]));
  const layout = tree.metadata.layout ? { ...tree.metadata.layout } : {};

  return {
    expected_revision: expectedRevision,
    schema_version: tree.schema_version,
    name: tree.name,
    metadata: {
      ...tree.metadata,
      version: tree.schema_version,
      layout: { ...layout, center: { ...graph.viewportCenter }, zoom: graph.viewportZoom }
    },
    nodes: graph.nodes.map((node) => {
      const existing = existingNodes.get(node.id);
      return {
        id: node.id,
        label: node.label,
        type: existing?.type ?? "child",
        position: { ...node.position },
        highlight_state: existing?.highlight_state ?? "none",
        relation_counts: relationCounts(graph, node.id)
      };
    }),
    relations: graph.relations.map((relation) => {
      const existing = existingRelations.get(relation.id);
      const createdAt = existing?.created_at ?? relationCreatedAt.get(relation.id) ?? new Date().toISOString();
      if (!existing) relationCreatedAt.set(relation.id, createdAt);
      return {
        id: relation.id,
        source_node_id: relation.sourceId,
        target_node_id: relation.targetId,
        kind: existing?.kind ?? "why",
        created_at: createdAt
      };
    }),
    owner_id: tree.owner_id
  };
}

function snapshotFingerprint(payload: CrtTreeUpdatePayload): string {
  return JSON.stringify(payload, (key, value: unknown) =>
    key === "expected_revision" || key === "updated_at" ? undefined : value
  );
}

function freezeDeep<T>(value: T): T {
  if (typeof value !== "object" || value === null || Object.isFrozen(value)) return value;
  Reflect.ownKeys(value).forEach((key) => {
    const child = (value as Record<PropertyKey, unknown>)[key];
    freezeDeep(child);
  });
  return Object.freeze(value);
}

function cloneGraph(graph: GraphState): GraphState {
  return freezeDeep({
    nodes: graph.nodes.map((node) => ({ ...node, position: { ...node.position } })),
    relations: graph.relations.map((relation) => ({ ...relation })),
    selectedNodeId: graph.selectedNodeId,
    editingNodeId: graph.editingNodeId,
    selectedRelationId: graph.selectedRelationId,
    viewportCenter: { ...graph.viewportCenter },
    viewportZoom: graph.viewportZoom
  });
}

function hasIncompleteCard(graph: GraphState): boolean {
  return graph.nodes.some((node) => node.label.trim().length === 0);
}

function centerFromTree(tree: CrtTreeResponse): { x: number; y: number } {
  const center = tree.metadata.layout?.center;
  if (
    typeof center === "object" && center !== null &&
    typeof (center as { x?: unknown }).x === "number" &&
    typeof (center as { y?: unknown }).y === "number"
  ) {
    return { x: (center as { x: number }).x, y: (center as { y: number }).y };
  }
  return { x: 0, y: 0 };
}

function zoomFromTree(tree: CrtTreeResponse): number {
  const zoom = tree.metadata.layout?.zoom;
  if (typeof zoom !== "number" || !Number.isFinite(zoom)) return DEFAULT_VIEWPORT_ZOOM;
  return Math.min(MAX_VIEWPORT_ZOOM, Math.max(MIN_VIEWPORT_ZOOM, zoom));
}

export function treeToGraph(tree: CrtTreeResponse, current?: GraphState): GraphState {
  const nodes = tree.nodes.map((node) => ({ id: node.id, label: node.label, position: { ...node.position } }));
  const relations = tree.relations.map((relation) => ({
    id: relation.id,
    sourceId: relation.source_node_id,
    targetId: relation.target_node_id
  }));
  const nodeIds = new Set(nodes.map((node) => node.id));
  const relationIds = new Set(relations.map((relation) => relation.id));
  return {
    nodes,
    relations,
    selectedNodeId: current
      ? current.selectedNodeId && nodeIds.has(current.selectedNodeId) ? current.selectedNodeId : null
      : nodes[nodes.length - 1]?.id ?? null,
    editingNodeId: current?.editingNodeId && nodeIds.has(current.editingNodeId) ? current.editingNodeId : null,
    selectedRelationId: current?.selectedRelationId && relationIds.has(current.selectedRelationId)
      ? current.selectedRelationId
      : null,
    viewportCenter: centerFromTree(tree),
    viewportZoom: zoomFromTree(tree),
    hasPersistedViewport: tree.metadata.layout !== undefined
  };
}

function treeFingerprint(tree: CrtTreeResponse): string {
  return snapshotFingerprint(graphToCrtUpdatePayload(tree, treeToGraph(tree), tree.revision));
}

function conflictReason(error: unknown): CrtConflict["reason"] | undefined {
  if (!(error instanceof ApiError) || error.status !== 409) return undefined;
  const payload = error.payload;
  const detail = typeof payload === "object" && payload !== null && "detail" in payload
    ? payload.detail
    : payload;
  const reason = typeof detail === "object" && detail !== null && "reason" in detail ? detail.reason : undefined;
  return reason === "stale_revision" || reason === "idempotency_conflict" ? reason : undefined;
}

type CrtSaveOutcome = "success" | "conflict" | "failure";
type CrtSaveReplay = "initial" | "retry";
type CrtPersistenceFailureReason = DraftFailureReason | "lock-unavailable" | "scope-mismatch" | "persistence-failed";
const CRT_PERSISTENCE_FAILURE_REASONS = new Set<CrtPersistenceFailureReason>([
  "storage-unavailable",
  "invalid-draft",
  "invalid-schema",
  "invalid-json",
  "stale-generation",
  "not-found",
  "rekey-conflict",
  "cleanup-failed",
  "writer-denied",
  "lock-unavailable",
  "scope-mismatch",
  "persistence-failed"
]);

function safePersistenceFailureReason(reason: string): CrtPersistenceFailureReason {
  return CRT_PERSISTENCE_FAILURE_REASONS.has(reason as CrtPersistenceFailureReason)
    ? reason as CrtPersistenceFailureReason
    : "persistence-failed";
}

function recordCrtSaveTelemetry(
  outcome: CrtSaveOutcome,
  startedAt: number,
  replay: CrtSaveReplay,
  revision?: number,
  correlationId?: string,
  storage?: "durable" | "online-only",
  failureReason?: CrtPersistenceFailureReason
): void {
  const details: Record<string, unknown> = { outcome, replay };
  if (typeof revision === "number") details.revision = revision;
  if (typeof correlationId === "string") details.correlationId = correlationId;
  if (storage !== undefined) details.storage = storage;
  if (failureReason !== undefined) details.failureReason = failureReason;
  const event = { name: "crt.save", durationMs: nowMs() - startedAt, details };
  if (outcome === "success") recordTelemetry(event);
  else recordTelemetry(event, "warn");
}

export type CrtAutosaveController = {
  readonly status: CrtSaveStatus;
  readonly reference: string | undefined;
  readonly conflict: CrtConflict | undefined;
  schedule: (graph: GraphState) => Promise<void>;
  retry: () => void;
  rebase: () => void;
  syncCanonical: (tree: CrtTreeResponse) => void | Promise<void>;
  setOnCanonical: (listener?: CanonicalListener) => void;
  subscribe: (listener: StatusListener) => () => void;
  dispose: () => void;
};

export function createCrtAutosaveController(
  initialTree: CrtTreeResponse,
  update: SaveUpdate = crtApi.updateCrtTree,
  onCanonical?: CanonicalListener,
  persistence?: CrtAutosavePersistence
): CrtAutosaveController {
  let canonical = initialTree;
  let status: CrtSaveStatus = "Saved";
  let reference: string | undefined;
  let conflict: CrtConflict | undefined;
  let disposed = false;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let active: FrozenCommand | undefined;
  let pending: FrozenCommand | undefined;
  let queued: QueuedGraph | undefined;
  let queuedPersistenceFailure = false;
  let queuedPersistenceGeneration: number | undefined;
  let queuedCommandOverflow = false;
  let localGraph: GraphState | undefined;
  let commandGeneration = 0;
  const listeners = new Set<StatusListener>();
  const relationCreatedAt = new Map<string, string>();
  let canonicalListener = onCanonical;

  const notify = () => {
    if (disposed) return;
    listeners.forEach((listener) => listener(status, reference));
  };
  const setStatus = (next: CrtSaveStatus, nextReference?: string) => {
    status = next;
    reference = nextReference;
    notify();
  };
  const clearTimer = () => {
    if (timer !== undefined) {
      globalThis.clearTimeout(timer);
      timer = undefined;
    }
  };
  const commandForGraph = (graph: GraphState): FrozenCommand => {
    const frozenGraph = cloneGraph(graph);
    const payload = freezeDeep(graphToCrtUpdatePayload(canonical, frozenGraph, canonical.revision, relationCreatedAt));
    return freezeDeep({
      treeId: canonical.id,
      fingerprint: snapshotFingerprint(payload),
      payload,
      idempotencyKey: randomIdempotencyKey(),
      signal: new AbortController().signal,
      graph: frozenGraph,
      generation: ++commandGeneration
    });
  };
  const retainPendingCommand = async (command: FrozenCommand): Promise<boolean> => {
    if (!persistence) return true;
    let persisted: CrtPersistenceResult;
    try {
      persisted = await persistence.persistBeforeSave({
        tree: canonical,
        graph: command.graph,
        payload: command.payload,
        idempotencyKey: command.idempotencyKey,
        baseRevision: command.payload.expected_revision,
        generation: command.generation,
        retry: false
      });
    } catch {
      return false;
    }
    persistence.onModeChange?.(persisted.mode, persisted.online_only_risk);
    return persisted.ok || persisted.mode === "online-only";
  };
  const samePersistedContent = (graph: GraphState, tree = canonical): boolean => {
    const candidate = graphToCrtUpdatePayload(tree, graph, tree.revision, relationCreatedAt);
    return snapshotFingerprint(candidate) === treeFingerprint(tree);
  };
  const setQueuedGraph = (graph: GraphState, baseGraph: GraphState): boolean => {
    const commands = deriveReplayableCommands(baseGraph, graph);
    if (commands.length > CRT_MAX_QUEUED_COMMANDS) {
      queued = undefined;
      queuedCommandOverflow = true;
      return false;
    }
    const snapshot = cloneGraph(graph);
    const fingerprint = snapshotFingerprint(graphToCrtUpdatePayload(canonical, snapshot, canonical.revision, relationCreatedAt));
    queued = { graph: snapshot, fingerprint, commands };
    queuedCommandOverflow = false;
    queuedPersistenceFailure = false;
    return true;
  };
  const dispatch = (command: FrozenCommand, retrying = false) => {
    if (disposed) return;
    const startedAt = nowMs();
    let storageMode: "durable" | "online-only" | undefined;
    active = command;
    pending = undefined;
    setStatus("Saving");
    void (async () => {
      let persisted: CrtPersistenceResult | undefined;
      if (persistence) {
        const request: CrtPersistenceRequest = {
          tree: canonical,
          graph: command.graph,
          payload: command.payload,
          idempotencyKey: command.idempotencyKey,
          baseRevision: command.payload.expected_revision,
          generation: command.generation,
          retry: retrying
        };
        try {
          persisted = retrying && persistence.persistRetry
            ? await persistence.persistRetry(request)
            : await persistence.persistBeforeSave(request);
        } catch {
          persisted = { ok: false, reason: "persistence-failed", mode: "durable", online_only_risk: false };
        }
        persistence.onModeChange?.(persisted.mode, persisted.online_only_risk);
        storageMode = persisted.mode;
        if (!persisted.ok && persisted.mode !== "online-only") {
          if (disposed || active !== command) return;
          active = undefined;
          recordCrtSaveTelemetry(
            "failure",
            startedAt,
            retrying ? "retry" : "initial",
            undefined,
            undefined,
            persisted.mode,
            safePersistenceFailureReason(persisted.reason)
          );
          pending = command;
          setStatus("Save failed");
          return;
        }
      }
      if (disposed || active !== command) return;
      const response = await update(command.treeId, command.payload, {
        idempotencyKey: command.idempotencyKey,
        signal: command.signal
      });
      if (disposed || active !== command) return;
      active = undefined;
      recordCrtSaveTelemetry(
        "success",
        startedAt,
        retrying ? "retry" : "initial",
        response.revision,
        undefined,
        persisted?.mode
      );
      if (response.id === canonical.id && response.revision > canonical.revision) {
        canonical = response;
      }
      await queuePersistence;
      if (disposed) return;
      const nextGraph = queued?.graph ?? localGraph;
      const nextQueued = queued;
      const queuedDurableGeneration = queuedPersistenceGeneration;
      const generationForClear = (successfulPersistence: Extract<CrtPersistenceResult, { ok: true }>): number =>
        queuedDurableGeneration ?? successfulPersistence.generation;
      queued = undefined;
      queuedPersistenceGeneration = undefined;
      if (nextQueued && hasIncompleteCard(nextQueued.graph)) {
        pending = undefined;
        setStatus("Unsaved");
        return;
      }
      // The visible canonical response is installed before any durable clear or replay.
      await canonicalListener?.(canonical);
      if (queuedCommandOverflow) {
        queuedCommandOverflow = false;
        if (nextGraph && !samePersistedContent(nextGraph)) {
          pending = commandForGraph(nextGraph);
          setStatus("Save failed");
          await retainPendingCommand(pending);
        } else {
          pending = undefined;
          if (persistence && persisted?.ok) {
            const cleared = await persistence.clearAfterCanonicalApplied(
              canonical,
              true,
              generationForClear(persisted)
            );
            if (cleared && typeof cleared === "object" && "ok" in cleared && cleared.ok === false) {
              pending = command;
              setStatus("Save failed");
              return;
            }
          }
          setStatus("Saved");
        }
        return;
      }
      if (nextQueued) {
        const nextCommand = commandForGraph(nextQueued.graph);
        if (queuedPersistenceFailure) {
          pending = nextCommand;
          setStatus("Save failed");
          return;
        }
        if (samePersistedContent(nextQueued.graph)) {
          pending = undefined;
          if (persistence && persisted?.ok) {
            const cleared = await persistence.clearAfterCanonicalApplied(
              canonical,
              true,
              generationForClear(persisted)
            );
            if (cleared && typeof cleared === "object" && "ok" in cleared && cleared.ok === false) {
              pending = command;
              setStatus("Save failed");
              return;
            }
          }
          setStatus("Saved");
        } else {

          pending = nextCommand;
          dispatch(nextCommand);
        }
        return;
      }
      if (nextGraph && !samePersistedContent(nextGraph)) {
        const nextCommand = commandForGraph(nextGraph);
        pending = nextCommand;
        setStatus("Unsaved");
        timer = globalThis.setTimeout(() => {
          timer = undefined;
          if (pending) dispatch(pending);
        }, CRT_AUTOSAVE_DEBOUNCE_MS);
        return;
      }
      pending = undefined;
      if (persistence && persisted?.ok) {
        const cleared = await persistence.clearAfterCanonicalApplied(
          canonical,
          true,
          generationForClear(persisted)
        );
        if (cleared && typeof cleared === "object" && "ok" in cleared && cleared.ok === false) {
          pending = command;
          setStatus("Save failed");
          return;
        }
      }
      setStatus("Saved");
    })().catch((error: unknown) => {
      if (disposed || active !== command) return;
      active = undefined;
      const reason = conflictReason(error);
      if (reason) {
        recordCrtSaveTelemetry(
          "conflict",
          startedAt,
          retrying ? "retry" : "initial",
          undefined,
          error instanceof ApiError ? error.correlationId : undefined,
          storageMode
        );
        conflict = { reason, reference: error instanceof ApiError ? error.correlationId : undefined };
        pending = command;
        setStatus("Conflict", conflict.reference);
        return;
      }
      recordCrtSaveTelemetry(
        "failure",
        startedAt,
        retrying ? "retry" : "initial",
        undefined,
        error instanceof ApiError ? error.correlationId : undefined,
        storageMode
      );
      pending = command;
      setStatus("Save failed", error instanceof ApiError ? error.correlationId : undefined);
    });
  };
  const dispatchPending = (retrying = false) => {
    if (disposed || active || !pending) return;
    const command = pending;
    dispatch(command, retrying);
  };
  let queuePersistence = Promise.resolve();
  const schedule = async (graph: GraphState): Promise<void> => {
    if (disposed) return;
    localGraph = cloneGraph(graph);
    const candidate = graphToCrtUpdatePayload(canonical, localGraph, canonical.revision, relationCreatedAt);
    const fingerprint = snapshotFingerprint(candidate);
    if (active) {
      const activeCommand = active;
      queuedCommandOverflow = false;
      if (fingerprint === activeCommand.fingerprint) {
        queued = undefined;
      } else if (!queued || queued.fingerprint !== fingerprint) {
        const bounded = setQueuedGraph(localGraph, activeCommand.graph);
        if (!bounded) {
          queuedPersistenceFailure = true;
          setStatus("Save failed");
          return;
        }
      }

      conflict = undefined;
      setStatus("Saving");
      if (hasIncompleteCard(localGraph)) return;
      if (persistence?.persistQueuedEdit) {
        const queuedSnapshot = queued;
        const request: CrtPersistenceRequest = {
          tree: canonical,
          graph: activeCommand.graph,
          payload: activeCommand.payload,
          idempotencyKey: activeCommand.idempotencyKey,
          baseRevision: activeCommand.payload.expected_revision,
          generation: activeCommand.generation,
          retry: false
        };
        queuePersistence = queuePersistence.then(async () => {
          let persisted: CrtPersistenceResult;
          try {
            persisted = await persistence.persistQueuedEdit?.({
              active: request,
              visibleGraph: localGraph as GraphState,
              queuedCommands: queuedSnapshot?.commands ?? []
            }) ?? { ok: true, generation: activeCommand.generation, mode: "online-only", online_only_risk: true };
          } catch {
            persisted = { ok: false, reason: "persistence-failed", mode: "durable", online_only_risk: false };
          }
          persistence.onModeChange?.(persisted.mode, persisted.online_only_risk);
          queuedPersistenceFailure = !persisted.ok && persisted.mode !== "online-only";
          queuedPersistenceGeneration = persisted.ok ? persisted.generation : undefined;
          if (!persisted.ok && persisted.mode !== "online-only" && active === activeCommand) setStatus("Save failed");
        });
        await queuePersistence;
      }
      return;
    }
    if (conflict) {
      setStatus("Conflict", conflict.reference);
      return;
    }
    if (hasIncompleteCard(localGraph)) {
      pending = undefined;
      clearTimer();
      setStatus("Unsaved");
      return;
    }
    // A graph scheduled after an active save has failed supersedes any older
    // queued snapshot. Keeping it would let the completed save replay stale
    // local content after this newer edit.
    queued = undefined;
    queuedPersistenceFailure = false;
    queuedPersistenceGeneration = undefined;
    if (status === "Save failed" && pending?.fingerprint === fingerprint) {
      clearTimer();
      setStatus("Save failed", reference);
      return;
    }
    if (fingerprint === treeFingerprint(canonical)) {
      pending = undefined;
      queued = undefined;
      clearTimer();
      setStatus("Saved");
      return;
    }
    if (!pending || pending.fingerprint !== fingerprint) pending = commandForGraph(localGraph);
    clearTimer();
    setStatus("Unsaved");
    timer = globalThis.setTimeout(() => {
      timer = undefined;
      dispatchPending();
    }, CRT_AUTOSAVE_DEBOUNCE_MS);
  };
  const retry = () => {
    if (disposed || status !== "Save failed" || !pending || active) return;
    clearTimer();
    dispatchPending(true);
  };
  const rebase = () => {
    if (disposed || status !== "Conflict" || !localGraph) return;
    conflict = undefined;
    pending = samePersistedContent(localGraph) ? undefined : commandForGraph(localGraph);
    clearTimer();
    if (!pending) {
      setStatus("Saved");
      canonicalListener?.(canonical);
      return;
    }
    setStatus("Unsaved");
    timer = globalThis.setTimeout(() => {
      timer = undefined;
      dispatchPending();
    }, CRT_AUTOSAVE_DEBOUNCE_MS);
  };

  const controller: CrtAutosaveController = {
    get status() { return status; },
    get reference() { return reference; },
    get conflict() { return conflict; },
    schedule,
    retry,
    rebase,
    syncCanonical(tree: CrtTreeResponse) {
      if (tree.id !== canonical.id) return;
      if (tree.revision < canonical.revision) return;
      if (tree.revision === canonical.revision) return;
      canonical = tree;
      if (!active && !pending && !queued && !conflict) return canonicalListener?.(canonical);
    },
    setOnCanonical(listener?: CanonicalListener) {
      canonicalListener = listener;
    },
    subscribe(listener: StatusListener) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    dispose() {
      if (disposed) return;
      disposed = true;
      clearTimer();
      // A dispatched command is intentionally not aborted: the server may have committed it.
      listeners.clear();
      canonicalListener = undefined;
    }
  };
  return controller;
}

export function useCrtAutosave(
  tree: CrtTreeResponse | null,
  onCanonical: (tree: CrtTreeResponse) => void,
  persistence?: CrtAutosavePersistence
): {
  status: CrtSaveStatus;
  reference: string | undefined;
  conflict: CrtConflict | undefined;
  schedule: (graph: GraphState) => Promise<void>;
  retry: () => void;
  rebase: () => void;
  syncCanonical: (tree: CrtTreeResponse) => void | Promise<void>;
} {
  const [status, setStatus] = useState<CrtSaveStatus>("Saved");
  const [reference, setReference] = useState<string | undefined>();
  const [conflict, setConflict] = useState<CrtConflict | undefined>();
  const callbackRef = useRef(onCanonical);
  callbackRef.current = onCanonical;
  const treeId = tree?.id;
  const initialTreeRef = useRef(tree);
  if (!tree) initialTreeRef.current = null;
  else if (initialTreeRef.current?.id !== tree.id) initialTreeRef.current = tree;
  const controller = useMemo(() => {
    if (treeId === undefined || !initialTreeRef.current) return null;
    return createCrtAutosaveController(
      initialTreeRef.current,
      crtApi.updateCrtTree,
      (canonicalTree) => callbackRef.current(canonicalTree),
      persistence
    );
  }, [treeId, persistence]);

  useEffect(() => {
    if (!controller || !tree) return undefined;
    controller.syncCanonical(tree);
    const unsubscribe = controller.subscribe((nextStatus, nextReference) => {
      setStatus(nextStatus);
      setReference(nextReference);
      setConflict(controller.conflict);
    });
    setStatus(controller.status);
    setReference(controller.reference);
    setConflict(controller.conflict);
    return () => unsubscribe();
  }, [controller, tree]);

  useEffect(() => () => controller?.dispose(), [controller]);

  const schedule = useCallback((graph: GraphState): Promise<void> => controller ? controller.schedule(graph) : Promise.resolve(), [controller]);
  const retry = useCallback(() => controller?.retry(), [controller]);
  const rebase = useCallback(() => controller?.rebase(), [controller]);
  const syncCanonical = useCallback((nextTree: CrtTreeResponse) => controller?.syncCanonical(nextTree), [controller]);
  return { status, reference, conflict, schedule, retry, rebase, syncCanonical };
}
