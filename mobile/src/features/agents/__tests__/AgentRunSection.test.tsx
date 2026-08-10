/**
 * The run monitor is the only place iOS reports what an external agent is
 * doing, so every assertion here is about honesty: the server's label is shown
 * verbatim, an unverified claim stays phrased as a claim, an unsafe link stays
 * inert, and a control the connector cannot honour is never offered.
 */

import { AgentRunSection } from "@/features/agents/AgentRunSection";
import { makeRun } from "@/test/agentFixtures";
import {
  getByLabel,
  pressText,
  queryByText,
  renderWithProviders,
  typeInto,
  visibleText,
} from "@/test/render";

const mockReply = jest.fn();
const mockCancel = jest.fn();

// jest-expo's expo-crypto stub returns no UUID, so pin one: every relay
// command must still carry an `Idempotency-Key`.
jest.mock("expo-crypto", () => ({ randomUUID: () => "idem_key_test" }));

jest.mock("@/auth/SessionProvider", () => {
  const api = {
    replyToAgentRun: (...args: unknown[]) => mockReply(...args),
    cancelAgentRun: (...args: unknown[]) => mockCancel(...args),
  };
  return {
    useApi: () => api,
    useSession: () => ({
      api,
      serverUrl: "https://brain.example.test/api",
      me: { id: "user-test" },
    }),
  };
});

function props(overrides: Partial<Parameters<typeof AgentRunSection>[0]> = {}) {
  return {
    runs: [],
    loading: false,
    error: null,
    online: true,
    onRunUpdated: jest.fn(),
    ...overrides,
  };
}

describe("AgentRunSection", () => {
  it("renders nothing for a task that was never handed to an agent", async () => {
    const { renderer, unmount } = await renderWithProviders(<AgentRunSection {...props()} />);

    expect(renderer.toJSON()).toBeNull();

    await unmount();
  });

  it("shows the server's state label verbatim rather than recomputing one", async () => {
    const run = makeRun({
      reported_state: "completed",
      primary_state_label: "Agent reported complete — Brain Buddy did not verify it",
      result_text: "Draft is in the repo.",
    });
    const { renderer, unmount } = await renderWithProviders(
      <AgentRunSection {...props({ runs: [run] })} />,
    );

    const text = visibleText(renderer);
    expect(text).toContain("Agent reported complete — Brain Buddy did not verify it");
    expect(text).toContain("My Claude Code box");
    expect(text).toContain("Draft is in the repo.");

    await unmount();
  });

  it("answers a blocked run and hands the updated run back to the feed", async () => {
    const run = makeRun({
      reported_state: "blocked",
      needs_user: true,
      primary_state_label: "Needs you",
      question_text: "Which repository should I open?",
      revision: 7,
    });
    const answered = makeRun({
      reported_state: "blocked",
      primary_state_label: "Needs you",
      question_text: "Which repository should I open?",
      reply_pending: true,
      revision: 3,
      run_version: 3,
    });
    mockReply.mockResolvedValue(answered);
    const onRunUpdated = jest.fn();

    const { renderer, unmount } = await renderWithProviders(
      <AgentRunSection {...props({ runs: [run], onRunUpdated })} />,
    );

    expect(visibleText(renderer)).toContain("Which repository should I open?");
    await typeInto(getByLabel(renderer, "Your answer"), "The brain_buddy repo");
    await pressText(renderer, "Send answer");

    expect(mockReply).toHaveBeenCalledWith(
      "run_1",
      { message: "The brain_buddy repo", expected_revision: 7 },
      "idem_key_test",
    );
    expect(onRunUpdated).toHaveBeenCalledWith(answered);

    await unmount();
  });

  it("states that replies are unsupported instead of offering an answer box", async () => {
    const run = makeRun({
      reported_state: "blocked",
      needs_user: true,
      primary_state_label: "Needs you",
      question_text: "Which repository should I open?",
      capabilities: { progress: true, reply: false, cancel: false },
    });

    const { renderer, unmount } = await renderWithProviders(
      <AgentRunSection {...props({ runs: [run] })} />,
    );

    expect(visibleText(renderer)).toContain("does not support replies");
    expect(queryByText(renderer, "Send answer")).toBeNull();

    await unmount();
  });

  it("refuses to queue a reply while offline", async () => {
    const run = makeRun({
      reported_state: "blocked",
      needs_user: true,
      primary_state_label: "Needs you",
      question_text: "Which repository should I open?",
    });

    const { renderer, unmount } = await renderWithProviders(
      <AgentRunSection {...props({ runs: [run], online: false })} />,
    );

    expect(visibleText(renderer)).toContain("You are offline");
    expect(queryByText(renderer, "Send answer")).toBeNull();
    expect(mockReply).not.toHaveBeenCalled();

    await unmount();
  });

  it("requests cancellation only when the connector disclosed it", async () => {
    const cancelled = makeRun({ cancel_requested: true, revision: 3 });
    mockCancel.mockResolvedValue(cancelled);
    const onRunUpdated = jest.fn();

    const { renderer, unmount } = await renderWithProviders(
      <AgentRunSection {...props({ runs: [makeRun()], onRunUpdated })} />,
    );
    await pressText(renderer, "Request cancellation");
    expect(mockCancel).toHaveBeenCalledWith("run_1", "idem_key_test");
    expect(onRunUpdated).toHaveBeenCalledWith(cancelled);
    await unmount();

    const noCancel = makeRun({ capabilities: { progress: true, reply: true, cancel: false } });
    const second = await renderWithProviders(
      <AgentRunSection {...props({ runs: [noCancel] })} />,
    );
    expect(queryByText(second.renderer, "Request cancellation")).toBeNull();
    await second.unmount();
  });

  it("keeps an unsafe result link as inert text and offers no way to open it", async () => {
    const run = makeRun({
      reported_state: "completed",
      primary_state_label: "Agent reported complete",
      result_link: "http://agent.example.test/result",
      result_link_interactive: false,
    });

    const { renderer, unmount } = await renderWithProviders(
      <AgentRunSection {...props({ runs: [run] })} />,
    );

    const text = visibleText(renderer);
    expect(text).toContain("http://agent.example.test/result");
    expect(text).toContain("plain text only");
    expect(queryByText(renderer, "Open result")).toBeNull();

    await unmount();
  });

  it("reports expiry as a retention fact and hides the expired content", async () => {
    const run = makeRun({
      content_expired: true,
      primary_state_label: "Agent reported complete",
      result_text: "should never render",
      progress_text: "should never render",
    });

    const { renderer, unmount } = await renderWithProviders(
      <AgentRunSection {...props({ runs: [run] })} />,
    );

    const text = visibleText(renderer);
    expect(text).toContain("Content expired under retention policy");
    expect(text).not.toContain("should never render");

    await unmount();
  });

  it("names the conditions Brain Buddy derived without blending them into the state", async () => {
    const run = makeRun({
      stopped_reporting: true,
      connection_disconnected: true,
      dispatch_state: "delivery_unconfirmed",
      primary_state_label: "Running",
    });

    const { renderer, unmount } = await renderWithProviders(
      <AgentRunSection {...props({ runs: [run] })} />,
    );

    const text = visibleText(renderer);
    expect(text).toContain("No report since the last contact");
    expect(text).toContain("did not cancel any work");
    expect(text).toContain("could not confirm");

    await unmount();
  });
});

/**
 * What the monitor does when the network is the thing that failed.
 *
 * A refresh that never reached the server says nothing about the run: the last
 * report is still the best answer anyone has. Hiding it behind an error screen
 * would lose real information, so it stays on screen with the staleness said
 * out loud — and only a *first* load with nothing to show is an error state.
 */
describe("AgentRunSection when a refresh fails", () => {
  it("keeps the cached run visible and says out loud that it may be stale", async () => {
    const run = makeRun({
      reported_state: "running",
      primary_state_label: "Running",
      progress_text: "Cloning the repo",
    });
    const onRetry = jest.fn();

    const { renderer, unmount } = await renderWithProviders(
      <AgentRunSection
        {...props({ runs: [run], error: new Error("Connection lost"), onRetry })}
      />,
    );

    const text = visibleText(renderer);
    expect(text).toContain("Running");
    expect(text).toContain("Cloning the repo");
    expect(text).toContain("could not reach the server just now");
    expect(text).toContain("may be out of date");

    await pressText(renderer, "Try again");
    expect(onRetry).toHaveBeenCalledTimes(1);

    await unmount();
  });

  it("stays an error and nothing else when the first load had nothing to show", async () => {
    const onRetry = jest.fn();

    const { renderer, unmount } = await renderWithProviders(
      <AgentRunSection {...props({ runs: [], error: new Error("Connection lost"), onRetry })} />,
    );

    const text = visibleText(renderer);
    expect(text).toContain("Connection lost");
    // No projection was ever received, so there is nothing to call stale.
    expect(text).not.toContain("may be out of date");
    expect(queryByText(renderer, "Running")).toBeNull();

    await unmount();
  });

  it("offers neither a reply nor a cancellation while offline", async () => {
    const run = makeRun({
      reported_state: "blocked",
      needs_user: true,
      primary_state_label: "Needs you",
      question_text: "Which repository should I open?",
    });

    const { renderer, unmount } = await renderWithProviders(
      <AgentRunSection
        {...props({ runs: [run], online: false, error: new Error("Connection lost") })}
      />,
    );

    // Both controls are withheld rather than shown and then failing, and the
    // cached question stays readable underneath.
    expect(queryByText(renderer, "Send answer")).toBeNull();
    expect(queryByText(renderer, "Request cancellation")).toBeNull();
    expect(visibleText(renderer)).toContain("Which repository should I open?");
    expect(visibleText(renderer)).toContain("You are offline");
    expect(mockReply).not.toHaveBeenCalled();
    expect(mockCancel).not.toHaveBeenCalled();

    await unmount();
  });
});
