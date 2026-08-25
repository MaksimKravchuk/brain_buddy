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
    expect(screen.getByRole("button", { name: "Thinking Mode — Coming soon" })).toBeDisabled();
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

  it("aligns task rows and the add-task affordance with the canonical design tokens", async () => {
    renderRoutes("/tasks/next");

    const rowTitle = await screen.findByText("Fix onboarding drop-off");
    const row = rowTitle.closest("article");
    expect(row).not.toBeNull();
    expect(row).toHaveClass("rounded-[12px]", "px-3.5", "py-[7px]", "shadow-soft", "transition-all", "duration-200", "ease-smooth");

    // The per-row project column is gone (prototype default); the group heading
    // carries the project name instead.
    expect(within(row as HTMLElement).queryByText("Onboarding drop-off")).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 2, name: "Onboarding drop-off" })).toBeInTheDocument();

    const addTaskForm = screen.getByLabelText("New task title").closest("form");
    expect(addTaskForm).toHaveClass("rounded-[12px]", "border-dashed");
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

  it("preserves owner connection reads when the external-agent relay rollout is off", async () => {
    renderRoutes("/settings/agents");

    expect(await screen.findByRole("heading", { name: "Connected agents" })).toBeInTheDocument();
    await waitFor(() => {
      expect(fetch).toHaveBeenCalledWith(
        expect.stringContaining("/agent-connections"),
        expect.objectContaining({ method: "GET" })
      );
    });
    expect(screen.queryByRole("form", { name: /add an agent/i })).not.toBeInTheDocument();
  });

  it("keeps direct CRT routes inert until the feature is available", async () => {
    renderRoutes("/crt/demo-tree");

    expect(await screen.findByRole("heading", { name: "Thinking Mode" })).toBeInTheDocument();
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

  it("groups Next actions by project on demand, sinking unassigned tasks to the bottom", async () => {
    const user = userEvent.setup();
    // Deliberately interleaved and unassigned-first, so passing this proves the
    // grouping reorders rather than the fixture already being in group order.
    const grouped = [
      { ...taskFixture("t1", "Unassigned first"), project_id: null, order_key: 1 },
      { ...taskFixture("t2", "Launch one"), project_id: "project-launch", order_key: 2 },
      { ...taskFixture("t3", "Onboarding one"), project_id: "project-onboarding", order_key: 3 },
      { ...taskFixture("t4", "Launch two"), project_id: "project-launch", order_key: 4 }
    ];
    vi.mocked(fetch).mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/tasks") || url.includes("/tasks?")) {
        return Promise.resolve(jsonResponse({ ...taskResponse, items: grouped }));
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
    expect(await screen.findByRole("heading", { name: "Next actions" })).toBeInTheDocument();

    // Grouping is the default view, first-seen project order is preserved and
    // "No project" sinks to the bottom, even though the unassigned task came
    // first in the response.
    const groupHeadings = await screen.findAllByRole("heading", { level: 2 });
    expect(groupHeadings.map((heading) => heading.textContent)).toEqual([
      "Launch v2",
      "Onboarding drop-off",
      "No project"
    ]);

    // Both Launch tasks collapse into one group rather than repeating the heading.
    const launchGroup = screen.getByRole("list", { name: "Launch v2" });
    expect(within(launchGroup).getAllByRole("listitem")).toHaveLength(2);
    // The per-row project column is redundant once the heading carries it.
    expect(within(launchGroup).queryByText("Launch v2")).not.toBeInTheDocument();

    // Toggling off restores the flat list and survives in the URL as group=off.
    await user.click(screen.getByRole("button", { name: "Group by project" }));
    expect(screen.queryByRole("list", { name: "Launch v2" })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "No project" })).not.toBeInTheDocument();
    expect(screen.getByRole("list", { name: "Tasks" })).toBeInTheDocument();

    // Toggling back on regroups.
    await user.click(screen.getByRole("button", { name: "Group by project" }));
    expect(await screen.findByRole("list", { name: "Launch v2" })).toBeInTheDocument();
  });

  it("hides the grouping toggle where every task would share one heading", async () => {
    renderRoutes("/tasks/inbox");

    expect(await screen.findByRole("heading", { name: "Inbox" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Group by project" })).not.toBeInTheDocument();
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
    // Every task is projectless, so the default grouping shows one group list.
    expect(within(screen.getByRole("list", { name: "No project" })).getAllByRole("listitem")).toHaveLength(55);
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
    // The Inbox pane leads with the prototype's processing hint instead of a count.
    expect(await screen.findByText("Process these — decide the next action for each.")).toBeInTheDocument();
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

    // Panel fields save on change, carrying the task's expected revision.
    await user.selectOptions(await screen.findByLabelText("Project"), "project-launch");
    await waitFor(() => {
      expect(fetch).toHaveBeenCalledWith(
        expect.stringMatching(/\/tasks\/task-1$/),
        expect.objectContaining({ method: "PATCH", body: expect.stringContaining('"project_id":"project-launch"') })
      );
    });

    await user.click(screen.getByLabelText("#calls"));
    await waitFor(() => {
      const patchCalls = vi
        .mocked(fetch)
        .mock.calls.filter(
          ([input, init]) => /\/tasks\/task-1$/.test(String(input)) && (init as RequestInit | undefined)?.method === "PATCH"
        );
      const tagCall = patchCalls[patchCalls.length - 1];
      expect(JSON.parse(String(tagCall?.[1]?.body))).toMatchObject({ tag_ids: ["tag-deep-work", "tag-calls"] });
    });
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
    await waitFor(() => {
      expect(fetch).toHaveBeenCalledWith(
        expect.stringMatching(/\/tasks\/task-1$/),
        expect.objectContaining({
          method: "PATCH",
          body: expect.stringContaining('"priority":"high"')
        })
      );
    });

    await user.type(await screen.findByLabelText("Details"), "Updated detail");
    await user.tab();
    await waitFor(() => {
      expect(fetch).toHaveBeenCalledWith(
        expect.stringMatching(/\/tasks\/task-1$/),
        expect.objectContaining({
          method: "PATCH",
          body: expect.stringContaining('"details":"Updated detail"')
        })
      );
    });

    await user.type(screen.getByLabelText("New subtask title"), "Draft outline{Enter}");
    await waitFor(() => {
      expect(fetch).toHaveBeenCalledWith(
        expect.stringMatching(/\/tasks\/task-1\/subtasks$/),
        expect.objectContaining({ body: expect.stringContaining("Draft outline") })
      );
    });

    await user.type(screen.getByLabelText("New comment"), "Looks good{Enter}");
    await waitFor(() => {
      expect(fetch).toHaveBeenCalledWith(
        expect.stringMatching(/\/tasks\/task-1\/comments$/),
        expect.objectContaining({ body: expect.stringContaining("Looks good") })
      );
    });

    await user.click(screen.getByRole("button", { name: "Complete task" }));
    await waitFor(() => {
      expect(fetch).toHaveBeenCalledWith(
        expect.stringMatching(/\/tasks\/task-1\/transitions$/),
        expect.objectContaining({ body: expect.stringContaining('"action":"complete"') })
      );
    });
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

    // Terminal tasks reopen through the list selector — never a bare move.
    const listSelect = await screen.findByLabelText("List");
    expect(screen.getByRole("option", { name: "Completed" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Reopen to Inbox" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Reopen to Next actions" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Reopen to Waiting for" })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: /^Move to/i })).not.toBeInTheDocument();

    await user.type(screen.getByLabelText("Waiting for"), "Ada");
    await user.selectOptions(listSelect, "waiting");

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

  it("keeps the panel's unbuilt Think affordance honest via the placeholder toast", async () => {
    const user = userEvent.setup();
    renderRoutes("/tasks/next/task-1");
    await screen.findByRole("heading", { name: "Task detail" });

    // The prototype panel has no agent zone; its Think action is present but
    // announces itself as a placeholder instead of pretending to work.
    await user.click(await screen.findByRole("button", { name: "Think" }));
    expect(await screen.findByRole("status")).toHaveTextContent("Thinking canvas isn't built yet — placeholder");
  });
});

// The real `/admin` route, not a directly-mounted `AdminPage`: wrong route
// wiring (a missing ProtectedRoute, a path typo) is invisible to a test that
// renders the component itself (009-FR-005).
describe("AppRoutes /admin (009-FR-005, 009-FR-010)", () => {
  it("009-FR-005: a signed-out visitor is redirected to sign-in, with no admin request", async () => {
    act(() => {
      useAuthStore.setState({ user: null, status: "anon" });
    });

    renderRoutes("/admin");

    await waitFor(() =>
      expect(screen.getByRole("heading", { name: /sign in/i })).toBeInTheDocument()
    );
    const calls = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls.map((call) =>
      String(call[0])
    );
    expect(calls.some((url) => url.includes("/admin"))).toBe(false);
  });

  it("009-FR-005: a signed-in non-operator reaches the denied state and no lookup form", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes("/admin/status")) {
          return Promise.resolve(jsonResponse({ message: "Not authorized." }, 403));
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
      })
    );

    renderRoutes("/admin");

    expect(await screen.findByText("Access denied")).toBeInTheDocument();
    expect(screen.queryByLabelText(/account id or email/i)).not.toBeInTheDocument();
  });

  it("009-FR-005: an operator reaches the lookup form by typing the URL", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes("/admin/status")) {
          return Promise.resolve(jsonResponse({ is_operator: true }));
        }
        if (url.includes("/admin/accounts")) {
          return Promise.resolve(jsonResponse({ accounts: [] }));
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
      })
    );

    renderRoutes("/admin");

    expect(await screen.findByRole("heading", { name: "Users" })).toBeInTheDocument();
    expect(screen.queryByText("Access denied")).not.toBeInTheDocument();
  });

  it("009-SC-006: an ordinary authenticated screen issues no /admin request", async () => {
    renderRoutes("/");

    expect(await screen.findByRole("heading", { name: "Next actions" })).toBeInTheDocument();
    const calls = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls.map((call) =>
      String(call[0])
    );
    expect(calls.some((url) => url.includes("/admin"))).toBe(false);
  });
});
