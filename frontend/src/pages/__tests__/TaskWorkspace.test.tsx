import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import TaskWorkspace from "../TaskWorkspace";

async function click(user: ReturnType<typeof userEvent.setup>, target: HTMLElement) {
  await act(async () => {
    await user.click(target);
  });
}

describe("TaskWorkspace", () => {
  it("renders the literal Next actions source header and source task treatments", () => {
    render(<TaskWorkspace />);

    expect(screen.getByRole("heading", { name: "Next actions" })).toBeInTheDocument();
    expect(screen.getByText("6 tasks · 1 running on AI")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /group by project/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sort" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Think" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Edit tasks" })).not.toBeInTheDocument();
    expect(screen.queryByText("⌘ K")).not.toBeInTheDocument();
    expect(screen.getByText("Drafter · ready in ~5 min")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Thinking · 12 steps" })).toBeInTheDocument();
    expect(screen.getByText("AI can draft")).toBeInTheDocument();
    expect(screen.getByText("Needs you — choose a venue")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Choose one" })).toBeInTheDocument();
  });

  it("keeps each literal state treatment on the source fixture row", () => {
    render(<TaskWorkspace />);

    const dentistCard = screen
      .getByLabelText("Complete Call the dentist to reschedule")
      .closest("article");
    const pricingCard = screen
      .getByLabelText("Complete Review Q3 pricing assumptions")
      .closest("article");

    expect(dentistCard).not.toBeNull();
    expect(pricingCard).not.toBeNull();
    expect(within(dentistCard as HTMLElement).queryByText(/Thinking/)).not.toBeInTheDocument();
    expect(
      within(pricingCard as HTMLElement).getByRole("button", {
        name: "Thinking · 12 steps",
      })
    ).toBeInTheDocument();
  });

  it("uses source-specific metadata, controls, and placeholder copy outside Next actions", async () => {
    const user = userEvent.setup();
    render(<TaskWorkspace />);

    await click(user, screen.getByRole("button", { name: /Inbox 4/ }));
    expect(
      screen.getByText("Process these — decide the next action for each.")
    ).toBeInTheDocument();
    expect(screen.queryByText(/unprocessed thoughts/i)).not.toBeInTheDocument();

    await click(user, screen.getByRole("button", { name: /Weekly review due Sun/i }));
    expect(
      screen.getByText(
        "A guided pass over your lists — empty the inbox, refresh next actions, decide on the somedays. Due Sunday."
      )
    ).toBeInTheDocument();
    expect(screen.getByText("PLACEHOLDER — NOT DESIGNED YET")).toBeInTheDocument();
  });

  it("updates the visible list count while preserving the source project fixture count", async () => {
    const user = userEvent.setup();
    render(<TaskWorkspace />);

    await click(user,
      screen.getByRole("checkbox", { name: "Complete Draft the launch announcement" })
    );

    expect(screen.getByRole("button", { name: /Next actions 5/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Onboarding revamp 6/ })).toBeInTheDocument();

    await click(user, screen.getByRole("button", { name: /Onboarding revamp 6/ }));
    expect(screen.getByText("6 tasks · 1 running on AI")).toBeInTheDocument();
  });

  it("opens expanded details from the source thinking affordance", async () => {
    const user = userEvent.setup();
    render(<TaskWorkspace />);

    await click(user, screen.getByRole("button", { name: "Thinking · 12 steps" }));

    expect(screen.getByRole("region", { name: "Task details" })).toBeInTheDocument();
    expect(screen.getByText("Run log")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Choose" })).toBeInTheDocument();
  });

  it("matches the source recording overlay and closes it from Stop", async () => {
    const user = userEvent.setup();
    render(<TaskWorkspace />);
    const trigger = screen.getByRole("button", { name: /brain dump/i });

    await click(user, trigger);

    expect(screen.getByText("Speak freely — tasks are extracted as you go")).toBeInTheDocument();
    expect(screen.getByText("0:00")).toBeInTheDocument();
    expect(screen.getByText("Nothing is saved until you stop")).toBeInTheDocument();
    expect(screen.getByText("HEADED TO INBOX · 0")).toBeInTheDocument();
    expect(screen.getByText("Tasks appear here as you speak")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Stop" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Stop & send/i })).not.toBeInTheDocument();

    await click(user, screen.getByRole("button", { name: "Stop" }));
    expect(screen.queryByRole("dialog", { name: "Brain dump" })).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });

  it("exposes the represented review and send states through the deterministic QA state hook", async () => {
    const user = userEvent.setup();
    render(<TaskWorkspace />);

    act(() => {
      window.dispatchEvent(
        new CustomEvent("brainbuddy:brain-dump-state", { detail: "captured" })
      );
    });
    expect(screen.getByText("Forming another task…")).toBeInTheDocument();

    act(() => {
      window.dispatchEvent(
        new CustomEvent("brainbuddy:brain-dump-state", { detail: "review" })
      );
    });

    expect(screen.getByRole("dialog", { name: "Brain dump" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /send to inbox/i })).toBeInTheDocument();

    await click(user, screen.getByRole("button", { name: /send to inbox/i }));
    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "Inbox" })).toBeInTheDocument();
      expect(screen.getByText("1 task sent to inbox")).toBeInTheDocument();
      expect(screen.getAllByRole("article")).toHaveLength(5);
    });
  });
});