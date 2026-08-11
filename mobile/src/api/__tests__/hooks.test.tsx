import { fireEvent, screen, waitFor } from "@testing-library/react-native";
import { Pressable, Text } from "react-native";

import { useSmartAddTask, useTransitionTask } from "@/api/hooks";
import { installFakeBackend, makeMe, makeTask, type FakeBackend } from "@/test/fakeBackend";
import { renderWithSession } from "@/test/harness";

let backend: FakeBackend;

afterEach(() => backend?.restore());

function SmartAdd() {
  const smartAdd = useSmartAddTask();
  return (
    <>
      <Text testID="state">{smartAdd.isSuccess ? "done" : "idle"}</Text>
      <Pressable
        accessibilityLabel="smart-add"
        onPress={() =>
          smartAdd.mutate({ title: "Call the notary #errand", state: "inbox" })
        }
      >
        <Text>smart add</Text>
      </Pressable>
    </>
  );
}

function TransitionWithoutTask() {
  const transition = useTransitionTask();
  return (
    <>
      <Text testID="error">{transition.error ? String(transition.error) : "-"}</Text>
      <Pressable
        accessibilityLabel="transition"
        onPress={() =>
          transition.mutate({ payload: { action: "complete", expected_revision: 1 } })
        }
      >
        <Text>transition</Text>
      </Pressable>
    </>
  );
}

describe("useSmartAddTask", () => {
  it("posts to the smart-add endpoint with an idempotency key", async () => {
    backend = installFakeBackend({
      "GET /auth/me": () => makeMe(),
      "POST /tasks/smart-add": () => ({ task: makeTask(), applied: {} }),
    });

    await renderWithSession(<SmartAdd />);
    await fireEvent.press(screen.getByLabelText("smart-add"));

    await waitFor(() => expect(screen.getByTestId("state")).toHaveTextContent("done"));
    const call = backend.callsTo("POST", "/tasks/smart-add")[0];
    expect(call.body).toEqual({ title: "Call the notary #errand", state: "inbox" });
    expect(call.headers["Idempotency-Key"]).toEqual(expect.any(String));
  });
});

describe("useTransitionTask", () => {
  it("refuses to transition when neither the hook nor the call names a task", async () => {
    backend = installFakeBackend({ "GET /auth/me": () => makeMe() });

    await renderWithSession(<TransitionWithoutTask />);
    await fireEvent.press(screen.getByLabelText("transition"));

    await waitFor(() =>
      expect(screen.getByTestId("error")).toHaveTextContent("Error: taskId is required"),
    );
    expect(backend.calls.filter((call) => call.path.startsWith("/tasks"))).toHaveLength(0);
  });
});
