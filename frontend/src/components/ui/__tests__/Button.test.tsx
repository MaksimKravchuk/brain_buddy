import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createRef } from "react";
import { describe, expect, it, vi } from "vitest";

import { Button } from "../Button";

describe("Button", () => {
  it("renders its children", () => {
    render(<Button>Click me</Button>);
    expect(screen.getByRole("button", { name: "Click me" })).toBeInTheDocument();
  });

  it("applies the primary variant by default", () => {
    render(<Button>Primary</Button>);
    const button = screen.getByRole("button", { name: "Primary" });
    expect(button.className).toContain("bg-brand-primary");
  });

  it("applies the danger variant when requested", () => {
    render(<Button variant="danger">Delete</Button>);
    const button = screen.getByRole("button", { name: "Delete" });
    expect(button.className).toContain("bg-rose-50");
  });

  it("disables click handling when isLoading is true", async () => {
    const onClick = vi.fn();
    render(
      <Button isLoading onClick={onClick}>
        Saving
      </Button>
    );
    const button = screen.getByRole("button", { name: /saving/i });
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute("data-loading", "true");
  });

  it("renders the left icon slot when provided and not loading", () => {
    render(
      <Button leftIcon={<svg data-testid="left-icon" />}>With icon</Button>
    );
    expect(screen.getByTestId("left-icon")).toBeInTheDocument();
  });

  it("hides the left icon when loading and shows the spinner instead", () => {
    render(
      <Button leftIcon={<svg data-testid="left-icon" />} isLoading>
        Loading
      </Button>
    );
    expect(screen.queryByTestId("left-icon")).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toBeInTheDocument();
  });

  it("is disabled when the disabled prop is true", () => {
    render(<Button disabled>Disabled</Button>);
    expect(screen.getByRole("button", { name: "Disabled" })).toBeDisabled();
  });

  it("calls onClick when enabled", async () => {
    const onClick = vi.fn();
    render(<Button onClick={onClick}>Go</Button>);
    await userEvent.click(screen.getByRole("button", { name: "Go" }));
    expect(onClick).toHaveBeenCalledOnce();
  });

  it("defaults to type='button' (never accidentally submits forms)", () => {
    render(<Button>Default type</Button>);
    expect(screen.getByRole("button")).toHaveAttribute("type", "button");
  });

  it("renders the right icon when provided and not loading", () => {
    render(<Button rightIcon={<svg data-testid="right-icon" />}>Next</Button>);
    expect(screen.getByTestId("right-icon")).toBeInTheDocument();
  });

  it("hides the right icon while loading", () => {
    render(
      <Button rightIcon={<svg data-testid="right-icon" />} isLoading>
        Next
      </Button>
    );
    expect(screen.queryByTestId("right-icon")).not.toBeInTheDocument();
  });

  it("forwards refs to the underlying button element", () => {
    const ref = createRef<HTMLButtonElement>();
    render(<Button ref={ref}>Ref</Button>);
    expect(ref.current).toBeInstanceOf(HTMLButtonElement);
  });

  it("applies icon variant sizing", () => {
    render(
      <Button variant="icon" aria-label="Close">
        <svg />
      </Button>
    );
    const button = screen.getByRole("button", { name: "Close" });
    expect(button.className).toMatch(/h-\d|w-\d/);
  });

  it("renders an icon-only button without an empty label slot", () => {
    render(<Button aria-label="Refresh" leftIcon={<svg data-testid="only-icon" />} />);

    const button = screen.getByRole("button", { name: "Refresh" });
    expect(screen.getByTestId("only-icon")).toBeInTheDocument();
    expect(button.querySelectorAll("span")).toHaveLength(1);
  });
});
