import { describe, expect, it } from "vitest";

import type { AgentConnectionResponse } from "../../../api/agentTypes";
import type { AgentRunResponse } from "../../../api/agentTypes";
import {
  artifactPlaceholderCopy,
  authSchemeLabel,
  cancelOutcomeCopy,
  compactRunLabel,
  dispatchStateDetail,
  guaranteeTierLabel,
  resultAvailabilityCopy,
  rateLimitRetryCopy,
  awaitsAnswer,
  capabilityDisclosure,
  connectionStatusDetail,
  connectionStatusLabel,
  formatDuration,
  formatTimestamp
} from "../agentCopy";

const base: AgentConnectionResponse = {
  id: "conn-1",
  name: "Hermes",
  agent_address: "https://agent.example.com",
  auth_scheme: "bearer",
  auth_header_name: null,
  status: "ready",
  stale: false,
  ready_for_handoff: true,
  capabilities: { streaming: true, push_notifications: false },
  controls_offered: { reply: true, cancel: true },
  card: null,
  guarantee_tier: "best_effort",
  tier_disclosure: "Best-effort single start.",
  tier_disclosure_url: "https://example.invalid/single-start/v1.md",
  cancellation_disclosure: "Cancellation depends on the agent.",
  agent_changed: false,
  best_effort_acknowledged_at: null,
  correlation_id_honoured: null,
  disconnect_reason: null,
  last_test_error_detail: null,
  last_test_error_code: null,
  last_contact_at: "2026-08-09T10:00:00Z",
  last_tested_at: "2026-08-09T10:00:00Z",
  stale_after_seconds: 3600,
  created_at: "2026-08-09T09:00:00Z",
  revision: 1
};

/** The dispatch-side slice of a run, which is all `dispatchStateDetail` reads. */
function runShape(
  overrides: Partial<AgentRunResponse>
): Parameters<typeof dispatchStateDetail>[0] {
  return {
    dispatch_state: "sent",
    dispatch_error_code: null,
    exchange_state: "none",
    exchange_open: false,
    reported_state: null,
    ...overrides
  };
}

describe("agentCopy", () => {
  it("keeps a disclosed blocked question answerable even before needs_user is projected", () => {
    expect(
      awaitsAnswer({ question_text: "Approve?", needs_user: false, reported_state: "blocked" })
    ).toBe(true);
  });

  it("never calls an untested or failing connection ready", () => {
    expect(connectionStatusLabel({ ...base, status: "untested", ready_for_handoff: false })).toBe("Not tested");
    expect(connectionStatusLabel({ ...base, status: "invalid_credentials", ready_for_handoff: false })).toBe(
      "Invalid credentials"
    );
    expect(connectionStatusLabel({ ...base, status: "unreachable", ready_for_handoff: false })).toBe("Unreachable");
    expect(connectionStatusLabel({ ...base, status: "unsupported", ready_for_handoff: false })).toBe(
      "Unsupported"
    );
    expect(connectionStatusLabel({ ...base, status: "disconnected", ready_for_handoff: false })).toBe("Disconnected");
    expect(connectionStatusLabel(base)).toBe("Tested ready");
  });

  it("shows a stale connection as stale even though its last test succeeded", () => {
    const stale = { ...base, stale: true, ready_for_handoff: false };
    expect(connectionStatusLabel(stale)).toBe("Stale");
    expect(connectionStatusDetail(stale)).toMatch(/test it again/i);
  });

  it("explains the corrective action behind every failing status", () => {
    expect(connectionStatusDetail({ ...base, status: "untested" })).toMatch(/has not contacted/i);
    expect(connectionStatusDetail({ ...base, status: "invalid_credentials" })).toMatch(/rejected the credential/i);
    expect(connectionStatusDetail({ ...base, status: "unreachable" })).toMatch(/nothing was sent/i);
    expect(
      connectionStatusDetail({
        ...base,
        status: "unsupported",
        last_test_error_code: "a2a_protocol_version_unsupported",
        last_test_error_detail: { found_version: "0.9.4" }
      })
    ).toMatch(/declares A2A 0\.9\.4/i);
    expect(connectionStatusDetail({ ...base, status: "disconnected" })).toMatch(/were destroyed/i);
    expect(connectionStatusDetail(base)).toMatch(/authenticated/i);
  });

  it("014-FR-002 discloses only what an agent card actually declares", () => {
    // Reply and cancellation are absent by design: no A2A card advertises
    // either, so listing them here would render a BrainBuddy decision as an
    // agent promise (FR-010).
    expect(capabilityDisclosure({ streaming: true, push_notifications: false })).toEqual([
      { label: "Streaming updates", supported: true },
      { label: "Push notifications", supported: false }
    ]);
  });

  it("014-FR-002 labels the two conditions that override a stored status", () => {
    expect(
      connectionStatusLabel({ ...base, status: "untested", agent_changed: true })
    ).toBe("Agent changed");
    expect(
      connectionStatusLabel({
        ...base,
        status: "untested",
        last_test_error_code: "a2a_rate_limited"
      })
    ).toBe("Rate limited");
    expect(
      connectionStatusLabel({
        ...base,
        status: "disconnected",
        disconnect_reason: "superseded_wire_contract"
      })
    ).toBe("Superseded wire contract");
    expect(connectionStatusLabel({ ...base, status: "disconnected" })).toBe("Disconnected");
  });

  it("014-FR-002 falls back honestly when a card gave no detail to name", () => {
    // The detail is coarse metadata an agent controls, so every branch has to
    // read sensibly with it missing rather than rendering an empty gap.
    const unsupported = { ...base, status: "unsupported" as const };
    expect(
      connectionStatusDetail({
        ...unsupported,
        last_test_error_code: "a2a_protocol_version_unsupported"
      })
    ).toMatch(/outside 1\.0\.x/i);
    expect(
      connectionStatusDetail({
        ...unsupported,
        last_test_error_code: "a2a_auth_scheme_unsupported"
      })
    ).toMatch(/does not support\. BrainBuddy supports a bearer token/i);
    expect(
      connectionStatusDetail({ ...unsupported, last_test_error_code: "a2a_not_an_agent" })
    ).toMatch(/well-known location/i);
    expect(
      connectionStatusDetail({
        ...unsupported,
        last_test_error_code: "a2a_no_supported_interface"
      })
    ).toMatch(/No JSON-RPC interface/i);
    expect(
      connectionStatusDetail({
        ...base,
        status: "disconnected",
        disconnect_reason: "superseded_wire_contract"
      })
    ).toMatch(/previous agent wire/i);
  });

  it("014-FR-002 never invents a retry countdown the agent did not give", () => {
    expect(
      rateLimitRetryCopy({ ...base, last_test_error_detail: { retry_after_seconds: 1 } })
    ).toBe("Test again in about 1 second.");
    expect(
      rateLimitRetryCopy({ ...base, last_test_error_detail: { retry_after_seconds: 30 } })
    ).toBe("Test again in about 30 seconds.");
    expect(
      rateLimitRetryCopy({ ...base, last_test_error_detail: { retry_after_seconds: null } })
    ).toBe("Test again shortly.");
    expect(rateLimitRetryCopy({ ...base, last_test_error_detail: null })).toBe(
      "Test again shortly."
    );
    // A detail belonging to a different code is not a countdown either.
    expect(rateLimitRetryCopy({ ...base, last_test_error_detail: { scheme: "oauth2" } })).toBe(
      "Test again shortly."
    );
  });

  it("014-FR-001 names the credential scheme without ever naming the credential", () => {
    expect(authSchemeLabel(base)).toBe("Bearer token · stored sealed");
    expect(authSchemeLabel({ ...base, auth_scheme: "api_key", auth_header_name: "X-API-Key" })).toBe(
      "API key in X-API-Key · stored sealed"
    );
    // Before discovery there is no header name to show, and inventing one would
    // claim the card said something it has not been asked yet.
    expect(authSchemeLabel({ ...base, auth_scheme: "api_key", auth_header_name: null })).toBe(
      "API key · stored sealed"
    );
  });

  it("says never rather than guessing when a timestamp is absent", () => {
    expect(formatTimestamp(null)).toBe("Never");
    expect(formatTimestamp("not-a-date")).toBe("not-a-date");
    expect(formatTimestamp("2026-08-09T10:00:00Z")).not.toBe("Never");
  });

  it("formats the server-configured thresholds in plain units", () => {
    expect(formatDuration(1)).toBe("1 second");
    expect(formatDuration(45)).toBe("45 seconds");
    expect(formatDuration(60)).toBe("1 minute");
    expect(formatDuration(900)).toBe("15 minutes");
    expect(formatDuration(3600)).toBe("1 hour");
    expect(formatDuration(7200)).toBe("2 hours");
  });

  it("014-FR-006 keeps Queued and Sent apart in the dispatch sentence", () => {
    // The whole point of the queued state: the identifiers are reserved, the
    // content is frozen, and nothing has left. Saying "Sent" here would be the
    // one claim this projection exists to avoid making.
    expect(
      dispatchStateDetail(
        runShape({
          dispatch_state: "delivery_unconfirmed",
          exchange_state: "queued",
          exchange_open: true
        })
      )
    ).toBe("Waiting for a free connection slot; nothing has been sent yet");
    expect(
      dispatchStateDetail(
        runShape({
          dispatch_state: "delivery_unconfirmed",
          exchange_state: "open",
          exchange_open: true
        })
      )
    ).toBe("Some agents answer only when the work is finished.");
    expect(dispatchStateDetail(runShape({ dispatch_state: "sent" }))).toBe(
      "Some agents answer only when the work is finished."
    );
  });

  it("014-FR-006 separates a restart that never sent from an ambiguous delivery", () => {
    expect(
      dispatchStateDetail(
        runShape({ dispatch_state: "not_sent", dispatch_error_code: "restarted_before_send" })
      )
    ).toBe("BrainBuddy restarted before this hand-off was sent. Nothing left BrainBuddy.");
    expect(
      dispatchStateDetail(
        runShape({ dispatch_state: "not_sent", dispatch_error_code: "a2a_rate_limited" })
      )
    ).toBe("The agent is rate limiting.");
    expect(
      dispatchStateDetail(runShape({ dispatch_state: "delivery_unconfirmed", exchange_state: "closed" }))
    ).toBe("BrainBuddy could not confirm the agent received this hand-off. It was not re-sent.");
  });

  it("014-FR-014 says nothing about dispatch once the agent has reported", () => {
    // Dispatch is BrainBuddy's own claim about its outbound request. Once the
    // agent has spoken, its state is the authority and a stale dispatch line
    // would compete with it.
    expect(
      dispatchStateDetail(runShape({ dispatch_state: "sent", reported_state: "running" }))
    ).toBeNull();
    expect(
      dispatchStateDetail(runShape({ dispatch_state: "not_sent", dispatch_error_code: null }))
    ).toBeNull();
  });
});


describe("014-FR-013 the observation-side copy", () => {
  it("names an artifact's content type and never a download", () => {
    expect(
      artifactPlaceholderCopy({
        name: "report.pdf",
        media_type: "application/pdf",
        kind: "file"
      })
    ).toBe("report.pdf · application/pdf");
    // A placeholder that could not say what it stood for would tell the user
    // nothing, so the kind fills in for a missing name.
    expect(artifactPlaceholderCopy({ name: null, media_type: null, kind: "data" })).toBe(
      "Untitled data"
    );
    expect(artifactPlaceholderCopy({ name: "  ", media_type: null, kind: "link" })).toBe(
      "Untitled link"
    );
    expect(
      artifactPlaceholderCopy({ name: "notes", media_type: null, kind: "text" })
    ).toBe("notes");
  });

  it("014-FR-014 keeps the cancel outcome a secondary line, never the label", () => {
    expect(cancelOutcomeCopy({ cancel_outcome: "unsupported" })).toBe(
      "Cancellation not supported by this agent."
    );
    expect(cancelOutcomeCopy({ cancel_outcome: "not_cancelable" })).toBe(
      "Cancellation not supported by this agent."
    );
    expect(cancelOutcomeCopy({ cancel_outcome: "unconfirmed" })).toBe(
      "Cancellation request unconfirmed — you can try again."
    );
    expect(cancelOutcomeCopy({ cancel_outcome: "accepted" })).toBeNull();
    expect(cancelOutcomeCopy({ cancel_outcome: "none" })).toBeNull();
  });

  it("014-FR-013 marks a too-large result rather than blaming the agent", () => {
    expect(resultAvailabilityCopy({ result_availability: "too_large" })).toBe(
      "Result too large to store."
    );
    expect(resultAvailabilityCopy({ result_availability: "available" })).toBeNull();
    expect(resultAvailabilityCopy({ result_availability: null })).toBeNull();
  });

  it("014-FR-013 spells the guarantee tier out, or says nothing at all", () => {
    expect(guaranteeTierLabel("guaranteed")).toBe("Guaranteed single start");
    expect(guaranteeTierLabel("best_effort")).toBe("Best-effort single start");
    // An untested connection has no tier, and inventing one would be a
    // promise about duplicate risk nobody made.
    expect(guaranteeTierLabel(null)).toBeNull();
    expect(
      compactRunLabel({
        primary_state_label: "Queued",
        guarantee_tier: null,
        cancel_outcome: "none"
      })
    ).toBe("Queued");
    expect(
      compactRunLabel({
        primary_state_label: "Running",
        guarantee_tier: "best_effort",
        cancel_outcome: "unconfirmed"
      })
    ).toBe("Running · Best-effort single start");
  });
});
