import { act, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import {
  DropdownMenu,
  DropdownMenuDivider,
  DropdownMenuItem,
  DropdownMenuSection
} from "../DropdownMenu";

describe("DropdownMenu", () => {
  it("opens from its trigger, supports roving keyboard navigation, and closes after selection", async () => {
    const user = userEvent.setup();
    const onFirst = vi.fn();
    const onSecond = vi.fn();
    render(
      <DropdownMenu trigger={<button type="button">Actions</button>} align="end" menuClassName="custom-menu">
        <DropdownMenuItem onSelect={onFirst}>First action</DropdownMenuItem>
        <DropdownMenuItem onSelect={onSecond} leftIcon={<span>+</span>} variant="danger">
          Second action
        </DropdownMenuItem>
      </DropdownMenu>
    );

    await act(async () => {
      await user.click(screen.getByRole("button", { name: "Actions" }));
    });
    const menu = screen.getByRole("menu");
    expect(screen.getByRole("menuitem", { name: "First action" })).toHaveFocus();
    expect(menu).toHaveClass("right-0", "custom-menu");

    await act(async () => {
      await user.keyboard("{ArrowDown}");
    });
    expect(screen.getByRole("menuitem", { name: /Second action/ })).toHaveFocus();
    await act(async () => {
      await user.keyboard("{Home}");
      await user.keyboard("{Enter}");
    });
    expect(onFirst).toHaveBeenCalledOnce();
    expect(screen.getByRole("button", { name: "Actions" })).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByRole("menu")).toHaveClass("animate-fade-out");
  });

  it("keeps disabled items inert and lets an item opt out of automatic closing", async () => {
    const user = userEvent.setup();
    const onDisabled = vi.fn();
    const onPersistent = vi.fn();
    render(
      <DropdownMenu trigger={<button type="button">More</button>}>
        <DropdownMenuItem disabled onSelect={onDisabled}>Unavailable</DropdownMenuItem>
        <DropdownMenuItem closeOnSelect={false} onSelect={onPersistent}>Keep open</DropdownMenuItem>
      </DropdownMenu>
    );

    await act(async () => {
      await user.click(screen.getByRole("button", { name: "More" }));
    });
    expect(screen.getByRole("menuitem", { name: "Unavailable" })).toBeDisabled();
    await act(async () => {
      await user.click(screen.getByRole("menuitem", { name: "Keep open" }));
    });
    expect(onPersistent).toHaveBeenCalledOnce();
    expect(onDisabled).not.toHaveBeenCalled();
    expect(screen.getByRole("menu")).toBeInTheDocument();
  });

  it("closes on Escape and outside pointer interactions while returning focus to the trigger", async () => {
    const user = userEvent.setup();
    render(
      <>
        <button type="button">Outside</button>
        <DropdownMenu trigger={<button type="button">Open menu</button>}>
          <DropdownMenuItem>Action</DropdownMenuItem>
        </DropdownMenu>
      </>
    );
    const trigger = screen.getByRole("button", { name: "Open menu" });

    await act(async () => {
      await user.click(trigger);
    });
    await act(async () => {
      await user.keyboard("{Escape}");
    });
    expect(trigger).toHaveFocus();
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByRole("menu")).toHaveClass("animate-fade-out");

    await act(async () => {
      await user.click(trigger);
    });
    fireEvent.mouseDown(screen.getByRole("button", { name: "Outside" }));
    expect(trigger).toHaveAttribute("aria-expanded", "false");
  });

  it("honors a trigger click handler that prevents the menu toggle", async () => {
    const user = userEvent.setup();
    render(
      <DropdownMenu
        trigger={
          <button
            type="button"
            onClick={(event) => {
              event.preventDefault();
            }}
          >
            Blocked
          </button>
        }
      >
        <DropdownMenuItem>Action</DropdownMenuItem>
      </DropdownMenu>
    );

    await act(async () => {
      await user.click(screen.getByRole("button", { name: "Blocked" }));
    });
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });

  it("renders menu structural helpers", () => {
    render(
      <DropdownMenu trigger={<button type="button">Open</button>}>
        <DropdownMenuSection label="Commands">
          <DropdownMenuDivider />
        </DropdownMenuSection>
      </DropdownMenu>
    );
    fireEvent.click(screen.getByRole("button", { name: "Open" }));
    expect(screen.getByText("Commands")).toBeInTheDocument();
    expect(screen.getByRole("separator")).toBeInTheDocument();
  });
});
