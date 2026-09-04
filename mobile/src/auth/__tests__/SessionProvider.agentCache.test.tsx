import {
  QueryClient,
  QueryClientProvider,
  timeoutManager,
  type CancelOptions,
  type QueryClientConfig,
  type QueryFilters,
  type QueryKey,
  type TimeoutProvider,
} from "@tanstack/react-query";
import { Pressable, Text } from "react-native";
import { act, create, type ReactTestRenderer } from "react-test-renderer";

import { PRIVATE_AGENT_ROOT } from "@/api/privateAgentCache";
import { ApiError } from "@/api/client";
import {
  useAgentConnections,
  useAgentConnection,
  useCancelAgentRun,
  useConfirmAgentHandoff,
  useCreateAgentConnection,
  usePreviewAgentHandoff,
  useReplyToAgentRun,
  useRotateAgentSigningSecret,
  useTestAgentConnection,
} from "@/api/hooks";
import { SessionProvider, useSession } from "@/auth/SessionProvider";

const profileA = {
  id: "user-a",
  email: "a@example.test",
  feature_flags: { external_agent_relay: true, voice_brain_dump: false },
};
const profileB = {
  ...profileA,
  id: "user-b",
  email: "b@example.test",
};
const profileC = {
  ...profileA,
  id: "user-c",
  email: "c@example.test",
};

type OwnedTimerId = ReturnType<typeof setTimeout>;

const systemTimers: TimeoutProvider<OwnedTimerId> = {
  setTimeout: (callback, delay) => setTimeout(callback, delay),
  clearTimeout: (id) => clearTimeout(id),
  setInterval: (callback, delay) => setInterval(callback, delay),
  clearInterval: (id) => clearInterval(id),
};

/**
 * Every timer React Query starts in this file, and how to stop it.
 *
 * Signing out removes queries the React tree is still observing — that is the
 * point of the purge. React Query answers by handing the observer a fresh query
 * under the new owner key and letting the old one go, and the old one schedules
 * its garbage-collection timer on the way out. By then the cache no longer holds
 * it, so `queryClient.clear()` cannot reach it and the default five-minute delay
 * keeps the Jest worker alive long after the suite is done.
 *
 * Owning the timer backend lets each test stop exactly what it started. The
 * alternatives are worse: shortening `gcTime` deletes the very window these
 * tests exercise, and `--forceExit` hides leaks instead of ending them.
 */
const pendingTimers = new Map<OwnedTimerId, () => void>();
const ownedTimers: TimeoutProvider<OwnedTimerId> = {
  setTimeout: (callback, delay) => {
    let id!: OwnedTimerId;
    id = systemTimers.setTimeout(() => {
      pendingTimers.delete(id);
      callback();
    }, delay);
    pendingTimers.set(id, () => clearTimeout(id));
    return id;
  },
  clearTimeout: (id) => {
    if (id !== undefined) {
      pendingTimers.delete(id);
    }
    clearTimeout(id);
  },
  setInterval: (callback, delay) => {
    const id = systemTimers.setInterval(callback, delay);
    pendingTimers.set(id, () => clearInterval(id));
    return id;
  },
  clearInterval: (id) => {
    if (id !== undefined) {
      pendingTimers.delete(id);
    }
    clearInterval(id);
  },
};
// Installed before any query work in this file, so no timer escapes the map.
timeoutManager.setTimeoutProvider(ownedTimers);

const liveClients: QueryClient[] = [];

/**
 * The QueryClient these tests use.
 *
 * It registers its cache for teardown and can suspend one private-agent cleanup
 * mid-flight: `resetPrivateAgentState` has exactly one await point —
 * cancelling the in-flight private queries — and that suspension is the window
 * in which the account being torn down can be replaced by a different one.
 * Holding the window open turns a timing race into a deterministic test; the
 * gate is always released by the test that armed it.
 */
class SessionTestQueryClient extends QueryClient {
  private gate: Promise<void> | null = null;

  constructor(config?: QueryClientConfig) {
    super(config);
    liveClients.push(this);
  }

  /** Suspends the next cleanup; returns the release that lets it finish. */
  pauseNextCleanup(): () => void {
    let release!: () => void;
    this.gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    return release;
  }

  override async cancelQueries<TTaggedQueryKey extends QueryKey = QueryKey>(
    filters?: QueryFilters<TTaggedQueryKey>,
    cancelOptions?: CancelOptions,
  ): Promise<void> {
    await super.cancelQueries(filters, cancelOptions);
    const gate = this.gate;
    if (gate) {
      this.gate = null;
      await gate;
    }
  }
}
const mockApi = {
  me: jest.fn().mockResolvedValue(profileA),
  login: jest.fn(),
  signup: jest.fn(),
  logout: jest.fn().mockResolvedValue(undefined),
  listAgentConnections: jest.fn().mockResolvedValue([]),
  getAgentConnection: jest.fn(),
  testAgentConnection: jest.fn(),
  previewAgentHandoff: jest.fn(),
  createAgentConnection: jest.fn(),
  rotateAgentSigningSecret: jest.fn(),
  confirmAgentHandoff: jest.fn(),
  replyToAgentRun: jest.fn(),
  cancelAgentRun: jest.fn(),
};
let clientOptions: {
  getSessionEpoch?: () => number;
  onUnauthorized?: (requestEpoch: number) => void;
};
let mockServerUrl = "https://brain-a.example.test/api";

jest.mock("@/api/client", () => ({
  ApiError: class ApiError extends Error {
    status: number;

    constructor(message: string, statusCode: number) {
      super(message);
      this.status = statusCode;
    }
  },
  createApiClient: (options: typeof clientOptions) => {
    clientOptions = options;
    return mockApi;
  },
}));

jest.mock("@/config/serverUrl", () => ({
  DEFAULT_SERVER_URL: "https://brain-a.example.test/api",
  currentServerUrl: jest.fn(() => mockServerUrl),
  loadServerUrl: jest.fn().mockResolvedValue("https://brain-a.example.test/api"),
  saveServerUrl: jest.fn(async (url: string) => {
    mockServerUrl = url;
    return url;
  }),
}));

function SessionHarness() {
  const session = useSession();
  const connections = useAgentConnections(session.agentRelayEnabled);
  return (
    <>
      <Text>{`${session.status}:${session.me?.id ?? "none"}`}</Text>
      <Text>
        {(connections.data ?? [])
          .map((connection: { name: string; agent_address: string }) =>
            `${connection.name}:${connection.agent_address}`,
          )
          .join("|") || "no private agents"}
      </Text>
      <Pressable accessibilityLabel="Sign out" onPress={() => session.signOut()} />
      <Pressable
        accessibilityLabel="Sign in B"
        onPress={() => session.signIn("b@example.test", "password")}
      />
      <Pressable accessibilityLabel="Refresh session" onPress={() => session.refreshMe()} />
    </>
  );
}

function RelayMutationHarness() {
  useAgentConnection("connection-1");
  const createConnection = useCreateAgentConnection();
  const testConnection = useTestAgentConnection();
  const rotateSigningSecret = useRotateAgentSigningSecret();
  const previewHandoff = usePreviewAgentHandoff("task-1");
  const confirmHandoff = useConfirmAgentHandoff("task-1");
  const reply = useReplyToAgentRun();
  const cancel = useCancelAgentRun();
  return (
    <>
      <Pressable
        accessibilityLabel="Create relay"
        onPress={() =>
          createConnection.mutate({
            payload: {
              name: "Hermes",
              agent_address: "https://agent.example.test/hook",
              credential: "secret",
              current_password: "password",
            },
            idempotencyKey: "create-key",
          })
        }
      />
      <Pressable
        accessibilityLabel="Test relay"
        onPress={() => testConnection.mutate("connection-1")}
      />
      <Pressable
        accessibilityLabel="Rotate signing secret"
        onPress={() =>
          rotateSigningSecret.mutate({
            connectionId: "connection-1",
            payload: { current_password: "password", expected_revision: 2 },
            idempotencyKey: "rotate-signing-key",
          })
        }
      />
      <Pressable
        accessibilityLabel="Preview handoff"
        onPress={() =>
          previewHandoff.mutate({
            connection_id: "connection-1",
            include_details: false,
            context_items: [],
          })
        }
      />
      <Pressable
        accessibilityLabel="Confirm handoff"
        onPress={() =>
          confirmHandoff.mutate({
            payload: {
              connection_id: "connection-1",
              include_details: false,
              context_items: [],
              manifest_token: "a".repeat(64),
              current_password: "password",
            },
            idempotencyKey: "handoff-key",
          })
        }
      />
      <Pressable
        accessibilityLabel="Reply to run"
        onPress={() =>
          reply.mutate({
            runId: "run-1",
            payload: { message: "Done", expected_revision: 3 },
            idempotencyKey: "reply-key",
          })
        }
      />
      <Pressable
        accessibilityLabel="Cancel run"
        onPress={() => cancel.mutate({ runId: "run-1", idempotencyKey: "cancel-key" })}
      />
    </>
  );
}

function text(renderer: ReactTestRenderer): string {
  const values: string[] = [];
  const visit = (value: unknown) => {
    if (typeof value === "string") values.push(value);
    else if (Array.isArray(value)) value.forEach(visit);
    else if (value && typeof value === "object" && "children" in value) {
      visit((value as { children: unknown }).children);
    }
  };
  visit(renderer.toJSON());
  return values.join(" ");
}

async function waitFor(condition: () => boolean): Promise<void> {
  for (let attempt = 0; attempt < 20; attempt += 1) {
    if (condition()) return;
    await act(async () => {
      await new Promise<void>((resolve) => setTimeout(resolve, 0));
    });
  }
  throw new Error("Condition was not reached");
}

describe("SessionProvider private agent cleanup", () => {
  beforeEach(() => {
    mockApi.me.mockReset().mockResolvedValue(profileA);
    mockApi.login.mockReset().mockResolvedValue(profileB);
    mockApi.logout.mockReset().mockResolvedValue(undefined);
    mockApi.listAgentConnections.mockReset().mockResolvedValue([]);
    mockApi.getAgentConnection.mockReset().mockResolvedValue({ id: "connection-1" });
    mockApi.testAgentConnection.mockReset().mockResolvedValue({ id: "connection-1" });
    mockApi.previewAgentHandoff.mockReset().mockResolvedValue({ manifest_token: "token" });
    mockApi.createAgentConnection.mockReset().mockResolvedValue({ id: "connection-1" });
    mockApi.rotateAgentSigningSecret.mockReset().mockResolvedValue({ id: "connection-1" });
    mockApi.confirmAgentHandoff.mockReset().mockResolvedValue({ id: "run-1" });
    mockApi.replyToAgentRun.mockReset().mockResolvedValue({ id: "run-1" });
    mockApi.cancelAgentRun.mockReset().mockResolvedValue({ id: "run-1" });
  });

  // Teardown belongs here, not at the end of each test body: a failing
  // assertion skips the rest of its test, and everything it started would
  // otherwise outlive it.
  afterEach(async () => {
    for (const client of liveClients.splice(0)) {
      client.clear();
    }
    for (const stop of pendingTimers.values()) {
      stop();
    }
    pendingTimers.clear();
  });

  it("forwards caller-owned keys through every remaining relay mutation hook", async () => {
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    let renderer!: ReactTestRenderer;
    await act(async () => {
      renderer = create(
        <QueryClientProvider client={client}>
          <SessionProvider>
            <RelayMutationHarness />
          </SessionProvider>
        </QueryClientProvider>,
      );
    });

    for (const accessibilityLabel of [
      "Create relay",
      "Test relay",
      "Rotate signing secret",
      "Preview handoff",
      "Confirm handoff",
      "Reply to run",
      "Cancel run",
    ]) {
      await act(async () => {
        renderer.root.findByProps({ accessibilityLabel }).props.onPress();
        await Promise.resolve();
      });
    }
    mockApi.rotateAgentSigningSecret.mockRejectedValueOnce(new ApiError("stale", 409, null));
    await act(async () => {
      renderer.root.findByProps({ accessibilityLabel: "Rotate signing secret" }).props.onPress();
      await Promise.resolve();
    });

    expect(mockApi.createAgentConnection.mock.calls[0][1]).toBe("create-key");
    expect(mockApi.getAgentConnection).toHaveBeenCalledWith("connection-1", expect.anything());
    // Test and preview take no relay key, so the hooks must forward nothing in
    // the key position — an extra argument here would be the mobile client
    // promising a dedupe the backend routes do not implement.
    expect(mockApi.testAgentConnection).toHaveBeenCalledWith("connection-1");
    expect(mockApi.testAgentConnection.mock.calls[0]).toHaveLength(1);
    expect(mockApi.previewAgentHandoff).toHaveBeenCalledWith(
      "task-1",
      expect.objectContaining({ connection_id: "connection-1" }),
    );
    expect(mockApi.previewAgentHandoff.mock.calls[0]).toHaveLength(2);
    expect(mockApi.rotateAgentSigningSecret.mock.calls[0][2]).toBe("rotate-signing-key");
    expect(mockApi.confirmAgentHandoff.mock.calls[0][2]).toBe("handoff-key");
    expect(mockApi.replyToAgentRun.mock.calls[0][2]).toBe("reply-key");
    expect(mockApi.cancelAgentRun).toHaveBeenCalledWith("run-1", "cancel-key");

    await act(async () => renderer.unmount());
    client.clear();
  });

  it("removes account A state before exposing signed-out UI and blocks a pending A response", async () => {
    const client = new QueryClient({
      defaultOptions: {
        queries: { retry: false, gcTime: 0 },
        mutations: { retry: false, gcTime: 0 },
      },
    });
    let resolveA!: (value: string[]) => void;
    const pendingA = new Promise<string[]>((resolve) => {
      resolveA = resolve;
    });
    const requestA = client.fetchQuery({
      queryKey: [...PRIVATE_AGENT_ROOT, "https://brain-a.example.test/api|user-a", "connections"],
      queryFn: () => pendingA,
    });
    const requestAOutcome = requestA.then(
      () => "resolved",
      () => "cancelled",
    );
    let renderer!: ReactTestRenderer;
    await act(async () => {
      renderer = create(
        <QueryClientProvider client={client}>
          <SessionProvider>
            <SessionHarness />
          </SessionProvider>
        </QueryClientProvider>,
      );
    });
    expect(text(renderer)).toContain("signed-in:user-a");

    await act(async () => {
      await renderer.root.findByProps({ accessibilityLabel: "Sign out" }).props.onPress();
    });
    expect(text(renderer)).toContain("signed-out:none");
    expect(
      client.getQueriesData({
        queryKey: [
          ...PRIVATE_AGENT_ROOT,
          "https://brain-a.example.test/api|user-a",
        ],
      }),
    ).toEqual([]);

    resolveA(["Account A endpoint"]);
    await expect(requestAOutcome).resolves.toBe("cancelled");
    await act(async () => {
      await Promise.resolve();
    });
    expect(
      client.getQueriesData({
        queryKey: [
          ...PRIVATE_AGENT_ROOT,
          "https://brain-a.example.test/api|user-a",
        ],
      }),
    ).toEqual([]);
    expect(text(renderer)).not.toContain("Account A endpoint");

    await act(async () => renderer.unmount());
    client.clear();
  });

  it("never flashes account A connection names or endpoints while switching to B", async () => {
    const client = new QueryClient({
      defaultOptions: {
        queries: { retry: false, gcTime: 0 },
        mutations: { retry: false, gcTime: 0 },
      },
    });
    let resolveA!: (value: { name: string; agent_address: string }[]) => void;
    let resolveB!: (value: { name: string; agent_address: string }[]) => void;
    const pendingA = new Promise<{ name: string; agent_address: string }[]>((resolve) => {
      resolveA = resolve;
    });
    const pendingB = new Promise<{ name: string; agent_address: string }[]>((resolve) => {
      resolveB = resolve;
    });
    mockApi.listAgentConnections.mockReturnValueOnce(pendingA).mockReturnValueOnce(pendingB);

    let renderer!: ReactTestRenderer;
    await act(async () => {
      renderer = create(
        <QueryClientProvider client={client}>
          <SessionProvider>
            <SessionHarness />
          </SessionProvider>
        </QueryClientProvider>,
      );
    });
    expect(text(renderer)).toContain("signed-in:user-a");

    await act(async () => {
      await renderer.root.findByProps({ accessibilityLabel: "Sign out" }).props.onPress();
    });
    await act(async () => {
      await renderer.root.findByProps({ accessibilityLabel: "Sign in B" }).props.onPress();
    });
    await waitFor(() => mockApi.listAgentConnections.mock.calls.length >= 2);
    expect(text(renderer)).toContain("signed-in:user-b");
    expect(text(renderer)).not.toContain("Account A agent");
    expect(text(renderer)).not.toContain("a-agent.example.test");

    resolveA([
      { name: "Account A agent", agent_address: "https://a-agent.example.test/relay" },
    ]);
    await act(async () => {
      await new Promise<void>((resolve) => setTimeout(resolve, 0));
    });
    expect(text(renderer)).not.toContain("Account A agent");
    expect(text(renderer)).not.toContain("a-agent.example.test");

    resolveB([
      { name: "Account B agent", agent_address: "https://b-agent.example.test/relay" },
    ]);
    await waitFor(() => text(renderer).includes("Account B agent"));
    expect(text(renderer)).toContain("Account B agent:https://b-agent.example.test/relay");

    await act(async () => renderer.unmount());
    client.clear();
  });

  it("ignores account A's late 401 after B signs in and preserves B's private cache", async () => {
    const client = new QueryClient({
      defaultOptions: {
        queries: { retry: false, gcTime: Infinity },
        mutations: { retry: false, gcTime: Infinity },
      },
    });
    let renderer!: ReactTestRenderer;
    await act(async () => {
      renderer = create(
        <QueryClientProvider client={client}>
          <SessionProvider>
            <SessionHarness />
          </SessionProvider>
        </QueryClientProvider>,
      );
    });
    await waitFor(() => text(renderer).includes("signed-in:user-a"));
    const accountAEpoch = clientOptions.getSessionEpoch?.();
    expect(accountAEpoch).toEqual(expect.any(Number));

    await act(async () => {
      await renderer.root.findByProps({ accessibilityLabel: "Sign out" }).props.onPress();
      await renderer.root.findByProps({ accessibilityLabel: "Sign in B" }).props.onPress();
    });
    await waitFor(() => text(renderer).includes("signed-in:user-b"));
    const bOwner = "https://brain-a.example.test/api|user-b";
    client.setQueryData([...PRIVATE_AGENT_ROOT, bOwner, "connections"], ["B private"]);
    client.setQueryData(["public", "sentinel"], "keep");

    await act(async () => {
      clientOptions.onUnauthorized?.(accountAEpoch as number);
      await Promise.resolve();
    });

    expect(text(renderer)).toContain("signed-in:user-b");
    expect(client.getQueryData([...PRIVATE_AGENT_ROOT, bOwner, "connections"])).toEqual([
      "B private",
    ]);
    expect(client.getQueryData(["public", "sentinel"])).toBe("keep");

    await act(async () => renderer.unmount());
    client.clear();
  });

  it("honours a current-scope 401 by signing out and purging private cache", async () => {
    const client = new QueryClient();
    let renderer!: ReactTestRenderer;
    await act(async () => {
      renderer = create(
        <QueryClientProvider client={client}>
          <SessionProvider>
            <SessionHarness />
          </SessionProvider>
        </QueryClientProvider>,
      );
    });
    await waitFor(() => text(renderer).includes("signed-in:user-a"));
    client.setQueryData([...PRIVATE_AGENT_ROOT, "private"], "erase");

    await act(async () => {
      clientOptions.onUnauthorized?.(clientOptions.getSessionEpoch?.() as number);
      await Promise.resolve();
    });
    await waitFor(() => text(renderer).includes("signed-out:none"));
    expect(client.getQueryData([...PRIVATE_AGENT_ROOT, "private"])).toBeUndefined();

    await act(async () => renderer.unmount());
    client.clear();
  });

  it("does not let a late login success overwrite a newer logout", async () => {
    let resolveLogin!: (value: typeof profileB) => void;
    mockApi.login.mockReturnValueOnce(
      new Promise<typeof profileB>((resolve) => {
        resolveLogin = resolve;
      }),
    );
    const client = new QueryClient();
    let renderer!: ReactTestRenderer;
    await act(async () => {
      renderer = create(
        <QueryClientProvider client={client}>
          <SessionProvider>
            <SessionHarness />
          </SessionProvider>
        </QueryClientProvider>,
      );
    });
    await waitFor(() => text(renderer).includes("signed-in:user-a"));

    void renderer.root.findByProps({ accessibilityLabel: "Sign in B" }).props.onPress();
    await act(async () => {
      await renderer.root.findByProps({ accessibilityLabel: "Sign out" }).props.onPress();
      resolveLogin(profileB);
      await Promise.resolve();
    });
    expect(text(renderer)).toContain("signed-out:none");

    await act(async () => renderer.unmount());
    client.clear();
  });

  /**
   * The purge itself — not just the state it guards — has to be scope-owned.
   *
   * A scope check taken before the cleanup starts is worthless by the time the
   * cleanup resumes: the account it was tearing down can have been replaced,
   * and the replacement's cache repopulated, while it was suspended. Both
   * cleanup entry points are held open here at exactly that point.
   */
  it("does not let a paused sign-out cleanup purge the account that replaced it", async () => {
    const client = new SessionTestQueryClient({
      defaultOptions: {
        queries: { retry: false },
        mutations: { retry: false },
      },
    });
    let renderer!: ReactTestRenderer;
    await act(async () => {
      renderer = create(
        <QueryClientProvider client={client}>
          <SessionProvider>
            <SessionHarness />
          </SessionProvider>
        </QueryClientProvider>,
      );
    });
    await waitFor(() => text(renderer).includes("signed-in:user-a"));
    const accountAEpoch = clientOptions.getSessionEpoch?.() as number;

    const releaseCleanup = client.pauseNextCleanup();
    await act(async () => {
      clientOptions.onUnauthorized?.(accountAEpoch);
      await new Promise<void>((resolve) => setTimeout(resolve, 0));
    });
    // A's sign-out owns the scope, but is suspended inside its own cleanup.
    expect(text(renderer)).toContain("signed-in:user-a");

    await act(async () => {
      await renderer.root.findByProps({ accessibilityLabel: "Sign in B" }).props.onPress();
    });
    await waitFor(() => text(renderer).includes("signed-in:user-b"));
    const bOwner = "https://brain-a.example.test/api|user-b";
    client.setQueryData([...PRIVATE_AGENT_ROOT, bOwner, "connections"], ["B private"]);

    await act(async () => {
      releaseCleanup();
      await new Promise<void>((resolve) => setTimeout(resolve, 0));
    });

    expect(client.getQueryData([...PRIVATE_AGENT_ROOT, bOwner, "connections"])).toEqual([
      "B private",
    ]);
    expect(text(renderer)).toContain("signed-in:user-b");

    await act(async () => renderer.unmount());
    client.clear();
  });

  it("does not let a paused sign-in cleanup purge the account that replaced it", async () => {
    mockApi.login.mockReset().mockResolvedValueOnce(profileB).mockResolvedValueOnce(profileC);
    const client = new SessionTestQueryClient({
      defaultOptions: {
        queries: { retry: false },
        mutations: { retry: false },
      },
    });
    let renderer!: ReactTestRenderer;
    await act(async () => {
      renderer = create(
        <QueryClientProvider client={client}>
          <SessionProvider>
            <SessionHarness />
          </SessionProvider>
        </QueryClientProvider>,
      );
    });
    await waitFor(() => text(renderer).includes("signed-in:user-a"));

    const releaseCleanup = client.pauseNextCleanup();
    await act(async () => {
      // Not awaited: this sign-in is deliberately left suspended mid-cleanup.
      void renderer.root.findByProps({ accessibilityLabel: "Sign in B" }).props.onPress();
      await new Promise<void>((resolve) => setTimeout(resolve, 0));
    });
    expect(text(renderer)).not.toContain("signed-in:user-b");

    await act(async () => {
      await renderer.root.findByProps({ accessibilityLabel: "Sign in B" }).props.onPress();
    });
    await waitFor(() => text(renderer).includes("signed-in:user-c"));
    const cOwner = "https://brain-a.example.test/api|user-c";
    client.setQueryData([...PRIVATE_AGENT_ROOT, cOwner, "connections"], ["C private"]);

    await act(async () => {
      releaseCleanup();
      await new Promise<void>((resolve) => setTimeout(resolve, 0));
    });

    expect(client.getQueryData([...PRIVATE_AGENT_ROOT, cOwner, "connections"])).toEqual([
      "C private",
    ]);
    expect(text(renderer)).toContain("signed-in:user-c");

    await act(async () => renderer.unmount());
    client.clear();
  });

  it("does not let a late probe error sign out a newer account", async () => {
    let rejectProbe!: (error: Error) => void;
    mockApi.me
      .mockImplementationOnce(() => Promise.resolve(profileA))
      .mockImplementationOnce(
        () =>
          new Promise((_, reject) => {
            rejectProbe = reject;
          }),
      );
    const client = new QueryClient();
    let renderer!: ReactTestRenderer;
    await act(async () => {
      renderer = create(
        <QueryClientProvider client={client}>
          <SessionProvider>
            <SessionHarness />
          </SessionProvider>
        </QueryClientProvider>,
      );
    });
    await waitFor(() => text(renderer).includes("signed-in:user-a"));
    void renderer.root.findByProps({ accessibilityLabel: "Refresh session" }).props.onPress();
    await act(async () => {
      await renderer.root.findByProps({ accessibilityLabel: "Sign in B" }).props.onPress();
      rejectProbe(new Error("late A failure"));
      await Promise.resolve();
    });
    expect(text(renderer)).toContain("signed-in:user-b");

    await act(async () => renderer.unmount());
    client.clear();
  });
});
