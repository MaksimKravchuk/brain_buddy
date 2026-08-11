/** Caller-owned idempotency for creating an external-agent connection. */
import { QueryClientProvider } from "@tanstack/react-query";
import type { ReactTestInstance, ReactTestRenderer } from "react-test-renderer";
import { act } from "react-test-renderer";

import { ApiError } from "@/api/client";
import { AddConnectionSheet } from "@/features/agents/AddConnectionSheet";
import { makeConnection } from "@/test/agentFixtures";
import { pressText, renderWithProviders, settle, typeInto } from "@/test/render";

const mockCreate = jest.fn();
const mockKeys = { issued: 0 };

jest.mock("expo-crypto", () => ({
  randomUUID: () => {
    mockKeys.issued += 1;
    return `create_key_${mockKeys.issued}`;
  },
}));

jest.mock("@/auth/SessionProvider", () => {
  const api = {
    createAgentConnection: (...args: unknown[]) => mockCreate(...args),
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

jest.mock("react-native-safe-area-context", () => ({
  useSafeAreaInsets: () => ({ top: 0, right: 0, bottom: 0, left: 0 }),
}));

function input(renderer: ReactTestRenderer, placeholder: string): ReactTestInstance {
  return renderer.root.find((node) => node.props?.placeholder === placeholder);
}

async function fillForm(renderer: ReactTestRenderer) {
  await typeInto(input(renderer, "What you call this agent"), "Release agent");
  await typeInto(
    input(renderer, "https://your-agent.example.com/brain-buddy"),
    "https://agent.example.test/relay",
  );
  await typeInto(input(renderer, "Sent as the auth header value"), "Bearer secret");
  await typeInto(input(renderer, "Confirm it is you"), "brain-buddy-password");
}

beforeEach(() => {
  mockKeys.issued = 0;
  mockCreate.mockReset();
});

describe("AddConnectionSheet idempotency", () => {
  it("resets a changed auth header after close and reopen", async () => {
    const onClose = jest.fn();
    const { renderer, client, unmount } = await renderWithProviders(
      <AddConnectionSheet visible onClose={onClose} onCreated={jest.fn()} />,
    );
    const authHeader = input(renderer, "X-Agent-Key");
    await typeInto(authHeader, "X-Temporary-Key");
    expect(authHeader.props.value).toBe("X-Temporary-Key");

    await act(async () => {
      renderer.update(
        <QueryClientProvider client={client}>
          <AddConnectionSheet visible={false} onClose={onClose} onCreated={jest.fn()} />
        </QueryClientProvider>,
      );
    });
    await act(async () => {
      renderer.update(
        <QueryClientProvider client={client}>
          <AddConnectionSheet visible onClose={onClose} onCreated={jest.fn()} />
        </QueryClientProvider>,
      );
    });

    expect(input(renderer, "X-Agent-Key").props.value).toBe("X-Agent-Key");
    await unmount();
  });

  it("retries a lost create response with the original key and recovers the one-time secret", async () => {
    const created = { ...makeConnection(), inbound_signing_secret: "shown-once" };
    mockCreate.mockRejectedValueOnce(new Error("Response lost")).mockResolvedValue(created);
    const onCreated = jest.fn();
    const { renderer, unmount } = await renderWithProviders(
      <AddConnectionSheet visible onClose={jest.fn()} onCreated={onCreated} />,
    );
    await fillForm(renderer);

    await pressText(renderer, "Save agent");
    await settle();
    await pressText(renderer, "Save agent");
    await settle();

    expect(mockCreate).toHaveBeenCalledTimes(2);
    expect(mockCreate.mock.calls[0][0].auth_header_name).toBe("X-Agent-Key");
    expect(mockCreate.mock.calls[1][1]).toBe(mockCreate.mock.calls[0][1]);
    expect(onCreated).toHaveBeenCalledWith(created);

    await unmount();
  });

  it("mints a new key after the user materially changes the connection form", async () => {
    mockCreate.mockRejectedValueOnce(new Error("Response lost")).mockResolvedValue({
      ...makeConnection(),
      inbound_signing_secret: "shown-once",
    });
    const { renderer, unmount } = await renderWithProviders(
      <AddConnectionSheet visible onClose={jest.fn()} onCreated={jest.fn()} />,
    );
    await fillForm(renderer);

    await pressText(renderer, "Save agent");
    await settle();
    await typeInto(
      input(renderer, "https://your-agent.example.com/brain-buddy"),
      "https://different-agent.example.test/relay",
    );
    await pressText(renderer, "Save agent");
    await settle();

    expect(mockCreate).toHaveBeenCalledTimes(2);
    expect(mockCreate.mock.calls[1][1]).not.toBe(mockCreate.mock.calls[0][1]);

    await unmount();
  });

  it("mints a new key when the password changes after an ambiguous failure", async () => {
    mockCreate.mockRejectedValueOnce(new Error("Response lost")).mockResolvedValue({
      ...makeConnection(),
      inbound_signing_secret: "shown-once",
    });
    const { renderer, unmount } = await renderWithProviders(
      <AddConnectionSheet visible onClose={jest.fn()} onCreated={jest.fn()} />,
    );
    await fillForm(renderer);

    await pressText(renderer, "Save agent");
    await settle();
    await typeInto(input(renderer, "Confirm it is you"), "changed-brain-buddy-password");
    await pressText(renderer, "Save agent");
    await settle();

    expect(mockCreate).toHaveBeenCalledTimes(2);
    expect(mockCreate.mock.calls[1][1]).not.toBe(mockCreate.mock.calls[0][1]);
    expect(mockCreate.mock.calls[1][0].current_password).toBe("changed-brain-buddy-password");

    await unmount();
  });

  it("retires the key after a definitive client rejection", async () => {
    mockCreate
      .mockRejectedValueOnce(new ApiError("Invalid endpoint", 422, {}))
      .mockResolvedValue({ ...makeConnection(), inbound_signing_secret: "shown-once" });
    const { renderer, unmount } = await renderWithProviders(
      <AddConnectionSheet visible onClose={jest.fn()} onCreated={jest.fn()} />,
    );
    await fillForm(renderer);

    await pressText(renderer, "Save agent");
    await settle();
    await pressText(renderer, "Save agent");
    await settle();

    expect(mockCreate).toHaveBeenCalledTimes(2);
    expect(mockCreate.mock.calls[1][1]).not.toBe(mockCreate.mock.calls[0][1]);

    await unmount();
  });
});
