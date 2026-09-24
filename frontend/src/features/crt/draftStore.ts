export const CRT_DRAFT_SCHEMA_VERSION = 1;
export const CRT_DRAFT_RETENTION_MS = 30 * 24 * 60 * 60 * 1000;
const DRAFT_KEY_PREFIX = "bb.crt.draft.v1";
const UUID_LIKE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const ISO_UTC = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?Z$/;

export interface DraftStorage {
  readonly length: number;
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
  removeItem(key: string): void;
  key(index: number): string | null;
}

export interface DraftClock { now(): number; }

export interface DraftOwnerScope { owner_id: string; origin: string; }

export interface DraftScope extends DraftOwnerScope {
  tree_id?: string | null;
  create_idempotency_key?: string | null;
}

export interface DraftListing {
  value: PendingDraftEnvelope;
  stale: boolean;
  requires_backup_confirmation: boolean;
}

export interface DraftTree {
  name: string;
  nodes: readonly unknown[];
  relations: readonly unknown[];
  layout?: unknown;
}

export type DraftOperationKind =
  | "card-create"
  | "label-edit"
  | "card-move"
  | "relation-create"
  | "relation-delete"
  | "card-delete"
  | "tree-rename"
  | "layout-change";

export type DraftOperationSummary = Readonly<{
  id: string;
  kind: DraftOperationKind;
  entity_id?: string;
  field?: "label" | "position" | "name" | "layout";
}>;

export type DraftInFlightSave = Readonly<{
  idempotency_key: string;
  base_revision: number | null;
  generation: number;
  snapshot: DraftTree;
  hash: string;
  /** Exact request body used by the keyed mutation; optional for pre-fix drafts. */
  request_payload?: Readonly<Record<string, unknown>>;
}>;

export type DraftQueuedCommand =
  | Readonly<{ id: string; kind: "card-create"; payload: { node_id: string; label: string; position: { x: number; y: number } } }>
  | Readonly<{ id: string; kind: "label-edit"; payload: { node_id: string; label: string } }>
  | Readonly<{ id: string; kind: "card-move"; payload: { node_id: string; position: { x: number; y: number } } }>
  | Readonly<{ id: string; kind: "relation-create"; payload: { relation_id: string; source_node_id: string; target_node_id: string } }>
  | Readonly<{ id: string; kind: "relation-delete"; payload: { relation_id: string } }>
  | Readonly<{ id: string; kind: "card-delete"; payload: { node_id: string; confirmed: true } }>
  | Readonly<{ id: string; kind: "tree-rename"; payload: { name: string } }>
  | Readonly<{ id: string; kind: "layout-change"; payload: { layout: { center: { x: number; y: number }; zoom: number } } }>;

export interface DraftWriteInput {
  tree: DraftTree;
  create_idempotency_key?: string | null;
  base_revision?: number | null;
  base_updated_at?: string | null;
  dirty_operations?: readonly DraftOperationSummary[];
  in_flight_save?: DraftInFlightSave | null;
  queued_commands?: readonly DraftQueuedCommand[];
  migration_id?: string;
  migration_fingerprint?: string;
  migration_source_create_idempotency_key?: string;
  migration_hash_algorithm?: "sha-256";
  migration_hash_version?: 1;
}

export interface PendingDraftEnvelope {
  schema_version: 1;
  owner_id: string;
  origin: string;
  tree_id: string | null;
  create_idempotency_key: string | null;
  base_revision: number | null;
  base_updated_at: string | null;
  local_updated_at: string;
  writer_session_id: string;
  generation: number;
  tree: DraftTree;
  dirty_operations: readonly DraftOperationSummary[];
  in_flight_save: DraftInFlightSave | null;
  queued_commands: readonly DraftQueuedCommand[];
  digest_algorithm: "sha-256";
  digest_version: 1;
  migration_id?: string;
  migration_fingerprint?: string;
  migration_source_create_idempotency_key?: string;
  migration_hash_algorithm?: "sha-256";
  migration_hash_version?: 1;
}

export type DraftMode = "durable" | "online-only";
export type DraftFailureReason =
  | "storage-unavailable"
  | "invalid-draft"
  | "invalid-schema"
  | "invalid-json"
  | "stale-generation"
  | "not-found"
  | "rekey-conflict"
  | "cleanup-failed"
  | "writer-denied";

export type DraftResult<T> =
  | { ok: true; value: T; mode: DraftMode }
  | { ok: false; reason: DraftFailureReason; mode: DraftMode; raw?: string };

export type DraftReadResult =
  | { ok: true; found: false; mode: DraftMode }
  | { ok: true; found: true; value: PendingDraftEnvelope; stale: boolean; requires_backup_confirmation: boolean; mode: DraftMode }
  | { ok: false; reason: DraftFailureReason; mode: DraftMode; raw?: string };

export interface DraftLockManager {
  request<T>(
    name: string,
    options: { mode: "shared" | "exclusive"; ifAvailable: true },
    callback: (lock: { name: string } | null) => T | Promise<T>
  ): Promise<T>;
}

export interface DraftCrypto {
  subtle: {
    digest(algorithm: "SHA-256", data: ArrayBuffer): Promise<ArrayBuffer>;
  };
}

export interface DraftStoreDependencies {
  storage?: DraftStorage | null;
  clock?: DraftClock;
  writer_session_id?: string;
  lock_manager?: DraftLockManager | null;
  crypto?: DraftCrypto | null;
}

export interface DraftGenerationToken { readonly key: string; readonly generation: number; }

export type DraftWriterResult<T> =
  | { ok: true; value: T; mode: "web-lock" | "in-memory-fallback" }
  | { ok: false; reason: "writer-denied" | "lock-unavailable"; mode: "in-memory-fallback" | "web-lock" };

export type DraftWriteOptions = Readonly<{ expected_generation?: number; token?: DraftGenerationToken }>;

type StorageState = "absent" | "available" | "failed";
type ParsedRaw =
  | { ok: true; value: PendingDraftEnvelope }
  | { ok: false; result: { ok: false; reason: DraftFailureReason; mode: DraftMode; raw?: string } };

let probeSequence = 0;
let sessionSequence = 0;
const defaultClock: DraftClock = { now: () => Date.now() };

function defaultWriterSessionId(): string {
  const cryptoApi = (globalThis as { crypto?: { randomUUID?: () => string } }).crypto;
  if (cryptoApi?.randomUUID) return cryptoApi.randomUUID();
  sessionSequence += 1;
  return `00000000-0000-4000-8000-${String(sessionSequence).padStart(12, "0")}`;
}

function defaultLockManager(): DraftLockManager | null {
  return (globalThis as { navigator?: { locks?: DraftLockManager } }).navigator?.locks ?? null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isUuidLike(value: unknown): value is string {
  return typeof value === "string" && UUID_LIKE.test(value);
}

function isTimestamp(value: unknown): value is string {
  if (typeof value !== "string" || !ISO_UTC.test(value)) return false;
  const parsed = Date.parse(value);
  if (!Number.isFinite(parsed)) return false;
  const fraction = /\.(\d{1,9})Z$/.exec(value)?.[1];
  const canonical = fraction
    ? `${value.slice(0, -(fraction.length + 2))}.${fraction.slice(0, 3).padEnd(3, "0")}Z`
    : `${value.slice(0, -1)}.000Z`;
  return new Date(parsed).toISOString() === canonical;
}

function isFiniteJson(value: unknown): boolean {
  if (typeof value === "number") return Number.isFinite(value);
  if (Array.isArray(value)) return value.every(isFiniteJson);
  if (isRecord(value)) return Object.values(value).every(isFiniteJson);
  return value === null || typeof value === "string" || typeof value === "boolean";
}

function hasExactKeys(value: Record<string, unknown>, keys: readonly string[]): boolean {
  const expected = new Set(keys);
  return Object.keys(value).every((key) => expected.has(key)) && keys.every((key) => key in value);
}

function validPoint(value: unknown): value is { x: number; y: number } {
  return isRecord(value) && hasExactKeys(value, ["x", "y"]) &&
    typeof value.x === "number" && Number.isFinite(value.x) &&
    typeof value.y === "number" && Number.isFinite(value.y);
}

function validNode(value: unknown): value is Record<string, unknown> {
  if (!isRecord(value) || !hasExactKeys(value, ["id", "label", "type", "position", "highlight_state", "relation_counts"]) ||
      typeof value.id !== "string" || value.id.length === 0 || typeof value.label !== "string" ||
      value.label.trim().length === 0 || (value.type !== "parent" && value.type !== "child") ||
      (value.highlight_state !== "none" && value.highlight_state !== "cause_candidate" && value.highlight_state !== "effect_spanning") ||
      !validPoint(value.position) || !isRecord(value.relation_counts) ||
      !hasExactKeys(value.relation_counts, ["up_count", "down_count"])) return false;
  const counts = value.relation_counts;
  return typeof counts.up_count === "number" && Number.isInteger(counts.up_count) && counts.up_count >= 0 &&
    typeof counts.down_count === "number" && Number.isInteger(counts.down_count) && counts.down_count >= 0 &&
    isFiniteJson(value);
}

function validRelation(value: unknown): value is Record<string, unknown> {
  if (!isRecord(value) || !hasExactKeys(value, ["id", "source_node_id", "target_node_id", "kind", "created_at"]) ||
      typeof value.id !== "string" || value.id.length === 0 || typeof value.source_node_id !== "string" ||
      value.source_node_id.length === 0 || typeof value.target_node_id !== "string" || value.target_node_id.length === 0 ||
      value.kind !== "why" || !isTimestamp(value.created_at)) return false;
  return isFiniteJson(value);
}

function validGraph(nodes: readonly unknown[], relations: readonly unknown[]): boolean {
  const nodeIds = new Set<string>();
  for (const node of nodes) {
    if (!validNode(node) || typeof node.id !== "string" || nodeIds.has(node.id)) return false;
    nodeIds.add(node.id);
  }
  const relationIds = new Set<string>();
  const pairs = new Set<string>();
  const adjacency = new Map<string, string[]>();
  for (const relation of relations) {
    if (!validRelation(relation) || typeof relation.id !== "string" ||
        typeof relation.source_node_id !== "string" || typeof relation.target_node_id !== "string" ||
        relationIds.has(relation.id) || !nodeIds.has(relation.source_node_id) ||
        !nodeIds.has(relation.target_node_id) || relation.source_node_id === relation.target_node_id) return false;
    const pair = `${relation.source_node_id}\u0000${relation.target_node_id}`;
    if (pairs.has(pair)) return false;
    relationIds.add(relation.id);
    pairs.add(pair);
    const outgoing = adjacency.get(relation.source_node_id) ?? [];
    outgoing.push(relation.target_node_id);
    adjacency.set(relation.source_node_id, outgoing);
  }
  const visiting = new Set<string>();
  const visited = new Set<string>();
  const visit = (nodeId: string): boolean => {
    if (visiting.has(nodeId)) return false;
    if (visited.has(nodeId)) return true;
    visiting.add(nodeId);
    for (const target of adjacency.get(nodeId) ?? []) if (!visit(target)) return false;
    visiting.delete(nodeId);
    visited.add(nodeId);
    return true;
  };
  return [...nodeIds].every(visit);
}

function validTree(value: unknown): value is DraftTree {
  return isRecord(value) && typeof value.name === "string" && value.name.trim().length > 0 &&
    Array.isArray(value.nodes) && Array.isArray(value.relations) && validGraph(value.nodes, value.relations) &&
    (value.layout === undefined || value.layout === null || (isRecord(value.layout) && isFiniteJson(value.layout)));
}

function isNullableTimestamp(value: unknown): value is string | null {
  return value === null || isTimestamp(value);
}

function validOperationSummary(value: unknown): value is DraftOperationSummary {
  if (!isRecord(value) || !hasExactKeys(value, ["id", "kind", ...(value.entity_id !== undefined ? ["entity_id"] : []), ...(value.field !== undefined ? ["field"] : [])]) ||
      !isUuidLike(value.id) || typeof value.kind !== "string" ||
      !(["card-create", "label-edit", "card-move", "relation-create", "relation-delete", "card-delete", "tree-rename", "layout-change"] as string[]).includes(value.kind) ||
      (value.entity_id !== undefined && (typeof value.entity_id !== "string" || value.entity_id.length === 0)) ||
      (value.field !== undefined && (typeof value.field !== "string" || !(["label", "position", "name", "layout"] as string[]).includes(value.field)))) return false;
  return true;
}

function validInFlightSave(value: unknown): value is DraftInFlightSave {
  return isRecord(value) && hasExactKeys(value, ["idempotency_key", "base_revision", "generation", "snapshot", "hash", ...(value.request_payload === undefined ? [] : ["request_payload"])]) &&
    isUuidLike(value.idempotency_key) &&
    (value.base_revision === null || (typeof value.base_revision === "number" && Number.isInteger(value.base_revision) && value.base_revision >= 0)) &&
    typeof value.generation === "number" && Number.isInteger(value.generation) && value.generation >= 1 &&
    validTree(value.snapshot) && typeof value.hash === "string" && /^[0-9a-f]{64}$/i.test(value.hash) &&
    (value.request_payload === undefined || (isRecord(value.request_payload) && isFiniteJson(value.request_payload)));
}

function validCommandPayload(kind: string, payload: unknown): boolean {
  if (!isRecord(payload)) return false;
  switch (kind) {
    case "card-create": return hasExactKeys(payload, ["node_id", "label", "position"]) && typeof payload.node_id === "string" &&
      typeof payload.label === "string" && payload.label.trim().length > 0 && validPoint(payload.position);
    case "label-edit": return hasExactKeys(payload, ["node_id", "label"]) && typeof payload.node_id === "string" &&
      typeof payload.label === "string" && payload.label.trim().length > 0;
    case "card-move": return hasExactKeys(payload, ["node_id", "position"]) && typeof payload.node_id === "string" && validPoint(payload.position);
    case "relation-create": return hasExactKeys(payload, ["relation_id", "source_node_id", "target_node_id"]) &&
      typeof payload.relation_id === "string" && typeof payload.source_node_id === "string" && typeof payload.target_node_id === "string" &&
      payload.source_node_id !== payload.target_node_id;
    case "relation-delete": return hasExactKeys(payload, ["relation_id"]) && typeof payload.relation_id === "string";
    case "card-delete": return hasExactKeys(payload, ["node_id", "confirmed"]) && typeof payload.node_id === "string" && payload.confirmed === true;
    case "tree-rename": return hasExactKeys(payload, ["name"]) && typeof payload.name === "string" && payload.name.trim().length > 0;
    case "layout-change": return hasExactKeys(payload, ["layout"]) && isRecord(payload.layout) && hasExactKeys(payload.layout, ["center", "zoom"]) &&
      validPoint(payload.layout.center) && typeof payload.layout.zoom === "number" && Number.isFinite(payload.layout.zoom);
    default: return false;
  }
}

function validQueuedCommand(value: unknown): value is DraftQueuedCommand {
  return isRecord(value) && hasExactKeys(value, ["id", "kind", "payload"]) && isUuidLike(value.id) &&
    typeof value.kind === "string" && validCommandPayload(value.kind, value.payload);
}

function validEnvelope(value: unknown): value is PendingDraftEnvelope {
  if (!isRecord(value)) return false;
  const treeId = value.tree_id;
  const createKey = value.create_idempotency_key;
  const canonical = typeof treeId === "string" && treeId.length > 0;
  const preCanonical = treeId === null;
  const hasMigration = value.migration_id !== undefined;
  const migrationFieldsPresent = [value.migration_fingerprint, value.migration_source_create_idempotency_key, value.migration_hash_algorithm, value.migration_hash_version]
    .some((field) => field !== undefined);
  return value.schema_version === CRT_DRAFT_SCHEMA_VERSION &&
    typeof value.owner_id === "string" && value.owner_id.length > 0 &&
    typeof value.origin === "string" && normalizeOrigin(value.origin) === value.origin &&
    (canonical || preCanonical) &&
    (preCanonical ? isUuidLike(createKey) : createKey === null || isUuidLike(createKey)) &&
    (value.base_revision === null || (typeof value.base_revision === "number" && Number.isInteger(value.base_revision) && value.base_revision >= 0)) &&
    isNullableTimestamp(value.base_updated_at) && isTimestamp(value.local_updated_at) && isUuidLike(value.writer_session_id) &&
    typeof value.generation === "number" && Number.isInteger(value.generation) && value.generation >= 1 && validTree(value.tree) &&
    value.digest_algorithm === "sha-256" && value.digest_version === 1 &&
    Array.isArray(value.dirty_operations) && value.dirty_operations.length <= 100 && value.dirty_operations.every(validOperationSummary) &&
    (value.in_flight_save === null || validInFlightSave(value.in_flight_save)) &&
    Array.isArray(value.queued_commands) && value.queued_commands.length <= 100 && value.queued_commands.every(validQueuedCommand) &&
    (!hasMigration ? !migrationFieldsPresent : canonical && isUuidLike(value.migration_id) &&
      typeof value.migration_fingerprint === "string" && /^[0-9a-f]{64}$/i.test(value.migration_fingerprint) &&
      isUuidLike(value.migration_source_create_idempotency_key) && value.migration_hash_algorithm === "sha-256" && value.migration_hash_version === 1);
}

export function validateDraftEnvelope(value: unknown):
  | { ok: true; value: PendingDraftEnvelope }
  | { ok: false; reason: "invalid-schema" | "invalid-draft" } {
  if (!isRecord(value) || value.schema_version !== CRT_DRAFT_SCHEMA_VERSION) return { ok: false, reason: "invalid-schema" };
  return validEnvelope(value) ? { ok: true, value } : { ok: false, reason: "invalid-draft" };
}

function clone<T>(value: T): T { return JSON.parse(JSON.stringify(value)) as T; }

function utf8(value: string): Uint8Array { return new TextEncoder().encode(value); }

function base64UrlEncode(value: string): string {
  const bytes = utf8(value);
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
}

function base64UrlDecode(value: string): string | null {
  try {
    const binary = atob(value.replace(/-/g, "+").replace(/_/g, "/") + "=".repeat((4 - value.length % 4) % 4));
    return new TextDecoder().decode(Uint8Array.from(binary, (char) => char.charCodeAt(0)));
  } catch { return null; }
}

function encodeKeyPart(value: string): string {
  return `${utf8(value).byteLength}-${base64UrlEncode(value)}`;
}

function decodeKeyPart(value: string): string | null {
  const match = /^(\d+)-([A-Za-z0-9_-]+)$/.exec(value);
  if (!match) return null;
  const decoded = base64UrlDecode(match[2]);
  return decoded !== null && utf8(decoded).byteLength === Number(match[1]) ? decoded : null;
}

export function normalizeOrigin(origin: string): string {
  try {
    const parsed = new URL(origin);
    if (parsed.protocol !== "http:" && parsed.protocol !== "https:") return "";
    return parsed.origin === "null" ? "" : parsed.origin;
  } catch { return ""; }
}

function scopeKey(scope: DraftScope): string {
  const origin = normalizeOrigin(scope.origin);
  const owner = scope.owner_id;
  const tree = scope.tree_id ?? null;
  const createKey = scope.create_idempotency_key ?? null;
  if (!owner || !origin || (tree === null && !isUuidLike(createKey)) || (tree !== null && tree.length === 0)) return "";
  const identity = tree === null ? `create:${createKey}` : `tree:${tree}`;
  return `${DRAFT_KEY_PREFIX}.${encodeKeyPart(origin)}.${encodeKeyPart(owner)}.${encodeKeyPart(identity)}`;
}

export function draftStorageKey(scope: DraftScope): string { return scopeKey(scope); }

function ownerPrefix(scope: DraftOwnerScope): string {
  const origin = normalizeOrigin(scope.origin);
  if (!origin || !scope.owner_id) return "";
  return `${DRAFT_KEY_PREFIX}.${encodeKeyPart(origin)}.${encodeKeyPart(scope.owner_id)}.`;
}

function physicalScope(key: string): DraftScope | null {
  const prefix = `${DRAFT_KEY_PREFIX}.`;
  if (!key.startsWith(prefix)) return null;
  const parts = key.slice(prefix.length).split(".");
  if (parts.length !== 3) return null;
  const origin = decodeKeyPart(parts[0]);
  const owner = decodeKeyPart(parts[1]);
  const identity = decodeKeyPart(parts[2]);
  if (!origin || !owner || !identity || normalizeOrigin(origin) !== origin) return null;
  if (identity.startsWith("tree:") && identity.length > 5) return { owner_id: owner, origin, tree_id: identity.slice(5) };
  if (identity.startsWith("create:") && isUuidLike(identity.slice(7))) return { owner_id: owner, origin, tree_id: null, create_idempotency_key: identity.slice(7) };
  return null;
}

function localUpdatedAt(clock: DraftClock): string { return new Date(clock.now()).toISOString(); }

function stableJson(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(stableJson).join(",")}]`;
  if (isRecord(value)) return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${stableJson(value[key])}`).join(",")}}`;
  return JSON.stringify(value);
}

function digestHex(buffer: ArrayBuffer): string {
  return [...new Uint8Array(buffer)].map((byte) => byte.toString(16).padStart(2, "0")).join("");
}

async function fingerprint(envelope: PendingDraftEnvelope, cryptoApi: DraftCrypto): Promise<string> {
  const content = stableJson({
    owner_id: envelope.owner_id,
    origin: envelope.origin,
    create_idempotency_key: envelope.create_idempotency_key,
    base_revision: envelope.base_revision,
    base_updated_at: envelope.base_updated_at,
    local_updated_at: envelope.local_updated_at,
    generation: envelope.generation,
    tree: envelope.tree,
    dirty_operations: envelope.dirty_operations,
    in_flight_save: envelope.in_flight_save,
    queued_commands: envelope.queued_commands
  });
  return digestHex(await cryptoApi.subtle.digest("SHA-256", utf8(content).slice().buffer));
}

function unavailableResult<T>(): DraftResult<T> { return { ok: false, reason: "storage-unavailable", mode: "online-only" }; }

function defaultCrypto(): DraftCrypto | null {
  const cryptoApi = (globalThis as { crypto?: DraftCrypto }).crypto;
  return cryptoApi?.subtle ? cryptoApi : null;
}

export function createCrtDraftStore(dependencies: DraftStoreDependencies): CrtDraftStore { return new CrtDraftStore(dependencies); }

export class CrtDraftStore {
  private readonly storage: DraftStorage | null;
  private readonly clock: DraftClock;
  private readonly writerSessionId: string;
  private readonly lockManager: DraftLockManager | null;
  private readonly crypto: DraftCrypto | null;
  private readonly memory = new Map<string, string>();
  private readonly memoryOnlyKeys = new Set<string>();
  private readonly deletionTombstones = new Set<string>();
  private readonly activeScopeKeys = new Set<string>();
  private readonly fallbackHeldKeys = new Set<string>();
  private readonly fallbackOwnerReaders = new Map<string, number>();
  private readonly fallbackOwnerExclusive = new Set<string>();
  private storageState: StorageState = "absent";

  public constructor(dependencies: DraftStoreDependencies) {
    this.storage = dependencies.storage ?? null;
    this.clock = dependencies.clock ?? defaultClock;
    this.writerSessionId = dependencies.writer_session_id ?? defaultWriterSessionId();
    this.lockManager = dependencies.lock_manager === undefined ? defaultLockManager() : dependencies.lock_manager;
    this.crypto = dependencies.crypto === undefined ? defaultCrypto() : dependencies.crypto;
    this.probeStorage();
  }

  public probeStorage(): boolean {
    if (!this.storage) { this.storageState = "absent"; return false; }
    const key = `${DRAFT_KEY_PREFIX}.probe.${probeSequence += 1}`;
    let available = false;
    try {
      this.storage.setItem(key, "1");
      if (this.storage.getItem(key) !== "1") throw new Error("probe read mismatch");
      this.storage.removeItem(key);
      if (this.storage.getItem(key) !== null) throw new Error("probe cleanup mismatch");
      available = true;
    } catch {
      try {
        this.storage.removeItem(key);
        if (this.storage.getItem(key) !== null) available = false;
      } catch { available = false; }
    }
    if (available && !this.flushDeletionTombstones()) available = false;
    if (this.memoryOnlyKeys.size > 0) available = false;
    this.storageState = available ? "available" : "failed";
    return available;
  }

  private flushDeletionTombstones(): boolean {
    if (!this.storage) return this.deletionTombstones.size === 0;
    for (const key of [...this.deletionTombstones].sort()) {
      try {
        this.storage.removeItem(key);
        if (this.storage.getItem(key) !== null) return false;
      } catch {
        return false;
      }
      this.deletionTombstones.delete(key);
    }
    return true;
  }

  public get mode(): DraftMode {
    return this.storageState === "available" && this.storage !== null && this.lockManager !== null ? "durable" : "online-only";
  }

  private mutationAllowed(key: string): DraftResult<never> | null {
    if (!key || !this.activeScopeKeys.has(key)) {
      return { ok: false, reason: "writer-denied", mode: this.mode };
    }
    return null;
  }

  private fallbackAcquireShared(ownerKey: string): boolean {
    if (this.fallbackOwnerExclusive.has(ownerKey)) return false;
    this.fallbackOwnerReaders.set(ownerKey, (this.fallbackOwnerReaders.get(ownerKey) ?? 0) + 1);
    return true;
  }

  private fallbackReleaseShared(ownerKey: string): void {
    const readers = this.fallbackOwnerReaders.get(ownerKey) ?? 0;
    if (readers <= 1) this.fallbackOwnerReaders.delete(ownerKey);
    else this.fallbackOwnerReaders.set(ownerKey, readers - 1);
  }

  private fallbackAcquireExclusive(ownerKey: string): boolean {
    if (this.fallbackOwnerExclusive.has(ownerKey) || (this.fallbackOwnerReaders.get(ownerKey) ?? 0) > 0) return false;
    this.fallbackOwnerExclusive.add(ownerKey);
    return true;
  }

  private fallbackReleaseExclusive(ownerKey: string): void {
    this.fallbackOwnerExclusive.delete(ownerKey);
  }

  private markStorageFailed(): void {
    this.storageState = this.storage ? "failed" : "absent";
    for (const key of this.memory.keys()) this.memoryOnlyKeys.add(key);
  }

  private invalidatePhysicalKey(key: string): void {
    if (!this.storage) return;
    try {
      this.storage.removeItem(key);
      if (this.storage.getItem(key) !== null) this.markStorageFailed();
    } catch {
      this.markStorageFailed();
    }
  }

  public write(scope: DraftScope, input: DraftWriteInput, options: DraftWriteOptions = {}): DraftResult<PendingDraftEnvelope> {
    const key = scopeKey(scope);
    if (!key) return { ok: false, reason: "invalid-draft", mode: this.mode };
    const denied = this.mutationAllowed(key);
    if (denied) return denied;
    if (scope.tree_id == null && input.create_idempotency_key !== undefined && input.create_idempotency_key !== scope.create_idempotency_key) {
      return { ok: false, reason: "invalid-draft", mode: this.mode };
    }
    if (!isUuidLike(this.writerSessionId)) return { ok: false, reason: "invalid-draft", mode: this.mode };
    const current = this.readRaw(key);
    const currentEnvelope = current.raw === null ? null : this.parseRaw(current.raw, key);
    if (currentEnvelope && !currentEnvelope.ok) return currentEnvelope.result;
    const currentGeneration = currentEnvelope?.ok ? currentEnvelope.value.generation : 0;
    const expected = options.token?.generation ?? options.expected_generation;
    if (options.token?.key !== undefined && options.token.key !== key) return { ok: false, reason: "stale-generation", mode: this.mode };
    if (expected !== undefined && expected !== currentGeneration) return { ok: false, reason: "stale-generation", mode: this.mode };
    const inputMigration = {
      migration_id: input.migration_id,
      migration_fingerprint: input.migration_fingerprint,
      migration_source_create_idempotency_key: input.migration_source_create_idempotency_key,
      migration_hash_algorithm: input.migration_hash_algorithm,
      migration_hash_version: input.migration_hash_version
    };
    const inputMigrationSupplied = Object.values(inputMigration).some((field) => field !== undefined);
    const currentMigration = currentEnvelope?.ok && currentEnvelope.value.migration_id !== undefined
      ? {
        migration_id: currentEnvelope.value.migration_id,
        migration_fingerprint: currentEnvelope.value.migration_fingerprint,
        migration_source_create_idempotency_key: currentEnvelope.value.migration_source_create_idempotency_key,
        migration_hash_algorithm: currentEnvelope.value.migration_hash_algorithm,
        migration_hash_version: currentEnvelope.value.migration_hash_version
      }
      : null;
    if (currentMigration && inputMigrationSupplied && Object.keys(currentMigration).some((field) =>
      inputMigration[field as keyof typeof inputMigration] !== currentMigration[field as keyof typeof currentMigration])) {
      return { ok: false, reason: "rekey-conflict", mode: this.mode };
    }
    const migration = currentMigration ?? (inputMigrationSupplied ? inputMigration : {});
    let envelope: PendingDraftEnvelope;
    try {
      envelope = clone({
        schema_version: CRT_DRAFT_SCHEMA_VERSION,
        owner_id: scope.owner_id,
        origin: normalizeOrigin(scope.origin),
        tree_id: scope.tree_id ?? null,
        create_idempotency_key: input.create_idempotency_key ?? scope.create_idempotency_key ?? null,
        base_revision: input.base_revision ?? null,
        base_updated_at: input.base_updated_at ?? null,
        local_updated_at: localUpdatedAt(this.clock),
        writer_session_id: this.writerSessionId,
        generation: currentGeneration + 1,
        tree: input.tree,
        dirty_operations: input.dirty_operations ? [...input.dirty_operations] : [],
        in_flight_save: input.in_flight_save ?? null,
        queued_commands: input.queued_commands ? [...input.queued_commands] : [],
        digest_algorithm: "sha-256",
        digest_version: 1,
        ...migration
      });
    } catch { return { ok: false, reason: "invalid-draft", mode: this.mode }; }
    if (!validEnvelope(envelope)) return { ok: false, reason: "invalid-draft", mode: this.mode };
    const serialized = JSON.stringify(envelope);
    if (this.mode === "durable" && this.storage) {
      try {
        this.storage.setItem(key, serialized);
        if (this.storage.getItem(key) !== serialized) throw new Error("write readback mismatch");
        this.memory.set(key, serialized);
        this.memoryOnlyKeys.delete(key);
        this.deletionTombstones.delete(key);
        return { ok: true, value: envelope, mode: "durable" };
      } catch {
        this.markStorageFailed();
        this.invalidatePhysicalKey(key);
        this.memory.set(key, serialized);
        this.memoryOnlyKeys.add(key);
        return { ok: true, value: envelope, mode: "online-only" };
      }
    }
    this.memory.set(key, serialized);
    this.memoryOnlyKeys.add(key);
    return { ok: true, value: envelope, mode: "online-only" };
  }

  public read(scope: DraftScope): DraftReadResult {
    const key = scopeKey(scope);
    if (!key) return { ok: false, reason: "invalid-draft", mode: this.mode };
    const rawResult = this.readRaw(key);
    if (rawResult.raw === null) return { ok: true, found: false, mode: rawResult.mode };
    const parsed = this.parseRaw(rawResult.raw, key);
    if (!parsed.ok) return parsed.result;
    const envelope = parsed.value;
    if (envelope.owner_id !== scope.owner_id || envelope.origin !== normalizeOrigin(scope.origin) ||
        envelope.tree_id !== (scope.tree_id ?? null) ||
        (scope.tree_id == null && envelope.create_idempotency_key !== (scope.create_idempotency_key ?? null))) {
      return { ok: true, found: false, mode: rawResult.mode };
    }
    const stale = this.clock.now() - Date.parse(envelope.local_updated_at) >= CRT_DRAFT_RETENTION_MS;
    return { ok: true, found: true, value: envelope, stale, requires_backup_confirmation: stale, mode: rawResult.mode };
  }

  public async withWriter<T>(scope: DraftScope, operation: () => T | Promise<T>): Promise<DraftWriterResult<T>> {
    const key = scopeKey(scope);
    if (!key) return { ok: false, reason: "writer-denied", mode: "in-memory-fallback" };
    const ownerKey = ownerPrefix(scope);
    const ownerLockName = `${DRAFT_KEY_PREFIX}.owner.${ownerKey}`;
    const lockName = `${DRAFT_KEY_PREFIX}.writer.${key}`;
    const run = async (mode: "web-lock" | "in-memory-fallback"): Promise<DraftWriterResult<T>> => {
      this.activeScopeKeys.add(key);
      try { return { ok: true, value: await operation(), mode }; }
      finally { this.activeScopeKeys.delete(key); }
    };
    const lockManager = this.lockManager;
    if (!lockManager) {
      if (!this.fallbackAcquireShared(ownerKey)) return { ok: false, reason: "writer-denied", mode: "in-memory-fallback" };
      if (this.fallbackHeldKeys.has(key)) {
        this.fallbackReleaseShared(ownerKey);
        return { ok: false, reason: "writer-denied", mode: "in-memory-fallback" };
      }
      this.fallbackHeldKeys.add(key);
      try { return await run("in-memory-fallback"); }
      finally {
        this.fallbackHeldKeys.delete(key);
        this.fallbackReleaseShared(ownerKey);
      }
    }
    let operationStarted = false;
    try {
      return await lockManager.request(ownerLockName, { mode: "shared", ifAvailable: true }, async (ownerLock) => {
        if (!ownerLock) return { ok: false, reason: "writer-denied", mode: "web-lock" };
        return lockManager.request(lockName, { mode: "exclusive", ifAvailable: true }, async (lock) => {
          if (!lock) return { ok: false, reason: "writer-denied", mode: "web-lock" };
          operationStarted = true;
          return run("web-lock");
        });
      });
    } catch (error) {
      if (operationStarted) throw error;
      return { ok: false, reason: "lock-unavailable", mode: "web-lock" };
    }
  }

  private async withRekeyLocks(
    ownerKey: string,
    sourceKey: string,
    canonicalKey: string,
    operation: () => Promise<DraftResult<PendingDraftEnvelope>>
  ): Promise<DraftResult<PendingDraftEnvelope>> {
    const denied = (): DraftResult<PendingDraftEnvelope> => ({ ok: false, reason: "rekey-conflict", mode: this.mode });
    const exactKeys = [sourceKey, canonicalKey].sort();
    const lockManager = this.lockManager;
    if (!lockManager) {
      if (!this.fallbackAcquireShared(ownerKey)) return denied();
      if (exactKeys.some((key) => this.fallbackHeldKeys.has(key))) {
        this.fallbackReleaseShared(ownerKey);
        return denied();
      }
      exactKeys.forEach((key) => this.fallbackHeldKeys.add(key));
      try { return await operation(); }
      finally {
        exactKeys.forEach((key) => this.fallbackHeldKeys.delete(key));
        this.fallbackReleaseShared(ownerKey);
      }
    }
    const requestExact = async (index: number): Promise<DraftResult<PendingDraftEnvelope>> => {
      if (index >= exactKeys.length) return operation();
      try {
        return await lockManager.request(`${DRAFT_KEY_PREFIX}.writer.${exactKeys[index]}`, { mode: "exclusive", ifAvailable: true }, async (lock) => {
          if (!lock) return denied();
          return requestExact(index + 1);
        });
      } catch { return denied(); }
    };
    try {
      return await lockManager.request(`${DRAFT_KEY_PREFIX}.owner.${ownerKey}`, { mode: "shared", ifAvailable: true }, async (ownerLock) => {
        if (!ownerLock) return denied();
        return requestExact(0);
      });
    } catch { return denied(); }
  }

  public async rekeyPreCanonical(sourceScope: DraftScope, canonicalTreeId: string, migrationId: string): Promise<DraftResult<PendingDraftEnvelope>> {
    const sourceKey = scopeKey(sourceScope);
    if (sourceScope.tree_id !== null && sourceScope.tree_id !== undefined || !canonicalTreeId || !isUuidLike(migrationId)) {
      return { ok: false, reason: "invalid-draft", mode: this.mode };
    }
    const crypto = this.crypto;
    if (!sourceKey || !crypto) return !sourceKey
      ? { ok: false, reason: "invalid-draft", mode: this.mode }
      : unavailableResult();
    const canonicalScope: DraftScope = { owner_id: sourceScope.owner_id, origin: sourceScope.origin, tree_id: canonicalTreeId };
    const canonicalKey = scopeKey(canonicalScope);
    if (!canonicalKey) return { ok: false, reason: "invalid-draft", mode: this.mode };
    return this.withRekeyLocks(ownerPrefix(sourceScope), sourceKey, canonicalKey, async () => {
      const existing = this.read(canonicalScope);
      if (!existing.ok) return existing;
      const source = this.read(sourceScope);
      if (!source.ok) return source;
      if (!source.found) {
        // A crash can occur after the canonical copy is verified but before the
        // source deletion is observed. Treat a matching migration marker as an
        // idempotent reconciliation, not as data loss.
        if (existing.found && existing.value.migration_id === migrationId &&
            existing.value.migration_source_create_idempotency_key === sourceScope.create_idempotency_key &&
            existing.value.migration_hash_algorithm === "sha-256" && existing.value.migration_hash_version === 1 &&
            typeof existing.value.migration_fingerprint === "string" && /^[0-9a-f]{64}$/i.test(existing.value.migration_fingerprint)) {
          return existing;
        }
        return { ok: false, reason: "not-found", mode: source.mode };
      }
      let sourceFingerprint: string;
      try { sourceFingerprint = await fingerprint(source.value, crypto); }
      catch { return unavailableResult(); }
      const removeSource = (): DraftResult<boolean> => {
        const current = this.read(sourceScope);
        if (!current.ok || !current.found || current.value.generation !== source.value.generation) {
          return { ok: false, reason: "rekey-conflict", mode: current.mode };
        }
        if (this.storage && this.storageState !== "absent" && !this.memoryOnlyKeys.has(sourceKey)) {
          if (this.storageState !== "available") return unavailableResult();
          try {
            this.storage.removeItem(sourceKey);
            if (this.storage.getItem(sourceKey) !== null) return unavailableResult();
          } catch { this.markStorageFailed(); return unavailableResult(); }
          this.deletionTombstones.delete(sourceKey);
        } else if (this.storage && this.storageState !== "absent") {
          this.deletionTombstones.add(sourceKey);
        }
        this.memory.delete(sourceKey);
        this.memoryOnlyKeys.delete(sourceKey);
        return { ok: true, value: true, mode: this.mode };
      };
      if (existing.found) {
        if (existing.value.migration_id !== migrationId || existing.value.migration_fingerprint !== sourceFingerprint ||
            existing.value.migration_source_create_idempotency_key !== source.value.create_idempotency_key) {
          return { ok: false, reason: "rekey-conflict", mode: existing.mode };
        }
        const currentSource = this.read(sourceScope);
        if (!currentSource.ok || !currentSource.found || currentSource.value.generation !== source.value.generation) {
          return { ok: false, reason: "rekey-conflict", mode: currentSource.mode };
        }
        try {
          if (await fingerprint(currentSource.value, crypto) !== sourceFingerprint) {
            return { ok: false, reason: "rekey-conflict", mode: currentSource.mode };
          }
        } catch { return unavailableResult(); }
        const removed = removeSource();
        if (!removed.ok) return removed;
        return { ok: true, value: existing.value, mode: existing.mode };
      }
      const migrated = clone({
        ...source.value,
        tree_id: canonicalTreeId,
        migration_id: migrationId,
        migration_fingerprint: sourceFingerprint,
        migration_source_create_idempotency_key: source.value.create_idempotency_key,
        migration_hash_algorithm: "sha-256" as const,
        migration_hash_version: 1 as const
      });
      if (!validEnvelope(migrated)) return { ok: false, reason: "invalid-draft", mode: this.mode };
      const written = this.writeRaw(canonicalKey, JSON.stringify(migrated));
      if (!written.ok) return written;
      const verified = this.read(canonicalScope);
      if (!verified.ok || !verified.found || verified.value.migration_id !== migrationId ||
          verified.value.migration_fingerprint !== sourceFingerprint ||
          verified.value.migration_source_create_idempotency_key !== source.value.create_idempotency_key) {
        return { ok: false, reason: "storage-unavailable", mode: verified.mode };
      }
      const currentSource = this.read(sourceScope);
      if (!currentSource.ok || !currentSource.found || currentSource.value.generation !== source.value.generation) {
        return { ok: false, reason: "rekey-conflict", mode: currentSource.mode };
      }
      try {
        if (await fingerprint(currentSource.value, crypto) !== sourceFingerprint) {
          return { ok: false, reason: "rekey-conflict", mode: currentSource.mode };
        }
      } catch { return unavailableResult(); }
      const removed = removeSource();
      if (!removed.ok) return removed;
      return { ok: true, value: verified.value, mode: written.mode };
    });
  }

  public async cleanupOwnerTransition(ownerScope: DraftOwnerScope): Promise<DraftResult<number>> {
    const prefix = ownerPrefix(ownerScope);
    if (!prefix) return { ok: false, reason: "cleanup-failed", mode: this.mode };
    const storage = this.storage;
    const lockManager = this.lockManager;
    const ownerLockName = `${DRAFT_KEY_PREFIX}.owner.${prefix}`;
    const clearMemory = (): DraftResult<number> => {
      const memoryKeys = [...this.memory.keys()].filter((key) => key.startsWith(prefix));
      memoryKeys.forEach((key) => { this.memory.delete(key); this.memoryOnlyKeys.delete(key); });
      const remaining = [...this.memory.keys()].some((key) => key.startsWith(prefix)) ||
        [...this.memoryOnlyKeys].some((key) => key.startsWith(prefix));
      if (remaining) return { ok: false, reason: "cleanup-failed", mode: "online-only" };
      return { ok: true, value: memoryKeys.length, mode: "online-only" };
    };
    if (!storage) {
      if (lockManager) {
        try {
          return await lockManager.request(ownerLockName, { mode: "exclusive", ifAvailable: true }, async (ownerLock) => {
            if (!ownerLock) return { ok: false, reason: "cleanup-failed", mode: "online-only" };
            return clearMemory();
          });
        } catch { return { ok: false, reason: "cleanup-failed", mode: "online-only" }; }
      }
      if (!this.fallbackAcquireExclusive(prefix)) return { ok: false, reason: "cleanup-failed", mode: "online-only" };
      try { return clearMemory(); }
      finally { this.fallbackReleaseExclusive(prefix); }
    }
    if (!lockManager || this.storageState !== "available") return { ok: false, reason: "cleanup-failed", mode: "online-only" };
    try {
      const ownerResult: DraftResult<number> = await lockManager.request(ownerLockName, { mode: "exclusive", ifAvailable: true }, async (ownerLock): Promise<DraftResult<number>> => {
        if (!ownerLock) return { ok: false, reason: "cleanup-failed", mode: this.mode };
        const physicalKeys: string[] = [];
        try {
          for (let index = 0; index < storage.length; index += 1) {
            const key = storage.key(index);
            if (key?.startsWith(prefix)) physicalKeys.push(key);
          }
        } catch { return { ok: false, reason: "cleanup-failed", mode: "online-only" }; }
        let removed = 0;
        for (const key of [...new Set(physicalKeys)].sort()) {
          const keyLockName = `${DRAFT_KEY_PREFIX}.writer.${key}`;
          const keyResult = await lockManager.request(keyLockName, { mode: "exclusive", ifAvailable: true }, async (keyLock) => {
            if (!keyLock) return false;
            try {
              storage.removeItem(key);
              if (storage.getItem(key) !== null) return false;
            } catch { return false; }
            this.memory.delete(key);
            this.memoryOnlyKeys.delete(key);
            removed += 1;
            return true;
          });
          if (!keyResult) return { ok: false, reason: "cleanup-failed", mode: this.mode };
        }
        try {
          for (let index = 0; index < storage.length; index += 1) {
            const key = storage.key(index);
            if (key?.startsWith(prefix)) return { ok: false, reason: "cleanup-failed", mode: this.mode };
          }
        } catch { return { ok: false, reason: "cleanup-failed", mode: "online-only" }; }
        for (const key of [...this.memory.keys()]) {
          if (key.startsWith(prefix)) { this.memory.delete(key); this.memoryOnlyKeys.delete(key); }
        }
        if ([...this.memory.keys()].some((key) => key.startsWith(prefix)) ||
            [...this.memoryOnlyKeys].some((key) => key.startsWith(prefix))) {
          return { ok: false, reason: "cleanup-failed", mode: this.mode };
        }
        return { ok: true, value: removed, mode: this.mode };
      });
      return ownerResult;
    } catch { return { ok: false, reason: "cleanup-failed", mode: "online-only" }; }
  }

  public async list(ownerScope: DraftOwnerScope): Promise<DraftResult<readonly DraftListing[]>> {
    const prefix = ownerPrefix(ownerScope);
    if (!prefix) return { ok: false, reason: "invalid-draft", mode: this.mode };
    if (this.storage && this.storageState === "failed") return unavailableResult();
    const keys = new Set<string>();
    if (this.mode === "online-only") {
      for (const key of this.memoryOnlyKeys) if (key.startsWith(prefix)) keys.add(key);
    } else if (this.storage && this.storageState === "available") {
      try {
        for (let index = 0; index < this.storage.length; index += 1) {
          const key = this.storage.key(index);
          if (key?.startsWith(prefix)) keys.add(key);
        }
      } catch { return unavailableResult(); }
    }
    const entries: Array<{ key: string; value: PendingDraftEnvelope; mode: DraftMode }> = [];
    for (const key of keys) {
      const rawResult = this.readRaw(key);
      if (rawResult.raw === null) {
        if (this.mode === "durable") continue;
        return unavailableResult();
      }
      const parsed = this.parseRaw(rawResult.raw, key);
      if (!parsed.ok) return parsed.result;
      const value = parsed.value;
      if (value.owner_id !== ownerScope.owner_id || value.origin !== normalizeOrigin(ownerScope.origin)) {
        return { ok: false, reason: "invalid-draft", mode: rawResult.mode };
      }
      entries.push({ key, value, mode: rawResult.mode });
    }
    const hidden = new Set<string>();
    const migrationGroups = new Map<string, typeof entries>();
    for (const entry of entries) {
      if (!entry.value.migration_id || entry.value.tree_id === null) continue;
      const group = migrationGroups.get(entry.value.migration_id) ?? [];
      group.push(entry);
      migrationGroups.set(entry.value.migration_id, group);
    }
    for (const group of migrationGroups.values()) {
      const first = group[0];
      if (!first) continue;
      const source = entries.find((candidate) => candidate.value.tree_id === null &&
        candidate.value.create_idempotency_key === first.value.migration_source_create_idempotency_key);
      let sourceFingerprint: string | null = null;
      if (source) {
        if (!this.crypto) return unavailableResult();
        try { sourceFingerprint = await fingerprint(source.value, this.crypto); }
        catch { return unavailableResult(); }
      }
      const structurallyValid = group.filter((candidate) =>
        candidate.value.migration_hash_algorithm === "sha-256" && candidate.value.migration_hash_version === 1 &&
        typeof candidate.value.migration_fingerprint === "string" &&
        isUuidLike(candidate.value.migration_source_create_idempotency_key));
      let validCanonical = structurallyValid;
      if (source) {
        validCanonical = structurallyValid.filter((candidate) =>
          candidate.value.migration_source_create_idempotency_key === source.value.create_idempotency_key &&
          candidate.value.migration_fingerprint === sourceFingerprint);
        group.filter((candidate) => !validCanonical.includes(candidate)).forEach((candidate) => hidden.add(candidate.key));
      } else if (structurallyValid.length > 0) {
        const marker = [...structurallyValid].sort((left, right) => {
          const leftMarker = `${left.value.migration_source_create_idempotency_key}:${left.value.migration_fingerprint}:${left.key}`;
          const rightMarker = `${right.value.migration_source_create_idempotency_key}:${right.value.migration_fingerprint}:${right.key}`;
          return leftMarker.localeCompare(rightMarker);
        })[0];
        if (marker) {
          validCanonical = structurallyValid.filter((candidate) =>
            candidate.value.migration_source_create_idempotency_key === marker.value.migration_source_create_idempotency_key &&
            candidate.value.migration_fingerprint === marker.value.migration_fingerprint);
        }
      }
      if (validCanonical.length > 0) {
        validCanonical.sort((left, right) => {
          const timestampOrder = right.value.local_updated_at.localeCompare(left.value.local_updated_at);
          return timestampOrder || left.key.localeCompare(right.key);
        });
        if (source) hidden.add(source.key);
        validCanonical.slice(1).forEach((candidate) => hidden.add(candidate.key));
      }
    }
    const listings: DraftListing[] = [];
    for (const entry of entries) {
      if (hidden.has(entry.key)) continue;
      const stale = this.clock.now() - Date.parse(entry.value.local_updated_at) >= CRT_DRAFT_RETENTION_MS;
      listings.push({ value: entry.value, stale, requires_backup_confirmation: stale });
    }
    listings.sort((left, right) => right.value.local_updated_at.localeCompare(left.value.local_updated_at));
    return { ok: true, value: listings, mode: this.mode };
  }

  public delete(scope: DraftScope, options: DraftWriteOptions = {}): DraftResult<boolean> {
    const key = scopeKey(scope);
    const denied = this.mutationAllowed(key);
    if (denied) return denied;
    const current = this.read(scope);
    if (!current.ok) return current;
    if (!current.found) return { ok: true, value: true, mode: current.mode };
    const expected = options.token?.generation ?? options.expected_generation;
    if (options.token?.key !== undefined && options.token.key !== key) return { ok: false, reason: "stale-generation", mode: current.mode };
    if (expected !== undefined && expected !== current.value.generation) return { ok: false, reason: "stale-generation", mode: current.mode };
    if (this.storage && this.storageState !== "absent" && !this.memoryOnlyKeys.has(key)) {
      if (this.storageState !== "available" || this.lockManager === null) return unavailableResult();
      try {
        this.storage.removeItem(key);
        if (this.storage.getItem(key) !== null) return unavailableResult();
      } catch { this.markStorageFailed(); return unavailableResult(); }
      this.deletionTombstones.delete(key);
    } else if (this.storage && this.storageState !== "absent") {
      this.deletionTombstones.add(key);
    }
    this.memory.delete(key);
    this.memoryOnlyKeys.delete(key);
    return { ok: true, value: true, mode: this.mode };
  }

  public exportBackup(scope: DraftScope): DraftResult<string> {
    const key = scopeKey(scope);
    if (!key) return { ok: false, reason: "invalid-draft", mode: this.mode };
    const raw = this.readRaw(key);
    if (raw.raw === null) return { ok: false, reason: "not-found", mode: raw.mode };
    const parsed = this.parseRaw(raw.raw, key);
    if (!parsed.ok) return parsed.result;
    if (parsed.value.owner_id !== scope.owner_id || parsed.value.origin !== normalizeOrigin(scope.origin)) return { ok: false, reason: "not-found", mode: raw.mode };
    return { ok: true, value: JSON.stringify(parsed.value), mode: raw.mode };
  }

  public recover(scope: DraftScope): DraftResult<PendingDraftEnvelope> {
    const key = scopeKey(scope);
    const denied = this.mutationAllowed(key);
    if (denied) return denied;
    const current = this.read(scope);
    if (!current.ok) return current;
    if (!current.found) return { ok: false, reason: "not-found", mode: current.mode };
    return this.write(scope, current.value, { expected_generation: current.value.generation });
  }

  public discard(scope: DraftScope, options: DraftWriteOptions = {}): DraftResult<boolean> { return this.delete(scope, options); }

  public captureGeneration(scope: DraftScope): DraftGenerationToken | null {
    const read = this.read(scope);
    if (!read.ok || !read.found) return null;
    return { key: scopeKey(scope), generation: read.value.generation };
  }

  private writeRaw(key: string, serialized: string): DraftResult<true> {
    if (!key) return { ok: false, reason: "invalid-draft", mode: this.mode };
    if (this.mode === "durable" && this.storage) {
      try {
        this.storage.setItem(key, serialized);
        if (this.storage.getItem(key) !== serialized) throw new Error("write readback mismatch");
        this.memory.set(key, serialized);
        this.memoryOnlyKeys.delete(key);
        this.deletionTombstones.delete(key);
        return { ok: true, value: true, mode: "durable" };
      } catch { this.markStorageFailed(); this.invalidatePhysicalKey(key); return unavailableResult(); }
    }
    this.memory.set(key, serialized);
    this.memoryOnlyKeys.add(key);
    return { ok: true, value: true, mode: "online-only" };
  }

  private readRaw(key: string): { raw: string | null; mode: DraftMode } {
    if (this.mode === "online-only") return { raw: this.memoryOnlyKeys.has(key) ? this.memory.get(key) ?? null : null, mode: "online-only" };
    if (this.storage && this.storageState === "available") {
      try {
        const raw = this.storage.getItem(key);
        if (raw !== null) {
          this.memory.set(key, raw);
          return { raw, mode: "durable" };
        }
        this.memory.delete(key);
        this.memoryOnlyKeys.delete(key);
        return { raw: null, mode: "durable" };
      } catch {
        this.markStorageFailed();
        return { raw: this.memoryOnlyKeys.has(key) ? this.memory.get(key) ?? null : null, mode: "online-only" };
      }
    }
    return { raw: this.memoryOnlyKeys.has(key) ? this.memory.get(key) ?? null : null, mode: this.mode };
  }

  private parseRaw(raw: string, expectedKey?: string): ParsedRaw {
    let decoded: unknown;
    try { decoded = JSON.parse(raw); } catch { return { ok: false, result: { ok: false, reason: "invalid-json", mode: this.mode, raw } }; }
    const validation = validateDraftEnvelope(decoded);
    if (!validation.ok) return { ok: false, result: { ok: false, reason: validation.reason, mode: this.mode, raw } };
    if (expectedKey && draftStorageKey({ owner_id: validation.value.owner_id, origin: validation.value.origin, tree_id: validation.value.tree_id, create_idempotency_key: validation.value.create_idempotency_key }) !== expectedKey) {
      return { ok: false, result: { ok: false, reason: "invalid-draft", mode: this.mode, raw } };
    }
    const physical = expectedKey ? physicalScope(expectedKey) : null;
    if (expectedKey && !physical) return { ok: false, result: { ok: false, reason: "invalid-draft", mode: this.mode, raw } };
    return { ok: true, value: validation.value };
  }
}
