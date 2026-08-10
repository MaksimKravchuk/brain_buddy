import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Pressable, Text } from "react-native";
import { act, create, type ReactTestRenderer } from "react-test-renderer";

import { PRIVATE_AGENT_ROOT } from "@/api/privateAgentCache";
import { useAgentConnections } from "@/api/hooks";
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
const mockApi = {
  me: jest.fn().mockResolvedValue(profileA),
  login: jest.fn(),
  signup: jest.fn(),
  logout: jest.fn().mockResolvedValue(undefined),
  listAgentConnections: jest.fn().mockResolvedValue([]),
};

class MockApiError extends Error {
  status: number;

  constructor(message: string, statusCode: number) {
    super(message);
    this.status = statusCode;
  }
}

jest.mock("@/api/client", () => ({
  ApiError: MockApiError,
  createApiClient: () => mockApi,
}));

jest.mock("@/config/serverUrl", () => ({
  DEFAULT_SERVER_URL: "https://brain-a.example.test/api",
  loadServerUrl: jest.fn().mockResolvedValue("https://brain-a.example.test/api"),
  saveServerUrl: jest.fn(async (url: string) => url),
}));

function SessionHarness() {
  const session = useSession();
  const connections = useAgentConnections(session.agentRelayEnabled);
  return (
    <>
      <Text>{`${session.status}:${session.me?.id ?? "none"}`}</Text>
      <Text>
        {(connections.data ?? [])
          .map((connection: { name: string; endpoint_url: string }) =>
            `${connection.name}:${connection.endpoint_url}`,
          )
          .join("|") || "no private agents"}
      </Text>
      <Pressable accessibilityLabel="Sign out" onPress={() => session.signOut()} />
      <Pressable
        accessibilityLabel="Sign in B"
        onPress={() => session.signIn("b@example.test", "password")}
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
    let resolveA!: (value: { name: string; endpoint_url: string }[]) => void;
    let resolveB!: (value: { name: string; endpoint_url: string }[]) => void;
    const pendingA = new Promise<{ name: string; endpoint_url: string }[]>((resolve) => {
      resolveA = resolve;
    });
    const pendingB = new Promise<{ name: string; endpoint_url: string }[]>((resolve) => {
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
      { name: "Account A agent", endpoint_url: "https://a-agent.example.test/relay" },
    ]);
    await act(async () => {
      await new Promise<void>((resolve) => setTimeout(resolve, 0));
    });
    expect(text(renderer)).not.toContain("Account A agent");
    expect(text(renderer)).not.toContain("a-agent.example.test");

    resolveB([
      { name: "Account B agent", endpoint_url: "https://b-agent.example.test/relay" },
    ]);
    await waitFor(() => text(renderer).includes("Account B agent"));
    expect(text(renderer)).toContain("Account B agent:https://b-agent.example.test/relay");

    await act(async () => renderer.unmount());
    client.clear();
  });
});
