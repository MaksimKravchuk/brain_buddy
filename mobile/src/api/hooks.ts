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
} from "@tanstack/react-query";

import { ApiError } from "@/api/client";

import { useApi, useSession } from "@/auth/SessionProvider";
import type {
  ProjectResponse,
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
import { cacheKey, isForgottenKey } from "@/features/tasks/storageKeys";
import { newIdempotencyKey } from "@/utils/ids";

export const taskKeys = {
  root: ["tasks"] as const,
  list: (filters: Omit<TaskListFilters, "cursor">) => ["tasks", "list", filters] as const,
  detail: (taskId: string) => ["tasks", "detail", taskId] as const,
  projects: ["tasks", "projects"] as const,
  tags: ["tasks", "tags"] as const,
};

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
      if (isForgottenKey(key)) {
        return;
      }
      const now = Date.now();
      const current = await readClassificationCache({ store: AsyncStorage, key, now });
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
      try {
        const projects = await api.listProjects(signal);
        cacheListsInBackground(serverUrl, accountId, {
          projects: cacheableEntries(projects),
        });
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
      try {
        const tags = await api.listTags(signal);
        cacheListsInBackground(serverUrl, accountId, { tags: cacheableEntries(tags) });
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
