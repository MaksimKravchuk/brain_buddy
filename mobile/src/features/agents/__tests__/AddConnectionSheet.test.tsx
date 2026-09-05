/** Caller-owned idempotency for creating an external-agent connection. */
import { QueryClientProvider } from "@tanstack/react-query";
import type { ReactTestInstance, ReactTestRenderer } from "react-test-renderer";
import { act } from "react-test-renderer";

import { ApiError } from "@/api/client";
import { AddConnectionSheet } from "@/features/agents/AddConnectionSheet";
import { makeConnection } from "@/test/agentFixtures";
import {
  pressLabel,
  pressText,
  renderWithProviders,
  settle,
  typeInto,
  visibleText,
} from "@/test/render";

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
    input(renderer, "https://your-agent.example.com"),
    "https://agent.example.test",
  );
  await typeInto(input(renderer, "Sent as the credential"), "Bearer secret");
  await typeInto(input(renderer, "Confirm it is you"), "brain-buddy-password");
}

beforeEach(() => {
  mockKeys.issued = 0;
  mockCreate.mockReset();
});

describe("AddConnectionSheet idempotency", () => {
  it("014-FR-001 resets a chosen credential scheme after close and reopen", async () => {
    const onClose = jest.fn();
    const { renderer, client, unmount } = await renderWithProviders(
      <AddConnectionSheet visible onClose={onClose} onCreated={jest.fn()} />,
    );
    await pressLabel(renderer, "API key");
    expect(visibleText(renderer)).toContain("Read from the agent card when you test");

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

    // Dismissing discards everything silently: nothing was stored and nothing
    // was sent, so the sheet reopens on the default scheme (M-01-S08).
    expect(visibleText(renderer)).not.toContain("Read from the agent card when you test");
    await unmount();
  });

  it("clears mounted secrets and error while preserving ambiguous create intent on reopen", async () => {
    mockCreate
      .mockRejectedValueOnce(new Error("Response lost"))
      .mockResolvedValue(makeConnection());
    const onClose = jest.fn();
    const onCreated = jest.fn();
    const { renderer, client, unmount } = await renderWithProviders(
      <AddConnectionSheet visible onClose={onClose} onCreated={onCreated} />,
    );
    await fillForm(renderer);
    await pressText(renderer, "Save agent");
    await settle();
    const firstKey = mockCreate.mock.calls[0][1];
    expect(visibleText(renderer)).toContain("Response lost");

    await pressLabel(renderer, "Close");

    expect(onClose).toHaveBeenCalledTimes(1);
    expect(input(renderer, "What you call this agent").props.value).toBe("");
    expect(input(renderer, "https://your-agent.example.com").props.value).toBe("");
    expect(input(renderer, "Sent as the credential").props.value).toBe("");
    expect(input(renderer, "Confirm it is you").props.value).toBe("");
    expect(visibleText(renderer)).not.toContain("Response lost");

    await act(async () => {
      renderer.update(
        <QueryClientProvider client={client}>
          <AddConnectionSheet visible={false} onClose={onClose} onCreated={onCreated} />
        </QueryClientProvider>,
      );
    });
    await act(async () => {
      renderer.update(
        <QueryClientProvider client={client}>
          <AddConnectionSheet visible onClose={onClose} onCreated={onCreated} />
        </QueryClientProvider>,
      );
    });
    await fillForm(renderer);
    await pressText(renderer, "Save agent");
    await settle();

    expect(mockCreate).toHaveBeenCalledTimes(2);
    expect(mockCreate.mock.calls[1][1]).toBe(firstKey);
    await unmount();
  });

  it("clears every mounted field before the successful create closes the sheet", async () => {
    const created = makeConnection();
    mockCreate.mockResolvedValue(created);
    const onCreated = jest.fn();
    const { renderer, unmount } = await renderWithProviders(
      <AddConnectionSheet visible onClose={jest.fn()} onCreated={onCreated} />,
    );
    await fillForm(renderer);

    await pressText(renderer, "Save agent");
    await settle();

    expect(onCreated).toHaveBeenCalledWith(created);
    expect(input(renderer, "What you call this agent").props.value).toBe("");
    expect(input(renderer, "https://your-agent.example.com").props.value).toBe("");
    expect(input(renderer, "Sent as the credential").props.value).toBe("");
    expect(input(renderer, "Confirm it is you").props.value).toBe("");
    await unmount();
  });

  it("retries a lost create response with the original key and recovers the one-time secret", async () => {
    const created = makeConnection();
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
    expect(mockCreate.mock.calls[0][0].auth_scheme).toBe("bearer");
    expect(mockCreate.mock.calls[0][0]).not.toHaveProperty("auth_header_name");
    expect(mockCreate.mock.calls[1][1]).toBe(mockCreate.mock.calls[0][1]);
    expect(onCreated).toHaveBeenCalledWith(created);

    await unmount();
  });

  it("blocks a materially changed connection form after an ambiguous failure", async () => {
    mockCreate.mockRejectedValueOnce(new Error("Response lost")).mockResolvedValue({
      ...makeConnection(),
    });
    const { renderer, unmount } = await renderWithProviders(
      <AddConnectionSheet visible onClose={jest.fn()} onCreated={jest.fn()} />,
    );
    await fillForm(renderer);

    await pressText(renderer, "Save agent");
    await settle();
    await typeInto(
      input(renderer, "https://your-agent.example.com"),
      "https://different-agent.example.test/relay",
    );
    await pressText(renderer, "Save agent");
    await settle();

    expect(mockCreate).toHaveBeenCalledTimes(1);
    expect(visibleText(renderer)).toContain("exact same connection details and secrets");

    await unmount();
  });

  it("blocks a changed password after an ambiguous failure", async () => {
    mockCreate.mockRejectedValueOnce(new Error("Response lost")).mockResolvedValue({
      ...makeConnection(),
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

    expect(mockCreate).toHaveBeenCalledTimes(1);
    expect(visibleText(renderer)).toContain("exact same connection details and secrets");

    await unmount();
  });

  it("retires the key after a definitive client rejection", async () => {
    mockCreate
      .mockRejectedValueOnce(new ApiError("Invalid endpoint", 422, {}))
      .mockResolvedValue(makeConnection());
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
