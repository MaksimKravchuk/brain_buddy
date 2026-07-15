import { render, screen, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { BrainDumpRoute } from "./BrainDumpRoute";

function renderBrainDump(initialEntry: string) {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <Routes>
        <Route path="/brain-dump/:operationId" element={<BrainDumpRoute />} />
        <Route path="/brain-dump/:operationId/review" element={<BrainDumpRoute />} />
      </Routes>
    </MemoryRouter>
  );
}

describe("BrainDumpRoute", () => {
  it("renders the source-derived recording task capture with explicit stop/review wording", () => {
    renderBrainDump("/brain-dump/new");

    const dialog = screen.getByRole("dialog", { name: "Brain dump" });
    expect(within(dialog).getByText("9 tasks captured")).toBeInTheDocument();
    expect(within(dialog).getByText("Headed to inbox · 9")).toBeInTheDocument();
    expect(within(dialog).getByText("Call dentist to move Monday's appointment")).toBeInTheDocument();
    expect(within(dialog).getByText("#9")).toBeInTheDocument();
    expect(within(dialog).getByText("Wording still changing")).toBeInTheDocument();
    expect(within(dialog).getByText("Nothing is saved until you stop")).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Stop & review" })).toBeEnabled();
    expect(within(dialog).queryByText(/Stop & send/i)).not.toBeInTheDocument();
  });

  it("renders the review surface with editable cards, delete affordance and final inbox confirmation", () => {
    renderBrainDump("/brain-dump/new/review");

    expect(screen.getByRole("heading", { name: "Review 9 tasks" })).toBeInTheDocument();
    expect(screen.getByText("Edit before they land in your inbox")).toBeInTheDocument();
    expect(screen.getByText("#1")).toBeInTheDocument();
    expect(screen.getAllByText("Ready to review").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByDisplayValue("Renew car insurance")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Delete Update pricing page copy" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add a task" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save 9 to inbox" })).toBeEnabled();
    expect(screen.queryByText(/Send 9 to inbox/i)).not.toBeInTheDocument();
  });
});
