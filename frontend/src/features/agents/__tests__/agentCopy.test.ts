import { describe, expect, it } from "vitest";

import type { AgentConnectionResponse } from "../../../api/agentTypes";
import {
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
  endpoint_url: "https://agent.example.com/hooks",
  auth_header_name: "Authorization",
  status: "ready",
  stale: false,
  ready_for_handoff: true,
  capabilities: { progress: true, reply: true, cancel: false },
  last_test_error_code: null,
  last_contact_at: "2026-08-09T10:00:00Z",
  last_tested_at: "2026-08-09T10:00:00Z",
  stale_after_seconds: 3600,
  created_at: "2026-08-09T09:00:00Z",
  revision: 1
};

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
      "Unsupported connector"
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
    expect(connectionStatusDetail({ ...base, status: "unsupported" })).toMatch(/protocol version/i);
    expect(connectionStatusDetail({ ...base, status: "disconnected" })).toMatch(/credential was destroyed/i);
    expect(connectionStatusDetail(base)).toMatch(/authenticated/i);
  });

  it("discloses unsupported capabilities as explicitly as supported ones", () => {
    expect(capabilityDisclosure({ progress: true, reply: false, cancel: false })).toEqual([
      { label: "Progress updates", supported: true },
      { label: "Replies to questions", supported: false },
      { label: "Cancellation", supported: false }
    ]);
  });

  it("says never rather than guessing when a timestamp is absent", () => {
    expect(formatTimestamp(null)).toBe("Never");
    expect(formatTimestamp("not-a-date")).toBe("not-a-date");
    expect(formatTimestamp("2026-08-09T10:00:00Z")).not.toBe("Never");
  });

  it("formats the server-configured thresholds in plain units", () => {
    expect(formatDuration(45)).toBe("45 seconds");
    expect(formatDuration(60)).toBe("1 minute");
    expect(formatDuration(900)).toBe("15 minutes");
    expect(formatDuration(3600)).toBe("1 hour");
    expect(formatDuration(7200)).toBe("2 hours");
  });
});
