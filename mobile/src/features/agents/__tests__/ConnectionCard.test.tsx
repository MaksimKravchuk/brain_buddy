import type { ReactTestRenderer } from "react-test-renderer";

import type { AgentConnectionResponse } from "@/api/types";
import { ConnectionCard } from "@/features/agents/ConnectionCard";
import { makeCard, makeConnection } from "@/test/agentFixtures";
import { renderWithProviders } from "@/test/render";

/** Everything the card renders, flattened — no element is a link on iOS. */
function textOf(renderer: ReactTestRenderer): string {
  return renderer.root
    .findAll(() => true)
    .flatMap((node) => node.children)
    .filter((child): child is string => typeof child === "string")
    .join(" ");
}

async function renderCard(overrides: Partial<AgentConnectionResponse> = {}) {
  return renderWithProviders(
    <ConnectionCard
      connection={makeConnection(overrides)}
      onTest={jest.fn()}
      onRotate={jest.fn()}
      onDisconnect={jest.fn()}
    />,
  );
}

describe("ConnectionCard connection conditions", () => {
  it("014-FR-002 shows the discovery result and the tier (M-01-S09)", async () => {
    const { renderer, unmount } = await renderCard();

    const rendered = textOf(renderer);
    expect(rendered).toContain("Name: My Claude Code box");
    expect(rendered).toContain("Version: 1.2.3");
    expect(rendered).toContain("Protocol version: 1.0");
    expect(rendered).toContain("Interface: https://agent.example.test/a2a");
    expect(rendered).toContain("Research");
    expect(rendered).toContain("Best-effort single start.");
    expect(rendered).toContain("Read the single-start extension specification");
    expect(rendered).toContain("Cancellation depends on the agent.");
    await unmount();
  });

  it("014-FR-016 renders card text inertly and never as a link (AC-031)", async () => {
    const hostile = "<script>alert(1)</script> **not markdown**";
    const { renderer, unmount } = await renderCard({
      card: makeCard({
        name: hostile,
        description: hostile,
        interface_url: "javascript:alert(2)",
      }),
    });

    const rendered = textOf(renderer);
    expect(rendered).toContain(hostile);
    expect(rendered).toContain("Interface: javascript:alert(2)");
    // Nothing on the card is a `Linking` target: no node carries an href, a
    // `url` prop or a link accessibility role, whatever scheme the agent chose.
    const linkish = renderer.root.findAll(
      (node) =>
        node.props?.accessibilityRole === "link" ||
        typeof node.props?.href === "string" ||
        typeof node.props?.url === "string",
    );
    expect(linkish).toHaveLength(0);
    await unmount();
  });

  it.each([
    ["a2a_not_an_agent", null, "well-known location"],
    [
      "a2a_protocol_version_unsupported",
      { found_version: "0.9.4" },
      "The card declares A2A 0.9.4.",
    ],
    ["a2a_no_supported_interface", null, "No JSON-RPC interface"],
    ["a2a_auth_scheme_unsupported", { scheme: "oauth2" }, "This card requires oauth2."],
  ])(
    "014-FR-002 gives the %s category its own sentence (M-01-S12..S15)",
    async (code, detail, expected) => {
      const { renderer, unmount } = await renderCard({
        status: "unsupported",
        ready_for_handoff: false,
        card: null,
        last_test_error_code: code,
        last_test_error_detail: detail as AgentConnectionResponse["last_test_error_detail"],
      });

      const rendered = textOf(renderer);
      expect(rendered).toContain("Unsupported");
      expect(rendered).toContain(expected);
      await unmount();
    },
  );

  it("014-FR-002 shows Agent changed with both interfaces (M-01-S18)", async () => {
    const { renderer, unmount } = await renderCard({
      status: "untested",
      ready_for_handoff: false,
      agent_changed: true,
      last_test_error_code: "agent_card_changed",
      last_test_error_detail: { interface_url: "https://second.example.test/a2a" },
    });

    const rendered = textOf(renderer);
    expect(rendered).toContain("Agent changed");
    expect(rendered).toContain("Tested interface: https://agent.example.test/a2a");
    expect(rendered).toContain("Card now says: https://second.example.test/a2a");
    expect(rendered).toContain("destination you have not tested");
    await unmount();
  });

  it("014-FR-012 names a superseded wire contract with no path back (M-01-S19)", async () => {
    const { renderer, unmount } = await renderCard({
      status: "disconnected",
      ready_for_handoff: false,
      card: null,
      tier_disclosure: null,
      disconnect_reason: "superseded_wire_contract",
    });

    const rendered = textOf(renderer);
    expect(rendered).toContain("Superseded wire contract");
    expect(rendered).toContain("Add the agent again by its address");
    await unmount();
  });

  it.each([
    [30, "Test again in about 30 seconds."],
    [null, "Test again shortly."],
  ])(
    "014-FR-002 keeps a rate-limited connection untested with its retry hint (M-01-S22)",
    async (retryAfter, expected) => {
      const { renderer, unmount } = await renderCard({
        status: "untested",
        ready_for_handoff: false,
        last_test_error_code: "a2a_rate_limited",
        last_test_error_detail: { retry_after_seconds: retryAfter },
      });

      const rendered = textOf(renderer);
      expect(rendered).toContain("Rate limited");
      expect(rendered).toContain("answered the test by refusing it");
      expect(rendered).toContain(expected);
      // Never ready, so still no hand-off — and the retry stays offered.
      expect(rendered).toContain("cannot take a hand-off");
      expect(rendered).toContain("Test connection");
      await unmount();
    },
  );

  it("014-FR-016 states the disabled accessibility state on every offline action (M-01-S07)", async () => {
    const { renderer, unmount } = await renderWithProviders(
      <ConnectionCard
        connection={makeConnection()}
        online={false}
        onTest={jest.fn()}
        onRotate={jest.fn()}
        onDisconnect={jest.fn()}
      />,
    );

    const pressables = renderer.root.findAll(
      (node) => node.props?.accessibilityRole === "button",
    );
    expect(pressables.length).toBeGreaterThan(0);
    for (const pressable of pressables) {
      expect(pressable.props.accessibilityState?.disabled).toBe(true);
    }
    await unmount();
  });
});

describe("ConnectionCard recovery guidance", () => {
  it("maps a migrated invalid header to an available action without showing its code", async () => {
    const code = "legacy_invalid_auth_header_requires_reconfiguration";
    const { renderer, unmount } = await renderWithProviders(
      <ConnectionCard
        connection={{
          ...makeConnection(),
          status: "untested",
          ready_for_handoff: false,
          last_test_error_code: code,
        }}
        onTest={jest.fn()}
        onRotate={jest.fn()}
        onDisconnect={jest.fn()}
      />,
    );

    const rendered = renderer.root
      .findAll(() => true)
      .flatMap((node) => node.children)
      .filter((child): child is string => typeof child === "string")
      .join(" ");
    expect(rendered).toContain(
      "Brain Buddy has not contacted this agent yet. Test it before handing over a task.",
    );
    expect(rendered).not.toContain(code);
    await unmount();
  });
});