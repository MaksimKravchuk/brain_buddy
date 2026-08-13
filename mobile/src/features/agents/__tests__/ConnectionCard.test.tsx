import { ConnectionCard } from "@/features/agents/ConnectionCard";
import { makeConnection } from "@/test/agentFixtures";
import { renderWithProviders } from "@/test/render";

describe("ConnectionCard recovery guidance", () => {
  it("maps a migrated invalid header to an available action without showing its code", async () => {
    const code = "legacy_invalid_auth_header_requires_reconfiguration";
    const { renderer, unmount } = await renderWithProviders(
      <ConnectionCard
        connection={{
          ...makeConnection(),
          auth_header_name: "X-Agent-Key",
          status: "untested",
          ready_for_handoff: false,
          last_test_error_code: code,
        }}
        onTest={jest.fn()}
        onRotate={jest.fn()}
        onReplaceSigningSecret={jest.fn()}
        onDisconnect={jest.fn()}
      />,
    );

    const rendered = renderer.root
      .findAll(() => true)
      .flatMap((node) => node.children)
      .filter((child): child is string => typeof child === "string")
      .join(" ");
    expect(rendered).toContain(
      "Enter a replacement credential for X-Agent-Key, then test the connection.",
    );
    expect(rendered).not.toContain(code);
    await unmount();
  });
});