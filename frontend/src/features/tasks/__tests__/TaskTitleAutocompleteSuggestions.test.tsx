import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { TaskTitleAutocompleteSuggestions } from "../TaskTitleAutocompleteSuggestions";

const candidates = ["Prepare launch notes", "Prepare launch checklist", "Prepare launch update"];

describe("TaskTitleAutocompleteSuggestions", () => {
  // 012-FR-001 012-FR-004 012-SC-003: one accessible, keyboard-owned listbox.
  it("renders one accessible three-option listbox with a stable active option", () => {
    render(
      <TaskTitleAutocompleteSuggestions
        candidates={candidates}
        activeIndex={1}
        listboxId="title-completions"
        onSelect={vi.fn()}
      />
    );

    const listbox = screen.getByRole("listbox", { name: "Task title suggestions" });
    const options = within(listbox).getAllByRole("option");
    expect(options).toHaveLength(3);
    expect(options[1]).toHaveAttribute("id", "title-completions-option-1");
    expect(options[1]).toHaveAttribute("aria-selected", "true");
  });

  it("selects by pointer without stealing input focus on mouse down", async () => {
    const onSelect = vi.fn();
    const user = userEvent.setup();
    render(
      <TaskTitleAutocompleteSuggestions
        candidates={candidates}
        activeIndex={0}
        listboxId="title-completions"
        onSelect={onSelect}
      />
    );

    await user.click(screen.getByRole("option", { name: "Prepare launch checklist" }));
    expect(onSelect).toHaveBeenCalledWith("Prepare launch checklist", 2);
  });

  it("renders nothing unless the provider returns exactly three candidates", () => {
    const { container } = render(
      <TaskTitleAutocompleteSuggestions
        candidates={candidates.slice(0, 2)}
        activeIndex={0}
        listboxId="title-completions"
        onSelect={vi.fn()}
      />
    );

    expect(container).toBeEmptyDOMElement();
  });
});
