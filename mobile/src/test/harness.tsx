/**
 * Render helpers that mount product code inside the providers it expects.
 *
 * `renderWithSession` boots the real `SessionProvider` and a real React Query
 * client over the fake backend, then waits for the session probe to settle, so
 * a test asserts against the same wiring the device runs.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react-native";
import type { ReactElement, ReactNode } from "react";
import { View } from "react-native";

import { SessionProvider, useSession } from "@/auth/SessionProvider";

export function makeQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      // A retry would turn every error-path assertion into a timeout.
      queries: { retry: false, gcTime: 0 },
      mutations: { retry: false },
    },
  });
}

/**
 * Holds children back until the session has settled, the way the app's own
 * `AuthGate` does — it keeps the splash up and routes nowhere while the status
 * is "loading". A screen mounted before that would see the default server URL
 * and a null profile, which is a state the device never renders.
 */
function SessionGate({ children }: { children: ReactNode }) {
  const { status } = useSession();
  return (
    <>
      <View testID={`session-${status}`} />
      {status === "loading" ? null : children}
    </>
  );
}

export function withProviders(children: ReactNode, queryClient: QueryClient) {
  return (
    <QueryClientProvider client={queryClient}>
      <SessionProvider>
        <SessionGate>{children}</SessionGate>
      </SessionProvider>
    </QueryClientProvider>
  );
}

export interface SessionRenderResult {
  queryClient: QueryClient;
  rerender: (ui: ReactElement) => Promise<void>;
  unmount: () => Promise<void>;
  /** Root test instance, for the rare query the screen helpers cannot express. */
  container: Awaited<ReturnType<typeof render>>["container"];
}

/**
 * Mount `ui` under a settled session. The caller must have installed a fake
 * backend that answers `GET /auth/me`.
 */
export async function renderWithSession(
  ui: ReactElement,
  { queryClient = makeQueryClient() }: { queryClient?: QueryClient } = {},
): Promise<SessionRenderResult> {
  const result = await render(withProviders(ui, queryClient));
  await waitFor(() => expect(screen.queryByTestId("session-loading")).toBeNull());
  return {
    queryClient,
    rerender: (next: ReactElement) => result.rerender(withProviders(next, queryClient)),
    unmount: result.unmount,
    container: result.container,
  };
}
