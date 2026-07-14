import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { MutableRefObject } from "react";

import {
  DropdownMenu,
  DropdownMenuItem
} from "../DropdownMenu";

describe("DropdownMenu ref forwarding and navigation edge cases", () => {
  it("forwards an object ref to the trigger element", async () => {
    const refObject: MutableRefObject<HTMLElement | null> = { current: null };
    const user = userEvent.setup();
    render(
      <DropdownMenu trigger={<button type="button" ref={refObject}>Open</button>}>
        <DropdownMenuItem>Action</DropdownMenuItem>
      </DropdownMenu>
    );

    await act(async () => {
      await user.click(screen.getByRole("button", { name: "Open" }));
    });
    expect(refObject.current).toBeInstanceOf(HTMLButtonElement);
  });

  it("ignores navigation keys that are not Arrow/Home/End", async () => {
    const user = userEvent.setup();
    render(
      <DropdownMenu trigger={<button type="button">Actions</button>}>
        <DropdownMenuItem>First</DropdownMenuItem>
      </DropdownMenu>
    );

    await act(async () => {
      await user.click(screen.getByRole("button", { name: "Actions" }));
    });
    await act(async () => {
      await user.keyboard("{a}");
    });
    expect(screen.getByRole("menuitem", { name: "First" })).toHaveFocus();
  });

  it("wraps navigation from the last item back to the first with ArrowDown", async () => {
    const user = userEvent.setup();
    render(
      <DropdownMenu trigger={<button type="button">Actions</button>}>
        <DropdownMenuItem>First</DropdownMenuItem>
        <DropdownMenuItem>Second</DropdownMenuItem>
      </DropdownMenu>
    );

    await act(async () => {
      await user.click(screen.getByRole("button", { name: "Actions" }));
    });
    await act(async () => {
      await user.keyboard("{End}");
    });
    expect(screen.getByRole("menuitem", { name: "Second" })).toHaveFocus();
    await act(async () => {
      await user.keyboard("{ArrowDown}");
    });
    expect(screen.getByRole("menuitem", { name: "First" })).toHaveFocus();
  });
});
