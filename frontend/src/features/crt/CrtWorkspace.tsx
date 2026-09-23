import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";

import { ApiError } from "../../api/client";
import { crtApi, type CrtTreeListItem, type CrtTreeResponse } from "../../api/crt";
import { useAuthStore } from "../../stores/authStore";
import { recordTelemetry } from "../../utils/telemetry";
import { CrtCanvas } from "./CrtCanvas";
import { CrtDeleteTreeDialog, CrtPendingWorkDialog } from "./CrtDeleteConfirmation";
import { CrtRecoveryDialog, CrtStorageUnavailableAlert } from "./CrtRecoveryDialog";
import {
  createCrtDraftCoordinator,
  createCrtLossBarrier,
  pendingDraftToGraphState,
  type CrtDraftCoordinator,
  type CrtDraftCoordinatorOptions,
  type DraftInitialization
} from "./crtDraftCoordinator";
import { type GraphState } from "./graphModel";
import { CrtTreeMenu } from "./CrtTreeMenu";
import {
  clearCrtLastTreePreference,
  readCrtLastTreePreference,
  rememberCrtLastTreePreference
} from "./crtLastTreePreference";
import {
  treeToGraph as graphFromTree,
  graphToCrtUpdatePayload,
  applyReplayableCommands,
  useCrtAutosave,
  type CrtAutosavePersistence
} from "./crtAutosave";
import type { PendingDraftEnvelope } from "./draftStore";

type RecoveryState = Readonly<{
  kind: "fresh-draft" | "stale-draft" | "conflict" | "invalid";
  draft?: PendingDraftEnvelope;
  reason?: string;
}>;

type DeferredRecoveryState = Readonly<{
  kind: "fresh-draft" | "stale-draft" | "conflict";
  draft: PendingDraftEnvelope;
}>;

type PendingTransition =
  | Readonly<{ kind: "switch"; treeId: string }>
  | Readonly<{ kind: "delete"; tree: CrtTreeResponse }>
  | Readonly<{ kind: "import"; file: File }>;

type PendingWorkItem = Readonly<{ id: string; name: string; editCount: number }>;

type ManagementMutation = Readonly<{ fingerprint: string; key: string }>;

export type CrtDraftBackupDownload = (backup: {
  content: string;
  filename: string;
  mime_type: "application/json";
}) => void;

export type CrtWorkspaceProps = Readonly<{
  createDraftCoordinator?: (options: CrtDraftCoordinatorOptions) => CrtDraftCoordinator;
  downloadBackup?: CrtDraftBackupDownload;
}>;

let workspaceIdSequence = 0;

function safeUuid(): string {
  try {
    const cryptoApi = (globalThis as { crypto?: { randomUUID?: () => string } }).crypto;
    if (cryptoApi?.randomUUID) return cryptoApi.randomUUID();
  } catch { /* fall through to the page-local UUID fallback */ }
  workspaceIdSequence += 1;
  return `00000000-0000-4000-8000-${String(workspaceIdSequence).padStart(12, "0")}`;
}

function referenceId(error: unknown): string | undefined {
  return error instanceof ApiError ? error.correlationId : undefined;
}

function importValidationReason(error: unknown): string {
  if (error instanceof ApiError) {
    const payload = error.payload;
    const detail = typeof payload === "object" && payload !== null && "detail" in payload
      ? (payload as { detail?: unknown }).detail
      : payload;
    if (typeof detail === "string" && detail.trim()) return detail;
    if (typeof detail === "object" && detail !== null) {
      const value = detail as { reason?: unknown; message?: unknown };
      if (typeof value.reason === "string" && value.reason.trim()) return value.reason;
      if (typeof value.message === "string" && value.message.trim()) return value.message;
    }
    return error.message || "The server rejected the tree import.";
  }
  if (error instanceof Error && error.message.trim()) return error.message;
  return "The selected file could not be validated.";
}

function importFailureMessage(error: unknown): string {
  const reference = referenceId(error) ?? `import-${safeUuid()}`;
  return `We couldn't import this tree. Validation reason: ${importValidationReason(error)}. Support reference: ${reference}`;
}

function newestTreeId(trees: Array<{ id: string; updated_at: string }>): string | undefined {
  return [...trees]
    .sort((left, right) => Date.parse(right.updated_at) - Date.parse(left.updated_at))[0]?.id;
}

function defaultDownloadBackup(backup: Parameters<CrtDraftBackupDownload>[0]): void {
  const blob = new Blob([backup.content], { type: backup.mime_type });
  const objectUrl = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = objectUrl;
  link.download = backup.filename;
  link.click();
  URL.revokeObjectURL(objectUrl);
}

function recoverySummary(draft: PendingDraftEnvelope): string[] {
  if (draft.dirty_operations.length > 0) {
    return draft.dirty_operations.map((operation) => `${operation.kind}${operation.entity_id ? ` (${operation.entity_id})` : ""}`);
  }
  return ["Local graph changes"];
}

function pendingEditCount(draft: PendingDraftEnvelope): number {
  return Math.max(
    1,
    draft.dirty_operations.length,
    draft.queued_commands.length,
    draft.in_flight_save ? 1 : 0
  );
}

function preCanonicalTree(ownerId: string, createKey: string): CrtTreeResponse {
  const timestamp = new Date().toISOString();
  return {
    id: createKey,
    name: "My first tree",
    revision: 0,
    schema_version: 1,
    metadata: {
      version: 1,
      created_at: timestamp,
      updated_at: timestamp,
      layout: null,
      owner_id: ownerId
    },
    nodes: [],
    relations: [],
    owner_id: ownerId
  };
}

export function CrtWorkspace({ createDraftCoordinator = createCrtDraftCoordinator, downloadBackup = defaultDownloadBackup }: CrtWorkspaceProps = {}): React.JSX.Element {
  const userId = useAuthStore((state) => state.user?.id ?? null);
  const [retryCount, setRetryCount] = useState(0);
  const [phase, setPhase] = useState<"loading" | "empty" | "error" | "recovery" | "ready">("loading");
  const [tree, setTree] = useState<CrtTreeResponse | null>(null);
  const [trees, setTrees] = useState<CrtTreeListItem[]>([]);
  const [graph, setGraph] = useState<GraphState | null>(null);
  const [loadReference, setLoadReference] = useState<string | undefined>();
  const [createError, setCreateError] = useState(false);
  const [conflictRefetched, setConflictRefetched] = useState(false);
  const [conflictRefreshReference, setConflictRefreshReference] = useState<string | undefined>();
  const [recovery, setRecovery] = useState<RecoveryState | null>(null);
  const [deferredRecovery, setDeferredRecovery] = useState<DeferredRecoveryState | null>(null);
  const [onlineOnlyRisk, setOnlineOnlyRisk] = useState(false);
  const [ownerError, setOwnerError] = useState(false);
  const [ownershipLost, setOwnershipLost] = useState(false);
  const [coordinatorState, setCoordinatorState] = useState<CrtDraftCoordinator | null>(null);
  const [managementBusy, setManagementBusy] = useState(false);
  const [managementError, setManagementError] = useState<string | undefined>();
  const [deleteTarget, setDeleteTarget] = useState<CrtTreeResponse | null>(null);
  const [deleteBarrierPassed, setDeleteBarrierPassed] = useState(false);
  const [pendingTransition, setPendingTransition] = useState<PendingTransition | null>(null);
  const [pendingAffectedTrees, setPendingAffectedTrees] = useState<readonly PendingWorkItem[]>([]);
  const [exportNeedsResolution, setExportNeedsResolution] = useState(false);

  const lifecycleRef = useRef(0);
  const mountedRef = useRef(true);
  const canvasOpenActivationRef = useRef(0);
  const canvasOpenEmittedRef = useRef(0);
  const createDraftCoordinatorRef = useRef(createDraftCoordinator);
  createDraftCoordinatorRef.current = createDraftCoordinator;
  const createIntentRef = useRef<{ key: string; migrationId: string; epoch: number; coordinator: CrtDraftCoordinator } | null>(null);
  const coordinatorRef = useRef<CrtDraftCoordinator | null>(null);
  const pendingScheduleRef = useRef<GraphState | null>(null);
  const importManagedTreeRef = useRef<((file: File, bypassSafety?: boolean) => Promise<void>) | null>(null);
  const canonicalCommitRef = useRef<{ treeId: string; revision: number; graph: GraphState; resolve: () => void } | null>(null);
  const pendingDraftClearRef = useRef<{ coordinator: CrtDraftCoordinator; tree: CrtTreeResponse; generation?: number } | null>(null);
  const managementMutationsRef = useRef(new Map<string, ManagementMutation>());
  const coordinatorInitialRiskRef = useRef(false);
  const pendingEnumerationFailedRef = useRef(false);

  const replaceCoordinator = useCallback((next: CrtDraftCoordinator | null) => {
    if (coordinatorRef.current && coordinatorRef.current !== next) coordinatorRef.current.dispose();
    coordinatorRef.current = next;
    coordinatorInitialRiskRef.current = next?.onlineOnlyRisk ?? false;
    if (next?.onlineOnlyRisk) setOnlineOnlyRisk(true);
    setCoordinatorState(next);
  }, []);
  const replaceCoordinatorRef = useRef(replaceCoordinator);
  replaceCoordinatorRef.current = replaceCoordinator;

  const persistence = useMemo<CrtAutosavePersistence | undefined>(() => {
    const coordinator = coordinatorState;
    if (!coordinator) return undefined;
    return {
      persistBeforeSave: (request) => coordinator.persistCommand(request),
      persistQueuedEdit: (request) => coordinator.persistQueuedEdit(request),
      persistRetry: (request) => coordinator.persistCommand(request),
      clearAfterCanonicalApplied: (response, applied, generation) => coordinator.clearAfterCanonicalApplied(response, applied, generation),
      onModeChange: (_mode, risk) => { if (risk) setOnlineOnlyRisk(true); }
    };
  }, [coordinatorState]);

  useLayoutEffect(() => {
    const pending = canonicalCommitRef.current;
    if (!pending || !tree || tree.id !== pending.treeId || tree.revision < pending.revision || !graph) return;
    const sameGraph = JSON.stringify({ nodes: graph.nodes, relations: graph.relations, viewportCenter: graph.viewportCenter }) ===
      JSON.stringify({ nodes: pending.graph.nodes, relations: pending.graph.relations, viewportCenter: pending.graph.viewportCenter });
    if (!sameGraph) return;
    canonicalCommitRef.current = null;
    pending.resolve();
  }, [graph, tree]);

  useLayoutEffect(() => {
    const pending = pendingDraftClearRef.current;
    if (!pending || !tree || tree.id !== pending.tree.id || !graph) return;
    pendingDraftClearRef.current = null;
    void pending.coordinator.clearAfterCanonicalApplied(tree, true, pending.generation);
  }, [graph, tree]);

  const applyCanonical = useCallback((canonical: CrtTreeResponse): Promise<void> => new Promise((resolve) => {
    const nextGraph = graphFromTree(canonical, graph ?? undefined);
    canonicalCommitRef.current = { treeId: canonical.id, revision: canonical.revision, graph: nextGraph, resolve };
    setTree(canonical);
    setGraph(nextGraph);
  }), [graph]);

  const autosave = useCrtAutosave(tree, applyCanonical, persistence);

  useEffect(() => {
    if (phase !== "ready" || !tree || !graph) return;
    const activation = canvasOpenActivationRef.current;
    if (activation === 0 || canvasOpenEmittedRef.current === activation) return;
    canvasOpenEmittedRef.current = activation;
    recordTelemetry({
      name: "crt.canvas_open",
      details: { outcome: "success", revision: tree.revision }
    });
  }, [graph, phase, tree]);

  const lossBarrier = useMemo(() => createCrtLossBarrier(), []);
  useEffect(() => {
    lossBarrier.setUnsynchronized(Boolean(onlineOnlyRisk && (autosave.status !== "Saved" || recovery || deferredRecovery)));
    return lossBarrier.attach();
  }, [autosave.status, deferredRecovery, lossBarrier, onlineOnlyRisk, recovery]);

  useEffect(() => {
    if (phase !== "ready" || !tree || !pendingScheduleRef.current) return;
    const next = pendingScheduleRef.current;
    pendingScheduleRef.current = null;
    setGraph(next);
    autosave.schedule(next);
  }, [autosave, phase, tree]);

  useEffect(() => {
    if (autosave.status !== "Conflict") setConflictRefetched(false);
  }, [autosave.status]);

  const backupDraft = useCallback((coordinator: CrtDraftCoordinator): void => {
    const backup = coordinator.backup();
    if (!backup.ok) throw new Error(`Draft backup unavailable: ${backup.reason}`);
    downloadBackup(backup);
  }, [downloadBackup]);

  const installLoadedTree = useCallback(async (loadedTree: CrtTreeResponse, skipDraftRecovery = false, clearGeneration?: number, recoveredGraph?: GraphState): Promise<void> => {
    if (!userId || loadedTree.owner_id !== userId) {
      setOwnerError(true);
      setPhase("error");
      return;
    }
    const ownerId = userId;
    const origin = globalThis.location?.origin ?? "";
    rememberCrtLastTreePreference({ ownerId, origin }, loadedTree.id);
    const nextCoordinator = createDraftCoordinator({
      owner_id: ownerId,
      origin,
      tree_id: loadedTree.id
    });
    replaceCoordinator(nextCoordinator);
    const initialized: DraftInitialization = await nextCoordinator.initialize();
    if (initialized.lock_state === "locked") {
      setOwnershipLost(true);
      setPhase("error");
      return;
    }
    if (initialized.online_only_risk) setOnlineOnlyRisk(true);
    const unsubscribeOwnership = nextCoordinator.subscribe((change) => {
      if (change.external && change.writer_session_id) {
        setOwnershipLost(true);
        setPhase("error");
      }
    });
    void unsubscribeOwnership;
    canvasOpenActivationRef.current += 1;
    setTree(loadedTree);
    setGraph(recoveredGraph ?? graphFromTree(loadedTree));
    if (skipDraftRecovery) {
      setRecovery(null);
      setPhase("ready");
      if (recoveredGraph) {
        pendingDraftClearRef.current = null;
        pendingScheduleRef.current = recoveredGraph;
      } else {
        pendingDraftClearRef.current = { coordinator: nextCoordinator, tree: loadedTree, generation: clearGeneration };
      }
      return;
    }
    if (initialized.classification === "invalid") {
      setRecovery({ kind: "invalid", reason: initialized.reason });
      setPhase("recovery");
      return;
    }
    if (initialized.draft && (initialized.classification === "fresh" || initialized.classification === "stale" || initialized.classification === "online-only")) {
      const localGraph = pendingDraftToGraphState(initialized.draft);
      if (!localGraph) {
        setRecovery({ kind: "invalid", reason: "draft-graph-integrity" });
        setPhase("recovery");
        return;
      }
      const migratedPreCanonical = initialized.draft.base_revision === null &&
        loadedTree.revision === 1 &&
        initialized.draft.migration_id !== undefined &&
        initialized.draft.migration_source_create_idempotency_key !== undefined;
      if (migratedPreCanonical) {
        setRecovery({ kind: "fresh-draft", draft: initialized.draft });
      } else if (initialized.draft.base_revision !== loadedTree.revision) {
        setRecovery({ kind: "conflict", draft: initialized.draft });
      } else if (initialized.classification === "stale") {
        setRecovery({ kind: "stale-draft", draft: initialized.draft });
      } else {
        setRecovery({ kind: "fresh-draft", draft: initialized.draft });
      }
      setPhase("recovery");
      return;
    }
    setRecovery(null);
    setPhase("ready");
  }, [createDraftCoordinator, replaceCoordinator, userId]);
  const installLoadedTreeRef = useRef(installLoadedTree);
  installLoadedTreeRef.current = installLoadedTree;

  useEffect(() => {

    mountedRef.current = true;
    const epoch = ++lifecycleRef.current;
    createIntentRef.current = null;
    const controller = new AbortController();
    let active = true;

    setPhase("loading");
    setLoadReference(undefined);
    setCreateError(false);
    setOwnerError(false);
    setOwnershipLost(false);
    setRecovery(null);
    void (async () => {
      try {
        const trees = await crtApi.listCrtTrees(controller.signal);
        if (!active || !mountedRef.current || epoch !== lifecycleRef.current) return;
        setTrees(trees);
        if (!userId) {
          setOwnerError(true);
          setPhase("error");
          return;
        }
        const scanCoordinator = createDraftCoordinatorRef.current({ owner_id: userId, origin: globalThis.location?.origin ?? "", tree_id: null });
        if (scanCoordinator.onlineOnlyRisk) setOnlineOnlyRisk(true);
        const scanned = await scanCoordinator.enumerateOwnerDrafts();
        if (!active || !mountedRef.current || epoch !== lifecycleRef.current) return;
        if (scanned.ok) {
          const preCanonical = scanned.value.find((entry) => entry.draft.tree_id === null && entry.draft.create_idempotency_key);
          if (preCanonical?.draft.create_idempotency_key) {
            scanCoordinator.dispose();
            const recoveryCoordinator = createDraftCoordinatorRef.current({
              owner_id: userId,
              origin: globalThis.location?.origin ?? "",
              tree_id: null,
              create_idempotency_key: preCanonical.draft.create_idempotency_key
            });
            replaceCoordinatorRef.current(recoveryCoordinator);
            createIntentRef.current = {
              key: preCanonical.draft.create_idempotency_key,
              migrationId: safeUuid(),
              epoch,
              coordinator: recoveryCoordinator
            };
            const initialized = await recoveryCoordinator.initialize();
            if (initialized.lock_state === "locked") {
              setOwnershipLost(true);
              setPhase("error");
              return;
            }
            if (initialized.online_only_risk) setOnlineOnlyRisk(true);
            const draftTree = preCanonicalTree(userId, preCanonical.draft.create_idempotency_key);
            const draftGraph = pendingDraftToGraphState(preCanonical.draft);
            if (!draftGraph) {
              setRecovery({ kind: "invalid", reason: "draft-graph-integrity" });
            } else {
              setTree(draftTree);
              setGraph(draftGraph);
              setRecovery({ kind: preCanonical.classification === "stale" ? "stale-draft" : "fresh-draft", draft: preCanonical.draft });
            }
            setPhase("recovery");
            return;
          }
        }
        scanCoordinator.dispose();
        const treeId = readCrtLastTreePreference(
          { ownerId: userId, origin: globalThis.location?.origin ?? "" },
          trees
        )?.id ?? newestTreeId(trees);
        if (!treeId) {
          setTree(null);
          setGraph(null);
          setPhase("empty");
          return;
        }
        const loadedTree = await crtApi.getCrtTree(treeId, controller.signal);
        if (!active || !mountedRef.current || epoch !== lifecycleRef.current) return;
        await installLoadedTreeRef.current(loadedTree);
      } catch (error) {
        if (!active || !mountedRef.current || controller.signal.aborted || epoch !== lifecycleRef.current) return;
        setLoadReference(referenceId(error));
        setCreateError(false);
        setPhase("error");
      }
    })();

    return () => {

      active = false;
      controller.abort();
      lifecycleRef.current += 1;
    };
  }, [retryCount, userId]);

  useEffect(() => () => {
    mountedRef.current = false;
    lifecycleRef.current += 1;
    coordinatorRef.current?.dispose();
    coordinatorRef.current = null;
  }, []);

  const createFirstTree = useCallback(async () => {
    if (!mountedRef.current || !userId) {
      setOwnerError(true);
      setPhase("error");
      return;
    }
    const epoch = lifecycleRef.current;
    const intent = createIntentRef.current ?? (() => {
      const key = safeUuid();
      const coordinator = createDraftCoordinator({
        owner_id: userId,
        origin: globalThis.location?.origin ?? "",
        tree_id: null,
        create_idempotency_key: key
      });
      return { key, migrationId: safeUuid(), epoch, coordinator };
    })();
    createIntentRef.current = intent;
    replaceCoordinator(intent.coordinator);
    if (intent.coordinator.onlineOnlyRisk) setOnlineOnlyRisk(true);
    setPhase("loading");
    setCreateError(false);
    try {
      const recoveredDraft = recovery?.draft?.tree_id === null && recovery.draft.create_idempotency_key === intent.key
        ? recovery.draft
        : undefined;
      const draftTree = preCanonicalTree(userId, intent.key);
      if (recoveredDraft) draftTree.name = recoveredDraft.tree.name;
      const draftGraph = recoveredDraft ? pendingDraftToGraphState(recoveredDraft) : graphFromTree(draftTree);
      if (!draftGraph) throw new Error("Could not verify the first-tree draft");
      const draftResult = await intent.coordinator.persistBeforeCreate(draftTree, draftGraph, recoveredDraft ? {
        dirty_operations: recoveredDraft.dirty_operations,
        in_flight_save: recoveredDraft.in_flight_save,
        queued_commands: recoveredDraft.queued_commands
      } : undefined);
      if (!draftResult.ok && draftResult.mode !== "online-only") throw new Error("Could not retain the first-tree draft");
      if (draftResult.online_only_risk) setOnlineOnlyRisk(true);
      const created = await crtApi.createCrtTree(
        { name: draftTree.name },
        { idempotencyKey: intent.key }
      );
      if (!mountedRef.current || epoch !== lifecycleRef.current || createIntentRef.current?.key !== intent.key) return;
      const rekeyed = await intent.coordinator.rekeyAfterCreate(created.id, intent.migrationId);


      if (!rekeyed.ok) throw new Error(`Could not finalize the first-tree draft: ${rekeyed.reason}`);
      const recoveredGraphHasEdits = Boolean(recoveredDraft && (
        draftGraph.nodes.length > 0 ||
        draftGraph.relations.length > 0 ||
        draftGraph.viewportCenter.x !== 0 ||
        draftGraph.viewportCenter.y !== 0 ||
        draftGraph.viewportZoom !== 1
      ));
      await installLoadedTree(created, true, rekeyed.value.generation, recoveredGraphHasEdits ? draftGraph : undefined);


      createIntentRef.current = null;
    } catch (error) {

      if (!mountedRef.current || epoch !== lifecycleRef.current || createIntentRef.current?.key !== intent.key) return;
      setLoadReference(referenceId(error));
      setCreateError(true);
      setPhase("error");
    }
  }, [createDraftCoordinator, installLoadedTree, recovery, replaceCoordinator, userId]);

  const finishRecovery = useCallback((nextGraph: GraphState) => {
    pendingScheduleRef.current = nextGraph;
    setGraph(nextGraph);
    setRecovery(null);
    setDeferredRecovery(null);
    setPhase("ready");
  }, []);

  const recoverDraft = useCallback(async () => {
    const coordinator = coordinatorRef.current;
    const draft = recovery?.draft;
    if (!coordinator || !draft) return;
    if (draft.tree_id === null) {
      await createFirstTree();
      return;
    }
    if (draft.in_flight_save && tree) {
      const replayed = await coordinator.replayInFlightSave(tree);
      if (!replayed.ok) throw new Error(`In-flight save replay failed: ${replayed.reason}`);
      if (replayed.response) {
        await autosave.syncCanonical(replayed.response);
        setTree(replayed.response);
        const rebased = applyReplayableCommands(graphFromTree(replayed.response), draft.queued_commands);
        if (draft.queued_commands.length === 0) {
          const cleared = await coordinator.clearAfterCanonicalApplied(replayed.response, true, draft.generation);
          if (!cleared.ok) throw new Error(`Replayed draft cleanup failed: ${cleared.reason}`);
          finishRecovery(rebased);
          return;
        }
        const persisted = await coordinator.completeInFlightRecovery(replayed.response, rebased);
        if (!persisted.ok) throw new Error(`Rebased draft persistence failed: ${persisted.reason}`);
        finishRecovery(rebased);
        return;
      }
    }
    const recovered = await coordinator.recover();
    if (!recovered.ok) throw new Error(`Draft recovery failed: ${recovered.reason}`);
    const nextGraph = pendingDraftToGraphState(recovered.draft);
    if (!nextGraph) throw new Error("Recovered draft failed integrity checks");
    finishRecovery(nextGraph);
  }, [autosave, createFirstTree, finishRecovery, recovery, tree]);

  const discardDraft = useCallback(async () => {
    const coordinator = coordinatorRef.current;
    const draft = recovery?.draft;
    if (!coordinator || !draft) return;
    const discarded = await coordinator.discard(draft.generation);
    if (!discarded.ok) throw new Error(`Draft discard failed: ${discarded.reason}`);
    if (!tree || draft.tree_id === null) {
      setTree(null);
      setGraph(null);
      setRecovery(null);
      setPhase("empty");
      return;
    }
    finishRecovery(graphFromTree(tree));
  }, [finishRecovery, recovery, tree]);

  const deferRecovery = useCallback(() => {
    if (!recovery?.draft || recovery.kind === "invalid" || !tree) return;
    setDeferredRecovery({ kind: recovery.kind, draft: recovery.draft });
    setRecovery(null);
    setGraph(graphFromTree(tree));
    setPhase("ready");
  }, [recovery, tree]);

  const refetchConflict = useCallback(async () => {
    if (!tree || autosave.status !== "Conflict") return;
    setConflictRefetched(false);
    setConflictRefreshReference(undefined);
    try {
      const latest = await crtApi.getCrtTree(tree.id);
      autosave.syncCanonical(latest);
      setTree(latest);
      setConflictRefetched(true);
    } catch (error) {
      setConflictRefreshReference(referenceId(error));
    }
  }, [autosave, tree]);

  const keepLocalConflict = useCallback(async () => {
    if (!tree || !recovery?.draft) return;
    const latest = await crtApi.getCrtTree(tree.id);
    autosave.syncCanonical(latest);
    const localGraph = pendingDraftToGraphState(recovery.draft);
    if (!localGraph) throw new Error("Local draft failed integrity checks");
    setTree(latest);
    finishRecovery(localGraph);
  }, [autosave, finishRecovery, recovery, tree]);

  const useServerConflict = useCallback(async () => {
    const coordinator = coordinatorRef.current;
    const draft = recovery?.draft;
    if (!coordinator || !draft || !tree) return;
    const discarded = await coordinator.discard(draft.generation);
    if (!discarded.ok) throw new Error(`Server-copy choice failed: ${discarded.reason}`);
    finishRecovery(graphFromTree(tree));
  }, [finishRecovery, recovery, tree]);

  const ensureTransitionSafe = useCallback((): boolean => {
    const coordinator = coordinatorRef.current;
    if (autosave.status === "Saved" && !deferredRecovery && !recovery) return true;
    if (coordinator?.mode === "online-only") {
      setManagementError("Cross-tab-safe recovery is unavailable while local storage is online-only. Keep this page open and restore durable recovery before changing trees.");
      return false;
    }
    setManagementError("Save or resolve local changes before changing trees.");
    return false;
  }, [autosave.status, deferredRecovery, recovery]);

  const managementIdempotencyKey = useCallback((operation: string, fingerprint: string): string => {
    const previous = managementMutationsRef.current.get(operation);
    if (previous?.fingerprint === fingerprint) return previous.key;
    const next = { fingerprint, key: safeUuid() };
    managementMutationsRef.current.set(operation, next);
    return next.key;
  }, []);

  const clearManagementIdempotencyKey = useCallback((operation: string, key: string): void => {
    if (managementMutationsRef.current.get(operation)?.key === key) managementMutationsRef.current.delete(operation);
  }, []);

  const collectPendingWork = useCallback(async (): Promise<readonly PendingWorkItem[] | null> => {
    const coordinator = coordinatorRef.current;
    if (!coordinator) return tree ? [{ id: tree.id, name: tree.name, editCount: 1 }] : [];
    const listed = await coordinator.enumerateOwnerDrafts();
    if (!listed.ok) {
      pendingEnumerationFailedRef.current = true;
      setManagementError("We couldn't verify every unsynced change. Nothing was discarded.");
      return tree ? [{ id: tree.id, name: tree.name, editCount: 1 }] : [];
    }
    const pending = listed.value.map((entry) => ({
      id: entry.draft.tree_id ?? entry.draft.create_idempotency_key ?? entry.draft.tree.name,
      name: entry.draft.tree.name,
      editCount: pendingEditCount(entry.draft)
    }));
    const currentIsPending = autosave.status !== "Saved" || Boolean(deferredRecovery || recovery);
    if (tree && currentIsPending && !pending.some((entry) => entry.id === tree.id)) {
      return [{ id: tree.id, name: tree.name, editCount: 1 }, ...pending];
    }
    return pending;
  }, [autosave.status, deferredRecovery, recovery, tree]);

  const openPendingTransition = useCallback(async (transition: PendingTransition): Promise<void> => {
    pendingEnumerationFailedRef.current = false;
    const affected = await collectPendingWork();
    if (!affected) return;
    setPendingAffectedTrees(affected);
    setPendingTransition(transition);
  }, [collectPendingWork]);

  const createManagedTree = useCallback(async () => {
    if (!userId || !ensureTransitionSafe()) return;
    const requestedName = globalThis.prompt("Name your new tree", "Current Reality Tree");
    const name = requestedName?.trim();
    if (!name) return;
    setManagementBusy(true);
    setManagementError(undefined);
    const idempotencyKey = managementIdempotencyKey("create", name);
    try {
      const created = await crtApi.createCrtTree({ name }, { idempotencyKey });
      clearManagementIdempotencyKey("create", idempotencyKey);
      setTrees((current) => [
        ...current.filter((entry) => entry.id !== created.id),
        { id: created.id, name: created.name, updated_at: created.metadata.updated_at, owner_id: created.owner_id }
      ]);
      await installLoadedTreeRef.current(created, true);
    } catch (error) {
      const reference = referenceId(error);
      setManagementError(reference ? `We couldn't create this tree. Support reference: ${reference}` : "We couldn't create this tree.");
    } finally {
      setManagementBusy(false);
    }
  }, [clearManagementIdempotencyKey, ensureTransitionSafe, managementIdempotencyKey, userId]);

  const renameManagedTree = useCallback(async () => {
    if (!tree || !graph || !ensureTransitionSafe()) return;
    const requestedName = globalThis.prompt("Rename tree", tree.name);
    const name = requestedName?.trim();
    if (!name || name === tree.name) return;
    setManagementBusy(true);
    setManagementError(undefined);
    const idempotencyKey = managementIdempotencyKey("rename", `${tree.id}:${tree.revision}:${name}`);
    try {
      const updated = await crtApi.updateCrtTree(
        tree.id,
        { ...graphToCrtUpdatePayload(tree, graph, tree.revision), name },
        { idempotencyKey }
      );
      clearManagementIdempotencyKey("rename", idempotencyKey);
      autosave.syncCanonical(updated);
      setTree(updated);
      setGraph(graphFromTree(updated, graph));
      setTrees((current) => current.map((entry) => entry.id === updated.id
        ? { ...entry, name: updated.name, updated_at: updated.metadata.updated_at }
        : entry));
    } catch (error) {
      const reference = referenceId(error);
      setManagementError(reference ? `We couldn't rename this tree. Support reference: ${reference}` : "We couldn't rename this tree.");
    } finally {
      setManagementBusy(false);
    }
  }, [autosave, clearManagementIdempotencyKey, ensureTransitionSafe, graph, managementIdempotencyKey, tree]);

  const selectManagedTree = useCallback(async (treeId: string, bypassSafety = false) => {
    if (!tree || treeId === tree.id) return;
    if (!bypassSafety && !ensureTransitionSafe()) {
      await openPendingTransition({ kind: "switch", treeId });
      return;
    }
    setManagementBusy(true);
    setManagementError(undefined);
    try {
      const selected = await crtApi.getCrtTree(treeId);
      await installLoadedTreeRef.current(selected);
    } catch (error) {
      const reference = referenceId(error);
      setManagementError(reference ? `We couldn't switch trees. Support reference: ${reference}` : "We couldn't switch trees.");
    } finally {
      setManagementBusy(false);
    }
  }, [ensureTransitionSafe, openPendingTransition, tree]);

  const discardPendingAndContinue = useCallback(async () => {
    const pending = pendingTransition;
    if (!pending || !tree) return;
    const coordinator = coordinatorRef.current;
    if (!coordinator) {
      setManagementError("We couldn't verify every unsynced change. Nothing was discarded.");
      return;
    }
    if (pendingEnumerationFailedRef.current) {
      setManagementError("We couldn't verify every unsynced change. Nothing was discarded.");
      return;
    }
    if (coordinator) {
      if (coordinator.onlineOnlyRisk && !coordinatorInitialRiskRef.current) {
        setManagementError("We couldn't verify every unsynced change. Nothing was discarded.");
        return;
      }
      const drafts = await coordinator.enumerateOwnerDrafts();
      if (!drafts.ok) {
        setManagementError("We couldn't verify every unsynced change. Nothing was discarded.");
        return;
      }
      if (drafts.mode === "online-only" && !coordinatorInitialRiskRef.current) {
        setManagementError("We couldn't verify every unsynced change. Nothing was discarded.");
        return;
      }
      const discarded = await coordinator.discardOwnerDrafts();
      if (!discarded.ok) {
        setManagementError("We couldn't discard the local changes. Nothing was discarded.");
        return;
      }
    }
    setGraph(graphFromTree(tree));
    setDeferredRecovery(null);
    setRecovery(null);
    setPendingTransition(null);
    if (pending.kind === "switch") {
      await selectManagedTree(pending.treeId, true);
    } else if (pending.kind === "import") {
      await importManagedTreeRef.current?.(pending.file, true);
    } else {
      setDeleteBarrierPassed(true);
      setDeleteTarget(pending.tree);
    }
  }, [pendingTransition, selectManagedTree, tree]);

  const exportManagedTree = useCallback(async () => {
    if (!tree) return;
    if (!ensureTransitionSafe()) {
      setExportNeedsResolution(true);
      return;
    }
    setManagementBusy(true);
    setManagementError(undefined);
    try {
      const exported = await crtApi.exportCrtTree(tree.id);
      downloadBackup({
        content: JSON.stringify(exported, null, 2),
        filename: `${tree.name.replace(/[^a-z0-9]+/gi, "-").replace(/^-|-$/g, "") || "crt-tree"}.json`,
        mime_type: "application/json"
      });
    } catch (error) {
      const reference = referenceId(error);
      setManagementError(reference ? `We couldn't export this tree. Support reference: ${reference}` : "We couldn't export this tree.");
    } finally {
      setManagementBusy(false);
    }
  }, [downloadBackup, ensureTransitionSafe, tree]);

  const downloadUnsynchronizedBackup = useCallback(() => {
    const coordinator = coordinatorRef.current;
    if (!coordinator) return;
    try {
      backupDraft(coordinator);
      setExportNeedsResolution(false);
    } catch (error) {
      setManagementError(error instanceof Error ? error.message : "Local backup is unavailable.");
    }
  }, [backupDraft]);

  const importManagedTree = useCallback(async (file: File, bypassSafety = false) => {
    if (!bypassSafety && !ensureTransitionSafe()) {
      await openPendingTransition({ kind: "import", file });
      return;
    }
    setManagementBusy(true);
    setManagementError(undefined);
    try {
      const parsed: unknown = JSON.parse(await file.text());
      const envelope = typeof parsed === "object" && parsed !== null && "tree" in parsed
        ? parsed as { tree: CrtTreeResponse }
        : { tree: parsed as CrtTreeResponse };
      if (!envelope.tree || typeof envelope.tree !== "object" || typeof envelope.tree.name !== "string") {
        throw new Error("The selected file is not a CRT tree export.");
      }
      const idempotencyKey = managementIdempotencyKey("import", JSON.stringify(envelope));
      const imported = await crtApi.importCrtTree(envelope, { idempotencyKey });
      clearManagementIdempotencyKey("import", idempotencyKey);
      setTrees((current) => [
        ...current,
        { id: imported.id, name: imported.name, updated_at: imported.metadata.updated_at, owner_id: imported.owner_id }
      ]);
      await installLoadedTreeRef.current(imported, true);
    } catch (error) {
      setManagementError(importFailureMessage(error));
    } finally {
      setManagementBusy(false);
    }
  }, [clearManagementIdempotencyKey, ensureTransitionSafe, managementIdempotencyKey, openPendingTransition]);
  importManagedTreeRef.current = importManagedTree;

  const deleteManagedTree = useCallback(async () => {
    if (!deleteTarget || (!deleteBarrierPassed && !ensureTransitionSafe())) return;
    setManagementBusy(true);
    setManagementError(undefined);
    const idempotencyKey = managementIdempotencyKey("delete", `${deleteTarget.id}:${deleteTarget.revision}`);
    try {
      await crtApi.deleteCrtTree(deleteTarget.id, { expectedRevision: deleteTarget.revision, idempotencyKey });
      clearManagementIdempotencyKey("delete", idempotencyKey);
      clearCrtLastTreePreference({ ownerId: userId ?? "", origin: globalThis.location?.origin ?? "" });
      const remaining = trees.filter((entry) => entry.id !== deleteTarget.id);
      setTrees(remaining);
      setDeleteTarget(null);
      setDeleteBarrierPassed(false);
      if (remaining.length === 0) {
        setTree(null);
        setGraph(null);
        setPhase("empty");
        return;
      }
      const nextId = newestTreeId(remaining);
      if (!nextId) return;
      const nextTree = await crtApi.getCrtTree(nextId);
      await installLoadedTreeRef.current(nextTree);
    } catch (error) {
      const reference = referenceId(error);
      setManagementError(reference ? `We couldn't delete this tree. Support reference: ${reference}` : "We couldn't delete this tree. Nothing was deleted.");
      throw error;
    } finally {
      setManagementBusy(false);
    }
  }, [clearManagementIdempotencyKey, deleteBarrierPassed, deleteTarget, ensureTransitionSafe, managementIdempotencyKey, trees, userId]);

  const openDeleteManagedTree = useCallback(() => {
    if (!tree) return;
    if (!ensureTransitionSafe()) {
      void openPendingTransition({ kind: "delete", tree });
      return;
    }
    setDeleteBarrierPassed(false);
    setDeleteTarget(tree);
  }, [ensureTransitionSafe, openPendingTransition, tree]);

  if (phase === "loading") {
    return (
      <main className="min-h-screen bg-surface-base px-6 py-8 text-slate-900">
        <header className="mx-auto max-w-6xl">
          <p className="text-xs font-semibold uppercase tracking-[0.06em] text-brand-primary">Thinking Mode</p>
          <h1 className="mt-2 text-title font-semibold">Current Reality Tree</h1>
          <p className="mt-2 text-sm text-slate-600" role="status">Loading your last tree…</p>
        </header>
      </main>
    );
  }

  if (phase === "error") {
    return (
      <main className="flex min-h-screen items-center justify-center bg-surface-base px-6 text-center">
        <section aria-live="polite" className="rounded-2xl border border-rose-200 bg-white px-8 py-10 shadow-raised">
          <p className="text-xs font-semibold uppercase tracking-[0.06em] text-brand-primary">Thinking Mode</p>
          <h1 className="mt-2 text-title font-semibold text-slate-900">{ownerError ? "We couldn't verify this tree" : ownershipLost ? "This tree is open in another tab" : createError ? "We couldn't create this tree" : "We couldn't load this tree"}</h1>
          <p className="mt-2 max-w-md text-sm text-slate-600">{ownerError ? "The authenticated owner could not be verified, so no tree content was opened." : ownershipLost ? "Editing is blocked until this tab owns the tree again." : createError ? "Your first-tree request is still safe to retry." : "Your route is unchanged. Retry loading to try again."}</p>
          {loadReference ? <p className="mt-3 font-mono text-xs text-slate-500">Support reference: {loadReference}</p> : null}
          <button type="button" className="mt-6 rounded-lg bg-brand-primary px-4 py-2 text-sm font-semibold text-white" onClick={() => ownershipLost ? setRetryCount((count) => count + 1) : createError ? void createFirstTree() : setRetryCount((count) => count + 1)}>
            {ownershipLost ? "Retry ownership" : createError ? "Retry creating tree" : "Retry loading"}
          </button>
        </section>
      </main>
    );
  }

  if (phase === "empty") {
    return (
      <main className="flex min-h-screen items-center justify-center bg-surface-base px-6 text-center">
        {onlineOnlyRisk ? <CrtStorageUnavailableAlert /> : null}
        <section className="rounded-2xl border border-slate-200 bg-white px-8 py-10 shadow-raised">
          <div className="mb-6 flex justify-center">
            <CrtTreeMenu
              currentTree={null}
              trees={trees}
              busy={managementBusy}
              error={managementError}
              onCreate={createManagedTree}
              onRename={async () => undefined}
              onImport={importManagedTree}
              onExport={async () => undefined}
              onDelete={async () => undefined}
              onSelectTree={selectManagedTree}
            />
          </div>
          <p className="text-xs font-semibold uppercase tracking-[0.06em] text-brand-primary">Thinking Mode</p>
          <h1 className="mt-2 text-title font-semibold text-slate-900">Start with your first undesired effect</h1>
          <p className="mt-2 max-w-md text-sm text-slate-600">No demo content is added for you.</p>
          <button type="button" className="mt-6 rounded-lg bg-brand-primary px-4 py-2 text-sm font-semibold text-white" onClick={() => void createFirstTree()}>Create first tree</button>
        </section>
      </main>
    );
  }

  if (phase === "recovery" && recovery?.kind === "invalid") {
    return (
      <main className="flex min-h-screen items-center justify-center bg-surface-base px-6 text-center">
        <section role="alert" className="rounded-2xl border border-rose-200 bg-white px-8 py-10 shadow-raised">
          <h1 className="text-title font-semibold text-slate-900">We couldn't verify the local draft</h1>
          <p className="mt-3 max-w-md text-sm text-slate-600">The draft was preserved and has not been applied or deleted. Retry loading to review it again.</p>
          {recovery.reason ? <p className="mt-3 font-mono text-xs text-slate-500">Recovery reference: {recovery.reason}</p> : null}
          <button type="button" className="mt-6 rounded-lg bg-brand-primary px-4 py-2 text-sm font-semibold text-white" onClick={() => setRetryCount((count) => count + 1)}>Retry loading</button>
        </section>
      </main>
    );
  }

  if (phase === "recovery" && recovery?.draft && tree) {
    const draft = recovery.draft;
    const isConflict = recovery.kind === "conflict";
    return (
      <main className="min-h-screen bg-surface-base px-6 py-8 text-slate-900">
        <header className="mx-auto max-w-6xl">
          <p className="text-xs font-semibold uppercase tracking-[0.06em] text-brand-primary">Thinking Mode</p>
          <h1 className="mt-2 text-title font-semibold">Current Reality Tree</h1>
          <p className="mt-2 text-sm text-slate-600">Review local recovery before the editable canvas is opened.</p>
        </header>
        {isConflict ? (
          <CrtRecoveryDialog
            kind="conflict"
            treeName={tree.name}
            serverCopy={{ label: "Server copy", revision: tree.revision, updatedAt: tree.metadata.updated_at, summary: "The latest canonical tree remains unchanged." }}
            localCopy={{ label: "Local draft", revision: draft.base_revision ?? undefined, updatedAt: draft.local_updated_at, summary: "Your browser draft remains preserved.", differences: recoverySummary(draft) }}
            localEditCount={Math.max(1, draft.dirty_operations.length)}
            comparisonStatus={conflictRefreshReference ? "error" : conflictRefetched ? "ready" : "ready"}
            comparisonError={conflictRefreshReference ? `We couldn't compare these versions. Support reference: ${conflictRefreshReference}` : undefined}
            onRetryComparison={() => refetchConflict()}
            onKeepLocalAndRetry={keepLocalConflict}
            onUseServerCopy={useServerConflict}
            onDownloadBackup={() => backupDraft(coordinatorRef.current as CrtDraftCoordinator)}
            onDefer={deferRecovery}
            onCancel={deferRecovery}
          />
        ) : (
          <CrtRecoveryDialog
            kind={recovery.kind === "stale-draft" ? "stale-draft" : "fresh-draft"}
            treeName={tree.name}
            onRecover={recoverDraft}
            onDownloadBackup={() => backupDraft(coordinatorRef.current as CrtDraftCoordinator)}
            onDiscard={discardDraft}
            onCancel={deferRecovery}
          />
        )}
      </main>
    );
  }

  if (!tree || !graph) return <></>;

  return (
    <main className="flex h-dvh min-h-0 flex-col overflow-hidden bg-surface-base text-slate-900">
      {onlineOnlyRisk ? <CrtStorageUnavailableAlert onRetry={autosave.retry} /> : null}
      <div className="shrink-0 border-b border-slate-200 bg-white px-6 py-3">
        <CrtTreeMenu
          currentTree={tree}
          trees={trees}
          busy={managementBusy}
          error={managementError}
          onCreate={createManagedTree}
          onRename={renameManagedTree}
          onImport={importManagedTree}
          onExport={exportManagedTree}
          onDelete={openDeleteManagedTree}
          onSelectTree={selectManagedTree}
        />
      </div>
      {exportNeedsResolution ? (
        <div className="border-b border-amber-200 bg-amber-50 px-6 py-3 text-center text-sm text-amber-950" role="alert">
          Unsynchronized changes are excluded from the saved server copy.
          <button type="button" className="ml-3 font-semibold underline" onClick={downloadUnsynchronizedBackup}>Download local backup</button>
          <button type="button" className="ml-3 underline" onClick={() => setExportNeedsResolution(false)}>Cancel</button>
        </div>
      ) : null}
      {deferredRecovery ? (
        <div className="border-b border-amber-200 bg-amber-50 px-6 py-3 text-center text-sm text-amber-950" role="status">
          Local draft retained. <button type="button" className="font-semibold underline" onClick={() => {
            setRecovery(deferredRecovery);
            setPhase("recovery");
          }}>Review local draft</button>
        </div>
      ) : null}
      <p className="sr-only" aria-live="polite">{tree.name}</p>
      {graph.nodes.length === 0 ? <p className="px-6 pt-4 text-center text-sm text-slate-600">Start with your first undesired effect</p> : null}
      <CrtCanvas
        graph={graph}
        historyKey={tree.id}
        saveStatus={autosave.status as "Saved" | "Unsaved changes"}
        onChange={(next) => {
          setGraph(next);
          autosave.schedule(next);
        }}
      />
      {autosave.status === "Conflict" ? (
        <div className="px-6 pb-4 text-center text-sm text-amber-800" role="alert">
          <p>The server changed this tree. Your local graph is retained; refresh the server copy before saving it again.</p>
          {conflictRefreshReference !== undefined ? <p>We couldn't refresh the server copy. Support reference: <span className="font-mono text-xs">{conflictRefreshReference}</span></p> : null}
          <button type="button" className="mr-3 font-semibold underline" onClick={() => void refetchConflict()}>Refresh server copy</button>
          {conflictRefetched ? <button type="button" className="font-semibold underline" onClick={() => autosave.rebase()}>Save local changes</button> : null}
          {autosave.reference ? <span className="ml-2 font-mono text-xs">Support reference: {autosave.reference}</span> : null}
        </div>
      ) : null}
      {autosave.status === "Save failed" ? (
        <div className="px-6 pb-4 text-center text-sm text-rose-700" role="alert">
          <button type="button" className="font-semibold underline" onClick={autosave.retry}>Retry save</button>
          {autosave.reference ? <span className="ml-2 font-mono text-xs">Support reference: {autosave.reference}</span> : null}
        </div>
      ) : null}
      {pendingTransition && tree ? (
        <CrtPendingWorkDialog
          affectedTrees={pendingAffectedTrees.length > 0 ? pendingAffectedTrees : [{ id: tree.id, name: tree.name, editCount: 1 }]}
          onStayAndRetry={async () => autosave.retry()}
          onDownloadBackup={async () => backupDraft(coordinatorRef.current as CrtDraftCoordinator)}
          onDiscardAndContinue={discardPendingAndContinue}
          onCancel={() => setPendingTransition(null)}
          offline={typeof navigator !== "undefined" && navigator.onLine === false}
          error={managementError}
        />
      ) : null}
      {deleteTarget ? (
        <CrtDeleteTreeDialog
          treeName={deleteTarget.name}
          cardCount={deleteTarget.nodes.length}
          relationCount={deleteTarget.relations.length}
          onCancel={() => setDeleteTarget(null)}
          onConfirm={deleteManagedTree}
          offline={typeof navigator !== "undefined" && !navigator.onLine}
        />
      ) : null}
    </main>
  );
}
