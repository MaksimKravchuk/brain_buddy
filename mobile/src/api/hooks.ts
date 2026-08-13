/**
 * React Query hooks over the API client.
 *
 * Mirrors the web app's pattern (`frontend/src/api/taskHooks.ts`): all task,
 * project, and tag queries live under the `["tasks"]` root so any mutation
 * invalidates every affected view — lists, counts, browse rows, and detail.
 */

import AsyncStorage from "@react-native-async-storage/async-storage";
import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,

  type MutateOptions,
  type UseMutationOptions,
  type UseMutationResult,
} from "@tanstack/react-query";
import { useCallback, useEffect, useRef } from "react";

import { ApiError } from "@/api/client";
import { projectRunsAt } from "@/agents/machine";
import { PRIVATE_AGENT_ROOT } from "@/api/privateAgentCache";

import { useApi, useSession } from "@/auth/SessionProvider";
import type {
  ProjectResponse,
  AgentConnectionCreateRequest,
  AgentConnectionCreatedResponse,
  AgentConnectionDisconnectRequest,
  AgentConnectionResponse,
  AgentConnectionRotateRequest,
  AgentConnectionRotateSigningSecretRequest,
  AgentConnectionSigningSecretResponse,
  AgentConnectionUpdateRequest,
  AgentHandoffConfirmRequest,
  AgentHandoffPreviewRequest,
  AgentReplyRequest,
  AgentRunResponse,
  SmartAddTaskCreateRequest,
  TagResponse,
  TaskCreateRequest,
  TaskListFilters,
  TaskListResponse,
  TaskTransitionRequest,
  TaskUpdateRequest,
} from "@/api/types";
import {
  readClassificationCache,
  writeClassificationCache,
} from "@/features/tasks/classificationCache";
import type { CachedClassificationLists } from "@/features/tasks/classificationTypes";
import {
  cacheKey,
  identityStoreGeneration,
  isStoreGenerationCurrent,
} from "@/features/tasks/storageKeys";
import { newIdempotencyKey, requireIdempotencyKey } from "@/utils/ids";

export const taskKeys = {
  root: ["tasks"] as const,
  list: (filters: Omit<TaskListFilters, "cursor">) => ["tasks", "list", filters] as const,
  detail: (taskId: string) => ["tasks", "detail", taskId] as const,
  projects: ["tasks", "projects"] as const,
  tags: ["tasks", "tags"] as const,
};

export const agentKeys = {
  root: PRIVATE_AGENT_ROOT,
  owner: (owner: string) => [...agentKeys.root, owner] as const,
  connections: (owner: string) => [...agentKeys.owner(owner), "connections"] as const,
  connection: (owner: string, connectionId: string) =>
    [...agentKeys.connections(owner), connectionId] as const,
  taskRuns: (owner: string, taskId: string) =>
    [...agentKeys.owner(owner), "runs", "task", taskId] as const,
  run: (owner: string, runId: string) => [...agentKeys.owner(owner), "runs", runId] as const,
  summaries: (owner: string, taskIds: string[]) =>
    [...agentKeys.owner(owner), "summaries", taskIds] as const,
  mutation: (owner: string, action: string) =>
    [...agentKeys.owner(owner), "mutation", action] as const,
};

export function agentOwnerIdentity(serverUrl: string, userId: string | null | undefined): string {
  return `${serverUrl.replace(/\/+$/, "")}|${userId ?? "signed-out"}`;
}

const PAGE_SIZE = 50;

/**
 * Revision stamped on a list entry that came back from the device cache
 * (006-FR-006, 006-SC-009).
 *
 * The cache stores ids and names only — see `CachedClassificationLists` — so an
 * offline read cannot know the real revision. A deliberately invalid sentinel
 * is used rather than a plausible `0`: this feature never edits a project or a
 * tag (that is out of scope), and if some later caller ever sends this as an
 * `expected_revision` the server must reject it rather than apply a write on a
 * guessed revision.
 */
const UNKNOWN_CACHED_REVISION = -1;

type CachedEntry = CachedClassificationLists["projects"][number];

/**
 * Only `active` entries are cached. The cached shape carries no state, so
 * anything cached is necessarily projected back as active on read — caching
 * only the entries that already are keeps that projection true, instead of
 * resurrecting an archived project into the picker while offline.
 */
function cacheableEntries(
  items: readonly { id: string; name: string; state: string }[],
): CachedEntry[] {
  return items
    .filter((item) => item.state === "active")
    .map((item) => ({ id: item.id, name: item.name }));
}

/**
 * The cache key of the identity these lists belong to, or `null` when the
 * device cannot name one.
 *
 * Both halves come from the session, which resolves them from storage when
 * there is no live profile — the cold start with no connection this cache
 * exists for is exactly when `/auth/me` never answers (006-FR-009).
 *
 * Returns `null` rather than falling back to an unscoped key: a shared key is a
 * cross-account read (006-SC-007), and no cache at all is the safe failure.
 */
function activeCacheKey(serverUrl: string, accountId: string | null): string | null {
  return serverUrl && accountId ? cacheKey(serverUrl, accountId) : null;
}

/**
 * Cache writes are serialized because the two halves are fetched by two
 * independent queries into one stored record. Read-modify-write from both at
 * once would let the later writer drop the earlier one's list — silent loss of
 * exactly the data the offline picker depends on.
 */
let cacheWrites: Promise<unknown> = Promise.resolve();

/**
 * Write one half of the freshly fetched lists through to the device cache,
 * preserving the other half (006-FR-006).
 *
 * Fire-and-forget on purpose: a failed device write must never fail the query
 * a screen is waiting on. The consequence is a staler cache, which the offline
 * read already tolerates.
 */
function cacheListsInBackground(
  serverUrl: string,
  accountId: string | null,
  half: { projects: CachedEntry[] } | { tags: CachedEntry[] },
  /** Read before the fetch that produced `half` went out. Reading it here
   *  instead would read it *after* the response arrived, so a sign-out that
   *  happened during the request would already be behind us and this write
   *  would put the old account's names back. */
  generation: number,
): void {
  const key = activeCacheKey(serverUrl, accountId);
  if (!key) {
    return;
  }
  cacheWrites = cacheWrites
    .catch(() => undefined)
    .then(async () => {
      // Checked here rather than above, because "is this identity still on the
      // device" is only meaningful when the write actually runs. This chain is
      // fire-and-forget from a query callback: a sign-out or server change can
      // land between the fetch that scheduled it and its turn, and writing then
      // would put one account's whole project and Tag vocabulary — names the
      // person wrote — back on a device that has just forgotten them.
      if (!isStoreGenerationCurrent(key, generation)) {
        return;
      }
      const now = Date.now();
      const current = await readClassificationCache({ store: AsyncStorage, key, now });
      // Again after the read, which is itself an await: a sign-out landing
      // inside it would otherwise be followed by a write that re-creates the
      // cache it just deleted, leaving one account's project and Tag names on
      // the device after a deliberate transition.
      if (!isStoreGenerationCurrent(key, generation)) {
        return;
      }
      await writeClassificationCache({
        store: AsyncStorage,
        key,
        lists: {
          projects: current?.projects ?? [],
          tags: current?.tags ?? [],
          ...half,
          fetchedAt: new Date(now).toISOString(),
        },
        now,
      });
    })
    .catch(() => undefined);
}

/** The device's answer for one half of the lists, or `null` if it has none. */
async function cachedHalf<K extends "projects" | "tags">(
  serverUrl: string,
  accountId: string | null,
  half: K,
): Promise<CachedEntry[] | null> {
  const key = activeCacheKey(serverUrl, accountId);
  if (!key) {
    return null;
  }
  try {
    const cached = await readClassificationCache({ store: AsyncStorage, key, now: Date.now() });
    return cached?.[half].length ? cached[half] : null;
  } catch {
    return null;
  }
}

export function useTaskList(filters: Omit<TaskListFilters, "cursor">) {
  const api = useApi();
  return useInfiniteQuery({
    queryKey: taskKeys.list(filters),
    queryFn: ({ pageParam, signal }) =>
      api.listTasks({ ...filters, cursor: pageParam, limit: PAGE_SIZE }, signal),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (lastPage: TaskListResponse) =>
      lastPage.has_more && lastPage.next_cursor ? lastPage.next_cursor : undefined,
  });
}

export function useTask(taskId: string) {
  const api = useApi();
  return useQuery({
    queryKey: taskKeys.detail(taskId),
    queryFn: ({ signal }) => api.getTask(taskId, signal),
  });
}

/**
 * Projects, written through to the device cache and read back from it when the
 * fetch fails (006-FR-006, 006-SC-009).
 *
 * React Query's cache is in memory and `mobile/` installs no persister, so
 * after a cold start with no connection it is empty — a person offline would
 * open an empty picker and be unable to classify anything, which is the whole
 * of FR-006. The cache read is therefore inside `queryFn`: a failure that the
 * device can answer resolves as data rather than as an error, so the picker
 * opens instead of showing an error state it has no way out of.
 *
 * The trade this makes explicitly: a transient failure no longer retries,
 * because the query no longer fails. It resolves from cache and refreshes on
 * the next refetch trigger. That is the offline-first choice this feature was
 * built on, applied consistently.
 */
export function useProjects() {
  const api = useApi();
  const { serverUrl, accountId } = useSession();
  return useQuery({
    queryKey: taskKeys.projects,
    queryFn: async ({ signal }): Promise<ProjectResponse[]> => {
      // Before the request, not after it. Read on the way back, this is
      // already the post-sign-out value: a clear that happened while the fetch
      // was in flight would be behind us, both checks in the writer would pass,
      // and the old account's project names would go back onto the device.
      const generation = identityStoreGeneration(serverUrl, accountId ?? "");
      try {
        const projects = await api.listProjects(signal);
        cacheListsInBackground(
          serverUrl,
          accountId,
          { projects: cacheableEntries(projects) },
          generation,
        );
        return projects;
      } catch (error) {
        const cached = await cachedHalf(serverUrl, accountId, "projects");
        if (!cached) {
          // Nothing on the device to answer with: surface the real failure
          // rather than an empty list that reads as "you have no projects".
          throw error;
        }
        return cached.map((project) => ({
          id: project.id,
          name: project.name,
          color: null,
          state: "active" as const,
          revision: UNKNOWN_CACHED_REVISION,
          open_task_count: 0,
        }));
      }
    },
  });
}

/** Tags, cached and read back exactly as `useProjects` — see its comment. */
export function useTags() {
  const api = useApi();
  const { serverUrl, accountId } = useSession();
  return useQuery({
    queryKey: taskKeys.tags,
    queryFn: async ({ signal }): Promise<TagResponse[]> => {
      // Before the request, for the same reason as `useProjects` above.
      const generation = identityStoreGeneration(serverUrl, accountId ?? "");
      try {
        const tags = await api.listTags(signal);
        cacheListsInBackground(
          serverUrl,
          accountId,
          { tags: cacheableEntries(tags) },
          generation,
        );
        return tags;
      } catch (error) {
        const cached = await cachedHalf(serverUrl, accountId, "tags");
        if (!cached) {
          throw error;
        }
        return cached.map((tag) => ({
          id: tag.id,
          name: tag.name,
          state: "active" as const,
          revision: UNKNOWN_CACHED_REVISION,
          open_task_count: 0,
        }));
      }
    },
  });
}

function useInvalidateTasks() {
  const queryClient = useQueryClient();
  return () => queryClient.invalidateQueries({ queryKey: taskKeys.root });
}

export function useCreateTask() {
  const api = useApi();
  const invalidate = useInvalidateTasks();
  return useMutation({
    mutationFn: (payload: TaskCreateRequest) => api.createTask(payload, newIdempotencyKey()),
    onSuccess: invalidate,
  });
}

export function useSmartAddTask() {
  const api = useApi();
  const invalidate = useInvalidateTasks();
  return useMutation({
    mutationFn: (payload: SmartAddTaskCreateRequest) =>
      api.smartAddTask(payload, newIdempotencyKey()),
    onSuccess: invalidate,
  });
}

/**
 * A 409 means our `expected_revision` is stale: refetch so the screen's
 * "the latest version is shown" claim is actually true and the next attempt
 * carries the fresh revision.
 */
function useInvalidateOnConflict() {
  const invalidate = useInvalidateTasks();
  return (error: unknown) => {
    if (error instanceof ApiError && error.status === 409) {
      invalidate();
    }
  };
}

/**
 * What `useUpdateTask` is asked to send.
 *
 * A bare payload keeps the one-shot behaviour every existing caller relies on:
 * a fresh key is minted for that single attempt. The wrapped form is what the
 * classification queue uses — 006-FR-017 requires the queue *entry* to own its
 * key so every retry of an unchanged payload carries the same one. A hook that
 * mints per call cannot satisfy that: a request that timed out may already have
 * been applied, and retrying it under a new key applies it twice.
 */
export type TaskUpdateVariables =
  | TaskUpdateRequest
  | { payload: TaskUpdateRequest; idempotencyKey: string };

function unwrapTaskUpdate(variables: TaskUpdateVariables): {
  payload: TaskUpdateRequest;
  idempotencyKey: string;
} {
  return "payload" in variables
    ? variables
    : { payload: variables, idempotencyKey: newIdempotencyKey() };
}

export function useUpdateTask(taskId: string) {
  const api = useApi();
  const invalidate = useInvalidateTasks();
  const onConflict = useInvalidateOnConflict();
  return useMutation({
    mutationFn: (variables: TaskUpdateVariables) => {
      const { payload, idempotencyKey } = unwrapTaskUpdate(variables);
      return api.updateTask(taskId, payload, idempotencyKey);
    },
    onSuccess: invalidate,
    onError: onConflict,
  });
}

export function useTransitionTask(taskId?: string) {
  const api = useApi();
  const invalidate = useInvalidateTasks();
  const onConflict = useInvalidateOnConflict();
  return useMutation({
    mutationFn: (input: { taskId?: string; payload: TaskTransitionRequest }) => {
      const target = input.taskId ?? taskId;
      if (!target) {
        throw new Error("taskId is required");
      }
      return api.transitionTask(target, input.payload, newIdempotencyKey());
    },
    onSuccess: invalidate,
    onError: onConflict,
  });
}

export function useCreateSubtask(taskId: string) {
  const api = useApi();
  const invalidate = useInvalidateTasks();
  const onConflict = useInvalidateOnConflict();
  return useMutation({
    mutationFn: (title: string) => api.createSubtask(taskId, { title }, newIdempotencyKey()),
    onSuccess: invalidate,
    onError: onConflict,
  });
}

export function useTransitionSubtask(taskId: string) {
  const api = useApi();
  const invalidate = useInvalidateTasks();
  const onConflict = useInvalidateOnConflict();
  return useMutation({
    mutationFn: (input: {
      subtaskId: string;
      action: "complete" | "reopen" | "cancel";
      expectedRevision: number;
    }) =>
      api.transitionSubtask(
        taskId,
        input.subtaskId,
        { action: input.action, expected_revision: input.expectedRevision },
        newIdempotencyKey(),
      ),
    onSuccess: invalidate,
    onError: onConflict,
  });
}

export function useCreateComment(taskId: string) {
  const api = useApi();
  const invalidate = useInvalidateTasks();
  const onConflict = useInvalidateOnConflict();
  return useMutation({
    mutationFn: (body: string) => api.createComment(taskId, { body }, newIdempotencyKey()),
    onSuccess: invalidate,
    onError: onConflict,
  });
}

// --- External agents ---
//
// Agent state lives under the `["agents"]` root so a connection change never
// silently invalidates task lists (and vice versa). Runs are attached to a
// task but are not part of it: a connector report never mutates the Task.

/**
 * Relay writes and their write-like probes must execute the caller's one
 * explicit attempt even when React Query believes the device is offline.
 *
 * The default `online` mutation mode pauses before `mutationFn`, then silently
 * resumes on reconnect. FR-018 forbids that queue/auto-send behavior. `always`
 * lets the transport fail now and leaves an ambiguous retry in the caller's
 * hands, where the original idempotency key is preserved.
 */
const RELAY_MUTATION_NETWORK = { networkMode: "always" as const };

const STALE_RELAY_MUTATION_MESSAGE = "Relay mutation scope is stale.";

class StaleRelayMutationScopeError extends Error {
  constructor() {
    super(STALE_RELAY_MUTATION_MESSAGE);
    this.name = "StaleRelayMutationScopeError";
  }
}

interface RelayDispatch<TVariables> {
  variables: TVariables;
  scope: { identityEpoch: number; owner: string };
}

function useRelayMutation<TTransport, TData = TTransport, TVariables = void>(
  options: Omit<UseMutationOptions<TData, Error, TVariables>, "mutationFn"> & {
    mutationFn(variables: TVariables): Promise<TTransport>;
    consume?: (result: TTransport) => TData;
  },
): UseMutationResult<TData, Error, TVariables> {
  const session = useSession();
  const queryClient = useQueryClient();
  const getIdentityEpoch = session.getIdentityEpoch ?? (() => 0);
  const owner = agentOwnerIdentity(session.serverUrl, session.accountId ?? undefined);
  const { mutationFn, consume, ...settlementOptions } = options;
  const currentDispatchRef = useRef<RelayDispatch<TVariables> | undefined>(undefined);
  const isDispatchCurrent = (dispatch: RelayDispatch<TVariables>) =>
    getIdentityEpoch() === dispatch.scope.identityEpoch && dispatch.scope.owner === owner;
  const removeDispatchMutation = (dispatch: RelayDispatch<TVariables>) => {
    const exactMutation = queryClient
      .getMutationCache()
      .getAll()
      .find((candidate: { state: { variables: unknown } }) =>
        candidate.state.variables === dispatch);
    if (exactMutation) {
      queueMicrotask(() => {
        queryClient.getMutationCache().remove(exactMutation);
        if (currentDispatchRef.current === dispatch) {
          mutation.reset();
        }
      });
    }
  };
  const stale = (dispatch: RelayDispatch<TVariables>): never => {
    removeDispatchMutation(dispatch);
    throw new StaleRelayMutationScopeError();
  };
  const mutationOptions = {
    ...settlementOptions,
    ...RELAY_MUTATION_NETWORK,
    onSuccess: (data: TData, dispatch: RelayDispatch<TVariables>, result: unknown, context: unknown) => {
      if (isDispatchCurrent(dispatch)) {
        settlementOptions.onSuccess?.(data, dispatch.variables, result, context as never);
      }
    },
    onError: (error: Error, dispatch: RelayDispatch<TVariables>, result: unknown, context: unknown) => {
      if (isDispatchCurrent(dispatch) && !(error instanceof StaleRelayMutationScopeError)) {
        settlementOptions.onError?.(error, dispatch.variables, result, context as never);
      }
    },
    onSettled: (data: TData | undefined, error: Error | null, dispatch: RelayDispatch<TVariables>, result: unknown, context: unknown) => {
      if (isDispatchCurrent(dispatch) && !(error instanceof StaleRelayMutationScopeError)) {
        settlementOptions.onSettled?.(data, error, dispatch.variables, result, context as never);
      }
    },
    mutationFn: async (dispatch: RelayDispatch<TVariables>) => {
      if (!isDispatchCurrent(dispatch)) {
        return stale(dispatch);
      }
      let result: TTransport;
      try {
        result = await mutationFn(dispatch.variables);
      } catch (error) {
        if (!isDispatchCurrent(dispatch)) {
          return stale(dispatch);
        }
        throw error;
      }
      if (!isDispatchCurrent(dispatch)) {
        return stale(dispatch);
      }
      return consume ? consume(result) : (result as unknown as TData);
    },
  } as unknown as UseMutationOptions<TData, Error, RelayDispatch<TVariables>>;
  const mutation = useMutation<TData, Error, RelayDispatch<TVariables>>(mutationOptions);
  const scope = () => ({ identityEpoch: getIdentityEpoch(), owner });
  const wrapMutateOptions = (
    mutateOptions?: MutateOptions<TData, Error, TVariables>,
  ): MutateOptions<TData, Error, RelayDispatch<TVariables>> | undefined => mutateOptions && ({
    onSuccess: (data, dispatch, result, context) => {
      if (isDispatchCurrent(dispatch)) {
        mutateOptions.onSuccess?.(data, dispatch.variables, result, context as never);
      }
    },
    onError: (error, dispatch, result, context) => {
      if (isDispatchCurrent(dispatch) && !(error instanceof StaleRelayMutationScopeError)) {
        mutateOptions.onError?.(error, dispatch.variables, result, context as never);
      }
    },
    onSettled: (data, error, dispatch, result, context) => {
      if (isDispatchCurrent(dispatch) && !(error instanceof StaleRelayMutationScopeError)) {
        mutateOptions.onSettled?.(data, error, dispatch.variables, result, context as never);
      }
    },
  });
  const mutate = (
    variables: TVariables,
    mutateOptions?: MutateOptions<TData, Error, TVariables>,
  ) => {
    const dispatch = { variables, scope: scope() };
    currentDispatchRef.current = dispatch;
    mutation.mutate(
      dispatch,
      wrapMutateOptions(mutateOptions),
    );
  };
  const mutateAsync = (
    variables: TVariables,
    mutateOptions?: MutateOptions<TData, Error, TVariables>,
  ) => {
    const dispatch = { variables, scope: scope() };
    currentDispatchRef.current = dispatch;
    return mutation.mutateAsync(dispatch, wrapMutateOptions(mutateOptions));
  };
  return { ...mutation, mutate, mutateAsync } as UseMutationResult<TData, Error, TVariables>;
}

function useAgentContext() {
  const { api, serverUrl, accountId } = useSession();
  return { api, owner: agentOwnerIdentity(serverUrl, accountId ?? undefined) };
}

function useInvalidateAgents(owner: string) {
  const queryClient = useQueryClient();
  return () => queryClient.invalidateQueries({ queryKey: agentKeys.owner(owner) });
}

export function useAgentConnections(enabled = true) {
  const { api, owner } = useAgentContext();
  return useQuery({
    queryKey: agentKeys.connections(owner),
    queryFn: ({ signal }) => api.listAgentConnections(signal),
    enabled,
  });
}

export function useAgentConnection(connectionId: string, enabled = true) {
  const { api, owner } = useAgentContext();
  return useQuery({
    queryKey: agentKeys.connection(owner, connectionId),
    queryFn: ({ signal }) => api.getAgentConnection(connectionId, signal),
    enabled,
  });
}

/**
 * The 201 body carries the inbound signing secret exactly once. It is returned
 * to the caller for a one-time panel and deliberately never written into the
 * query cache.
 */
export function useCreateAgentConnection(options?: { onSigningSecret(secret: string): void }) {
  const { api, owner } = useAgentContext();
  const invalidate = useInvalidateAgents(owner);
  return useRelayMutation<AgentConnectionCreatedResponse, AgentConnectionResponse, {
    payload: AgentConnectionCreateRequest;
    idempotencyKey: string;
  }>({
    mutationKey: agentKeys.mutation(owner, "create-connection"),
    mutationFn: (input) => api.createAgentConnection(
      input.payload,
      requireIdempotencyKey("useCreateAgentConnection", input.idempotencyKey),
    ),
    consume: ({ inbound_signing_secret: secret, ...connection }) => {
      options?.onSigningSecret(secret);
      return connection;
    },
    onSuccess: invalidate,
  });
}

export function useTestAgentConnection() {
  const { api, owner } = useAgentContext();
  const invalidate = useInvalidateAgents(owner);
  return useRelayMutation({
    mutationKey: agentKeys.mutation(owner, "test-connection"),
    mutationFn: (connectionId: string) => api.testAgentConnection(connectionId),
    onSuccess: invalidate,
  });
}

/**
 * The caller owns the relay intent key, and there is no fallback.
 *
 * A relay mutation that times out is ambiguous — it may already have reached
 * the server. Minting a key here would turn that one attempt into a second
 * command on retry, so every hook requires and forwards the caller's exact key.
 */
export function useUpdateAgentConnection() {
  const { api, owner } = useAgentContext();
  const invalidate = useInvalidateAgents(owner);
  return useRelayMutation({
    mutationKey: agentKeys.mutation(owner, "update-connection"),
    mutationFn: (input: {
      connectionId: string;
      payload: AgentConnectionUpdateRequest;
      idempotencyKey: string;
    }) =>
      api.updateAgentConnection(
        input.connectionId,
        input.payload,
        requireIdempotencyKey("useUpdateAgentConnection", input.idempotencyKey),
      ),
    onSuccess: invalidate,
    onError: (error: unknown) => {
      if (error instanceof ApiError && error.status === 409) {
        invalidate();
      }
    },
  });
}

export function useRotateAgentCredential() {
  const { api, owner } = useAgentContext();
  const invalidate = useInvalidateAgents(owner);
  return useRelayMutation({
    mutationKey: agentKeys.mutation(owner, "rotate-credential"),
    mutationFn: (input: {
      connectionId: string;
      payload: AgentConnectionRotateRequest;
      idempotencyKey: string;
    }) =>
      api.rotateAgentCredential(
        input.connectionId,
        input.payload,
        requireIdempotencyKey("useRotateAgentCredential", input.idempotencyKey),
      ),
    onSuccess: invalidate,
    onError: (error: unknown) => {
      if (error instanceof ApiError && error.status === 409) {
        invalidate();
      }
    },
  });
}

export function useRotateAgentSigningSecret(options?: { onSigningSecret(secret: string): void }) {
  const { api, owner } = useAgentContext();
  const invalidate = useInvalidateAgents(owner);
  return useRelayMutation<AgentConnectionSigningSecretResponse, AgentConnectionResponse, {
    connectionId: string;
    payload: AgentConnectionRotateSigningSecretRequest;
    idempotencyKey: string;
  }>({
    mutationKey: agentKeys.mutation(owner, "rotate-signing-secret"),
    mutationFn: (input) => api.rotateAgentSigningSecret(
      input.connectionId,
      input.payload,
      requireIdempotencyKey("useRotateAgentSigningSecret", input.idempotencyKey),
    ),
    consume: ({ inbound_signing_secret: secret, ...connection }) => {
      options?.onSigningSecret(secret);
      return connection;
    },
    onSuccess: invalidate,
    onError: (error: unknown) => {
      if (error instanceof ApiError && error.status === 409) {
        invalidate();
      }
    },
  });
}

export function useDisconnectAgentConnection() {
  const { api, owner } = useAgentContext();
  const invalidate = useInvalidateAgents(owner);
  return useRelayMutation({
    mutationKey: agentKeys.mutation(owner, "disconnect-connection"),
    mutationFn: (input: {
      connectionId: string;
      payload: AgentConnectionDisconnectRequest;
      idempotencyKey: string;
    }) =>
      api.disconnectAgentConnection(
        input.connectionId,
        input.payload,
        requireIdempotencyKey("useDisconnectAgentConnection", input.idempotencyKey),
      ),
    onSuccess: invalidate,
    onError: (error: unknown) => {
      if (error instanceof ApiError && error.status === 409) {
        invalidate();
      }
    },
  });
}

export interface AgentRunsExpiryRuntime {
  /** Monotonic time source; wall-clock changes must not affect retention. */
  now: () => number;
  schedule: (callback: () => void, delayMs: number) => () => void;
}

const defaultAgentRunsExpiryRuntime: AgentRunsExpiryRuntime = {
  now: () => performance.now(),
  schedule: (callback, delayMs) => {
    const timer = setTimeout(callback, delayMs);
    return () => clearTimeout(timer);
  },
};

export function useAgentRuns(
  taskId: string,
  enabled = true,
  expiryRuntime: AgentRunsExpiryRuntime = defaultAgentRunsExpiryRuntime,
) {
  const { api, owner } = useAgentContext();
  const { serverTimeAnchor } = useSession();
  const queryClient = useQueryClient();
  const queryKey = agentKeys.taskRuns(owner, taskId);
  const authoritativeNow = useCallback(
    () =>
      serverTimeAnchor
        ? serverTimeAnchor.serverTimeMs + (expiryRuntime.now() - serverTimeAnchor.monotonicTimeMs)
        : null,
    [expiryRuntime, serverTimeAnchor],
  );
  const query = useQuery({
    queryKey,
    queryFn: async ({ signal }) => {
      const runs = await api.listAgentRuns(taskId, signal);
      const now = authoritativeNow();
      // Without a current session-scoped server anchor, privacy wins: do not
      // retain content based on a device wall clock that may be skewed.
      return projectRunsAt(runs, now ?? Number.POSITIVE_INFINITY);
    },
    enabled,
  });

  useEffect(() => {
    const now = authoritativeNow();
    if (now === null) {
      return;
    }
    const nextDeadline = (query.data ?? [])
      .filter((run) => !run.content_expired)
      .map((run) => Date.parse(run.content_expires_at))
      .filter((deadline) => !Number.isNaN(deadline) && deadline > now)
      .reduce<number | null>((earliest, deadline) =>
        earliest === null || deadline < earliest ? deadline : earliest, null);
    if (nextDeadline === null) {
      return;
    }
    const delay = Math.min(nextDeadline - now, 2_147_483_647);
    let active = true;
    const cancel = expiryRuntime.schedule(() => {
      if (!active) {
        return;
      }
      const callbackNow = authoritativeNow();
      if (callbackNow === null) {
        return;
      }
      queryClient.setQueryData<AgentRunResponse[]>(queryKey, (cached) =>
        cached ? projectRunsAt(cached, callbackNow) : cached,
      );
    }, delay);
    return () => {
      active = false;
      cancel();
    };
  }, [authoritativeNow, expiryRuntime, query.data, queryClient, queryKey]);

  return query;
}

/**
 * The latest run per task, for the compact task list.
 *
 * Asked only about the task IDs actually on screen, and only while the
 * account's `external_agent_relay` flag is on — the backend answers 404
 * otherwise, and a list of tasks must never manufacture an error for a
 * capability the user cannot see. The answer is sparse: a task with no hand-off
 * is simply absent, so its row stays exactly as it was.
 */
export function useAgentRunSummaries(
  taskIds: string[],
  enabled: boolean,
  refetchInterval = 15_000,
) {
  const { api, owner } = useAgentContext();
  return useQuery({
    queryKey: agentKeys.summaries(owner, taskIds),
    queryFn: ({ signal }) => api.listAgentRunSummaries(taskIds, signal),
    enabled: enabled && taskIds.length > 0,
    // Connector reports arrive independently of this process, so invalidation
    // alone cannot converge a mounted list. This bounded interval is active
    // only while the query has observers; React Query also refetches on focus.
    refetchInterval,
    refetchOnWindowFocus: true,
  });
}

/**
 * Reserves a run id and returns the manifest to review. Nothing is sent, and no
 * relay key is minted or required — the key appears at confirmation, derived
 * from the manifest token this call returns.
 */
export function usePreviewAgentHandoff(taskId: string) {
  const { api, owner } = useAgentContext();
  return useRelayMutation({
    mutationKey: agentKeys.mutation(owner, "preview-handoff"),
    mutationFn: (payload: AgentHandoffPreviewRequest) => api.previewAgentHandoff(taskId, payload),
  });
}

/**
 * The key is derived from the reviewed manifest token, not from a fresh random
 * value, so retrying the hand-off the user actually reviewed returns the
 * original run instead of starting a second one. Matches the web semantics in
 * `frontend/src/features/agents/AgentHandoffOverlay.tsx`; re-previewing mints a
 * new token, which is exactly when a new key is wanted.
 */
export function useConfirmAgentHandoff(taskId: string) {
  const { api, owner } = useAgentContext();
  const invalidate = useInvalidateAgents(owner);
  return useRelayMutation({
    mutationKey: agentKeys.mutation(owner, "confirm-handoff"),
    mutationFn: (input: {
      payload: AgentHandoffConfirmRequest;
      idempotencyKey: string;
    }) =>
      api.confirmAgentHandoff(
        taskId,
        input.payload,
        requireIdempotencyKey("useConfirmAgentHandoff", input.idempotencyKey),
      ),
    onSuccess: invalidate,
  });
}

/**
 * The caller owns the key (see `useIntentKey`): a reply that timed out may
 * already have reached the server, so the retry must carry the same key.
 */
export function useReplyToAgentRun() {
  const { api, owner } = useAgentContext();
  const invalidate = useInvalidateAgents(owner);
  return useRelayMutation({
    mutationKey: agentKeys.mutation(owner, "reply-run"),
    mutationFn: (input: {
      runId: string;
      payload: AgentReplyRequest;
      idempotencyKey: string;
    }) =>
      api.replyToAgentRun(
        input.runId,
        input.payload,
        requireIdempotencyKey("useReplyToAgentRun", input.idempotencyKey),
      ),
    onSuccess: invalidate,
  });
}

export function useCancelAgentRun() {
  const { api, owner } = useAgentContext();
  const invalidate = useInvalidateAgents(owner);
  return useRelayMutation({
    mutationKey: agentKeys.mutation(owner, "cancel-run"),
    mutationFn: (input: { runId: string; idempotencyKey: string }) =>
      api.cancelAgentRun(
        input.runId,
        requireIdempotencyKey("useCancelAgentRun", input.idempotencyKey),
      ),
    onSuccess: invalidate,
  });
}
