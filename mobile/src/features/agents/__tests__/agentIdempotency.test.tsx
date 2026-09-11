/**
 * What a retry means to the relay.
 *
 * A reply or a cancellation that came back as an error may still have reached
 * the server — only the answer was lost. So the retry has to arrive under the
 * key the first attempt used, or the agent is asked twice. The other half of
 * the contract matters just as much: a genuinely different thing to say must
 * get a different key, or the second answer is silently deduplicated away.
 */

import { useState } from "react";
import { Pressable, Text } from "react-native";
import { act } from "react-test-renderer";
import { QueryClientProvider } from "@tanstack/react-query";

import { useConfirmAgentHandoff } from "@/api/hooks";
import type { AgentHandoffConfirmRequest } from "@/api/types";
import { AgentRunSection } from "@/features/agents/AgentRunSection";
import { makeRun } from "@/test/agentFixtures";
import { getByLabel, pressText, renderWithProviders, settle, typeInto } from "@/test/render";

const mockReply = jest.fn();
const mockCancel = jest.fn();
const mockConfirmHandoff = jest.fn();

// jest-expo's expo-crypto stub returns no UUID at all, and a stub pinned to one
// value would make "a new intent mints a new key" unfalsifiable. Hand out a
// sequence instead, so equality between two keys is a real claim.
const mockKeys = { issued: 0 };
jest.mock("expo-crypto", () => ({
  randomUUID: () => {
    mockKeys.issued += 1;
    return `idem_key_${mockKeys.issued}`;
  },
}));

jest.mock("@/auth/SessionProvider", () => {
  const api = {
    replyToAgentRun: (...args: unknown[]) => mockReply(...args),
    cancelAgentRun: (...args: unknown[]) => mockCancel(...args),
    confirmAgentHandoff: (...args: unknown[]) => mockConfirmHandoff(...args),
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

function props(overrides: Record<string, unknown> = {}) {
  return {
    runs: [],
    loading: false,
    error: null,
    online: true,
    onRunUpdated: jest.fn(),
    ...overrides,
  };
}

function blockedRun() {
  return makeRun({
    reported_state: "blocked",
    needs_user: true,
    primary_state_label: "Needs you",
    question_text: "Which repository should I open?",
  });
}

beforeEach(() => {
  mockKeys.issued = 0;
  mockReply.mockReset();
  mockCancel.mockReset();
  mockConfirmHandoff.mockReset();
});

describe("relay command idempotency", () => {
  it("mints distinct keys, so key equality below is a real assertion", async () => {
    const { renderer, unmount } = await renderWithProviders(
      <AgentRunSection {...props({ runs: [blockedRun()] })} />,
    );
    mockReply.mockResolvedValue(makeRun({ reply_pending: true }));

    await typeInto(getByLabel(renderer, "Your answer"), "The brain_buddy repo");
    await pressText(renderer, "Send answer");
    await settle();

    // The first reply settled, so the next answer is a new intent.
    await typeInto(getByLabel(renderer, "Your answer"), "The other repo");
    await pressText(renderer, "Send answer");
    await settle();

    expect(mockReply).toHaveBeenCalledTimes(2);
    expect(mockReply.mock.calls[1][2]).not.toBe(mockReply.mock.calls[0][2]);
    expect(mockReply.mock.calls[1][1]).toEqual({
      message: "The other repo",
      expected_revision: 2,
    });

    await unmount();
  });

  it("retries a rejected reply under the key the first attempt used", async () => {
    mockReply
      .mockRejectedValueOnce(new Error("Connection lost"))
      .mockResolvedValue(makeRun({ reply_pending: true }));

    const { renderer, unmount } = await renderWithProviders(
      <AgentRunSection {...props({ runs: [blockedRun()] })} />,
    );

    await typeInto(getByLabel(renderer, "Your answer"), "The brain_buddy repo");
    await pressText(renderer, "Send answer");
    await settle();

    // The answer is still in the box because nothing definitive happened, so
    // pressing send again is the same intent, not a second one.
    await pressText(renderer, "Send answer");
    await settle();

    expect(mockReply).toHaveBeenCalledTimes(2);
    expect(mockReply.mock.calls[1][2]).toBe(mockReply.mock.calls[0][2]);
    expect(mockReply.mock.calls[1][1]).toEqual({
      message: "The brain_buddy repo",
      expected_revision: 2,
    });

    await unmount();
  });

  it("reuses the frozen key and revision when the same question refreshes", async () => {
    mockReply
      .mockRejectedValueOnce(new Error("Connection lost"))
      .mockResolvedValue(makeRun({ reply_pending: true, revision: 4 }));
    const firstRun = blockedRun();
    const { renderer, client, unmount } = await renderWithProviders(
      <AgentRunSection {...props({ runs: [firstRun] })} />,
    );

    await typeInto(getByLabel(renderer, "Your answer"), "Use staging");
    await pressText(renderer, "Send answer");
    await settle();

    await act(async () => {
      renderer.update(
        <QueryClientProvider client={client}>
          <AgentRunSection
            {...props({ runs: [{ ...firstRun, revision: firstRun.revision + 1 }] })}
          />
        </QueryClientProvider>,
      );
    });
    await pressText(renderer, "Send answer");
    await settle();

    expect(mockReply).toHaveBeenCalledTimes(2);
    expect(mockReply.mock.calls[1][2]).toBe(mockReply.mock.calls[0][2]);
    expect(mockReply.mock.calls[1][1]).toEqual({
      message: "Use staging",
      expected_revision: firstRun.revision,
    });

    await unmount();
  });

  it("blocks a changed answer while the original reply outcome is ambiguous", async () => {
    mockReply.mockRejectedValue(new Error("Connection lost"));
    const { renderer, unmount } = await renderWithProviders(
      <AgentRunSection {...props({ runs: [blockedRun()] })} />,
    );

    await typeInto(getByLabel(renderer, "Your answer"), "Use staging");
    await pressText(renderer, "Send answer");
    await settle();
    await typeInto(getByLabel(renderer, "Your answer"), "Use production");
    await pressText(renderer, "Send answer");
    await settle();

    expect(mockReply).toHaveBeenCalledTimes(1);
    await unmount();
  });

  it("mints a new reply key when the displayed question materially changes", async () => {
    mockReply
      .mockRejectedValueOnce(new Error("Connection lost"))
      .mockResolvedValue(makeRun({ reply_pending: true, revision: 4 }));
    const firstRun = blockedRun();
    const { renderer, client, unmount } = await renderWithProviders(
      <AgentRunSection {...props({ runs: [firstRun] })} />,
    );

    await typeInto(getByLabel(renderer, "Your answer"), "Use staging");
    await pressText(renderer, "Send answer");
    await settle();

    const changedRun = {
      ...firstRun,
      revision: firstRun.revision + 1,
      question_text: "Which deployment target?",
    };
    await act(async () => {
      renderer.update(
        <QueryClientProvider client={client}>
          <AgentRunSection {...props({ runs: [changedRun] })} />
        </QueryClientProvider>,
      );
    });
    expect(getByLabel(renderer, "Your answer").props.value).toBe("");
    await typeInto(getByLabel(renderer, "Your answer"), "Use production");
    await pressText(renderer, "Send answer");
    await settle();

    expect(mockReply).toHaveBeenCalledTimes(2);
    expect(mockReply.mock.calls[1][2]).not.toBe(mockReply.mock.calls[0][2]);
    expect(mockReply.mock.calls[1][1]).toEqual({
      message: "Use production",
      expected_revision: changedRun.revision,
    });

    await unmount();
  });

  it("retries a rejected cancellation under the key the first attempt used", async () => {
    mockCancel
      .mockRejectedValueOnce(new Error("Connection lost"))
      .mockResolvedValue(makeRun({ cancel_requested: true }));

    const { renderer, unmount } = await renderWithProviders(
      <AgentRunSection {...props({ runs: [makeRun()] })} />,
    );

    await pressText(renderer, "Request cancellation");
    await settle();
    await pressText(renderer, "Request cancellation");
    await settle();

    expect(mockCancel).toHaveBeenCalledTimes(2);
    expect(mockCancel.mock.calls[1][1]).toBe(mockCancel.mock.calls[0][1]);

    await unmount();
  });
});

/** Presses "Confirm" as many times as the test asks, always with `payload`. */
function ConfirmHarness({ payload }: { payload: AgentHandoffConfirmRequest }) {
  const confirm = useConfirmAgentHandoff("task_1");
  const [attempts, setAttempts] = useState(0);
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel="Confirm"
      onPress={() => {
        setAttempts((count) => count + 1);
        confirm.mutate({
          payload,
          idempotencyKey: `agent-handoff-${payload.manifest_token}`,
        });
      }}
    >
      <Text>{`Confirm ${attempts}`}</Text>
    </Pressable>
  );
}

describe("hand-off confirmation idempotency", () => {
  const payload = (token: string): AgentHandoffConfirmRequest => ({
    connection_id: "conn_1",
    include_details: true,
    supporting_items: [],
    manifest_token: token,
    current_password: null,
  });

  it("keys a retried hand-off off the reviewed manifest token, not the clock", async () => {
    mockConfirmHandoff
      .mockRejectedValueOnce(new Error("Connection lost"))
      .mockResolvedValue(makeRun());

    const { renderer, unmount } = await renderWithProviders(
      <ConfirmHarness payload={payload("manifest_token_1")} />,
    );

    await pressText(renderer, "Confirm 0");
    await settle();
    await pressText(renderer, "Confirm 1");
    await settle();

    expect(mockConfirmHandoff).toHaveBeenCalledTimes(2);
    // Deterministic, so the retry of a reviewed hand-off returns the original
    // run rather than dispatching the task to the agent a second time.
    expect(mockConfirmHandoff.mock.calls[0][2]).toBe("agent-handoff-manifest_token_1");
    expect(mockConfirmHandoff.mock.calls[1][2]).toBe(mockConfirmHandoff.mock.calls[0][2]);

    await unmount();
  });

  it("treats a re-reviewed manifest as a different hand-off", async () => {
    mockConfirmHandoff.mockResolvedValue(makeRun());

    const first = await renderWithProviders(<ConfirmHarness payload={payload("manifest_token_1")} />);
    await pressText(first.renderer, "Confirm 0");
    await settle();
    await first.unmount();

    // Re-previewing mints a new token: what the user reviewed changed, so the
    // command must not be deduplicated against the earlier one.
    const second = await renderWithProviders(<ConfirmHarness payload={payload("manifest_token_2")} />);
    await pressText(second.renderer, "Confirm 0");
    await settle();
    await second.unmount();

    expect(mockConfirmHandoff.mock.calls[1][2]).toBe("agent-handoff-manifest_token_2");
    expect(mockConfirmHandoff.mock.calls[1][2]).not.toBe(mockConfirmHandoff.mock.calls[0][2]);
  });
});
