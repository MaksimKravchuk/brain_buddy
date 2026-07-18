import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { SmartAddSuggestions } from "../SmartAddSuggestions";

const suggestions = [
  { kind: "tag" as const, label: "work", ref: { id: "tag-work" }, create: false },
  { kind: "tag" as const, label: "Create #writer", ref: { name: "writer" }, create: true }
];

describe("SmartAddSuggestions", () => {
  it("does not render a popup without suggestions", () => {
    render(<SmartAddSuggestions suggestions={[]} activeIndex={0} listboxId="smart-add" onSelect={vi.fn()} />);

    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  });

  it("exposes the active option and forwards pointer selection", async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    render(<SmartAddSuggestions suggestions={suggestions} activeIndex={1} listboxId="smart-add" onSelect={onSelect} />);

    const listbox = screen.getByRole("listbox", { name: "Smart Add suggestions" });
    expect(listbox).toHaveAttribute("id", "smart-add");
    expect(screen.getByRole("option", { name: "work" })).toHaveAttribute("aria-selected", "false");
    expect(screen.getByRole("option", { name: "Create #writer" })).toHaveAttribute("aria-selected", "true");

    await user.click(screen.getByRole("option", { name: "work" }));
    expect(onSelect).toHaveBeenCalledWith(suggestions[0]);
  });
});
