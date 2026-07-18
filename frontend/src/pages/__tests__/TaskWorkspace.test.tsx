import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import TaskWorkspace from "../TaskWorkspace";

describe("TaskWorkspace", () => {
  it("renders the source default and groups tasks without changing the selected list", async () => {
    const user = userEvent.setup();
    render(<TaskWorkspace />);

    expect(screen.getByRole("heading", { name: "Next actions" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Next actions 6/ })).toHaveAttribute(
      "aria-current",
      "page"
    );

    await user.click(screen.getByRole("button", { name: /group by project/i }));

    expect(
      screen.getByRole("heading", { name: /Onboarding revamp 2/ })
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Next actions 6/ })).toHaveAttribute(
      "aria-current",
      "page"
    );
  });

  it("updates a visible count when a task is completed", async () => {
    const user = userEvent.setup();
    render(<TaskWorkspace />);

    await user.click(screen.getByRole("button", { name: /Inbox 4/ }));
    await user.click(screen.getAllByRole("checkbox")[0]);

    await waitFor(() =>
      expect(screen.getByRole("button", { name: /Inbox 3/ })).toBeInTheDocument()
    );
  });

  it("keeps the two represented rows for each source project fixture", async () => {
    const user = userEvent.setup();
    render(<TaskWorkspace />);

    await user.click(screen.getByRole("button", { name: /Pricing 4/ }));
    expect(screen.getAllByRole("article")).toHaveLength(2);

    await user.click(screen.getByRole("button", { name: /Team offsite 3/ }));
    expect(screen.getAllByRole("article")).toHaveLength(2);
  });

  it("represents the Think control, AI squircle, and compact edit state", async () => {
    const user = userEvent.setup();
    render(<TaskWorkspace />);

    expect(screen.getByRole("button", { name: "Think" })).toBeInTheDocument();
    expect(screen.getByLabelText("AI working on Draft the launch announcement")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Edit tasks" }));
    expect(screen.getByRole("button", { name: "Edit tasks" })).toHaveAttribute(
      "aria-pressed",
      "true"
    );
  });

  it("projects completion through list and project counts with metadata", async () => {
    const user = userEvent.setup();
    render(<TaskWorkspace />);

    await user.click(screen.getByRole("checkbox", { name: "Complete Draft the launch announcement" }));
    expect(screen.getByRole("button", { name: /Next actions 5/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Onboarding revamp 5/ })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /Onboarding revamp 5/ }));
    expect(screen.getByText("5 tasks · 0 running on AI")).toBeInTheDocument();
  });

  it("opens Brain Dump in its represented recording state before capture", async () => {
    const user = userEvent.setup();
    render(<TaskWorkspace />);

    await user.click(screen.getByRole("button", { name: /brain dump/i }));
    expect(screen.getByText("No tasks captured yet")).toBeInTheDocument();
    expect(screen.getByText("Keep talking — Brain Buddy will collect useful next actions here.")).toBeInTheDocument();
  });

  it("closes Brain Dump with Escape and restores focus to its trigger", async () => {
    const user = userEvent.setup();
    render(<TaskWorkspace />);
    const trigger = screen.getByRole("button", { name: /brain dump/i });

    await user.click(trigger);
    expect(screen.getByRole("button", { name: "Close brain dump" })).toHaveFocus();

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog", { name: "Brain dump" })).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });

  it("sends a brain dump to Inbox and shows the source toast", async () => {
    const user = userEvent.setup();
    render(<TaskWorkspace />);

    await user.click(screen.getByRole("button", { name: /brain dump/i }));
    await user.click(screen.getByRole("button", { name: /stop & send/i }));
    await user.click(screen.getByRole("button", { name: /send to inbox/i }));

    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "Inbox" })).toBeInTheDocument();
      expect(screen.getByText("1 task sent to inbox")).toBeInTheDocument();
      expect(screen.getAllByRole("article")).toHaveLength(5);
    });
  });
});
