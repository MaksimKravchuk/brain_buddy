import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "../../../api/client";
import { reviewApi, type ReviewState } from "../../../api/review";
import { markWhileAwayShown, readWhileAwayLastShown, localDay } from "../../../features/review/wywaPresentation";
import type { ProjectResponse, TagResponse, TaskCounts } from "../../../api/taskTypes";
import { useAuthStore } from "../../../stores/authStore";
import { AppShell } from "../AppShell";
import { useShellToast } from "../shellToast";

vi.mock("../../../api/review", async () => {
  const actual = await vi.importActual<typeof import("../../../api/review")>("../../../api/review");
  return {
    ...actual,
    reviewApi: { ...actual.reviewApi, getState: vi.fn(), acknowledgeExplainer: vi.fn(), acknowledgeParks: vi.fn(), updateSettings: vi.fn() }
  };
});

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
  const { pathname, search, state } = useLocation();
  const navigate = useNavigate();
  const notify = useShellToast();

  return (
    <div>
      <div>{pathname === "/tasks/inbox" ? "Inbox task list content" : "Next task list content"}</div>
      <span className="sr-only" data-testid="pathname">{pathname}</span>
      <div data-testid="location">{`${pathname}${search}`}</div>
      <div data-testid="location-state">{state ? JSON.stringify(state) : "none"}</div>
      <button type="button" onClick={() => navigate(-1)}>Previous test view</button>
      <button type="button" onClick={() => navigate(1)}>Next test view</button>
      <button type="button" onClick={() => notify("Thinking canvas isn't built yet — placeholder")}>
        Raise shell toast
      </button>
      <button
        type="button"
        onClick={() => {
          dismissUndo = notify("“Renovate the bathroom” released to Someday", {
            action: { label: "Undo", accessibleLabel: "Undo: Released to Someday Renovate the bathroom", onAction: undoSpy }
          });
        }}
      >
        Raise undo toast
      </button>
      <button type="button" onClick={() => dismissUndo()}>
        Take the undo toast away
      </button>
      <label>
        Scratch field
        <input />
      </label>
    </div>
  );
}

const undoSpy = vi.fn();
let dismissUndo: () => void = () => undefined;

function renderShell(
  overrides: Partial<Parameters<typeof AppShell>[0]> = {},
  initialEntries: string[] = ["/tasks/next"]
) {
  const handlers = {
    onCreateProject: vi.fn(),
    onRenameProject: vi.fn(),
    onArchiveProject: vi.fn(),
    onCreateTag: vi.fn(),
    onRenameTag: vi.fn(),
    onDeleteTag: vi.fn()
  };
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={initialEntries}>
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
    </QueryClientProvider>
  );
  return handlers;
}

const currentLocation = () => screen.getByTestId("location").textContent;

beforeEach(() => {
  act(() => {
    useAuthStore.setState({
      user: { id: "user-1", email: "max@example.test" },
      status: "authed",
      deletionCancelledNotice: false
    });
  });
});

afterEach(() => {
  act(() => {
    useAuthStore.setState({ user: null, status: "loading", deletionCancelledNotice: false });
  });
  vi.restoreAllMocks();
});

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

  it("applies the canonical brand easing to nav row hover/active transitions", () => {
    renderShell();
    const sidebar = screen.getByRole("navigation", { name: "Task navigation" });
    const next = within(sidebar).getByRole("link", { name: /Next actions/ });
    expect(next).toHaveClass("transition-colors", "duration-200", "ease-smooth");
  });

  it("keeps the mobile header labels from wrapping inside the fixed-height chrome", () => {
    renderShell();

    expect(screen.getByRole("link", { name: "BrainBuddy" })).toHaveClass("shrink-0", "whitespace-nowrap");
    expect(screen.getByRole("button", { name: "Brain dump" })).toHaveClass("shrink-0", "whitespace-nowrap", "px-3", "sm:px-4");
  });

  it("renders Weekly review and Thinking Mode as matching disabled Soon affordances", () => {
    renderShell();

    const weeklyReview = screen.getByRole("button", { name: "Weekly review — Coming soon" });
    const thinkingMode = screen.getByRole("button", { name: "Thinking Mode — Coming soon" });
    expect(weeklyReview).toBeDisabled();
    expect(weeklyReview).toHaveClass("cursor-not-allowed", "text-slate-400");
    expect(thinkingMode).toBeDisabled();
    expect(thinkingMode).toHaveClass("cursor-not-allowed", "text-slate-400");
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

  it("reaches connected agents from the account menu", async () => {
    const user = userEvent.setup();
    renderShell();

    await user.click(screen.getByRole("button", { name: /Account menu/ }));
    const menu = screen.getByRole("menu", { name: "Account" });
    await user.click(within(menu).getByRole("menuitem", { name: "Connected agents" }));

    expect(screen.getByTestId("pathname")).toHaveTextContent("/settings/agents");
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

  it("closes each popover when its own trigger is pressed a second time", async () => {
    const user = userEvent.setup();
    renderShell();

    const newProject = screen.getByRole("button", { name: "New project" });
    await user.click(newProject);
    expect(screen.getByRole("dialog", { name: "Create project" })).toBeInTheDocument();
    await user.click(newProject);
    expect(screen.queryByRole("dialog", { name: "Create project" })).not.toBeInTheDocument();

    const newTag = screen.getByRole("button", { name: "New tag" });
    await user.click(newTag);
    expect(screen.getByRole("dialog", { name: "Create tag" })).toBeInTheDocument();
    await user.click(newTag);
    expect(screen.queryByRole("dialog", { name: "Create tag" })).not.toBeInTheDocument();

    const projectOptions = screen.getByRole("button", { name: "Project options Launch v2" });
    await user.click(projectOptions);
    expect(screen.getByRole("dialog", { name: "Edit project Launch v2" })).toBeInTheDocument();
    await user.click(projectOptions);
    expect(screen.queryByRole("dialog", { name: "Edit project Launch v2" })).not.toBeInTheDocument();

    const tagOptions = screen.getByRole("button", { name: "Tag options deep-work" });
    await user.click(tagOptions);
    expect(screen.getByRole("dialog", { name: "Edit tag deep-work" })).toBeInTheDocument();
    await user.click(tagOptions);
    expect(screen.queryByRole("dialog", { name: "Edit tag deep-work" })).not.toBeInTheDocument();
  });

  it("refuses to submit a blank or unchanged name, so no needless write reaches the server", async () => {
    const user = userEvent.setup();
    const handlers = renderShell();

    await user.click(screen.getByRole("button", { name: "New project" }));
    const projectName = screen.getByLabelText("New project name");
    await user.type(projectName, "   ");
    expect(screen.getByRole("button", { name: "Add" })).toBeDisabled();
    await user.type(projectName, "{Enter}");
    expect(handlers.onCreateProject).not.toHaveBeenCalled();
    // Enter never submits while Add is disabled; a forced submit still refuses the blank name.
    fireEvent.submit(projectName.closest("form") as HTMLFormElement);
    expect(handlers.onCreateProject).not.toHaveBeenCalled();
    await user.keyboard("{Escape}");

    await user.click(screen.getByRole("button", { name: "New tag" }));
    const tagName = screen.getByLabelText("New tag name");
    await user.type(tagName, "  {Enter}");
    expect(handlers.onCreateTag).not.toHaveBeenCalled();
    fireEvent.submit(tagName.closest("form") as HTMLFormElement);
    expect(handlers.onCreateTag).not.toHaveBeenCalled();
    await user.keyboard("{Escape}");

    await user.click(screen.getByRole("button", { name: "Project options Launch v2" }));
    await user.type(screen.getByLabelText("Project name Launch v2"), "{Enter}");
    expect(handlers.onRenameProject).not.toHaveBeenCalled();
    expect(screen.queryByRole("dialog", { name: "Edit project Launch v2" })).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Tag options deep-work" }));
    await user.type(screen.getByLabelText("Tag name deep-work"), "{Enter}");
    expect(handlers.onRenameTag).not.toHaveBeenCalled();
    expect(screen.queryByRole("dialog", { name: "Edit tag deep-work" })).not.toBeInTheDocument();
  });

  it("falls back to a palette colour for a project the server left uncoloured", () => {
    renderShell({
      projects: [{ id: "project-plain", name: "Uncoloured", color: null, state: "active", revision: 1, open_task_count: 0 }]
    });

    const swatch = screen.getByRole("link", { name: "Uncoloured" }).querySelector("span[aria-hidden]");
    expect(swatch).toHaveStyle({ backgroundColor: "#0ea5e9" });
  });

  it("offers no editing affordances when the host supplies no mutation handlers", () => {
    renderShell({
      onCreateProject: undefined,
      onRenameProject: undefined,
      onArchiveProject: undefined,
      onCreateTag: undefined,
      onRenameTag: undefined,
      onDeleteTag: undefined
    });

    expect(screen.getByRole("link", { name: "Launch v2" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Project options Launch v2" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "New project" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Tag options deep-work" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "New tag" })).not.toBeInTheDocument();
  });

  it("says so plainly when there are no projects and no tags yet", () => {
    renderShell({ projects: [], tags: [] });

    expect(screen.getByText("No active projects yet")).toBeInTheDocument();
    expect(screen.getByText("No tags yet")).toBeInTheDocument();
  });

  it("badges a non-empty inbox and marks the active project and tag as current", () => {
    renderShell({
      counts: { inbox: 17, next: 6, waiting: 3, someday: 0 },
      activeState: undefined,
      activeProjectId: "project-launch",
      activeTagId: "tag-calls"
    });

    const sidebar = screen.getByRole("navigation", { name: "Task navigation" });
    expect(within(within(sidebar).getByRole("link", { name: /Inbox/ })).getByText("17")).toBeInTheDocument();
    expect(within(sidebar).getByRole("link", { name: "Launch v2" })).toHaveClass("bg-white", "shadow-soft");
    expect(within(sidebar).getByRole("link", { name: "Onboarding drop-off" })).not.toHaveClass("bg-white");
    expect(within(sidebar).getByRole("link", { name: "@calls" })).toHaveClass("border-brand-primary");
    expect(within(sidebar).getByRole("link", { name: "#deep-work" })).not.toHaveClass("border-brand-primary");
  });

  it("leaves keys other than Escape alone in the drawer", async () => {
    const user = userEvent.setup();
    renderShell();

    await user.click(screen.getByRole("button", { name: "Open task navigation" }));
    await user.keyboard("a");

    expect(screen.getByRole("dialog", { name: "Task navigation" })).toBeInTheDocument();
  });
});

describe("AppShell top bar", () => {
  it("dismisses mobile navigation when browser history changes the task route, while search typing keeps it open", async () => {
    const user = userEvent.setup();
    renderShell({}, ["/tasks/next/task-1", "/tasks/next"]);
    await user.click(screen.getByRole("button", { name: "Open task navigation" }));
    const drawer = screen.getByRole("dialog", { name: "Task navigation" });
    await user.type(within(drawer).getByRole("searchbox", { name: "Search tasks" }), "draft");
    expect(drawer).toBeInTheDocument();
    // Programmatic history movement models browser Back without clicking the
    // inert task workspace underneath the drawer.
    fireEvent.click(screen.getByRole("button", { name: "Previous test view" }));
    await waitFor(() => expect(currentLocation()).toBe("/tasks/next/task-1"));
    expect(screen.queryByRole("dialog", { name: "Task navigation" })).not.toBeInTheDocument();
  });

  it("synchronizes a focused search with Back and Forward history", async () => {
    const user = userEvent.setup();
    renderShell({}, ["/tasks/next?q=earlier", "/tasks/next?q=latest"]);
    const search = screen.getByRole("searchbox", { name: "Search tasks" });
    await user.type(search, " phrase ");
    expect(search).toHaveValue("latest phrase ");
    expect(currentLocation()).toBe("/tasks/next?q=latest+phrase");

    // Browser history shortcuts preserve the field's focus.
    fireEvent.click(screen.getByRole("button", { name: "Previous test view" }));
    await waitFor(() => expect(search).toHaveValue("earlier"));
    expect(search).toHaveFocus();
    fireEvent.click(screen.getByRole("button", { name: "Next test view" }));
    await waitFor(() => expect(search).toHaveValue("latest phrase"));
    expect(search).toHaveFocus();
  });

  it("searches from the mobile drawer and returns to the filtered list on Enter", async () => {
    const user = userEvent.setup();
    renderShell({}, ["/tasks/next?sort=due&q=drop"]);

    await user.click(screen.getByRole("button", { name: "Open task navigation" }));
    const drawer = screen.getByRole("dialog", { name: "Task navigation" });
    const search = within(drawer).getByRole("searchbox", { name: "Search tasks" });
    expect(search).toHaveValue("drop");
    await user.clear(search);
    await user.type(search, "review homepage{Enter}");

    expect(screen.queryByRole("dialog", { name: "Task navigation" })).not.toBeInTheDocument();
    expect(currentLocation()).toBe("/tasks/next?sort=due&q=review+homepage");
    expect(screen.getByRole("button", { name: "Open task navigation" })).toHaveFocus();
    expect(screen.getByRole("searchbox", { name: "Search tasks" })).toHaveValue("review homepage");
  });

  it("clears a mobile search without dropping other filters", async () => {
    const user = userEvent.setup();
    renderShell({}, ["/tasks/next?sort=due&q=drop"]);

    await user.click(screen.getByRole("button", { name: "Open task navigation" }));
    const drawer = screen.getByRole("dialog", { name: "Task navigation" });
    await user.clear(within(drawer).getByRole("searchbox", { name: "Search tasks" }));
    await user.click(within(drawer).getByRole("button", { name: "Search" }));

    expect(screen.queryByRole("dialog", { name: "Task navigation" })).not.toBeInTheDocument();
    expect(currentLocation()).toBe("/tasks/next?sort=due");
  });

  it("writes the search box into the query string and clears it again when emptied", async () => {
    const user = userEvent.setup();
    renderShell();

    const search = screen.getByRole("searchbox", { name: "Search tasks" });
    await user.type(search, "onboarding");
    await waitFor(() => expect(currentLocation()).toBe("/tasks/next?q=onboarding"));

    await user.clear(search);
    await waitFor(() => expect(currentLocation()).toBe("/tasks/next"));
  });

  it("keeps an existing query in the box and preserves other params while searching", async () => {
    const user = userEvent.setup();
    renderShell({}, ["/tasks/next?q=drop&sort=due"]);

    const search = screen.getByRole("searchbox", { name: "Search tasks" });
    expect(search).toHaveValue("drop");

    await user.clear(search);
    await user.type(search, "x");
    await waitFor(() => expect(currentLocation()).toContain("sort=due"));
    expect(currentLocation()).toContain("q=x");
  });

  it("opens brain dump over the current view by stamping the background location", async () => {
    const user = userEvent.setup();
    renderShell();

    await user.click(screen.getByRole("button", { name: "Brain dump" }));

    expect(currentLocation()).toBe("/brain-dump/new");
    expect(screen.getByTestId("location-state").textContent).toContain("backgroundLocation");
  });

  it("shows a shell toast raised by a child and lets a later one replace it", () => {
    // fireEvent rather than userEvent: the toast's own dismissal timer is what
    // is under test, and driving the pointer through a faked clock only adds a
    // second thing that can hang.
    vi.useFakeTimers();
    try {
      renderShell();

      const trigger = screen.getByRole("button", { name: "Raise shell toast" });
      fireEvent.click(trigger);
      expect(screen.getByRole("status")).toHaveTextContent("Thinking canvas isn't built yet — placeholder");

      // A second toast restarts the timer rather than letting the first one
      // dismiss the replacement early.
      fireEvent.click(trigger);
      act(() => {
        vi.advanceTimersByTime(2599);
      });
      expect(screen.getByRole("status")).toBeInTheDocument();

      act(() => {
        vi.advanceTimersByTime(1);
      });
      expect(screen.queryByRole("status")).not.toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });
});

describe("020-FR-048 AppShell action toast", () => {
  beforeEach(() => {
    undoSpy.mockReset();
  });

  it("020-FR-048 shows Undo about 5 s in a polite status that names the action and its shortcut", () => {
    vi.useFakeTimers();
    try {
      renderShell();
      fireEvent.click(screen.getByRole("button", { name: "Raise undo toast" }));

      const toast = screen.getByRole("status");
      expect(toast).toHaveTextContent("“Renovate the bathroom” released to Someday");
      expect(toast).toHaveAccessibleDescription("Undo: Released to Someday Renovate the bathroom (Ctrl+Z)");
      const undo = within(toast).getByRole("button", { name: "Undo: Released to Someday Renovate the bathroom" });
      expect(undo).toHaveTextContent("Undo");
      expect(undo).toHaveClass("min-h-11", "min-w-11");

      act(() => {
        vi.advanceTimersByTime(4999);
      });
      expect(screen.getByRole("status")).toBeInTheDocument();
      act(() => {
        vi.advanceTimersByTime(1);
      });
      expect(screen.queryByRole("status")).not.toBeInTheDocument();
      expect(undoSpy).not.toHaveBeenCalled();
    } finally {
      vi.useRealTimers();
    }
  });

  it("020-FR-048 runs Undo from the button once and closes the toast", () => {
    renderShell();
    fireEvent.click(screen.getByRole("button", { name: "Raise undo toast" }));

    fireEvent.click(screen.getByRole("button", { name: "Undo: Released to Someday Renovate the bathroom" }));

    expect(undoSpy).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("020-FR-048 pauses the timer while the toast has hover or focus, then lets it finish", () => {
    vi.useFakeTimers();
    try {
      renderShell();
      fireEvent.click(screen.getByRole("button", { name: "Raise undo toast" }));
      const toast = screen.getByRole("status");

      act(() => {
        vi.advanceTimersByTime(3000);
      });
      fireEvent.mouseEnter(toast);
      act(() => {
        vi.advanceTimersByTime(60_000);
      });
      expect(screen.getByRole("status")).toBeInTheDocument();
      fireEvent.mouseLeave(toast);
      act(() => {
        vi.advanceTimersByTime(1000);
      });
      expect(screen.getByRole("status")).toBeInTheDocument();

      // Hover and focus overlap: the toast waits until both have let go.
      const undo = within(toast).getByRole("button");
      fireEvent.mouseEnter(toast);
      act(() => undo.focus());
      fireEvent.mouseLeave(toast);
      act(() => {
        vi.advanceTimersByTime(60_000);
      });
      expect(screen.getByRole("status")).toBeInTheDocument();
      act(() => undo.blur());
      act(() => {
        vi.advanceTimersByTime(999);
      });
      expect(screen.getByRole("status")).toBeInTheDocument();
      act(() => {
        vi.advanceTimersByTime(1);
      });
      expect(screen.queryByRole("status")).not.toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });

  it("020-FR-048 triggers Undo with Ctrl+Z or Cmd+Z outside text fields while the toast is visible", () => {
    renderShell();
    fireEvent.click(screen.getByRole("button", { name: "Raise undo toast" }));

    fireEvent.keyDown(screen.getByLabelText("Scratch field"), { key: "z", ctrlKey: true });
    expect(undoSpy).not.toHaveBeenCalled();
    expect(screen.getByRole("status")).toBeInTheDocument();

    fireEvent.keyDown(document.body, { key: "x", ctrlKey: true });
    expect(undoSpy).not.toHaveBeenCalled();

    fireEvent.keyDown(document.body, { key: "z", metaKey: true });
    expect(undoSpy).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("status")).not.toBeInTheDocument();

    fireEvent.keyDown(document.body, { key: "z", ctrlKey: true });
    expect(undoSpy).toHaveBeenCalledTimes(1);
  });

  it("020-FR-048 triggers Undo with Ctrl+Z on a Russian layout (\"я\" on the Z key), still not inside a text field", () => {
    renderShell();
    fireEvent.click(screen.getByRole("button", { name: "Raise undo toast" }));

    fireEvent.keyDown(screen.getByLabelText("Scratch field"), { key: "я", code: "KeyZ", ctrlKey: true });
    expect(undoSpy).not.toHaveBeenCalled();

    fireEvent.keyDown(document.body, { key: "я", code: "KeyZ", ctrlKey: true });
    expect(undoSpy).toHaveBeenCalledTimes(1);
  });

  it("020-FR-048 lets a plain toast replace an action toast, so a stale Undo cannot fire", () => {
    renderShell();
    fireEvent.click(screen.getByRole("button", { name: "Raise undo toast" }));
    fireEvent.click(screen.getByRole("button", { name: "Raise shell toast" }));

    expect(screen.getByRole("status")).toHaveTextContent("Thinking canvas isn't built yet — placeholder");
    expect(screen.getByRole("status")).not.toHaveAccessibleDescription();
    fireEvent.keyDown(document.body, { key: "z", ctrlKey: true });
    expect(undoSpy).not.toHaveBeenCalled();
  });

  it("020-FR-048 takes an action toast away on request, but never the newer toast that replaced it", () => {
    renderShell();
    fireEvent.click(screen.getByRole("button", { name: "Raise undo toast" }));
    fireEvent.click(screen.getByRole("button", { name: "Take the undo toast away" }));

    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    fireEvent.keyDown(document.body, { key: "z", ctrlKey: true });
    expect(undoSpy).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Take the undo toast away" }));
    expect(screen.queryByRole("status")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Raise undo toast" }));
    fireEvent.click(screen.getByRole("button", { name: "Raise shell toast" }));
    fireEvent.click(screen.getByRole("button", { name: "Take the undo toast away" }));
    expect(screen.getByRole("status")).toHaveTextContent("Thinking canvas isn't built yet — placeholder");
  });
});

describe("AppShell account menu", () => {
  it("navigates to account settings and to the privacy policy from the menu", async () => {
    const user = userEvent.setup();
    renderShell();

    const trigger = screen.getByRole("button", { name: "Account menu for max@example.test" });
    expect(trigger).toHaveTextContent("M");
    expect(trigger).toHaveAttribute("aria-expanded", "false");

    await user.click(trigger);
    expect(trigger).toHaveAttribute("aria-expanded", "true");
    await user.click(screen.getByRole("menuitem", { name: "Account settings" }));
    expect(currentLocation()).toBe("/settings/account");
    expect(screen.queryByRole("menu", { name: "Account" })).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Account menu for max@example.test" }));
    await user.click(screen.getByRole("menuitem", { name: "Privacy policy" }));
    expect(currentLocation()).toBe("/privacy");
  });

  it("signs out and lands on the login route", async () => {
    const user = userEvent.setup();
    const logout = vi.fn(async () => {
      useAuthStore.setState({ user: null, status: "anon" });
      return true;
    });
    act(() => {
      useAuthStore.setState({ logout });
    });
    renderShell();

    await user.click(screen.getByRole("button", { name: "Account menu for max@example.test" }));
    await user.click(screen.getByRole("menuitem", { name: "Sign out" }));

    await waitFor(() => expect(logout).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(currentLocation()).toBe("/login"));
  });

  it("stays on the current route when signing out does not clear the session", async () => {
    const user = userEvent.setup();
    const logout = vi.fn(async () => false);
    act(() => {
      useAuthStore.setState({ logout });
    });
    renderShell();

    await user.click(screen.getByRole("button", { name: "Account menu for max@example.test" }));
    await user.click(screen.getByRole("menuitem", { name: "Sign out" }));

    await waitFor(() => expect(logout).toHaveBeenCalledTimes(1));
    expect(screen.queryByRole("menu", { name: "Account" })).not.toBeInTheDocument();
    expect(currentLocation()).toBe("/tasks/next");
  });

  it("closes on Escape, on an outside click, and on a second press of the trigger", async () => {
    const user = userEvent.setup();
    renderShell();

    const trigger = screen.getByRole("button", { name: "Account menu for max@example.test" });

    await user.click(trigger);
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("menu", { name: "Account" })).not.toBeInTheDocument();

    await user.click(trigger);
    await user.click(screen.getByRole("link", { name: "BrainBuddy" }));
    expect(screen.queryByRole("menu", { name: "Account" })).not.toBeInTheDocument();

    await user.click(trigger);
    await user.click(trigger);
    expect(screen.queryByRole("menu", { name: "Account" })).not.toBeInTheDocument();
  });

  it("ignores keys other than Escape while the menu is open", async () => {
    const user = userEvent.setup();
    renderShell();

    await user.click(screen.getByRole("button", { name: "Account menu for max@example.test" }));
    await user.keyboard("a");

    expect(screen.getByRole("menu", { name: "Account" })).toBeInTheDocument();
  });

  // These three were inverted, not deleted. Before PD-1 the shell probed
  // `/admin/status` on every render and showed an "Admin portal" item to an
  // operator; the assertions below are the same scenarios re-pointed at the
  // decided behaviour, so a re-introduced menu entry fails here rather than
  // slipping through as an untested removal.

  it("009-FR-010, 009-FR-011: never renders an Admin portal entry, whatever the server would say", async () => {
    const user = userEvent.setup();
    const spy = vi.spyOn(apiClient, "getAdminStatus").mockResolvedValue({ is_operator: true });
    renderShell();

    await user.click(screen.getByRole("button", { name: "Account menu for max@example.test" }));

    expect(screen.getByRole("menu", { name: "Account" })).toBeInTheDocument();
    expect(screen.queryByRole("menuitem", { name: "Admin portal" })).not.toBeInTheDocument();
    expect(spy).not.toHaveBeenCalled();
    expect(currentLocation()).not.toBe("/admin");
  });

  it("010-FR-006: the shell issues no request to any /admin route, including the new flag routes", async () => {
    // PD-1 holds unchanged for feature 010: `/admin` is reached only by typing
    // the URL, so a member who never does issues no admin request of any kind
    // — the flag routes are behind the same gate and the same silence.
    const user = userEvent.setup();
    const spies = [
      vi.spyOn(apiClient, "getAdminStatus"),
      vi.spyOn(apiClient, "getAdminFeatureFlags"),
      vi.spyOn(apiClient, "setAdminFeatureFlagMode"),
      vi.spyOn(apiClient, "addAdminFeatureFlagUser"),
      vi.spyOn(apiClient, "removeAdminFeatureFlagUser")
    ];
    renderShell();

    await user.click(screen.getByRole("button", { name: "Account menu for max@example.test" }));
    await user.keyboard("{Escape}");

    for (const spy of spies) {
      expect(spy).not.toHaveBeenCalled();
    }
    expect(screen.queryByRole("menuitem", { name: /feature flag/i })).not.toBeInTheDocument();
  });

  it("009-SC-006: an authenticated shell issues no admin request during ordinary navigation", async () => {
    const user = userEvent.setup();
    const spy = vi.spyOn(apiClient, "getAdminStatus");
    renderShell();

    await user.click(screen.getByRole("button", { name: "Account menu for max@example.test" }));
    await user.keyboard("{Escape}");
    await user.click(screen.getByRole("button", { name: "Account menu for max@example.test" }));

    expect(spy).not.toHaveBeenCalled();
  });

  it("009-FR-010: renders the account menu with no admin entry and no capability query at all", async () => {
    const user = userEvent.setup();
    const spy = vi.spyOn(apiClient, "getAdminStatus").mockResolvedValue(
      null as unknown as Awaited<ReturnType<typeof apiClient.getAdminStatus>>
    );
    renderShell();

    await user.click(screen.getByRole("button", { name: "Account menu for max@example.test" }));

    expect(screen.getByRole("menu", { name: "Account" })).toBeInTheDocument();
    expect(screen.queryByRole("menuitem", { name: "Admin portal" })).not.toBeInTheDocument();
    expect(spy).not.toHaveBeenCalled();
  });

  it("stays open while the pointer lands inside the menu itself", async () => {
    const user = userEvent.setup();
    renderShell();

    await user.click(screen.getByRole("button", { name: "Account menu for max@example.test" }));
    await user.click(screen.getByText("max@example.test", { selector: "p" }));

    expect(screen.getByRole("menu", { name: "Account" })).toBeInTheDocument();
  });

  it("prefers a display name over the email and falls back when the session has neither", async () => {
    const user = userEvent.setup();
    act(() => {
      useAuthStore.setState({
        user: { id: "user-1", email: "max@example.test", display_name: "Max K" }
      });
    });
    const { unmount } = render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <MemoryRouter initialEntries={["/tasks/next"]}>
          <AppShell counts={counts} projects={projects} tags={tags} activeState="next">
            <div>content</div>
          </AppShell>
        </MemoryRouter>
      </QueryClientProvider>
    );

    const named = screen.getByRole("button", { name: "Account menu for max@example.test" });
    expect(named).toHaveTextContent("M");
    await user.click(named);
    expect(screen.getByText("Max K")).toBeInTheDocument();
    expect(screen.getByText("max@example.test")).toBeInTheDocument();
    unmount();

    act(() => {
      useAuthStore.setState({ user: null });
    });
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <MemoryRouter initialEntries={["/tasks/next"]}>
          <AppShell counts={counts} projects={projects} tags={tags} activeState="next">
            <div>content</div>
          </AppShell>
        </MemoryRouter>
      </QueryClientProvider>
    );

    const anonymous = screen.getByRole("button", { name: "Account menu" });
    expect(anonymous).toHaveTextContent("M");
    await user.click(anonymous);
    expect(screen.getByText("Signed in")).toBeInTheDocument();
  });
});

describe("AppShell deletion notice", () => {
  it("welcomes a returning user whose deletion was cancelled and dismisses the banner on request", async () => {
    const user = userEvent.setup();
    act(() => {
      useAuthStore.setState({ deletionCancelledNotice: true });
    });
    renderShell();

    expect(screen.getByText("Welcome back — your scheduled account deletion has been cancelled.")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Dismiss deletion notice" }));
    expect(
      screen.queryByText("Welcome back — your scheduled account deletion has been cancelled.")
    ).not.toBeInTheDocument();
  });

  it("shows no banner for an ordinary session", () => {
    renderShell();

    expect(
      screen.queryByText("Welcome back — your scheduled account deletion has been cancelled.")
    ).not.toBeInTheDocument();
  });
});

describe("020-FR-051 AppShell review dialogs at web open", () => {
  const DAY = 86_400_000;
  const iso = (offsetMs: number) => new Date(Date.now() + offsetMs).toISOString();
  const apiOrigin = "http://localhost:3000/api";
  const baseState: ReviewState = {
    settings: { threshold_days: 14, review_weekday: 5, review_time: "16:00", time_zone: "UTC", onboarded_at: null, activated_at: null, owner_park_floor_at: null, revision: 1 },
    explainer_seen: false,
    grace_until: null,
    last_counted_review_at: null,
    last_counted_review: null,
    next_review_at: null,
    restart_mode: false,
    open_session: null,
    unseen_parks: [],
    counts: { asks_for_decision: 0, moves_tomorrow: 0 },
    receipts: [],
    server_now: iso(0)
  };
  const parkedAt = iso(-1 * DAY);
  const seenWithParks: ReviewState = {
    ...baseState,
    explainer_seen: true,
    grace_until: iso(13 * DAY),
    settings: { ...baseState.settings, activated_at: iso(-1 * DAY), revision: 2 },
    unseen_parks: [{ task_id: "task-pt", formulation_id: "form_pt", parked_at: parkedAt }]
  };
  const parkedTask = {
    id: "task-pt",
    title: "Learn basic Portuguese",
    details: null,
    state: "someday" as const,
    project_id: null,
    tag_ids: [],
    due_date: null,
    priority: "none" as const,
    waiting_for: null,
    waiting_since: null,
    order_key: 1,
    source_capture_ids: [],
    created_at: iso(-40 * DAY),
    updated_at: parkedAt,
    completed_at: null,
    cancelled_at: null,
    revision: 4,
    formulation: null,
    parked: { at: parkedAt, formulation_id: "form_pt" }
  };

  /** Let the loaded review state render before asserting that nothing shows. */
  const flush = () => act(() => new Promise<void>((resolve) => setTimeout(resolve, 20)));

  function signIn(id: string, flags: Record<string, boolean> = { weekly_review: true }) {
    act(() => {
      useAuthStore.setState({ user: { id, email: `${id}@example.test`, feature_flags: flags }, status: "authed" });
    });
  }

  function renderWithHeading(headingTabIndex?: number) {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    return render(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={["/tasks/next"]}>
          <AppShell counts={counts} projects={projects} tags={tags}>
            <h1 tabIndex={headingTabIndex}>Next actions</h1>
          </AppShell>
        </MemoryRouter>
      </QueryClientProvider>
    );
  }

  beforeEach(() => {
    window.localStorage.clear();
    vi.spyOn(apiClient, "getTask").mockResolvedValue(parkedTask);
    vi.spyOn(apiClient, "listProjects").mockResolvedValue([]);
  });

  afterEach(() => {
    vi.mocked(reviewApi.getState).mockReset();
    vi.mocked(reviewApi.acknowledgeExplainer).mockReset();
    vi.mocked(reviewApi.acknowledgeParks).mockReset();
    window.localStorage.clear();
  });

  it("020-FR-042 with the flag off the shell asks the review nothing and keeps “Weekly review — Coming soon”", () => {
    renderShell();

    expect(screen.getByRole("button", { name: "Weekly review — Coming soon" })).toBeDisabled();
    expect(reviewApi.getState).not.toHaveBeenCalled();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("020-FR-042 020-FR-038 with the flag on the sidebar link works and shows when the last review was", async () => {
    signIn("user-link");
    vi.mocked(reviewApi.getState).mockResolvedValue({ ...seenWithParks, unseen_parks: [], last_counted_review_at: iso(-9 * DAY) });
    renderShell();

    const link = await screen.findByRole("link", { name: /Weekly review/ });
    expect(link).toHaveAttribute("href", "/review");
    await waitFor(() => expect(link).toHaveTextContent("Last review: 9 days ago"));
    expect(screen.queryByRole("button", { name: "Weekly review — Coming soon" })).not.toBeInTheDocument();
  });

  it("020-FR-038 the link shows no recap line while the state loads or after it failed", async () => {
    signIn("user-recap");
    vi.mocked(reviewApi.getState).mockReturnValueOnce(new Promise(() => undefined));
    const loading = renderWithHeading();

    const link = await screen.findByRole("link", { name: "Weekly review" });
    expect(link).toHaveAttribute("href", "/review");
    expect(link).not.toHaveTextContent(/Last review|Set up/);
    loading.unmount();

    vi.mocked(reviewApi.getState).mockRejectedValueOnce(new Error("down"));
    renderWithHeading();
    await waitFor(() => expect(reviewApi.getState).toHaveBeenCalledTimes(2));
    await flush();
    expect(screen.getByRole("link", { name: "Weekly review" })).not.toHaveTextContent(/Last review|Set up/);
  });

  it("020-FR-035 020-FR-038 someone who never reviewed is offered setup instead of a day count", async () => {
    signIn("user-never");
    vi.mocked(reviewApi.getState).mockResolvedValue({ ...seenWithParks, unseen_parks: [], last_counted_review_at: null });
    renderShell();

    expect(await screen.findByRole("link", { name: /^Weekly review\s*Set up in a minute$/ })).toBeInTheDocument();
  });

  it("020-FR-042 the 390 px navigation drawer carries the same working link", async () => {
    const user = userEvent.setup();
    signIn("user-drawer");
    vi.mocked(reviewApi.getState).mockResolvedValue({ ...seenWithParks, unseen_parks: [], last_counted_review_at: iso(-1 * DAY) });
    renderShell();
    await flush();

    await user.click(screen.getByRole("button", { name: "Open task navigation" }));
    const drawer = screen.getByRole("dialog", { name: "Task navigation" });

    const link = within(drawer).getByRole("link", { name: /Weekly review/ });
    expect(link).toHaveAttribute("href", "/review");
    expect(link).toHaveTextContent("Last review: 1 day ago");
  });

  it("020-FR-051 020-FR-015 shows the explainer first, then While you were away, and focus returns to the main heading", async () => {
    const user = userEvent.setup();
    signIn("user-order");
    vi.mocked(reviewApi.getState).mockResolvedValueOnce(baseState).mockResolvedValue(seenWithParks);
    vi.mocked(reviewApi.acknowledgeExplainer).mockResolvedValueOnce(seenWithParks);
    vi.mocked(reviewApi.acknowledgeParks).mockResolvedValueOnce(undefined);
    renderWithHeading(-1);

    expect(await screen.findByRole("dialog", { name: "How Next stays fresh" })).toBeInTheDocument();
    expect(screen.queryByRole("dialog", { name: "While you were away" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Got it" }));

    const away = await screen.findByRole("dialog", { name: "While you were away" });
    expect(screen.queryByRole("dialog", { name: "How Next stays fresh" })).not.toBeInTheDocument();
    expect(await within(away).findByText("Learn basic Portuguese")).toBeInTheDocument();
    expect(readWhileAwayLastShown({ apiOrigin, accountId: "user-order" })).toBe(localDay());

    await user.click(within(away).getByRole("button", { name: "Continue" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(screen.getByRole("heading", { level: 1, name: "Next actions" })).toHaveFocus();
  });

  it("020-FR-015 Escape leaves the parks unseen, focuses the main heading and does not show again today", async () => {
    const user = userEvent.setup();
    signIn("user-esc");
    vi.mocked(reviewApi.getState).mockResolvedValue(seenWithParks);
    const first = renderWithHeading();

    await screen.findByRole("dialog", { name: "While you were away" });
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    const heading = screen.getByRole("heading", { level: 1, name: "Next actions" });
    expect(heading).toHaveFocus();
    expect(heading).toHaveAttribute("tabindex", "-1");
    expect(reviewApi.acknowledgeParks).not.toHaveBeenCalled();
    first.unmount();

    renderWithHeading();
    await waitFor(() => expect(reviewApi.getState).toHaveBeenCalledTimes(2));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("020-FR-015 shows nothing when the parks were already shown today or there are none", async () => {
    signIn("user-today");
    markWhileAwayShown({ apiOrigin, accountId: "user-today" }, localDay());
    vi.mocked(reviewApi.getState).mockResolvedValue(seenWithParks);
    renderWithHeading();

    await waitFor(() => expect(reviewApi.getState).toHaveBeenCalled());
    await flush();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("020-FR-015 closing on a page without a main heading leaves focus where it is", async () => {
    const user = userEvent.setup();
    signIn("user-no-heading");
    vi.mocked(reviewApi.getState).mockResolvedValue(seenWithParks);
    renderShell();

    await screen.findByRole("dialog", { name: "While you were away" });
    await user.click(screen.getByRole("button", { name: "Close" }));

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(reviewApi.acknowledgeParks).not.toHaveBeenCalled();
  });

  it("020-FR-051 an explainer closed offline stays away for the rest of this web open", async () => {
    const user = userEvent.setup();
    signIn("user-offline");
    const online = vi.spyOn(navigator, "onLine", "get").mockReturnValue(false);
    vi.mocked(reviewApi.getState).mockResolvedValue(baseState);
    const first = renderWithHeading();

    await screen.findByRole("dialog", { name: "How Next stays fresh" });
    await user.click(screen.getByRole("button", { name: "Close" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(reviewApi.acknowledgeExplainer).not.toHaveBeenCalled();
    first.unmount();
    online.mockReturnValue(true);

    renderWithHeading();
    await waitFor(() => expect(reviewApi.getState).toHaveBeenCalledTimes(2));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("020-FR-051 020-FR-042 an explainer one account closed for later is still shown to the next account in the same open shell", async () => {
    const user = userEvent.setup();
    signIn("user-later-a");
    const online = vi.spyOn(navigator, "onLine", "get").mockReturnValue(false);
    vi.mocked(reviewApi.getState).mockResolvedValue(baseState);
    renderWithHeading();

    await screen.findByRole("dialog", { name: "How Next stays fresh" });
    await user.click(screen.getByRole("button", { name: "Close" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    online.mockReturnValue(true);

    // A session refresh swaps the account while the shell stays mounted.
    signIn("user-later-b");

    expect(await screen.findByRole("dialog", { name: "How Next stays fresh" })).toBeInTheDocument();
  });

  it("020-FR-051 020-FR-042 an account switch never hands one account's open explainer to the next", async () => {
    const user = userEvent.setup();
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    vi.mocked(reviewApi.getState).mockResolvedValue(baseState);
    // B's state is already cached, so the dialog would otherwise be reused in place.
    client.setQueryData(["review", "state", { accountId: "user-keep-b", apiOrigin }], baseState);
    signIn("user-keep-a");
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={["/tasks/next"]}>
          <AppShell counts={counts} projects={projects} tags={tags}>
            <h1>Next actions</h1>
          </AppShell>
        </MemoryRouter>
      </QueryClientProvider>
    );
    await screen.findByRole("dialog", { name: "How Next stays fresh" });
    await user.click(screen.getByRole("button", { name: "Change the number of days" }));
    await user.click(screen.getByRole("radio", { name: "28 days" }));

    signIn("user-keep-b");

    const fresh = await screen.findByRole("dialog", { name: "How Next stays fresh" });
    expect(fresh).toHaveTextContent("If a next action keeps the same wording for 14 days, it asks for a decision.");
    expect(within(fresh).getByRole("button", { name: "Change the number of days" })).toBeInTheDocument();
  });
});
