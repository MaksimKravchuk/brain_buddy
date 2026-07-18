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
  it("redirects the authenticated root route into the source-faithful next actions shell", async () => {
    renderRoutes("/");

    expect(await screen.findByRole("heading", { name: "Next actions" })).toBeInTheDocument();
    expect(screen.getByRole("banner")).toHaveStyle({ height: "52px" });
    expect(screen.getByText("Brain Buddy")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("Search tasks")).toBeEnabled();
    expect(screen.getByRole("button", { name: "Brain dump" })).toBeEnabled();
    expect(await screen.findByText("6 tasks")).toBeInTheDocument();
  });

  it("renders projects, tags and task rows from server projections without Context copy", async () => {
    renderRoutes("/tasks/next");

    expect(await screen.findByRole("heading", { name: "Next actions" })).toBeInTheDocument();
    const sidebar = screen.getByRole("navigation", { name: "Task navigation" });
    expect(within(sidebar).getByText("Inbox")).toBeInTheDocument();
    expect(await within(sidebar).findByText("17")).toBeInTheDocument();
    expect(within(sidebar).getByText("Projects")).toBeInTheDocument();
    expect(within(sidebar).getByText("Launch v2")).toBeInTheDocument();
    expect(within(sidebar).getByText("Tags")).toBeInTheDocument();
    expect(within(sidebar).queryByText("Contexts")).not.toBeInTheDocument();
    expect(within(sidebar).getByText("@deep-work")).toBeInTheDocument();

    expect(screen.getByText("Fix onboarding drop-off")).toBeInTheDocument();
    expect(screen.getAllByText("Onboarding drop-off").length).toBeGreaterThanOrEqual(2);
    expect(screen.getAllByText(/@deep-work/).length).toBeGreaterThanOrEqual(2);
  });

  it("keeps the legacy CRT workspace isolated under /crt/*", async () => {
    renderRoutes("/crt/demo-tree");

    expect(await screen.findByText("legacy CRT workspace")).toBeInTheDocument();
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

    await user.type(screen.getByLabelText("New project name"), "Client work{Enter}");
    await waitFor(() => {
      expect(fetch).toHaveBeenCalledWith(
        expect.stringMatching(/\/projects$/),
        expect.objectContaining({ method: "POST", body: expect.stringContaining("Client work") })
      );
    });

    await user.clear(screen.getByLabelText("Project name Onboarding drop-off"));
    await user.type(screen.getByLabelText("Project name Onboarding drop-off"), "Activation{Enter}");
    await waitFor(() => {
      expect(fetch).toHaveBeenCalledWith(
        expect.stringMatching(/\/projects\/project-onboarding$/),
        expect.objectContaining({ method: "PATCH", body: expect.stringContaining("Activation") })
      );
    });

    await user.click(screen.getAllByRole("button", { name: "Archive" })[1]);
    await waitFor(() => {
      expect(fetch).toHaveBeenCalledWith(
        expect.stringMatching(/\/projects\/project-onboarding\/archive$/),
        expect.objectContaining({ method: "POST" })
      );
    });

    await waitFor(() => {
      expect(fetch).toHaveBeenCalledWith(expect.stringContaining("/tasks?state=next"), expect.anything());
    });

    await user.type(screen.getByLabelText("New tag name"), "errands{Enter}");
    await waitFor(() => {
      expect(fetch).toHaveBeenCalledWith(
        expect.stringMatching(/\/tags$/),
        expect.objectContaining({ method: "POST", body: expect.stringContaining("errands") })
      );
    });

    await user.clear(screen.getByLabelText("Tag name deep-work"));
    await user.type(screen.getByLabelText("Tag name deep-work"), "focus{Enter}");
    await waitFor(() => {
      expect(fetch).toHaveBeenCalledWith(
        expect.stringMatching(/\/tags\/tag-deep-work$/),
        expect.objectContaining({ method: "PATCH", body: expect.stringContaining("focus") })
      );
    });

    await user.click(screen.getAllByRole("button", { name: "Delete" })[1]);
    await waitFor(() => {
      expect(fetch).toHaveBeenCalledWith(
        expect.stringMatching(/\/tags\/tag-deep-work\?expected_revision=1$/),
        expect.objectContaining({ method: "DELETE" })
      );
    });

    await user.selectOptions(screen.getByLabelText("Project for Fix onboarding drop-off"), "project-launch");
    await waitFor(() => {
      expect(fetch).toHaveBeenCalledWith(
        expect.stringMatching(/\/tasks\/task-1$/),
        expect.objectContaining({ method: "PATCH", body: expect.stringContaining('"project_id":"project-launch"') })
      );
    });

    await user.selectOptions(screen.getByLabelText("Add tag to Fix onboarding drop-off"), "tag-calls");
    await waitFor(() => {
      expect(fetch).toHaveBeenCalledWith(
        expect.stringMatching(/\/tasks\/task-1$/),
        expect.objectContaining({ method: "PATCH", body: expect.stringContaining('"tag_ids":["tag-deep-work","tag-calls"]') })
      );
    });

    await user.click(screen.getByRole("button", { name: "Remove deep-work from Fix onboarding drop-off" }));
    await waitFor(() => {
      expect(fetch).toHaveBeenCalledWith(
        expect.stringMatching(/\/tasks\/task-1$/),
        expect.objectContaining({ method: "PATCH", body: expect.stringContaining('"tag_ids":[]') })
      );
    });
  });

  it("returns to Next actions when the active Project or Tag view is archived or deleted", async () => {
    const user = userEvent.setup();
    const projectView = renderRoutes("/projects/project-onboarding");

    expect(await screen.findByRole("heading", { name: "Onboarding drop-off" })).toBeInTheDocument();
    await user.click(screen.getAllByRole("button", { name: "Archive" })[1]);
    await waitFor(() => {
      expect(fetch).toHaveBeenCalledWith(expect.stringContaining("/tasks?state=next"), expect.anything());
    });

    projectView.unmount();
    renderRoutes("/tags/tag-deep-work");

    expect(await screen.findByRole("heading", { name: "@deep-work" })).toBeInTheDocument();
    await user.click(screen.getAllByRole("button", { name: "Delete" })[1]);
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
});
