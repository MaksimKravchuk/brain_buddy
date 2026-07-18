import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

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

  it("does not show source-absent project counts and keeps New project in the projects section", () => {
    render(<TaskWorkspace />);

    expect(screen.queryByText("Onboarding revamp 6")).not.toBeInTheDocument();
    const onboardingButton = screen.getByRole("button", { name: /Onboarding revamp/ });
    expect(within(onboardingButton).queryByText("6")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /New project/i })).toBeInTheDocument();
  });

  it("keeps each literal state treatment on the source fixture row", () => {
    render(<TaskWorkspace />);

    const dentistCard = screen.getByText("Call the dentist to reschedule").closest("article");
    const pricingCard = screen.getByText("Review Q3 pricing assumptions").closest("article");

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

    await click(user, screen.getByRole("button", { name: /Inbox/ }));
    expect(
      screen.getByText("Process these — decide the next action for each.")
    ).toBeInTheDocument();
    expect(screen.queryByText(/unprocessed thoughts/i)).not.toBeInTheDocument();

    await click(user, screen.getByRole("button", { name: /Weekly review/i }));
    expect(
      screen.getByText(
        "A guided pass over your lists — empty the inbox, refresh next actions, decide on the somedays. Due Sunday."
      )
    ).toBeInTheDocument();
    expect(screen.getByText("Placeholder — not designed yet")).toBeInTheDocument();
  });

  it("updates the visible list count while completing a task", async () => {
    const user = userEvent.setup();
    render(<TaskWorkspace />);

    await click(user, screen.getByRole("button", { name: /Complete Draft the launch announcement/ }));

    expect(screen.getByRole("button", { name: /Next actions/ })).toHaveTextContent("5");
  });

  it("opens expanded details from the source thinking affordance with literal placeholder content", async () => {
    const user = userEvent.setup();
    render(<TaskWorkspace />);

    await click(user, screen.getByRole("button", { name: "Thinking · 12 steps" }));

    expect(screen.getByLabelText("Task details")).toBeInTheDocument();
    expect(screen.getByText("Subtasks")).toBeInTheDocument();
    expect(screen.getByText("Agent")).toBeInTheDocument();
    expect(screen.getByText("Comments")).toBeInTheDocument();
  });

  it("expands the literal run log for a task that has one", async () => {
    const user = userEvent.setup();
    render(<TaskWorkspace />);

    const dentistCard = screen.getByText("Draft the launch announcement").closest("article") as HTMLElement;
    await click(user, within(dentistCard).getByText("Draft the launch announcement"));

    expect(within(dentistCard).getByText("Run log")).toBeInTheDocument();
    expect(within(dentistCard).getByText("Drafting outline")).toBeInTheDocument();
  });

  it("matches the source recording overlay and progresses to review naturally after capture", async () => {
    vi.useFakeTimers();
    const user = userEvent.setup({ delay: null, advanceTimers: vi.advanceTimersByTime });
    render(<TaskWorkspace />);
    const trigger = screen.getByRole("button", { name: /brain dump/i });

    await click(user, trigger);

    expect(screen.getByText("Speak freely — tasks are extracted as you go")).toBeInTheDocument();
    expect(screen.getByText("0:00")).toBeInTheDocument();
    expect(screen.getByText("Nothing is saved until you stop")).toBeInTheDocument();
    expect(screen.getByText("Tasks appear here as you speak")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Stop" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Stop & send/i })).not.toBeInTheDocument();

    // Advance the deterministic capture timeline past the first captured task (~4.5s).
    await act(async () => {
      vi.advanceTimersByTime(4600);
    });

    expect(screen.getByRole("button", { name: /Stop & send 1 to inbox/i })).toBeInTheDocument();

    await click(user, screen.getByRole("button", { name: /Stop & send 1 to inbox/i }));

    expect(screen.getByRole("dialog", { name: "Brain dump" })).toBeInTheDocument();
    expect(screen.getByText("Review 1 task")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /send 1 to inbox/i })).toBeInTheDocument();

    await click(user, screen.getByRole("button", { name: /send 1 to inbox/i }));

    expect(screen.getByRole("heading", { name: "Inbox" })).toBeInTheDocument();
    expect(screen.getByText("1 task sent to inbox")).toBeInTheDocument();
    vi.useRealTimers();
  });

  it("closes the recording overlay from Stop with zero captured tasks and returns focus", async () => {
    const user = userEvent.setup();
    render(<TaskWorkspace />);
    const trigger = screen.getByRole("button", { name: /brain dump/i });

    await click(user, trigger);
    await click(user, screen.getByRole("button", { name: "Stop" }));

    expect(screen.queryByRole("dialog", { name: "Brain dump" })).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });
});
