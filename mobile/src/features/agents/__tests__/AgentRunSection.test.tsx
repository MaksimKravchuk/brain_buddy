/**
 * The run monitor is the only place iOS reports what an external agent is
 * doing, so every assertion here is about honesty: the server's label is shown
 * verbatim, an unverified claim stays phrased as a claim, an unsafe link stays
 * inert, and a control the connector cannot honour is never offered.
 */

import { AgentRunSection } from "@/features/agents/AgentRunSection";
import { makeManifest, makeRun } from "@/test/agentFixtures";
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
const mockCheckDelivery = jest.fn();

// jest-expo's expo-crypto stub returns no UUID, so pin one: every relay
// command must still carry an `Idempotency-Key`.
jest.mock("expo-crypto", () => ({ randomUUID: () => "idem_key_test" }));

jest.mock("@/auth/SessionProvider", () => {
  const api = {
    replyToAgentRun: (...args: unknown[]) => mockReply(...args),
    cancelAgentRun: (...args: unknown[]) => mockCancel(...args),
    checkAgentRunDelivery: (...args: unknown[]) => mockCheckDelivery(...args),
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

  it("clears a sensitive draft when the displayed question changes", async () => {
    const questionA = makeRun({
      reported_state: "blocked",
      needs_user: true,
      question_text: "Private question A",
      primary_state_label: "Needs you",
      run_version: 2,
    });
    const questionB = makeRun({
      reported_state: "blocked",
      needs_user: true,
      question_text: "Private question B",
      primary_state_label: "Needs you",
      run_version: 3,
    });
    const { renderer, rerender, unmount } = await renderWithProviders(
      <AgentRunSection {...props({ runs: [questionA] })} />,
    );
    await typeInto(getByLabel(renderer, "Your answer"), "Secret answer for A");

    await rerender(<AgentRunSection {...props({ runs: [questionB] })} />);

    expect(getByLabel(renderer, "Your answer").props.value).toBe("");
    await unmount();
  });

  it("clears a sensitive draft when the run terminalizes", async () => {
    const blocked = makeRun({
      reported_state: "blocked",
      needs_user: true,
      question_text: "Private question",
      primary_state_label: "Needs you",
    });
    const { renderer, rerender, unmount } = await renderWithProviders(
      <AgentRunSection {...props({ runs: [blocked] })} />,
    );
    await typeInto(getByLabel(renderer, "Your answer"), "Secret terminal draft");

    await rerender(
      <AgentRunSection
        {...props({
          runs: [makeRun({ reported_state: "completed", primary_state_label: "Complete" })],
        })}
      />,
    );
    await rerender(<AgentRunSection {...props({ runs: [blocked] })} />);

    expect(getByLabel(renderer, "Your answer").props.value).toBe("");
    await unmount();
  });

  it("does not carry a sensitive draft to another run target", async () => {
    const runA = makeRun({
      reported_state: "blocked",
      needs_user: true,
      question_text: "Run A question",
      primary_state_label: "Needs you",
    });
    const runB = makeRun({
      id: "run_2",
      reported_state: "blocked",
      needs_user: true,
      question_text: "Run B question",
      primary_state_label: "Needs you",
    });
    const { renderer, rerender, unmount } = await renderWithProviders(
      <AgentRunSection {...props({ runs: [runA] })} />,
    );
    await typeInto(getByLabel(renderer, "Your answer"), "Run A secret");

    await rerender(<AgentRunSection {...props({ runs: [runB] })} />);

    expect(getByLabel(renderer, "Your answer").props.value).toBe("");
    await unmount();
  });

  it("states that replies are unsupported instead of offering an answer box", async () => {
    const run = makeRun({
      reported_state: "blocked",
      needs_user: true,
      primary_state_label: "Needs you",
      question_text: "Which repository should I open?",
      capabilities: { reply: false, cancel: false },
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

    const noCancel = makeRun({ capabilities: { reply: true, cancel: false } });
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

  it("does not wall-clock reproject an authoritative feed projection", async () => {
    const run = makeRun({
      content_expired: false,
      content_expires_at: "2000-01-01T00:00:00Z",
      progress_text: "Authoritative retained progress",
    });
    const { renderer, unmount } = await renderWithProviders(
      <AgentRunSection {...props({ runs: [run] })} />,
    );

    const text = visibleText(renderer);
    expect(text).not.toContain("Content expired under retention policy");
    expect(text).toContain("Authoritative retained progress");

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
    // 014-FR-006: the agent reported, and that *is* the delivery evidence, so
    // the ambiguous-delivery sentence is now known false and is withdrawn.
    expect(text).not.toContain("could not confirm");

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

describe("AgentRunSection dispatch states", () => {
  it("014-SC-004 shows a queued exchange as Queued and never as Sent", async () => {
    const { renderer, unmount } = await renderWithProviders(
      <AgentRunSection
        {...props({
          runs: [
            makeRun({
              dispatch_state: "delivery_unconfirmed",
              exchange_state: "queued",
              exchange_open: true,
              reported_state: null,
              primary_state_label: "Queued",
            }),
          ],
        })}
      />,
    );

    const text = visibleText(renderer);
    expect(text).toContain("Queued");
    expect(text).toContain("Waiting for a free connection slot; nothing has been sent yet");
    expect(text).not.toContain("could not confirm the agent received");
    // A queued hand-off has provably not been sent, so there is nothing at the
    // agent to check on.
    expect(queryByText(renderer, "Check again")).toBeNull();

    await unmount();
  });

  it("014-FR-006 states a restart that never sent and re-offers the hand-off", async () => {
    const { renderer, unmount } = await renderWithProviders(
      <AgentRunSection
        {...props({
          runs: [
            makeRun({
              dispatch_state: "not_sent",
              dispatch_error_code: "restarted_before_send",
              reported_state: null,
              primary_state_label: "Not sent",
              // The frozen review is what makes the retry a *retry*.
              manifest: makeManifest(),
            }),
          ],
        })}
      />,
    );

    expect(visibleText(renderer)).toContain(
      "Brain Buddy restarted before this hand-off was sent. Nothing left Brain Buddy.",
    );
    expect(queryByText(renderer, "Try this hand-off again")).toBeTruthy();

    await unmount();
  });

  it("014-FR-006 names the rate-limited category on a hand-off that was refused", async () => {
    const { renderer, unmount } = await renderWithProviders(
      <AgentRunSection
        {...props({
          runs: [
            makeRun({
              dispatch_state: "not_sent",
              dispatch_error_code: "a2a_rate_limited",
              reported_state: null,
              primary_state_label: "Not sent",
            }),
          ],
        })}
      />,
    );

    expect(visibleText(renderer)).toContain("The agent is rate limiting.");

    await unmount();
  });

  it("014-FR-006 checks delivery with the run's own ids and never mints a new run", async () => {
    mockCheckDelivery.mockResolvedValue(
      makeRun({ dispatch_state: "sent", primary_state_label: "Sent" }),
    );
    const onRunUpdated = jest.fn();
    const { renderer, unmount } = await renderWithProviders(
      <AgentRunSection
        {...props({
          onRunUpdated,
          runs: [
            makeRun({
              dispatch_state: "delivery_unconfirmed",
              exchange_state: "closed",
              reported_state: null,
              primary_state_label: "Delivery unconfirmed",
            }),
          ],
        })}
      />,
    );

    expect(visibleText(renderer)).toContain(
      "Runs the same check again with the same correlation ID and the same message ID.",
    );
    const again = getByLabel(renderer, "Check again");
    // 44pt, like every other real decision on this surface.
    expect(again.props.style).toEqual(expect.objectContaining({ minHeight: 44 }));

    await pressText(renderer, "Check again");

    expect(mockCheckDelivery).toHaveBeenCalledWith(
      "run_1",
      { current_password: null },
      "idem_key_test",
    );

    await unmount();
  });

  it("014-FR-006 disables Check again offline and queues nothing", async () => {
    const { renderer, unmount } = await renderWithProviders(
      <AgentRunSection
        {...props({
          online: false,
          runs: [
            makeRun({
              dispatch_state: "delivery_unconfirmed",
              exchange_state: "closed",
              reported_state: null,
              primary_state_label: "Delivery unconfirmed",
            }),
          ],
        })}
      />,
    );

    const again = getByLabel(renderer, "Check again");
    expect(again.props.accessibilityState?.disabled).toBe(true);
    await pressText(renderer, "Check again");
    expect(mockCheckDelivery).not.toHaveBeenCalled();

    await unmount();
  });
});
