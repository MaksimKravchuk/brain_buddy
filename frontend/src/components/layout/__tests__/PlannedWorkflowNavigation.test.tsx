import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { PlannedWorkflowNavigation } from "../PlannedWorkflowNavigation";

describe("PlannedWorkflowNavigation", () => {
  it("renders separate CRT and Weekly Review placeholders marked Coming Later", () => {
    render(<PlannedWorkflowNavigation />);

    const navigation = screen.getByRole("navigation", { name: /planned workflows/i });
    const crt = within(navigation).getByRole("button", { name: /crt.*coming later/i });
    const weeklyReview = within(navigation).getByRole("button", {
      name: /weekly review.*coming later/i
    });

    expect(crt).toBeDisabled();
    expect(weeklyReview).toBeDisabled();
    expect(within(crt).getByText("Coming Later")).toBeInTheDocument();
    expect(within(weeklyReview).getByText("Coming Later")).toBeInTheDocument();
    expect(within(navigation).queryAllByRole("link")).toHaveLength(0);
  });
});
