import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, apiClient } from "../../../api/client";
import { taskKeys } from "../../../api/taskHooks";
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
      listAgentConnections: vi.fn(),
      listAgentRunSummaries: vi.fn(),
      listAgentRuns: vi.fn(),
      previewAgentHandoff: vi.fn(),
      confirmAgentHandoff: vi.fn()
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
const renderedTaskRows = () => screen.getAllByRole("listitem").filter((row) => row.tagName === "ARTICLE");

function renderPage(initialEntry = "/tasks/next", client = new QueryClient({ defaultOptions: { queries: { retry: false } } })) {
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
  vi.stubGlobal("matchMedia", vi.fn(() => ({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() })));
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
  mocked.listAgentConnections.mockResolvedValue([]);
  mocked.listAgentRunSummaries.mockResolvedValue({});
  mocked.listAgentRuns.mockResolvedValue([]);
  mocked.previewAgentHandoff.mockResolvedValue({
    token: "a".repeat(64),
    run_id: "run-row",
    task_id: "task-1",
    connection_id: "agent-hermes",
    agent_name: "Hermes",
    title: "Fix onboarding drop-off",
    details: null,
    supporting_items: [],
    message_id: "run-row:start",
    correlation_id: "run-row",
    destination_interface: "https://hermes.example.test/a2a",
    protocol_version: "1.0",
    guarantee_tier: "guaranteed",
    tier_disclosure: "Guaranteed single start.",
    tier_disclosure_url: "https://example.test/guarantee",
    acknowledgement_required: false,
    cancellation_disclosure: "Cancellation is supported.",
    push_callback: null,
    external_copy_notice: "The agent keeps its own copy.",
    reauthentication_required: false,
    parts_preview: ["Fix onboarding drop-off"]
  });
  mocked.confirmAgentHandoff.mockResolvedValue({
    id: "run-row",
    task_id: "task-1",
    connection_id: "agent-hermes"
  } as Awaited<ReturnType<typeof apiClient.confirmAgentHandoff>>);
});

afterEach(() => {
  vi.unstubAllGlobals();
  resetTaskDetailAutosaveControllersForTests();
  sessionStorage.clear();
  vi.clearAllMocks();
  act(() => {
    useAuthStore.setState({ user: null, status: "loading" });
  });
});

describe("TaskListPage projections", () => {
  it("017-FR-014 017-FR-015 shows existing runs through the existing summary read while rollout is off", async () => {
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
        last_contact_at: "2026-08-11T12:00:00Z",
        guarantee_tier: "guaranteed",
        cancel_outcome: "none",
        agent_task_missing: false
      },
      "task-2": {
        id: "agentrun-2",
        task_id: "task-2",
        agent_name: "Hermes",
        primary_state_label: "Needs you",
        needs_user: true,
        stopped_reporting: false,
        last_contact_at: "2026-08-11T12:01:00Z",
        guarantee_tier: "best_effort",
        cancel_outcome: "not_cancelable",
        agent_task_missing: false
      }
    });

    renderPage();

    // D-03-S21: the compact row states the tier in full beside the label, and
    // repeats a withdrawn cancellation, so the list and the detail cannot
    // disagree about what the user may still do.
    expect(
      await screen.findByRole("button", { name: /Hermes.*Running.*Guaranteed single start/i })
    ).toHaveClass("w-[184px]");
    expect(
      screen.getByRole("button", { name: /Hermes.*Needs you.*Best-effort single start.*Cancellation not supported/i })
    ).toHaveClass("w-[184px]");
    expect(mocked.listAgentRunSummaries).toHaveBeenCalledWith(
      ["task-1", "task-2"],
      expect.any(AbortSignal)
    );
    expect(mocked.listAgentConnections).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: /Choose agent/i })).not.toBeInTheDocument();
  });

  it("keeps a cached agent status readable when refresh fails and retries without reopening an already selected row", async () => {
    const user = userEvent.setup();
    const summary = {
      "task-1": {
        id: "agentrun-1",
        task_id: "task-1",
        agent_name: "Hermes",
        primary_state_label: "Running",
        needs_user: false,
        stopped_reporting: false,
        last_contact_at: "2026-08-11T12:00:00Z",
        guarantee_tier: "guaranteed",
        cancel_outcome: "none",
        agent_task_missing: false
      }
    } as Awaited<ReturnType<typeof apiClient.listAgentRunSummaries>>;
    mocked.listAgentRunSummaries.mockResolvedValue(summary);
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    renderPage("/tasks/next/task-1?group=off", client);

    const assigned = await screen.findByRole("button", { name: /Hermes.*Running.*Guaranteed single start/i });
    await user.click(assigned);
    expect(currentLocation()).toBe("/tasks/next/task-1?group=off");

    mocked.listAgentRunSummaries.mockRejectedValueOnce(new Error("Status refresh unavailable."));
    await act(async () => {
      await client.invalidateQueries({ queryKey: ["agents"] });
    });
    expect(await screen.findByText("Agent statuses may be out of date.")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(screen.queryByText("Agent statuses may be out of date.")).not.toBeInTheDocument());
    expect(screen.getByRole("button", { name: /Hermes.*Running.*Guaranteed single start/i })).toBeInTheDocument();
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

  it("distinguishes an empty Inbox from no search matches and clears only the search filter", async () => {
    mocked.listTasks.mockResolvedValue(listResponse([], {
      counts_by_state: { inbox: 0, next: 0, waiting: 0, someday: 0 }
    }));
    const emptyInbox = renderPage("/tasks/inbox");
    expect(await screen.findByText("Inbox is clear")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Clear search" })).not.toBeInTheDocument();
    emptyInbox.unmount();

    mocked.listTasks.mockImplementation(async (filters) => listResponse(
      filters?.q ? [] : [taskFixture({ state: "inbox", project_id: null })],
      { counts_by_state: { inbox: filters?.q ? 0 : 9, next: 0, waiting: 0, someday: 0 } }
    ));
    renderPage("/tasks/inbox?sort=due&group=off&q=no+matching+task");
    expect(await screen.findByText("No tasks match your search")).toBeInTheDocument();
    expect(screen.queryByText("Inbox is clear")).not.toBeInTheDocument();
    expect(screen.queryByText(/Use Brain dump when you are ready/)).not.toBeInTheDocument();

    const user = userEvent.setup();
    screen.getByRole("button", { name: "Clear search" }).focus();
    await user.keyboard("{Enter}");

    expect(currentLocation()).toBe("/tasks/inbox?sort=due&group=off");
    expect(await screen.findByRole("link", { name: "Fix onboarding drop-off" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1, name: "Inbox" })).toHaveFocus();
    expect(screen.queryByText("No tasks match your search")).not.toBeInTheDocument();
    expect(screen.getByRole("searchbox", { name: "Search tasks" })).toHaveValue("");
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
  it("moves grouping, sorting and cancelled history through the URL and the query", async () => {
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

    await user.click(screen.getByRole("checkbox", { name: "Show cancelled" }));
    await waitFor(() => expect(lastListFilters().includeCompleted).toBe(true));
    expect(lastListFilters().includeCancelled).toBe(true);
    await user.click(screen.getByRole("checkbox", { name: "Show cancelled" }));
    await waitFor(() => expect(lastListFilters().includeCancelled).toBe(false));
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
  it("017-FR-001 017-FR-002 renders a flat 44px header with tags but no project label", async () => {
    mocked.listTasks.mockImplementation(async () => listResponse([taskFixture()]));
    renderPage("/tasks/next?group=off");

    const row = (await screen.findByRole("link", { name: "Fix onboarding drop-off" })).closest("article") as HTMLElement;
    const header = within(row).getByTestId("task-row-header");
    expect(header).toHaveClass("h-11");
    expect(row).not.toHaveClass("rounded-[12px]");
    expect(within(row).getByText("#deep-work")).toBeInTheDocument();
    expect(within(row).queryByText("Launch v2")).not.toBeInTheDocument();
  });

  it("017-FR-004 017-FR-005 opens detail inline and uses the URL as collapse-only state", async () => {
    const user = userEvent.setup();
    renderPage("/tasks/next/task-1?group=off");

    const title = await screen.findByLabelText("Title");
    const row = screen.getByRole("link", { name: "Fix onboarding drop-off" }).closest("article") as HTMLElement;
    expect(row).toContainElement(title);
    expect(screen.getByRole("complementary", { name: "Task detail" })).toBeInTheDocument();
    expect(screen.queryByRole("dialog", { name: "Task detail" })).not.toBeInTheDocument();

    await user.click(screen.getByLabelText("Details"));
    expect(currentLocation()).toBe("/tasks/next/task-1?group=off");

    await user.click(screen.getByRole("link", { name: "Fix onboarding drop-off" }));
    expect(currentLocation()).toBe("/tasks/next?group=off");
    await user.click(within(row).getByTestId("task-row-header"));
    expect(currentLocation()).toBe("/tasks/next/task-1?group=off");

    await user.click(await screen.findByLabelText("List"));
    await user.keyboard("{Escape}");
    expect(currentLocation()).toBe("/tasks/next/task-1?group=off");

    await user.click(within(row).getByTestId("task-row-header"));
    expect(currentLocation()).toBe("/tasks/next?group=off");
    expect(screen.queryByLabelText("Title")).not.toBeInTheDocument();

    await user.keyboard("{Control>}\\{/Control}");
    expect(currentLocation()).toBe("/tasks/next?group=off");
  });

  it("017-FR-010 017-FR-011 aligns row agent controls, reviews first, then focuses the confirmed run", async () => {
    const user = userEvent.setup();
    act(() => {
      useAuthStore.setState({
        user: {
          id: "user-1",
          email: "max@example.test",
          feature_flags: { external_agent_relay: true }
        },
        status: "authed"
      });
    });
    mocked.listAgentConnections.mockResolvedValue([
      {
        id: "agent-hermes",
        name: "Hermes",
        agent_address: "https://hermes.example.test/a2a",
        status: "ready",
        stale: false,
        ready_for_handoff: true
      } as Awaited<ReturnType<typeof apiClient.listAgentConnections>>[number]
    ]);
    let dispatched = false;
    mocked.listAgentRunSummaries.mockImplementation(async () => (dispatched ? {
      "task-1": {
        id: "run-row",
        task_id: "task-1",
        agent_name: "Hermes",
        primary_state_label: "Queued",
        needs_user: false,
        stopped_reporting: false,
        last_contact_at: null,
        guarantee_tier: "guaranteed",
        cancel_outcome: "none",
        agent_task_missing: false
      }
    } : {}) as Awaited<ReturnType<typeof apiClient.listAgentRunSummaries>>);
    mocked.confirmAgentHandoff.mockImplementation(async () => {
      dispatched = true;
      return {
        id: "run-row",
        task_id: "task-1",
        connection_id: "agent-hermes"
      } as Awaited<ReturnType<typeof apiClient.confirmAgentHandoff>>;
    });
    renderPage("/tasks/next?group=off");

    const handoff = await screen.findByRole("button", { name: "Hand Fix onboarding drop-off to Hermes" });
    await user.click(handoff);
    expect(await screen.findByRole("dialog", { name: "Hand this task to an agent" })).toBeInTheDocument();
    expect(currentLocation()).toBe("/tasks/next?group=off");
    expect(mocked.confirmAgentHandoff).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("dialog", { name: "Hand this task to an agent" })).not.toBeInTheDocument();

    await user.click(handoff);
    expect(await screen.findByRole("heading", { name: "What will be sent" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Send to agent" }));
    const assigned = await screen.findByRole("button", { name: /Hermes.*Queued.*Guaranteed single start/i });
    await waitFor(() => expect(assigned).toHaveFocus());
    await user.click(assigned);
    expect(await screen.findByLabelText("Title")).toHaveValue("Fix onboarding drop-off");
  });

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

    await user.click(within(screen.getByText("Fix onboarding drop-off").closest("article") as HTMLElement).getByTestId("task-row-header"));
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

describe("016 completed task presentation", () => {
  it.each(["/tasks/next", "/projects/project-launch", "/tags/tag-deep-work", "/tasks/next?q=shared", "/tasks/today"])(
    "016-FR-001 016-SC-001 016-SC-003 includes completed work after all open groups in %s",
    async (route) => {
      mocked.listTasks.mockImplementation(async () => listResponse([
        taskFixture({ id: "done", title: "Finished shared task", state: "completed" }),
        taskFixture({ id: "open-b", title: "Second open group", project_id: "project-onboarding" }),
        taskFixture({ id: "open-a", title: "First open group" })
      ], { counts_by_state: { inbox: 0, next: 2, waiting: 0, someday: 0 } }));
      renderPage(route);
      await screen.findByText("Finished shared task");
      expect(lastListFilters()).toMatchObject({ includeCompleted: true, includeCancelled: false });
      const rows = renderedTaskRows();
      expect(rows[rows.length - 1]).toHaveTextContent("Finished shared task");
      expect(screen.getAllByRole("heading", { name: "Completed" })).toHaveLength(1);
      const completed = screen.getByRole("list", { name: "Completed" });
      expect(within(completed).getAllByRole("listitem")).toHaveLength(1);
      expect(within(completed).getByRole("link", { name: "Finished shared task" })).toHaveClass("text-slate-500", "line-through");
      expect(within(completed).getByRole("listitem").className).not.toMatch(/opacity-/);
      expect(screen.getByText("2 tasks")).toBeInTheDocument();
    }
  );

  it("places the task creator after active tasks and before Completed", async () => {
    mocked.listTasks.mockResolvedValue(listResponse([
      taskFixture({ id: "active", title: "Active task" }),
      taskFixture({ id: "done", title: "Completed task", state: "completed" })
    ]));
    renderPage("/tasks/next");

    const active = await screen.findByRole("link", { name: "Active task" });
    const creator = screen.getByRole("combobox", { name: "New task title" }).closest("form");
    const completed = screen.getByRole("heading", { name: "Completed" });
    if (!creator) {
      throw new Error("Task creator form is missing");
    }
    expect(active.compareDocumentPosition(creator)).toBe(Node.DOCUMENT_POSITION_FOLLOWING);
    expect(creator.compareDocumentPosition(completed)).toBe(Node.DOCUMENT_POSITION_FOLLOWING);
  });

  it("016-FR-001 separates opt-in cancelled history and omits empty terminal headings", async () => {
    mocked.listTasks.mockImplementation(async (filters) => listResponse([
      taskFixture(),
      ...(filters?.includeCancelled ? [taskFixture({ id: "cancelled", title: "Cancelled history", state: "cancelled" })] : [])
    ]));
    renderPage();
    await screen.findByText("Fix onboarding drop-off");
    expect(screen.queryByRole("heading", { name: "Completed" })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Cancelled" })).not.toBeInTheDocument();
    await userEvent.setup().click(screen.getByRole("checkbox", { name: "Show cancelled" }));
    expect(await screen.findByRole("list", { name: "Cancelled" })).toHaveTextContent("Cancelled history");
    expect(lastListFilters()).toMatchObject({ includeCompleted: true, includeCancelled: true });
  });

  it("016-FR-001 016-SC-003 places later fetched open work before a completed-only first page", async () => {
    mocked.listTasks.mockImplementation(async (filters) => filters?.cursor
      ? listResponse([taskFixture({ id: "later", title: "Later open task" }), taskFixture({ id: "done", title: "First page done", state: "completed" })])
      : listResponse([taskFixture({ id: "done", title: "First page done", state: "completed" })], { has_more: true, next_cursor: "page-2" }));
    renderPage();
    expect(await screen.findByRole("list", { name: "Completed" })).toHaveTextContent("First page done");
    await userEvent.setup().click(screen.getByRole("button", { name: "Load more tasks" }));
    await screen.findByText("Later open task");
    expect(renderedTaskRows().map((row) => within(row).getByRole("link").textContent)).toEqual(["Later open task", "First page done"]);
  });

  it.each(["/projects/project-launch", "/tags/tag-deep-work", "/tasks/today"])("016-FR-001 keeps the full open-only subtitle when completed work fills the first page in %s", async (route) => {
    mocked.listTasks.mockResolvedValue(listResponse([taskFixture({ state: "completed" })], {
      counts_by_state: { inbox: 0, next: 3, waiting: 2, someday: 1 }, has_more: true, next_cursor: "page-2"
    }));
    renderPage(route);
    await screen.findByRole("heading", { name: "Completed" });
    expect(screen.getByText("6 tasks")).toBeInTheDocument();
  });

  it("016-FR-003 guards repeated completion while pending and focuses the moved title only after acknowledgement", async () => {
    let resolveSave!: (task: TaskResponse) => void;
    mocked.transitionTask.mockReturnValueOnce(new Promise((resolve) => { resolveSave = resolve; }));
    renderPage();
    const complete = await screen.findByRole("button", { name: "Complete Fix onboarding drop-off" });
    complete.focus();
    fireEvent.click(complete);
    fireEvent.click(complete);
    expect(complete).toBeDisabled();
    expect(screen.getByRole("link", { name: "Fix onboarding drop-off" })).not.toHaveClass("line-through");
    expect(screen.queryByRole("heading", { name: "Completed" })).not.toBeInTheDocument();
    await waitFor(() => expect(mocked.transitionTask).toHaveBeenCalledTimes(1));
    const done = taskFixture({ state: "completed", revision: 5, completed_at: "2026-07-15T11:00:00Z" });
    mocked.listTasks.mockResolvedValue(listResponse([done]));
    await act(async () => resolveSave(done));
    const link = within(await screen.findByRole("list", { name: "Completed" })).getByRole("link", { name: "Fix onboarding drop-off" });
    expect(link).toHaveFocus();
    expect(mocked.transitionTask).toHaveBeenCalledTimes(1);
    expect(renderedTaskRows()).toHaveLength(1);
    const saved = await screen.findByText("Saved");
    expect(saved.closest("[role]")).toHaveAttribute("role", "status");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("016-FR-003 disables repeated detail completion until the canonical response", async () => {
    let resolveSave!: (task: TaskResponse) => void;
    mocked.transitionTask.mockReturnValueOnce(new Promise((resolve) => { resolveSave = resolve; }));
    renderPage("/tasks/next/task-1");
    const complete = await screen.findByRole("button", { name: "Complete task" });
    fireEvent.click(complete);
    fireEvent.click(complete);
    expect(complete).toBeDisabled();
    await waitFor(() => expect(mocked.transitionTask).toHaveBeenCalledTimes(1));
    expect(screen.queryByRole("heading", { name: "Completed" })).not.toBeInTheDocument();
    const done = taskFixture({ state: "completed", revision: 5, completed_at: "2026-07-15T11:00:00Z" });
    mocked.listTasks.mockResolvedValue(listResponse([done]));
    mocked.getTask.mockResolvedValue(done);
    await act(async () => resolveSave(done));
    expect(await screen.findByRole("list", { name: "Completed" })).toHaveTextContent(done.title);
    await waitFor(() => expect(currentLocation()).toBe("/tasks/next"));
    expect(screen.queryByRole("button", { name: "Reopen task" })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: done.title })).toHaveFocus();
    expect(mocked.transitionTask).toHaveBeenCalledTimes(1);
  });

  it("016-FR-003 keeps failed rows open during mixed completion outcomes", async () => {
    const first = taskFixture();
    const second = taskFixture({ id: "task-2", title: "Failed second task" });
    let saved = false;
    mocked.listTasks.mockImplementation(async () => listResponse([saved ? { ...first, state: "completed", revision: 5 } : first, second]));
    mocked.transitionTask.mockImplementation(async (id) => {
      if (id === second.id) throw new Error("Connection interrupted");
      saved = true;
      return { ...first, state: "completed", revision: 5, completed_at: "2026-07-15T11:00:00Z" };
    });
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: `Complete ${first.title}` }));
    fireEvent.click(screen.getByRole("button", { name: `Complete ${second.title}` }));
    expect(await screen.findByRole("list", { name: "Completed" })).toHaveTextContent(first.title);
    expect(screen.getByRole("button", { name: `Complete ${second.title}` })).toBeEnabled();
    expect(screen.getByRole("link", { name: second.title })).not.toHaveClass("line-through");
    expect(renderedTaskRows()).toHaveLength(2);
  });

  it("016-FR-003 retries an exhausted transient completion from its row using the original idempotency key", async () => {
    const done = taskFixture({ state: "completed", revision: 5, completed_at: "2026-07-15T11:00:00Z" });
    mocked.transitionTask
      .mockRejectedValueOnce(new ApiError("Temporarily unavailable", 503, {}))
      .mockRejectedValueOnce(new ApiError("Temporarily unavailable", 503, {}))
      .mockRejectedValueOnce(new ApiError("Temporarily unavailable", 503, {}))
      .mockResolvedValueOnce(done);
    renderPage();
    const complete = await screen.findByRole("button", { name: "Complete Fix onboarding drop-off" });
    fireEvent.click(complete);
    expect(await screen.findByRole("alert", {}, { timeout: 3500 })).toHaveTextContent("Temporarily unavailable");
    expect(complete).toBeEnabled();
    expect(mocked.transitionTask).toHaveBeenCalledTimes(3);
    mocked.listTasks.mockResolvedValue(listResponse([done]));
    fireEvent.click(complete);
    expect(await screen.findByRole("list", { name: "Completed" })).toHaveTextContent(done.title);
    expect(mocked.transitionTask).toHaveBeenCalledTimes(4);
    const keys = mocked.transitionTask.mock.calls.map((call) => call[2]);
    expect(new Set(keys).size).toBe(1);
  });

  it("016-FR-003 shares completion and reopen across cached project, tag and search matches without inserting unrelated tasks", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const matchingKeys = [
      taskKeys.list({ projectId: "project-launch", includeCompleted: true }),
      taskKeys.list({ tagId: "tag-deep-work", includeCompleted: true }),
      taskKeys.list({ q: "onboarding", includeCompleted: true })
    ];
    const unrelatedKey = taskKeys.list({ q: "unrelated", includeCompleted: true });
    for (const key of matchingKeys) client.setQueryData(key, { pages: [listResponse([taskFixture()])], pageParams: [undefined] });
    client.setQueryData(unrelatedKey, { pages: [listResponse([])], pageParams: [undefined] });
    let canonical = taskFixture();
    mocked.listTasks.mockImplementation(async () => listResponse([canonical]));
    mocked.getTask.mockImplementation(async () => canonical);
    mocked.transitionTask.mockImplementation(async (_id, payload) => {
      canonical = { ...canonical, state: payload.action === "complete" ? "completed" : "next", revision: canonical.revision + 1, completed_at: payload.action === "complete" ? "2026-07-15T11:00:00Z" : null };
      return canonical;
    });
    renderPage("/tasks/next", client);
    await userEvent.setup().click(await screen.findByRole("button", { name: `Complete ${canonical.title}` }));
    await screen.findByRole("list", { name: "Completed" });
    const cachedItems = (key: ReturnType<typeof taskKeys.list>) => client.getQueryData<{ pages: TaskListResponse[] }>(key)?.pages.flatMap((page) => page.items);
    for (const key of matchingKeys) expect(cachedItems(key)).toEqual([canonical]);
    expect(cachedItems(unrelatedKey)).toEqual([]);
    await userEvent.setup().click(screen.getByRole("link", { name: canonical.title }));
    await userEvent.setup().selectOptions(await screen.findByLabelText("List"), "next");
    await waitFor(() => { for (const key of matchingKeys) expect(cachedItems(key)).toEqual([canonical]); });
    expect(canonical.state).toBe("next");
    expect(cachedItems(unrelatedKey)).toEqual([]);
  });

  it("016-FR-003 isolates first paint and late completion after an account switch", async () => {
    let resolveSave!: (task: TaskResponse) => void;
    mocked.transitionTask.mockReturnValueOnce(new Promise((resolve) => { resolveSave = resolve; }));
    mocked.listTasks.mockImplementation(async () => listResponse([taskFixture({ title: useAuthStore.getState().user?.id === "user-1" ? "Owner A task" : "Owner B task" })]));
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Complete Owner A task" }));
    await waitFor(() => expect(mocked.transitionTask).toHaveBeenCalledTimes(1));
    act(() => useAuthStore.setState({ user: { id: "user-2", email: "b@example.test" } }));
    expect(screen.queryByRole("link", { name: "Owner A task" })).not.toBeInTheDocument();
    await screen.findByRole("link", { name: "Owner B task" });
    await act(async () => resolveSave(taskFixture({ title: "Owner A task", state: "completed", revision: 5, completed_at: "2026-07-15T11:00:00Z" })));
    expect(screen.queryByRole("link", { name: "Owner A task" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Complete Owner B task" })).toBeEnabled();
    expect(screen.queryByRole("heading", { name: "Completed" })).not.toBeInTheDocument();
    expect(screen.queryByText("Saved")).not.toBeInTheDocument();
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

  it("announces title-completion loading while the provider response is pending", async () => {
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
    let resolveCompletions!: (value: Awaited<ReturnType<typeof apiClient.generateTitleCompletions>>) => void;
    mocked.generateTitleCompletions.mockReturnValueOnce(new Promise((resolve) => {
      resolveCompletions = resolve;
    }));
    const user = userEvent.setup();
    renderPage("/tasks/next");

    const field = await screen.findByRole("combobox", { name: "New task title" });
    await user.type(field, "Prepare launch notes");
    await user.click(await screen.findByRole("checkbox", { name: /Allow deterministic/ }));
    expect(await screen.findByRole("status")).toHaveTextContent("Finding title suggestions…");

    await act(async () => resolveCompletions({
      request_id: "8f3d2f73-0e55-4f47-9f9b-1a0b6c7a9c6e",
      candidates: [
        "Prepare launch notes today",
        "Prepare launch notes this week",
        "Prepare launch notes tomorrow"
      ]
    }));
    expect(await screen.findByRole("listbox", { name: "Task title suggestions" })).toBeInTheDocument();
  });

  it("creates a plain task in the current list and clears the field", async () => {
    const user = userEvent.setup();
    renderPage("/tasks/next");

    const field = await screen.findByLabelText("New task title");
    await user.type(field, "Write the release note");
    field.blur();
    fireEvent.submit(field.closest("form") as HTMLFormElement);

    await waitFor(() =>
      expect(mocked.createTask).toHaveBeenCalledWith(
        { title: "Write the release note", state: "next" },
        expect.stringContaining("task-shell-create")
      )
    );
    await waitFor(() => expect(field).toHaveValue(""));
  });

  it("guards Enter twice with one synchronous capture attempt", async () => {
    let release: (task: TaskResponse) => void = () => undefined;
    mocked.createTask.mockImplementationOnce(() => new Promise<TaskResponse>((resolve) => { release = resolve; }));
    renderPage("/tasks/next");
    const user = userEvent.setup();
    const field = await screen.findByLabelText("New task title");
    await user.type(field, "Rapid Enter");
    await user.keyboard("{Enter}{Enter}");
    expect(mocked.createTask).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("button", { name: /Adding task/ })).toBeDisabled();
    expect(screen.getAllByText("Adding task…").length).toBeGreaterThan(0);
    await act(async () => release(taskFixture({ id: "rapid-enter" })));
  });

  it("guards two same-tick form submissions before React commits pending state", async () => {
    let release: (task: TaskResponse) => void = () => undefined;
    mocked.createTask.mockImplementationOnce(() => new Promise<TaskResponse>((resolve) => { release = resolve; }));
    renderPage("/tasks/next");
    const user = userEvent.setup();
    const field = await screen.findByLabelText("New task title");
    await user.type(field, "Same tick");

    const form = field.closest("form");
    expect(form).not.toBeNull();
    await act(async () => {
      (form as HTMLFormElement).dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
      (form as HTMLFormElement).dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
      await Promise.resolve();
    });

    expect(mocked.createTask).toHaveBeenCalledTimes(1);
    await act(async () => release(taskFixture({ id: "same-tick" })));
  });

  it("does not steal focus moved to another form while capture is pending", async () => {
    let release: (task: TaskResponse) => void = () => undefined;
    mocked.createTask.mockImplementationOnce(() => new Promise<TaskResponse>((resolve) => { release = resolve; }));
    renderPage("/tasks/next");
    const user = userEvent.setup();
    const field = await screen.findByLabelText("New task title");
    await user.type(field, "External pending focus");
    await user.click(screen.getByRole("button", { name: "Add task" }));
    const externalForm = document.createElement("form");
    const externalInput = document.createElement("input");
    externalInput.setAttribute("aria-label", "External form input");
    externalForm.append(externalInput);
    document.body.append(externalForm);
    externalInput.focus();

    await act(async () => release(taskFixture({ id: "external-focus" })));
    expect(externalInput).toHaveFocus();
    externalForm.remove();
  });

  it("preserves newer edits and focus when an older capture settles", async () => {
    let release: (task: TaskResponse) => void = () => undefined;
    mocked.createTask.mockImplementationOnce(() => new Promise<TaskResponse>((resolve) => { release = resolve; }));
    renderPage("/tasks/next");
    const user = userEvent.setup();
    const field = await screen.findByLabelText("New task title");
    await user.type(field, "Accepted first");
    await user.click(screen.getByRole("button", { name: "Add task" }));
    await user.type(field, " and newer");
    const heading = screen.getByRole("heading", { level: 1, name: "Next actions" });
    heading.focus();

    await act(async () => release(taskFixture({ id: "accepted-first" })));
    await waitFor(() => expect(field).toHaveValue("Accepted first and newer"));
    expect(heading).toHaveFocus();
  });

  it("mints a fresh identity for a later intentional same-title capture", async () => {
    const user = userEvent.setup();
    renderPage("/tasks/next");
    const field = await screen.findByLabelText("New task title");
    await user.type(field, "Repeat intentionally");
    await user.click(screen.getByRole("button", { name: "Add task" }));
    await waitFor(() => expect(mocked.createTask).toHaveBeenCalledTimes(1));
    const firstKey = mocked.createTask.mock.calls[0]?.[1];
    await user.type(field, "Repeat intentionally");
    await user.click(screen.getByRole("button", { name: "Add task" }));
    await waitFor(() => expect(mocked.createTask).toHaveBeenCalledTimes(2));
    expect(mocked.createTask.mock.calls[1]?.[1]).not.toBe(firstKey);
  });

  it("guards mixed Enter and click activation without deduplicating Smart Add titles", async () => {
    let release: (response: { task: TaskResponse; project: null; tags: never[]; created: { project_id: null; tag_ids: never[] } }) => void = () => undefined;
    mocked.smartAddTask.mockImplementationOnce(() => new Promise((resolve) => { release = resolve; }));
    renderPage("/tasks/next");
    const user = userEvent.setup();
    const field = await screen.findByLabelText("New task title");
    await user.type(field, "Call bank #calls ");
    await user.keyboard("{Enter}");
    fireEvent.submit(field.closest("form") as HTMLFormElement);
    expect(mocked.smartAddTask).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("button", { name: /Adding task/ })).toBeDisabled();
    await act(async () => release({ task: taskFixture({ id: "smart-rapid" }), project: null, tags: [], created: { project_id: null, tag_ids: [] } }));
  });

  it("reuses the body and key for an unchanged failed retry, then mints after editing", async () => {
    mocked.createTask.mockRejectedValueOnce(new Error("Timed out."));
    renderPage("/tasks/next");
    const user = userEvent.setup();
    const field = await screen.findByLabelText("New task title");
    await user.type(field, "Retry title");
    await user.click(screen.getByRole("button", { name: "Add task" }));
    await screen.findByRole("alert");
    mocked.createTask.mockResolvedValueOnce(taskFixture({ id: "retry-1" }));
    await user.click(screen.getByRole("button", { name: "Add task" }));
    await waitFor(() => expect(mocked.createTask).toHaveBeenCalledTimes(2));
    expect(mocked.createTask.mock.calls[1]).toEqual(mocked.createTask.mock.calls[0]);
    await user.type(field, " again");
    mocked.createTask.mockResolvedValueOnce(taskFixture({ id: "retry-2" }));
    await user.click(screen.getByRole("button", { name: "Add task" }));
    await waitFor(() => expect(mocked.createTask).toHaveBeenCalledTimes(3));
    expect(mocked.createTask.mock.calls[2][1]).not.toBe(mocked.createTask.mock.calls[1][1]);
  });

  it("clears after a retry whose whitespace-only edit preserves the normalized payload", async () => {
    const user = userEvent.setup();
    mocked.createTask.mockRejectedValueOnce(new Error("Timed out."));
    renderPage("/tasks/next");
    const field = await screen.findByLabelText("New task title");
    await user.type(field, "  Normalized retry  ");
    await user.click(screen.getByRole("button", { name: "Add task" }));
    await screen.findByRole("alert");
    mocked.createTask.mockResolvedValueOnce(taskFixture({ id: "normalized-retry" }));
    await user.clear(field);
    await user.type(field, "Normalized retry");
    await user.click(screen.getByRole("button", { name: "Add task" }));
    await waitFor(() => expect(field).toHaveValue(""));
    expect(mocked.createTask.mock.calls[1]?.[1]).toBe(mocked.createTask.mock.calls[0]?.[1]);
  });

  it("reuses a waiting capture key when only waiting-for whitespace changes after an ambiguous retry", async () => {
    const user = userEvent.setup();
    mocked.createTask.mockRejectedValueOnce(new Error("Request status is unknown."));
    renderPage("/tasks/waiting");
    const field = await screen.findByLabelText("New task title");
    await user.type(field, "Chase the invoice");
    const waiting = screen.getByRole("textbox", { name: "Waiting for" });
    await user.type(waiting, "Finance");
    await user.click(screen.getByRole("button", { name: "Add task" }));
    await screen.findByRole("alert");

    await user.clear(waiting);
    await user.type(waiting, "  Finance  ");
    mocked.createTask.mockResolvedValueOnce(taskFixture({ id: "waiting-retry" }));
    await user.click(screen.getByRole("button", { name: "Add task" }));
    await waitFor(() => expect(mocked.createTask).toHaveBeenCalledTimes(2));

    expect(mocked.createTask.mock.calls[1]?.[0]).toEqual({
      title: "Chase the invoice",
      state: "waiting",
      waiting_for: "Finance"
    });
    expect(mocked.createTask.mock.calls[1]?.[1]).toBe(mocked.createTask.mock.calls[0]?.[1]);
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
  it("017-FR-005 clears excluding filters once and expands the real row in the retained state route", async () => {
    mocked.listTasks.mockImplementation(async (filters) => {
      if (filters?.limit) return listResponse([]);
      return filters?.q
        ? listResponse([taskFixture({ id: "other", title: "Other task" })])
        : listResponse([taskFixture()]);
    });
    renderPage("/tasks/next/task-1?q=hidden&group=off");

    await waitFor(() => expect(currentLocation()).toBe("/tasks/next/task-1"));
    const title = await screen.findByLabelText("Title");
    expect(screen.getByRole("link", { name: "Fix onboarding drop-off" }).closest("article")).toContainElement(title);
  });

  it("017-FR-005 prefers a resolvable project, then uses terminal fallback with cancelled visibility", async () => {
    const moved = taskFixture({ state: "waiting", project_id: "project-launch" });
    mocked.getTask.mockResolvedValue(moved);
    mocked.listTasks.mockImplementation(async (filters) =>
      filters?.projectId === "project-launch" ? listResponse([moved]) : listResponse([])
    );
    const first = renderPage("/tasks/next/task-1");
    await waitFor(() => expect(currentLocation()).toBe("/projects/project-launch/task-1"));
    expect(await screen.findByLabelText("Title")).toHaveValue(moved.title);
    first.unmount();

    const cancelled = taskFixture({ state: "cancelled", project_id: null });
    mocked.getTask.mockResolvedValue(cancelled);
    mocked.listTasks.mockImplementation(async (filters) =>
      filters?.includeCancelled ? listResponse([cancelled]) : listResponse([])
    );
    renderPage("/tasks/waiting/task-1");
    await waitFor(() => expect(currentLocation()).toBe("/tasks/next/task-1?showCancelled=1"));
    expect(await screen.findByLabelText("Title")).toHaveValue(cancelled.title);
  });

  it("017-FR-005 redirects an Inbox-state task with a project to that project", async () => {
    const classifiedInboxTask = taskFixture({ state: "inbox", project_id: "project-launch" });
    mocked.getTask.mockResolvedValue(classifiedInboxTask);
    mocked.listTasks.mockImplementation(async (filters) =>
      filters?.projectId === "project-launch" ? listResponse([classifiedInboxTask]) : listResponse([])
    );

    renderPage("/tasks/inbox/task-1");

    await waitFor(() => expect(currentLocation()).toBe("/projects/project-launch/task-1"));
    expect(await screen.findByLabelText("Title")).toHaveValue(classifiedInboxTask.title);
  });

  it("017-FR-005 loads bounded pages until the selected real row exists", async () => {
    mocked.listTasks.mockImplementation(async (filters) => {
      if (filters?.limit) return listResponse([]);
      if (filters?.cursor === "page-2") return listResponse([taskFixture()]);
      return listResponse([taskFixture({ id: "other", title: "Other task" })], {
        next_cursor: "page-2",
        has_more: true
      });
    });
    renderPage("/tasks/next/task-1");

    expect(await screen.findByLabelText("Title")).toHaveValue("Fix onboarding drop-off");
    expect(lastListFilters().cursor).toBe("page-2");
  });

  it("017-FR-005 retains matching project and tag routes while removing excluding filters", async () => {
    mocked.listTasks.mockResolvedValue(listResponse([]));
    mocked.getTask.mockResolvedValue(taskFixture({ project_id: "project-launch", state: "waiting" }));
    const projectView = renderPage("/projects/project-launch/task-1?sort=due&q=hidden");
    await waitFor(() => expect(currentLocation()).toBe("/projects/project-launch/task-1?sort=due"));
    expect(await screen.findByText(/not in this list/i)).toBeInTheDocument();
    projectView.unmount();

    mocked.getTask.mockResolvedValue(taskFixture({ project_id: null, tag_ids: ["tag-deep-work"], state: "waiting" }));
    renderPage("/tags/tag-deep-work/task-1?q=hidden");
    await waitFor(() => expect(currentLocation()).toBe("/tags/tag-deep-work/task-1"));
    expect(await screen.findByText(/not in this list/i)).toBeInTheDocument();
  });

  it("017-FR-005 reports a failed automatic page and retries it on request", async () => {
    let pageAttempts = 0;
    mocked.listTasks.mockImplementation(async (filters) => {
      if (filters?.limit) return listResponse([]);
      if (filters?.cursor) {
        pageAttempts += 1;
        if (pageAttempts === 1) throw new Error("Page unavailable.");
        return listResponse([taskFixture()]);
      }
      return listResponse([taskFixture({ id: "other", title: "Other task" })], {
        next_cursor: "page-2",
        has_more: true
      });
    });
    const user = userEvent.setup();
    renderPage("/tasks/next/task-1");

    expect(await screen.findByText(/Could not load the row/i)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Retry / load more" }));
    expect(await screen.findByLabelText("Title")).toHaveValue("Fix onboarding drop-off");
    expect(pageAttempts).toBe(2);
  });

  it("017-FR-005 stops automatic recovery after ten additional pages", async () => {
    mocked.listTasks.mockImplementation(async (filters) => {
      if (filters?.limit) return listResponse([]);
      const current = filters?.cursor ? Number(filters.cursor.replace("page-", "")) : 0;
      return listResponse([taskFixture({ id: `other-${current}`, title: `Other task ${current}` })], {
        next_cursor: `page-${current + 1}`,
        has_more: true
      });
    });
    renderPage("/tasks/next/task-1");

    expect(await screen.findByText(/beyond the automatic 10-page limit/i)).toBeInTheDocument();
    const automaticPageCalls = mocked.listTasks.mock.calls.filter(([filters]) => Boolean(filters?.cursor));
    expect(automaticPageCalls).toHaveLength(10);
    expect(automaticPageCalls.some(([filters]) => filters?.cursor === "page-11")).toBe(false);
    expect(lastListFilters().cursor).toBe("page-10");
  });

  it("017-FR-005 keeps an indistinguishable missing-task error at list level without redirecting", async () => {
    mocked.getTask.mockRejectedValueOnce(new Error("Task not found."));
    mocked.listTasks.mockImplementation(async () => listResponse([taskFixture({ id: "other", title: "Other task" })]));
    renderPage("/tasks/next/missing-task?q=private");

    expect(await screen.findByRole("alert")).toHaveTextContent("Task not found.");
    expect(currentLocation()).toBe("/tasks/next/missing-task?q=private");
    expect(screen.getByRole("button", { name: "Close" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(mocked.getTask.mock.calls.length).toBeGreaterThanOrEqual(2));
  });

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

  it("navigates the displayed grouped tasks through inline detail and returns to the opening row", async () => {
    const user = userEvent.setup();
    const items = [
      taskFixture(),
      taskFixture({ id: "task-unassigned", title: "Unassigned last", project_id: null }),
      taskFixture({ id: "task-2", title: "Second in launch" }),
      taskFixture({ id: "task-3", title: "Other project", project_id: "project-onboarding" })
    ];
    mocked.listTasks.mockImplementation(async () => listResponse(items));
    mocked.getTask.mockImplementation(async (id) => items.find((task) => task.id === id) as TaskResponse);
    renderPage("/tasks/next?sort=priority&q=launch");
    const origin = await screen.findByRole("link", { name: items[0].title });
    await user.click(origin);
    const firstDetail = screen.getByRole("complementary", { name: "Task detail" });
    expect(origin.closest("article")).toContainElement(firstDetail);
    expect(screen.getByRole("heading", { name: "Task detail" })).toHaveFocus();
    expect(screen.getByRole("button", { name: "Previous task" })).toBeDisabled();
    expect(screen.getByText("1 of 4")).toBeInTheDocument();
    let next = screen.getByRole("button", { name: "Next task" });
    await user.click(next);
    await waitFor(() => expect(screen.getByLabelText("Title")).toHaveValue(items[2].title));
    expect(currentLocation()).toBe("/tasks/next/task-2?sort=priority&q=launch");
    expect(screen.getByRole("link", { name: items[2].title }).closest("article")).toContainElement(
      screen.getByRole("complementary", { name: "Task detail" })
    );
    next = screen.getByRole("button", { name: "Next task" });
    expect(next).toHaveFocus();
    await user.click(next);
    next = screen.getByRole("button", { name: "Next task" });
    await user.click(next);
    await waitFor(() => expect(screen.getByLabelText("Title")).toHaveValue(items[1].title));
    expect(screen.getByText("4 of 4")).toBeInTheDocument();
    next = screen.getByRole("button", { name: "Next task" });
    expect(next).toBeDisabled();
    const previous = screen.getByRole("button", { name: "Previous task" });
    expect(previous).toHaveFocus();
    await user.click(previous);
    await waitFor(() => expect(screen.getByLabelText("Title")).toHaveValue(items[3].title));
    // Assistive activation and some pointer browsers do not focus a clicked
    // button. In that case the new task gets heading focus, not a stale field.
    screen.getByLabelText("Title").focus();
    next = screen.getByRole("button", { name: "Next task" });
    fireEvent.click(next);
    await waitFor(() => expect(screen.getByLabelText("Title")).toHaveValue(items[1].title));
    expect(screen.getByRole("heading", { name: "Task detail" })).toHaveFocus();
    await user.click(screen.getByRole("button", { name: "Close task" }));
    expect(currentLocation()).toBe("/tasks/next?sort=priority&q=launch");
    await waitFor(() => expect(origin).toHaveFocus());
  });

  it("reserves the detail panel for selected tasks and releases it after closing", async () => {
    const user = userEvent.setup();
    const { unmount } = renderPage("/tasks/next");
    await screen.findByRole("link", { name: "Fix onboarding drop-off" });
    expect(screen.queryByRole("complementary", { name: "Task detail" })).not.toBeInTheDocument();
    unmount();

    renderPage("/tasks/next/task-1");
    await user.click(await screen.findByRole("button", { name: "Close task" }));
    expect(currentLocation()).toBe("/tasks/next");
    expect(screen.queryByRole("complementary", { name: "Task detail" })).not.toBeInTheDocument();
  });

  it("starts a fresh bounded recovery attempt after the selected list filters change", async () => {
    const user = userEvent.setup();
    renderPage("/tasks/next/task-1");

    expect(await screen.findByLabelText("Title")).toBeInTheDocument();
    await user.click(screen.getByRole("checkbox", { name: "Show cancelled" }));
    await waitFor(() => expect(currentLocation()).toBe("/tasks/next/task-1?showCancelled=1"));
    expect(screen.getByRole("complementary", { name: "Task detail" })).toBeInTheDocument();
  });

  it("returns focus to the row that opened inline detail", async () => {
    const user = userEvent.setup();
    const { unmount } = renderPage("/tasks/next");

    await user.click(await screen.findByRole("link", { name: "Fix onboarding drop-off" }));
    expect(currentLocation()).toBe("/tasks/next/task-1");
    await user.click(screen.getByRole("button", { name: "Close task" }));
    await waitFor(() => expect(screen.getByRole("link", { name: "Fix onboarding drop-off" })).toHaveFocus());
    unmount();
  });

  it("collapses inline detail with the keyboard shortcut and never reopens hidden state", async () => {
    const user = userEvent.setup();
    renderPage("/tasks/next/task-1");

    expect(await screen.findByLabelText("Title")).toBeInTheDocument();

    await user.keyboard("{Meta>}\\{/Meta}");
    await waitFor(() => expect(screen.queryByLabelText("Title")).not.toBeInTheDocument());
    expect(currentLocation()).toBe("/tasks/next");

    await user.keyboard("{Control>}\\{/Control}");
    expect(screen.queryByLabelText("Title")).not.toBeInTheDocument();
    expect(currentLocation()).toBe("/tasks/next");
  });

  it("closes on Escape from a plain details field and flushes its pending edit", async () => {
    const user = userEvent.setup();
    let release: (task: TaskResponse) => void = () => undefined;
    mocked.updateTask.mockImplementation(() => new Promise((resolve) => { release = resolve; }));
    renderPage("/tasks/next/task-1");

    const details = await screen.findByLabelText("Details");
    await user.type(details, "Preserve this pending draft");
    await user.keyboard("{Escape}");
    expect(currentLocation()).toBe("/tasks/next");
    await waitFor(() => expect(mocked.updateTask).toHaveBeenCalledWith("task-1", { details: "Preserve this pending draft", expected_revision: 4 }, expect.any(String)));
    await act(async () => release(taskFixture({ details: "Preserve this pending draft", revision: 5 })));
    await waitFor(() => expect(screen.getByRole("link", { name: "Fix onboarding drop-off" })).toHaveFocus());
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
      await user.keyboard("{Control>}\\{/Control}");
      expect(screen.getByRole("complementary", { name: "Task detail" })).toBeInTheDocument();
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
    vi.mocked(window.confirm).mockReturnValueOnce(false);
    fireEvent.click(discard);
    expect(sessionStorage.getItem(recoveryKey)).not.toBeNull();
    title.focus();
    fireEvent.mouseDown(discard);
    fireEvent.click(discard);
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
    expect(document.activeElement).toBe(titleNode);
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
    await screen.findByLabelText("Title");
    act(() => {
      useAuthStore.setState({ user: null, status: "authed" });
    });
    const title = await screen.findByLabelText("Title");

    fireEvent.change(title, { target: { value: "Local only" } });
    fireEvent.blur(title);
    fireEvent.click(screen.getByRole("button", { name: "Complete task" }));
    fireEvent.click(screen.getByRole("button", { name: "Complete Fix onboarding drop-off" }));

    expect(mocked.updateTask).not.toHaveBeenCalled();
    expect(mocked.transitionTask).not.toHaveBeenCalled();
  });
});
