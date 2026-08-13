import { onlineManager } from "@tanstack/react-query";
import { Pressable, Text } from "react-native";
import { act } from "react-test-renderer";

import {
  useCancelAgentRun,
  useConfirmAgentHandoff,
  useCreateAgentConnection,
  useDisconnectAgentConnection,
  usePreviewAgentHandoff,
  useReplyToAgentRun,
  useRotateAgentCredential,
  useRotateAgentSigningSecret,
  useTestAgentConnection,
} from "@/api/hooks";
import { pressText, renderWithProviders, settle, visibleText } from "@/test/render";

const offlineFailure = new TypeError("Network request failed");
const mockApi = {
  createAgentConnection: jest.fn(),
  testAgentConnection: jest.fn(),
  rotateAgentCredential: jest.fn(),
  rotateAgentSigningSecret: jest.fn(),
  disconnectAgentConnection: jest.fn(),
  previewAgentHandoff: jest.fn(),
  confirmAgentHandoff: jest.fn(),
  replyToAgentRun: jest.fn(),
  cancelAgentRun: jest.fn(),
};

jest.mock("@/auth/SessionProvider", () => ({
  useSession: () => ({
    api: mockApi,
    serverUrl: "https://brain.example.test/api",
    accountId: "user-1",
  }),
}));

function OfflineRelayHarness() {
  const create = useCreateAgentConnection();
  const test = useTestAgentConnection();
  const rotateCredential = useRotateAgentCredential();
  const rotateSigning = useRotateAgentSigningSecret();
  const disconnect = useDisconnectAgentConnection();
  const preview = usePreviewAgentHandoff("task-1");
  const confirm = useConfirmAgentHandoff("task-1");
  const reply = useReplyToAgentRun();
  const cancel = useCancelAgentRun();
  const connectionPayload = { current_password: "password", expected_revision: 4 };
  const mutations = [
    create,
    test,
    rotateCredential,
    rotateSigning,
    disconnect,
    preview,
    confirm,
    reply,
    cancel,
  ];

  return (
    <>
      <Pressable
        onPress={() =>
          create.mutate({
            payload: {
              name: "Agent",
              endpoint_url: "https://agent.example.test/relay",
              credential: "secret",
              current_password: "password",
            },
            idempotencyKey: "create-key",
          })
        }
      >
        <Text>Create</Text>
      </Pressable>
      <Pressable onPress={() => test.mutate("connection-1")}><Text>Test</Text></Pressable>
      <Pressable
        onPress={() =>
          rotateCredential.mutate({
            connectionId: "connection-1",
            payload: { ...connectionPayload, credential: "new-secret" },
            idempotencyKey: "rotate-key",
          })
        }
      >
        <Text>Rotate credential</Text>
      </Pressable>
      <Pressable
        onPress={() =>
          rotateSigning.mutate({
            connectionId: "connection-1",
            payload: connectionPayload,
            idempotencyKey: "signing-key",
          })
        }
      >
        <Text>Rotate signing</Text>
      </Pressable>
      <Pressable
        onPress={() =>
          disconnect.mutate({
            connectionId: "connection-1",
            payload: connectionPayload,
            idempotencyKey: "disconnect-key",
          })
        }
      >
        <Text>Disconnect</Text>
      </Pressable>
      <Pressable
        onPress={() => preview.mutate({ connection_id: "connection-1" })}
      >
        <Text>Preview</Text>
      </Pressable>
      <Pressable
        onPress={() =>
          confirm.mutate({
            payload: { connection_id: "connection-1", manifest_token: "manifest-1" },
            idempotencyKey: "handoff-key",
          })
        }
      >
        <Text>Confirm</Text>
      </Pressable>
      <Pressable
        onPress={() =>
          reply.mutate({
            runId: "run-1",
            payload: { message: "Answer", expected_revision: 2 },
            idempotencyKey: "reply-key",
          })
        }
      >
        <Text>Reply</Text>
      </Pressable>
      <Pressable
        onPress={() => cancel.mutate({ runId: "run-1", idempotencyKey: "cancel-key" })}
      >
        <Text>Cancel</Text>
      </Pressable>
      <Text>{mutations.map((mutation) => mutation.status).join(",")}</Text>
    </>
  );
}

describe("relay mutations while React Query reports offline", () => {
  beforeEach(() => {
    onlineManager.setOnline(false);
    for (const endpoint of Object.values(mockApi)) {
      endpoint.mockReset().mockRejectedValue(offlineFailure);
    }
  });

  afterEach(() => {
    onlineManager.setOnline(true);
  });

  it("attempts every relay command and probe once, fails immediately, and never replays on reconnect", async () => {
    const rendered = await renderWithProviders(<OfflineRelayHarness />);

    for (const label of [
      "Create",
      "Test",
      "Rotate credential",
      "Rotate signing",
      "Disconnect",
      "Preview",
      "Confirm",
      "Reply",
      "Cancel",
    ]) {
      await pressText(rendered.renderer, label);
    }
    await settle();

    expect(Object.values(mockApi).map((endpoint) => endpoint.mock.calls.length)).toEqual(
      Array(9).fill(1),
    );
    expect(visibleText(rendered.renderer)).toContain(Array(9).fill("error").join(","));

    await act(async () => {
      onlineManager.setOnline(true);
      await new Promise<void>((resolve) => setTimeout(resolve, 0));
    });
    expect(Object.values(mockApi).map((endpoint) => endpoint.mock.calls.length)).toEqual(
      Array(9).fill(1),
    );

    await rendered.unmount();
  });
});
