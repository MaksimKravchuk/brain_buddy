import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { AgentConnectionResponse, AgentRunSummaryResponse } from "../../../api/agentTypes";
import type { TaskResponse } from "../../../api/taskTypes";
import { TaskAgentControl } from "../TaskAgentControl";

function connection(overrides: Partial<AgentConnectionResponse> = {}): AgentConnectionResponse {
  return {
    id: "agent-hermes",
    name: "Hermes",
    agent_address: "https://hermes.example.test/a2a",
    auth_scheme: "bearer",
    auth_header_name: null,
    status: "ready",
    stale: false,
    ready_for_handoff: true,
    capabilities: { streaming: false, push_notifications: false },
    controls_offered: { reply: false, cancel: false },
    card: null,
    guarantee_tier: "guaranteed",
    tier_disclosure: null,
    tier_disclosure_url: null,
    cancellation_disclosure: null,
    agent_changed: false,
    best_effort_acknowledged_at: null,
    correlation_id_honoured: true,
    disconnect_reason: null,
    last_test_error_code: null,
    last_test_error_detail: null,
    last_contact_at: "2026-09-11T10:00:00Z",
    last_tested_at: "2026-09-11T10:00:00Z",
    stale_after_seconds: 3600,
    created_at: "2026-09-11T09:00:00Z",
    revision: 1,
    ...overrides
  };
}

const task = {
  id: "task-1",
  title: "Prepare the launch review",
  state: "next"
} as TaskResponse;

function run(overrides: Partial<AgentRunSummaryResponse> = {}): AgentRunSummaryResponse {
  return {
    id: "run-1",
    task_id: task.id,
    agent_name: "Hermes",
    primary_state_label: "Running",
    needs_user: false,
    stopped_reporting: false,
    last_contact_at: "2026-09-11T10:01:00Z",
    guarantee_tier: "guaranteed",
    cancel_outcome: "none",
    agent_task_missing: false,
    ...overrides
  };
}

describe("017-FR-007 017-FR-009 017-FR-010 017-FR-011 017-SC-006 compact task agent control", () => {
  it("uses the quiet split control for the last-used eligible agent with keyboard menu navigation", async () => {
    const user = userEvent.setup();
    const onReview = vi.fn();
    const agents = [
      connection(),
      connection({ id: "agent-argus", name: "Argus", agent_address: "https://argus.example.test/a2a" })
    ];

    render(
      <TaskAgentControl
        task={task}
        relayEnabled
        connections={agents}
        preferredConnectionId="agent-hermes"
        onReview={onReview}
        onOpenTask={vi.fn()}
      />
    );

    const primary = screen.getByRole("button", { name: "Hand Prepare the launch review to Hermes" });
    const chooser = screen.getByRole("button", { name: "Choose agent for Prepare the launch review" });
    expect(primary).toHaveClass("h-7");
    expect(chooser).toHaveClass("h-7");

    await user.click(primary);
    expect(onReview).toHaveBeenCalledWith("agent-hermes");

    await user.click(chooser);
    expect(screen.getByRole("menu", { name: "Choose agent" })).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: "Hermes" })).toHaveFocus();
    fireEvent.mouseDown(screen.getByRole("menuitem", { name: "Hermes" }));
    expect(screen.getByRole("menu", { name: "Choose agent" })).toBeInTheDocument();
    await user.keyboard("{ArrowDown}");
    expect(screen.getByRole("menuitem", { name: "Argus" })).toHaveFocus();
    await user.keyboard("{ArrowUp}{End}");
    expect(screen.getByRole("menuitem", { name: "Argus" })).toHaveFocus();
    await user.keyboard("{Home}{Escape}");
    expect(screen.queryByRole("menu", { name: "Choose agent" })).not.toBeInTheDocument();
    expect(chooser).toHaveFocus();

    await user.keyboard("{ArrowDown}");
    expect(screen.getByRole("menuitem", { name: "Hermes" })).toHaveFocus();
    await user.keyboard("{Escape}");
    await user.keyboard("{ArrowUp}");
    expect(screen.getByRole("menuitem", { name: "Argus" })).toHaveFocus();
    fireEvent.mouseDown(document.body);
    expect(screen.queryByRole("menu", { name: "Choose agent" })).not.toBeInTheDocument();

    await user.click(chooser);
    await user.keyboard("{ArrowDown}");
    await user.keyboard("{Enter}");
    expect(onReview).toHaveBeenLastCalledWith("agent-argus");
  });

  it("disambiguates duplicate agent names without making the row noisy", async () => {
    const user = userEvent.setup();
    render(
      <TaskAgentControl
        task={task}
        relayEnabled
        connections={[
          connection({ id: "agent-one", agent_address: "https://one.example.test/a2a" }),
          connection({ id: "agent-two", agent_address: "https://two.example.test/a2a" })
        ]}
        preferredConnectionId="agent-one"
        onReview={vi.fn()}
        onOpenTask={vi.fn()}
      />
    );

    await user.click(screen.getByRole("button", { name: "Choose agent for Prepare the launch review" }));
    expect(screen.getByRole("menuitem", { name: "Hermes · one.example.test" })).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: "Hermes · two.example.test" })).toBeInTheDocument();
  });

  it("falls back to the raw address when duplicate agent addresses are not URLs", async () => {
    const user = userEvent.setup();
    render(
      <TaskAgentControl
        task={task}
        relayEnabled
        connections={[
          connection({ id: "agent-one", agent_address: "not-a-url" }),
          connection({ id: "agent-two", agent_address: "also-not-a-url" })
        ]}
        onReview={vi.fn()}
        onOpenTask={vi.fn()}
      />
    );

    await user.click(screen.getByRole("button", { name: "Choose agent for Prepare the launch review" }));
    expect(screen.getByRole("menuitem", { name: "Hermes · not-a-url" })).toBeInTheDocument();
  });

  it("gates the split control for rollout, eligibility, and terminal task state", () => {
    const props = {
      task,
      connections: [connection()],
      onReview: vi.fn(),
      onOpenTask: vi.fn()
    };
    const { rerender } = render(<TaskAgentControl {...props} relayEnabled={false} />);
    expect(screen.queryByRole("button")).not.toBeInTheDocument();

    rerender(<TaskAgentControl {...props} relayEnabled connections={[connection({ ready_for_handoff: false })]} />);
    expect(screen.queryByRole("button")).not.toBeInTheDocument();

    rerender(<TaskAgentControl {...props} task={{ ...task, state: "completed" }} relayEnabled />);
    expect(screen.queryByRole("button")).not.toBeInTheDocument();

    rerender(<TaskAgentControl {...props} task={{ ...task, state: "cancelled" }} relayEnabled />);
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("renders every assigned status at one width with no chooser caret and full accessible disclosure", () => {
    const onOpenTask = vi.fn();
    const { rerender } = render(
      <TaskAgentControl
        task={task}
        run={run()}
        relayEnabled
        connections={[]}
        onReview={vi.fn()}
        onOpenTask={onOpenTask}
      />
    );

    const running = screen.getByRole("button", { name: /Hermes.*Running.*Guaranteed single start/i });
    expect(running).toHaveClass("h-7", "w-[184px]");
    expect(screen.getByText("Running")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Choose agent/i })).not.toBeInTheDocument();
    fireEvent.click(running);
    expect(onOpenTask).toHaveBeenCalledOnce();

    rerender(
      <TaskAgentControl
        task={task}
        run={run({ primary_state_label: "Agent reported complete" })}
        relayEnabled
        connections={[]}
        onReview={vi.fn()}
        onOpenTask={vi.fn()}
      />
    );
    expect(screen.getByText("Reported")).toBeInTheDocument();
    expect(screen.queryByText("Done")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Agent reported complete.*Guaranteed single start/i })).toHaveClass("w-[184px]");

    for (const [primaryState, visibleState, needsUser] of [
      ["Queued", "Queued", false],
      ["Failed", "Failed", false],
      ["Needs you", "Needs you", true],
      ["Disconnected", "Disconnected", false]
    ] as const) {
      rerender(
        <TaskAgentControl
          task={task}
          run={run({ primary_state_label: primaryState, needs_user: needsUser })}
          relayEnabled
          connections={[]}
          onReview={vi.fn()}
          onOpenTask={vi.fn()}
        />
      );
      expect(screen.getByText(visibleState)).toBeInTheDocument();
    }
  });
});
