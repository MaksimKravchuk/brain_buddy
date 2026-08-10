/**
 * The task-screen entry point for the external-agent relay: the "Hand to
 * agent" trigger, the review-then-confirm sheet, and the run monitor for that
 * one task, wired to the real feature flag and API hooks.
 */

import { TaskAgentSection } from "@/features/agents/TaskAgentSection";
import { makeConnection, makeManifest, makeRun, makeTask } from "@/test/agentFixtures";
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
const mockApi = {
  listAgentConnections: (...args: unknown[]) => mockListConnections(...args),
  listAgentRuns: (...args: unknown[]) => mockListRuns(...args),
  previewAgentHandoff: (...args: unknown[]) => mockPreview(...args),
  confirmAgentHandoff: (...args: unknown[]) => mockConfirm(...args),
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
  useApi: () => mockApi,
  useSession: () => ({
    api: mockApi,
    serverUrl: "https://brain.example.test/api",
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
  mockListConnections.mockReset();
  mockListRuns.mockReset();
  mockPreview.mockReset();
  mockConfirm.mockReset();
  mockListRuns.mockResolvedValue([]);
});

describe("TaskAgentSection", () => {
  it("renders nothing and calls no agent API when the feature flag is off", async () => {
    const { renderer, unmount } = await renderWithProviders(
      <TaskAgentSection {...props({ enabled: false })} />,
    );

    expect(renderer.toJSON()).toBeNull();
    expect(mockListRuns).not.toHaveBeenCalled();
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
});
