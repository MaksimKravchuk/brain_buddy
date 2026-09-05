/** Deterministic ordering coverage for hand-off previews. */
import { agentKeys } from "@/api/hooks";
import { HandoffSheet } from "@/features/agents/HandoffSheet";
import { makeConnection, makeManifest, makeTask } from "@/test/agentFixtures";
import {
  getByLabel,
  pressLabel,
  pressText,
  queryByText,
  renderWithProviders,
  settle,
  visibleText,
} from "@/test/render";
import { QueryClientProvider } from "@tanstack/react-query";
import { Linking } from "react-native";
import { act, type ReactTestInstance, type ReactTestRenderer } from "react-test-renderer";

const mockListConnections = jest.fn();
const mockPreview = jest.fn();
const mockConfirm = jest.fn();
const mockApi = {
  listAgentConnections: (...args: unknown[]) => mockListConnections(...args),
  previewAgentHandoff: (...args: unknown[]) => mockPreview(...args),
  confirmAgentHandoff: (...args: unknown[]) => mockConfirm(...args),
};

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
    accountId: "user-test",
    me: { id: "user-test" },
  }),
}));

interface Deferred<T> {
  promise: Promise<T>;
  resolve: (value: T) => void;
  reject: (reason: unknown) => void;
}

function deferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

function props() {
  return {
    visible: true,
    onClose: jest.fn(),
    task: makeTask(),
    projectName: "Launch",
    tagNames: ["Writing"],
    onDispatched: jest.fn(),
  };
}

function pressableForText(renderer: ReactTestRenderer, text: string): ReactTestInstance {
  let node = queryByText(renderer, text);
  if (!node) {
    throw new Error(`No node showing ${text}`);
  }
  while (node && node.props.accessibilityRole !== "button") {
    node = node.parent;
  }
  if (!node) {
    throw new Error(`No button showing ${text}`);
  }
  return node;
}

function currentSendButton(renderer: ReactTestRenderer): ReactTestInstance {
  const matches = renderer.root.findAll(
    (node) =>
      typeof node.props.children === "string" &&
      (node.props.children === "Send" || node.props.children.startsWith("Send to ")),
    { deep: true },
  );
  const text = matches[matches.length - 1];
  if (!text) {
    throw new Error(`No Send button.\n${visibleText(renderer)}`);
  }
  let node: ReactTestInstance | null = text;
  while (node && node.props.accessibilityRole !== "button") {
    node = node.parent;
  }
  if (!node) {
    throw new Error("Send text has no button ancestor");
  }
  return node;
}

function isDisabled(node: ReactTestInstance): boolean {
  return node.props.disabled === true || node.props.accessibilityState?.disabled === true;
}

beforeEach(() => {
  mockListConnections.mockReset();
  mockPreview.mockReset();
  mockConfirm.mockReset();
  mockListConnections.mockResolvedValue([
    makeConnection(),
    makeConnection({ id: "conn_2", name: "Second agent" }),
  ]);
});

describe("HandoffSheet preview ordering", () => {
  it("renders only preview B when B resolves before stale preview A", async () => {
    const previewA = deferred<ReturnType<typeof makeManifest>>();
    const previewB = deferred<ReturnType<typeof makeManifest>>();
    mockPreview.mockReturnValueOnce(previewA.promise).mockReturnValueOnce(previewB.promise);
    const { renderer, unmount } = await renderWithProviders(<HandoffSheet {...props()} />);
    await settle();

    await pressText(renderer, "My Claude Code box");
    await pressText(renderer, "Second agent");
    await act(async () => {
      previewB.resolve(
        makeManifest({
          token: "token-b",
          connection_id: "conn_2",
          agent_name: "Second agent",
          title: "Preview B",
        }),
      );
    });
    await settle();
    expect(visibleText(renderer)).toContain("Preview B");
    expect(isDisabled(pressableForText(renderer, "Send to Second agent"))).toBe(false);

    await act(async () => {
      previewA.resolve(makeManifest({ token: "token-a", title: "Preview A" }));
    });
    await settle();
    expect(visibleText(renderer)).toContain("Preview B");
    expect(visibleText(renderer)).not.toContain("Preview A");
    expect(isDisabled(pressableForText(renderer, "Send to Second agent"))).toBe(false);

    await unmount();
  });

  it("keeps preview B when stale preview A rejects after B succeeds", async () => {
    const previewA = deferred<ReturnType<typeof makeManifest>>();
    const previewB = deferred<ReturnType<typeof makeManifest>>();
    mockPreview.mockReturnValueOnce(previewA.promise).mockReturnValueOnce(previewB.promise);
    const { renderer, unmount } = await renderWithProviders(<HandoffSheet {...props()} />);
    await settle();

    await pressText(renderer, "My Claude Code box");
    await pressText(renderer, "Second agent");
    await act(async () => {
      previewB.resolve(
        makeManifest({
          token: "token-b",
          connection_id: "conn_2",
          agent_name: "Second agent",
          title: "Preview B",
        }),
      );
    });
    await settle();

    await act(async () => {
      previewA.reject(new Error("stale A failed"));
    });
    await settle();
    expect(visibleText(renderer)).toContain("Preview B");
    expect(isDisabled(pressableForText(renderer, "Send to Second agent"))).toBe(false);

    await unmount();
  });

  it.each([
    ["agent", async (renderer: ReactTestRenderer) => pressText(renderer, "Second agent")],
    ["details", async (renderer: ReactTestRenderer) => pressLabel(renderer, "Exclude task details")],
    ["context", async (renderer: ReactTestRenderer) => pressLabel(renderer, "Remove Classification")],
  ])("clears the old manifest and disables Send while changed %s preview is pending", async (_kind, change) => {
    const replacement = deferred<ReturnType<typeof makeManifest>>();
    mockPreview
      .mockResolvedValueOnce(
        makeManifest({
          token: "token-a",
          title: "Preview A",
          supporting_items: [{ label: "Classification", body: "Project: Launch\nTags: Writing" }],
        }),
      )
      .mockReturnValueOnce(replacement.promise);
    const { renderer, unmount } = await renderWithProviders(<HandoffSheet {...props()} />);
    await settle();

    await pressText(renderer, "My Claude Code box");
    await settle();
    expect(visibleText(renderer)).toContain("Preview A");

    await change(renderer);
    expect(visibleText(renderer)).not.toContain("Preview A");
    expect(isDisabled(pressableForText(renderer, "Send"))).toBe(true);
    expect(mockPreview).toHaveBeenCalledTimes(2);

    await act(async () => {
      replacement.resolve(makeManifest({ token: "replacement-token" }));
    });
    await settle();

    await unmount();
  });

  it.each([
    ["title", { task: makeTask({ title: "Changed title" }) }],
    ["details", { task: makeTask({ details: "Changed details" }) }],
    ["revision", { task: makeTask({ revision: 4 }) }],
    ["project", { projectName: "Changed project" }],
    ["tags", { tagNames: ["Writing", "Changed tag"] }],
    [
      "subtask context source",
      {
        task: makeTask({
          subtasks: [{ id: "subtask-1", title: "Changed subtask", state: "open", order_key: 1, revision: 1 }],
        }),
      },
    ],
    [
      "comment context source",
      {
        task: makeTask({
          comments: [
            {
              id: "comment-1",
              body: "Changed comment",
              actor_id: "user-test",
              created_at: "2026-08-10T09:00:00Z",
              edited_at: null,
              revision: 1,
            },
          ],
        }),
      },
    ],
  ])("invalidates synchronously and re-previews when %s changes", async (_kind, changed) => {
    const replacement = deferred<ReturnType<typeof makeManifest>>();
    mockPreview
      .mockResolvedValueOnce(makeManifest({ token: "token-a", title: "Preview A" }))
      .mockReturnValueOnce(replacement.promise);
    const initialProps = props();
    const { renderer, client, unmount } = await renderWithProviders(<HandoffSheet {...initialProps} />);
    await settle();
    await pressText(renderer, "My Claude Code box");
    await settle();
    expect(isDisabled(pressableForText(renderer, "Send to My Claude Code box"))).toBe(false);

    await act(async () => {
      renderer.update(
        <QueryClientProvider client={client}>
          <HandoffSheet {...initialProps} {...changed} />
        </QueryClientProvider>,
      );
    });

    expect(isDisabled(currentSendButton(renderer))).toBe(true);
    expect(visibleText(renderer)).not.toContain("Preview A");
    expect(mockPreview).toHaveBeenCalledTimes(2);

    await act(async () => {
      replacement.resolve(makeManifest({ token: "token-b", title: "Preview B" }));
    });
    await settle();
    expect(visibleText(renderer)).toContain("Preview B");
    expect(isDisabled(pressableForText(renderer, "Send to My Claude Code box"))).toBe(false);

    await unmount();
  });

  it.each([
    ["revision", makeConnection({ revision: 2 }), true],
    ["capabilities", makeConnection({ capabilities: { streaming: false, push_notifications: true } }), true],
    ["name", makeConnection({ name: "Renamed agent" }), true],
    ["endpoint", makeConnection({ agent_address: "https://changed.example.test/relay" }), true],
    [
      "dispatch status",
      makeConnection({ status: "unreachable", ready_for_handoff: false }),
      false,
    ],
  ])(
    "invalidates synchronously when selected connection %s changes",
    async (_kind, changedConnection, remainsEligible) => {
      const replacement = deferred<ReturnType<typeof makeManifest>>();
      mockPreview
        .mockResolvedValueOnce(makeManifest({ token: "token-a", title: "Preview A" }))
        .mockReturnValueOnce(replacement.promise);
      const initialProps = props();
      const { renderer, client, unmount } = await renderWithProviders(
        <HandoffSheet {...initialProps} />,
      );
      await settle();
      await pressText(renderer, "My Claude Code box");
      await settle();
      expect(isDisabled(pressableForText(renderer, "Send to My Claude Code box"))).toBe(false);

      await act(async () => {
        client.setQueryData(
          agentKeys.connections("https://brain.example.test/api|user-test"),
          [changedConnection, makeConnection({ id: "conn_2", name: "Second agent" })],
        );
      });
      await settle();

      expect(isDisabled(currentSendButton(renderer))).toBe(true);
      expect(visibleText(renderer)).not.toContain("Preview A");
      expect(mockPreview).toHaveBeenCalledTimes(remainsEligible ? 2 : 1);

      if (remainsEligible) {
        await act(async () => {
          replacement.resolve(
            makeManifest({ token: "token-b", agent_name: changedConnection.name, title: "Preview B" }),
          );
        });
        await settle();
        expect(visibleText(renderer)).toContain("Preview B");
        expect(isDisabled(pressableForText(renderer, `Send to ${changedConnection.name}`))).toBe(false);
      }

      await unmount();
    },
  );

  it("invalidates close and starts a fresh preview for the same selection on reopen", async () => {
    const replacement = deferred<ReturnType<typeof makeManifest>>();
    mockPreview
      .mockResolvedValueOnce(makeManifest({ token: "token-a", title: "Preview A" }))
      .mockReturnValueOnce(replacement.promise);
    const initialProps = props();
    const { renderer, client, unmount } = await renderWithProviders(<HandoffSheet {...initialProps} />);
    await settle();
    await pressText(renderer, "My Claude Code box");
    await settle();
    expect(isDisabled(pressableForText(renderer, "Send to My Claude Code box"))).toBe(false);

    await act(async () => {
      renderer.update(
        <QueryClientProvider client={client}>
          <HandoffSheet {...initialProps} visible={false} />
        </QueryClientProvider>,
      );
    });
    expect(visibleText(renderer)).not.toContain("Preview A");

    await act(async () => {
      renderer.update(
        <QueryClientProvider client={client}>
          <HandoffSheet {...initialProps} visible />
        </QueryClientProvider>,
      );
    });
    await settle();
    expect(isDisabled(currentSendButton(renderer))).toBe(true);
    expect(mockPreview).toHaveBeenCalledTimes(2);

    await act(async () => {
      replacement.resolve(makeManifest({ token: "token-b", title: "Preview B" }));
    });
    await settle();
    expect(visibleText(renderer)).toContain("Preview B");
    expect(isDisabled(pressableForText(renderer, "Send to My Claude Code box"))).toBe(false);

    await unmount();
  });

  it("confirms only the token and exact inputs bound to the current preview", async () => {
    mockPreview
      .mockResolvedValueOnce(makeManifest({ token: "token-a", title: "Preview A" }))
      .mockResolvedValueOnce(
        makeManifest({
          token: "token-b",
          details: null,
          title: "Preview B",
        }),
      );
    mockConfirm.mockResolvedValue({});
    const { renderer, unmount } = await renderWithProviders(<HandoffSheet {...props()} />);
    await settle();

    await pressText(renderer, "My Claude Code box");
    await settle();
    await pressLabel(renderer, "Exclude task details");
    await settle();
    await pressText(renderer, "Send to My Claude Code box");
    await settle();

    expect(mockConfirm).toHaveBeenCalledWith(
      "task_1",
      expect.objectContaining({
        connection_id: "conn_1",
        include_details: false,
        manifest_token: "token-b",
      }),
      "agent-handoff-token-b",
    );
    expect(getByLabel(renderer, "Include task details")).toBeTruthy();

    await unmount();
  });
});

describe("HandoffSheet review contract", () => {
  it("014-FR-005 lists every value the manifest names, and no reporting instructions", async () => {
    mockPreview.mockResolvedValue(
      makeManifest({
        supporting_items: [{ label: "Classification", body: "Project: Launch" }],
      }),
    );
    const { renderer, unmount } = await renderWithProviders(<HandoffSheet {...props()} />);
    await settle();
    await pressText(renderer, "My Claude Code box");
    await settle();

    const text = visibleText(renderer);
    expect(text).toContain("Supporting items");
    expect(text).toContain("Correlation ID");
    expect(text).toContain("https://agent.example.test/a2a");
    expect(text).toContain("Cancellation depends on the agent.");
    expect(text).toContain("Best-effort single start.");
    // The bespoke reporting block is gone with the wire that needed it: an A2A
    // agent reports by answering, so it is told nothing about reporting.
    expect(text).not.toContain("Reporting instructions");
    expect(text).not.toContain("Instructions ");

    await unmount();
  });

  it("014-FR-005 discloses the masked push callback only when one is registered", async () => {
    mockPreview.mockResolvedValue(
      makeManifest({
        push_callback: {
          registered: true,
          url_preview: "https://brain.example.test/api/a2a/push/run_1/…",
          disclosure: "Brain Buddy also gives this agent a private callback address …",
        },
      }),
    );
    const { renderer, unmount } = await renderWithProviders(<HandoffSheet {...props()} />);
    await settle();
    await pressText(renderer, "My Claude Code box");
    await settle();

    const text = visibleText(renderer);
    expect(text).toContain("Push callback");
    expect(text).toContain("https://brain.example.test/api/a2a/push/run_1/…");
    expect(text).toContain("private callback address");
    // The token itself appears in no response, so it can never be on screen.
    expect(text).not.toMatch(/push\/run_1\/[A-Za-z0-9_-]{20,}/);

    await unmount();
  });

  it("014-FR-005 offers no push callback row when the agent cannot push", async () => {
    mockPreview.mockResolvedValue(makeManifest());
    const { renderer, unmount } = await renderWithProviders(<HandoffSheet {...props()} />);
    await settle();
    await pressText(renderer, "My Claude Code box");
    await settle();

    expect(visibleText(renderer)).not.toContain("Push callback");

    await unmount();
  });

  it("014-SC-005 gates Send on the one-time duplicate-risk acknowledgement", async () => {
    mockPreview.mockResolvedValue(makeManifest({ acknowledgement_required: true }));
    mockConfirm.mockResolvedValue({});
    const { renderer, unmount } = await renderWithProviders(<HandoffSheet {...props()} />);
    await settle();
    await pressText(renderer, "My Claude Code box");
    await settle();

    expect(isDisabled(currentSendButton(renderer))).toBe(true);
    const row = getByLabel(
      renderer,
      "I understand that a duplicate task is possible with this agent",
    );
    expect(row.props.accessibilityState?.checked).toBe(false);
    // A real 44pt target, not a label with a tap handler bolted on.
    expect(row.props.style).toEqual(expect.objectContaining({ minHeight: 44 }));

    await pressLabel(
      renderer,
      "I understand that a duplicate task is possible with this agent",
    );
    await settle();

    expect(isDisabled(currentSendButton(renderer))).toBe(false);
    expect(visibleText(renderer)).toContain("Acknowledged. Brain Buddy will not ask again");

    await pressText(renderer, "Send to My Claude Code box");
    await settle();
    expect(mockConfirm).toHaveBeenCalledWith(
      "task_1",
      expect.objectContaining({ acknowledge_duplicate_risk: true }),
      expect.stringContaining("agent-handoff-"),
    );

    await unmount();
  });

  it("014-SC-005 asks nothing on a later hand-off to the same agent", async () => {
    mockPreview.mockResolvedValue(makeManifest({ acknowledgement_required: false }));
    mockConfirm.mockResolvedValue({});
    const { renderer, unmount } = await renderWithProviders(<HandoffSheet {...props()} />);
    await settle();
    await pressText(renderer, "My Claude Code box");
    await settle();

    expect(
      queryByText(
        renderer,
        "☐ I understand that a duplicate task is possible with this agent",
      ),
    ).toBeNull();
    expect(visibleText(renderer)).toContain("so there is no acknowledgement step here");
    expect(isDisabled(currentSendButton(renderer))).toBe(false);

    await pressText(renderer, "Send to My Claude Code box");
    await settle();
    expect(mockConfirm).toHaveBeenCalledWith(
      "task_1",
      expect.objectContaining({ acknowledge_duplicate_risk: false }),
      expect.stringContaining("agent-handoff-"),
    );

    await unmount();
  });

  it("014-FR-016 renders an adversarial agent name and destination as inert text", async () => {
    mockPreview.mockResolvedValue(
      makeManifest({
        agent_name: "<script>alert(1)</script>Agent",
        destination_interface: "javascript:alert(document.cookie)",
      }),
    );
    const { renderer, unmount } = await renderWithProviders(<HandoffSheet {...props()} />);
    await settle();
    await pressText(renderer, "My Claude Code box");
    await settle();

    const text = visibleText(renderer);
    expect(text).toContain("javascript:alert(document.cookie)");
    // AC-031: nothing card-sourced is a Linking target, whatever its scheme.
    const links = renderer.root.findAll(
      (node) => node.props.accessibilityRole === "link",
      { deep: true },
    );
    for (const link of links) {
      expect(link.props.accessibilityLabel).toBe(
        "Read the single-start extension specification",
      );
    }

    await unmount();
  });

  it("014-FR-003 opens the extension specification only on an explicit tap", async () => {
    mockPreview.mockResolvedValue(makeManifest());
    const openURL = jest
      .spyOn(Linking, "openURL")
      .mockResolvedValue(undefined as unknown as never);
    const { renderer, unmount } = await renderWithProviders(<HandoffSheet {...props()} />);
    await settle();
    await pressText(renderer, "My Claude Code box");
    await settle();

    expect(openURL).not.toHaveBeenCalled();
    await pressLabel(renderer, "Read the single-start extension specification");
    await settle();
    expect(openURL).toHaveBeenCalledWith("https://example.invalid/single-start/v1.md");

    openURL.mockRestore();
    await unmount();
  });
});
