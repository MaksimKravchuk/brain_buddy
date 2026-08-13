import { fireEvent, screen, waitFor } from "@testing-library/react-native";

import { HandoffSheet } from "@/features/agents/HandoffSheet";
import { makeConnection, makeManifest, makeRun, makeTask } from "@/test/agentFixtures";
import { installFakeBackend, makeMe, type FakeBackend } from "@/test/fakeBackend";
import { renderWithSession } from "@/test/harness";

let backend: FakeBackend;

afterEach(() => backend?.restore());

describe("handoff sheet real lifecycle", () => {
  it("blocks scrim and native back dismissal while confirm is pending, then settles through the mounted observer", async () => {
    let resolveConfirm!: (run: ReturnType<typeof makeRun>) => void;
    backend = installFakeBackend({
      "GET /auth/me": () => makeMe({ feature_flags: { external_agent_relay: true } }),
      "GET /agent-connections": () => [makeConnection()],
      "POST /tasks/task_1/agent-runs/preview": () => makeManifest(),
      "POST /tasks/task_1/agent-runs": () =>
        new Promise((resolve) => {
          resolveConfirm = resolve;
        }),
    });
    const onClose = jest.fn();
    const onDispatched = jest.fn();
    const rendered = await renderWithSession(
      <HandoffSheet
        visible
        onClose={onClose}
        task={makeTask()}
        projectName={null}
        tagNames={[]}
        onDispatched={onDispatched}
      />,
    );

    await fireEvent.press(await screen.findByText("My Claude Code box"));
    await fireEvent.press(await screen.findByText("Send to My Claude Code box"));
    await waitFor(() => expect(backend.callsTo("POST", "/tasks/task_1/agent-runs")).toHaveLength(1));

    const scrim = screen.getByLabelText("Close");
    expect(scrim.props.accessibilityState.disabled).toBe(true);
    await fireEvent.press(scrim);
    const [modal] = rendered.container.queryAll((node) => node.type === "Modal");
    if (!modal) throw new Error("Expected the real Modal host");
    modal.props.onRequestClose();
    expect(onClose).not.toHaveBeenCalled();

    const run = makeRun();
    resolveConfirm(run);
    await waitFor(() => expect(onDispatched).toHaveBeenCalledWith(run));
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
