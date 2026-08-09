/**
 * What the compact list is allowed to ask the server.
 *
 * The summaries endpoint is gated behind the account's relay flag — with the
 * flag off the backend answers 404, so asking at all would only manufacture an
 * error for a capability the user cannot see. The flag reaches the query as its
 * `enabled` condition, which is exactly what these tests pin down: off means no
 * request, and on means a request about the visible tasks and no others.
 */

import { Text } from "react-native";

import { useAgentRunSummaries } from "@/api/hooks";
import { renderWithProviders, settle, visibleText } from "@/test/render";

const mockListSummaries = jest.fn();

jest.mock("@/auth/SessionProvider", () => ({
  useApi: () => ({
    listAgentRunSummaries: (...args: unknown[]) => mockListSummaries(...args),
  }),
}));

function Probe({ taskIds, enabled }: { taskIds: string[]; enabled: boolean }) {
  const summaries = useAgentRunSummaries(taskIds, enabled);
  return <Text>{Object.keys(summaries.data ?? {}).join(",") || "no summaries"}</Text>;
}

beforeEach(() => {
  mockListSummaries.mockReset();
  mockListSummaries.mockResolvedValue({});
});

describe("useAgentRunSummaries", () => {
  it("asks nothing at all while the relay flag is off", async () => {
    const { renderer, unmount } = await renderWithProviders(
      <Probe taskIds={["task_1", "task_2"]} enabled={false} />,
    );
    await settle();

    expect(mockListSummaries).not.toHaveBeenCalled();
    expect(visibleText(renderer)).toContain("no summaries");

    await unmount();
  });

  it("asks nothing when no task is on screen, flag or not", async () => {
    const { unmount } = await renderWithProviders(<Probe taskIds={[]} enabled />);
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

    const { renderer, unmount } = await renderWithProviders(
      <Probe taskIds={["task_1", "task_2"]} enabled />,
    );
    await settle();

    expect(mockListSummaries).toHaveBeenCalledTimes(1);
    expect(mockListSummaries.mock.calls[0][0]).toEqual(["task_1", "task_2"]);
    // Tasks without a hand-off are simply absent rather than present-and-empty.
    expect(visibleText(renderer)).toBe("task_2");

    await unmount();
  });
});
