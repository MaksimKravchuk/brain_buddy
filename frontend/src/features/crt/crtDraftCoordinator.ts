import { crtApi, type CrtTreeResponse, type CrtTreeUpdatePayload } from "../../api/crt";
import type { CrtPersistenceRequest } from "./crtAutosave";
import { graphToCrtUpdatePayload } from "./crtAutosave";
import type { GraphState } from "./graphModel";
import { createGraphState } from "./graphModel";
import {
  createCrtDraftStore,
  draftStorageKey,
  normalizeOrigin,
  type CrtDraftStore,
  type DraftClock,
  type DraftCrypto,
  type DraftFailureReason,
  type DraftInFlightSave,
  type DraftLockManager,
  type DraftMode,
  type DraftOperationSummary,
  type DraftQueuedCommand,
  type DraftScope,
  type DraftStorage,
  type DraftWriteInput,
  type DraftResult,
  type PendingDraftEnvelope
} from "./draftStore";

export type CrtDraftJournal = Readonly<{
  dirty_operations?: readonly DraftOperationSummary[];
  in_flight_save?: DraftInFlightSave | null;
  queued_commands?: readonly DraftQueuedCommand[];
}>;

export type DraftClassification = "none" | "fresh" | "stale" | "invalid" | "online-only";

export type DraftInitialization = Readonly<{
  classification: DraftClassification;
  draft?: PendingDraftEnvelope;
  mode: DraftMode;
  online_only_risk: boolean;
  reason?: DraftFailureReason;
  lock_state: "held" | "locked" | "unavailable";
}>;

export type DraftEnumerationEntry = Readonly<{
  classification: Exclude<DraftClassification, "none" | "invalid"> | "invalid";
  draft: PendingDraftEnvelope;
  mode: DraftMode;
  online_only_risk: boolean;
}>;

export type DraftGenerationMessage = Readonly<{
  key: string;
  generation: number;
  writer_session_id: string;
  action: "changed" | "cleared";
}>;

export type DraftBroadcastEvent = Readonly<{ data: unknown }>;

export interface DraftBroadcast {
  postMessage(message: DraftGenerationMessage): void;
  addEventListener(type: "message", listener: (event: DraftBroadcastEvent) => void): void;
  removeEventListener(type: "message", listener: (event: DraftBroadcastEvent) => void): void;
  close?: () => void;
}

export type DraftStorageEvent = Readonly<{
  key: string | null;
  generation?: number;
  writer_session_id?: string;
  action?: "changed" | "cleared";
}>;

export interface DraftStorageEventSource {
  subscribe?: (listener: (event: DraftStorageEvent) => void) => () => void;
  addEventListener?: (type: "storage", listener: (event: DraftStorageEvent) => void) => void;
  removeEventListener?: (type: "storage", listener: (event: DraftStorageEvent) => void) => void;
}

export type CrtDraftChange = Readonly<{
  key: string;
  generation: number;
  action: "changed" | "cleared";
  writer_session_id?: string;
  external: boolean;
}>;

export type CrtDraftCoordinatorOptions = DraftScope & Readonly<{
  store?: CrtDraftStore;
  storage?: DraftStorage | null;
  clock?: DraftClock;
  writer_session_id?: string;
  lock_manager?: DraftLockManager | null;
  crypto?: DraftCrypto | null;
  broadcast?: DraftBroadcast | null;
  storage_events?: DraftStorageEventSource | null;
}>;

export type CoordinatorFailureReason = DraftFailureReason | "scope-mismatch" | "not-applied" | "lock-unavailable";

export type CoordinatorFailure = Readonly<{
  ok: false;
  reason: CoordinatorFailureReason;
  mode: DraftMode;
  online_only_risk: boolean;
}>;

export type PersistedDraft = Readonly<{
  ok: true;
  draft: PendingDraftEnvelope;
  tree_id: string | null;
  create_idempotency_key: string | null;
  generation: number;
  mode: DraftMode;
  online_only_risk: boolean;
}>;

export type PersistResult = PersistedDraft | CoordinatorFailure;

export type ClearResult = Readonly<{
  ok: true;
  cleared: boolean;
  mode: DraftMode;
  online_only_risk: boolean;
}> | CoordinatorFailure;

export type BackupResult = Readonly<{
  ok: true;
  filename: string;
  mime_type: "application/json";
  content: string;
  metadata: Readonly<{
    owner_id: string;
    origin: string;
    tree_id: string | null;
    create_idempotency_key: string | null;
    generation: number;
    local_updated_at: string;
  }>;
  mode: DraftMode;
  online_only_risk: boolean;
}> | CoordinatorFailure;

export type RekeyResult = DraftResult<PendingDraftEnvelope> | CoordinatorFailure | Readonly<{
  ok: true;
  value: PendingDraftEnvelope;
  draft: PendingDraftEnvelope;
  tree_id: string;
  mode: DraftMode;
}>;

export type DraftChangeListener = (change: CrtDraftChange) => void;

export type InFlightReplayResult = Readonly<{
  ok: true;
  replayed: boolean;
  response?: CrtTreeResponse;
}> | CoordinatorFailure;

export const CRT_ONLINE_ONLY_LOSS_MESSAGE = "Unsynchronized online-only changes may be lost. Stay on this page unless you explicitly confirm leaving.";

export type CrtLossBarrier = Readonly<{
  setUnsynchronized: (active: boolean) => void;
  isBlocking: () => boolean;
  attach: (target?: Window) => () => void;
}>;

export function createCrtLossBarrier(): CrtLossBarrier {
  let active = false;
  const shouldBlock = (): boolean => active || [...activeCrtCoordinators].some((coordinator) => coordinator.hasPendingDraft());
  return {
    setUnsynchronized(next) { active = next; },
    isBlocking() { return shouldBlock(); },
    attach(target = globalThis.window): () => void {
      if (!target) return () => undefined;
      const beforeUnload = (event: BeforeUnloadEvent) => {
        if (!shouldBlock()) return;
        event.preventDefault();
        event.returnValue = CRT_ONLINE_ONLY_LOSS_MESSAGE;
      };
      const navigation = (event: MouseEvent) => {
        if (!shouldBlock() || event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
        const element = event.target instanceof Element ? event.target.closest("a[href]") : null;
        if (!(element instanceof HTMLAnchorElement) || element.target === "_blank" || element.origin === target.location.origin) return;
        if (target.confirm(CRT_ONLINE_ONLY_LOSS_MESSAGE)) return;
        event.preventDefault();
        event.stopPropagation();
      };
      const history = target.history;
      const originalPushState = history.pushState.bind(history);
      const originalReplaceState = history.replaceState.bind(history);
      const originalGo = history.go.bind(history);
      const originalBack = history.back.bind(history);
      const originalForward = history.forward.bind(history);
      let previousUrl = target.location.href;
      let previousState: unknown = history.state;
      let restoringPop = false;
      const rememberLocation = (): void => {
        previousUrl = target.location.href;
        previousState = history.state;
      };
      const confirmNavigation = (): boolean => !shouldBlock() || target.confirm(CRT_ONLINE_ONLY_LOSS_MESSAGE);
      const handlePopState = (): void => {
        if (restoringPop) {
          restoringPop = false;
          rememberLocation();
          return;
        }
        if (confirmNavigation()) {
          rememberLocation();
          return;
        }
        const currentIndex = typeof history.state?.idx === "number" ? history.state.idx : undefined;
        const previousIndex = typeof (previousState as { idx?: unknown } | null)?.idx === "number"
          ? (previousState as { idx: number }).idx
          : undefined;
        if (currentIndex !== undefined && previousIndex !== undefined && currentIndex !== previousIndex) {
          restoringPop = true;
          originalGo(previousIndex - currentIndex);
          return;
        }
        originalPushState(previousState, "", previousUrl);
        target.dispatchEvent(new PopStateEvent("popstate", { state: previousState }));
      };
      history.pushState = ((state: unknown, title: string, url?: string | URL | null) => {
        if (confirmNavigation()) {
          originalPushState(state, title, url);
          rememberLocation();
        }
      }) as typeof history.pushState;
      history.replaceState = ((state: unknown, title: string, url?: string | URL | null) => {
        if (confirmNavigation()) {
          originalReplaceState(state, title, url);
          rememberLocation();
        }
      }) as typeof history.replaceState;
      history.go = ((delta?: number) => {
        if (confirmNavigation()) originalGo(delta);
      }) as typeof history.go;
      history.back = (() => {
        if (confirmNavigation()) originalBack();
      }) as typeof history.back;
      history.forward = (() => {
        if (confirmNavigation()) originalForward();
      }) as typeof history.forward;
      target.addEventListener("beforeunload", beforeUnload);
      target.addEventListener("click", navigation, true);
      target.addEventListener("popstate", handlePopState, true);
      return () => {
        target.removeEventListener("beforeunload", beforeUnload);
        target.removeEventListener("click", navigation, true);
        target.removeEventListener("popstate", handlePopState, true);
        history.pushState = originalPushState as typeof history.pushState;
        history.replaceState = originalReplaceState as typeof history.replaceState;
        history.go = originalGo as typeof history.go;
        history.back = originalBack as typeof history.back;
        history.forward = originalForward as typeof history.forward;
      };
    }
  };
}

function defaultStorage(): DraftStorage | null {
  try {
    return (globalThis as { localStorage?: DraftStorage }).localStorage ?? null;
  } catch {
    return null;
  }
}

function defaultBroadcast(): DraftBroadcast | null {
  try {
    const BroadcastChannelCtor = (globalThis as { BroadcastChannel?: new (name: string) => DraftBroadcast }).BroadcastChannel;
    return BroadcastChannelCtor ? new BroadcastChannelCtor("bb.crt.draft.v1.events") : null;
  } catch {
    return null;
  }
}

function defaultStorageEvents(): DraftStorageEventSource | null {
  try {
    const globalWindow = globalThis as unknown as DraftStorageEventSource;
    return typeof globalWindow.addEventListener === "function" ? globalWindow : null;
  } catch {
    return null;
  }
}

let coordinatorSessionSequence = 0;

function defaultMigrationId(): string {
  const cryptoApi = (globalThis as { crypto?: { randomUUID?: () => string } }).crypto;
  if (cryptoApi?.randomUUID) return cryptoApi.randomUUID();
  coordinatorSessionSequence += 1;
  return `00000000-0000-4000-8000-${String(coordinatorSessionSequence).padStart(12, "0")}`;
}

async function sha256Hex(value: string): Promise<string> {
  try {
    const cryptoApi = (globalThis as { crypto?: DraftCrypto }).crypto;
    if (!cryptoApi?.subtle) return "0".repeat(64);
    const digest = await cryptoApi.subtle.digest("SHA-256", new TextEncoder().encode(value).slice().buffer);
    return [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, "0")).join("");
  } catch {
    return "0".repeat(64);
  }
}

function isGenerationMessage(value: unknown): value is DraftGenerationMessage {
  if (typeof value !== "object" || value === null) return false;
  const message = value as Record<string, unknown>;
  return typeof message.key === "string" && typeof message.generation === "number" && Number.isInteger(message.generation) &&
    message.generation >= 1 && typeof message.writer_session_id === "string" &&
    (message.action === "changed" || message.action === "cleared");
}

function inputFromState(
  tree: CrtTreeResponse,
  graph: GraphState,
  scope: DraftScope,
  journal: CrtDraftJournal = {},
  relationCreatedAt = new Map<string, string>()
): DraftWriteInput {
  const payload = graphToCrtUpdatePayload(tree, graph, tree.revision, relationCreatedAt);
  return {
    tree: {
      name: payload.name,
      nodes: payload.nodes,
      relations: payload.relations,
      layout: payload.metadata.layout
    },
    create_idempotency_key: scope.create_idempotency_key ?? null,
    base_revision: scope.tree_id == null ? null : tree.revision,
    base_updated_at: scope.tree_id == null ? null : tree.metadata.updated_at,
    dirty_operations: journal.dirty_operations ? [...journal.dirty_operations] : [],
    in_flight_save: journal.in_flight_save ?? null,
    queued_commands: journal.queued_commands ? [...journal.queued_commands] : []
  };
}

export function pendingDraftToGraphState(draft: PendingDraftEnvelope): GraphState | null {
  const nodes: Array<{ id: string; label: string; position: { x: number; y: number } }> = [];
  const nodeIds = new Set<string>();
  for (const candidate of draft.tree.nodes) {
    if (typeof candidate !== "object" || candidate === null) return null;
    const value = candidate as Record<string, unknown>;
    const position = value.position;
    if (typeof value.id !== "string" || value.id.length === 0 || nodeIds.has(value.id) ||
        typeof value.label !== "string" || value.label.trim().length === 0 ||
        typeof position !== "object" || position === null ||
        typeof (position as { x?: unknown }).x !== "number" || !Number.isFinite((position as { x: number }).x) ||
        typeof (position as { y?: unknown }).y !== "number" || !Number.isFinite((position as { y: number }).y)) return null;
    nodeIds.add(value.id);
    nodes.push({ id: value.id, label: value.label, position: { x: (position as { x: number }).x, y: (position as { y: number }).y } });
  }
  const relations: Array<{ id: string; sourceId: string; targetId: string }> = [];
  const relationIds = new Set<string>();
  for (const candidate of draft.tree.relations) {
    if (typeof candidate !== "object" || candidate === null) return null;
    const value = candidate as Record<string, unknown>;
    if (typeof value.id !== "string" || value.id.length === 0 || relationIds.has(value.id) ||
        typeof value.source_node_id !== "string" || !nodeIds.has(value.source_node_id) ||
        typeof value.target_node_id !== "string" || !nodeIds.has(value.target_node_id) ||
        value.source_node_id === value.target_node_id) return null;
    relationIds.add(value.id);
    relations.push({ id: value.id, sourceId: value.source_node_id, targetId: value.target_node_id });
  }
  const layout = typeof draft.tree.layout === "object" && draft.tree.layout !== null
    ? draft.tree.layout as Record<string, unknown>
    : {};
  const center = typeof layout.center === "object" && layout.center !== null
    ? layout.center as Record<string, unknown>
    : {};
  const zoom = typeof layout.zoom === "number" && Number.isFinite(layout.zoom)
    ? Math.min(1, Math.max(0.25, layout.zoom))
    : 1;
  return createGraphState({
    nodes,
    relations,
    viewportCenter: typeof center.x === "number" && Number.isFinite(center.x) && typeof center.y === "number" && Number.isFinite(center.y)
      ? { x: center.x, y: center.y }
      : { x: 0, y: 0 },
    viewportZoom: zoom
  });
}

/** Convert the current canonical tree, visible graph, and autosave journal to the draft schema. */
export function draftWriteInputFromCrtState(
  tree: CrtTreeResponse,
  graph: GraphState,
  scope: DraftScope,
  journal: CrtDraftJournal = {}
): DraftWriteInput {
  return inputFromState(tree, graph, scope, journal);
}

export const toDraftWriteInput = draftWriteInputFromCrtState;

export class CrtDraftCoordinator {
  private readonly store: CrtDraftStore;
  private readonly scope: DraftScope;
  private readonly key: string;
  private readonly relationCreatedAt = new Map<string, string>();
  private readonly listeners = new Set<DraftChangeListener>();
  private readonly broadcast: DraftBroadcast | null;
  private readonly storageEvents: DraftStorageEventSource | null;
  private readonly writerSessionId: string;
  private readonly editLockManager: DraftLockManager | null;
  private editLockState: "held" | "locked" | "unavailable" = "unavailable";
  private editLockRelease: (() => void) | undefined;
  private editLockRequest: Promise<void> | undefined;
  private initializationPromise: Promise<DraftInitialization> | undefined;
  private readonly unsubscribeStorage: (() => void) | undefined;
  private readonly onBroadcast = (event: DraftBroadcastEvent): void => {
    if (!isGenerationMessage(event.data) || event.data.key !== this.key) return;
    this.emitChange({
      key: event.data.key,
      generation: event.data.generation,
      action: event.data.action,
      writer_session_id: event.data.writer_session_id,
      external: true
    });
  };
  private onlineOnlyRiskState: boolean;

  public constructor(options: CrtDraftCoordinatorOptions) {
    const origin = normalizeOrigin(options.origin);
    this.scope = {
      owner_id: options.owner_id,
      origin,
      tree_id: options.tree_id ?? null,
      ...(options.create_idempotency_key === undefined ? {} : { create_idempotency_key: options.create_idempotency_key })
    };
    this.key = draftStorageKey(this.scope);
    this.writerSessionId = options.writer_session_id ?? defaultMigrationId();
    this.editLockManager = options.lock_manager === undefined
      ? (globalThis as { navigator?: { locks?: DraftLockManager } }).navigator?.locks ?? null
      : options.lock_manager;
    this.store = options.store ?? createCrtDraftStore({
      storage: options.storage === undefined ? defaultStorage() : options.storage,
      clock: options.clock,
      writer_session_id: this.writerSessionId,
      lock_manager: options.lock_manager,
      crypto: options.crypto
    });
    this.broadcast = options.broadcast === undefined ? defaultBroadcast() : options.broadcast;
    this.storageEvents = options.storage_events === undefined ? defaultStorageEvents() : options.storage_events;
    this.onlineOnlyRiskState = this.store.mode === "online-only";
    if (this.broadcast) this.broadcast.addEventListener("message", this.onBroadcast);
    const onStorageEvent = (event: DraftStorageEvent): void => {
      if (event.key !== this.key) return;
      this.emitChange({
        key: this.key,
        generation: event.generation ?? 0,
        action: event.action ?? "changed",
        writer_session_id: event.writer_session_id,
        external: true
      });
    };
    if (this.storageEvents?.subscribe) {
      this.unsubscribeStorage = this.storageEvents.subscribe(onStorageEvent);
    } else if (this.storageEvents?.addEventListener) {
      this.storageEvents.addEventListener("storage", onStorageEvent);
      this.unsubscribeStorage = this.storageEvents.removeEventListener
        ? () => this.storageEvents?.removeEventListener?.("storage", onStorageEvent)
        : undefined;
    }
    activeCrtCoordinators.add(this);
  }

  public get storageMode(): DraftMode { return this.store.mode; }
  public get mode(): DraftMode { return this.store.mode; }
  public get onlineOnlyRisk(): boolean { return this.onlineOnlyRiskState; }
  public get scopeKey(): string { return this.key; }
  public get activeScope(): DraftScope { return { ...this.scope }; }

  private resultFailure(reason: CoordinatorFailureReason, mode = this.store.mode): CoordinatorFailure {
    if (mode === "online-only") this.onlineOnlyRiskState = true;
    return { ok: false, reason, mode, online_only_risk: this.onlineOnlyRiskState };
  }

  private trackMode(mode: DraftMode): void {
    if (mode === "online-only") this.onlineOnlyRiskState = true;
  }

  private emitChange(change: CrtDraftChange): void {
    this.listeners.forEach((listener) => listener(change));
  }

  private publish(generation: number, action: "changed" | "cleared", writerSessionId = this.writerSessionId): void {
    this.trackMode(this.store.mode);
    const message: DraftGenerationMessage = {
      key: this.key,
      generation,
      writer_session_id: writerSessionId,
      action
    };
    this.broadcast?.postMessage(message);
    this.emitChange({ ...message, external: false });
  }

  private matchesTree(tree: CrtTreeResponse): boolean {
    return this.scope.tree_id === null || (tree.id === this.scope.tree_id && tree.owner_id === this.scope.owner_id);
  }

  private matchesCanonicalResponse(response: CrtTreeResponse): boolean {
    return this.scope.tree_id !== null && response.id === this.scope.tree_id && response.owner_id === this.scope.owner_id;
  }

  private currentRead(): ReturnType<CrtDraftStore["read"]> {
    return this.store.read(this.scope);
  }

  public hasPendingDraft(): boolean {
    const current = this.currentRead();
    return current.ok && current.found;
  }

  private async ensureEditLock(): Promise<"held" | "locked" | "unavailable"> {
    if (this.editLockState === "held" || this.editLockState === "locked") return this.editLockState;
    if (!this.editLockManager || !this.key) {
      this.editLockState = "unavailable";
      return this.editLockState;
    }
    if (this.editLockRequest) {
      await this.editLockRequest;
      return this.editLockState;
    }
    let ready!: () => void;
    const readyPromise = new Promise<void>((resolve) => { ready = resolve; });
    let release!: () => void;
    const hold = new Promise<void>((resolve) => { release = resolve; });
    this.editLockRelease = release;
    this.editLockRequest = this.editLockManager.request(`bb.crt.edit.${this.key}`, { mode: "exclusive", ifAvailable: true }, async (lock) => {
      if (!lock) {
        this.editLockState = "locked";
        ready();
        return;
      }
      this.editLockState = "held";
      ready();
      await hold;
    }).then(() => undefined).catch(() => {
      if (this.editLockState !== "held") this.editLockState = "locked";
      ready();
    });
    await readyPromise;
    return this.editLockState;
  }

  public get editLockStatus(): "held" | "locked" | "unavailable" { return this.editLockState; }

  public async initialize(): Promise<DraftInitialization> {
    return (async () => {
      const lockState = await this.ensureEditLock();
      if (lockState === "locked") return {
        classification: "none" as const,
        mode: this.store.mode,
        online_only_risk: this.onlineOnlyRiskState,
        lock_state: lockState
      };
      const read = this.currentRead();
        this.trackMode(read.mode);
        if (!read.ok) {
          return {
            classification: read.reason === "invalid-json" || read.reason === "invalid-schema" || read.reason === "invalid-draft" ? "invalid" as const : "online-only" as const,
            mode: read.mode,
            online_only_risk: this.onlineOnlyRiskState,
            reason: read.reason,
            lock_state: lockState
          };
        }
        if (!read.found) {
          return {
            classification: read.mode === "online-only" ? "online-only" as const : "none" as const,
            mode: read.mode,
            online_only_risk: this.onlineOnlyRiskState,
            lock_state: lockState
          };
        }
        return {
          classification: read.mode === "online-only" ? "online-only" as const : read.stale ? "stale" as const : "fresh" as const,
          draft: read.value,
          mode: read.mode,
          online_only_risk: this.onlineOnlyRiskState,
          lock_state: lockState
        };
      })();
  }

  public async retryInitialization(): Promise<DraftInitialization> {
    if (this.editLockState === "locked") {
      this.editLockState = "unavailable";
      this.editLockRequest = undefined;
      this.initializationPromise = undefined;
    }
    return this.initialize();
  }

  public async enumerate(): Promise<DraftResult<readonly DraftEnumerationEntry[]>> {
    const listed = await this.store.list({ owner_id: this.scope.owner_id, origin: this.scope.origin });
    this.trackMode(listed.mode);
    if (!listed.ok) return listed;
    const entries: DraftEnumerationEntry[] = listed.value
      .filter((entry) => draftStorageKey({
        owner_id: entry.value.owner_id,
        origin: entry.value.origin,
        tree_id: entry.value.tree_id,
        create_idempotency_key: entry.value.create_idempotency_key
      }) === this.key)
      .map((entry) => ({
        classification: listed.mode === "online-only" ? "online-only" : entry.stale ? "stale" : "fresh",
        draft: entry.value,
        mode: listed.mode,
        online_only_risk: this.onlineOnlyRiskState
      }));
    return { ok: true, value: entries, mode: listed.mode };
  }

  public async enumerateOwnerDrafts(): Promise<DraftResult<readonly DraftEnumerationEntry[]>> {
    const listed = await this.store.list({ owner_id: this.scope.owner_id, origin: this.scope.origin });
    this.trackMode(listed.mode);
    if (!listed.ok) return listed;
    return {
      ok: true,
      value: listed.value.map((entry) => ({
        classification: listed.mode === "online-only" ? "online-only" : entry.stale ? "stale" : "fresh",
        draft: entry.value,
        mode: listed.mode,
        online_only_risk: this.onlineOnlyRiskState
      })),
      mode: listed.mode
    };
  }

  private persistInput(input: DraftWriteInput): Promise<PersistResult> {
    return this.store.withWriter(this.scope, () => this.store.write(this.scope, input)).then((writerResult) => {
      if (!writerResult.ok) return this.resultFailure(writerResult.reason, this.store.mode);
      const written = writerResult.value;
      this.trackMode(written.mode);
      if (!written.ok) return this.resultFailure(written.reason, written.mode);
      this.publish(written.value.generation, "changed", written.value.writer_session_id);
      return {
        ok: true,
        draft: written.value,
        tree_id: written.value.tree_id,
        create_idempotency_key: written.value.create_idempotency_key,
        generation: written.value.generation,
        mode: written.mode,
        online_only_risk: this.onlineOnlyRiskState
      };
    });
  }

  private persist(tree: CrtTreeResponse, graph: GraphState, journal: CrtDraftJournal): Promise<PersistResult> {
    if (!this.key || !this.matchesTree(tree)) return Promise.resolve(this.resultFailure("scope-mismatch"));
    return this.persistInput(inputFromState(tree, graph, this.scope, journal, this.relationCreatedAt));
  }

  /** Persist the exact visible save snapshot before dispatching its server request. */
  public persistBeforeSave(tree: CrtTreeResponse, graph: GraphState, journal: CrtDraftJournal = {}): Promise<PersistResult> {
    return this.persist(tree, graph, journal);
  }

  public persistBeforeServerSave = this.persistBeforeSave.bind(this);

  public async persistCommand(request: CrtPersistenceRequest): Promise<PersistResult> {
    if (!this.key || !this.matchesTree(request.tree)) return this.resultFailure("scope-mismatch");
    const snapshot = {
      name: request.payload.name,
      nodes: request.payload.nodes,
      relations: request.payload.relations,
      layout: request.payload.metadata.layout
    };
    const hash = await sha256Hex(JSON.stringify({
      idempotency_key: request.idempotencyKey,
      base_revision: request.baseRevision,
      snapshot
    }));
    return this.persistInput({
      tree: snapshot,
      create_idempotency_key: this.scope.create_idempotency_key ?? null,
      base_revision: request.baseRevision,
      base_updated_at: request.tree.metadata.updated_at,
      in_flight_save: {
        idempotency_key: request.idempotencyKey,
        base_revision: request.baseRevision,
        generation: request.generation,
        snapshot,
        hash,
        request_payload: request.payload as unknown as Record<string, unknown>
      }
    });
  }

  public async persistQueuedEdit(request: Readonly<{
    active: CrtPersistenceRequest;
    visibleGraph: GraphState;
    queuedCommands: readonly DraftQueuedCommand[];
  }>): Promise<PersistResult> {
    if (!this.key || !this.matchesTree(request.active.tree)) return this.resultFailure("scope-mismatch");
    const visiblePayload = graphToCrtUpdatePayload(request.active.tree, request.visibleGraph, request.active.baseRevision, this.relationCreatedAt);
    const snapshot = {
      name: visiblePayload.name,
      nodes: visiblePayload.nodes,
      relations: visiblePayload.relations,
      layout: visiblePayload.metadata.layout
    };
    const activeSnapshot = {
      name: request.active.payload.name,
      nodes: request.active.payload.nodes,
      relations: request.active.payload.relations,
      layout: request.active.payload.metadata.layout
    };
    const hash = await sha256Hex(JSON.stringify({
      idempotency_key: request.active.idempotencyKey,
      base_revision: request.active.baseRevision,
      snapshot: activeSnapshot
    }));
    return this.persistInput({
      tree: snapshot,
      create_idempotency_key: this.scope.create_idempotency_key ?? null,
      base_revision: request.active.baseRevision,
      base_updated_at: request.active.tree.metadata.updated_at,
      in_flight_save: {
        idempotency_key: request.active.idempotencyKey,
        base_revision: request.active.baseRevision,
        generation: request.active.generation,
        snapshot: activeSnapshot,
        hash,
        request_payload: request.active.payload as unknown as Record<string, unknown>
      },
      queued_commands: request.queuedCommands
    });
  }

  public async replayInFlightSave(
    tree: CrtTreeResponse,
    update: typeof crtApi.updateCrtTree = crtApi.updateCrtTree
  ): Promise<InFlightReplayResult> {
    if (!this.matchesTree(tree)) return this.resultFailure("scope-mismatch");
    const current = this.currentRead();
    if (!current.ok) return this.resultFailure(current.reason, current.mode);
    if (!current.found || !current.value.in_flight_save) return { ok: true, replayed: false };
    const inFlight = current.value.in_flight_save;
    const expectedHash = await sha256Hex(JSON.stringify({
      idempotency_key: inFlight.idempotency_key,
      base_revision: inFlight.base_revision,
      snapshot: inFlight.snapshot
    }));
    if (expectedHash !== inFlight.hash || !inFlight.request_payload) return this.resultFailure("invalid-draft");
    const response = await update(tree.id, inFlight.request_payload as unknown as CrtTreeUpdatePayload, {
      idempotencyKey: inFlight.idempotency_key,
      signal: new AbortController().signal
    });
    return { ok: true, replayed: true, response };
  }

  public async completeInFlightRecovery(response: CrtTreeResponse, graph: GraphState): Promise<PersistResult> {
    return this.persist(response, graph, { dirty_operations: [], in_flight_save: null, queued_commands: [] });
  }

  public persistRetry(tree: CrtTreeResponse, graph: GraphState, journal: CrtDraftJournal = {}): Promise<PersistResult> {
    return this.persist(tree, graph, journal);
  }

  /** Persist the same immutable snapshot/key used for a pre-canonical create. */
  public persistBeforeCreate(tree: CrtTreeResponse, graph: GraphState, journal: CrtDraftJournal = {}): Promise<PersistResult> {
    return this.persist(tree, graph, journal);
  }

  public async clearAfterCanonicalApplied(
    response: CrtTreeResponse,
    applied = true,
    expectedGeneration?: number
  ): Promise<ClearResult> {
    if (!applied) return { ok: true, cleared: false, mode: this.store.mode, online_only_risk: this.onlineOnlyRiskState };
    if (!this.matchesCanonicalResponse(response)) return this.resultFailure("scope-mismatch");
    const current = this.currentRead();
    if (!current.ok) return this.resultFailure(current.reason, current.mode);
    if (!current.found) return { ok: true, cleared: false, mode: current.mode, online_only_risk: this.onlineOnlyRiskState };
    const generation = expectedGeneration ?? current.value.generation;
    const writerResult = await this.store.withWriter(this.scope, () => this.store.discard(this.scope, { expected_generation: generation }));
    if (!writerResult.ok) return this.resultFailure(writerResult.reason, this.store.mode);
    const cleared = writerResult.value;
    this.trackMode(cleared.mode);
    if (!cleared.ok) return this.resultFailure(cleared.reason, cleared.mode);
    if (cleared.value) this.publish(generation, "cleared", current.value.writer_session_id);
    return { ok: true, cleared: cleared.value, mode: cleared.mode, online_only_risk: this.onlineOnlyRiskState };
  }

  public clearAfterCanonicalResponse = this.clearAfterCanonicalApplied.bind(this);

  public async recover(): Promise<Readonly<{ ok: true; draft: PendingDraftEnvelope; generation: number; mode: DraftMode; online_only_risk: boolean }> | CoordinatorFailure> {
    const writerResult = await this.store.withWriter(this.scope, () => this.store.recover(this.scope));
    if (!writerResult.ok) return this.resultFailure(writerResult.reason, this.store.mode);
    const recovered = writerResult.value;
    this.trackMode(recovered.mode);
    if (!recovered.ok) return this.resultFailure(recovered.reason, recovered.mode);
    this.publish(recovered.value.generation, "changed", recovered.value.writer_session_id);
    return {
      ok: true,
      draft: recovered.value,
      generation: recovered.value.generation,
      mode: recovered.mode,
      online_only_risk: this.onlineOnlyRiskState
    };
  }

  public backup(): BackupResult {
    const exported = this.store.exportBackup(this.scope);
    this.trackMode(exported.mode);
    if (!exported.ok) return this.resultFailure(exported.reason, exported.mode);
    let value: PendingDraftEnvelope;
    try { value = JSON.parse(exported.value) as PendingDraftEnvelope; }
    catch { return this.resultFailure("invalid-json", exported.mode); }
    const identity = value.tree_id ?? value.create_idempotency_key ?? "draft";
    return {
      ok: true,
      filename: `crt-${identity}-draft.json`,
      mime_type: "application/json",
      content: exported.value,
      metadata: {
        owner_id: value.owner_id,
        origin: value.origin,
        tree_id: value.tree_id,
        create_idempotency_key: value.create_idempotency_key,
        generation: value.generation,
        local_updated_at: value.local_updated_at
      },
      mode: exported.mode,
      online_only_risk: this.onlineOnlyRiskState
    };
  }

  public async discard(expectedGeneration?: number): Promise<ClearResult> {
    const current = this.currentRead();
    if (!current.ok) return this.resultFailure(current.reason, current.mode);
    if (!current.found) return { ok: true, cleared: false, mode: current.mode, online_only_risk: this.onlineOnlyRiskState };
    const generation = expectedGeneration ?? current.value.generation;
    const writerResult = await this.store.withWriter(this.scope, () => this.store.discard(this.scope, { expected_generation: generation }));
    if (!writerResult.ok) return this.resultFailure(writerResult.reason, this.store.mode);
    const discarded = writerResult.value;
    this.trackMode(discarded.mode);
    if (!discarded.ok) return this.resultFailure(discarded.reason, discarded.mode);
    if (discarded.value) this.publish(generation, "cleared", current.value.writer_session_id);
    return { ok: true, cleared: discarded.value, mode: discarded.mode, online_only_risk: this.onlineOnlyRiskState };
  }

  public async rekeyAfterCreate(canonicalTreeId: string, migrationId = defaultMigrationId()): Promise<RekeyResult> {
    if (this.scope.tree_id !== null) return this.resultFailure("scope-mismatch");
    const rekeyed = await this.store.rekeyPreCanonical(this.scope, canonicalTreeId, migrationId);
    this.trackMode(rekeyed.mode);
    if (rekeyed.ok) {
      this.publish(rekeyed.value.generation, "changed", rekeyed.value.writer_session_id);
      return { ...rekeyed, tree_id: rekeyed.value.tree_id as string, draft: rekeyed.value };
    }
    return rekeyed;
  }

  public async cleanupAccountScope(): Promise<Readonly<{ ok: true; removed: number; mode: DraftMode; online_only_risk: boolean }> | CoordinatorFailure> {
    const cleaned = await this.store.cleanupOwnerTransition({ owner_id: this.scope.owner_id, origin: this.scope.origin });
    this.trackMode(cleaned.mode);
    if (!cleaned.ok) return this.resultFailure(cleaned.reason, cleaned.mode);
    this.emitChange({ key: `${this.key}:owner`, generation: 0, action: "cleared", external: false });
    return { ok: true, removed: cleaned.value, mode: cleaned.mode, online_only_risk: this.onlineOnlyRiskState };
  }

  /** Discard every currently listed draft for this owner/origin after explicit user confirmation. */
  public async discardOwnerDrafts(): Promise<Readonly<{ ok: true; removed: number; mode: DraftMode; online_only_risk: boolean }> | CoordinatorFailure> {
    const listed = await this.enumerateOwnerDrafts();
    if (!listed.ok) return this.resultFailure(listed.reason, listed.mode);
    if (listed.mode === "online-only") {
      let removed = 0;
      for (const entry of listed.value) {
        const scope: DraftScope = {
          owner_id: entry.draft.owner_id,
          origin: entry.draft.origin,
          tree_id: entry.draft.tree_id,
          create_idempotency_key: entry.draft.create_idempotency_key
        };
        const discarded = await this.store.withWriter(
          scope,
          () => this.store.discard(scope, { expected_generation: entry.draft.generation })
        );
        if (!discarded.ok) return this.resultFailure(discarded.reason, this.store.mode);
        if (!discarded.value.ok) return this.resultFailure(discarded.value.reason, discarded.value.mode);
        if (!discarded.value.value) return this.resultFailure("cleanup-failed", discarded.value.mode);
        removed += 1;
        this.publish(entry.draft.generation, "cleared", entry.draft.writer_session_id);
      }
      return { ok: true, removed, mode: "online-only", online_only_risk: this.onlineOnlyRiskState };
    }
    const cleaned = await this.store.cleanupOwnerTransition({ owner_id: this.scope.owner_id, origin: this.scope.origin });
    this.trackMode(cleaned.mode);
    if (!cleaned.ok) return this.resultFailure(cleaned.reason, cleaned.mode);
    this.emitChange({ key: `${this.key}:owner`, generation: 0, action: "cleared", external: false });
    return { ok: true, removed: cleaned.value, mode: cleaned.mode, online_only_risk: this.onlineOnlyRiskState };
  }

  public subscribe(listener: DraftChangeListener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  public dispose(): void {
    activeCrtCoordinators.delete(this);
    this.editLockRelease?.();
    this.editLockRelease = undefined;
    this.broadcast?.removeEventListener("message", this.onBroadcast);
    this.broadcast?.close?.();
    this.unsubscribeStorage?.();
    this.listeners.clear();
  }
}

export function createCrtDraftCoordinator(options: CrtDraftCoordinatorOptions): CrtDraftCoordinator {
  return new CrtDraftCoordinator(options);
}

export type CrtOwnerCleanupResult =
  | Readonly<{ ok: true; removed: number }>
  | Readonly<{ ok: false; reason: "cleanup-failed" | "transition-cancelled" }>;

const activeCrtCoordinators = new Set<CrtDraftCoordinator>();

/**
 * Complete the browser-local part of an authenticated owner transition.
 *
 * This is deliberately owned by the CRT boundary rather than by a page. A
 * logout or account deletion can happen after the canvas has unmounted, while
 * pre-canonical drafts and drafts for other trees still need to be removed.
 * The cleanup is fail-closed: a storage/read-back failure leaves the session
 * in place so the caller cannot claim that the departing owner's bytes were
 * cleared.
 */
export async function cleanupCrtOwnerScope(ownerId: string, origin = globalThis.location?.origin ?? ""): Promise<CrtOwnerCleanupResult> {
  const normalizedOrigin = normalizeOrigin(origin);
  if (!ownerId || !normalizedOrigin) return { ok: false, reason: "cleanup-failed" };
  const active = [...activeCrtCoordinators].filter((coordinator) => {
    const scope = coordinator.activeScope;
    return scope.owner_id === ownerId && scope.origin === normalizedOrigin;
  });
  const scanner = createCrtDraftCoordinator({ owner_id: ownerId, origin: normalizedOrigin, tree_id: null });
  try {
    const listed = await scanner.enumerateOwnerDrafts();
    if (!listed.ok) return { ok: false, reason: "cleanup-failed" };
    const hasPendingWork = listed.value.length > 0 || active.some((coordinator) => coordinator.hasPendingDraft());
    if (!hasPendingWork) {
      active.forEach((coordinator) => coordinator.dispose());
      return { ok: true, removed: 0 };
    }
    if (typeof globalThis.window?.confirm !== "function") {
      return { ok: false, reason: "cleanup-failed" };
    }
    if (!globalThis.window.confirm(CRT_ONLINE_ONLY_LOSS_MESSAGE)) {
      return { ok: false, reason: "transition-cancelled" };
    }
    // Keep active coordinators registered until every coordinator-local draft
    // has been discarded and the owner-wide deletion has verified every
    // durable key. If cleanup fails, the canvas must retain its loss barrier
    // and the user must be able to retry instead of losing the only
    // protection around an unresolved draft.
    let removed = 0;
    for (const coordinator of active) {
      let coordinatorCleanup: Awaited<ReturnType<CrtDraftCoordinator["discardOwnerDrafts"]>>;
      try {
        coordinatorCleanup = await coordinator.discardOwnerDrafts();
      } catch {
        return { ok: false, reason: "cleanup-failed" };
      }
      if (!coordinatorCleanup.ok) return { ok: false, reason: "cleanup-failed" };
      removed += coordinatorCleanup.removed;
    }
    const cleaned = await scanner.cleanupAccountScope();
    if (!cleaned.ok) return { ok: false, reason: "cleanup-failed" };
    active.forEach((coordinator) => coordinator.dispose());
    return { ok: true, removed: removed + cleaned.removed };
  } finally {
    scanner.dispose();
  }
}
