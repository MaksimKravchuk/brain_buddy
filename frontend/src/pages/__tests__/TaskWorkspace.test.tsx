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

  it("closes the recording overlay via Escape and returns focus to the trigger", async () => {
    const user = userEvent.setup();
    render(<TaskWorkspace />);
    const trigger = screen.getByRole("button", { name: /brain dump/i });

    await click(user, trigger);
    expect(screen.getByRole("dialog", { name: "Brain dump" })).toBeInTheDocument();

    await act(async () => {
      await user.keyboard("{Escape}");
    });

    expect(screen.queryByRole("dialog", { name: "Brain dump" })).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });

  it("groups Next actions by project, showing a No project group, and can be toggled back off", async () => {
    const user = userEvent.setup();
    const { container } = render(<TaskWorkspace />);

    await click(user, screen.getByRole("button", { name: /group by project/i }));

    const groupedList = container.querySelector(".grouped-list");
    expect(groupedList).not.toBeNull();
    expect(within(groupedList as HTMLElement).getByText("No project")).toBeInTheDocument();
    expect(within(groupedList as HTMLElement).getByText("Call the dentist to reschedule")).toBeInTheDocument();
    expect(within(groupedList as HTMLElement).getByText("Onboarding revamp")).toBeInTheDocument();

    await click(user, screen.getByRole("button", { name: /group by project/i }));
    expect(container.querySelector(".grouped-list")).not.toBeInTheDocument();
  });

  it("adds a subtask and toggles the incomplete one from the expanded task detail", async () => {
    const user = userEvent.setup();
    render(<TaskWorkspace />);

    await click(user, screen.getByText("Draft the launch announcement"));
    const subtaskInput = screen.getByPlaceholderText("Add a subtask");

    await act(async () => {
      await user.type(subtaskInput, "Send for legal review{Enter}");
    });
    expect(screen.getByText("Send for legal review")).toBeInTheDocument();

    const incompleteSubtask = screen.getByText("Review Drafter's draft");
    const toggleButton = incompleteSubtask
      .closest(".task-subtask")
      ?.querySelector("button.task-check-sm") as HTMLElement;
    await click(user, toggleButton);
    expect(incompleteSubtask).toHaveClass("task-subtask-done");
  });

  it("hands a task with no run log off to an agent from the expanded detail", async () => {
    const user = userEvent.setup();
    render(<TaskWorkspace />);

    await click(user, screen.getByText("Call the dentist to reschedule"));

    expect(screen.getByText("No agent on this task.")).toBeInTheDocument();
    await click(user, screen.getByRole("button", { name: "Hand to agent" }));
    expect(screen.getByText("Task details isn't built yet — placeholder")).toBeInTheDocument();

    await click(user, screen.getByRole("button", { name: /Edit prompt & hand off/ }));
    expect(screen.getByText("Task details isn't built yet — placeholder")).toBeInTheDocument();
  });

  it("runs the ask-step action and artifact affordance inside an expanded run log", async () => {
    const user = userEvent.setup();
    render(<TaskWorkspace />);

    await click(user, screen.getByText("Choose a venue for the offsite"));
    const askActions = screen.getAllByRole("button", { name: "Choose one" });
    await click(user, askActions[askActions.length - 1]);
    expect(screen.getByText("Task details isn't built yet — placeholder")).toBeInTheDocument();

    await click(user, screen.getByRole("button", { name: /Waiting for/ }));
    await click(user, screen.getByText("Compare-plans research"));
    await click(user, screen.getByRole("button", { name: "Comparison v2" }));
    expect(screen.getByText("Task details isn't built yet — placeholder")).toBeInTheDocument();
  });

  it("adds a comment from the expanded task detail", async () => {
    const user = userEvent.setup();
    render(<TaskWorkspace />);

    await click(user, screen.getByText("Draft the launch announcement"));
    const commentInput = screen.getByPlaceholderText("Add a comment");

    await act(async () => {
      await user.type(commentInput, "Looks great{Enter}");
    });
    expect(screen.getByText("Looks great")).toBeInTheDocument();
  });

  it("edits, adds a due date to, and removes a task inside Brain Dump review before sending", async () => {
    vi.useFakeTimers();
    const user = userEvent.setup({ delay: null, advanceTimers: vi.advanceTimersByTime });
    render(<TaskWorkspace />);

    await click(user, screen.getByRole("button", { name: /brain dump/i }));

    // Advance past two captured tasks so review has an item without a due date.
    await act(async () => {
      vi.advanceTimersByTime(9000);
    });

    await click(user, screen.getByRole("button", { name: /Stop & send \d to inbox/i }));
    expect(screen.getByRole("dialog", { name: "Brain dump" })).toBeInTheDocument();

    const titleInputs = screen.getAllByLabelText("Task title");
    expect(titleInputs.length).toBeGreaterThanOrEqual(2);

    await act(async () => {
      await user.clear(titleInputs[0]);
      await user.type(titleInputs[0], "Edited task title");
    });
    expect(titleInputs[0]).toHaveValue("Edited task title");

    const addDateButtons = screen.getAllByRole("button", { name: /Add date/i });
    await click(user, addDateButtons[0]);
    expect(screen.getByText("Date picker isn't built yet — placeholder")).toBeInTheDocument();

    const removeButtons = screen.getAllByRole("button", { name: "Remove task" });
    const remainingBefore = removeButtons.length;
    await click(user, removeButtons[0]);
    expect(screen.getAllByRole("button", { name: "Remove task" }).length).toBe(remainingBefore - 1);

    await click(user, screen.getByRole("button", { name: /send \d to inbox/i }));
    expect(screen.getByRole("heading", { name: "Inbox" })).toBeInTheDocument();
    vi.useRealTimers();
  });

  it("adds a task to a non-Next list via the add-task prompt", async () => {
    const user = userEvent.setup();
    const promptSpy = vi.spyOn(window, "prompt").mockReturnValue("Pack the passport photos");
    render(<TaskWorkspace />);

    await click(user, screen.getByRole("button", { name: /Someday \/ maybe/i }));
    await click(user, screen.getByRole("button", { name: "Add a task" }));

    expect(promptSpy).toHaveBeenCalledWith("New task");
    expect(screen.getByText("Pack the passport photos")).toBeInTheDocument();
    promptSpy.mockRestore();
  });

  it("ignores the add-task prompt when the entry is blank", async () => {
    const user = userEvent.setup();
    const promptSpy = vi.spyOn(window, "prompt").mockReturnValue("   ");
    render(<TaskWorkspace />);

    await click(user, screen.getByRole("button", { name: /Waiting for/i }));
    await click(user, screen.getByRole("button", { name: "Add a task" }));

    expect(screen.getByRole("button", { name: /Waiting for/ })).toHaveTextContent("2");
    promptSpy.mockRestore();
  });

  it("opens a project pane, runs Think and add-task placeholders, and toggles a task", async () => {
    const user = userEvent.setup();
    const { container } = render(<TaskWorkspace />);

    await click(user, screen.getByRole("button", { name: /Onboarding revamp/ }));

    expect(screen.getByRole("heading", { name: "Onboarding revamp" })).toBeInTheDocument();
    expect(screen.getByText("6 tasks · 1 running on AI")).toBeInTheDocument();

    await click(user, screen.getByRole("button", { name: "Think" }));
    expect(screen.getByText("Thinking canvas isn't built yet — placeholder")).toBeInTheDocument();

    const pane = container.querySelector(".task-content-inner") as HTMLElement;
    await click(
      user,
      within(pane).getByRole("button", { name: /Complete Write the onboarding email sequence/ })
    );

    await click(user, within(pane).getByText("Draft the launch announcement"));
    expect(within(pane).getByLabelText("Task details")).toBeInTheDocument();
    await click(user, within(pane).getByRole("button", { name: "AI can draft" }));
    expect(screen.getByText("Task details isn't built yet — placeholder")).toBeInTheDocument();

    await click(user, screen.getByRole("button", { name: "Add a task to this project" }));
    expect(screen.getByText("Add to project isn't built yet — placeholder")).toBeInTheDocument();
  });

  it("opens a context pane showing project labels on its tasks and can expand a row", async () => {
    const user = userEvent.setup();
    const { container } = render(<TaskWorkspace />);

    await click(user, screen.getByRole("button", { name: "@deep-work" }));

    expect(screen.getByRole("heading", { name: "@deep-work" })).toBeInTheDocument();
    expect(screen.getByText(/tasks across your lists/)).toBeInTheDocument();
    const pane = container.querySelector(".task-content-inner") as HTMLElement;
    expect(within(pane).getByText("Onboarding revamp")).toBeInTheDocument();
    expect(within(pane).getByText("Pricing")).toBeInTheDocument();

    await click(user, within(pane).getByText("Draft the launch announcement"));
    expect(within(pane).getByLabelText("Task details")).toBeInTheDocument();
    await click(user, within(pane).getByRole("button", { name: /Complete Draft the launch announcement/ }));
  });

  it("runs the Sort placeholder and navigates back to Next actions from another view", async () => {
    const user = userEvent.setup();
    render(<TaskWorkspace />);

    await click(user, screen.getByRole("button", { name: "Sort" }));
    expect(screen.getByText("Sorting isn't built yet — placeholder")).toBeInTheDocument();

    await click(user, screen.getByRole("button", { name: /Waiting for/i }));
    expect(screen.getByRole("heading", { name: "Waiting for" })).toBeInTheDocument();

    await click(user, screen.getByRole("button", { name: /^Next actions/ }));
    expect(screen.getByRole("heading", { name: "Next actions" })).toBeInTheDocument();
  });

  it("triggers placeholder actions from the topbar search, avatar menu, and New project", async () => {
    const user = userEvent.setup();
    render(<TaskWorkspace />);

    const search = screen.getByPlaceholderText("Search tasks and trees");
    await act(async () => {
      await user.type(search, "flaky emails{Enter}");
    });
    expect(screen.getByText("Search isn't built yet — placeholder")).toBeInTheDocument();

    await click(user, screen.getByRole("button", { name: "TS" }));
    expect(screen.getByText("Account menu isn't built yet — placeholder")).toBeInTheDocument();

    await click(user, screen.getByRole("button", { name: /New project/i }));
    expect(screen.getByText("New project isn't built yet — placeholder")).toBeInTheDocument();
  });

  it("ignores whitespace-only subtask and comment drafts on the expanded task detail", async () => {
    const user = userEvent.setup();
    const { container } = render(<TaskWorkspace />);

    await click(user, screen.getByText("Draft the launch announcement"));

    const subtaskInput = screen.getByPlaceholderText("Add a subtask");
    await act(async () => {
      await user.type(subtaskInput, "   {Enter}");
    });
    expect(container.querySelectorAll(".task-subtask")).toHaveLength(2);

    const commentInput = screen.getByPlaceholderText("Add a comment");
    await act(async () => {
      await user.type(commentInput, "   {Enter}");
    });
    expect(container.querySelectorAll(".task-comment")).toHaveLength(1);
  });

  it("collapses an expanded task detail when the row is toggled a second time", async () => {
    const user = userEvent.setup();
    render(<TaskWorkspace />);

    await click(user, screen.getByText("Draft the launch announcement"));
    expect(screen.getByLabelText("Task details")).toBeInTheDocument();

    await click(user, screen.getByText("Draft the launch announcement"));
    expect(screen.queryByLabelText("Task details")).not.toBeInTheDocument();
  });

  it("shows the source forming preview mid-utterance before a brain-dump task is confirmed", async () => {
    vi.useFakeTimers();
    const user = userEvent.setup({ delay: null, advanceTimers: vi.advanceTimersByTime });
    const { container } = render(<TaskWorkspace />);

    await click(user, screen.getByRole("button", { name: /brain dump/i }));

    await act(async () => {
      vi.advanceTimersByTime(3700);
    });

    expect(container.querySelector(".dump-forming")).toHaveTextContent("email the venue about catering…");
    vi.useRealTimers();
  });

  it("renders due, context, and AI-offer chips for every captured brain-dump task through review and sends the plural notification", async () => {
    vi.useFakeTimers();
    const user = userEvent.setup({ delay: null, advanceTimers: vi.advanceTimersByTime });
    render(<TaskWorkspace />);

    await click(user, screen.getByRole("button", { name: /brain dump/i }));

    // Advance past all five scripted captures (renew passport @errands, fix flaky signup emails AI-offer, etc.).
    await act(async () => {
      vi.advanceTimersByTime(20000);
    });

    const dialog = screen.getByRole("dialog", { name: "Brain dump" });
    expect(within(dialog).getByText("@errands")).toBeInTheDocument();
    expect(within(dialog).getByText("AI can draft")).toBeInTheDocument();
    expect(within(dialog).getByText("before Thu")).toBeInTheDocument();

    await click(user, screen.getByRole("button", { name: /Stop & send 5 to inbox/i }));

    const reviewDialog = screen.getByRole("dialog", { name: "Brain dump" });
    expect(within(reviewDialog).getByText("@errands")).toBeInTheDocument();
    expect(within(reviewDialog).getByText("AI can draft")).toBeInTheDocument();

    await click(user, screen.getByRole("button", { name: /send 5 to inbox/i }));

    expect(screen.getByText("5 tasks sent to inbox")).toBeInTheDocument();
    vi.useRealTimers();
  });

  it("shows the singular task count once a list is reduced to one remaining task", async () => {
    const user = userEvent.setup();
    render(<TaskWorkspace />);

    await click(user, screen.getByRole("button", { name: /Waiting for/i }));
    await click(user, screen.getByRole("button", { name: /Complete Contract redlines from the venue/ }));

    expect(screen.getByText("1 task")).toBeInTheDocument();
  });

  it("shows the singular task count for a context with exactly one matching task", async () => {
    const user = userEvent.setup();
    render(<TaskWorkspace />);

    await click(user, screen.getByRole("button", { name: "@calls" }));

    expect(screen.getByText("1 task across your lists")).toBeInTheDocument();
  });

  it("hides the inbox sidebar badge once every inbox task is completed", async () => {
    const user = userEvent.setup();
    const { container } = render(<TaskWorkspace />);

    await click(user, screen.getByRole("button", { name: /^Inbox/ }));
    expect(container.querySelector(".sidebar-badge-inbox")).toBeInTheDocument();

    await click(user, screen.getByRole("button", { name: /Complete Figure out what to do about the flaky signup emails/ }));
    await click(user, screen.getByRole("button", { name: /Complete Sarah mentioned a grant deadline/ }));
    await click(user, screen.getByRole("button", { name: /Complete Idea: sample data preinstalled on signup/ }));
    await click(user, screen.getByRole("button", { name: /Complete Renew passport\?/ }));

    expect(container.querySelector(".sidebar-badge-inbox")).not.toBeInTheDocument();
  });
});
