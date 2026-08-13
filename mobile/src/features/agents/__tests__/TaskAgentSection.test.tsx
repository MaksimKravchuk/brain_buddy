/**
 * The task-screen entry point for the external-agent relay: the "Hand to
 * agent" trigger, the review-then-confirm sheet, and the run monitor for that
 * one task, wired to the real feature flag and API hooks.
 */

import { TaskAgentSection } from "@/features/agents/TaskAgentSection";
import { useAgentRunsFeed, type AgentRunsPollRuntime } from "@/features/agents/useAgentRunsFeed";
import { makeConnection, makeManifest, makeRun, makeTask } from "@/test/agentFixtures";
import { useRef, useState } from "react";
import { Pressable, Text } from "react-native";
import { act } from "react-test-renderer";
import {
  getByLabel,
  pressText,
  queryByText,
  renderWithProviders,
  settle,
  visibleText,
} from "@/test/render";

const mockListConnections = jest.fn();
const mockListRuns = jest.fn();
const mockPreview = jest.fn();
const mockConfirm = jest.fn();
const mockInspectFeed = jest.fn();
const mockApi = {
  listAgentConnections: (...args: unknown[]) => mockListConnections(...args),
  listAgentRuns: (...args: unknown[]) => mockListRuns(...args),
  previewAgentHandoff: (...args: unknown[]) => mockPreview(...args),
  confirmAgentHandoff: (...args: unknown[]) => mockConfirm(...args),
};
let mockActiveApi = mockApi;
let mockAccountId = "user-test";
let mockServerUrl = "https://brain.example.test/api";
let mockServerTimeAnchor: { serverTimeMs: number; monotonicTimeMs: number } | null = {
  serverTimeMs: Date.parse("2026-08-09T12:00:00Z"),
  monotonicTimeMs: 1_000,
};

jest.mock("expo-crypto", () => ({ randomUUID: () => "idem_key_test" }));

// Keep this focused component test independent of the animated modal host.
// Sheet behavior has its own tests; here we verify the hand-off content and
// task integration without leaving animation timers alive after unmount.
jest.mock("@/components/Sheet", () => {
  const { View } = jest.requireActual("react-native") as typeof import("react-native");
  return {
    Sheet: ({ visible, children }: { visible: boolean; children: React.ReactNode }) =>
      visible ? <View>{children}</View> : null,
  };
});

jest.mock("react-native-safe-area-context", () => ({
  useSafeAreaInsets: () => ({ top: 0, left: 0, right: 0, bottom: 0 }),
}));

jest.mock("@/auth/SessionProvider", () => ({
  useApi: () => mockActiveApi,
  useSession: () => ({
    api: mockActiveApi,
    serverUrl: mockServerUrl,
    accountId: mockAccountId,
    serverTimeAnchor: mockServerTimeAnchor,
    me: { id: "user-test" },
  }),
}));

function props(overrides: Partial<Parameters<typeof TaskAgentSection>[0]> = {}) {
  return {
    task: makeTask(),
    projectName: null,
    tagNames: [],
    enabled: true,
    ...overrides,
  };
}

beforeEach(() => {
  jest.spyOn(performance, "now").mockReturnValue(1_000);
  mockActiveApi = mockApi;
  mockAccountId = "user-test";
  mockServerUrl = "https://brain.example.test/api";
  mockServerTimeAnchor = { serverTimeMs: FIXED_NOW, monotonicTimeMs: 1_000 };
  mockListConnections.mockReset();
  mockListRuns.mockReset();
  mockPreview.mockReset();
  mockConfirm.mockReset();
  mockInspectFeed.mockReset();
  mockListRuns.mockResolvedValue([]);
});

afterEach(() => {
  jest.restoreAllMocks();
});

describe("TaskAgentSection", () => {
  it("loads and renders existing runs but hides new handoff when the feature flag is off", async () => {
    mockListRuns.mockResolvedValue([
      makeRun({ primary_state_label: "Needs you", needs_user: true, question_text: "Which repo?" }),
    ]);
    const { renderer, unmount } = await renderWithProviders(
      <TaskAgentSection {...props({ enabled: false })} />,
    );
    await settle();

    expect(visibleText(renderer)).toContain("Needs you");
    expect(visibleText(renderer)).toContain("Which repo?");
    expect(queryByText(renderer, "Hand to agent")).toBeNull();
    expect(mockListRuns).toHaveBeenCalledWith("task_1");
    expect(mockListConnections).not.toHaveBeenCalled();

    await unmount();
  });

  it("offers Hand to agent, and dispatching a run surfaces it in the run monitor", async () => {
    mockListConnections.mockResolvedValue([makeConnection()]);
    const manifest = makeManifest();
    mockPreview.mockResolvedValue(manifest);
    const dispatched = makeRun({ primary_state_label: "Sent" });
    mockConfirm.mockResolvedValue(dispatched);

    const { renderer, unmount } = await renderWithProviders(<TaskAgentSection {...props()} />);
    await settle();

    await pressText(renderer, "Hand to agent");
    await settle();
    await settle();
    expect(visibleText(renderer)).toContain("My Claude Code box");

    await pressText(renderer, "My Claude Code box");
    await settle();
    expect(mockPreview).toHaveBeenCalled();
    expect(visibleText(renderer)).toContain("Exactly what will be sent");

    await pressText(renderer, "Send to My Claude Code box");
    await settle();

    expect(mockConfirm).toHaveBeenCalled();
    expect(queryByText(renderer, "Hand to agent")).not.toBeNull();
    expect(visibleText(renderer)).toContain("Sent");

    await unmount();
  });

  it("shows an existing run's state without requiring the sheet to be opened", async () => {
    mockListConnections.mockResolvedValue([makeConnection()]);
    mockListRuns.mockResolvedValue([
      makeRun({ primary_state_label: "Needs you", needs_user: true, question_text: "Which repo?" }),
    ]);

    const { renderer, unmount } = await renderWithProviders(<TaskAgentSection {...props()} />);
    await settle();

    expect(visibleText(renderer)).toContain("Needs you");
    expect(visibleText(renderer)).toContain("Which repo?");
    expect(getByLabel(renderer, "Your answer")).not.toBeNull();

    await unmount();
  });

  it("uses the authoritative server anchor instead of the consumer wall clock", async () => {
    mockListRuns.mockResolvedValue([
      makeRun({
        progress_text: "Still retained by server time",
        content_expires_at: "2026-08-09T12:00:01Z",
      }),
    ]);
    const dateNow = jest.spyOn(Date, "now").mockReturnValue(Date.parse("2036-08-09T12:00:00Z"));
    const { renderer, unmount } = await renderWithProviders(<TaskAgentSection {...props()} />);
    await settle();

    expect(visibleText(renderer)).toContain("Still retained by server time");

    dateNow.mockRestore();
    await unmount();
  });
});

const FIXED_NOW = Date.parse("2026-08-09T12:00:00Z");

interface ScheduledPoll {
  callback: () => void;
  delay: number;
  cancelled: boolean;
}

/** A poll runtime that keeps every timer it was handed, armed or cancelled. */
function recordingRuntime(): {
  runtime: AgentRunsPollRuntime;
  scheduled: ScheduledPoll[];
  armed: () => ScheduledPoll[];
} {
  const scheduled: ScheduledPoll[] = [];
  return {
    runtime: {
      now: () => 1_000,
      schedule: (callback, delay) => {
        const entry: ScheduledPoll = { callback, delay, cancelled: false };
        scheduled.push(entry);
        return () => {
          entry.cancelled = true;
        };
      },
    },
    scheduled,
    armed: () => scheduled.filter((entry) => !entry.cancelled),
  };
}

function FeedProbe({ runtime, taskId = "task_1" }: { runtime: AgentRunsPollRuntime; taskId?: string }) {
  const feed = useAgentRunsFeed(taskId, true, runtime);
  return (
    <Pressable onPress={() => feed.absorb(makeRun())}>
      <Text>{`Absorb ${feed.runs.length}`}</Text>
    </Pressable>
  );
}

function FeedScopeHarness({
  runtime,
  apiB,
}: {
  runtime: AgentRunsPollRuntime;
  apiB: typeof mockApi;
}) {
  const [taskId, setTaskId] = useState("task_a");
  const [, forceApiRender] = useState(0);
  const feed = useAgentRunsFeed(taskId, true, runtime);
  // Stands in for a mutation that captured the callback under one scope and
  // resolves after the user has already moved to another.
  const capturedAbsorb = useRef(feed.absorb);
  return (
    <>
      <Pressable onPress={() => setTaskId("task_b")}>
        <Text>Switch task</Text>
      </Pressable>
      <Pressable
        onPress={() => {
          mockActiveApi = apiB;
          mockAccountId = "user-b";
          forceApiRender((version) => version + 1);
        }}
      >
        <Text>Switch account</Text>
      </Pressable>
      <Pressable
        onPress={() => {
          capturedAbsorb.current = feed.absorb;
        }}
      >
        <Text>Capture absorb</Text>
      </Pressable>
      <Pressable
        onPress={() =>
          capturedAbsorb.current(
            makeRun({ id: "run_a", task_id: "task_a", progress_text: "Absorbed A" }),
          )
        }
      >
        <Text>Replay absorb</Text>
      </Pressable>
      <Pressable onPress={() => feed.refresh()}>
        <Text>Refresh feed</Text>
      </Pressable>
      <Pressable onPress={() => mockInspectFeed(feed.runs)}>
        <Text>Inspect feed</Text>
      </Pressable>
      <Pressable
        onPress={() =>
          feed.absorb(
            makeRun({ id: "run_b", run_version: 10, revision: 10, progress_text: "B absorbed" }),
          )
        }
      >
        <Text>Absorb B update</Text>
      </Pressable>
      <Text>{feed.runs.map((run) => run.progress_text).join("|") || "empty"}</Text>
    </>
  );
}

function FeedExpiryProbe({ runtime }: { runtime: AgentRunsPollRuntime }) {
  const feed = useAgentRunsFeed("task_1", true, runtime);
  const run = feed.runs[0];
  return <Text>{run ? `${run.content_expired}:${run.progress_text ?? "redacted"}` : "empty"}</Text>;
}

describe("useAgentRunsFeed absorb polling", () => {
  it("clears task A immediately and ignores its delayed response after switching to task B", async () => {
    let resolveA!: (runs: ReturnType<typeof makeRun>[]) => void;
    mockListRuns
      .mockImplementationOnce(() => new Promise((resolve) => { resolveA = resolve; }))
      .mockResolvedValueOnce([
        makeRun({ id: "run_b", task_id: "task_b", progress_text: "Private B" }),
      ]);
    const runtime: AgentRunsPollRuntime = { schedule: () => () => undefined };
    const { renderer, unmount } = await renderWithProviders(
      <FeedScopeHarness runtime={runtime} apiB={mockApi} />,
    );

    await pressText(renderer, "Switch task");
    expect(visibleText(renderer)).not.toContain("Private A");
    await settle();
    expect(visibleText(renderer)).toContain("Private B");

    resolveA([makeRun({ id: "run_a", task_id: "task_a", progress_text: "Private A" })]);
    await settle();
    expect(visibleText(renderer)).toContain("Private B");
    expect(visibleText(renderer)).not.toContain("Private A");
    await unmount();
  });

  it("clears account A immediately and ignores its delayed response after the API identity changes", async () => {
    let resolveA!: (runs: ReturnType<typeof makeRun>[]) => void;
    const apiA = {
      ...mockApi,
      listAgentRuns: jest.fn(() => new Promise<ReturnType<typeof makeRun>[]>((resolve) => {
        resolveA = resolve;
      })),
    };
    const apiB = {
      ...mockApi,
      listAgentRuns: jest.fn().mockResolvedValue([
        makeRun({ id: "run_b", task_id: "task_a", progress_text: "Account B private" }),
      ]),
    };
    mockActiveApi = apiA;
    const runtime: AgentRunsPollRuntime = { schedule: () => () => undefined };
    const { renderer, unmount } = await renderWithProviders(
      <FeedScopeHarness runtime={runtime} apiB={apiB} />,
    );

    await pressText(renderer, "Switch account");
    expect(visibleText(renderer)).not.toContain("Account A private");
    await settle();
    expect(visibleText(renderer)).toContain("Account B private");

    resolveA([makeRun({ id: "run_a", task_id: "task_a", progress_text: "Account A private" })]);
    await settle();
    expect(visibleText(renderer)).toContain("Account B private");
    expect(visibleText(renderer)).not.toContain("Account A private");
    await unmount();
  });

  it("arms no timer for task B when task A's late response lands", async () => {
    let resolveA!: (runs: ReturnType<typeof makeRun>[]) => void;
    mockListRuns
      .mockImplementationOnce(() => new Promise((resolve) => { resolveA = resolve; }))
      .mockResolvedValueOnce([
        makeRun({
          id: "run_b",
          task_id: "task_b",
          dispatch_state: "not_sent",
          primary_state_label: "Not sent",
          content_expired: true,
        }),
      ]);
    const { runtime, scheduled, armed } = recordingRuntime();
    const { renderer, unmount } = await renderWithProviders(
      <FeedScopeHarness runtime={runtime} apiB={mockApi} />,
    );

    await pressText(renderer, "Switch task");
    await settle();
    // Task B is neither pollable nor awaiting a retention deadline.
    expect(armed()).toHaveLength(0);

    resolveA([makeRun({ id: "run_a", task_id: "task_a", progress_text: "Private A" })]);
    await settle();

    expect(armed()).toHaveLength(0);
    expect(scheduled).toHaveLength(0);
    expect(mockListRuns).toHaveBeenCalledTimes(2);

    await unmount();
  });

  it("keeps every account B run and its monotonic versions after account A resolves late", async () => {
    let resolveA!: (runs: ReturnType<typeof makeRun>[]) => void;
    const apiA = {
      ...mockApi,
      listAgentRuns: jest.fn(() => new Promise<ReturnType<typeof makeRun>[]>((resolve) => {
        resolveA = resolve;
      })),
    };
    const apiB = {
      ...mockApi,
      listAgentRuns: jest
        .fn()
        .mockResolvedValueOnce([
          makeRun({ id: "run_b", run_version: 9, revision: 9, progress_text: "B newest" }),
          makeRun({ id: "run_b_other", run_version: 7, revision: 7, progress_text: "B other" }),
        ])
        .mockResolvedValueOnce([
          makeRun({ id: "run_b", run_version: 4, revision: 4, progress_text: "B rolled back" }),
          makeRun({
            id: "run_b_other",
            run_version: 3,
            revision: 3,
            progress_text: "B other rolled back",
          }),
        ]),
    };
    mockActiveApi = apiA;
    const { runtime } = recordingRuntime();
    const { renderer, unmount } = await renderWithProviders(
      <FeedScopeHarness runtime={runtime} apiB={apiB} />,
    );

    await pressText(renderer, "Switch account");
    await settle();
    expect(visibleText(renderer)).toContain("B newest");
    expect(visibleText(renderer)).toContain("B other");

    resolveA([makeRun({ id: "run_a", progress_text: "Account A private" })]);
    await settle();

    await pressText(renderer, "Absorb B update");
    await pressText(renderer, "Inspect feed");
    expect(mockInspectFeed).toHaveBeenLastCalledWith([
      expect.objectContaining({ id: "run_b", run_version: 10, revision: 10 }),
      expect.objectContaining({ id: "run_b_other", run_version: 7, revision: 7 }),
    ]);

    // Account A's answer must not erase the snapshot the next poll merges onto,
    // or an out-of-order response would roll account B's projection backwards.
    await pressText(renderer, "Refresh feed");
    await settle();
    expect(apiB.listAgentRuns).toHaveBeenCalledTimes(2);
    await pressText(renderer, "Inspect feed");
    expect(mockInspectFeed).toHaveBeenLastCalledWith([
      expect.objectContaining({ id: "run_b", run_version: 10, revision: 10 }),
      expect.objectContaining({ id: "run_b_other", run_version: 7, revision: 7 }),
    ]);

    await unmount();
  });

  it("leaves task B's armed poll alone when a callback captured under task A fires", async () => {
    mockListRuns
      .mockResolvedValueOnce([
        makeRun({
          id: "run_a",
          task_id: "task_a",
          dispatch_state: "not_sent",
          content_expired: true,
        }),
      ])
      .mockResolvedValueOnce([makeRun({ id: "run_b", task_id: "task_b" })]);
    const { runtime, scheduled, armed } = recordingRuntime();
    const { renderer, unmount } = await renderWithProviders(
      <FeedScopeHarness runtime={runtime} apiB={mockApi} />,
    );
    await settle();

    await pressText(renderer, "Capture absorb");
    await pressText(renderer, "Switch task");
    await settle();
    const taskBPoll = armed()[0];
    expect(armed()).toHaveLength(1);

    await pressText(renderer, "Replay absorb");

    // The stale absorb must neither cancel task B's timer nor arm its own.
    expect(taskBPoll.cancelled).toBe(false);
    expect(scheduled).toHaveLength(1);

    taskBPoll.cancelled = true;
    await act(async () => taskBPoll.callback());
    await settle();
    expect(mockListRuns).toHaveBeenCalledTimes(3);
    expect(mockListRuns).toHaveBeenLastCalledWith("task_b");

    await unmount();
  });

  it("arms exactly one poll when the first handoff follows an initially empty list", async () => {
    mockListRuns
      .mockResolvedValueOnce([])
      .mockResolvedValueOnce([makeRun({ run_version: 2, progress_text: "Polled update" })]);
    const scheduled: { callback: () => void; delay: number; cancelled: boolean }[] = [];
    const runtime: AgentRunsPollRuntime = {
      schedule: (callback, delay) => {
        const entry = { callback, delay, cancelled: false };
        scheduled.push(entry);
        return () => {
          entry.cancelled = true;
        };
      },
    };
    const { renderer, unmount } = await renderWithProviders(<FeedProbe runtime={runtime} />);
    await settle();
    expect(scheduled).toHaveLength(0);

    await pressText(renderer, "Absorb 0");
    expect(scheduled.filter((entry) => !entry.cancelled)).toHaveLength(1);
    await pressText(renderer, "Absorb 1");
    expect(scheduled.filter((entry) => !entry.cancelled)).toHaveLength(1);

    const firstPoll = scheduled.find((entry) => !entry.cancelled);
    if (!firstPoll) {
      throw new Error("Expected an armed poll");
    }
    firstPoll.cancelled = true;
    await act(async () => firstPoll.callback());
    await settle();

    expect(mockListRuns).toHaveBeenCalledTimes(2);
    expect(scheduled.filter((entry) => !entry.cancelled)).toHaveLength(1);

    await unmount();
    expect(scheduled.filter((entry) => !entry.cancelled)).toHaveLength(0);
  });

  it("uses its single wake timer to redact UI at an earlier retention deadline", async () => {
    let now = 1_000;
    const scheduled: { callback: () => void; delay: number; cancelled: boolean }[] = [];
    const runtime: AgentRunsPollRuntime = {
      now: () => now,
      schedule: (callback, delay) => {
        const entry = { callback, delay, cancelled: false };
        scheduled.push(entry);
        return () => {
          entry.cancelled = true;
        };
      },
    };
    mockListRuns.mockResolvedValue([
      makeRun({
        progress_text: "Private progress",
        content_expires_at: "2026-08-09T12:00:01Z",
      }),
    ]);
    const { renderer, unmount } = await renderWithProviders(<FeedExpiryProbe runtime={runtime} />);
    await settle();

    expect(visibleText(renderer)).toBe("false:Private progress");
    expect(scheduled.filter((entry) => !entry.cancelled)).toHaveLength(1);
    expect(scheduled.find((entry) => !entry.cancelled)?.delay).toBe(1000);

    now = 2_000;
    const wake = scheduled.find((entry) => !entry.cancelled);
    if (!wake) {
      throw new Error("Expected an expiry wake");
    }
    wake.cancelled = true;
    await act(async () => wake.callback());
    await settle();

    expect(visibleText(renderer)).toBe("true:redacted");
    expect(mockListRuns).toHaveBeenCalledTimes(1);
    await unmount();
    expect(scheduled.filter((entry) => !entry.cancelled)).toHaveLength(0);
  });

  it("clamps a retention wake beyond the native timer ceiling", async () => {
    const { runtime, scheduled, armed } = recordingRuntime();
    mockListRuns.mockResolvedValue([
      makeRun({
        dispatch_state: "sent",
        reported_state: "completed",
        content_expires_at: "2026-09-08T12:00:00Z",
      }),
    ]);
    const { unmount } = await renderWithProviders(<FeedExpiryProbe runtime={runtime} />);
    await settle();

    expect(armed()).toHaveLength(1);
    expect(armed()[0].delay).toBe(2_147_483_647);
    expect(scheduled).toHaveLength(1);
    await unmount();
  });

  it("fails closed and arms no retention timer without an authoritative server anchor", async () => {
    mockServerTimeAnchor = null;
    const { runtime, scheduled, armed } = recordingRuntime();
    mockListRuns.mockResolvedValue([
      makeRun({
        dispatch_state: "sent",
        reported_state: "completed",
        progress_text: "Must not survive without an anchor",
        content_expires_at: "2026-09-08T12:00:00Z",
      }),
    ]);
    const { renderer, unmount } = await renderWithProviders(<FeedExpiryProbe runtime={runtime} />);
    await settle();

    expect(visibleText(renderer)).toBe("true:redacted");
    expect(armed()).toHaveLength(0);
    expect(scheduled).toHaveLength(0);
    await unmount();
  });
});
