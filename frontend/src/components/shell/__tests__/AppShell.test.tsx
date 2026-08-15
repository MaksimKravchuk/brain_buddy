import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "../../../api/client";
import type { ProjectResponse, TagResponse, TaskCounts } from "../../../api/taskTypes";
import { useAuthStore } from "../../../stores/authStore";
import { AppShell } from "../AppShell";
import { useShellToast } from "../shellToast";

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
  const notify = useShellToast();

  return (
    <div>
      <div>{pathname === "/tasks/inbox" ? "Inbox task list content" : "Next task list content"}</div>
      <span className="sr-only" data-testid="pathname">{pathname}</span>
      <div data-testid="location">{`${pathname}${search}`}</div>
      <div data-testid="location-state">{state ? JSON.stringify(state) : "none"}</div>
      <button type="button" onClick={() => notify("Thinking canvas isn't built yet — placeholder")}>
        Raise shell toast
      </button>
    </div>
  );
}

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

    expect(screen.getByRole("link", { name: "Brain Buddy" })).toHaveClass("shrink-0", "whitespace-nowrap");
    expect(screen.getByRole("button", { name: "Brain dump" })).toHaveClass("shrink-0", "whitespace-nowrap", "px-3", "sm:px-4");
  });

  it("returns to the Inbox route after Weekly review without retaining the in-shell placeholder", async () => {
    const user = userEvent.setup();
    renderShell();

    expect(screen.getByRole("button", { name: "Thinking Mode — Coming soon" })).toBeDisabled();
    expect(screen.getByText("Next task list content")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Weekly review" }));
    expect(screen.getByRole("region", { name: "Weekly review placeholder" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Weekly review — coming soon" })).toBeInTheDocument();
    expect(screen.queryByText("Next task list content")).not.toBeInTheDocument();

    await user.click(screen.getByRole("link", { name: "Inbox" }));
    expect(await screen.findByText("Inbox task list content")).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Weekly review placeholder" })).not.toBeInTheDocument();
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
    await user.keyboard("{Escape}");

    await user.click(screen.getByRole("button", { name: "New tag" }));
    const tagName = screen.getByLabelText("New tag name");
    await user.type(tagName, "  {Enter}");
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

  it("closes on Escape, on an outside click, and on a second press of the trigger", async () => {
    const user = userEvent.setup();
    renderShell();

    const trigger = screen.getByRole("button", { name: "Account menu for max@example.test" });

    await user.click(trigger);
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("menu", { name: "Account" })).not.toBeInTheDocument();

    await user.click(trigger);
    await user.click(screen.getByRole("link", { name: "Brain Buddy" }));
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
