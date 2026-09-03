import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, apiClient } from "../../../api/client";
import type {
  ProjectResponse,
  TagResponse,
  TaskListFilters,
  TaskListResponse,
  TaskResponse,
  TaskState
} from "../../../api/taskTypes";
import { useAuthStore } from "../../../stores/authStore";
import { TaskListPage } from "../TaskListPage";
import { resetTaskDetailAutosaveControllersForTests, taskAutosaveStorageKey } from "../taskDetailAutosave";

vi.mock("../../../api/client", async () => {
  const actual = await vi.importActual<typeof import("../../../api/client")>("../../../api/client");
  return {
    ...actual,
    apiClient: {
      listTasks: vi.fn(),
      getTask: vi.fn(),
      listProjects: vi.fn(),
      listTags: vi.fn(),
      createTask: vi.fn(),
      smartAddTask: vi.fn(),
      getTitleCompletionProvider: vi.fn(),
      generateTitleCompletions: vi.fn(),
      recordTitleCompletionAccepted: vi.fn(),
      updateTask: vi.fn(),
      transitionTask: vi.fn(),
      createSubtask: vi.fn(),
      transitionSubtask: vi.fn(),
      createComment: vi.fn(),
      createProject: vi.fn(),
      updateProject: vi.fn(),
      archiveProject: vi.fn(),
      createTag: vi.fn(),
      updateTag: vi.fn(),
      deleteTag: vi.fn(),
      listAgentRunSummaries: vi.fn(),
      listAgentRuns: vi.fn()
    }
  };
});

const mocked = vi.mocked(apiClient, true);

const projects: ProjectResponse[] = [
  { id: "project-launch", name: "Launch v2", color: "#0ea5e9", state: "active", revision: 3, open_task_count: 2 },
  { id: "project-onboarding", name: "Onboarding drop-off", color: null, state: "active", revision: 1, open_task_count: 1 }
];

const tags: TagResponse[] = [
  { id: "tag-calls", name: "@calls", state: "active", revision: 2, open_task_count: 2 },
  { id: "tag-deep-work", name: "deep-work", state: "active", revision: 1, open_task_count: 1 }
];

function taskFixture(overrides: Partial<TaskResponse> = {}): TaskResponse {
  return {
    id: "task-1",
    title: "Fix onboarding drop-off",
    details: null,
    state: "next" as TaskState,
    project_id: "project-launch",
    tag_ids: ["tag-deep-work"],
    due_date: null,
    priority: "none",
    waiting_for: null,
    waiting_since: null,
    order_key: 1,
    source_capture_ids: [],
    created_at: "2026-07-15T10:00:00Z",
    updated_at: "2026-07-15T10:00:00Z",
    completed_at: null,
    cancelled_at: null,
    revision: 4,
    subtasks: [],
    comments: [],
    ...overrides
  };
}

function listResponse(items: TaskResponse[], overrides: Partial<TaskListResponse> = {}): TaskListResponse {
  return {
    items,
    next_cursor: null,
    has_more: false,
    counts_by_state: { inbox: 17, next: items.length, waiting: 3, someday: 0 },
    ...overrides
  };
}

/** The filters the page passed to the last non-badge list query. */
function lastListFilters(): TaskListFilters {
  const calls = mocked.listTasks.mock.calls.filter(([filters]) => !(filters as TaskListFilters).limit);
  return calls[calls.length - 1]?.[0] as TaskListFilters;
}

function LocationProbe(): React.JSX.Element {
  const { pathname, search } = useLocation();
  return <div data-testid="location">{`${pathname}${search}`}</div>;
}

const currentLocation = () => screen.getByTestId("location").textContent;

function renderPage(initialEntry = "/tasks/next") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[initialEntry]}>
        <LocationProbe />
        <Routes>
          <Route path="/tasks/:state" element={<TaskListPage mode="state" />} />
          <Route path="/tasks/:state/:taskId" element={<TaskListPage mode="state" />} />
          <Route path="/projects/:projectId" element={<TaskListPage mode="project" />} />
          <Route path="/projects/:projectId/:taskId" element={<TaskListPage mode="project" />} />
          <Route path="/tags/:tagId" element={<TaskListPage mode="tag" />} />
          <Route path="/tags/:tagId/:taskId" element={<TaskListPage mode="tag" />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  );
}

beforeEach(() => {
  resetTaskDetailAutosaveControllersForTests();
  sessionStorage.clear();
  act(() => {
    useAuthStore.setState({ user: { id: "user-1", email: "max@example.test" }, status: "authed" });
  });
  vi.spyOn(window, "confirm").mockReturnValue(true);
  mocked.listTasks.mockImplementation(async () => listResponse([taskFixture()]));
  mocked.getTask.mockImplementation(async () => taskFixture());
  mocked.listProjects.mockResolvedValue(projects);
  mocked.listTags.mockResolvedValue(tags);
  mocked.createTask.mockImplementation(async () => taskFixture({ id: "task-new" }));
  mocked.smartAddTask.mockImplementation(async () => ({
    task: taskFixture({ id: "task-smart" }),
    project: null,
    tags: [],
    created: { project_id: null, tag_ids: [] }
  }));
  mocked.getTitleCompletionProvider.mockResolvedValue({ provider: "deterministic" });
  mocked.generateTitleCompletions.mockResolvedValue({
    request_id: "8f3d2f73-0e55-4f47-9f9b-1a0b6c7a9c6e",
    candidates: ["Prepare launch notes today", "Prepare launch notes this week", "Prepare launch notes tomorrow"]
  });
  mocked.recordTitleCompletionAccepted.mockResolvedValue(undefined);
  mocked.updateTask.mockImplementation(async (_id, payload) => taskFixture({ ...payload, revision: payload.expected_revision + 1 }));
  mocked.transitionTask.mockImplementation(async (_id, payload) => {
    const state = payload.action === "complete" ? "completed" : payload.action === "cancel" ? "cancelled" : payload.to_state ?? "next";
    return taskFixture({
      state,
      revision: payload.expected_revision + 1,
      waiting_for: state === "waiting" ? payload.waiting_for ?? "Waiting" : null,
      waiting_since: state === "waiting" ? "2026-07-15T11:00:00Z" : null,
      completed_at: state === "completed" ? "2026-07-15T11:00:00Z" : null,
      cancelled_at: state === "cancelled" ? "2026-07-15T11:00:00Z" : null
    });
  });
  mocked.createSubtask.mockResolvedValue({ id: "subtask-1", title: "Draft", state: "open", order_key: 1, revision: 1 });
  mocked.transitionSubtask.mockResolvedValue({
    id: "subtask-1",
    title: "Draft",
    state: "completed",
    order_key: 1,
    revision: 2
  });
  mocked.createComment.mockResolvedValue({
    id: "comment-1",
    body: "Noted",
    actor_id: "user-1",
    created_at: "2026-07-16T09:30:00Z",
    edited_at: null,
    revision: 1
  });
  mocked.createProject.mockResolvedValue(projects[0]);
  mocked.updateProject.mockResolvedValue(projects[0]);
  mocked.archiveProject.mockResolvedValue({ ...projects[0], state: "archived" });
  mocked.createTag.mockResolvedValue(tags[0]);
  mocked.updateTag.mockResolvedValue(tags[0]);
  mocked.deleteTag.mockResolvedValue({ ...tags[0], state: "deleted" });
  mocked.listAgentRunSummaries.mockResolvedValue({});
  mocked.listAgentRuns.mockResolvedValue([]);
});

afterEach(() => {
  resetTaskDetailAutosaveControllersForTests();
  sessionStorage.clear();
  vi.clearAllMocks();
  act(() => {
    useAuthStore.setState({ user: null, status: "loading" });
  });
});

describe("TaskListPage projections", () => {
  it("shows honest agent and needs-you chips and still queries them when rollout is off", async () => {
    act(() => {
      useAuthStore.setState({
        user: {
          id: "user-1",
          email: "max@example.test",
          feature_flags: {}
        },
        status: "authed"
      });
    });
    mocked.listTasks.mockImplementation(async () =>
      listResponse([
        taskFixture(),
        taskFixture({ id: "task-2", title: "Approve staging", order_key: 2 })
      ])
    );
    mocked.listAgentRunSummaries.mockResolvedValue({
      "task-1": {
        id: "agentrun-1",
        task_id: "task-1",
        agent_name: "Hermes",
        primary_state_label: "Running",
        needs_user: false,
        stopped_reporting: false,
        last_contact_at: "2026-08-11T12:00:00Z"
      },
      "task-2": {
        id: "agentrun-2",
        task_id: "task-2",
        agent_name: "Hermes",
        primary_state_label: "Needs you",
        needs_user: true,
        stopped_reporting: false,
        last_contact_at: "2026-08-11T12:01:00Z"
      }
    });

    renderPage();

    expect(await screen.findByText("Running")).toBeInTheDocument();
    expect(screen.getByText("Needs you")).toBeInTheDocument();
    expect(mocked.listAgentRunSummaries).toHaveBeenCalledWith(
      ["task-1", "task-2"],
      expect.any(AbortSignal)
    );
  });

  it("titles each projection from the route and groups tasks by project by default", async () => {
    renderPage("/tasks/next");

    expect(await screen.findByRole("heading", { level: 1, name: "Next actions" })).toBeInTheDocument();
    expect(await screen.findByRole("heading", { level: 2, name: "Launch v2" })).toBeInTheDocument();
    expect(screen.getByText("1 task")).toBeInTheDocument();
  });

  it("leads the Inbox with a processing hint and offers no grouping there", async () => {
    mocked.listTasks.mockImplementation(async () => listResponse([taskFixture({ project_id: null })]));
    renderPage("/tasks/inbox");

    expect(await screen.findByRole("heading", { level: 1, name: "Inbox" })).toBeInTheDocument();
    expect(screen.getByText("Process these — decide the next action for each.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Group by project" })).not.toBeInTheDocument();
    await waitFor(() => expect(lastListFilters().unassignedProject).toBe(true));
  });

  it("names a project view after the project and a tag view after the tag", async () => {
    const { unmount } = renderPage("/projects/project-launch");
    expect(await screen.findByRole("heading", { level: 1, name: "Launch v2" })).toBeInTheDocument();
    await waitFor(() => expect(lastListFilters().projectId).toBe("project-launch"));
    unmount();

    renderPage("/tags/tag-calls");
    expect(await screen.findByRole("heading", { level: 1, name: "#calls" })).toBeInTheDocument();
    await waitFor(() => expect(lastListFilters().tagId).toBe("tag-calls"));
  });

  it("falls back to neutral titles when the referenced project or tag is unknown", async () => {
    const { unmount } = renderPage("/projects/project-missing");
    expect(await screen.findByRole("heading", { level: 1, name: "Project" })).toBeInTheDocument();
    unmount();

    renderPage("/tags/tag-missing");
    expect(await screen.findByRole("heading", { level: 1, name: "#tag" })).toBeInTheDocument();
  });

  it("falls back to Next actions for an unknown state route", async () => {
    renderPage("/tasks/not-a-state");

    expect(await screen.findByRole("heading", { level: 1, name: "Next actions" })).toBeInTheDocument();
  });

  it("turns each date view into the matching due-date filter and swaps capture for a hint", async () => {
    const { unmount: closeOverdue } = renderPage("/tasks/overdue");
    expect(await screen.findByRole("heading", { level: 1, name: "Overdue" })).toBeInTheDocument();
    expect(screen.getByText(/Date views are filters over existing tasks/)).toBeInTheDocument();
    expect(screen.queryByLabelText("New task title")).not.toBeInTheDocument();
    await waitFor(() => expect(lastListFilters().dueBefore).toMatch(/^\d{4}-\d{2}-\d{2}$/));
    closeOverdue();

    const { unmount: closeToday } = renderPage("/tasks/today");
    expect(await screen.findByRole("heading", { level: 1, name: "Today" })).toBeInTheDocument();
    await waitFor(() => expect(lastListFilters().dueOn).toMatch(/^\d{4}-\d{2}-\d{2}$/));
    closeToday();

    renderPage("/tasks/upcoming");
    expect(await screen.findByRole("heading", { level: 1, name: "Upcoming" })).toBeInTheDocument();
    await waitFor(() => expect(lastListFilters().dueAfter).toMatch(/^\d{4}-\d{2}-\d{2}$/));
  });

  it("shows a skeleton while the frame loads and an empty state when nothing comes back", async () => {
    let resolveList: (value: TaskListResponse) => void = () => undefined;
    mocked.listTasks.mockImplementation(
      (filters) =>
        filters?.limit
          ? Promise.resolve(listResponse([]))
          : new Promise<TaskListResponse>((resolve) => {
              resolveList = resolve;
            })
    );

    renderPage("/tasks/someday");
    expect(await screen.findByLabelText("Loading Someday / maybe")).toBeInTheDocument();

    await act(async () => {
      resolveList(listResponse([]));
    });

    expect(await screen.findByText("Someday / maybe is clear")).toBeInTheDocument();
  });

  it("says a view is clear without naming a list when the view is a project", async () => {
    mocked.listTasks.mockImplementation(async () => listResponse([]));
    renderPage("/projects/project-launch");

    expect(await screen.findByText("This view is clear")).toBeInTheDocument();
  });

  it("reports a failed projects or tags load through the same frame error", async () => {
    const user = userEvent.setup();
    mocked.listProjects.mockRejectedValueOnce(new Error("Projects are unavailable."));
    renderPage("/tasks/next");

    expect(await screen.findByRole("alert")).toHaveTextContent("Projects are unavailable.");

    mocked.listTags.mockRejectedValueOnce(new Error("Tags are unavailable."));
    await user.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Tags are unavailable."));
  });

  it("recovers from a failed frame load when the reader retries", async () => {
    mocked.listTasks.mockRejectedValueOnce(new Error("Tasks are unavailable."));
    renderPage("/tasks/next");

    expect(await screen.findByRole("alert")).toHaveTextContent("Tasks are unavailable.");
    expect(screen.getByText("We couldn't load tasks")).toBeInTheDocument();

    await userEvent.setup().click(screen.getByRole("button", { name: "Retry" }));

    expect(await screen.findByText("Fix onboarding drop-off")).toBeInTheDocument();
  });

  it("loads the next page on demand and says so while it is in flight", async () => {
    const user = userEvent.setup();
    let releaseSecondPage: (value: TaskListResponse) => void = () => undefined;
    mocked.listTasks.mockImplementation((filters) => {
      if (filters?.limit) {
        return Promise.resolve(listResponse([]));
      }
      if (filters?.cursor) {
        return new Promise<TaskListResponse>((resolve) => {
          releaseSecondPage = resolve;
        });
      }
      return Promise.resolve(listResponse([taskFixture()], { next_cursor: "cursor-2", has_more: true }));
    });

    renderPage("/tasks/next");
    await user.click(await screen.findByRole("button", { name: "Load more tasks" }));

    const loading = await screen.findByText("Loading more tasks…");
    expect(loading.closest("button")).toBeDisabled();
    await act(async () => {
      releaseSecondPage(listResponse([taskFixture({ id: "task-2", title: "Second page task" })]));
    });

    expect(await screen.findByText("Second page task")).toBeInTheDocument();
    await waitFor(() => expect(lastListFilters().cursor).toBe("cursor-2"));
  });
});

describe("TaskListPage list controls", () => {
  it("moves grouping, sorting and completed tasks through the URL and the query", async () => {
    const user = userEvent.setup();
    renderPage("/tasks/next");

    await user.click(await screen.findByRole("button", { name: "Group by project" }));
    expect(currentLocation()).toBe("/tasks/next?group=off");
    expect(screen.queryByRole("heading", { level: 2, name: "Launch v2" })).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Group by project" }));
    expect(currentLocation()).toBe("/tasks/next");

    await user.selectOptions(screen.getByLabelText("Sort tasks"), "due");
    expect(currentLocation()).toBe("/tasks/next?sort=due");
    await waitFor(() => expect(lastListFilters().sort).toBe("due"));

    await user.selectOptions(screen.getByLabelText("Sort tasks"), "manual");
    expect(currentLocation()).toBe("/tasks/next");

    await user.click(screen.getByRole("checkbox", { name: "Show completed" }));
    await waitFor(() => expect(lastListFilters().includeCompleted).toBe(true));
    expect(lastListFilters().includeCancelled).toBe(true);
  });

  it("reads an unknown sort in the URL as manual order", async () => {
    renderPage("/tasks/next?sort=nonsense");

    expect(await screen.findByLabelText("Sort tasks")).toHaveValue("manual");
    await waitFor(() => expect(lastListFilters().sort).toBe("manual"));
  });

  it("carries the search box query into the list request", async () => {
    renderPage("/tasks/next?q=onboarding");

    await waitFor(() => expect(lastListFilters().q).toBe("onboarding"));
  });

  it("sinks the projectless group beneath the named ones", async () => {
    mocked.listTasks.mockImplementation(async () =>
      listResponse([
        taskFixture({ id: "task-loose", title: "Loose end", project_id: null }),
        taskFixture({ id: "task-launch", title: "Launch task", project_id: "project-launch" }),
        taskFixture({ id: "task-unknown", title: "Orphan project task", project_id: "project-gone" })
      ])
    );
    renderPage("/tasks/next");

    const headings = await screen.findAllByRole("heading", { level: 2 });
    expect(headings.map((heading) => heading.textContent)).toEqual(["Launch v2", "No project", "No project"]);
  });
});

describe("TaskListPage rows", () => {
  it("renders due dates, subtask progress, tags and who a task waits on", async () => {
    mocked.listTasks.mockImplementation(async () =>
      listResponse([
        taskFixture({
          id: "task-rich",
          title: "Rich row",
          due_date: "2026-08-01",
          tag_ids: ["tag-calls", "tag-deep-work"],
          state: "waiting",
          waiting_for: "Finance",
          subtasks: [
            { id: "s1", title: "One", state: "completed", order_key: 1, revision: 1 },
            { id: "s2", title: "Two", state: "open", order_key: 2, revision: 1 }
          ]
        })
      ])
    );
    renderPage("/tasks/waiting");

    const row = (await screen.findByText("Rich row")).closest("article") as HTMLElement;
    expect(within(row).getByText("1 / 2")).toBeInTheDocument();
    expect(within(row).getByText("Finance")).toBeInTheDocument();
    expect(within(row).getByText("@calls")).toBeInTheDocument();
    expect(within(row).getByText("#deep-work")).toBeInTheDocument();
    expect(within(row).getByText(new Date("2026-08-01T00:00:00Z").toLocaleDateString(undefined, {
      month: "short",
      day: "numeric",
      timeZone: "UTC"
    }))).toBeInTheDocument();
  });

  it("renders a row the server sent without a subtask array", async () => {
    mocked.listTasks.mockImplementation(async () =>
      listResponse([taskFixture({ id: "task-bare", title: "Bare row", subtasks: undefined })])
    );
    renderPage("/tasks/next");

    const row = (await screen.findByText("Bare row")).closest("article") as HTMLElement;
    expect(within(row).queryByText("/", { exact: false })).not.toBeInTheDocument();
  });

  it("keeps an unparseable due date visible rather than swallowing it", async () => {
    mocked.listTasks.mockImplementation(async () =>
      listResponse([taskFixture({ id: "task-bad-date", title: "Bad date", due_date: "not-a-date" })])
    );
    renderPage("/tasks/next");

    expect(await screen.findByText("not-a-date")).toBeInTheDocument();
  });

  it("marks completed and cancelled rows as terminal instead of offering a checkbox", async () => {
    mocked.listTasks.mockImplementation(async () =>
      listResponse([
        taskFixture({ id: "task-done", title: "Done task", state: "completed" }),
        taskFixture({ id: "task-cancelled", title: "Cancelled task", state: "cancelled" })
      ])
    );
    renderPage("/tasks/next");

    expect(await screen.findByText("Done task")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Complete Done task" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Complete Cancelled task" })).not.toBeInTheDocument();
  });

  it("opens the detail route from a click anywhere on the row but not from its controls", async () => {
    const user = userEvent.setup();
    renderPage("/tasks/next");

    await user.click(await screen.findByRole("button", { name: "Complete Fix onboarding drop-off" }));
    await waitFor(() =>
      expect(mocked.transitionTask).toHaveBeenCalledWith(
        "task-1",
        { action: "complete", to_state: undefined, expected_revision: 4 },
        expect.stringContaining("task-shell-complete")
      )
    );
    expect(currentLocation()).toBe("/tasks/next");

    await user.click((screen.getByText("Fix onboarding drop-off").closest("article") as HTMLElement));
    expect(currentLocation()).toBe("/tasks/next/task-1");
  });

  it("reports a failed completion without losing the list", async () => {
    const user = userEvent.setup();
    mocked.transitionTask.mockRejectedValueOnce(new Error("Revision is stale."));
    renderPage("/tasks/next");

    await user.click(await screen.findByRole("button", { name: "Complete Fix onboarding drop-off" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Revision is stale.");
    expect(screen.getByText("Fix onboarding drop-off")).toBeInTheDocument();
  });
});

describe("TaskListPage capture", () => {
  // 012-FR-005 012-FR-013 012-FR-014 012-SC-006: Smart Add arbitration,
  // no pre-submit write, and safe OFF/dismiss behavior preserve capture.
  it("accepts a consented completion without writing, then submits once on the next Enter", async () => {
    act(() => {
      useAuthStore.setState({
        user: {
          id: "user-1",
          email: "max@example.test",
          feature_flags: { task_title_autocomplete: true }
        },
        status: "authed"
      });
    });
    const user = userEvent.setup();
    renderPage("/tasks/next");

    const field = await screen.findByRole("combobox", { name: "New task title" });
    await user.type(field, "Prepare launch notes");
    const consent = await screen.findByRole("checkbox", { name: /Allow deterministic/ });
    await user.click(consent);
    const listbox = await screen.findByRole("listbox", { name: "Task title suggestions" });
    expect(within(listbox).getAllByRole("option")).toHaveLength(3);

    await user.click(field);
    await user.keyboard("{Enter}");
    expect(field).toHaveValue("Prepare launch notes today");
    expect(mocked.createTask).not.toHaveBeenCalled();
    expect(mocked.smartAddTask).not.toHaveBeenCalled();
    expect(screen.queryByRole("listbox", { name: "Task title suggestions" })).not.toBeInTheDocument();

    await user.keyboard("{Enter}");
    await waitFor(() => expect(mocked.createTask).toHaveBeenCalledTimes(1));
    expect(mocked.recordTitleCompletionAccepted).toHaveBeenCalledWith(
      "8f3d2f73-0e55-4f47-9f9b-1a0b6c7a9c6e",
      1
    );
  });

  it("navigates completions upward and dismisses them with Escape without writing", async () => {
    act(() => {
      useAuthStore.setState({
        user: {
          id: "user-1",
          email: "max@example.test",
          feature_flags: { task_title_autocomplete: true }
        },
        status: "authed"
      });
    });
    const user = userEvent.setup();
    renderPage("/tasks/next");

    const field = await screen.findByRole("combobox", { name: "New task title" });
    await user.type(field, "Prepare launch notes");
    await user.click(await screen.findByRole("checkbox", { name: /Allow deterministic/ }));
    const listbox = await screen.findByRole("listbox", { name: "Task title suggestions" });

    await user.click(field);
    await user.keyboard("{ArrowDown}");
    expect(within(listbox).getAllByRole("option")[1]).toHaveAttribute("aria-selected", "true");
    await user.keyboard("{ArrowUp}");
    expect(within(listbox).getAllByRole("option")[0]).toHaveAttribute("aria-selected", "true");
    await user.keyboard("{ArrowUp}");
    expect(within(listbox).getAllByRole("option")[2]).toHaveAttribute("aria-selected", "true");
    await user.keyboard("{Escape}");

    expect(screen.queryByRole("listbox", { name: "Task title suggestions" })).not.toBeInTheDocument();
    expect(field).toHaveValue("Prepare launch notes");
    expect(mocked.createTask).not.toHaveBeenCalled();
    expect(mocked.smartAddTask).not.toHaveBeenCalled();
  });

  it("creates a plain task in the current list and clears the field", async () => {
    const user = userEvent.setup();
    renderPage("/tasks/next");

    const field = await screen.findByLabelText("New task title");
    await user.type(field, "Write the release note");
    await user.click(screen.getByRole("button", { name: "Add task" }));

    await waitFor(() =>
      expect(mocked.createTask).toHaveBeenCalledWith(
        { title: "Write the release note", state: "next" },
        expect.stringContaining("task-shell-create")
      )
    );
    await waitFor(() => expect(field).toHaveValue(""));
  });

  it("carries the project or tag context of the view into the created task", async () => {
    const user = userEvent.setup();
    const { unmount } = renderPage("/projects/project-launch");

    await user.type(await screen.findByLabelText("New task title"), "Project scoped");
    await user.keyboard("{Control>}{Enter}{/Control}");
    await waitFor(() =>
      expect(mocked.createTask).toHaveBeenCalledWith(
        { title: "Project scoped", state: "inbox", project_id: "project-launch" },
        expect.any(String)
      )
    );
    unmount();

    renderPage("/tags/tag-calls");
    await user.type(await screen.findByLabelText("New task title"), "Tag scoped");
    await user.keyboard("{Control>}{Enter}{/Control}");
    await waitFor(() =>
      expect(mocked.createTask).toHaveBeenCalledWith(
        { title: "Tag scoped", state: "inbox", tag_ids: ["tag-calls"] },
        expect.any(String)
      )
    );
  });

  it("requires who the task waits on before a waiting capture can be submitted", async () => {
    const user = userEvent.setup();
    renderPage("/tasks/waiting");

    await user.type(await screen.findByLabelText("New task title"), "Chase the invoice");
    const submit = screen.getByRole("button", { name: "Add task" });
    expect(submit).toBeDisabled();

    await user.keyboard("{Control>}{Enter}{/Control}");
    expect(mocked.createTask).not.toHaveBeenCalled();

    await user.type(screen.getByRole("textbox", { name: "Waiting for" }), "Finance");
    expect(submit).toBeEnabled();
    await user.click(submit);

    await waitFor(() =>
      expect(mocked.createTask).toHaveBeenCalledWith(
        { title: "Chase the invoice", state: "waiting", waiting_for: "Finance" },
        expect.any(String)
      )
    );
  });

  it("routes a capture carrying smart-add tokens through the smart-add endpoint", async () => {
    const user = userEvent.setup();
    renderPage("/tasks/next");

    await user.type(await screen.findByLabelText("New task title"), "Call the bank #calls ");
    expect(screen.getByLabelText("Smart Add classification chips")).toHaveTextContent("#calls");
    expect(screen.getByText("Title: “Call the bank”")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Add task" }));

    await waitFor(() =>
      expect(mocked.smartAddTask).toHaveBeenCalledWith(
        {
          title: "Call the bank",
          state: "next",
          project: null,
          tags: [{ id: "tag-calls" }]
        },
        expect.stringContaining("task-shell-smart-add")
      )
    );
  });

  it("suppresses autocomplete after a Smart Add token is completed and its popup closes", async () => {
    act(() => {
      useAuthStore.setState({
        user: {
          id: "user-1",
          email: "max@example.test",
          feature_flags: { task_title_autocomplete: true }
        },
        status: "authed"
      });
    });
    const user = userEvent.setup();
    renderPage("/tasks/next");

    const field = await screen.findByRole("combobox", { name: "New task title" });
    await user.type(field, "Prepare launch notes");
    await user.click(await screen.findByRole("checkbox", { name: /Allow deterministic/ }));
    await screen.findByRole("listbox", { name: "Task title suggestions" });
    mocked.generateTitleCompletions.mockClear();

    await user.type(field, " #calls ");

    expect(await screen.findByLabelText("Smart Add classification chips")).toHaveTextContent("#calls");
    expect(screen.queryByRole("listbox", { name: "Task title suggestions" })).not.toBeInTheDocument();
    await new Promise((resolve) => window.setTimeout(resolve, 400));
    expect(mocked.generateTitleCompletions).not.toHaveBeenCalled();
  });

  it("surfaces a rejected capture as an alert", async () => {
    const user = userEvent.setup();
    mocked.createTask.mockRejectedValueOnce(new Error("Title is too long."));
    renderPage("/tasks/next");

    await user.type(await screen.findByLabelText("New task title"), "Too much");
    await user.click(screen.getByRole("button", { name: "Add task" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Title is too long.");
  });

  it("hides the submit button until something is typed and refuses an all-token draft", async () => {
    const user = userEvent.setup();
    renderPage("/tasks/next");

    const field = await screen.findByLabelText("New task title");
    expect(screen.queryByRole("button", { name: "Add task" })).not.toBeInTheDocument();

    await user.type(field, "#calls ");
    expect(screen.getByRole("button", { name: "Add task" })).toBeDisabled();

    await user.keyboard("{Control>}{Enter}{/Control}");
    expect(mocked.smartAddTask).not.toHaveBeenCalled();
  });
});

describe("TaskListPage smart-add suggestions", () => {
  it("walks the suggestion list with the arrow keys and applies the selected one with Enter", async () => {
    const user = userEvent.setup();
    renderPage("/tasks/next");

    const field = await screen.findByLabelText("New task title");
    await user.type(field, "Ring back #");
    const listbox = await screen.findByRole("listbox");
    expect(within(listbox).getAllByRole("option")).toHaveLength(2);
    expect(field).toHaveAttribute("aria-expanded", "true");

    await user.keyboard("{ArrowDown}");
    expect(within(listbox).getAllByRole("option")[1]).toHaveAttribute("aria-selected", "true");

    // Wrapping in both directions keeps the keyboard model closed.
    await user.keyboard("{ArrowDown}");
    expect(within(listbox).getAllByRole("option")[0]).toHaveAttribute("aria-selected", "true");
    await user.keyboard("{ArrowUp}");
    expect(within(listbox).getAllByRole("option")[1]).toHaveAttribute("aria-selected", "true");

    await user.keyboard("{Enter}");
    await waitFor(() => expect(field).toHaveValue("Ring back #deep-work "));
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  });

  it("completes a suggestion with Tab and dismisses the list with Escape", async () => {
    const user = userEvent.setup();
    renderPage("/tasks/next");

    const field = await screen.findByLabelText("New task title");
    await user.type(field, "Ring back #cal");
    expect(await screen.findByRole("listbox")).toBeInTheDocument();

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();

    await user.type(field, "l");
    expect(await screen.findByRole("listbox")).toBeInTheDocument();
    await user.keyboard("{Tab}");
    await waitFor(() => expect(field).toHaveValue("Ring back #calls "));
  });

  it("applies a suggestion clicked with the pointer", async () => {
    const user = userEvent.setup();
    renderPage("/tasks/next");

    const field = await screen.findByLabelText("New task title");
    await user.type(field, "Plan the work @Launch");
    await user.click(await screen.findByRole("option", { name: /Launch v2/ }));

    // A name that is not a bare identifier round-trips through the quoted form.
    await waitFor(() => expect(field).toHaveValue('Plan the work @"Launch v2" '));
  });

  it("offers to create the entity a query does not match yet", async () => {
    const user = userEvent.setup();
    renderPage("/tasks/next");

    await user.type(await screen.findByLabelText("New task title"), "Buy milk #errands");
    expect(await screen.findByRole("option", { name: "Create #errands" })).toBeInTheDocument();

    await userEvent.setup().keyboard("{Enter}");
    await waitFor(() => expect(screen.getByLabelText("New task title")).toHaveValue("Buy milk #errands "));
  });
});

describe("TaskListPage detail wiring", () => {
  it("saves a detail edit and keeps the panel on the refreshed revision", async () => {
    const user = userEvent.setup();
    renderPage("/tasks/next/task-1");

    const title = await screen.findByLabelText("Title");
    await user.clear(title);
    await user.type(title, "Renamed task{Enter}");

    await waitFor(() =>
      expect(mocked.updateTask).toHaveBeenCalledWith(
        "task-1",
        { title: "Renamed task", expected_revision: 4 },
        expect.any(String)
      )
    );
  });

  it("serializes selected-row Complete behind the detail PATCH on the shared controller", async () => {
    const user = userEvent.setup();
    let resolvePatch: ((task: TaskResponse) => void) | undefined;
    const patch = new Promise<TaskResponse>((resolve) => { resolvePatch = resolve; });
    mocked.updateTask.mockReturnValueOnce(patch);
    mocked.transitionTask.mockImplementationOnce(async (_id, payload) => taskFixture({
      state: "completed",
      completed_at: "2026-07-15T11:00:00Z",
      revision: payload.expected_revision + 1
    }));

    renderPage("/tasks/next/task-1");
    const title = await screen.findByLabelText("Title");
    await user.clear(title);
    await user.type(title, "Renamed task{Enter}");
    await waitFor(() => expect(mocked.updateTask).toHaveBeenCalledWith(
      "task-1",
      { title: "Renamed task", expected_revision: 4 },
      expect.any(String)
    ));

    await user.click(await screen.findByRole("button", { name: "Complete Fix onboarding drop-off" }));
    expect(mocked.transitionTask).not.toHaveBeenCalled();

    resolvePatch?.(taskFixture({ title: "Renamed task", revision: 5 }));
    await waitFor(() => expect(mocked.transitionTask).toHaveBeenCalledWith(
      "task-1",
      { action: "complete", to_state: undefined, expected_revision: 5 },
      expect.any(String)
    ));
  });

  it("drives every detail action against the API", async () => {
    const user = userEvent.setup();
    mocked.getTask.mockImplementation(async () =>
      taskFixture({ subtasks: [{ id: "subtask-1", title: "Draft", state: "open", order_key: 1, revision: 2 }] })
    );
    renderPage("/tasks/next/task-1");

    await user.selectOptions(await screen.findByLabelText("List"), "someday");
    await waitFor(() =>
      expect(mocked.transitionTask).toHaveBeenCalledWith(
        "task-1",
        { action: "move", to_state: "someday", expected_revision: 4 },
        expect.any(String)
      )
    );

    await user.type(screen.getByLabelText("New subtask title"), "Second step{Enter}");
    await waitFor(() =>
      expect(mocked.createSubtask).toHaveBeenCalledWith(
        "task-1",
        { title: "Second step" },
        expect.stringContaining("task-shell-subtask-create")
      )
    );

    await user.click(screen.getByRole("button", { name: "Complete Draft" }));
    await waitFor(() =>
      expect(mocked.transitionSubtask).toHaveBeenCalledWith(
        "task-1",
        "subtask-1",
        { action: "complete", expected_revision: 2 },
        expect.stringContaining("task-shell-subtask-complete")
      )
    );

    await user.type(screen.getByLabelText("New comment"), "Blocked{Enter}");
    await waitFor(() =>
      expect(mocked.createComment).toHaveBeenCalledWith(
        "task-1",
        { body: "Blocked" },
        expect.stringContaining("task-shell-comment-create")
      )
    );
  });

  it("reports a failure from any detail action", async () => {
    const user = userEvent.setup();
    mocked.updateTask.mockRejectedValueOnce(new Error("Someone else edited this task."));
    renderPage("/tasks/next/task-1");

    await user.selectOptions(await screen.findByLabelText("Priority"), "high");

    expect(await screen.findByRole("alert")).toHaveTextContent("Someone else edited this task.");
  });

  it("reports a failed detail transition, subtask action or comment", async () => {
    const user = userEvent.setup();
    mocked.transitionTask.mockRejectedValueOnce(new Error("Transition rejected."));
    mocked.createSubtask.mockRejectedValueOnce(new Error("Subtask rejected."));
    mocked.createComment.mockRejectedValueOnce(new Error("Comment rejected."));
    mocked.transitionSubtask.mockRejectedValueOnce(new Error("Subtask transition rejected."));
    mocked.getTask.mockImplementation(async () =>
      taskFixture({ subtasks: [{ id: "subtask-1", title: "Draft", state: "open", order_key: 1, revision: 2 }] })
    );
    renderPage("/tasks/next/task-1");

    await user.selectOptions(await screen.findByLabelText("List"), "someday");
    expect(await screen.findByText(/Transition rejected\./)).toBeInTheDocument();

    await user.type(screen.getByLabelText("New subtask title"), "Second step{Enter}");
    await waitFor(() => expect(screen.getByText("Subtask rejected.")).toBeInTheDocument());

    await user.click(screen.getByRole("button", { name: "Complete Draft" }));
    await waitFor(() => expect(screen.getByText("Subtask transition rejected.")).toBeInTheDocument());

    await user.type(screen.getByLabelText("New comment"), "Blocked{Enter}");
    await waitFor(() => expect(screen.getByText("Comment rejected.")).toBeInTheDocument());
  });

  it("shows the empty panel with no task selected and closes the open one back to the list", async () => {
    const user = userEvent.setup();
    const { unmount } = renderPage("/tasks/next");
    expect(await screen.findByRole("complementary", { name: "Task detail" })).toBeInTheDocument();
    unmount();

    renderPage("/tasks/next/task-1");
    await user.click(await screen.findByRole("button", { name: "Close" }));
    expect(currentLocation()).toBe("/tasks/next");
  });

  it("returns focus to the row that opened the panel, or to the heading when that row is gone", async () => {
    const user = userEvent.setup();
    const { unmount } = renderPage("/tasks/next");

    await user.click(await screen.findByRole("link", { name: "Fix onboarding drop-off" }));
    expect(currentLocation()).toBe("/tasks/next/task-1");
    await user.click(screen.getByRole("button", { name: "Close" }));
    await waitFor(() => expect(screen.getByRole("link", { name: "Fix onboarding drop-off" })).toHaveFocus());
    unmount();

    // A task opened by URL that the current list does not contain has no row to
    // return to, so focus lands on the list heading instead of nowhere.
    mocked.listTasks.mockImplementation(async () =>
      listResponse([taskFixture({ id: "task-other", title: "Some other task" })])
    );
    renderPage("/tasks/next/task-1");
    await user.click(await screen.findByRole("button", { name: "Close" }));

    await waitFor(() => expect(screen.getByRole("heading", { level: 1, name: "Next actions" })).toHaveFocus());
  });

  it("toggles the whole panel with the keyboard shortcut", async () => {
    const user = userEvent.setup();
    renderPage("/tasks/next/task-1");

    expect(await screen.findByLabelText("Title")).toBeInTheDocument();

    await user.keyboard("{Meta>}\\{/Meta}");
    await waitFor(() => expect(screen.queryByLabelText("Title")).not.toBeInTheDocument());

    await user.keyboard("{Control>}\\{/Control}");
    expect(await screen.findByLabelText("Title")).toBeInTheDocument();
  });

  it("deselects the task on Escape unless a field or a modal owns the key", async () => {
    const user = userEvent.setup();
    renderPage("/tasks/next/task-1");

    await user.click(await screen.findByLabelText("Details"));
    await user.keyboard("{Escape}");
    expect(currentLocation()).toBe("/tasks/next/task-1");

    await user.click(screen.getByRole("heading", { level: 1, name: "Next actions" }));
    await user.keyboard("{Escape}");
    await waitFor(() => expect(currentLocation()).toBe("/tasks/next"));

    // With nothing selected the key is inert rather than navigating again.
    await user.keyboard("{Escape}");
    expect(currentLocation()).toBe("/tasks/next");
  });

  it("keeps the selection while a modal dialog is open", async () => {
    const user = userEvent.setup();
    renderPage("/tasks/next/task-1");
    await screen.findByLabelText("Title");

    const modal = document.createElement("div");
    modal.setAttribute("role", "dialog");
    modal.setAttribute("aria-modal", "true");
    document.body.append(modal);
    try {
      await user.keyboard("{Escape}");
      expect(currentLocation()).toBe("/tasks/next/task-1");
    } finally {
      modal.remove();
    }
  });

  it("surfaces a failed detail fetch inside the panel", async () => {
    mocked.getTask.mockRejectedValue(new Error("Task detail is unavailable."));
    renderPage("/tasks/next/task-1");

    expect(await screen.findByText("Task detail is unavailable.")).toBeInTheDocument();
  });
});

describe("TaskListPage sidebar mutations", () => {
  it("creates, renames and archives projects, leaving an archived project's view", async () => {
    const user = userEvent.setup();
    renderPage("/projects/project-launch");

    await user.click(await screen.findByRole("button", { name: "New project" }));
    await user.type(screen.getByLabelText("New project name"), "Client work{Enter}");
    await waitFor(() =>
      expect(mocked.createProject).toHaveBeenCalledWith({ name: "Client work" }, expect.stringContaining("create-project"))
    );

    await user.click(screen.getByRole("button", { name: "Project options Launch v2" }));
    await user.clear(screen.getByLabelText("Project name Launch v2"));
    await user.type(screen.getByLabelText("Project name Launch v2"), "Launch v3{Enter}");
    await waitFor(() =>
      expect(mocked.updateProject).toHaveBeenCalledWith(
        "project-launch",
        { name: "Launch v3", expected_revision: 3 },
        expect.stringContaining("rename-project")
      )
    );

    await user.click(screen.getByRole("button", { name: "Project options Launch v2" }));
    await user.click(screen.getByRole("button", { name: "Archive" }));
    await waitFor(() => expect(mocked.archiveProject).toHaveBeenCalledWith("project-launch", 3, expect.any(String)));
    await waitFor(() => expect(currentLocation()).toBe("/tasks/next"));
  });

  it("creates, renames and deletes tags, leaving a deleted tag's view", async () => {
    const user = userEvent.setup();
    renderPage("/tags/tag-calls");

    await user.click(await screen.findByRole("button", { name: "New tag" }));
    await user.type(screen.getByLabelText("New tag name"), "errands{Enter}");
    await waitFor(() =>
      expect(mocked.createTag).toHaveBeenCalledWith({ name: "errands" }, expect.stringContaining("create-tag"))
    );

    await user.click(screen.getByRole("button", { name: "Tag options deep-work" }));
    await user.clear(screen.getByLabelText("Tag name deep-work"));
    await user.type(screen.getByLabelText("Tag name deep-work"), "focus{Enter}");
    await waitFor(() =>
      expect(mocked.updateTag).toHaveBeenCalledWith(
        "tag-deep-work",
        { name: "focus", expected_revision: 1 },
        expect.stringContaining("rename-tag")
      )
    );

    await user.click(screen.getByRole("button", { name: "Tag options @calls" }));
    await user.click(screen.getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(mocked.deleteTag).toHaveBeenCalledWith("tag-calls", 2, expect.any(String)));
    await waitFor(() => expect(currentLocation()).toBe("/tasks/next"));
  });

  it("stays on the current view when some other project or tag is archived or deleted", async () => {
    const user = userEvent.setup();
    renderPage("/projects/project-launch");

    await user.click(await screen.findByRole("button", { name: "Project options Onboarding drop-off" }));
    await user.click(screen.getByRole("button", { name: "Archive" }));
    await waitFor(() => expect(mocked.archiveProject).toHaveBeenCalledWith("project-onboarding", 1, expect.any(String)));
    expect(currentLocation()).toBe("/projects/project-launch");

    await user.click(screen.getByRole("button", { name: "Tag options deep-work" }));
    await user.click(screen.getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(mocked.deleteTag).toHaveBeenCalledWith("tag-deep-work", 1, expect.any(String)));
    expect(currentLocation()).toBe("/projects/project-launch");
  });

  it("reports a rejected project or tag write", async () => {
    const user = userEvent.setup();
    mocked.createProject.mockRejectedValueOnce(new Error("Project name is taken."));
    mocked.createTag.mockRejectedValueOnce(new Error("Tag name is taken."));
    renderPage("/tasks/next");

    await user.click(await screen.findByRole("button", { name: "New project" }));
    await user.type(screen.getByLabelText("New project name"), "Launch v2{Enter}");
    expect(await screen.findByRole("alert")).toHaveTextContent("Project name is taken.");

    await user.click(screen.getByRole("button", { name: "New tag" }));
    await user.type(screen.getByLabelText("New tag name"), "calls{Enter}");
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Tag name is taken."));
  });
});

describe("TaskListPage canonical Discard paths", () => {
  it("retries an unselected row-completion conflict from the list alert", async () => {
    const user = userEvent.setup();
    const stale = taskFixture({ title: "Retry row", state: "next", revision: 4 });
    const canonical = taskFixture({ title: "Retry row", state: "next", revision: 5 });
    mocked.listTasks.mockImplementation(async () => listResponse([stale]));
    mocked.transitionTask
      .mockRejectedValueOnce(new ApiError("stale", 409, {}))
      .mockResolvedValueOnce(taskFixture({
        title: "Retry row",
        state: "completed",
        completed_at: "2026-07-15T11:00:00Z",
        revision: 6
      }));
    mocked.getTask.mockResolvedValueOnce(canonical);

    renderPage("/tasks/next");
    await user.click((await screen.findAllByRole("button", { name: /^Complete / }))[0]);
    const warning = await screen.findByRole("alert");
    await user.click(within(warning).getByRole("button", { name: "Retry" }));

    await waitFor(() => expect(mocked.transitionTask).toHaveBeenCalledTimes(2));
    expect(await screen.findByText("Saved", {}, { timeout: 3000 })).toBeInTheDocument();
  });

  it("discards an unselected row-completion conflict and converges canonical list state", async () => {
    const user = userEvent.setup();
    const stale = taskFixture({ title: "Stale row", state: "next", revision: 4 });
    const canonical = taskFixture({ title: "Canonical row", state: "next", revision: 5 });
    mocked.transitionTask.mockRejectedValueOnce(new ApiError("stale", 409, {}));
    mocked.getTask.mockResolvedValueOnce(canonical);
    let nextListCalls = 0;
    let resolveCanonicalList: ((response: TaskListResponse) => void) | undefined;
    const canonicalList = new Promise<TaskListResponse>((resolve) => { resolveCanonicalList = resolve; });
    mocked.listTasks.mockImplementation(async (filters) => {
      if (filters?.limit) return listResponse([stale]);
      nextListCalls += 1;
      return nextListCalls === 1 ? listResponse([stale], {
        counts_by_state: { inbox: 17, next: 1, waiting: 3, someday: 0 }
      }) : canonicalList;
    });

    renderPage("/tasks/next");
    await user.click((await screen.findAllByRole("button", { name: /^Complete / }))[0]);
    const warning = await screen.findByRole("alert");
    expect(warning).toHaveTextContent("Task changed elsewhere");
    fireEvent.click(within(warning).getByRole("button", { name: "Discard" }));
    await waitFor(() => expect(screen.getByRole("link", { name: "Canonical row" })).toBeInTheDocument());
    resolveCanonicalList?.(listResponse([canonical], {
      counts_by_state: { inbox: 17, next: 2, waiting: 3, someday: 0 }
    }));

    await waitFor(() => {
      expect(screen.queryByRole("alert")).not.toBeInTheDocument();
      expect(screen.getByRole("link", { name: "Canonical row" })).toBeInTheDocument();
      expect(screen.getByText("2 tasks")).toBeInTheDocument();
    });
    expect(mocked.getTask).toHaveBeenCalledWith("task-1");
  });

  it("conflict Discard restores canonical fields without remount or focus regression", async () => {
    const user = userEvent.setup();
    mocked.updateTask.mockRejectedValue(new ApiError("stale", 409, {}));
    mocked.getTask.mockResolvedValue(taskFixture({
      state: "waiting", waiting_for: "Canonical owner", waiting_since: "2026-01-01T00:00:00Z",
      details: "Canonical details", revision: 5
    }));
    let waitingListCalls = 0;
    let resolveCanonicalList: ((response: TaskListResponse) => void) | undefined;
    const canonicalList = new Promise<TaskListResponse>((resolve) => { resolveCanonicalList = resolve; });
    mocked.listTasks.mockImplementation(async (filters) => filters?.state === "waiting"
      ? (++waitingListCalls === 1
        ? listResponse([taskFixture({ title: "Pre-discard waiting row", state: "waiting", waiting_for: "Old owner" })], { counts_by_state: { inbox: 1, next: 1, waiting: 2, someday: 1 } })
        : canonicalList)
      : listResponse([taskFixture()]));
    renderPage("/tasks/waiting/task-1");
    const title = await screen.findByLabelText("Title");
    await user.clear(title); await user.type(title, "Dirty title");
    await user.clear(screen.getByLabelText("Details")); await user.type(screen.getByLabelText("Details"), "Dirty details");
    const panel = screen.getByRole("complementary", { name: "Task detail" });
    const waitingFor = within(panel).getByLabelText("Waiting for");
    await user.clear(waitingFor); await user.type(waitingFor, "Dirty owner"); await user.tab();
    title.focus();
    const titleNode = title;
    fireEvent.click(await screen.findByRole("button", { name: "Discard my edits" }));
    fireEvent.click(screen.getByRole("button", { name: "Discard" }));
    await waitFor(() => expect(screen.getByRole("link", { name: "Fix onboarding drop-off" })).toBeInTheDocument());
    resolveCanonicalList?.(listResponse([taskFixture({ title: "Fix onboarding drop-off", state: "waiting", waiting_for: "Canonical owner" })], { counts_by_state: { inbox: 1, next: 1, waiting: 4, someday: 1 } }));
    const conflictPanel = await screen.findByRole("complementary", { name: "Task detail" });
    await waitFor(() => {
      expect(within(conflictPanel).getByLabelText("Title")).toHaveValue("Fix onboarding drop-off");
      expect(within(conflictPanel).getByLabelText("Details")).toHaveValue("Canonical details");
      expect(within(conflictPanel).getByLabelText("Waiting for")).toHaveValue("Canonical owner");
      expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    });
    expect(screen.getByText("4 tasks")).toBeInTheDocument();
    expect(screen.getByLabelText("Title")).toBe(titleNode);
    expect(document.activeElement).toBe(titleNode);
  });

  it("recovery-only Discard restores canonical fields without remount or focus regression", async () => {
    const user = userEvent.setup();
    mocked.getTask.mockResolvedValue(taskFixture({
      title: "Canonical recovery title", details: "Canonical recovery details", state: "waiting",
      waiting_for: "Canonical recovery owner", waiting_since: "2026-01-01T00:00:00Z", revision: 5
    }));
    let waitingListCalls = 0;
    mocked.listTasks.mockImplementation(async (filters) => filters?.state === "waiting"
      ? (++waitingListCalls === 1
        ? listResponse([taskFixture({ title: "Pre-discard recovery row", state: "waiting", waiting_for: "Old recovery owner" })], { counts_by_state: { inbox: 17, next: 3, waiting: 2, someday: 0 } })
        : listResponse([taskFixture({ title: "Canonical recovery title", state: "waiting", waiting_for: "Canonical recovery owner" })], { counts_by_state: { inbox: 17, next: 3, waiting: 5, someday: 0 } }))
      : listResponse([taskFixture()]));
    const apiOrigin = new URL("/api", window.location.origin).href.replace(/\/$/, "");
    const recoveryKey = taskAutosaveStorageKey("user-1", apiOrigin, "task-1");
    const baseline = taskFixture({ state: "waiting", waiting_for: "Old recovery owner", waiting_since: "2026-01-01T00:00:00Z" });
    sessionStorage.setItem(recoveryKey, JSON.stringify({
      version: 1,
      identity: { accountId: "user-1", apiOrigin, taskId: "task-1" },
      baseline,
      draft: { title: "Recovered title", details: "Recovered details", state: "waiting", project_id: baseline.project_id, priority: baseline.priority, tag_ids: baseline.tag_ids, waiting_for: "Recovered owner", due_date: baseline.due_date },
      dirty: {
        title: { baseValue: baseline.title, generation: 1, value: "Recovered title" },
        details: { baseValue: baseline.details, generation: 1, value: "Recovered details" },
        waiting_for: { baseValue: baseline.waiting_for, generation: 1, value: "Recovered owner" }
      },
      inFlight: { kind: "patch", body: { title: "Recovered title", details: "Recovered details", waiting_for: "Recovered owner", expected_revision: 4 }, generations: { title: 1, details: 1, waiting_for: 1 }, idempotencyKey: "autosave-recovery-test", attempt: 1 },
      barriers: [], status: "failed", conflict: null,
      error: { kind: "network", message: "offline", retryAllowed: true, offline: true }, retrying: false
    }));
    renderPage("/tasks/waiting/task-1");
    const title = await screen.findByLabelText("Title");
    fireEvent.change(title, { target: { value: "Dirty title" } });
    fireEvent.change(screen.getByLabelText("Details"), { target: { value: "Dirty details" } });
    const panel = screen.getByRole("complementary", { name: "Task detail" });
    fireEvent.change(within(panel).getByLabelText("Waiting for"), { target: { value: "Dirty owner" } });
    const titleNode = title;
    const discard = await screen.findByRole("button", { name: "Discard" });
    fireEvent.mouseDown(discard);
    discard.focus();
    await user.keyboard("{Enter}");
    const recoveryPanel = await screen.findByRole("complementary", { name: "Task detail" });
    await waitFor(() => {
      expect(within(recoveryPanel).getByLabelText("Title")).toHaveValue("Canonical recovery title");
      expect(within(recoveryPanel).getByLabelText("Details")).toHaveValue("Canonical recovery details");
      expect(within(recoveryPanel).getByLabelText("Waiting for")).toHaveValue("Canonical recovery owner");
      expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    });
    expect(screen.getByRole("link", { name: "Canonical recovery title" })).toBeInTheDocument();
    expect(screen.getByText("5 tasks")).toBeInTheDocument();
    expect(sessionStorage.getItem(recoveryKey)).toBeNull();
    expect(screen.getByLabelText("Title")).toBe(titleNode);
    expect(document.activeElement).toBe(screen.getByRole("heading", { name: "Task detail" }));
  });

  it("retries a persisted failed edit from the list alert", async () => {
    const user = userEvent.setup();
    const apiOrigin = new URL("/api", window.location.origin).href.replace(/\/$/, "");
    const recoveryKey = taskAutosaveStorageKey("user-1", apiOrigin, "task-1");
    const baseline = taskFixture();
    sessionStorage.setItem(recoveryKey, JSON.stringify({
      version: 1,
      identity: { accountId: "user-1", apiOrigin, taskId: "task-1" },
      baseline,
      draft: {
        title: "Recovered title",
        details: baseline.details,
        state: baseline.state,
        project_id: baseline.project_id,
        priority: baseline.priority,
        tag_ids: baseline.tag_ids,
        waiting_for: baseline.waiting_for,
        due_date: baseline.due_date
      },
      dirty: {
        title: { baseValue: baseline.title, generation: 1, value: "Recovered title" }
      },
      inFlight: {
        kind: "patch",
        body: { title: "Recovered title", expected_revision: baseline.revision },
        generations: { title: 1 },
        idempotencyKey: "autosave-recovery-retry-test",
        attempt: 1
      },
      barriers: [],
      status: "failed",
      conflict: null,
      error: { kind: "network", message: "offline", retryAllowed: true, offline: true },
      retrying: false
    }));
    mocked.updateTask
      .mockRejectedValueOnce(new TypeError("offline"))
      .mockResolvedValueOnce(taskFixture({ title: "Recovered title", revision: 5 }));

    renderPage("/tasks/next/task-1");
    const recoveredMessage = await screen.findByText("Unsaved task change recovered. Retry or Discard.");
    const warning = recoveredMessage.closest('[role="alert"]');
    if (!(warning instanceof HTMLElement)) throw new Error("Recovery alert was not rendered");
    await user.click(within(warning).getByRole("button", { name: "Retry" }));

    await waitFor(() => expect(mocked.updateTask).toHaveBeenCalledTimes(2));
    expect(await screen.findByText("Saved", {}, { timeout: 3000 })).toBeInTheDocument();
    expect(screen.getByLabelText("Title")).toHaveValue("Recovered title");
    await waitFor(() => expect(sessionStorage.getItem(recoveryKey)).toBeNull());
  });

  it("keeps detail fallback controls inert when the account controller disappears", async () => {
    renderPage("/tasks/next/task-1");
    const title = await screen.findByLabelText("Title");
    act(() => {
      useAuthStore.setState({ user: null, status: "authed" });
    });

    fireEvent.change(title, { target: { value: "Local only" } });
    fireEvent.blur(title);
    fireEvent.click(screen.getByRole("button", { name: "Complete task" }));
    fireEvent.click(screen.getByRole("button", { name: "Complete Fix onboarding drop-off" }));

    expect(mocked.updateTask).not.toHaveBeenCalled();
    expect(mocked.transitionTask).not.toHaveBeenCalled();
  });
});
