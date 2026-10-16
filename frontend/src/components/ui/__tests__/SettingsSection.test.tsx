import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { Feedback, Field, SectionCard, SettingRow, SettingsTabs } from "../SettingsSection";

describe("SettingsSection", () => {
  it("lays a labelled field out in the label column of a row", () => {
    render(<Field row label="Name" name="name" type="text" value="Max" onChange={() => undefined} hint="Shown in the app" />);
    expect(screen.getByLabelText("Name")).toHaveValue("Max");
    expect(screen.getByLabelText("Name")).toHaveAccessibleDescription("Shown in the app");
  });

  it("keeps a stacked field's label tied to its input", () => {
    render(<Field label="Email" name="email" type="email" value="" onChange={() => undefined} />);
    expect(screen.getByLabelText("Email")).toHaveClass("bg-card");
  });

  it("renders a row with a plain label, or with no label at all", () => {
    render(
      <>
        <SettingRow label="Password" action={<button type="button">Change</button>}>Set</SettingRow>
        <SettingRow>Only a value</SettingRow>
      </>
    );
    expect(screen.getByText("Password")).toHaveClass("text-ink-muted");
    expect(screen.getByText("Only a value")).toBeInTheDocument();
  });

  it("keeps the heading of a flat section for assistive technology", () => {
    render(
      <>
        <SectionCard flat title="One" description="First group">x</SectionCard>
        <SectionCard flat title="Two" description="Second group">y</SectionCard>
        <SectionCard tone="danger" title="Danger" description="Careful">z</SectionCard>
      </>
    );
    expect(screen.getByRole("heading", { name: "Two" })).toHaveClass("sr-only");
    expect(screen.getByRole("heading", { name: "Danger" })).toHaveClass("text-danger");
  });

  it("marks the current settings tab", () => {
    render(
      <MemoryRouter initialEntries={["/settings/account"]}>
        <SettingsTabs />
      </MemoryRouter>
    );
    expect(screen.getByRole("link", { name: "Account" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "Agents" })).toHaveAttribute("href", "/settings/agents");
  });

  it("shows errors and successes as quiet cards", () => {
    const { rerender } = render(<Feedback error="Nope" success={null} />);
    expect(screen.getByRole("alert")).toHaveClass("text-danger");
    rerender(<Feedback error={null} success="Saved" />);
    expect(screen.getByRole("status")).toHaveClass("bg-quiet");
    rerender(<Feedback error={null} success={null} />);
    expect(screen.queryByRole("status")).toBeNull();
  });
});
