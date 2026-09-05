/**
 * What the compact list is allowed to ask the server.
 *
 * Existing-run summaries remain readable when rollout disables new handoffs.
 * The query is gated only by an authenticated owner and the task IDs currently
 * on screen: no owner means no request, while a signed-in owner is monitored
 * regardless of the rollout flag chosen by the consuming screen.
 */

import { Text } from "react-native";
import { act } from "react-test-renderer";

import { useAgentRunSummaries } from "@/api/hooks";
import { renderWithProviders, settle, visibleText } from "@/test/render";

const mockListSummaries = jest.fn();

jest.mock("@/auth/SessionProvider", () => ({
  useApi: () => ({
    listAgentRunSummaries: (...args: unknown[]) => mockListSummaries(...args),
  }),
  useSession: () => ({
    serverUrl: "https://brain-a.example.test/api",
    accountId: "user-a",
    me: { id: "user-a" },
    api: {
      listAgentRunSummaries: (...args: unknown[]) => mockListSummaries(...args),
    },
  }),
}));

function Probe({ taskIds, hasOwner, interval }: { taskIds: string[]; hasOwner: boolean; interval?: number }) {
  const summaries = useAgentRunSummaries(taskIds, hasOwner, interval);
  return <Text>{Object.keys(summaries.data ?? {}).join(",") || "no summaries"}</Text>;
}

beforeEach(() => {
  mockListSummaries.mockReset();
  mockListSummaries.mockResolvedValue({});
});

describe("useAgentRunSummaries", () => {
  it("asks nothing without an authenticated owner", async () => {
    const { renderer, unmount } = await renderWithProviders(
      <Probe taskIds={["task_1", "task_2"]} hasOwner={false} />,
    );
    await settle();

    expect(mockListSummaries).not.toHaveBeenCalled();
    expect(visibleText(renderer)).toContain("no summaries");

    await unmount();
  });

  it("asks nothing when no task is on screen", async () => {
    const { unmount } = await renderWithProviders(<Probe taskIds={[]} hasOwner />);
    await settle();

    expect(mockListSummaries).not.toHaveBeenCalled();

    await unmount();
  });

  it("asks only about the tasks currently listed and keeps the answer sparse", async () => {
    mockListSummaries.mockResolvedValue({
      task_2: {
        id: "run_1",
        task_id: "task_2",
        agent_name: "My Claude Code box",
        primary_state_label: "Needs you",
        needs_user: true,
        stopped_reporting: false,
        last_contact_at: "2026-08-09T09:05:00Z",
      },
    });

    const { renderer, client, unmount } = await renderWithProviders(
      <Probe taskIds={["task_1", "task_2"]} hasOwner />,
    );
    await settle();

    expect(mockListSummaries).toHaveBeenCalledTimes(1);
    expect(mockListSummaries.mock.calls[0][0]).toEqual(["task_1", "task_2"]);
    expect(
      client.getQueryData([
        "agents",
        "private",
        "https://brain-a.example.test/api|user-a",
        "summaries",
        ["task_1", "task_2"],
      ]),
    ).toBeDefined();
    // Tasks without a hand-off are simply absent rather than present-and-empty.
    expect(visibleText(renderer)).toBe("task_2");

    await unmount();
  });

  it("polls boundedly so externally changing compact summaries converge", async () => {
    jest.useFakeTimers({ doNotFake: ["nextTick"] });
    let unmount: (() => Promise<void>) | undefined;
    try {
      ({ unmount } = await renderWithProviders(
        <Probe taskIds={["task_1"]} hasOwner interval={10} />,
      ));
      // Flush observer notifications without advancing the polling interval.
      await act(async () => { await jest.advanceTimersByTimeAsync(0); });
      expect(mockListSummaries).toHaveBeenCalledTimes(1);
      await act(async () => { await jest.advanceTimersByTimeAsync(9); });
      expect(mockListSummaries).toHaveBeenCalledTimes(1);
      await act(async () => { await jest.advanceTimersByTimeAsync(1); });
      expect(mockListSummaries).toHaveBeenCalledTimes(2);
      await act(async () => { await jest.advanceTimersByTimeAsync(10); });
      expect(mockListSummaries).toHaveBeenCalledTimes(3);

      await unmount();
      await act(async () => { await jest.advanceTimersByTimeAsync(30); });
      expect(mockListSummaries).toHaveBeenCalledTimes(3);
    } finally {
      await unmount?.();
      jest.useRealTimers();
    }
  });
});
