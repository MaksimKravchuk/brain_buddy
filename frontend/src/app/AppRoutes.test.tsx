import { act, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, useNavigate } from "react-router-dom";
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

// Exposes real router navigation alongside AppRoutes so tests can drive
// forward pushes and a genuine `navigate(-1)` Back, which plain MemoryRouter
// initialEntries cannot trigger on their own. Pushing forward (rather than
// starting directly on the destination) matters: it lets React Query cache
// each visited task's detail, so navigating back later serves the cached
// data on the very first render instead of passing through a loading state.
function NavigationHarness({ paths }: { paths: string[] }): JSX.Element {
  const navigate = useNavigate();
  return (
    <div>
      {paths.map((path) => (
        <button key={path} type="button" onClick={() => navigate(path)}>
          {`Go to ${path}`}
        </button>
      ))}
      <button type="button" onClick={() => navigate(-1)}>
        Simulate browser back
      </button>
    </div>
  );
}

function renderRoutesWithNavigator(initialEntry: string, paths: string[]) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });

  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[initialEntry]}>
        <NavigationHarness paths={paths} />
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

// Lets a test hold a mocked fetch response open and choose exactly when it
// resolves, so two competing refetches (e.g. detail vs. list) can be made to
// land in a deliberately adverse order.
function createDeferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((res) => {
    resolve = res;
  });
  return { promise, resolve };
}

// Releasing a held-open mocked fetch response only settles that Promise --
// the rest of the chain (Response#json(), the query retryer's own .then(),
// the query cache dispatch) runs across further microtask turns that a bare
// `act(async () => { release() })` does not wait for, since the callback
// itself never awaits that chain. Worse, React Query's own observer
// notification (which drives the React re-render) is scheduled via its
// notifyManager, whose default scheduler is a *real* `setTimeout(fn, 0)` --
// not a microtask. A same-delay `setTimeout(resolve, 0)` flush here would
// race that internal timer for queue order (whichever was registered first
// runs first), which is exactly backwards: at the point this is called, our
// own flush timer registers before React Query's internal one even exists
// yet, so it would routinely fire first and observe pre-settlement state.
// A strictly larger delay guarantees this fires after any 0ms timer already
// queued by the time it was scheduled, regardless of registration order.
function flushMicrotasks(): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, 10));
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
    expect(screen.getByRole("button", { name: "Save task detail" })).toHaveFocus();

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
    expect(screen.getByRole("heading", { name: "Task detail" })).toHaveFocus();
  });

  it("submits the revision the draft was displayed against, not a newer revision picked up by a same-task concurrent refetch", async () => {
    // A same-task refetch can land while the user still has an unsaved draft
    // open -- e.g. an unrelated mutation elsewhere invalidates the shared
    // "tasks" query root, which also refetches this open detail. The
    // uncontrolled Details field correctly keeps showing the user's draft
    // (no remount happens), but the underlying task object now reports a
    // newer revision from someone else's concurrent edit. Save must still
    // send the revision the draft was actually based on (1), never the
    // revision that merely arrived later (2) -- sending the newer one would
    // silently skip the backend's optimistic-concurrency check and could
    // clobber the concurrent edit instead of surfacing an explicit conflict.
    const user = userEvent.setup();
    let taskGetCount = 0;
    const patchBodies: Array<Record<string, unknown>> = [];

    vi.mocked(fetch).mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      if (url.endsWith("/tasks/task-1") && method === "PATCH") {
        const body = JSON.parse(String(init?.body)) as Record<string, unknown>;
        patchBodies.push(body);
        // The real server revision is already 2, so a request that (correctly)
        // targets base revision 1 is rejected as an explicit conflict.
        return Promise.resolve(jsonResponse({ detail: "Conflict" }, 409));
      }
      if (url.endsWith("/tasks/task-1") && method === "GET") {
        taskGetCount += 1;
        if (taskGetCount === 1) {
          return Promise.resolve(jsonResponse({ ...taskResponse.items[0], details: "Original details", revision: 1 }));
        }
        return Promise.resolve(
          jsonResponse({ ...taskResponse.items[0], details: "Edited concurrently elsewhere", revision: 2 })
        );
      }
      if (url.endsWith("/tasks") && method === "POST") {
        // Any other task mutation invalidates the shared "tasks" query root,
        // which is what triggers the concurrent-looking detail refetch here.
        return Promise.resolve(jsonResponse(taskFixture("task-unrelated", "Unrelated capture"), 201));
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

    renderRoutes("/tasks/next/task-1");

    expect(await screen.findByLabelText("Details")).toHaveValue("Original details");
    await user.clear(screen.getByLabelText("Details"));
    await user.type(screen.getByLabelText("Details"), "My unsaved draft edit");

    // Trigger the concurrent-looking refetch via an unrelated create, the way
    // it would happen for real (any task mutation anywhere invalidates the
    // shared query root).
    await user.type(screen.getByLabelText("New task title"), "Unrelated capture");
    await user.click(screen.getByRole("button", { name: "Add task" }));

    await waitFor(() => expect(taskGetCount).toBeGreaterThanOrEqual(2));
    // The draft survives the concurrent refetch untouched -- it must not be
    // silently overwritten by the newer, concurrently-edited server value.
    expect(screen.getByLabelText("Details")).toHaveValue("My unsaved draft edit");

    await user.click(screen.getByRole("button", { name: "Save task detail" }));

    await waitFor(() => expect(patchBodies.length).toBeGreaterThanOrEqual(1));
    expect(patchBodies[0]).toMatchObject({
      details: "My unsaved draft edit",
      expected_revision: 1
    });

    expect(await screen.findByRole("alert")).toHaveTextContent("Conflict");
    // The failed save must not discard the user's draft either.
    expect(screen.getByLabelText("Details")).toHaveValue("My unsaved draft edit");
  });

  it("on a same-task 409 Save conflict, refetches the Task, rebases only the concurrency baseline, keeps every unsaved draft field, and lets an explicit retry succeed at the refetched revision", async () => {
    // Same concurrent-refetch setup as the previous spec (an unrelated
    // capture invalidates the shared "tasks" query root and surfaces a
    // same-task background refetch reporting the authoritative revision-2
    // state left by someone else's concurrent edit). That prior spec only
    // proves the *first* Save keeps targeting the stale baseline it was
    // shown against. Per ADR-0006's invalid-transition contract, the UI must
    // additionally refetch the Task on 409 and let a later explicit retry
    // succeed against the now-current revision -- it must never leave the
    // user stuck resubmitting a permanently stale expected_revision, and it
    // must never silently convert the conflict into an overwrite.
    const user = userEvent.setup();
    let taskGetCount = 0;
    let concurrentEditVisible = false;
    const patchBodies: Array<Record<string, unknown>> = [];

    vi.mocked(fetch).mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      if (url.endsWith("/tasks/task-1") && method === "PATCH") {
        const body = JSON.parse(String(init?.body)) as Record<string, unknown>;
        patchBodies.push(body);
        if (body.expected_revision === 2) {
          return Promise.resolve(
            jsonResponse({
              ...taskResponse.items[0],
              title: body.title,
              details: body.details,
              priority: body.priority,
              revision: 3
            })
          );
        }
        // The real server revision is already 2 (the concurrent edit), so a
        // request that still targets base revision 1 is an explicit conflict.
        return Promise.resolve(jsonResponse({ detail: "Conflict" }, 409));
      }
      if (url.endsWith("/tasks/task-1") && method === "GET") {
        taskGetCount += 1;
        if (!concurrentEditVisible) {
          return Promise.resolve(jsonResponse({ ...taskResponse.items[0], details: "Original details", revision: 1 }));
        }
        return Promise.resolve(
          jsonResponse({ ...taskResponse.items[0], details: "Edited concurrently elsewhere", revision: 2 })
        );
      }
      if (url.endsWith("/tasks") && method === "POST") {
        // Any other task mutation invalidates the shared "tasks" query root,
        // which is what triggers the concurrent-looking detail refetch here.
        concurrentEditVisible = true;
        return Promise.resolve(jsonResponse(taskFixture("task-unrelated", "Unrelated capture"), 201));
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

    renderRoutes("/tasks/next/task-1");

    expect(await screen.findByLabelText("Details")).toHaveValue("Original details");
    await user.clear(screen.getByLabelText("Title"));
    await user.type(screen.getByLabelText("Title"), "My unsaved title edit");
    await user.clear(screen.getByLabelText("Details"));
    await user.type(screen.getByLabelText("Details"), "My unsaved draft edit");
    await user.selectOptions(screen.getByLabelText("Priority"), "high");

    // Trigger the concurrent-looking refetch via an unrelated create, the way
    // it would happen for real.
    await user.type(screen.getByLabelText("New task title"), "Unrelated capture");
    await user.click(screen.getByRole("button", { name: "Add task" }));
    await waitFor(() => expect(taskGetCount).toBeGreaterThanOrEqual(2));

    // Every mounted unsaved draft field survives the concurrent refetch.
    expect(screen.getByLabelText("Title")).toHaveValue("My unsaved title edit");
    expect(screen.getByLabelText("Details")).toHaveValue("My unsaved draft edit");
    expect(screen.getByLabelText("Priority")).toHaveValue("high");

    const getCountBeforeSave = taskGetCount;

    await user.click(screen.getByRole("button", { name: "Save task detail" }));

    await waitFor(() => expect(patchBodies.length).toBeGreaterThanOrEqual(1));
    expect(patchBodies[0]).toMatchObject({ expected_revision: 1 });
    expect(await screen.findByRole("alert")).toHaveTextContent("Conflict");

    // ADR-0006: "on 409 refetches the Task while preserving unsaved user
    // input for an explicit retry."
    await waitFor(() => expect(taskGetCount).toBeGreaterThan(getCountBeforeSave));

    // Only the concurrency baseline rebases to the refetched revision -- the
    // user's own unsaved draft values are left completely untouched.
    expect(screen.getByLabelText("Title")).toHaveValue("My unsaved title edit");
    expect(screen.getByLabelText("Details")).toHaveValue("My unsaved draft edit");
    expect(screen.getByLabelText("Priority")).toHaveValue("high");

    // No automatic mutation/overwrite happens off the back of the conflict --
    // still just the one, rejected PATCH until the user explicitly retries.
    expect(patchBodies).toHaveLength(1);

    // The explicit retry now targets the refetched revision and succeeds.
    await user.click(screen.getByRole("button", { name: "Save task detail" }));

    await waitFor(() => expect(patchBodies.length).toBeGreaterThanOrEqual(2));
    expect(patchBodies[1]).toMatchObject({
      expected_revision: 2,
      title: "My unsaved title edit",
      details: "My unsaved draft edit",
      priority: "high"
    });
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("on a same-task 409 transition conflict, refetches the Task, rebases only the concurrency baseline, keeps every unsaved draft field, and lets an explicit retry succeed at the refetched revision", async () => {
    // Same contract as the Save spec above, but exercised through the
    // detail Complete/transition path, which is a distinct mutation
    // (POST .../transitions, not PATCH) with its own onError handler --
    // it must uphold the same on-409 refetch/rebase/no-overwrite contract.
    const user = userEvent.setup();
    let taskGetCount = 0;
    let concurrentEditVisible = false;
    let transitionSucceeded = false;
    const transitionBodies: Array<Record<string, unknown>> = [];

    vi.mocked(fetch).mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      if (url.endsWith("/tasks/task-1/transitions") && method === "POST") {
        const body = JSON.parse(String(init?.body)) as Record<string, unknown>;
        transitionBodies.push(body);
        if (body.expected_revision === 2) {
          transitionSucceeded = true;
          return Promise.resolve(jsonResponse({ ...taskResponse.items[0], state: "completed", revision: 3 }));
        }
        return Promise.resolve(jsonResponse({ detail: "Conflict" }, 409));
      }
      if (url.endsWith("/tasks/task-1") && method === "GET") {
        taskGetCount += 1;
        if (transitionSucceeded) {
          return Promise.resolve(jsonResponse({ ...taskResponse.items[0], state: "completed", revision: 3 }));
        }
        if (!concurrentEditVisible) {
          return Promise.resolve(jsonResponse({ ...taskResponse.items[0], details: "Original details", revision: 1 }));
        }
        return Promise.resolve(
          jsonResponse({ ...taskResponse.items[0], details: "Edited concurrently elsewhere", revision: 2 })
        );
      }
      if (url.endsWith("/tasks") && method === "POST") {
        concurrentEditVisible = true;
        return Promise.resolve(jsonResponse(taskFixture("task-unrelated", "Unrelated capture"), 201));
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

    renderRoutes("/tasks/next/task-1");

    expect(await screen.findByLabelText("Details")).toHaveValue("Original details");
    await user.clear(screen.getByLabelText("Title"));
    await user.type(screen.getByLabelText("Title"), "My unsaved title edit");
    await user.clear(screen.getByLabelText("Details"));
    await user.type(screen.getByLabelText("Details"), "My unsaved draft edit");
    await user.selectOptions(screen.getByLabelText("Priority"), "high");

    await user.type(screen.getByLabelText("New task title"), "Unrelated capture");
    await user.click(screen.getByRole("button", { name: "Add task" }));
    await waitFor(() => expect(taskGetCount).toBeGreaterThanOrEqual(2));

    expect(screen.getByLabelText("Title")).toHaveValue("My unsaved title edit");
    expect(screen.getByLabelText("Details")).toHaveValue("My unsaved draft edit");
    expect(screen.getByLabelText("Priority")).toHaveValue("high");

    const getCountBeforeTransition = taskGetCount;

    await user.click(screen.getByRole("button", { name: "Complete" }));

    await waitFor(() => expect(transitionBodies.length).toBeGreaterThanOrEqual(1));
    expect(transitionBodies[0]).toMatchObject({ action: "complete", expected_revision: 1 });
    expect(await screen.findByRole("alert")).toHaveTextContent("Conflict");

    // ADR-0006: on 409 the app refetches the Task while preserving unsaved
    // user input for an explicit retry.
    await waitFor(() => expect(taskGetCount).toBeGreaterThan(getCountBeforeTransition));

    // Only the concurrency baseline rebases; the still-mounted unsaved draft
    // fields are untouched by the transition conflict.
    expect(screen.getByLabelText("Title")).toHaveValue("My unsaved title edit");
    expect(screen.getByLabelText("Details")).toHaveValue("My unsaved draft edit");
    expect(screen.getByLabelText("Priority")).toHaveValue("high");

    // No automatic retry/overwrite off the back of the conflict.
    expect(transitionBodies).toHaveLength(1);

    // The explicit retry now targets the refetched revision and succeeds.
    await user.click(screen.getByRole("button", { name: "Complete" }));

    await waitFor(() => expect(transitionBodies.length).toBeGreaterThanOrEqual(2));
    expect(transitionBodies[1]).toMatchObject({ action: "complete", expected_revision: 2 });
    expect(await screen.findByRole("button", { name: "Reopen to Inbox" })).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("publishes the authoritative TaskResponse into the detail cache on Complete/Reopen/Move so an inline<->standalone projection swap never shows a stale revision", async () => {
    // Completing, reopening, or moving a task out of and back into the
    // active "Next" projection remounts the task detail panel -- it swaps
    // between the standalone route panel and the in-row panel embedded in
    // TaskList (see TaskListPage's `detailIsInProjection` branch). Each swap
    // is a genuine unmount/mount of TaskDetailPanel, which re-pins its
    // uncontrolled draft state from whatever `task` prop it is handed at
    // mount time. That value must be the mutation's own authoritative
    // response, published synchronously -- not whatever the shared "tasks"
    // query root's background refetch eventually delivers, which this test
    // holds open forever below to prove the swap never depends on it landing.
    const user = userEvent.setup();
    let currentTask = { ...taskResponse.items[0], waiting_for: taskResponse.items[0].waiting_for as string | null };
    let detailGetCount = 0;

    vi.mocked(fetch).mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      if (url.endsWith("/tasks/task-1") && method === "GET") {
        detailGetCount += 1;
        if (detailGetCount === 1) {
          return Promise.resolve(jsonResponse(currentTask));
        }
        // Every background detail refetch that invalidateTasks() triggers
        // after a mutation is deliberately held open forever.
        return new Promise<Response>(() => {});
      }
      if (url.endsWith("/tasks/task-1/transitions") && method === "POST") {
        const body = JSON.parse(String(init?.body)) as Record<string, unknown>;
        currentTask = {
          ...currentTask,
          state: body.action === "complete" ? "completed" : String(body.to_state),
          waiting_for: typeof body.waiting_for === "string" && body.waiting_for ? body.waiting_for : currentTask.waiting_for,
          revision: currentTask.revision + 1
        };
        return Promise.resolve(jsonResponse(currentTask));
      }
      if (url.endsWith("/tasks") || url.includes("/tasks?")) {
        return Promise.resolve(jsonResponse({
          ...taskResponse,
          items: currentTask.state === "next" ? [currentTask] : []
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

    await screen.findByRole("link", { name: "Fix onboarding drop-off" });
    expect(await screen.findByRole("button", { name: "Complete" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Complete" }));
    await waitFor(() => expect(currentTask.state).toBe("completed"));
    // The task leaves the Next projection and the panel swaps inline ->
    // standalone. The swapped-in panel must show the completed state
    // immediately, not the stale "next" state from the very first GET.
    expect(await screen.findByRole("button", { name: "Reopen to Next" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Fix onboarding drop-off" })).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Reopen to Next" }));
    await waitFor(() => expect(currentTask.state).toBe("next"));
    // Reopening returns the task to Next, swapping standalone -> inline.
    // Same requirement in reverse.
    expect(await screen.findByRole("button", { name: "Complete" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Reopen to Next" })).not.toBeInTheDocument();

    await user.type(screen.getByLabelText("Waiting for"), "Ada from finance");
    await user.click(screen.getByRole("button", { name: "Move to Waiting for" }));
    await waitFor(() => expect(currentTask.state).toBe("waiting"));
    // Moving to Waiting removes the task from Next again, swapping inline ->
    // standalone a second time.
    expect(await screen.findByRole("button", { name: "Move to Next" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Move to Waiting for" })).not.toBeInTheDocument();
  });

  it("on a same-task 409 with a pre-conflict GET still held in flight, issues a genuine post-conflict GET instead of deduplicating onto the stale one, preserves every unsaved draft, and survives the stale GET resolving after the authoritative publish without regressing the rendered detail or the explicit retry", async () => {
    // ADR-0006's on-409 refetch must be a real post-conflict request. If a
    // background refetch for this same detail query key was already in
    // flight when the conflict landed (e.g. an unrelated mutation elsewhere
    // invalidated the shared "tasks" query root moments earlier), the
    // conflict handler must not silently attach to that older, pre-conflict
    // promise -- doing so can hand back stale data and rebase the retry onto
    // the wrong revision. Beyond that, the older promise is still alive:
    // this test resolves it only *after* the authoritative revision-2 GET
    // has already been published into the cache, proving that late arrival
    // can never regress the rendered detail back to the pre-conflict
    // revision, nor corrupt the baseline the explicit retry targets.
    const user = userEvent.setup();
    let taskGetCount = 0;
    let releaseStaleInFlightGet: (() => void) | undefined;
    const patchBodies: Array<Record<string, unknown>> = [];

    vi.mocked(fetch).mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      if (url.endsWith("/tasks/task-1") && method === "GET") {
        taskGetCount += 1;
        if (taskGetCount === 1) {
          return Promise.resolve(
            jsonResponse({ ...taskResponse.items[0], title: "Fix onboarding drop-off", details: "Original details", revision: 1 })
          );
        }
        if (taskGetCount === 2) {
          // The background refetch triggered by the unrelated create's
          // invalidateTasks() below. Held open deliberately, and released
          // later -- strictly after the authoritative revision-2 GET below
          // has already been published -- to prove its late arrival is inert.
          return new Promise<Response>((resolve) => {
            releaseStaleInFlightGet = () =>
              resolve(
                jsonResponse({
                  ...taskResponse.items[0],
                  title: "STALE TITLE (must never reappear)",
                  details: "Stale pre-conflict snapshot",
                  revision: 1
                })
              );
          });
        }
        // The genuine post-conflict GET the conflict handler must issue.
        return Promise.resolve(
          jsonResponse({ ...taskResponse.items[0], title: "Edited concurrently elsewhere", details: "Original details", revision: 2 })
        );
      }
      if (url.endsWith("/tasks/task-1") && method === "PATCH") {
        const body = JSON.parse(String(init?.body)) as Record<string, unknown>;
        patchBodies.push(body);
        if (body.expected_revision === 2) {
          return Promise.resolve(
            jsonResponse({ ...taskResponse.items[0], ...body, title: "Edited concurrently elsewhere", revision: 3 })
          );
        }
        return Promise.resolve(jsonResponse({ detail: "Conflict" }, 409));
      }
      if (url.endsWith("/tasks") && method === "POST") {
        return Promise.resolve(jsonResponse(taskFixture("task-unrelated", "Unrelated capture"), 201));
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

    renderRoutes("/tasks/next/task-1");

    const detailPanel = () => {
      const heading = screen.getByRole("heading", { name: "Task detail" });
      const aside = heading.closest("aside");
      if (!aside) {
        throw new Error("expected the task detail panel to be mounted");
      }
      return aside as HTMLElement;
    };

    expect(await screen.findByLabelText("Details")).toHaveValue("Original details");
    await user.clear(screen.getByLabelText("Details"));
    await user.type(screen.getByLabelText("Details"), "My unsaved draft edit");

    // Trigger the background refetch (GET #2) and leave it in flight.
    await user.type(screen.getByLabelText("New task title"), "Unrelated capture");
    await user.click(screen.getByRole("button", { name: "Add task" }));
    await waitFor(() => expect(taskGetCount).toBe(2));
    expect(releaseStaleInFlightGet).toBeDefined();

    // Save collides with the real revision-1 baseline (a genuine concurrent
    // edit landed server-side even though the stale in-flight GET above
    // hasn't told the client about it yet) and is rejected with 409.
    await user.click(screen.getByRole("button", { name: "Save task detail" }));
    await waitFor(() => expect(patchBodies.length).toBeGreaterThanOrEqual(1));
    expect(patchBodies[0]).toMatchObject({ expected_revision: 1 });

    // The conflict handler must issue a genuine third GET rather than
    // deduplicating onto the still-unresolved second one -- proven without
    // ever resolving that stuck promise.
    await waitFor(() => expect(taskGetCount).toBeGreaterThanOrEqual(3));

    // The alert only renders once rejectAfterConflictRefetch has finished --
    // i.e. once the revision-2 GET has resolved *and* been published into
    // the cache. This is the ordering guarantee the stale-GET release below
    // depends on.
    expect(await screen.findByRole("alert")).toHaveTextContent("Conflict");
    expect(screen.getByLabelText("Details")).toHaveValue("My unsaved draft edit");
    expect(within(detailPanel()).getByText("Edited concurrently elsewhere")).toBeInTheDocument();

    // Now release the stale, pre-conflict GET -- strictly after the
    // authoritative revision-2 publish above. Its resolution must be inert:
    // it must not regress the rendered detail back to the pre-conflict title.
    await act(async () => {
      releaseStaleInFlightGet?.();
      await flushMicrotasks();
    });

    expect(within(detailPanel()).queryByText("STALE TITLE (must never reappear)")).not.toBeInTheDocument();
    expect(within(detailPanel()).getByText("Edited concurrently elsewhere")).toBeInTheDocument();
    expect(screen.getByLabelText("Details")).toHaveValue("My unsaved draft edit");

    // The explicit retry now targets the refetched revision and succeeds --
    // proving the retry's own concurrency baseline was never corrupted by
    // the late-arriving stale GET either.
    await user.click(screen.getByRole("button", { name: "Save task detail" }));
    await waitFor(() => expect(patchBodies.length).toBeGreaterThanOrEqual(2));
    expect(patchBodies[1]).toMatchObject({ expected_revision: 2, details: "My unsaved draft edit" });
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("on a same-task 409 transition conflict, a stale pre-conflict GET resolving after the authoritative publish cannot regress the cache -- including through the explicit retry's own projection remount", async () => {
    // Same race as the Save spec above, but through the detail
    // Complete/transition path (POST .../transitions, not PATCH). The stale,
    // pre-conflict GET is released right after the authoritative revision-2
    // GET has been published (same window as the Save spec) -- i.e. before
    // the explicit retry, whose own success triggers a *second*,
    // React-Query-driven invalidation of this same query. That second
    // invalidation defaults to cancelRefetch: true and would cancel a
    // still-in-flight stale GET on its own, which would mask the bug this
    // spec targets; releasing early keeps the assertion specific to the
    // conflict handler's own fencing. The retry then moves the task out of
    // the "Next" projection, remounting TaskDetailPanel entirely (see the
    // "publishes the authoritative TaskResponse" spec above) -- proving the
    // freshly mounted panel still reflects the correctly-fenced state, not
    // whatever the (already-settled) stale GET would have written.
    const user = userEvent.setup();
    // The single source of truth the mock server advances on every
    // successful transition -- read live by every "genuine" GET, so a
    // later action (the explicit Reopen retry) always sees the correct,
    // just-confirmed state rather than a hardcoded snapshot.
    let server: { state: "next" | "completed"; revision: number } = { state: "next", revision: 1 };
    let taskGetCount = 0;
    let releaseStaleInFlightGet: (() => void) | undefined;
    const transitionBodies: Array<Record<string, unknown>> = [];

    vi.mocked(fetch).mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      if (url.endsWith("/tasks/task-1/transitions") && method === "POST") {
        const body = JSON.parse(String(init?.body)) as Record<string, unknown>;
        transitionBodies.push(body);
        if (body.expected_revision !== server.revision) {
          return Promise.resolve(jsonResponse({ detail: "Conflict" }, 409));
        }
        server = {
          state: body.action === "complete" ? "completed" : (String(body.to_state ?? server.state) as "next" | "completed"),
          revision: server.revision + 1
        };
        return Promise.resolve(jsonResponse({ ...taskResponse.items[0], ...server, title: "Edited concurrently elsewhere" }));
      }
      if (url.endsWith("/tasks/task-1") && method === "GET") {
        taskGetCount += 1;
        if (taskGetCount === 1) {
          return Promise.resolve(
            jsonResponse({ ...taskResponse.items[0], title: "Fix onboarding drop-off", state: "next", revision: 1 })
          );
        }
        if (taskGetCount === 2) {
          // The background refetch triggered by the unrelated create's
          // invalidateTasks() below. Held open deliberately, and released
          // later -- strictly after the authoritative revision-2 GET has
          // already been published -- to prove its late arrival is inert.
          // It reflects the pre-conflict snapshot the client actually saw
          // (revision 1), not whatever the server has since moved on to.
          return new Promise<Response>((resolve) => {
            releaseStaleInFlightGet = () =>
              resolve(
                jsonResponse({
                  ...taskResponse.items[0],
                  title: "STALE TITLE (must never reappear)",
                  state: "next",
                  revision: 1
                })
              );
          });
        }
        // The genuine post-conflict GET (and every later background
        // refetch) must reflect the live server-side truth.
        return Promise.resolve(jsonResponse({ ...taskResponse.items[0], ...server, title: "Edited concurrently elsewhere" }));
      }
      if (url.endsWith("/tasks") && method === "POST") {
        // Simulates a genuine concurrent edit landing server-side, moments
        // before the Complete click below, that the client doesn't know
        // about yet (the stale in-flight GET above still reports revision 1).
        server = { ...server, revision: 2 };
        return Promise.resolve(jsonResponse(taskFixture("task-unrelated", "Unrelated capture"), 201));
      }
      if (url.endsWith("/tasks") || url.includes("/tasks?")) {
        return Promise.resolve(jsonResponse({
          ...taskResponse,
          items: server.state === "next" ? [{ ...taskResponse.items[0], ...server }] : []
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

    const detailPanel = () => {
      const heading = screen.getByRole("heading", { name: "Task detail" });
      const aside = heading.closest("aside");
      if (!aside) {
        throw new Error("expected the task detail panel to be mounted");
      }
      return aside as HTMLElement;
    };

    expect(await screen.findByRole("button", { name: "Complete" })).toBeInTheDocument();

    // Every mounted unsaved draft field must survive the 409/rebase below.
    await user.clear(screen.getByLabelText("Title"));
    await user.type(screen.getByLabelText("Title"), "My unsaved title edit");
    await user.type(screen.getByLabelText("Details"), "My unsaved draft edit");
    await user.selectOptions(screen.getByLabelText("Priority"), "high");

    // Trigger the background refetch (GET #2) and leave it in flight.
    await user.type(screen.getByLabelText("New task title"), "Unrelated capture");
    await user.click(screen.getByRole("button", { name: "Add task" }));
    await waitFor(() => expect(taskGetCount).toBe(2));
    expect(releaseStaleInFlightGet).toBeDefined();

    // Complete collides with the real revision-1 baseline (a genuine
    // concurrent edit landed server-side even though the stale in-flight GET
    // above hasn't told the client about it yet) and is rejected with 409.
    await user.click(screen.getByRole("button", { name: "Complete" }));
    await waitFor(() => expect(transitionBodies.length).toBeGreaterThanOrEqual(1));
    expect(transitionBodies[0]).toMatchObject({ action: "complete", expected_revision: 1 });

    // The alert only renders once rejectAfterConflictRefetch has finished --
    // i.e. once the revision-2 GET has resolved *and* been published.
    expect(await screen.findByRole("alert")).toHaveTextContent("Conflict");
    expect(screen.getByLabelText("Title")).toHaveValue("My unsaved title edit");
    expect(screen.getByLabelText("Details")).toHaveValue("My unsaved draft edit");
    expect(screen.getByLabelText("Priority")).toHaveValue("high");
    expect(within(detailPanel()).getByText("Edited concurrently elsewhere")).toBeInTheDocument();

    // Now release the stale, pre-conflict GET -- strictly after the
    // authoritative revision-2 publish above, and before the explicit retry
    // below. Its resolution must be inert: it must not regress the rendered
    // detail back to the pre-conflict title.
    await act(async () => {
      releaseStaleInFlightGet?.();
      await flushMicrotasks();
    });

    expect(within(detailPanel()).queryByText("STALE TITLE (must never reappear)")).not.toBeInTheDocument();
    expect(within(detailPanel()).getByText("Edited concurrently elsewhere")).toBeInTheDocument();
    expect(screen.getByLabelText("Title")).toHaveValue("My unsaved title edit");
    expect(screen.getByLabelText("Details")).toHaveValue("My unsaved draft edit");

    // The explicit retry now targets the refetched revision and succeeds,
    // moving the task out of the Next projection and remounting the panel.
    // The remount must read the correctly-fenced state, not whatever the
    // (already inert) stale GET would have written.
    await user.click(screen.getByRole("button", { name: "Complete" }));
    await waitFor(() => expect(transitionBodies.length).toBeGreaterThanOrEqual(2));
    expect(transitionBodies[1]).toMatchObject({ action: "complete", expected_revision: 2 });

    expect(await screen.findByRole("button", { name: "Reopen to Next" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Complete" })).not.toBeInTheDocument();
    expect(within(detailPanel()).getByText("Edited concurrently elsewhere")).toBeInTheDocument();

    // A further action from the remounted panel must still target the
    // correct, uncorrupted concurrency baseline (3), not the stale one (1).
    await user.click(screen.getByRole("button", { name: "Reopen to Next" }));
    await waitFor(() => expect(transitionBodies.length).toBeGreaterThanOrEqual(3));
    expect(transitionBodies[2]).toMatchObject({ action: "reopen", to_state: "next", expected_revision: 3 });
    expect(await screen.findByRole("button", { name: "Complete" })).toBeInTheDocument();
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

  it("falls back to a visible focus target, never document.body, when a desktop-to-mobile viewport swap hides the originally focused detail control", async () => {
    // Simulates the real browser media-query flip (desktop -> collapsed
    // mobile) that remounts the detail panel from its inline desktop form to
    // the standalone mobile form. On mobile the Properties disclosure starts
    // collapsed (hidden), so a control that was focused on desktop (the
    // Title field, inside Properties) is no longer visible in the new panel.
    // The swap must never leave focus on document.body.
    let changeListener: (() => void) | null = null;
    let matches = true;
    vi.stubGlobal("matchMedia", (query: string) => ({
      get matches() {
        return matches;
      },
      media: query,
      addEventListener: (_event: string, listener: () => void) => {
        changeListener = listener;
      },
      removeEventListener: () => {
        changeListener = null;
      },
      addListener: () => {},
      removeListener: () => {}
    }));

    renderRoutes("/tasks/next/task-1");

    const titleInput = await screen.findByLabelText("Title");
    titleInput.focus();
    expect(titleInput).toHaveFocus();

    matches = false;
    act(() => {
      changeListener?.();
    });

    await waitFor(() => expect(document.activeElement).not.toBe(document.body));
    expect(titleInput).not.toHaveFocus();
    expect(screen.getByRole("heading", { name: "Task detail" })).toHaveFocus();
  });

  it("does not let a failed task A transition steal focus onto task B's matching action after switching tasks", async () => {
    const user = userEvent.setup();
    const secondTask = taskFixture("task-2", "Second task title", "next");

    vi.mocked(fetch).mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      if (url.endsWith("/tasks/task-1/transitions") && method === "POST") {
        // The completion is rejected (e.g. a stale revision conflict); the
        // pending focus-restore intent recorded before this mutate() call
        // must not survive to affect a later, unrelated task.
        return Promise.resolve(jsonResponse({ detail: "Conflict" }, 409));
      }
      if (url.endsWith("/tasks/task-1")) {
        return Promise.resolve(jsonResponse(taskResponse.items[0]));
      }
      if (url.endsWith("/tasks/task-2")) {
        return Promise.resolve(jsonResponse(secondTask));
      }
      if (url.includes("/tasks?")) {
        return Promise.resolve(jsonResponse({
          items: [taskResponse.items[0], secondTask],
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

    renderRoutes("/tasks/next/task-1");

    await waitFor(() => expect(screen.getByRole("heading", { name: "Task detail" })).toHaveFocus());
    await user.click(await screen.findByRole("button", { name: "Complete" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Conflict");

    await user.click(screen.getByRole("link", { name: "Second task title" }));

    await waitFor(() => expect(screen.getByDisplayValue("Second task title")).toBeInTheDocument());
    await waitFor(() => expect(screen.getByRole("heading", { name: "Task detail" })).toHaveFocus());
    expect(screen.getByRole("button", { name: "Complete" })).not.toHaveFocus();
  });

  it("never leaves focus on document.body after a row-level Complete removes the focused row from the list", async () => {
    const user = userEvent.setup();

    let completed = false;
    vi.mocked(fetch).mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      if (url.endsWith("/tasks/task-1/transitions") && method === "POST") {
        completed = true;
        return Promise.resolve(jsonResponse({ ...taskResponse.items[0], state: "completed", revision: 2 }));
      }
      if (url.includes("/tasks?")) {
        // Completing the only Next task removes it from this filtered
        // projection once the mutation's refetch lands -- the row (and the
        // Complete button the click just focused) disappears from the DOM.
        return Promise.resolve(jsonResponse(
          completed
            ? { items: [], next_cursor: null, has_more: false, counts_by_state: { inbox: 0, next: 0, waiting: 0, someday: 0 } }
            : taskResponse
        ));
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

    const completeButton = await screen.findByRole("button", { name: "Complete Fix onboarding drop-off" });
    await user.click(completeButton);

    await waitFor(() => expect(screen.getByText("Next actions is clear")).toBeInTheDocument());
    expect(document.activeElement).not.toBe(document.body);
    expect(document.activeElement).not.toBeNull();
    expect(screen.getByRole("heading", { name: "Next actions" })).toHaveFocus();
  });

  it("does not leak task B's unsaved form values into task A after a standalone A -> B -> browser-back-to-A navigation", async () => {
    // Both tasks are "waiting" while the route filters "next", so neither is
    // ever in the active list projection -- each opens through the same
    // standalone <TaskDetailPanel> JSX slot instead of an in-row one. That
    // slot is where a missing `key` lets React reuse the same mounted host
    // DOM across tasks instead of remounting fresh uncontrolled inputs.
    const user = userEvent.setup();
    const taskA = { ...taskFixture("task-a", "Alpha standalone", "waiting"), waiting_for: "Alice" };
    const taskB = { ...taskFixture("task-b", "Bravo standalone", "waiting"), waiting_for: "Bob" };

    vi.mocked(fetch).mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      if (url.endsWith("/tasks/task-a") && method === "PATCH") {
        return Promise.resolve(jsonResponse({ ...taskA, ...JSON.parse(String(init?.body)), revision: 2 }));
      }
      if (url.endsWith("/tasks/task-a")) {
        return Promise.resolve(jsonResponse(taskA));
      }
      if (url.endsWith("/tasks/task-b")) {
        return Promise.resolve(jsonResponse(taskB));
      }
      if (url.includes("/tasks?")) {
        return Promise.resolve(jsonResponse({
          items: [],
          next_cursor: null,
          has_more: false,
          counts_by_state: { inbox: 0, next: 0, waiting: 2, someday: 0 }
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

    // Visit A first (so React Query caches its detail), then push forward to
    // B, then go back -- back-navigating to a task already cached serves its
    // data on the very first render, with no intervening loading gap that
    // would otherwise force the uncontrolled inputs to remount naturally.
    renderRoutesWithNavigator("/tasks/next/task-a", ["/tasks/next/task-b"]);

    await screen.findByDisplayValue("Alpha standalone");

    await user.click(screen.getByRole("button", { name: "Go to /tasks/next/task-b" }));
    await screen.findByDisplayValue("Bravo standalone");
    await user.clear(screen.getByLabelText("Title"));
    await user.type(screen.getByLabelText("Title"), "Bravo edited in B");
    await user.clear(screen.getByLabelText("Waiting for"));
    await user.type(screen.getByLabelText("Waiting for"), "Beatrice");

    await user.click(screen.getByRole("button", { name: "Simulate browser back" }));

    // The header text is driven directly from task data (not an uncontrolled
    // input), so it proves the route/data actually switched to task A.
    await screen.findByText("Alpha standalone");
    expect(screen.getByLabelText("Title")).toHaveValue("Alpha standalone");
    expect(screen.getByLabelText("Waiting for")).toHaveValue("Alice");

    await user.click(screen.getByRole("button", { name: "Save task detail" }));

    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith(
        expect.stringMatching(/\/tasks\/task-a$/),
        expect.objectContaining({ method: "PATCH" })
      )
    );
    const saveDetailCall = vi.mocked(fetch).mock.calls.find(
      ([input, init]) => /\/tasks\/task-a$/.test(String(input)) && (init as RequestInit | undefined)?.method === "PATCH"
    );
    expect(JSON.parse(String(saveDetailCall?.[1]?.body))).toMatchObject({
      title: "Alpha standalone",
      waiting_for: "Alice"
    });
  });

  it("does not strand list-row focus on document.body when the detail refetch settles before the list refetch confirms the row left the projection", async () => {
    // task-1's detail is open in-row (desktop, in projection) while its own
    // row-level Complete button (distinct from the detail panel's Complete
    // control) is clicked. Completing it invalidates both the detail query
    // and the "next" list query at once; this mock lets the test choose
    // which one resolves first -- here, deliberately, the unrelated detail
    // refetch lands before the list refetch that actually removes the row.
    const user = userEvent.setup();
    let completed = false;
    const detailGates: Array<{ resolve: (value: Response) => void }> = [];
    const listGates: Array<{ resolve: (value: Response) => void }> = [];

    vi.mocked(fetch).mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      if (url.endsWith("/tasks/task-1/transitions") && method === "POST") {
        completed = true;
        return Promise.resolve(jsonResponse({ ...taskResponse.items[0], state: "completed", revision: 2 }));
      }
      if (url.endsWith("/tasks/task-1") && method === "GET") {
        if (!completed) {
          return Promise.resolve(jsonResponse(taskResponse.items[0]));
        }
        const deferred = createDeferred<Response>();
        detailGates.push(deferred);
        return deferred.promise;
      }
      if (url.includes("/tasks?state=next")) {
        if (!completed) {
          return Promise.resolve(jsonResponse(taskResponse));
        }
        const deferred = createDeferred<Response>();
        listGates.push(deferred);
        return deferred.promise;
      }
      if (url.includes("/tasks?")) {
        // Inbox badge query -- irrelevant to the race under test.
        return Promise.resolve(jsonResponse({
          items: [],
          next_cursor: null,
          has_more: false,
          counts_by_state: { inbox: 0, next: completed ? 0 : 1, waiting: 0, someday: 0 }
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
    await waitFor(() => expect(screen.getByRole("heading", { name: "Task detail" })).toHaveFocus());

    const rowCompleteButton = await screen.findByRole("button", { name: "Complete Fix onboarding drop-off" });
    await user.click(rowCompleteButton);

    await waitFor(() => {
      expect(detailGates).toHaveLength(1);
      expect(listGates).toHaveLength(1);
    });

    // Adverse ordering: the detail refetch lands first. The row is still
    // present in the (not yet refetched) list, so nothing should move yet.
    await act(async () => {
      detailGates[0].resolve(jsonResponse({ ...taskResponse.items[0], state: "completed", revision: 2 }));
    });
    await screen.findByRole("button", { name: "Reopen to Inbox" });
    expect(rowCompleteButton).toHaveFocus();

    // The list refetch lands next, confirming the row actually left the
    // projection -- only now should a stranded document.body focus be rescued.
    await act(async () => {
      listGates[0].resolve(jsonResponse({
        items: [],
        next_cursor: null,
        has_more: false,
        counts_by_state: { inbox: 0, next: 0, waiting: 0, someday: 0 }
      }));
    });

    await waitFor(() => expect(document.activeElement).not.toBe(document.body));
    expect(document.activeElement).not.toBeNull();
    expect(screen.getByRole("heading", { name: "Task detail" })).toHaveFocus();
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

  it("keeps a grouped task visible in an accessible fallback group when its project is missing from the fetched active projects (archived or a refetch race)", async () => {
    const launchTask = { ...taskFixture("group-1", "Ship v2 changelog", "next"), project_id: "project-launch" };
    const orphanedTask = { ...taskFixture("group-orphan", "Ship orphaned task", "next"), project_id: "project-archived-or-racing" };

    vi.mocked(fetch).mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/tasks?")) {
        return Promise.resolve(jsonResponse({
          items: [launchTask, orphanedTask],
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
    // The task's project_id ("project-archived-or-racing") is not present in
    // the fetched active projects list -- it could be archived, or the
    // projects query could still be settling on a refetch. Either way the
    // task must never silently disappear from the grouped view; it belongs
    // in an accurate, accessible fallback group distinct from "No project"
    // (which means the task genuinely has no project_id at all).
    expect(await within(groupedList).findByText("Ship orphaned task")).toBeInTheDocument();
    expect(within(groupedList).getByRole("list", { name: /unavailable project/i })).toBeInTheDocument();
    const headings = within(groupedList).getAllByRole("heading", { level: 2 });
    expect(headings.map((heading) => heading.textContent)).toEqual(
      expect.arrayContaining([expect.stringContaining("Unavailable project")])
    );
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

  it("keeps the cached ordinary task-list frame and the routed task detail visible when a background refetch of that frame fails", async () => {
    // React Query never clears a query's last successful `data` just because
    // a later background refetch errors -- `isError` becomes true while
    // `data` still holds the previous good page. Replacing the whole frame
    // with ErrorState in that case would throw away a perfectly usable
    // cached list (and the routed task detail sitting alongside it) for a
    // transient failure the user can retry without losing anything.
    const user = userEvent.setup();
    let listAttempts = 0;

    vi.mocked(fetch).mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      if (url.includes("/tasks?state=next")) {
        listAttempts += 1;
        if (listAttempts === 1) {
          return Promise.resolve(jsonResponse(taskResponse));
        }
        return Promise.reject(new Error("network down"));
      }
      if (url.endsWith("/tasks") && method === "POST") {
        // An unrelated create invalidates the shared "tasks" query root,
        // forcing the already-loaded "next" list frame to refetch.
        return Promise.resolve(jsonResponse(taskFixture("task-unrelated-ordinary", "Unrelated ordinary capture"), 201));
      }
      if (url.endsWith("/tasks/task-1")) {
        return Promise.resolve(jsonResponse(taskResponse.items[0]));
      }
      if (url.includes("/tasks?")) {
        return Promise.resolve(jsonResponse({
          items: [],
          next_cursor: null,
          has_more: false,
          counts_by_state: { inbox: 0, next: 0, waiting: 0, someday: 0 }
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

    expect(await screen.findByRole("link", { name: "Fix onboarding drop-off" })).toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: "Task detail" })).toBeInTheDocument();

    await user.type(screen.getByLabelText("New task title"), "Unrelated ordinary capture");
    await user.click(screen.getByRole("button", { name: "Add task" }));

    await waitFor(() => expect(listAttempts).toBeGreaterThanOrEqual(2));

    // Honest, retryable notice -- but the cached row and the routed detail
    // stay on screen instead of being replaced by a full-page error.
    expect(await screen.findByText(/Showing previously loaded tasks/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Fix onboarding drop-off" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Task detail" })).toBeInTheDocument();
    expect(screen.queryByText(/we couldn't load tasks/i)).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(listAttempts).toBeGreaterThanOrEqual(3));
  });

  it("keeps the cached grouped all-pages frame visible when a background refetch of that frame fails", async () => {
    const user = userEvent.setup();
    let groupedAttempts = 0;

    vi.mocked(fetch).mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      if (url.includes("/tasks?") && url.includes("limit=200")) {
        groupedAttempts += 1;
        if (groupedAttempts === 1) {
          return Promise.resolve(jsonResponse(taskResponse));
        }
        return Promise.reject(new Error("network down"));
      }
      if (url.endsWith("/tasks") && method === "POST") {
        return Promise.resolve(jsonResponse(taskFixture("task-unrelated-grouped", "Unrelated grouped capture"), 201));
      }
      if (url.endsWith("/tasks/task-1")) {
        return Promise.resolve(jsonResponse(taskResponse.items[0]));
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

    renderRoutes("/tasks/next/task-1?group=project");
    expect(await screen.findByTestId("grouped-task-list")).toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: "Task detail" })).toHaveFocus();

    await user.type(screen.getByLabelText("New task title"), "Unrelated grouped capture");
    await user.click(screen.getByRole("button", { name: "Add task" }));

    await waitFor(() => expect(groupedAttempts).toBeGreaterThanOrEqual(2));

    expect(await screen.findByText(/Showing previously loaded tasks/)).toBeInTheDocument();
    expect(screen.getByTestId("grouped-task-list")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save task detail" })).toBeEnabled();
    expect(screen.queryByText(/we couldn't load tasks/i)).not.toBeInTheDocument();
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

describe("cross-account task cache isolation", () => {
  // Guards the leak this test file's parent bug describes: task list/detail/
  // project/tag cache identity used to be keyed only on task id and filters,
  // with no notion of which signed-in principal fetched it. A same-SPA
  // session loss followed by a different principal signing in from the same
  // preserved URL (ProtectedRoute -> /login -> LoginPage's redirectTo) could
  // then render the outgoing principal's cached data, or have a held
  // post-409 conflict refetch publish it after the switch. taskKeys now
  // qualifies every task cache entry by the signed-in principal, and
  // installTaskCacheOwnerGuard purges the outgoing principal's subtree
  // synchronously on every login/signup/logout/unauthorized-clear/hydrate
  // transition.
  const user = userEvent.setup();
  // Neither test cares about list-row content -- only about the routed
  // task detail URL -- and an empty list keeps the shared taskResponse
  // fixture's own "Fix onboarding drop-off" row out of the DOM so it can't
  // be confused with a genuine leak of A's cached detail data.
  const emptyTaskListResponse = {
    items: [],
    next_cursor: null,
    has_more: false,
    counts_by_state: { inbox: 0, next: 0, waiting: 0, someday: 0 }
  };

  it("never renders principal A's cached task detail after a same-SPA session loss and sign-in as a different principal on the same preserved URL", async () => {
    let taskGetCount = 0;
    let releaseSecondPrincipalGet: (() => void) | undefined;

    vi.mocked(fetch).mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      if (url.includes("/auth/login") && method === "POST") {
        return Promise.resolve(jsonResponse({ id: "user-2", email: "b@example.test" }));
      }
      if (url.endsWith("/tasks/task-1") && method === "GET") {
        taskGetCount += 1;
        if (taskGetCount === 1) {
          // Principal A's own initial detail load.
          return Promise.resolve(jsonResponse(taskResponse.items[0]));
        }
        // Principal B's request for the same task id after the preserved-
        // URL redirect. Held deliberately so the test can assert nothing
        // renders A's cached title while it's pending, then resolved 404
        // (B does not own this task) to prove it's never rendered after
        // either.
        return new Promise<Response>((resolve) => {
          releaseSecondPrincipalGet = () => resolve(jsonResponse({ detail: "Task not found" }, 404));
        });
      }
      if (url.endsWith("/tasks") || url.includes("/tasks?")) {
        return Promise.resolve(jsonResponse(emptyTaskListResponse));
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

    // The row link and the detail panel's mobile summary both render "Fix
    // onboarding drop-off" at this desktop-and-mobile-agnostic viewport, so
    // assert on the count rather than a single unique match throughout.
    expect(await screen.findAllByText("Fix onboarding drop-off")).not.toHaveLength(0);

    // Session loss (e.g. the unauthorized handler firing off a 401
    // elsewhere) clears the session. ProtectedRoute redirects to /login,
    // preserving this task detail URL as the post-login target.
    act(() => {
      useAuthStore.setState({ user: null, status: "anon" });
    });

    expect(await screen.findByRole("heading", { name: "Sign in to Brain Buddy" })).toBeInTheDocument();
    expect(screen.queryAllByText("Fix onboarding drop-off")).toHaveLength(0);

    // A different principal signs in from the same preserved URL.
    await user.type(screen.getByLabelText("Email"), "b@example.test");
    await user.type(screen.getByLabelText("Password"), "correct horse battery staple");
    await user.click(screen.getByRole("button", { name: "Sign in" }));

    await flushMicrotasks();
    // B's own request for task-1 is still pending -- must never render A's
    // cached title while it settles.
    expect(await screen.findByText("Loading task detail…")).toBeInTheDocument();
    expect(screen.queryAllByText("Fix onboarding drop-off")).toHaveLength(0);

    await waitFor(() => expect(releaseSecondPrincipalGet).toBeDefined());
    await act(async () => {
      releaseSecondPrincipalGet?.();
      await flushMicrotasks();
    });

    // B's request resolves 404 (B does not own this task) -- an honest
    // not-found state, never A's stale cached detail.
    expect(await screen.findByRole("alert")).toHaveTextContent("Task not found");
    expect(screen.queryAllByText("Fix onboarding drop-off")).toHaveLength(0);
  });

  it("drops a post-409 conflict refetch released after a same-SPA identity switch instead of publishing or rebasing the outgoing principal's Task", async () => {
    let taskGetCount = 0;
    let releaseConflictGet: (() => void) | undefined;

    vi.mocked(fetch).mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      if (url.includes("/auth/login") && method === "POST") {
        return Promise.resolve(jsonResponse({ id: "user-2", email: "b@example.test" }));
      }
      if (url.endsWith("/tasks/task-1") && method === "GET") {
        taskGetCount += 1;
        if (taskGetCount === 1) {
          return Promise.resolve(
            jsonResponse({ ...taskResponse.items[0], title: "Fix onboarding drop-off", details: "Original details", revision: 1 })
          );
        }
        if (taskGetCount === 2) {
          // ADR-0006's post-409 refetch, issued while principal A is still
          // signed in. Held deliberately and released only after the SPA
          // has switched to a different principal, to prove the late
          // arrival can never publish A's Task into the cache or rebase
          // any (by then orphaned) draft's concurrency baseline.
          return new Promise<Response>((resolve) => {
            releaseConflictGet = () =>
              resolve(
                jsonResponse({
                  ...taskResponse.items[0],
                  title: "STALE A TITLE (must never publish)",
                  details: "Stale A details",
                  revision: 2
                })
              );
          });
        }
        // Principal B's own request for the same task id -- B does not own it.
        return Promise.resolve(jsonResponse({ detail: "Task not found" }, 404));
      }
      if (url.endsWith("/tasks/task-1") && method === "PATCH") {
        return Promise.resolve(jsonResponse({ detail: "Conflict" }, 409));
      }
      if (url.endsWith("/tasks") || url.includes("/tasks?")) {
        return Promise.resolve(jsonResponse(emptyTaskListResponse));
      }
      if (url.includes("/projects")) {
        return Promise.resolve(jsonResponse(projectsResponse));
      }
      if (url.includes("/tags")) {
        return Promise.resolve(jsonResponse(tagsResponse));
      }
      return Promise.resolve(jsonResponse(null));
    });

    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={["/tasks/next/task-1"]}>
          <AppRoutes />
        </MemoryRouter>
      </QueryClientProvider>
    );

    expect(await screen.findByLabelText("Details")).toHaveValue("Original details");
    await user.clear(screen.getByLabelText("Details"));
    await user.type(screen.getByLabelText("Details"), "My unsaved draft edit");
    await user.click(screen.getByRole("button", { name: "Save task detail" }));

    await waitFor(() => expect(taskGetCount).toBeGreaterThanOrEqual(2));
    expect(releaseConflictGet).toBeDefined();

    // Session loss, then a different principal signs in from the same
    // preserved URL -- while the conflict refetch above is still held.
    act(() => {
      useAuthStore.setState({ user: null, status: "anon" });
    });
    expect(await screen.findByRole("heading", { name: "Sign in to Brain Buddy" })).toBeInTheDocument();

    await user.type(screen.getByLabelText("Email"), "b@example.test");
    await user.type(screen.getByLabelText("Password"), "correct horse battery staple");
    await user.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Task not found");

    // Release the held conflict refetch strictly after B's own 404 landed.
    await act(async () => {
      releaseConflictGet?.();
      await flushMicrotasks();
    });

    // The late arrival must be inert: it never publishes A's Task into
    // either principal's cache slot, and B's honest not-found state must
    // survive it untouched.
    expect(screen.queryByText("STALE A TITLE (must never publish)")).not.toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("Task not found");
    expect(client.getQueryData(["tasks", "user-1", "detail", "task-1"])).toBeUndefined();
    expect(client.getQueryData(["tasks", "user-2", "detail", "task-1"])).toBeUndefined();
  });

  it("drops an in-flight, successful detail Save/transition response released after a same-SPA identity switch instead of publishing the outgoing principal's Task", async () => {
    // Distinct from the post-409 conflict-refetch spec above: this covers
    // the *ordinary* success path (detailUpdateMutation's onSuccess ->
    // publishDetail + invalidateTasks), which has no ADR-0006 conflict
    // branch to guard it. A same-SPA identity switch while a genuine
    // in-flight PATCH is still pending must stop its onSuccess from
    // publishing/invalidating against whichever principal happens to be
    // signed in when the response finally lands.
    let taskGetCount = 0;
    let releaseHeldSave: (() => void) | undefined;

    vi.mocked(fetch).mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      if (url.includes("/auth/login") && method === "POST") {
        return Promise.resolve(jsonResponse({ id: "user-2", email: "b@example.test" }));
      }
      if (url.endsWith("/tasks/task-1") && method === "GET") {
        taskGetCount += 1;
        if (taskGetCount === 1) {
          return Promise.resolve(
            jsonResponse({ ...taskResponse.items[0], title: "Fix onboarding drop-off", details: "Original details", revision: 1 })
          );
        }
        // Principal B's own request for the same task id -- B does not own it.
        return Promise.resolve(jsonResponse({ detail: "Task not found" }, 404));
      }
      if (url.endsWith("/tasks/task-1") && method === "PATCH") {
        // A genuine, successful (never 409) Save response. Held
        // deliberately and released only after the SPA has switched to a
        // different principal, to prove the ordinary success path can
        // never publish A's Task into the cache or invalidate B's queries.
        return new Promise<Response>((resolve) => {
          releaseHeldSave = () =>
            resolve(
              jsonResponse({
                ...taskResponse.items[0],
                title: "A UPDATED TITLE (must never publish)",
                details: "A's saved details",
                revision: 2
              })
            );
        });
      }
      if (url.endsWith("/tasks") || url.includes("/tasks?")) {
        return Promise.resolve(jsonResponse(emptyTaskListResponse));
      }
      if (url.includes("/projects")) {
        return Promise.resolve(jsonResponse(projectsResponse));
      }
      if (url.includes("/tags")) {
        return Promise.resolve(jsonResponse(tagsResponse));
      }
      return Promise.resolve(jsonResponse(null));
    });

    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={["/tasks/next/task-1"]}>
          <AppRoutes />
        </MemoryRouter>
      </QueryClientProvider>
    );

    expect(await screen.findByLabelText("Details")).toHaveValue("Original details");
    await user.clear(screen.getByLabelText("Details"));
    await user.type(screen.getByLabelText("Details"), "My unsaved draft edit");
    await user.click(screen.getByRole("button", { name: "Save task detail" }));

    await waitFor(() => expect(releaseHeldSave).toBeDefined());

    // Session loss, then a different principal signs in from the same
    // preserved URL -- while the Save above is still held in flight.
    act(() => {
      useAuthStore.setState({ user: null, status: "anon" });
    });
    expect(await screen.findByRole("heading", { name: "Sign in to Brain Buddy" })).toBeInTheDocument();

    await user.type(screen.getByLabelText("Email"), "b@example.test");
    await user.type(screen.getByLabelText("Password"), "correct horse battery staple");
    await user.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Task not found");
    const tasksListGetCountBeforeRelease = taskGetCount;

    // Release the held Save strictly after B's own 404 landed.
    await act(async () => {
      releaseHeldSave?.();
      await flushMicrotasks();
    });

    // The late, successful arrival must be inert: it never publishes A's
    // Task into either principal's cache slot, never re-invalidates/
    // refetches on B's behalf, and B's honest not-found state survives it
    // untouched.
    expect(screen.queryByText("A UPDATED TITLE (must never publish)")).not.toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("Task not found");
    expect(client.getQueryData(["tasks", "user-1", "detail", "task-1"])).toBeUndefined();
    expect(client.getQueryData(["tasks", "user-2", "detail", "task-1"])).toBeUndefined();
    expect(taskGetCount).toBe(tasksListGetCountBeforeRelease);
  });
});
