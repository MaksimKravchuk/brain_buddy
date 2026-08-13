import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Pressable, Text } from "react-native";
import { act, create, type ReactTestRenderer } from "react-test-renderer";

import {
  agentKeys,
  useCreateAgentConnection,
  useRotateAgentSigningSecret,
} from "@/api/hooks";

const publicConnection = {
  id: "connection-1",
  owner_id: "user-a",
  name: "Hermes",
  endpoint_url: "https://agent.example.test/hook",
  auth_header_name: "X-Agent-Key",
  status: "connected" as const,
  last_error_code: null,
  consecutive_failures: 0,
  stale: false,
  ready_for_handoff: true,
  capabilities: { receive_task: true, send_progress: true, send_result: true },
  last_test_error_code: null,
  last_contact_at: null,
  last_tested_at: null,
  stale_after_seconds: 300,
  created_at: "2026-08-13T00:00:00Z",
  revision: 1,
};

let mockEpoch = 1;
let mockServerUrl = "https://brain-a.example.test/api/";
let mockAccountId: string | null = "user-a";
const mockApi = {
  createAgentConnection: jest.fn(),
  rotateAgentSigningSecret: jest.fn(),
};

jest.mock("@/auth/SessionProvider", () => ({
  useSession: () => ({
    api: mockApi,
    serverUrl: mockServerUrl,
    accountId: mockAccountId,
    getIdentityEpoch: () => mockEpoch,
  }),
}));

type Deferred<T> = {
  promise: Promise<T>;
  resolve(value: T): void;
  reject(reason: unknown): void;
};
function deferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  return {
    promise: new Promise<T>((done, fail) => {
      resolve = done;
      reject = fail;
    }),
    resolve,
    reject,
  };
}

const hookSecrets: string[] = [];
const ordinaryResults: unknown[] = [];
const settlementCallbacks: string[] = [];
let asyncSettlement: Promise<unknown> | undefined;

function Harness() {
  const createConnection = useCreateAgentConnection({
    onSigningSecret: (secret) => hookSecrets.push(secret),
  });
  const rotateSecret = useRotateAgentSigningSecret({
    onSigningSecret: (secret) => hookSecrets.push(secret),
  });
  return (
    <>
      <Pressable
        accessibilityLabel="Create async"
        onPress={() => {
          asyncSettlement = createConnection.mutateAsync(
            {
              payload: {
                name: "Hermes",
                endpoint_url: "https://agent.example.test/hook",
                credential: "credential",
                current_password: "password",
              },
              idempotencyKey: "create-async",
            },
            {
              onSuccess: () => settlementCallbacks.push("call-success"),
              onError: () => settlementCallbacks.push("call-error"),
              onSettled: () => settlementCallbacks.push("call-settled"),
            },
          );
        }}
      />
      <Pressable
        accessibilityLabel="Create"
        onPress={() =>
          createConnection.mutate(
            {
              payload: {
                name: "Hermes",
                endpoint_url: "https://agent.example.test/hook",
                credential: "credential",
                current_password: "password",
              },
              idempotencyKey: `create-${mockApi.createAgentConnection.mock.calls.length}`,
            },
            { onSuccess: (result) => ordinaryResults.push(result) },
          )
        }
      />
      <Pressable
        accessibilityLabel="Rotate"
        onPress={() =>
          rotateSecret.mutate(
            {
              connectionId: "connection-1",
              payload: { current_password: "password", expected_revision: 1 },
              idempotencyKey: `rotate-${mockApi.rotateAgentSigningSecret.mock.calls.length}`,
            },
            { onSuccess: (result) => ordinaryResults.push(result) },
          )
        }
      />
      <Text testID="create-state">{JSON.stringify(createConnection.data ?? null)}</Text>
      <Text testID="create-error">{createConnection.error?.message ?? ""}</Text>
      <Text testID="rotate-state">{JSON.stringify(rotateSecret.data ?? null)}</Text>
    </>
  );
}

async function renderHarness(client: QueryClient): Promise<ReactTestRenderer> {
  let renderer!: ReactTestRenderer;
  await act(async () => {
    renderer = create(
      <QueryClientProvider client={client}>
        <Harness />
      </QueryClientProvider>,
    );
  });
  return renderer;
}

async function flush(): Promise<void> {
  await act(async () => {
    await new Promise<void>((resolve) => setTimeout(resolve, 0));
  });
}

describe("one-time signing-secret settlement", () => {
  beforeEach(() => {
    mockEpoch = 1;
    mockServerUrl = "https://brain-a.example.test/api/";
    mockAccountId = "user-a";
    hookSecrets.splice(0);
    ordinaryResults.splice(0);
    settlementCallbacks.splice(0);
    asyncSettlement = undefined;
    mockApi.createAgentConnection.mockReset();
    mockApi.rotateAgentSigningSecret.mockReset();
  });

  it.each([
    ["Create", mockApi.createAgentConnection],
    ["Rotate", mockApi.rotateAgentSigningSecret],
  ] as const)("delivers %s plaintext once while all ordinary result surfaces are redacted", async (label, endpoint) => {
    endpoint.mockResolvedValue({ ...publicConnection, inbound_signing_secret: "sk-plaintext" });
    const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
    const renderer = await renderHarness(client);

    await act(async () => {
      renderer.root.findByProps({ accessibilityLabel: label }).props.onPress();
    });
    await flush();

    expect(hookSecrets).toEqual(["sk-plaintext"]);
    expect(ordinaryResults).toEqual([publicConnection]);
    expect(renderer.root.findByProps({ testID: `${label.toLowerCase()}-state` }).props.children)
      .toBe(JSON.stringify(publicConnection));
    expect(JSON.stringify(client.getMutationCache().getAll())).not.toContain("sk-plaintext");

    await act(async () => renderer.unmount());
    client.clear();
  });

  it("rejects a dispatch whose logout epoch is stale before transport I/O", async () => {
    const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
    const renderer = await renderHarness(client);

    renderer.root.findByProps({ accessibilityLabel: "Create" }).props.onPress();
    mockEpoch += 1;
    await flush();

    expect(mockApi.createAgentConnection).not.toHaveBeenCalled();
    expect(hookSecrets).toEqual([]);
    expect(ordinaryResults).toEqual([]);

    await act(async () => renderer.unmount());
    client.clear();
  });

  it("promptly rejects stale mutateAsync without callbacks, canary retention, or an observer", async () => {
    const pending = deferred<typeof publicConnection & { inbound_signing_secret: string }>();
    mockApi.createAgentConnection.mockReturnValue(pending.promise);
    const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
    const renderer = await renderHarness(client);

    renderer.root.findByProps({ accessibilityLabel: "Create async" }).props.onPress();
    await flush();
    mockEpoch += 1;
    pending.reject(new Error("transport-rejection-canary"));

    await expect(asyncSettlement).rejects.toMatchObject({
      name: "StaleRelayMutationScopeError",
      message: "Relay mutation scope is stale.",
    });
    await flush();

    expect(settlementCallbacks).toEqual([]);
    expect(hookSecrets).toEqual([]);
    expect(JSON.stringify(client.getMutationCache().getAll())).not.toContain("transport-rejection-canary");
    expect(client.getMutationCache().getAll()).toHaveLength(0);
    expect(renderer.root.findByProps({ testID: "create-state" }).props.children).toBe("null");
    expect(renderer.root.findByProps({ testID: "create-error" }).props.children).toBe("");

    await act(async () => renderer.unmount());
    client.clear();
  });

  it("promptly rejects mutateAsync when its dispatch is stale before transport I/O", async () => {
    const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
    const renderer = await renderHarness(client);

    renderer.root.findByProps({ accessibilityLabel: "Create async" }).props.onPress();
    mockEpoch += 1;

    await expect(asyncSettlement).rejects.toMatchObject({
      name: "StaleRelayMutationScopeError",
      message: "Relay mutation scope is stale.",
    });
    await flush();

    expect(mockApi.createAgentConnection).not.toHaveBeenCalled();
    expect(settlementCallbacks).toEqual([]);
    expect(client.getMutationCache().getAll()).toHaveLength(0);
    expect(renderer.root.findByProps({ testID: "create-state" }).props.children).toBe("null");
    expect(renderer.root.findByProps({ testID: "create-error" }).props.children).toBe("");

    await act(async () => renderer.unmount());
    client.clear();
  });

  it.each([
    ["account switch", () => { mockEpoch += 1; mockAccountId = "user-b"; }],
    ["same-account origin switch", () => { mockEpoch += 1; mockServerUrl = "https://brain-b.example.test/api"; }],
    ["delayed 401 settlement", () => { mockEpoch += 1; mockAccountId = null; }],
  ] as const)("suppresses every stale %s settlement surface", async (_name, transition) => {
    const pending = deferred<typeof publicConnection & { inbound_signing_secret: string }>();
    mockApi.createAgentConnection.mockReturnValue(pending.promise);
    const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
    const owner = "https://brain-a.example.test/api|user-a";
    client.setQueryData(agentKeys.connections(owner), [publicConnection]);
    const renderer = await renderHarness(client);

    renderer.root.findByProps({ accessibilityLabel: "Create" }).props.onPress();
    await flush();
    expect(mockApi.createAgentConnection).toHaveBeenCalledTimes(1);
    transition();
    pending.resolve({ ...publicConnection, inbound_signing_secret: "stale-secret" });
    await flush();

    expect(hookSecrets).toEqual([]);
    expect(ordinaryResults).toEqual([]);
    expect(client.getQueryState(agentKeys.connections(owner))?.isInvalidated).toBe(false);
    expect(JSON.stringify(client.getMutationCache().getAll())).not.toContain("stale-secret");
    expect(client.getMutationCache().getAll()).toHaveLength(0);
    expect(renderer.root.findByProps({ testID: "create-state" }).props.children).toBe("null");
    expect(renderer.root.findByProps({ testID: "create-error" }).props.children).toBe("");

    await act(async () => renderer.unmount());
    client.clear();
  });

  it("settles only the current dispatch when overlapping requests cross an epoch", async () => {
    const older = deferred<typeof publicConnection & { inbound_signing_secret: string }>();
    const newer = deferred<typeof publicConnection & { inbound_signing_secret: string }>();
    mockApi.createAgentConnection
      .mockReturnValueOnce(older.promise)
      .mockReturnValueOnce(newer.promise);
    const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
    const renderer = await renderHarness(client);

    renderer.root.findByProps({ accessibilityLabel: "Create" }).props.onPress();
    await flush();
    mockEpoch += 1;
    renderer.root.findByProps({ accessibilityLabel: "Create" }).props.onPress();
    await flush();
    older.resolve({ ...publicConnection, inbound_signing_secret: "older-secret" });
    await flush();
    expect(client.getMutationCache().getAll()).toHaveLength(1);
    newer.resolve({ ...publicConnection, inbound_signing_secret: "newer-secret" });
    await flush();

    expect(hookSecrets).toEqual(["newer-secret"]);
    expect(ordinaryResults).toEqual([publicConnection]);
    expect(JSON.stringify(client.getMutationCache().getAll())).not.toContain("older-secret");

    await act(async () => renderer.unmount());
    client.clear();
  });
});
