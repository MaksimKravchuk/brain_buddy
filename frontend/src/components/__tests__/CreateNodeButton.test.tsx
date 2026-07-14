import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { CreateNodeButton } from "../CreateNodeButton";

describe("CreateNodeButton branches", () => {
  it("uses Parent as the default label for parent nodes and resets the input", async () => {
    const onCreate = vi.fn();
    const user = userEvent.setup();
    render(<CreateNodeButton onCreate={onCreate} />);

    await act(async () => {
      await user.click(screen.getByRole("button", { name: "Parent" }));
    });
    await act(async () => {
      await user.click(screen.getByRole("button", { name: "Add" }));
    });

    expect(onCreate).toHaveBeenCalledWith({ type: "parent", label: "Parent" });
    expect(screen.getByPlaceholderText("Node label")).toHaveValue("");
  });

  it("uses Child as the default label when the input is empty and type is child", async () => {
    const onCreate = vi.fn();
    const user = userEvent.setup();
    render(<CreateNodeButton onCreate={onCreate} />);

    await act(async () => {
      await user.click(screen.getByRole("button", { name: "Add" }));
    });
    expect(onCreate).toHaveBeenCalledWith({ type: "child", label: "Child" });
  });

  it("prevents submission while disabled", async () => {
    const onCreate = vi.fn();
    const user = userEvent.setup();
    render(<CreateNodeButton onCreate={onCreate} disabled />);

    await user.click(screen.getByRole("button", { name: "Add" }));
    expect(onCreate).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Add" })).toBeDisabled();
  });
});
