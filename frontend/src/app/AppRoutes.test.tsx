import { act, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useAuthStore } from "../stores/authStore";
import { AppRoutes } from "./AppRoutes";

vi.mock("../pages/TreeWorkspace", () => ({
  default: () => <div>legacy CRT workspace</div>
}));

const taskResponse = {
  items: [
    {
      id: "task-1",
      title: "Fix onboarding drop-off",
      details: null,
      state: "next",
      project_id: "project-onboarding",
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
      revision: 1,
      subtasks: [],
      comments: []
    }
  ],
  next_cursor: null,
  has_more: false,
  counts_by_state: { inbox: 17, next: 6, waiting: 3, someday: 0 }
};

const projectsResponse = [
  { id: "project-launch", name: "Launch v2", color: "#0ea5e9", state: "active", revision: 1, open_task_count: 2 },
  {
    id: "project-onboarding",
    name: "Onboarding drop-off",
    color: "#6366f1",
    state: "active",
    revision: 1,
    open_task_count: 1
  }
];

const tagsResponse = [
  { id: "tag-calls", name: "calls", state: "active", revision: 1, open_task_count: 2 },
  { id: "tag-deep-work", name: "deep-work", state: "active", revision: 1, open_task_count: 1 }
];

function taskFixture(id: string, title: string, state = "next") {
  return {
    ...taskResponse.items[0],
    id,
    title,
    state,
    project_id: null,
    tag_ids: [],
    order_key: Number(id.replace(/\D/g, "")) || 1
  };
}

function renderRoutes(initialEntry: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });

  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[initialEntry]}>
        <AppRoutes />
      </MemoryRouter>
    </QueryClientProvider>
  );
}

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" }
  });
}

beforeEach(() => {
  act(() => {
    useAuthStore.setState({
      user: { id: "user-1", email: "max@example.test" },
      status: "authed"
    });
  });

  vi.stubGlobal(
    "fetch",
    vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/tasks") && url.includes("/transitions")) {
        return Promise.resolve(jsonResponse({ ...taskResponse.items[0], state: "completed", revision: 2 }));
      }
      if (url.endsWith("/tasks") || url.includes("/tasks?")) {
        return Promise.resolve(jsonResponse(taskResponse));
      }
      if (url.includes("/tasks/")) {
        return Promise.resolve(jsonResponse(taskResponse.items[0]));
      }
      if (url.includes("/projects")) {
        return Promise.resolve(jsonResponse(projectsResponse));
      }
      if (url.includes("/tags")) {
        return Promise.resolve(jsonResponse(tagsResponse));
      }
      return Promise.resolve(jsonResponse(null));
    })
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.clearAllMocks();
  act(() => {
    useAuthStore.setState({ user: null, status: "loading" });
  });
});

describe("AppRoutes", () => {
  it("renders persisted GTD projections at the authenticated root route without demo fixtures", async () => {
    renderRoutes("/");

    expect(await screen.findByRole("heading", { name: "Next actions" })).toBeInTheDocument();
    expect(screen.getByRole("banner")).toHaveStyle({ height: "56px" });
    expect(screen.getByText("Brain Buddy")).toBeInTheDocument();
    expect(screen.getByRole("searchbox", { name: "Search tasks" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Brain dump" })).toBeEnabled();
    expect(await screen.findByText("Fix onboarding drop-off")).toBeInTheDocument();
    expect(screen.getByText("6 tasks")).toBeInTheDocument();
    expect(screen.queryByText("Draft the launch announcement")).not.toBeInTheDocument();
    expect(fetch).toHaveBeenCalledWith(expect.stringContaining("/tasks?state=next"), expect.anything());
    expect(screen.getByRole("button", { name: "Weekly review" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Think with CRT — Coming soon" })).toBeDisabled();
    expect(screen.queryByRole("link", { name: /CRT.*legacy/i })).not.toBeInTheDocument();
  });

  it("renders projects, tags and task rows from server projections without Context copy", async () => {
    const tagsWithAt = [...tagsResponse, { id: "tag-at-calls", name: "@calls", state: "active", revision: 1, open_task_count: 1 }];
    vi.mocked(fetch).mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/tasks") || url.includes("/tasks?")) {
        return Promise.resolve(jsonResponse(taskResponse));
      }
      if (url.includes("/tasks/")) {
        return Promise.resolve(jsonResponse(taskResponse.items[0]));
      }
      if (url.includes("/projects")) {
        return Promise.resolve(jsonResponse(projectsResponse));
      }
      if (url.includes("/tags")) {
        return Promise.resolve(jsonResponse(tagsWithAt));
      }
      return Promise.resolve(jsonResponse(null));
    });

    renderRoutes("/tasks/next");

    expect(await screen.findByRole("heading", { name: "Next actions" })).toBeInTheDocument();
    const sidebar = screen.getByRole("navigation", { name: "Task navigation" });
    expect(within(sidebar).getByText("Inbox")).toBeInTheDocument();
    expect(await within(sidebar).findByText("17")).toBeInTheDocument();
    expect(within(sidebar).getByText("Projects")).toBeInTheDocument();
    expect(within(sidebar).getByText("Launch v2")).toBeInTheDocument();
    expect(within(sidebar).getByText("Tags")).toBeInTheDocument();
    expect(within(sidebar).queryByText("Contexts")).not.toBeInTheDocument();
    expect(within(sidebar).getByText("#deep-work")).toBeInTheDocument();
    expect(await within(sidebar).findByRole("link", { name: "@calls" })).toBeInTheDocument();

    expect(screen.getByText("Fix onboarding drop-off")).toBeInTheDocument();
    expect(screen.getAllByText("Onboarding drop-off").length).toBeGreaterThanOrEqual(2);
    expect(screen.getAllByText(/#deep-work/).length).toBeGreaterThanOrEqual(2);
  });

  it("accepts a Smart Add suggestion by keyboard before submitting the clean classified task", async () => {
    const user = userEvent.setup();
    vi.mocked(fetch).mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/tasks/smart-add")) {
        return Promise.resolve(
          jsonResponse({
            task: taskFixture("task-smart-add", "Call supplier"),
            project: null,
            tags: [tagsResponse[0]],
            created: { project_id: null, tag_ids: [] }
          }, 201)
        );
      }
      if (url.endsWith("/tasks") || url.includes("/tasks?")) {
        return Promise.resolve(jsonResponse(taskResponse));
      }
      if (url.includes("/projects")) {
        return Promise.resolve(jsonResponse(projectsResponse));
      }
      if (url.includes("/tags")) {
        return Promise.resolve(jsonResponse(tagsResponse));
      }
      return Promise.resolve(jsonResponse(null));
    });

    renderRoutes("/tasks/next");
    const title = await screen.findByLabelText("New task title");
    await user.type(title, "Call supplier #ca");

    expect(await screen.findByRole("listbox", { name: "Smart Add suggestions" })).toBeInTheDocument();
    expect(title).toHaveAttribute("aria-expanded", "true");
    await user.keyboard("{Enter}");
    expect(title).toHaveValue("Call supplier #calls ");
    await user.keyboard("{Enter}");

    await waitFor(() => {
      expect(fetch).toHaveBeenCalledWith(
        expect.stringContaining("/tasks/smart-add"),
        expect.objectContaining({ method: "POST" })
      );
    });
    const smartAddCall = vi.mocked(fetch).mock.calls.find(([input]) => String(input).includes("/tasks/smart-add"));
    expect(JSON.parse(String(smartAddCall?.[1]?.body))).toMatchObject({
      title: "Call supplier",
      tags: [{ id: "tag-calls" }]
    });
  });

  it("keeps direct CRT routes inert until the feature is available", async () => {
    renderRoutes("/crt/demo-tree");

    expect(await screen.findByRole("heading", { name: "Think with CRT" })).toBeInTheDocument();
    expect(screen.getByText("Coming later")).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.queryByRole("heading", { name: "Next actions" })).not.toBeInTheDocument();
    });
    expect(fetch).not.toHaveBeenCalledWith(expect.stringContaining("/tasks"), expect.anything());
  });

  it("routes task-only search, date views and named sort filters through URL-backed task queries", async () => {
    const user = userEvent.setup();
    renderRoutes("/tasks/today?sort=priority&q=invoice");

    expect(await screen.findByRole("heading", { name: "Today" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Add task" })).not.toBeInTheDocument();
    expect(screen.getByText(/Date views are filters over existing tasks/i)).toBeInTheDocument();
    await user.type(screen.getByRole("searchbox", { name: "Search tasks" }), " review");
    await user.selectOptions(screen.getByLabelText("Sort tasks"), "due");

    await waitFor(() => {
      expect(fetch).toHaveBeenCalledWith(expect.stringContaining("due_on="), expect.anything());
      expect(fetch).toHaveBeenCalledWith(expect.stringContaining("q=invoicereview"), expect.anything());
      expect(fetch).toHaveBeenCalledWith(expect.stringContaining("sort=due"), expect.anything());
    });
    expect(screen.queryByRole("button", { name: /Sort by tag/i })).not.toBeInTheDocument();
  });

  it("offers cursor continuation so large state projections remain reachable", async () => {
    const user = userEvent.setup();
    const firstPageTasks = Array.from({ length: 50 }, (_, index) =>
      taskFixture(`someday-${index}`, `Overflow task ${String(index).padStart(2, "0")}`, "someday")
    );
    const secondPageTasks = Array.from({ length: 5 }, (_, index) =>
      taskFixture(`someday-${index + 50}`, `Overflow task ${String(index + 50).padStart(2, "0")}`, "someday")
    );

    vi.mocked(fetch).mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/tasks?") && url.includes("cursor=next-page")) {
        return Promise.resolve(jsonResponse({
          items: secondPageTasks,
          next_cursor: null,
          has_more: false,
          counts_by_state: { inbox: 0, next: 0, waiting: 0, someday: 55 }
        }));
      }
      if (url.includes("/tasks?")) {
        return Promise.resolve(jsonResponse({
          items: firstPageTasks,
          next_cursor: "next-page",
          has_more: true,
          counts_by_state: { inbox: 0, next: 0, waiting: 0, someday: 55 }
        }));
      }
      if (url.includes("/projects")) {
        return Promise.resolve(jsonResponse(projectsResponse));
      }
      if (url.includes("/tags")) {
        return Promise.resolve(jsonResponse(tagsResponse));
      }
      return Promise.resolve(jsonResponse(null));
    });

    renderRoutes("/tasks/someday");

    expect(await screen.findByRole("heading", { name: "Someday / maybe" })).toBeInTheDocument();
    expect(await screen.findByText("55 tasks")).toBeInTheDocument();
    expect(screen.getByText("Overflow task 00")).toBeInTheDocument();
    expect(screen.queryByText("Overflow task 54")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Load more tasks" }));

    expect(await screen.findByText("Overflow task 54")).toBeInTheDocument();
    expect(within(screen.getByRole("list", { name: "Tasks" })).getAllByRole("listitem")).toHaveLength(55);
    expect(screen.queryByRole("button", { name: "Load more tasks" })).not.toBeInTheDocument();
    expect(fetch).toHaveBeenCalledWith(expect.stringContaining("cursor=next-page"), expect.anything());
  });

  it("routes Inbox rows, search, and pagination through the canonical projectless projection", async () => {
    const user = userEvent.setup();
    const inboxPage = {
      items: [taskFixture("inbox-1", "Projectless captured task", "inbox")],
      next_cursor: "inbox-next-page",
      has_more: true,
      counts_by_state: { inbox: 2, next: 0, waiting: 0, someday: 0 }
    };
    const inboxSecondPage = {
      items: [taskFixture("inbox-2", "Second projectless task", "inbox")],
      next_cursor: null,
      has_more: false,
      counts_by_state: { inbox: 2, next: 0, waiting: 0, someday: 0 }
    };

    vi.mocked(fetch).mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/tasks?") && url.includes("cursor=inbox-next-page")) {
        return Promise.resolve(jsonResponse(inboxSecondPage));
      }
      if (url.includes("/tasks?")) {
        return Promise.resolve(jsonResponse(inboxPage));
      }
      if (url.includes("/projects")) {
        return Promise.resolve(jsonResponse(projectsResponse));
      }
      if (url.includes("/tags")) {
        return Promise.resolve(jsonResponse(tagsResponse));
      }
      return Promise.resolve(jsonResponse(null));
    });

    renderRoutes("/tasks/inbox?q=shared");

    expect(await screen.findByRole("heading", { name: "Inbox" })).toBeInTheDocument();
    expect(await screen.findByText("2 tasks")).toBeInTheDocument();
    await waitFor(() => {
      expect(fetch).toHaveBeenCalledWith(
        expect.stringContaining("/tasks?state=inbox"),
        expect.anything()
      );
      expect(fetch).toHaveBeenCalledWith(
        expect.stringContaining("unassigned_project=true"),
        expect.anything()
      );
      expect(fetch).toHaveBeenCalledWith(expect.stringContaining("q=shared"), expect.anything());
    });

    await user.click(screen.getByRole("button", { name: "Load more tasks" }));

    expect(await screen.findByText("Second projectless task")).toBeInTheDocument();
    await waitFor(() => {
      expect(fetch).toHaveBeenCalledWith(expect.stringContaining("cursor=inbox-next-page"), expect.anything());
      expect(fetch).toHaveBeenCalledWith(expect.stringContaining("unassigned_project=true"), expect.anything());
    });
  });

  it("keeps the Inbox navigation badge projectless while a Project view is active", async () => {
    const assignedInboxTask = {
      ...taskFixture("assigned-inbox-1", "Assigned inbox task stays in project", "inbox"),
      project_id: "project-onboarding"
    };

    vi.mocked(fetch).mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/tasks?") && url.includes("project_id=project-onboarding")) {
        return Promise.resolve(jsonResponse({
          items: [assignedInboxTask],
          next_cursor: null,
          has_more: false,
          counts_by_state: { inbox: 9, next: 0, waiting: 0, someday: 0 }
        }));
      }
      if (url.includes("/tasks?") && url.includes("state=inbox") && url.includes("unassigned_project=true")) {
        return Promise.resolve(jsonResponse({
          items: [taskFixture("projectless-inbox-1", "Projectless badge sample", "inbox")],
          next_cursor: null,
          has_more: false,
          counts_by_state: { inbox: 4, next: 0, waiting: 0, someday: 0 }
        }));
      }
      if (url.includes("/projects")) {
        return Promise.resolve(jsonResponse(projectsResponse));
      }
      if (url.includes("/tags")) {
        return Promise.resolve(jsonResponse(tagsResponse));
      }
      return Promise.resolve(jsonResponse(null));
    });

    renderRoutes("/projects/project-onboarding");

    expect(await screen.findByRole("heading", { name: "Onboarding drop-off" })).toBeInTheDocument();
    expect(await screen.findByText("Assigned inbox task stays in project")).toBeInTheDocument();
    const sidebar = screen.getByRole("navigation", { name: "Task navigation" });
    expect(await within(sidebar).findByText("4")).toBeInTheDocument();
    expect(within(sidebar).queryByText("9")).not.toBeInTheDocument();
    await waitFor(() => {
      expect(fetch).toHaveBeenCalledWith(expect.stringContaining("project_id=project-onboarding"), expect.anything());
      expect(fetch).toHaveBeenCalledWith(expect.stringContaining("unassigned_project=true"), expect.anything());
    });
  });

  it("creates contextual Waiting, Project and Tag tasks with required organization fields", async () => {
    const user = userEvent.setup();
    const firstView = renderRoutes("/projects/project-onboarding");

    await user.type(await screen.findByLabelText("New task title"), "Follow onboarding metrics");
    await user.click(screen.getByRole("button", { name: "Add task" }));
    await waitFor(() => {
      expect(fetch).toHaveBeenCalledWith(
        expect.stringMatching(/\/tasks$/),
        expect.objectContaining({
          body: expect.stringContaining('"project_id":"project-onboarding"')
        })
      );
    });

    firstView.unmount();
    renderRoutes("/tags/tag-deep-work");
    await user.type(await screen.findByLabelText("New task title"), "Deep work block");
    const addButtons = screen.getAllByRole("button", { name: "Add task" });
    await user.click(addButtons[addButtons.length - 1]);
    await waitFor(() => {
      expect(fetch).toHaveBeenCalledWith(
        expect.stringMatching(/\/tasks$/),
        expect.objectContaining({ body: expect.stringContaining('"tag_ids":["tag-deep-work"]') })
      );
    });
  });

  it("wires project and tag management plus task assignment controls", async () => {
    const user = userEvent.setup();
    renderRoutes("/tasks/next");

    expect(await screen.findByText("Fix onboarding drop-off")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "New project" }));
    await user.type(screen.getByLabelText("New project name"), "Client work{Enter}");
    await waitFor(() => {
      expect(fetch).toHaveBeenCalledWith(
        expect.stringMatching(/\/projects$/),
        expect.objectContaining({ method: "POST", body: expect.stringContaining("Client work") })
      );
    });

    await user.click(screen.getByRole("button", { name: "Project options Onboarding drop-off" }));
    await user.clear(screen.getByLabelText("Project name Onboarding drop-off"));
    await user.type(screen.getByLabelText("Project name Onboarding drop-off"), "Activation{Enter}");
    await waitFor(() => {
      expect(fetch).toHaveBeenCalledWith(
        expect.stringMatching(/\/projects\/project-onboarding$/),
        expect.objectContaining({ method: "PATCH", body: expect.stringContaining("Activation") })
      );
    });

    await user.click(screen.getByRole("button", { name: "Project options Onboarding drop-off" }));
    await user.click(screen.getByRole("button", { name: "Archive" }));
    await waitFor(() => {
      expect(fetch).toHaveBeenCalledWith(
        expect.stringMatching(/\/projects\/project-onboarding\/archive$/),
        expect.objectContaining({ method: "POST" })
      );
    });

    await waitFor(() => {
      expect(fetch).toHaveBeenCalledWith(expect.stringContaining("/tasks?state=next"), expect.anything());
    });

    await user.click(screen.getByRole("button", { name: "New tag" }));
    await user.type(screen.getByLabelText("New tag name"), "errands{Enter}");
    await waitFor(() => {
      expect(fetch).toHaveBeenCalledWith(
        expect.stringMatching(/\/tags$/),
        expect.objectContaining({ method: "POST", body: expect.stringContaining("errands") })
      );
    });

    await user.click(screen.getByRole("button", { name: "Tag options deep-work" }));
    await user.clear(screen.getByLabelText("Tag name deep-work"));
    await user.type(screen.getByLabelText("Tag name deep-work"), "focus{Enter}");
    await waitFor(() => {
      expect(fetch).toHaveBeenCalledWith(
        expect.stringMatching(/\/tags\/tag-deep-work$/),
        expect.objectContaining({ method: "PATCH", body: expect.stringContaining("focus") })
      );
    });

    await user.click(screen.getByRole("button", { name: "Tag options deep-work" }));
    await user.click(screen.getByRole("button", { name: "Delete" }));
    await waitFor(() => {
      expect(fetch).toHaveBeenCalledWith(
        expect.stringMatching(/\/tags\/tag-deep-work\?expected_revision=1$/),
        expect.objectContaining({ method: "DELETE" })
      );
    });

    await user.click(screen.getByRole("link", { name: "Fix onboarding drop-off" }));
    expect(await screen.findByRole("heading", { name: "Task detail" })).toBeInTheDocument();

    await user.selectOptions(await screen.findByLabelText("Project"), "project-launch");
    await user.click(screen.getByLabelText("#calls"));
    await user.click(screen.getByLabelText("#deep-work"));
    await user.click(screen.getByRole("button", { name: "Save task detail" }));

    await waitFor(() => {
      expect(fetch).toHaveBeenCalledWith(
        expect.stringMatching(/\/tasks\/task-1$/),
        expect.objectContaining({ method: "PATCH", body: expect.stringContaining('"project_id":"project-launch"') })
      );
    });
    const saveDetailCall = vi.mocked(fetch).mock.calls.find(
      ([input, init]) => /\/tasks\/task-1$/.test(String(input)) && (init as RequestInit | undefined)?.method === "PATCH"
    );
    expect(JSON.parse(String(saveDetailCall?.[1]?.body))).toMatchObject({ tag_ids: ["tag-calls"] });
  });

  it("returns to Next actions when the active Project or Tag view is archived or deleted", async () => {
    const user = userEvent.setup();
    const projectView = renderRoutes("/projects/project-onboarding");

    expect(await screen.findByRole("heading", { name: "Onboarding drop-off" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Project options Onboarding drop-off" }));
    await user.click(screen.getByRole("button", { name: "Archive" }));
    await waitFor(() => {
      expect(fetch).toHaveBeenCalledWith(expect.stringContaining("/tasks?state=next"), expect.anything());
    });

    projectView.unmount();
    renderRoutes("/tags/tag-deep-work");

    expect(await screen.findByRole("heading", { name: "#deep-work" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Tag options deep-work" }));
    await user.click(screen.getByRole("button", { name: "Delete" }));
    await waitFor(() => {
      expect(fetch).toHaveBeenCalledWith(expect.stringContaining("/tasks?state=next"), expect.anything());
    });
  });

  it("opens task detail and persists priority, subtasks, comments and lifecycle commands", async () => {
    const user = userEvent.setup();
    renderRoutes("/tasks/next/task-1");

    expect(await screen.findByRole("heading", { name: "Task detail" })).toBeInTheDocument();
    await user.selectOptions(await screen.findByLabelText("Priority"), "high");
    await user.type(await screen.findByLabelText("Details"), "Updated detail");
    await user.click(screen.getByRole("button", { name: "Save task detail" }));
    await waitFor(() => {
      expect(fetch).toHaveBeenCalledWith(
        expect.stringMatching(/\/tasks\/task-1$/),
        expect.objectContaining({
          method: "PATCH",
          body: expect.stringContaining('"priority":"high"')
        })
      );
    });

    await user.type(screen.getByLabelText("New subtask title"), "Draft outline");
    await user.click(screen.getByRole("button", { name: "Add subtask" }));
    await waitFor(() => {
      expect(fetch).toHaveBeenCalledWith(
        expect.stringMatching(/\/tasks\/task-1\/subtasks$/),
        expect.objectContaining({ body: expect.stringContaining("Draft outline") })
      );
    });

    await user.type(screen.getByLabelText("New comment"), "Looks good");
    await user.click(screen.getByRole("button", { name: "Add comment" }));
    await waitFor(() => {
      expect(fetch).toHaveBeenCalledWith(
        expect.stringMatching(/\/tasks\/task-1\/comments$/),
        expect.objectContaining({ body: expect.stringContaining("Looks good") })
      );
    });

    await user.click(screen.getByRole("button", { name: "Complete" }));
    await waitFor(() => {
      expect(fetch).toHaveBeenCalledWith(
        expect.stringMatching(/\/tasks\/task-1\/transitions$/),
        expect.objectContaining({ body: expect.stringContaining('"action":"complete"') })
      );
    });
  });

  it("does not steal focus back to the Task detail heading after a save, subtask, comment, or transition mutation refetches the task", async () => {
    const user = userEvent.setup();

    // React Query applies structural sharing: if a refetch resolves to a value
    // that is deep-equal to the previous one, it reuses the SAME object
    // reference for `data`, so an effect keyed on `detailQuery.data` would
    // never re-run and the steal-focus bug would look fixed even when it is
    // not (a false green). A stateless mock that always returns the original
    // fixture falls into exactly that trap. This mock instead tracks mutable
    // task state and reflects every mutation (PATCH/subtask/comment/
    // transition) in the next GET, the way the real backend does, so each
    // refetch genuinely changes `detailQuery.data` and can exercise the bug.
    let currentTask = {
      ...taskResponse.items[0],
      subtasks: [] as Array<{ id: string; title: string; state: string; revision: number }>,
      comments: [] as Array<{ id: string; body: string; actor_id: string }>
    };
    vi.mocked(fetch).mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      const body = init?.body ? JSON.parse(String(init.body)) : undefined;
      if (url.endsWith("/tasks/task-1") && method === "PATCH") {
        currentTask = { ...currentTask, ...body, revision: currentTask.revision + 1 };
        return Promise.resolve(jsonResponse(currentTask));
      }
      if (url.endsWith("/tasks/task-1") && method === "GET") {
        return Promise.resolve(jsonResponse(currentTask));
      }
      if (url.endsWith("/tasks/task-1/subtasks") && method === "POST") {
        const subtask = { id: `subtask-${currentTask.subtasks.length + 1}`, title: body.title, state: "open", revision: 1 };
        currentTask = { ...currentTask, subtasks: [...currentTask.subtasks, subtask] };
        return Promise.resolve(jsonResponse(subtask, 201));
      }
      if (url.endsWith("/tasks/task-1/comments") && method === "POST") {
        const comment = { id: `comment-${currentTask.comments.length + 1}`, body: body.body, actor_id: "user-1" };
        currentTask = { ...currentTask, comments: [...currentTask.comments, comment] };
        return Promise.resolve(jsonResponse(comment, 201));
      }
      if (url.endsWith("/tasks/task-1/transitions") && method === "POST") {
        currentTask = { ...currentTask, state: "completed", revision: currentTask.revision + 1 };
        return Promise.resolve(jsonResponse(currentTask));
      }
      if (url.endsWith("/tasks") || url.includes("/tasks?")) {
        // Completing a Next task removes it from the list projection. The
        // detail panel then swaps from the inline row to its standalone path;
        // that remount must not treat a mutation-driven projection swap as a
        // newly opened detail route and steal focus back to the heading.
        return Promise.resolve(jsonResponse({
          ...taskResponse,
          items: currentTask.state === "completed" ? taskResponse.items.filter((task) => task.id !== "task-1") : taskResponse.items
        }));
      }
      if (url.includes("/projects")) {
        return Promise.resolve(jsonResponse(projectsResponse));
      }
      if (url.includes("/tags")) {
        return Promise.resolve(jsonResponse(tagsResponse));
      }
      return Promise.resolve(jsonResponse(null));
    });

    renderRoutes("/tasks/next/task-1");

    // Before the task list finishes loading, the detail panel renders in its
    // transient "standalone" form (the task isn't in the active projection
    // yet); once the list resolves it swaps to the in-row form, remounting
    // the heading. That swap is unrelated to the bug under test, so let it
    // settle — and re-query the heading by role afterward rather than
    // holding onto an early reference, which the swap would silently make
    // stale (a variable pointing at a since-detached node can never observe
    // a genuine steal-focus regression).
    await screen.findByRole("link", { name: "Fix onboarding drop-off" });
    await waitFor(() => expect(screen.getByRole("heading", { name: "Task detail" })).toHaveFocus());

    await user.selectOptions(await screen.findByLabelText("Priority"), "high");
    await user.click(screen.getByRole("button", { name: "Save task detail" }));
    await waitFor(() => {
      expect(fetch).toHaveBeenCalledWith(expect.stringMatching(/\/tasks\/task-1$/), expect.objectContaining({ method: "PATCH" }));
    });
    // Wait for the refetch to actually land and re-render (the Priority
    // select remounts with the server's confirmed value) before checking
    // focus, so the assertion observes the effect's real post-refetch state.
    await waitFor(() => expect(screen.getByLabelText("Priority")).toHaveValue("high"));
    expect(screen.getByRole("heading", { name: "Task detail" })).not.toHaveFocus();

    await user.type(screen.getByLabelText("New subtask title"), "Draft outline");
    await user.click(screen.getByRole("button", { name: "Add subtask" }));
    await screen.findByText("Draft outline");
    expect(screen.getByRole("heading", { name: "Task detail" })).not.toHaveFocus();

    await user.type(screen.getByLabelText("New comment"), "Looks good");
    await user.click(screen.getByRole("button", { name: "Add comment" }));
    await screen.findByText("Looks good");
    expect(screen.getByRole("heading", { name: "Task detail" })).not.toHaveFocus();

    await user.click(screen.getByRole("button", { name: "Complete" }));
    await screen.findByRole("button", { name: "Reopen to Inbox" });
    expect(screen.getByRole("heading", { name: "Task detail" })).not.toHaveFocus();
  });

  it("keeps direct task detail visible when the task is absent from the active projection", async () => {
    const directTask = taskFixture("task-direct", "Shared task outside Next", "waiting");
    vi.mocked(fetch).mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/tasks/task-direct")) {
        return Promise.resolve(jsonResponse(directTask));
      }
      if (url.includes("/tasks?")) {
        return Promise.resolve(jsonResponse({
          items: [],
          next_cursor: null,
          has_more: false,
          counts_by_state: { inbox: 0, next: 0, waiting: 1, someday: 0 }
        }));
      }
      if (url.includes("/projects")) {
        return Promise.resolve(jsonResponse(projectsResponse));
      }
      if (url.includes("/tags")) {
        return Promise.resolve(jsonResponse(tagsResponse));
      }
      return Promise.resolve(jsonResponse(null));
    });

    renderRoutes("/tasks/next/task-direct");

    expect(await screen.findByRole("heading", { name: "Task detail" })).toBeInTheDocument();
    expect(await screen.findByDisplayValue("Shared task outside Next")).toBeInTheDocument();
    expect(screen.getByText("Next actions is clear")).toBeInTheDocument();
  });

  it("keeps terminal recovery explicit in task detail", async () => {
    const user = userEvent.setup();
    const completedTask = {
      ...taskResponse.items[0],
      state: "completed",
      completed_at: "2026-07-16T10:00:00Z",
      revision: 2
    };

    vi.mocked(fetch).mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/tasks") && url.includes("/transitions")) {
        return Promise.resolve(jsonResponse({ ...completedTask, state: "waiting", waiting_for: "Ada", revision: 3 }));
      }
      if (url.endsWith("/tasks") || url.includes("/tasks?")) {
        return Promise.resolve(jsonResponse({ ...taskResponse, items: [completedTask] }));
      }
      if (url.includes("/tasks/")) {
        return Promise.resolve(jsonResponse(completedTask));
      }
      if (url.includes("/projects")) {
        return Promise.resolve(jsonResponse(projectsResponse));
      }
      if (url.includes("/tags")) {
        return Promise.resolve(jsonResponse(tagsResponse));
      }
      return Promise.resolve(jsonResponse(null));
    });

    renderRoutes("/tasks/next/task-1");

    expect(await screen.findByRole("button", { name: "Reopen to Inbox" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reopen to Next" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reopen to Waiting for" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Move to/i })).not.toBeInTheDocument();

    await user.type(screen.getByLabelText("Waiting for"), "Ada");
    await user.click(screen.getByRole("button", { name: "Reopen to Waiting for" }));

    await waitFor(() => {
      expect(fetch).toHaveBeenCalledWith(
        expect.stringMatching(/\/tasks\/task-1\/transitions$/),
        expect.objectContaining({
          body: expect.stringContaining('"action":"reopen"')
        })
      );
      expect(fetch).toHaveBeenCalledWith(
        expect.stringMatching(/\/tasks\/task-1\/transitions$/),
        expect.objectContaining({
          body: expect.stringContaining('"to_state":"waiting"')
        })
      );
      expect(fetch).toHaveBeenCalledWith(
        expect.stringMatching(/\/tasks\/task-1\/transitions$/),
        expect.objectContaining({
          body: expect.stringContaining('"waiting_for":"Ada"')
        })
      );
    });
  });

  it("opens task detail from a click on the noninteractive card body but not from interactive descendants", async () => {
    const user = userEvent.setup();
    renderRoutes("/tasks/next");

    const row = (await screen.findByRole("link", { name: "Fix onboarding drop-off" })).closest('[role="listitem"]');
    expect(row).not.toBeNull();
    expect(screen.queryByRole("heading", { name: "Task detail" })).not.toBeInTheDocument();

    await user.click(within(row as HTMLElement).getByRole("button", { name: "Complete Fix onboarding drop-off" }));
    expect(screen.queryByRole("heading", { name: "Task detail" })).not.toBeInTheDocument();

    await user.click(row as HTMLElement);
    expect(await screen.findByRole("heading", { name: "Task detail" })).toBeInTheDocument();
  });

  it("preserves filtered task routes while focusing detail and restoring the originating row link", async () => {
    const user = userEvent.setup();
    renderRoutes("/tasks/next?sort=priority&q=Persisted");

    const rowLink = await screen.findByRole("link", { name: "Fix onboarding drop-off" });
    expect(rowLink).toHaveAttribute("href", "/tasks/next/task-1?sort=priority&q=Persisted");
    await user.click(rowLink);

    const heading = await screen.findByRole("heading", { name: "Task detail" });
    await waitFor(() => expect(heading).toHaveFocus());

    await user.click(screen.getByRole("button", { name: "Close" }));
    await waitFor(() => expect(screen.queryByRole("heading", { name: "Task detail" })).not.toBeInTheDocument());
    expect(screen.getByRole("searchbox", { name: "Search tasks" })).toHaveValue("Persisted");
    expect(screen.getByLabelText("Sort tasks")).toHaveValue("priority");
    expect(screen.getByRole("link", { name: "Fix onboarding drop-off" })).toHaveFocus();
  });

  it("focuses the Task detail heading immediately on a direct task detail URL and preserves query params on close", async () => {
    const user = userEvent.setup();
    renderRoutes("/tasks/next/task-1?sort=due");

    const heading = await screen.findByRole("heading", { name: "Task detail" });
    await waitFor(() => expect(heading).toHaveFocus());
    expect(screen.getByLabelText("Sort tasks")).toHaveValue("due");

    await user.click(screen.getByRole("button", { name: "Close" }));
    await waitFor(() => expect(screen.queryByRole("heading", { name: "Task detail" })).not.toBeInTheDocument());
    expect(screen.getByLabelText("Sort tasks")).toHaveValue("due");
  });

  it("restores focus to the list heading when the originating row is absent on close", async () => {
    const user = userEvent.setup();
    const directTask = taskFixture("task-direct", "Shared task outside Next", "waiting");
    vi.mocked(fetch).mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/tasks/task-direct")) {
        return Promise.resolve(jsonResponse(directTask));
      }
      if (url.includes("/tasks?")) {
        return Promise.resolve(jsonResponse({
          items: [],
          next_cursor: null,
          has_more: false,
          counts_by_state: { inbox: 0, next: 0, waiting: 1, someday: 0 }
        }));
      }
      if (url.includes("/projects")) {
        return Promise.resolve(jsonResponse(projectsResponse));
      }
      if (url.includes("/tags")) {
        return Promise.resolve(jsonResponse(tagsResponse));
      }
      return Promise.resolve(jsonResponse(null));
    });

    renderRoutes("/tasks/next/task-direct");
    await screen.findByRole("heading", { name: "Task detail" });

    await user.click(screen.getByRole("button", { name: "Close" }));
    await waitFor(() => expect(screen.queryByRole("heading", { name: "Task detail" })).not.toBeInTheDocument());
    expect(screen.getByRole("heading", { name: "Next actions" })).toHaveFocus();
  });

  it("shows an honest, noninteractive Agent placeholder in task detail", async () => {
    renderRoutes("/tasks/next/task-1");
    await screen.findByRole("heading", { name: "Task detail" });

    const agentZone = await screen.findByTestId("task-detail-agent");
    expect(within(agentZone).getByRole("heading", { name: "Agent" })).toBeInTheDocument();
    const soon = within(agentZone).getByText("Soon");
    expect(soon).toHaveAttribute("aria-hidden", "true");
    expect(within(agentZone).getByText("Coming soon")).toBeInTheDocument();
    expect(within(agentZone).queryByRole("button")).not.toBeInTheDocument();
    expect(within(agentZone).queryByRole("link")).not.toBeInTheDocument();
  });

  it("groups tasks by project through a URL-backed toggle, draining every cursor page before rendering complete groups", async () => {
    const user = userEvent.setup();
    const launchTask = { ...taskFixture("group-1", "Ship v2 changelog", "next"), project_id: "project-launch" };
    const onboardingTask = { ...taskFixture("group-2", "Audit onboarding funnel", "next"), project_id: "project-onboarding" };
    const unassignedTask = taskFixture("group-3", "Read industry report", "next");
    const secondPageTask = { ...taskFixture("group-4", "Second page launch task", "next"), project_id: "project-launch" };

    vi.mocked(fetch).mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/tasks?") && url.includes("cursor=group-next-page")) {
        return Promise.resolve(jsonResponse({
          items: [secondPageTask],
          next_cursor: null,
          has_more: false,
          counts_by_state: { inbox: 0, next: 4, waiting: 0, someday: 0 }
        }));
      }
      if (url.includes("/tasks?")) {
        return Promise.resolve(jsonResponse({
          items: [launchTask, onboardingTask, unassignedTask],
          next_cursor: "group-next-page",
          has_more: true,
          counts_by_state: { inbox: 0, next: 4, waiting: 0, someday: 0 }
        }));
      }
      if (url.includes("/projects")) {
        return Promise.resolve(jsonResponse(projectsResponse));
      }
      if (url.includes("/tags")) {
        return Promise.resolve(jsonResponse(tagsResponse));
      }
      return Promise.resolve(jsonResponse(null));
    });

    renderRoutes("/tasks/next");

    expect(await screen.findByText("Ship v2 changelog")).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "Load more tasks" })).toBeInTheDocument();
    expect(screen.queryByTestId("grouped-task-list")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Group by project" }));
    expect(screen.getByRole("button", { name: "Group by project" })).toHaveAttribute("aria-pressed", "true");

    const groupedList = await screen.findByTestId("grouped-task-list");
    expect(await within(groupedList).findByText("Second page launch task")).toBeInTheDocument();
    await waitFor(() => {
      expect(fetch).toHaveBeenCalledWith(expect.stringContaining("cursor=group-next-page"), expect.anything());
    });

    const headings = within(groupedList).getAllByRole("heading", { level: 2 });
    expect(headings.map((heading) => heading.textContent)).toEqual([
      expect.stringContaining("Launch v2"),
      expect.stringContaining("Onboarding drop-off"),
      expect.stringContaining("No project")
    ]);

    expect(screen.queryByRole("button", { name: "Load more tasks" })).not.toBeInTheDocument();

    const launchGroup = within(groupedList).getByRole("heading", { name: /Launch v2/ }).closest("section") as HTMLElement;
    expect(within(launchGroup).getAllByText("Launch v2")).toHaveLength(1);
    const rowLink = within(launchGroup).getByRole("link", { name: "Ship v2 changelog" });
    expect(rowLink.getAttribute("href")).toContain("group=project");

    await user.click(screen.getByRole("button", { name: "Group by project" }));
    expect(screen.queryByTestId("grouped-task-list")).not.toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "Load more tasks" })).toBeInTheDocument();
  });

  it("opens exactly one detail surface for a grouped task delivered on a later cursor page", async () => {
    const launchTask = { ...taskFixture("group-1", "Ship v2 changelog", "next"), project_id: "project-launch" };
    const secondPageTask = { ...taskFixture("group-4", "Second page launch task", "next"), project_id: "project-launch" };

    vi.mocked(fetch).mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/tasks/group-4")) {
        return Promise.resolve(jsonResponse(secondPageTask));
      }
      if (url.includes("/tasks?") && url.includes("cursor=group-next-page")) {
        return Promise.resolve(jsonResponse({
          items: [secondPageTask],
          next_cursor: null,
          has_more: false,
          counts_by_state: { inbox: 0, next: 2, waiting: 0, someday: 0 }
        }));
      }
      if (url.includes("/tasks?")) {
        return Promise.resolve(jsonResponse({
          items: [launchTask],
          next_cursor: "group-next-page",
          has_more: true,
          counts_by_state: { inbox: 0, next: 2, waiting: 0, someday: 0 }
        }));
      }
      if (url.includes("/projects")) {
        return Promise.resolve(jsonResponse(projectsResponse));
      }
      if (url.includes("/tags")) {
        return Promise.resolve(jsonResponse(tagsResponse));
      }
      return Promise.resolve(jsonResponse(null));
    });

    renderRoutes("/tasks/next/group-4?group=project");

    const groupedList = await screen.findByTestId("grouped-task-list");
    expect(await within(groupedList).findByRole("link", { name: "Second page launch task" })).toBeInTheDocument();

    const detailHeadings = await screen.findAllByRole("heading", { name: "Task detail" });
    expect(detailHeadings).toHaveLength(1);
    expect(screen.getAllByLabelText("Title")).toHaveLength(1);
  });

  it("issues only the all-pages request for a direct grouped URL load, without a redundant ordinary list query", async () => {
    vi.mocked(fetch).mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/tasks?")) {
        return Promise.resolve(jsonResponse(taskResponse));
      }
      if (url.includes("/projects")) {
        return Promise.resolve(jsonResponse(projectsResponse));
      }
      if (url.includes("/tags")) {
        return Promise.resolve(jsonResponse(tagsResponse));
      }
      return Promise.resolve(jsonResponse(null));
    });

    renderRoutes("/tasks/next?group=project");

    expect(await screen.findByTestId("grouped-task-list")).toBeInTheDocument();

    const taskListCalls = vi
      .mocked(fetch)
      .mock.calls.map(([input]) => String(input))
      .filter((url) => url.includes("/tasks?") && url.includes("state=next"));
    expect(taskListCalls.length).toBeGreaterThan(0);
    expect(taskListCalls.every((url) => url.includes("limit=200"))).toBe(true);
  });

  it("gives each grouped task list a project-specific accessible name instead of a generic 'Tasks' label", async () => {
    const launchTask = { ...taskFixture("group-1", "Ship v2 changelog", "next"), project_id: "project-launch" };
    const unassignedTask = taskFixture("group-3", "Read industry report", "next");

    vi.mocked(fetch).mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/tasks?")) {
        return Promise.resolve(jsonResponse({
          items: [launchTask, unassignedTask],
          next_cursor: null,
          has_more: false,
          counts_by_state: { inbox: 0, next: 2, waiting: 0, someday: 0 }
        }));
      }
      if (url.includes("/projects")) {
        return Promise.resolve(jsonResponse(projectsResponse));
      }
      if (url.includes("/tags")) {
        return Promise.resolve(jsonResponse(tagsResponse));
      }
      return Promise.resolve(jsonResponse(null));
    });

    renderRoutes("/tasks/next?group=project");

    const groupedList = await screen.findByTestId("grouped-task-list");
    await within(groupedList).findByText("Ship v2 changelog");
    expect(within(groupedList).getByRole("list", { name: "Tasks in Launch v2" })).toBeInTheDocument();
    expect(within(groupedList).getByRole("list", { name: /no project/i })).toBeInTheDocument();
    expect(within(groupedList).queryByRole("list", { name: "Tasks" })).not.toBeInTheDocument();
  });

  it("reads Group by project from the URL on load and hides the control on Project pages", async () => {
    vi.mocked(fetch).mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/tasks?")) {
        return Promise.resolve(jsonResponse(taskResponse));
      }
      if (url.includes("/projects")) {
        return Promise.resolve(jsonResponse(projectsResponse));
      }
      if (url.includes("/tags")) {
        return Promise.resolve(jsonResponse(tagsResponse));
      }
      return Promise.resolve(jsonResponse(null));
    });

    const groupedView = renderRoutes("/tasks/next?group=project");
    expect(await screen.findByTestId("grouped-task-list")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Group by project" })).toHaveAttribute("aria-pressed", "true");

    groupedView.unmount();
    renderRoutes("/projects/project-onboarding");
    await screen.findByRole("heading", { name: "Onboarding drop-off" });
    expect(screen.queryByRole("button", { name: "Group by project" })).not.toBeInTheDocument();
  });

  it("reports the complete drained count on a direct grouped Tag route instead of the disabled first-page total", async () => {
    const firstTagTask = { ...taskFixture("tag-group-1", "Draft outreach email", "next"), project_id: "project-launch", tag_ids: ["tag-deep-work"] };
    const secondTagTask = { ...taskFixture("tag-group-2", "Second page outreach task", "next"), project_id: "project-onboarding", tag_ids: ["tag-deep-work"] };

    vi.mocked(fetch).mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/tasks?") && url.includes("tag_id=tag-deep-work") && url.includes("cursor=tag-next-page")) {
        return Promise.resolve(jsonResponse({
          items: [secondTagTask],
          next_cursor: null,
          has_more: false,
          counts_by_state: { inbox: 0, next: 2, waiting: 0, someday: 0 }
        }));
      }
      if (url.includes("/tasks?") && url.includes("tag_id=tag-deep-work")) {
        return Promise.resolve(jsonResponse({
          items: [firstTagTask],
          next_cursor: "tag-next-page",
          has_more: true,
          counts_by_state: { inbox: 0, next: 2, waiting: 0, someday: 0 }
        }));
      }
      if (url.includes("/tasks?")) {
        return Promise.resolve(jsonResponse(taskResponse));
      }
      if (url.includes("/projects")) {
        return Promise.resolve(jsonResponse(projectsResponse));
      }
      if (url.includes("/tags")) {
        return Promise.resolve(jsonResponse(tagsResponse));
      }
      return Promise.resolve(jsonResponse(null));
    });

    renderRoutes("/tags/tag-deep-work?group=project");

    const groupedList = await screen.findByTestId("grouped-task-list");
    expect(await within(groupedList).findByText("Second page outreach task")).toBeInTheDocument();
    await waitFor(() => {
      expect(fetch).toHaveBeenCalledWith(expect.stringContaining("cursor=tag-next-page"), expect.anything());
    });
    expect(await screen.findByText("2 tasks")).toBeInTheDocument();
    expect(screen.queryByText("0 tasks")).not.toBeInTheDocument();
  });

  it("reports the complete drained count on a direct grouped date-view route instead of the disabled first-page total", async () => {
    const firstOverdueTask = { ...taskFixture("overdue-group-1", "Chase overdue invoice", "next"), project_id: "project-launch", due_date: "2026-01-01" };
    const secondOverdueTask = { ...taskFixture("overdue-group-2", "Second page overdue task", "next"), project_id: "project-onboarding", due_date: "2026-01-02" };

    vi.mocked(fetch).mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/tasks?") && url.includes("due_before=") && url.includes("cursor=overdue-next-page")) {
        return Promise.resolve(jsonResponse({
          items: [secondOverdueTask],
          next_cursor: null,
          has_more: false,
          counts_by_state: { inbox: 0, next: 2, waiting: 0, someday: 0 }
        }));
      }
      if (url.includes("/tasks?") && url.includes("due_before=")) {
        return Promise.resolve(jsonResponse({
          items: [firstOverdueTask],
          next_cursor: "overdue-next-page",
          has_more: true,
          counts_by_state: { inbox: 0, next: 2, waiting: 0, someday: 0 }
        }));
      }
      if (url.includes("/tasks?")) {
        return Promise.resolve(jsonResponse(taskResponse));
      }
      if (url.includes("/projects")) {
        return Promise.resolve(jsonResponse(projectsResponse));
      }
      if (url.includes("/tags")) {
        return Promise.resolve(jsonResponse(tagsResponse));
      }
      return Promise.resolve(jsonResponse(null));
    });

    renderRoutes("/tasks/overdue?group=project");

    const groupedList = await screen.findByTestId("grouped-task-list");
    expect(await within(groupedList).findByText("Second page overdue task")).toBeInTheDocument();
    await waitFor(() => {
      expect(fetch).toHaveBeenCalledWith(expect.stringContaining("cursor=overdue-next-page"), expect.anything());
    });
    expect(await screen.findByText("2 tasks")).toBeInTheDocument();
    expect(screen.queryByText("0 tasks")).not.toBeInTheDocument();
  });

  it("replaces the stale flat first-page subtitle count with the complete grouped total after toggling Group by project on a Tag route", async () => {
    const user = userEvent.setup();
    const flatFirstPageTask = { ...taskFixture("tag-toggle-1", "Flat page task", "next"), tag_ids: ["tag-deep-work"] };
    const groupedFirstTask = { ...taskFixture("tag-toggle-1", "Flat page task", "next"), project_id: "project-launch", tag_ids: ["tag-deep-work"] };
    const groupedSecondTask = { ...taskFixture("tag-toggle-2", "Second grouped tag task", "next"), project_id: "project-onboarding", tag_ids: ["tag-deep-work"] };

    vi.mocked(fetch).mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/tasks?") && url.includes("tag_id=tag-deep-work") && url.includes("limit=200") && url.includes("cursor=tag-toggle-next")) {
        return Promise.resolve(jsonResponse({
          items: [groupedSecondTask],
          next_cursor: null,
          has_more: false,
          counts_by_state: { inbox: 0, next: 2, waiting: 0, someday: 0 }
        }));
      }
      if (url.includes("/tasks?") && url.includes("tag_id=tag-deep-work") && url.includes("limit=200")) {
        return Promise.resolve(jsonResponse({
          items: [groupedFirstTask],
          next_cursor: "tag-toggle-next",
          has_more: true,
          counts_by_state: { inbox: 0, next: 2, waiting: 0, someday: 0 }
        }));
      }
      if (url.includes("/tasks?") && url.includes("tag_id=tag-deep-work")) {
        return Promise.resolve(jsonResponse({
          items: [flatFirstPageTask],
          next_cursor: null,
          has_more: false,
          counts_by_state: { inbox: 0, next: 1, waiting: 0, someday: 0 }
        }));
      }
      if (url.includes("/tasks?")) {
        return Promise.resolve(jsonResponse(taskResponse));
      }
      if (url.includes("/projects")) {
        return Promise.resolve(jsonResponse(projectsResponse));
      }
      if (url.includes("/tags")) {
        return Promise.resolve(jsonResponse(tagsResponse));
      }
      return Promise.resolve(jsonResponse(null));
    });

    renderRoutes("/tags/tag-deep-work");

    expect(await screen.findByText("Flat page task")).toBeInTheDocument();
    expect(await screen.findByText("1 task")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Group by project" }));

    const groupedList = await screen.findByTestId("grouped-task-list");
    expect(await within(groupedList).findByText("Second grouped tag task")).toBeInTheDocument();
    await waitFor(() => {
      expect(fetch).toHaveBeenCalledWith(expect.stringContaining("cursor=tag-toggle-next"), expect.anything());
    });
    expect(await screen.findByText("2 tasks")).toBeInTheDocument();
    expect(screen.queryByText("1 task")).not.toBeInTheDocument();
  });

  it("shows an aggregate error with retry when draining pages for Group by project fails", async () => {
    const user = userEvent.setup();
    let groupedAttempts = 0;
    vi.mocked(fetch).mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/tasks?") && url.includes("limit=200")) {
        groupedAttempts += 1;
        if (groupedAttempts === 1) {
          return Promise.reject(new Error("network down"));
        }
        return Promise.resolve(jsonResponse(taskResponse));
      }
      if (url.endsWith("/tasks") || url.includes("/tasks?")) {
        return Promise.resolve(jsonResponse(taskResponse));
      }
      if (url.includes("/projects")) {
        return Promise.resolve(jsonResponse(projectsResponse));
      }
      if (url.includes("/tags")) {
        return Promise.resolve(jsonResponse(tagsResponse));
      }
      return Promise.resolve(jsonResponse(null));
    });

    renderRoutes("/tasks/next");
    await user.click(await screen.findByRole("button", { name: "Group by project" }));

    expect(await screen.findByText(/We couldn't load tasks/i)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByTestId("grouped-task-list")).toBeInTheDocument();
  });

  it("renders real Waiting metadata on Waiting rows instead of a fabricated status", async () => {
    const waitingTask = {
      ...taskFixture("waiting-1", "Confirm vendor contract", "waiting"),
      waiting_for: "Legal sign-off from Dana",
      waiting_since: "2026-07-10T09:00:00Z"
    };

    vi.mocked(fetch).mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/tasks?")) {
        return Promise.resolve(jsonResponse({
          items: [waitingTask],
          next_cursor: null,
          has_more: false,
          counts_by_state: { inbox: 0, next: 0, waiting: 1, someday: 0 }
        }));
      }
      if (url.includes("/projects")) {
        return Promise.resolve(jsonResponse(projectsResponse));
      }
      if (url.includes("/tags")) {
        return Promise.resolve(jsonResponse(tagsResponse));
      }
      return Promise.resolve(jsonResponse(null));
    });

    renderRoutes("/tasks/waiting");

    expect(await screen.findByText("Confirm vendor contract")).toBeInTheDocument();
    expect(screen.getByText(/Waiting on Legal sign-off from Dana/)).toBeInTheDocument();
    expect(screen.getByText(/since Jul 10/)).toBeInTheDocument();
  });

  it("shows the truthful non-terminal total instead of the first loaded page on a flat Project route with more pages remaining", async () => {
    const firstPageTasks = Array.from({ length: 50 }, (_, index) => ({
      ...taskFixture(`proj-page-${index}`, `Project task ${String(index).padStart(2, "0")}`, "next"),
      project_id: "project-onboarding"
    }));

    vi.mocked(fetch).mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/tasks?") && url.includes("project_id=project-onboarding")) {
        return Promise.resolve(jsonResponse({
          items: firstPageTasks,
          next_cursor: "proj-next-page",
          has_more: true,
          counts_by_state: { inbox: 80, next: 126, waiting: 0, someday: 0 }
        }));
      }
      if (url.includes("/projects")) {
        return Promise.resolve(jsonResponse(projectsResponse));
      }
      if (url.includes("/tags")) {
        return Promise.resolve(jsonResponse(tagsResponse));
      }
      return Promise.resolve(jsonResponse(taskResponse));
    });

    renderRoutes("/projects/project-onboarding");

    expect(await screen.findByRole("heading", { name: "Onboarding drop-off" })).toBeInTheDocument();
    expect(await screen.findByText("206 tasks")).toBeInTheDocument();
    expect(screen.queryByText("50 tasks")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Load more tasks" })).toBeInTheDocument();
  });

  it("shows the truthful non-terminal total instead of the first loaded page on a flat Tag route with an active search filter", async () => {
    const firstPageTasks = Array.from({ length: 50 }, (_, index) => ({
      ...taskFixture(`tag-q-page-${index}`, `Outreach task ${String(index).padStart(2, "0")}`, "next"),
      tag_ids: ["tag-deep-work"]
    }));

    vi.mocked(fetch).mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/tasks?") && url.includes("tag_id=tag-deep-work") && url.includes("q=call")) {
        return Promise.resolve(jsonResponse({
          items: firstPageTasks,
          next_cursor: "tag-q-next-page",
          has_more: true,
          counts_by_state: { inbox: 40, next: 63, waiting: 0, someday: 0 }
        }));
      }
      if (url.includes("/projects")) {
        return Promise.resolve(jsonResponse(projectsResponse));
      }
      if (url.includes("/tags")) {
        return Promise.resolve(jsonResponse(tagsResponse));
      }
      return Promise.resolve(jsonResponse(taskResponse));
    });

    renderRoutes("/tags/tag-deep-work?q=call");

    expect(await screen.findByRole("heading", { name: "#deep-work" })).toBeInTheDocument();
    expect(await screen.findByText("103 tasks")).toBeInTheDocument();
    expect(screen.queryByText("50 tasks")).not.toBeInTheDocument();
  });

  it("shows the truthful non-terminal total instead of the first loaded page on a flat date-view route with more pages remaining", async () => {
    const firstPageTasks = Array.from({ length: 50 }, (_, index) =>
      taskFixture(`overdue-page-${index}`, `Overdue task ${String(index).padStart(2, "0")}`, "next")
    );

    vi.mocked(fetch).mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/tasks?") && url.includes("due_before=")) {
        return Promise.resolve(jsonResponse({
          items: firstPageTasks,
          next_cursor: "overdue-next-page",
          has_more: true,
          counts_by_state: { inbox: 0, next: 120, waiting: 0, someday: 0 }
        }));
      }
      if (url.includes("/projects")) {
        return Promise.resolve(jsonResponse(projectsResponse));
      }
      if (url.includes("/tags")) {
        return Promise.resolve(jsonResponse(tagsResponse));
      }
      return Promise.resolve(jsonResponse(taskResponse));
    });

    renderRoutes("/tasks/overdue");

    expect(await screen.findByRole("heading", { name: "Overdue" })).toBeInTheDocument();
    expect(await screen.findByText("120 tasks")).toBeInTheDocument();
    expect(screen.queryByText("50 tasks")).not.toBeInTheDocument();
  });

  it("falls back to loaded-subset '+' copy when terminal tasks are included, then shows the exact count once fully loaded", async () => {
    const user = userEvent.setup();
    const openFirstPage = Array.from({ length: 50 }, (_, index) => ({
      ...taskFixture(`proj-open-${index}`, `Open task ${String(index).padStart(2, "0")}`, "next"),
      project_id: "project-onboarding"
    }));
    const terminalFirstPage = Array.from({ length: 50 }, (_, index) => ({
      ...taskFixture(`proj-term-${index}`, `Terminal-inclusive task ${String(index).padStart(2, "0")}`, "next"),
      project_id: "project-onboarding"
    }));
    const terminalSecondPage = Array.from({ length: 12 }, (_, index) => ({
      ...taskFixture(`proj-term-${index + 50}`, `Terminal-inclusive task ${String(index + 50).padStart(2, "0")}`, "completed"),
      project_id: "project-onboarding"
    }));

    vi.mocked(fetch).mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (
        url.includes("/tasks?") &&
        url.includes("project_id=project-onboarding") &&
        url.includes("include_completed=true") &&
        url.includes("cursor=term-next-page")
      ) {
        return Promise.resolve(jsonResponse({
          items: terminalSecondPage,
          next_cursor: null,
          has_more: false,
          counts_by_state: { inbox: 20, next: 40, waiting: 0, someday: 0 }
        }));
      }
      if (
        url.includes("/tasks?") &&
        url.includes("project_id=project-onboarding") &&
        url.includes("include_completed=true")
      ) {
        return Promise.resolve(jsonResponse({
          items: terminalFirstPage,
          next_cursor: "term-next-page",
          has_more: true,
          counts_by_state: { inbox: 20, next: 40, waiting: 0, someday: 0 }
        }));
      }
      if (url.includes("/tasks?") && url.includes("project_id=project-onboarding")) {
        return Promise.resolve(jsonResponse({
          items: openFirstPage,
          next_cursor: "proj-next-page",
          has_more: true,
          counts_by_state: { inbox: 20, next: 40, waiting: 0, someday: 0 }
        }));
      }
      if (url.includes("/projects")) {
        return Promise.resolve(jsonResponse(projectsResponse));
      }
      if (url.includes("/tags")) {
        return Promise.resolve(jsonResponse(tagsResponse));
      }
      return Promise.resolve(jsonResponse(taskResponse));
    });

    renderRoutes("/projects/project-onboarding");

    expect(await screen.findByRole("heading", { name: "Onboarding drop-off" })).toBeInTheDocument();
    expect(await screen.findByText("60 tasks")).toBeInTheDocument();

    await user.click(screen.getByRole("checkbox", { name: "Show terminal tasks" }));

    expect(await screen.findByText("50+ tasks")).toBeInTheDocument();
    expect(screen.queryByText("60 tasks")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Load more tasks" }));

    expect(await screen.findByText("62 tasks")).toBeInTheDocument();
    expect(screen.queryByText("50+ tasks")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Load more tasks" })).not.toBeInTheDocument();
  });

  it("shows the truthful terminal-inclusive subtitle count on a flat state route instead of the open-only state count", async () => {
    const user = userEvent.setup();
    const openTasks = Array.from({ length: 6 }, (_, index) => taskFixture(`next-open-${index}`, `Open next task ${index}`, "next"));
    const terminalInclusiveTasks = [
      ...openTasks,
      taskFixture("next-done-1", "Completed next task 1", "completed"),
      taskFixture("next-done-2", "Completed next task 2", "completed")
    ];

    vi.mocked(fetch).mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/tasks?") && url.includes("state=next") && url.includes("include_completed=true")) {
        return Promise.resolve(jsonResponse({
          items: terminalInclusiveTasks,
          next_cursor: null,
          has_more: false,
          counts_by_state: { inbox: 0, next: 6, waiting: 0, someday: 0 }
        }));
      }
      if (url.includes("/tasks?") && url.includes("state=next")) {
        return Promise.resolve(jsonResponse({
          items: openTasks,
          next_cursor: null,
          has_more: false,
          counts_by_state: { inbox: 0, next: 6, waiting: 0, someday: 0 }
        }));
      }
      if (url.includes("/projects")) {
        return Promise.resolve(jsonResponse(projectsResponse));
      }
      if (url.includes("/tags")) {
        return Promise.resolve(jsonResponse(tagsResponse));
      }
      return Promise.resolve(jsonResponse(taskResponse));
    });

    renderRoutes("/tasks/next");

    expect(await screen.findByRole("heading", { name: "Next actions" })).toBeInTheDocument();
    expect(await screen.findByText("6 tasks")).toBeInTheDocument();

    await user.click(screen.getByRole("checkbox", { name: "Show terminal tasks" }));

    expect(await screen.findByText("Completed next task 2")).toBeInTheDocument();
    // The full terminal-inclusive projection has 8 loaded rows with no further
    // pages; the subtitle must report that truthful drained total, not the
    // open-only `next` state count (6) which ignores the completed rows now
    // visible in the list.
    expect(await screen.findByText("8 tasks")).toBeInTheDocument();
    expect(screen.queryByText("6 tasks")).not.toBeInTheDocument();
  });

  it("keeps the flat truthful subtitle and the grouped drained subtitle in agreement when toggling Group by project on a Tag route with more pages remaining", async () => {
    const user = userEvent.setup();
    const flatFirstTask = { ...taskFixture("tag-consist-1", "First tag task", "next"), project_id: "project-launch", tag_ids: ["tag-deep-work"] };
    const flatSecondTask = { ...taskFixture("tag-consist-2", "Second tag task", "next"), project_id: "project-onboarding", tag_ids: ["tag-deep-work"] };
    const groupedThirdTask = { ...taskFixture("tag-consist-3", "Third tag task", "next"), project_id: "project-onboarding", tag_ids: ["tag-deep-work"] };

    vi.mocked(fetch).mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/tasks?") && url.includes("tag_id=tag-deep-work") && url.includes("limit=200") && url.includes("cursor=tag-consist-next")) {
        return Promise.resolve(jsonResponse({
          items: [groupedThirdTask],
          next_cursor: null,
          has_more: false,
          counts_by_state: { inbox: 0, next: 3, waiting: 0, someday: 0 }
        }));
      }
      if (url.includes("/tasks?") && url.includes("tag_id=tag-deep-work") && url.includes("limit=200")) {
        return Promise.resolve(jsonResponse({
          items: [flatFirstTask, flatSecondTask],
          next_cursor: "tag-consist-next",
          has_more: true,
          counts_by_state: { inbox: 0, next: 3, waiting: 0, someday: 0 }
        }));
      }
      if (url.includes("/tasks?") && url.includes("tag_id=tag-deep-work")) {
        return Promise.resolve(jsonResponse({
          items: [flatFirstTask, flatSecondTask],
          next_cursor: "tag-consist-flat-next",
          has_more: true,
          counts_by_state: { inbox: 0, next: 3, waiting: 0, someday: 0 }
        }));
      }
      if (url.includes("/projects")) {
        return Promise.resolve(jsonResponse(projectsResponse));
      }
      if (url.includes("/tags")) {
        return Promise.resolve(jsonResponse(tagsResponse));
      }
      return Promise.resolve(jsonResponse(taskResponse));
    });

    renderRoutes("/tags/tag-deep-work");

    expect(await screen.findByText("First tag task")).toBeInTheDocument();
    expect(await screen.findByText("3 tasks")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Load more tasks" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Group by project" }));

    const groupedList = await screen.findByTestId("grouped-task-list");
    expect(await within(groupedList).findByText("Third tag task")).toBeInTheDocument();
    expect(await screen.findByText("3 tasks")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Load more tasks" })).not.toBeInTheDocument();
  });
});
