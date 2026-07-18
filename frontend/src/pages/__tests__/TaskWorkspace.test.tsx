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

  it("sends a brain dump to Inbox and shows the source toast", async () => {
    const user = userEvent.setup();
    render(<TaskWorkspace />);

    await user.click(screen.getByRole("button", { name: /brain dump/i }));
    await user.click(screen.getByRole("button", { name: /stop & send/i }));
    await user.click(screen.getByRole("button", { name: /send to inbox/i }));

    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "Inbox" })).toBeInTheDocument();
      expect(screen.getByText("1 task sent to inbox")).toBeInTheDocument();
    });
  });
});
