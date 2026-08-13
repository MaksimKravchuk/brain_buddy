import { useState } from "react";
import { Pressable, Text } from "react-native";
import { act } from "react-test-renderer";

import {
  agentKeys,
  type AgentRunsExpiryRuntime,
  useAgentRuns,
  useDisconnectAgentConnection,
  useRotateAgentCredential,
} from "@/api/hooks";
import type { AgentRunResponse } from "@/api/types";
import { makeConnection, makeRun } from "@/test/agentFixtures";
import { pressText, renderWithProviders, settle, visibleText } from "@/test/render";

const mockListRuns = jest.fn();
const mockRotate = jest.fn();
const mockDisconnect = jest.fn();
let mockServerTimeAnchor: { serverTimeMs: number; monotonicTimeMs: number } | null = null;
let mockSessionStatus = "signed-in";
let mockOwner = "user-test";

jest.mock("@/auth/SessionProvider", () => {
  const api = {
    listAgentRuns: (...args: unknown[]) => mockListRuns(...args),
    rotateAgentCredential: (...args: unknown[]) => mockRotate(...args),
    disconnectAgentConnection: (...args: unknown[]) => mockDisconnect(...args),
  };
  return {
    useApi: () => api,
    useSession: () => ({
      api,
      serverUrl: "https://brain.example.test/api",
      status: mockSessionStatus,
      me: null,
      accountId: mockOwner,
      serverTimeAnchor: mockServerTimeAnchor,
    }),
  };
});

function Probe({ runtime }: { runtime: AgentRunsExpiryRuntime }) {
  const runs = useAgentRuns("task_1", true, runtime);
  const run = runs.data?.[0];
  return <Text>{run ? `${run.content_expired}:${run.progress_text ?? "redacted"}` : "loading"}</Text>;
}

function createControlledRuntime(initialNow: number) {
  let now = initialNow;
  const scheduled: { callback: () => void; delay: number; cancelled: boolean }[] = [];
  const runtime: AgentRunsExpiryRuntime = {
    now: () => now,
    schedule: (callback, delay) => {
      const entry = { callback, delay, cancelled: false };
      scheduled.push(entry);
      return () => {
        entry.cancelled = true;
      };
    },
  };
  return {
    runtime,
    scheduled,
    setNow: (next: number) => {
      now = next;
    },
  };
}

describe("useAgentRuns local expiry", () => {
  beforeEach(() => {
    mockListRuns.mockReset();
    mockRotate.mockReset();
    mockDisconnect.mockReset();
    mockServerTimeAnchor = null;
    mockSessionStatus = "signed-in";
    mockOwner = "user-test";
  });

  it("redacts from server-anchored time rather than the device wall clock", async () => {
    const start = Date.parse("2026-08-09T12:00:00Z");
    const clock = createControlledRuntime(50_000);
    mockServerTimeAnchor = { serverTimeMs: start, monotonicTimeMs: 50_000 };
    mockListRuns.mockResolvedValue([
      makeRun({
        progress_text: "Private progress",
        content_expires_at: "2026-08-09T12:00:01Z",
      }),
    ]);
    const { renderer, client, unmount } = await renderWithProviders(
      <Probe runtime={clock.runtime} />,
    );
    await settle();

    expect(visibleText(renderer)).toBe("false:Private progress");
    expect(mockListRuns).toHaveBeenCalledTimes(1);
    expect(clock.scheduled).toHaveLength(1);
    expect(clock.scheduled[0].delay).toBe(1000);

    clock.setNow(50_999);
    expect(visibleText(renderer)).toBe("false:Private progress");

    clock.setNow(51_000);
    await act(async () => {
      clock.scheduled[0].callback();
    });
    await settle();

    const cached = client.getQueryData<AgentRunResponse[]>(
      agentKeys.taskRuns("https://brain.example.test/api|user-test", "task_1"),
    );
    expect(cached?.[0]).toMatchObject({ content_expired: true, progress_text: null });
    expect(visibleText(renderer)).toBe("true:redacted");
    expect(mockListRuns).toHaveBeenCalledTimes(1);

    await unmount();
  });

  it("ignores a stale timer callback after the expiry owner unmounts", async () => {
    const start = Date.parse("2026-08-09T12:00:00Z");
    const clock = createControlledRuntime(100);
    mockServerTimeAnchor = { serverTimeMs: start, monotonicTimeMs: 100 };
    mockListRuns.mockResolvedValue([
      makeRun({ progress_text: "Private progress", content_expires_at: "2026-08-09T12:00:01Z" }),
    ]);
    const rendered = await renderWithProviders(<Probe runtime={clock.runtime} />);
    await settle();
    const key = agentKeys.taskRuns("https://brain.example.test/api|user-test", "task_1");
    const before = rendered.client.getQueryData(key);

    await rendered.unmount();
    expect(clock.scheduled[0].cancelled).toBe(true);
    rendered.client.setQueryData(key, before);
    clock.setNow(1_100);
    clock.scheduled[0].callback();

    expect(rendered.client.getQueryData(key)).toBe(before);
  });

  it("fails closed offline when no authoritative server clock is available", async () => {
    mockSessionStatus = "signed-in-offline";
    const clock = createControlledRuntime(9_000_000);
    mockListRuns.mockResolvedValue([
      makeRun({ progress_text: "Private progress", content_expires_at: "2000-01-01T00:00:00Z" }),
    ]);
    const { renderer, unmount } = await renderWithProviders(<Probe runtime={clock.runtime} />);
    await settle();

    expect(visibleText(renderer)).toBe("true:redacted");
    expect(clock.scheduled).toHaveLength(0);
    await unmount();
  });
});

function StableIntentHarness() {
  const rotate = useRotateAgentCredential();
  const disconnect = useDisconnectAgentConnection();
  const [attempts, setAttempts] = useState(0);
  const connection = makeConnection();
  return (
    <>
      <Pressable
        onPress={() => {
          setAttempts((value) => value + 1);
          rotate.mutate({
            connectionId: connection.id,
            payload: {
              credential: "sealed-new",
              current_password: "password",
              expected_revision: connection.revision,
            },
            idempotencyKey: "rotate-intent-stable",
          });
        }}
      >
        <Text>{`Rotate ${attempts}`}</Text>
      </Pressable>
      <Pressable
        onPress={() =>
          disconnect.mutate({
            connectionId: connection.id,
            payload: { current_password: "password", expected_revision: connection.revision },
            idempotencyKey: "disconnect-intent-stable",
          })
        }
      >
        <Text>Disconnect</Text>
      </Pressable>
    </>
  );
}

describe("connection mutation intent ownership", () => {
  it("passes caller-owned stable rotate and disconnect idempotency keys", async () => {
    mockRotate.mockRejectedValue(new Error("ambiguous transport failure"));
    mockDisconnect.mockRejectedValue(new Error("ambiguous transport failure"));
    const { renderer, unmount } = await renderWithProviders(<StableIntentHarness />);

    await pressText(renderer, "Rotate 0");
    await settle();
    await pressText(renderer, "Rotate 1");
    await settle();
    await pressText(renderer, "Disconnect");
    await settle();

    expect(mockRotate.mock.calls.map((call) => call[2])).toEqual([
      "rotate-intent-stable",
      "rotate-intent-stable",
    ]);
    expect(mockDisconnect.mock.calls[0][2]).toBe("disconnect-intent-stable");

    await unmount();
  });
});

type RotateInput = Parameters<ReturnType<typeof useRotateAgentCredential>["mutate"]>[0];
type DisconnectInput = Parameters<ReturnType<typeof useDisconnectAgentConnection>["mutate"]>[0];

const ROTATE_PAYLOAD = {
  credential: "sealed-new",
  current_password: "password",
  expected_revision: 4,
} as const;
const DISCONNECT_PAYLOAD = { current_password: "password", expected_revision: 4 } as const;

function refusalOf(error: unknown): string {
  return error instanceof Error ? error.message : "none";
}

/**
 * Drives both relay mutations with whatever the caller supplied — including
 * nothing at all, which only a JavaScript caller or a regressed signature can
 * express. `intentKey` of `undefined` omits the property entirely rather than
 * sending an explicit `undefined`.
 */
function SuppliedIntentHarness({ intentKey }: { intentKey: string | undefined }) {
  const rotate = useRotateAgentCredential();
  const disconnect = useDisconnectAgentConnection();
  const intent = intentKey === undefined ? {} : { idempotencyKey: intentKey };
  return (
    <>
      <Pressable
        onPress={() =>
          rotate.mutate({
            connectionId: "conn_1",
            payload: { ...ROTATE_PAYLOAD },
            ...intent,
          } as RotateInput)
        }
      >
        <Text>Rotate</Text>
      </Pressable>
      <Pressable
        onPress={() =>
          disconnect.mutate({
            connectionId: "conn_1",
            payload: { ...DISCONNECT_PAYLOAD },
            ...intent,
          } as DisconnectInput)
        }
      >
        <Text>Disconnect</Text>
      </Pressable>
      <Text>{`rotate:${refusalOf(rotate.error)}`}</Text>
      <Text>{`disconnect:${refusalOf(disconnect.error)}`}</Text>
    </>
  );
}

describe.each([
  ["an omitted", undefined],
  ["an empty", ""],
  ["a blank", "   "],
])("relay mutations with %s idempotency key", (_label, intentKey) => {
  beforeEach(() => {
    mockRotate.mockReset();
    mockDisconnect.mockReset();
    mockRotate.mockResolvedValue(makeConnection());
    mockDisconnect.mockResolvedValue(makeConnection());
  });

  it("never reaches the credential rotation endpoint", async () => {
    const { renderer, unmount } = await renderWithProviders(
      <SuppliedIntentHarness intentKey={intentKey} />,
    );

    await pressText(renderer, "Rotate");
    await settle();

    expect(mockRotate).not.toHaveBeenCalled();
    expect(visibleText(renderer)).toContain("rotate:useRotateAgentCredential");
    expect(visibleText(renderer)).toContain("caller-owned Idempotency-Key");

    await unmount();
  });

  it("never reaches the disconnect endpoint", async () => {
    const { renderer, unmount } = await renderWithProviders(
      <SuppliedIntentHarness intentKey={intentKey} />,
    );

    await pressText(renderer, "Disconnect");
    await settle();

    expect(mockDisconnect).not.toHaveBeenCalled();
    expect(visibleText(renderer)).toContain("disconnect:useDisconnectAgentConnection");
    expect(visibleText(renderer)).toContain("caller-owned Idempotency-Key");

    await unmount();
  });
});

describe("relay mutations with a caller-owned idempotency key", () => {
  beforeEach(() => {
    mockRotate.mockReset();
    mockDisconnect.mockReset();
    mockRotate.mockResolvedValue(makeConnection());
    mockDisconnect.mockResolvedValue(makeConnection());
  });

  it("forwards the key and body byte-for-byte, normalising neither", async () => {
    const { renderer, unmount } = await renderWithProviders(
      <SuppliedIntentHarness intentKey="  padded-intent  " />,
    );

    await pressText(renderer, "Rotate");
    await settle();
    await pressText(renderer, "Disconnect");
    await settle();

    expect(mockRotate).toHaveBeenCalledWith("conn_1", ROTATE_PAYLOAD, "  padded-intent  ");
    expect(mockDisconnect).toHaveBeenCalledWith("conn_1", DISCONNECT_PAYLOAD, "  padded-intent  ");

    await unmount();
  });
});
