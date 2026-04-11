import { render, screen } from "@testing-library/react";
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
});
