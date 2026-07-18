import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SidePanel } from "../SidePanel";

describe("SidePanel", () => {
  it("renders its title, toolbar, content, and footer landmarks", () => {
    render(
      <SidePanel title="Details" toolbar={<button type="button">Refresh</button>} footer="Saved just now">
        <p>Node content</p>
      </SidePanel>
    );

    expect(screen.getByRole("heading", { name: "Details" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Refresh" })).toBeInTheDocument();
    expect(screen.getByText("Node content")).toBeInTheDocument();
    expect(screen.getByText("Saved just now")).toBeInTheDocument();
  });

  it("renders a title without a toolbar", () => {
    render(
      <SidePanel title="Details">
        <p>Only content</p>
      </SidePanel>
    );

    expect(screen.getByRole("heading", { name: "Details" })).toBeInTheDocument();
    expect(screen.getByText("Only content")).toBeInTheDocument();
  });

  it("renders a toolbar without a title", () => {
    render(
      <SidePanel toolbar={<button type="button">Refresh</button>}>
        <p>Only content</p>
      </SidePanel>
    );

    expect(screen.getByRole("button", { name: "Refresh" })).toBeInTheDocument();
    expect(screen.queryByRole("heading")).not.toBeInTheDocument();
  });

  it("keeps content available when optional chrome is omitted", () => {
    render(
      <SidePanel>
        <p>Only content</p>
      </SidePanel>
    );

    expect(screen.getByText("Only content")).toBeInTheDocument();
    expect(screen.queryByRole("heading")).not.toBeInTheDocument();
  });
});
