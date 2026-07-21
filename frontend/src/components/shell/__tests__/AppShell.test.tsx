import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import type { ProjectResponse, TagResponse, TaskCounts } from "../../../api/taskTypes";
import { AppShell } from "../AppShell";

const counts: TaskCounts = { inbox: 0, next: 6, waiting: 3, someday: 0 };

const projects: ProjectResponse[] = [
  { id: "project-launch", name: "Launch v2", color: "#0ea5e9", state: "active", revision: 1, open_task_count: 2 },
  { id: "project-onboarding", name: "Onboarding drop-off", color: "#6366f1", state: "active", revision: 1, open_task_count: 1 }
];

const tags: TagResponse[] = [
  { id: "tag-calls", name: "@calls", state: "active", revision: 1, open_task_count: 2 },
  { id: "tag-deep-work", name: "deep-work", state: "active", revision: 1, open_task_count: 1 }
];

function RoutedTaskListContent() {
  const { pathname } = useLocation();

  return <div>{pathname === "/tasks/inbox" ? "Inbox task list content" : "Next task list content"}</div>;
}

function renderShell(overrides: Partial<Parameters<typeof AppShell>[0]> = {}) {
  const handlers = {
    onCreateProject: vi.fn(),
    onRenameProject: vi.fn(),
    onArchiveProject: vi.fn(),
    onCreateTag: vi.fn(),
    onRenameTag: vi.fn(),
    onDeleteTag: vi.fn()
  };
  render(
    <MemoryRouter initialEntries={["/tasks/next"]}>
      <Routes>
        <Route
          path="*"
          element={
            <AppShell counts={counts} projects={projects} tags={tags} activeState="next" {...handlers} {...overrides}>
              <RoutedTaskListContent />
            </AppShell>
          }
        />
      </Routes>
    </MemoryRouter>
  );
  return handlers;
}

describe("AppShell canonical sidebar", () => {
  it("always renders secondary list counts, including zero, and hides the Inbox badge at zero", () => {
    renderShell();
    const sidebar = screen.getByRole("navigation", { name: "Task navigation" });

    const someday = within(sidebar).getByRole("link", { name: /Someday \/ maybe/ });
    expect(within(someday).getByText("0")).toBeInTheDocument();
    const next = within(sidebar).getByRole("link", { name: /Next actions/ });
    expect(within(next).getByText("6")).toBeInTheDocument();
    const inbox = within(sidebar).getByRole("link", { name: "Inbox" });
    expect(within(inbox).queryByText("0")).not.toBeInTheDocument();
  });

  it("returns to the Inbox route after Weekly review without retaining the in-shell placeholder", async () => {
    const user = userEvent.setup();
    renderShell();

    expect(screen.getByRole("button", { name: "Think with CRT — Coming soon" })).toBeDisabled();
    expect(screen.getByText("Next task list content")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Weekly review" }));
    expect(screen.getByRole("region", { name: "Weekly review placeholder" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Weekly review — coming soon" })).toBeInTheDocument();
    expect(screen.queryByText("Next task list content")).not.toBeInTheDocument();

    await user.click(screen.getByRole("link", { name: "Inbox" }));
    expect(await screen.findByText("Inbox task list content")).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Weekly review placeholder" })).not.toBeInTheDocument();
  });

  it("exits Weekly review when the same-route Next actions link is reselected via the mobile drawer", async () => {
    const user = userEvent.setup();
    renderShell();
    const trigger = screen.getByRole("button", { name: "Open task navigation" });

    await user.click(trigger);
    let drawer = screen.getByRole("dialog", { name: "Task navigation" });
    await user.click(within(drawer).getByRole("button", { name: "Weekly review" }));
    expect(screen.queryByRole("dialog", { name: "Task navigation" })).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
    expect(screen.getByRole("region", { name: "Weekly review placeholder" })).toBeInTheDocument();
    expect(screen.queryByText("Next task list content")).not.toBeInTheDocument();

    await user.click(trigger);
    drawer = screen.getByRole("dialog", { name: "Task navigation" });
    await user.click(within(drawer).getByRole("link", { name: /Next actions/ }));

    expect(screen.queryByRole("dialog", { name: "Task navigation" })).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
    expect(screen.queryByRole("region", { name: "Weekly review placeholder" })).not.toBeInTheDocument();
    expect(screen.getByText("Next task list content")).toBeInTheDocument();
  });

  it("drives project create, rename and archive through the popover menus", async () => {
    const user = userEvent.setup();
    const handlers = renderShell();

    await user.click(screen.getByRole("button", { name: "New project" }));
    await user.type(screen.getByLabelText("New project name"), "Client work{Enter}");
    expect(handlers.onCreateProject).toHaveBeenCalledWith("Client work");

    await user.click(screen.getByRole("button", { name: "Project options Launch v2" }));
    await user.clear(screen.getByLabelText("Project name Launch v2"));
    await user.type(screen.getByLabelText("Project name Launch v2"), "Launch v3{Enter}");
    expect(handlers.onRenameProject).toHaveBeenCalledWith(projects[0], "Launch v3");
    expect(screen.queryByRole("dialog", { name: "Edit project Launch v2" })).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Project options Onboarding drop-off" }));
    await user.click(screen.getByRole("button", { name: "Archive" }));
    expect(handlers.onArchiveProject).toHaveBeenCalledWith(projects[1]);
  });

  it("drives tag create, rename and delete through the popover menus and keeps @/# naming", async () => {
    const user = userEvent.setup();
    const handlers = renderShell();

    expect(screen.getByRole("link", { name: "@calls" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "#deep-work" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "New tag" }));
    await user.type(screen.getByLabelText("New tag name"), "errands{Enter}");
    expect(handlers.onCreateTag).toHaveBeenCalledWith("errands");

    await user.click(screen.getByRole("button", { name: "Tag options deep-work" }));
    await user.clear(screen.getByLabelText("Tag name deep-work"));
    await user.type(screen.getByLabelText("Tag name deep-work"), "focus{Enter}");
    expect(handlers.onRenameTag).toHaveBeenCalledWith(tags[1], "focus");

    await user.click(screen.getByRole("button", { name: "Tag options @calls" }));
    await user.click(screen.getByRole("button", { name: "Delete" }));
    expect(handlers.onDeleteTag).toHaveBeenCalledWith(tags[0]);
  });

  it("keeps the mobile drawer CRUD usable and closes it on Escape and on navigation", async () => {
    const user = userEvent.setup();
    renderShell();

    await user.click(screen.getByRole("button", { name: "Open task navigation" }));
    const drawer = screen.getByRole("dialog", { name: "Task navigation" });

    await user.click(within(drawer).getByRole("button", { name: "New project" }));
    expect(within(drawer).getByLabelText("New project name")).toBeInTheDocument();
    expect(screen.getByRole("dialog", { name: "Task navigation" })).toBeInTheDocument();

    await user.keyboard("{Escape}");
    expect(within(drawer).queryByLabelText("New project name")).not.toBeInTheDocument();
    expect(screen.getByRole("dialog", { name: "Task navigation" })).toBeInTheDocument();

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog", { name: "Task navigation" })).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Open task navigation" }));
    const reopened = screen.getByRole("dialog", { name: "Task navigation" });
    await user.click(within(reopened).getByRole("link", { name: "Overdue" }));
    expect(screen.queryByRole("dialog", { name: "Task navigation" })).not.toBeInTheDocument();
  });

  it("restores focus to the Open task navigation trigger after Escape, overlay click, and explicit close", async () => {
    const user = userEvent.setup();
    renderShell();
    const trigger = screen.getByRole("button", { name: "Open task navigation" });

    await user.click(trigger);
    let drawer = screen.getByRole("dialog", { name: "Task navigation" });
    const [, explicitCloseButton] = within(drawer).getAllByRole("button", { name: "Close task navigation" });
    expect(explicitCloseButton).toHaveFocus();

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog", { name: "Task navigation" })).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();

    await user.click(trigger);
    drawer = screen.getByRole("dialog", { name: "Task navigation" });
    const [overlayCloseButton] = within(drawer).getAllByRole("button", { name: "Close task navigation" });
    await user.click(overlayCloseButton);
    expect(screen.queryByRole("dialog", { name: "Task navigation" })).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();

    await user.click(trigger);
    drawer = screen.getByRole("dialog", { name: "Task navigation" });
    const [, reopenedExplicitCloseButton] = within(drawer).getAllByRole("button", { name: "Close task navigation" });
    await user.click(reopenedExplicitCloseButton);
    expect(screen.queryByRole("dialog", { name: "Task navigation" })).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });

  it("restores focus to the Open task navigation trigger when the drawer closes via a navigation link or Weekly Review, not just Escape/overlay/explicit close", async () => {
    const user = userEvent.setup();
    renderShell();
    const trigger = screen.getByRole("button", { name: "Open task navigation" });

    await user.click(trigger);
    let drawer = screen.getByRole("dialog", { name: "Task navigation" });
    await user.click(within(drawer).getByRole("link", { name: "Overdue" }));
    expect(screen.queryByRole("dialog", { name: "Task navigation" })).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();

    await user.click(trigger);
    drawer = screen.getByRole("dialog", { name: "Task navigation" });
    await user.click(within(drawer).getByRole("button", { name: "Weekly review" }));
    expect(screen.queryByRole("dialog", { name: "Task navigation" })).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });

  it("traps Tab and Shift+Tab focus inside the actual drawer panel instead of escaping to the overlay or controls behind it", async () => {
    const user = userEvent.setup();
    renderShell();

    await user.click(screen.getByRole("button", { name: "Open task navigation" }));
    const drawer = screen.getByRole("dialog", { name: "Task navigation" });
    const panel = within(drawer).getByTestId("task-navigation-panel");
    const [overlayCloseButton, explicitCloseButton] = within(drawer).getAllByRole("button", { name: "Close task navigation" });
    expect(explicitCloseButton).toHaveFocus();

    await user.tab({ shift: true });
    expect(panel.contains(document.activeElement)).toBe(true);
    expect(document.activeElement).not.toBe(overlayCloseButton);
    expect(document.activeElement).not.toBe(explicitCloseButton);
    const lastFocusable = document.activeElement;

    await user.tab();
    expect(document.activeElement).toBe(explicitCloseButton);

    await user.tab({ shift: true });
    expect(document.activeElement).toBe(lastFocusable);
  });
});
