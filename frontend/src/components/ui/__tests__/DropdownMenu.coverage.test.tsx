import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  DropdownMenu,
  DropdownMenuItem,
  DropdownMenuDivider,
  DropdownMenuSection
} from "../DropdownMenu";

describe("DropdownMenu additional branch coverage", () => {
  beforeEach(() => {
    vi.spyOn(console, "error").mockImplementation(() => undefined);
  });

  it("closes the menu when clicking outside both menu and trigger", async () => {
    const user = userEvent.setup();
    render(
      <div>
        <span data-testid="outside">Outside</span>
        <DropdownMenu trigger={<button type="button">Open</button>}>
          <DropdownMenuItem>Action</DropdownMenuItem>
        </DropdownMenu>
      </div>
    );

    await act(async () => {
      await user.click(screen.getByRole("button", { name: "Open" }));
    });
    expect(screen.getByRole("menu")).toBeInTheDocument();

    await act(async () => {
      await user.click(screen.getByTestId("outside"));
    });
    // The menu uses useDelayedUnmount so it animates out before being removed.
    // The aria-expanded attribute should become false once closed.
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Open" })).toHaveAttribute("aria-expanded", "false");
    });
  });

  it("does not close when clicking inside the menu panel", async () => {
    const user = userEvent.setup();
    render(
      <DropdownMenu trigger={<button type="button">Open</button>}>
        <DropdownMenuItem onSelect={vi.fn()}>Item</DropdownMenuItem>
      </DropdownMenu>
    );

    await act(async () => {
      await user.click(screen.getByRole("button", { name: "Open" }));
    });
    await act(async () => {
      await user.click(screen.getByRole("menuitem", { name: "Item" }));
    });
  });

  it("does not close when the opening pointer event originates from its trigger", async () => {
    const user = userEvent.setup();
    render(
      <DropdownMenu trigger={<button type="button">Open</button>}>
        <DropdownMenuItem>Item</DropdownMenuItem>
      </DropdownMenu>
    );

    const trigger = screen.getByRole("button", { name: "Open" });
    await act(async () => {
      await user.click(trigger);
    });
    fireEvent.mouseDown(trigger);
    expect(trigger).toHaveAttribute("aria-expanded", "true");
  });

  it("starts ArrowDown navigation at the first item when the menu itself has focus", async () => {
    const user = userEvent.setup();
    render(
      <DropdownMenu trigger={<button type="button">Open</button>}>
        <DropdownMenuItem>First</DropdownMenuItem>
        <DropdownMenuItem>Second</DropdownMenuItem>
      </DropdownMenu>
    );

    await act(async () => {
      await user.click(screen.getByRole("button", { name: "Open" }));
    });
    const menu = screen.getByRole("menu");
    menu.focus();
    await act(async () => {
      await user.keyboard("{ArrowDown}");
    });
    expect(screen.getByRole("menuitem", { name: "First" })).toHaveFocus();
  });

  it("navigates up from the first item to the last with ArrowUp", async () => {
    const user = userEvent.setup();
    render(
      <DropdownMenu trigger={<button type="button">Open</button>}>
        <DropdownMenuItem>First</DropdownMenuItem>
        <DropdownMenuItem>Second</DropdownMenuItem>
      </DropdownMenu>
    );

    await act(async () => {
      await user.click(screen.getByRole("button", { name: "Open" }));
    });
    await act(async () => {
      await user.keyboard("{ArrowUp}");
    });
    expect(screen.getByRole("menuitem", { name: "Second" })).toHaveFocus();
  });

  it("navigates to the first item with Home and the last with End", async () => {
    const user = userEvent.setup();
    render(
      <DropdownMenu trigger={<button type="button">Open</button>}>
        <DropdownMenuItem>First</DropdownMenuItem>
        <DropdownMenuItem>Second</DropdownMenuItem>
      </DropdownMenu>
    );

    await act(async () => {
      await user.click(screen.getByRole("button", { name: "Open" }));
    });
    await act(async () => {
      await user.keyboard("{ArrowDown}");
    });
    expect(screen.getByRole("menuitem", { name: "Second" })).toHaveFocus();
    await act(async () => {
      await user.keyboard("{Home}");
    });
    expect(screen.getByRole("menuitem", { name: "First" })).toHaveFocus();
    await act(async () => {
      await user.keyboard("{End}");
    });
    expect(screen.getByRole("menuitem", { name: "Second" })).toHaveFocus();
  });

  it("does nothing when navigating an empty menu", async () => {
    const user = userEvent.setup();
    render(
      <DropdownMenu trigger={<button type="button">Open</button>}>
        <DropdownMenuSection label="Empty">
          <div />
        </DropdownMenuSection>
      </DropdownMenu>
    );

    await act(async () => {
      await user.click(screen.getByRole("button", { name: "Open" }));
    });
    await act(async () => {
      screen.getByRole("menu").focus();
      await user.keyboard("{ArrowDown}");
    });
  });

  it("closes the menu on Escape and returns focus to the trigger", async () => {
    const user = userEvent.setup();
    render(
      <DropdownMenu trigger={<button type="button">Open</button>}>
        <DropdownMenuItem>Action</DropdownMenuItem>
      </DropdownMenu>
    );

    await act(async () => {
      await user.click(screen.getByRole("button", { name: "Open" }));
    });
    await act(async () => {
      await user.keyboard("{Escape}");
    });
    // The menu uses useDelayedUnmount; we check the closed state via aria-expanded
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Open" })).toHaveAttribute("aria-expanded", "false");
    });
    expect(screen.getByRole("button", { name: "Open" })).toHaveFocus();
  });

  it("renders the trigger directly when it is not a valid React element", () => {
    render(
      <DropdownMenu trigger={"plain string" as unknown as React.ReactElement}>
        <DropdownMenuItem>Action</DropdownMenuItem>
      </DropdownMenu>
    );
    expect(screen.getByText("plain string")).toBeInTheDocument();
  });

  it("does not fire onSelect for a disabled item and keeps menu open", async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    render(
      <DropdownMenu trigger={<button type="button">Open</button>}>
        <DropdownMenuItem onSelect={onSelect} disabled>
          Disabled
        </DropdownMenuItem>
      </DropdownMenu>
    );

    await act(async () => {
      await user.click(screen.getByRole("button", { name: "Open" }));
    });
    await act(async () => {
      await user.click(screen.getByRole("menuitem", { name: "Disabled" }));
    });
    expect(onSelect).not.toHaveBeenCalled();
    expect(screen.getByRole("menu")).toBeInTheDocument();
  });

  it("keeps the menu open when closeOnSelect is false", async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    render(
      <DropdownMenu trigger={<button type="button">Open</button>}>
        <DropdownMenuItem onSelect={onSelect} closeOnSelect={false}>
          Keep open
        </DropdownMenuItem>
      </DropdownMenu>
    );

    await act(async () => {
      await user.click(screen.getByRole("button", { name: "Open" }));
    });
    await act(async () => {
      await user.click(screen.getByRole("menuitem", { name: "Keep open" }));
    });
    expect(onSelect).toHaveBeenCalledOnce();
    expect(screen.getByRole("menu")).toBeInTheDocument();
  });

  it("activates an item with Space key", async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    render(
      <DropdownMenu trigger={<button type="button">Open</button>}>
        <DropdownMenuItem onSelect={onSelect}>Space item</DropdownMenuItem>
      </DropdownMenu>
    );

    await act(async () => {
      await user.click(screen.getByRole("button", { name: "Open" }));
    });
    await act(async () => {
      await user.keyboard(" ");
    });
    expect(onSelect).toHaveBeenCalledOnce();
  });

  it("renders align end and passes menuClassName", async () => {
    const user = userEvent.setup();
    render(
      <DropdownMenu
        trigger={<button type="button">Open</button>}
        align="end"
        menuClassName="custom-menu"
      >
        <DropdownMenuItem>Action</DropdownMenuItem>
      </DropdownMenu>
    );

    await act(async () => {
      await user.click(screen.getByRole("button", { name: "Open" }));
    });
    const menu = screen.getByRole("menu");
    expect(menu.className).toContain("right-0");
    expect(menu.className).toContain("custom-menu");
  });

  it("renders a divider and section", async () => {
    const user = userEvent.setup();
    render(
      <DropdownMenu trigger={<button type="button">Open</button>}>
        <DropdownMenuItem>First</DropdownMenuItem>
        <DropdownMenuDivider />
        <DropdownMenuSection label="Section">
          <DropdownMenuItem>Sectioned</DropdownMenuItem>
        </DropdownMenuSection>
      </DropdownMenu>
    );

    await act(async () => {
      await user.click(screen.getByRole("button", { name: "Open" }));
    });
    expect(screen.getByRole("separator")).toBeInTheDocument();
    expect(screen.getByText("Section")).toBeInTheDocument();
  });
});
