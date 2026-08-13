import {
  onlineManager,
  useMutation,
  type MutateOptions,
  type MutationFunction,
  type MutationFunctionContext,
  type UseMutationOptions,
  type UseMutationResult
} from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";

import { useAuthStore } from "../stores/authStore";
import { agentKeysFor } from "./agentHooks";

/** Relay commands are explicit user intents and must never wait in React Query's offline queue. */
export const RELAY_MUTATION_NETWORK_MODE = "always" as const;

export function isRelayOnline(): boolean {
  const browserOnline = typeof navigator === "undefined" || navigator.onLine;
  return browserOnline && onlineManager.isOnline();
}

export function requireRelayOnline(): void {
  if (!isRelayOnline()) {
    throw new Error("Offline — reconnect before sending an agent command.");
  }
}

function currentRelayScope(): string {
  const ownerId = useAuthStore.getState().user?.id ?? null;
  return agentKeysFor(ownerId).all[1];
}

/**
 * The relay scope each in-flight dispatch was issued under.
 *
 * A render cannot hold this. React Query re-reads a pending mutation's options
 * on every rerender under an unchanged mutation key, so a scope closed over at
 * render time is silently re-pointed at whatever session rendered last — and a
 * per-call callback is held by the observer, which a session change never
 * touches at all. React Query does build one context object per execution and
 * hand that same object to `onMutate` and to every settlement callback, both
 * hook-level and per-call, so it is what identifies one dispatch from inside a
 * callback. Keys are weak: a dispatch's scope is forgotten with its mutation.
 */
const dispatchScopes = new WeakMap<MutationFunctionContext, string>();

/**
 * Whether this dispatch's answer still belongs to the session that asked for it.
 *
 * An unrecorded dispatch settles nothing. The entry is written before the
 * caller's own `onMutate` runs, so a miss means the dispatch never started
 * here, and applying an owner-scoped relay response on that guess is the one
 * outcome worth ruling out.
 */
function settlesInDispatchScope(context: MutationFunctionContext): boolean {
  return dispatchScopes.get(context) === currentRelayScope();
}

/**
 * Relay intents execute immediately so the online guard can reject them rather
 * than letting React Query pause and replay them after connectivity returns.
 *
 * Every settlement — hook-level or per-call, success, error or settled — is
 * gated on the dispatch's own scope, so a command still in flight when the
 * owner, session or API origin changes can never write its answer into the
 * session that replaced it.
 */
export function useRelayMutation<TData, TError = Error, TVariables = void, TContext = unknown>(
  options: Omit<UseMutationOptions<TData, TError, TVariables, TContext>, "mutationFn" | "networkMode"> & {
    mutationFn: MutationFunction<TData, TVariables>;
  }
): UseMutationResult<TData, TError, TVariables, TContext> {
  // Settlement runs long after the render that dispatched it, and the caller's
  // callbacks are re-read at that moment rather than captured per render.
  const latest = useRef(options);
  latest.current = options;

  const mutation = useMutation<TData, TError, TVariables, TContext>({
    ...options,
    networkMode: RELAY_MUTATION_NETWORK_MODE,
    mutationFn: (variables, context) => {
      requireRelayOnline();
      return latest.current.mutationFn(variables, context);
    },
    onMutate: (variables, context) => {
      dispatchScopes.set(context, currentRelayScope());
      return latest.current.onMutate?.(variables, context) as Promise<TContext> | TContext;
    },
    onSuccess: (data, variables, onMutateResult, context) =>
      settlesInDispatchScope(context)
        ? latest.current.onSuccess?.(data, variables, onMutateResult, context)
        : undefined,
    onError: (error, variables, onMutateResult, context) =>
      settlesInDispatchScope(context)
        ? latest.current.onError?.(error, variables, onMutateResult, context)
        : undefined,
    onSettled: (data, error, variables, onMutateResult, context) =>
      settlesInDispatchScope(context)
        ? latest.current.onSettled?.(data, error, variables, onMutateResult, context)
        : undefined
  });

  // Stable across renders in React Query, which keeps both wrappers stable too:
  // call sites are free to put `mutate` in a dependency array.
  const { mutateAsync } = mutation;
  // Per-call callbacks are invoked by the observer, which builds its own context
  // object rather than passing the mutation's — so they are bound to this
  // dispatch by closure instead. Both capture points read the same store inside
  // the same synchronous dispatch, so they cannot disagree about the scope.
  const dispatch = useCallback(
    (variables: TVariables, callbacks?: MutateOptions<TData, TError, TVariables, TContext>) => {
      const dispatchScope = currentRelayScope();
      const stillDispatchScope = () => currentRelayScope() === dispatchScope;
      return mutateAsync(variables, {
        onSuccess: (data, sent, onMutateResult, context) =>
          stillDispatchScope() ? callbacks?.onSuccess?.(data, sent, onMutateResult, context) : undefined,
        onError: (error, sent, onMutateResult, context) =>
          stillDispatchScope() ? callbacks?.onError?.(error, sent, onMutateResult, context) : undefined,
        onSettled: (data, error, sent, onMutateResult, context) =>
          stillDispatchScope()
            ? callbacks?.onSettled?.(data, error, sent, onMutateResult, context)
            : undefined
      });
    },
    [mutateAsync]
  );

  // `mutate` is the fire-and-forget form: the rejection is reported through
  // the guarded callbacks and must not also surface as an unhandled rejection.
  const fireAndForget = useCallback(
    (variables: TVariables, callbacks?: MutateOptions<TData, TError, TVariables, TContext>) => {
      void dispatch(variables, callbacks).catch(() => undefined);
    },
    [dispatch]
  );

  return { ...mutation, mutate: fireAndForget, mutateAsync: dispatch };
}

/** Reactive connectivity for disabling relay controls before an intent is submitted. */
export function useRelayOnline(): boolean {
  const [online, setOnline] = useState(isRelayOnline);

  useEffect(() => {
    const refresh = () => setOnline(isRelayOnline());
    const unsubscribe = onlineManager.subscribe(refresh);
    window.addEventListener("online", refresh);
    window.addEventListener("offline", refresh);
    refresh();
    return () => {
      unsubscribe();
      window.removeEventListener("online", refresh);
      window.removeEventListener("offline", refresh);
    };
  }, []);

  return online;
}
