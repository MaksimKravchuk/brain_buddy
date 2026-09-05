import { act, createRef } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type {
  ProjectResponse,
  TagResponse,
  TaskCommentResponse,
  TaskResponse,
  TaskState,
  TaskSubtaskResponse
} from "../../../api/taskTypes";
import { apiClient } from "../../../api/client";
import { ShellToastContext } from "../../../components/shell/shellToast";
import { useAuthStore } from "../../../stores/authStore";
import { TaskDetailPanel } from "../TaskDetailPanel";

vi.mock("../../agents/AgentRunSection", () => ({
  AgentRunSection: ({ runs }: { runs: Array<{ capabilities?: { reply: boolean; cancel: boolean }; reported_state?: string }> }) => (
    <div data-testid="agent-run-count">
      {runs.length}
      {runs.some((run) => run.reported_state === "blocked" && run.capabilities?.reply) ? <button>Send answer</button> : null}
      {runs.some((run) => run.capabilities?.cancel) ? <button>Request cancellation</button> : null}
    </div>
  )
}));

vi.mock("../../agents/AgentHandoffOverlay", () => ({
  AgentHandoffOverlay: ({
    onClose,
    onDispatched
  }: {
    onClose: () => void;
    onDispatched: (run: never) => void;
  }) => (
    <div>
      <h2>Hand this task to an agent</h2>
      <button type="button" onClick={onClose}>
        Close handoff
      </button>
      <button type="button" onClick={() => onDispatched({} as never)}>
        Simulate dispatch
      </button>
    </div>
  )
}));

const projects: ProjectResponse[] = [
  { id: "project-launch", name: "Launch v2", color: "#0ea5e9", state: "active", revision: 1, open_task_count: 2 },
  { id: "project-onboarding", name: "Onboarding drop-off", color: null, state: "active", revision: 1, open_task_count: 1 }
];

const tags: TagResponse[] = [
  { id: "tag-calls", name: "@calls", state: "active", revision: 1, open_task_count: 2 },
  { id: "tag-deep-work", name: "#deep-work", state: "active", revision: 1, open_task_count: 1 }
];

function taskFixture(overrides: Partial<TaskResponse> = {}): TaskResponse {
  return {
    id: "task-1",
    title: "Fix onboarding drop-off",
    details: null,
    state: "next",
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

function subtaskFixture(overrides: Partial<TaskSubtaskResponse> = {}): TaskSubtaskResponse {
  return { id: "subtask-1", title: "Draft the copy", state: "open", order_key: 1, revision: 2, ...overrides };
}

function commentFixture(overrides: Partial<TaskCommentResponse> = {}): TaskCommentResponse {
  return {
    id: "comment-1",
    body: "Waiting on the analytics export.",
    actor_id: "usr_9fa",
    created_at: "2026-07-16T09:30:00Z",
    edited_at: null,
    revision: 1,
    ...overrides
  };
}

type PanelProps = Parameters<typeof TaskDetailPanel>[0];

function renderPanel(overrides: Partial<PanelProps> = {}) {
  const handlers = {
    onClose: vi.fn(),
    onSave: vi.fn(),
    onTransition: vi.fn(),
    onCreateSubtask: vi.fn(),
    onTransitionSubtask: vi.fn(),
    onCreateComment: vi.fn()
  };
  const notify = vi.fn();
  const headingRef = createRef<HTMLHeadingElement>();
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const view = render(
    <QueryClientProvider client={queryClient}>
      <ShellToastContext.Provider value={notify}>
        <TaskDetailPanel
          task={taskFixture()}
          projects={projects}
          tags={tags}
          isLoading={false}
          error={null}
          headingRef={headingRef}
          {...handlers}
          {...overrides}
        />
      </ShellToastContext.Provider>
    </QueryClientProvider>
  );
  return { ...view, ...handlers, notify, headingRef };
}

afterEach(() => {
  vi.restoreAllMocks();
  act(() => {
    useAuthStore.setState({ user: null, status: "loading", deletionCancelledNotice: false });
  });
});

describe("TaskDetailPanel chrome", () => {
  it("normalizes cleared optional fields through the non-autosave fallback", () => {
    const { onSave } = renderPanel({
      task: taskFixture({ due_date: "2026-08-01", project_id: "project-launch" })
    });

    fireEvent.change(screen.getByLabelText("Due date"), { target: { value: "" } });
    fireEvent.change(screen.getByLabelText("Project"), { target: { value: "" } });
    fireEvent.click(screen.getByRole("checkbox", { name: "#deep-work" }));

    expect(onSave).toHaveBeenCalledWith(expect.any(Object), expect.objectContaining({ due_date: null }));
    expect(onSave).toHaveBeenCalledWith(expect.any(Object), expect.objectContaining({ project_id: null }));
    expect(onSave).toHaveBeenCalledWith(expect.any(Object), expect.objectContaining({ tag_ids: [] }));
  });

  it("switches due dates with task identity without remounting on revisions", () => {
    const first = taskFixture({ due_date: "2026-08-01" });
    const second = taskFixture({ id: "task-2", due_date: "2026-09-15", revision: 5 });
    const props = {
      projects,
      tags,
      isLoading: false,
      error: null,
      headingRef: createRef<HTMLHeadingElement>(),
      onClose: vi.fn(),
      onSave: vi.fn(),
      onTransition: vi.fn(),
      onCreateSubtask: vi.fn(),
      onTransitionSubtask: vi.fn(),
      onCreateComment: vi.fn()
    };
    const queryClient = new QueryClient();
    const { rerender } = render(
      <QueryClientProvider client={queryClient}>
        <TaskDetailPanel task={first} resetKey={0} {...props} />
      </QueryClientProvider>
    );
    const dueDate = screen.getByLabelText("Due date");
    rerender(
      <QueryClientProvider client={queryClient}>
        <TaskDetailPanel task={{ ...first, revision: 5 }} resetKey={0} {...props} />
      </QueryClientProvider>
    );
    expect(screen.getByLabelText("Due date")).toBe(dueDate);
    rerender(
      <QueryClientProvider client={queryClient}>
        <TaskDetailPanel task={second} resetKey={0} {...props} />
      </QueryClientProvider>
    );
    expect(screen.getByLabelText("Due date")).toHaveValue("2026-09-15");
  });

  it("ignores submit events after their named draft control has disappeared", () => {
    const { onCreateSubtask, onCreateComment } = renderPanel();
    const subtaskInput = screen.getByLabelText("New subtask title");
    const subtaskForm = subtaskInput.closest("form");
    if (!subtaskForm) throw new Error("Subtask form is missing");
    subtaskInput.remove();
    fireEvent.submit(subtaskForm);

    const commentInput = screen.getByLabelText("New comment");
    const commentForm = commentInput.closest("form");
    if (!commentForm) throw new Error("Comment form is missing");
    commentInput.remove();
    fireEvent.submit(commentForm);

    expect(onCreateSubtask).not.toHaveBeenCalled();
    expect(onCreateComment).not.toHaveBeenCalled();
  });

  it("shows an enabled relay entry point for an open task and hides it for an empty terminal history", async () => {
    vi.spyOn(apiClient, "listAgentRuns").mockResolvedValue([]);
    vi.spyOn(apiClient, "listAgentConnections").mockResolvedValue([]);
    act(() => {
      useAuthStore.setState({
        user: {
          id: "user-1",
          email: "max@example.test",
          feature_flags: { external_agent_relay: true }
        },
        status: "authed",
        deletionCancelledNotice: false
      });
    });

    const open = renderPanel();
    const user = userEvent.setup();
    const handoff = await screen.findByRole("button", { name: "Hand to agent" });
    expect(handoff).toBeInTheDocument();
    expect(
      screen.getByText("Review exactly what would be sent before anything leaves BrainBuddy.")
    ).toBeInTheDocument();
    await user.click(handoff);
    expect(await screen.findByRole("heading", { name: "Hand this task to an agent" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Close handoff" }));
    expect(screen.queryByRole("heading", { name: "Hand this task to an agent" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Hand to agent" }));
    await user.click(screen.getByRole("button", { name: "Simulate dispatch" }));
    expect(screen.queryByRole("heading", { name: "Hand this task to an agent" })).not.toBeInTheDocument();

    open.unmount();
    const terminalEmpty = renderPanel({
      task: taskFixture({
        state: "completed",
        completed_at: "2026-07-17T08:00:00Z"
      })
    });
    expect(await screen.findByText("Fix onboarding drop-off")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Hand to agent" })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "External agent" })).not.toBeInTheDocument();

    terminalEmpty.unmount();
    vi.mocked(apiClient.listAgentRuns).mockResolvedValue([{} as never]);
    renderPanel({
      task: taskFixture({
        state: "completed",
        completed_at: "2026-07-17T08:00:00Z"
      })
    });
    expect(await screen.findByRole("heading", { name: "External agent" })).toBeInTheDocument();
    expect(screen.getByTestId("agent-run-count")).toHaveTextContent("1");
    expect(screen.queryByRole("button", { name: "Hand to agent" })).not.toBeInTheDocument();
    expect(screen.queryByText("Review exactly what would be sent before anything leaves BrainBuddy.")).not.toBeInTheDocument();
  });

  it("keeps an existing actionable run visible while rollout is off without exposing a new handoff", async () => {
    vi.spyOn(apiClient, "listAgentRuns").mockResolvedValue([
      { reported_state: "blocked", capabilities: { progress: true, reply: true, cancel: true } } as never
    ]);
    act(() => {
      useAuthStore.setState({
        user: { id: "user-1", email: "max@example.test", feature_flags: {} },
        status: "authed",
        deletionCancelledNotice: false
      });
    });

    renderPanel();

    await waitFor(() => expect(screen.getByTestId("agent-run-count")).toHaveTextContent("1"));
    expect(apiClient.listAgentRuns).toHaveBeenCalledWith("task-1", expect.any(AbortSignal));
    expect(screen.getByRole("button", { name: "Send answer" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Request cancellation" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Hand to agent" })).not.toBeInTheDocument();
    expect(screen.queryByText(/review exactly what would be sent/i)).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Hand this task to an agent" })).not.toBeInTheDocument();
  });

  it("keeps rollout-off tasks with no run unobtrusive", async () => {
    vi.spyOn(apiClient, "listAgentRuns").mockResolvedValue([]);
    act(() => {
      useAuthStore.setState({
        user: { id: "user-1", email: "max@example.test", feature_flags: {} },
        status: "authed",
        deletionCancelledNotice: false
      });
    });

    renderPanel();

    await screen.findByText("Fix onboarding drop-off");
    expect(apiClient.listAgentRuns).toHaveBeenCalled();
    expect(screen.queryByRole("heading", { name: "External agent" })).not.toBeInTheDocument();
    expect(screen.getByTestId("agent-run-count")).toHaveTextContent("0");
  });

  it("closes on the chevron without exposing placeholder thinking actions", async () => {
    const user = userEvent.setup();
    const { onClose } = renderPanel();

    await user.click(screen.getByRole("button", { name: "Close" }));
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("button", { name: "Thinking canvas" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Think" })).not.toBeInTheDocument();
  });

  it("opens the overflow menu, cancels the task from it, and closes it again on a second click", async () => {
    const user = userEvent.setup();
    const task = taskFixture();
    const { onTransition } = renderPanel({ task });

    const menuButton = screen.getByRole("button", { name: "Task menu" });
    expect(menuButton).toHaveAttribute("aria-expanded", "false");

    await user.click(menuButton);
    expect(menuButton).toHaveAttribute("aria-expanded", "true");
    await user.click(menuButton);
    expect(screen.queryByRole("button", { name: "Cancel task" })).not.toBeInTheDocument();

    await user.click(menuButton);
    await user.click(screen.getByRole("button", { name: "Cancel task" }));
    expect(onTransition).toHaveBeenCalledWith(task, "cancel");
    expect(screen.queryByRole("button", { name: "Cancel task" })).not.toBeInTheDocument();
  });

  it("hides the destructive menu once the task is terminal", () => {
    renderPanel({ task: taskFixture({ state: "completed", completed_at: "2026-07-17T08:00:00Z" }) });

    expect(screen.queryByRole("button", { name: "Task menu" })).not.toBeInTheDocument();
  });

  it("shows nothing but chrome while there is no task yet, and surfaces loading and error copy", () => {
    const { rerender, headingRef } = renderPanel({ task: undefined, isLoading: true });

    expect(screen.getByText("Loading task detail…")).toBeInTheDocument();
    expect(screen.queryByLabelText("Title")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Task menu" })).not.toBeInTheDocument();
    expect(headingRef.current).toBe(screen.getByRole("heading", { name: "Task detail" }));

    rerender(
      <ShellToastContext.Provider value={vi.fn()}>
        <TaskDetailPanel
          task={undefined}
          projects={projects}
          tags={tags}
          isLoading={false}
          error={new Error("Task detail is unavailable.")}
          headingRef={headingRef}
          onClose={vi.fn()}
          onSave={vi.fn()}
          onTransition={vi.fn()}
          onCreateSubtask={vi.fn()}
          onTransitionSubtask={vi.fn()}
          onCreateComment={vi.fn()}
        />
      </ShellToastContext.Provider>
    );

    expect(screen.getByRole("alert")).toHaveTextContent("Task detail is unavailable.");
    expect(screen.queryByText("Loading task detail…")).not.toBeInTheDocument();
  });

  it("closes an open menu when the panel switches to another task", async () => {
    const user = userEvent.setup();
    const headingRef = createRef<HTMLHeadingElement>();
    const props = {
      projects,
      tags,
      isLoading: false,
      error: null,
      headingRef,
      onClose: vi.fn(),
      onSave: vi.fn(),
      onTransition: vi.fn(),
      onCreateSubtask: vi.fn(),
      onTransitionSubtask: vi.fn(),
      onCreateComment: vi.fn()
    };
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const { rerender } = render(
      <QueryClientProvider client={queryClient}>
        <TaskDetailPanel task={taskFixture()} {...props} />
      </QueryClientProvider>
    );

    await user.click(screen.getByRole("button", { name: "Task menu" }));
    expect(screen.getByRole("button", { name: "Cancel task" })).toBeInTheDocument();

    rerender(
      <QueryClientProvider client={queryClient}>
        <TaskDetailPanel task={taskFixture({ id: "task-2", title: "Second task" })} {...props} />
      </QueryClientProvider>
    );

    expect(screen.queryByRole("button", { name: "Cancel task" })).not.toBeInTheDocument();
  });
});

describe("TaskDetailPanel editing", () => {
  it("resets a same-task draft when the canonical reset signal changes", async () => {
    const user = userEvent.setup();
    const task = taskFixture({ title: "Canonical title", details: "Canonical details" });
    const props = {
      projects,
      tags,
      isLoading: false,
      error: null,
      headingRef: createRef<HTMLHeadingElement>(),
      onClose: vi.fn(),
      onSave: vi.fn(),
      onTransition: vi.fn(),
      onCreateSubtask: vi.fn(),
      onTransitionSubtask: vi.fn(),
      onCreateComment: vi.fn()
    };
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const { rerender } = render(
      <QueryClientProvider client={queryClient}>
        <ShellToastContext.Provider value={vi.fn()}>
          <TaskDetailPanel task={task} resetKey={0} {...props} />
        </ShellToastContext.Provider>
      </QueryClientProvider>
    );

    await user.clear(screen.getByLabelText("Title"));
    await user.type(screen.getByLabelText("Title"), "Rejected title");
    await user.clear(screen.getByLabelText("Details"));
    await user.type(screen.getByLabelText("Details"), "Rejected details");

    rerender(
      <QueryClientProvider client={queryClient}>
        <ShellToastContext.Provider value={vi.fn()}>
          <TaskDetailPanel task={task} resetKey={1} {...props} />
        </ShellToastContext.Provider>
      </QueryClientProvider>
    );

    expect(screen.getByLabelText("Title")).toHaveValue("Canonical title");
    expect(screen.getByLabelText("Details")).toHaveValue("Canonical details");
  });

  it("keeps later metadata drafts through an older acknowledgement", async () => {
    const user = userEvent.setup();
    const initial = taskFixture({ due_date: "2026-08-01" });
    const props = {
      projects,
      tags,
      isLoading: false,
      error: null,
      headingRef: createRef<HTMLHeadingElement>(),
      onClose: vi.fn(),
      onSave: vi.fn(),
      onTransition: vi.fn(),
      onCreateSubtask: vi.fn(),
      onTransitionSubtask: vi.fn(),
      onCreateComment: vi.fn()
    };
    const queryClient = new QueryClient();
    const { rerender } = render(
      <QueryClientProvider client={queryClient}>
        <TaskDetailPanel task={initial} resetKey={0} {...props} />
      </QueryClientProvider>
    );

    await user.selectOptions(screen.getByLabelText("List"), "someday");
    await user.selectOptions(screen.getByLabelText("Project"), "project-onboarding");
    await user.selectOptions(screen.getByLabelText("Priority"), "high");
    await user.click(screen.getByRole("checkbox", { name: "#calls" }));
    fireEvent.change(screen.getByLabelText("Due date"), { target: { value: "2026-09-03" } });

    rerender(
      <QueryClientProvider client={queryClient}>
        <TaskDetailPanel task={{ ...initial, details: "older acknowledgement", revision: 5 }} resetKey={0} {...props} />
      </QueryClientProvider>
    );

    expect(screen.getByLabelText("List")).toHaveValue("someday");
    expect(screen.getByLabelText("Project")).toHaveValue("project-onboarding");
    expect(screen.getByLabelText("Priority")).toHaveValue("high");
    expect(screen.getByRole("checkbox", { name: "#calls" })).toBeChecked();
    expect(screen.getByLabelText("Due date")).toHaveValue("2026-09-03");
  });

  it("saves a changed title on blur and commits with Enter rather than inserting a newline", async () => {
    const user = userEvent.setup();
    const task = taskFixture();
    const { onSave } = renderPanel({ task });

    const title = screen.getByLabelText("Title");
    await user.clear(title);
    await user.type(title, "Fix onboarding drop-off properly{Enter}");

    expect(title).not.toHaveFocus();
    expect(onSave).toHaveBeenCalledWith(task, {
      title: "Fix onboarding drop-off properly",
      expected_revision: 4
    });
  });

  it("leaves the title alone when it is unchanged or blanked", async () => {
    const user = userEvent.setup();
    const { onSave } = renderPanel();

    const title = screen.getByLabelText("Title");
    await user.click(title);
    await user.tab();
    expect(onSave).not.toHaveBeenCalled();

    await user.clear(title);
    await user.tab();
    expect(onSave).not.toHaveBeenCalled();
  });

  it("keeps a shift-Enter newline inside the title instead of committing", async () => {
    const user = userEvent.setup();
    const { onSave } = renderPanel();

    const title = screen.getByLabelText("Title");
    await user.clear(title);
    await user.type(title, "First line{Shift>}{Enter}{/Shift}second line");

    expect(title).toHaveFocus();
    expect(onSave).not.toHaveBeenCalled();
  });

  it("saves the due date, the project, the priority and tag toggles with the current revision", async () => {
    const user = userEvent.setup();
    const task = taskFixture({ due_date: "2026-07-20" });
    const { onSave } = renderPanel({ task });

    const dueDate = screen.getByLabelText("Due date");
    expect(dueDate).toHaveValue("2026-07-20");
    await user.clear(dueDate);
    expect(onSave).toHaveBeenLastCalledWith(task, { due_date: null, expected_revision: 4 });

    await user.type(dueDate, "2026-08-01");
    expect(onSave).toHaveBeenLastCalledWith(task, { due_date: "2026-08-01", expected_revision: 4 });

    await user.selectOptions(screen.getByLabelText("Project"), "project-onboarding");
    expect(onSave).toHaveBeenLastCalledWith(task, { project_id: "project-onboarding", expected_revision: 4 });

    await user.selectOptions(screen.getByLabelText("Project"), "");
    expect(onSave).toHaveBeenLastCalledWith(task, { project_id: null, expected_revision: 4 });

    await user.selectOptions(screen.getByLabelText("Priority"), "high");
    expect(onSave).toHaveBeenLastCalledWith(task, { priority: "high", expected_revision: 4 });

    await user.click(screen.getByRole("checkbox", { name: "#calls" }));
    expect(onSave).toHaveBeenLastCalledWith(task, {
      tag_ids: ["tag-deep-work", "tag-calls"],
      expected_revision: 4
    });

    await user.click(screen.getByRole("checkbox", { name: "#deep-work" }));
    expect(onSave).toHaveBeenLastCalledWith(task, { tag_ids: ["tag-calls"], expected_revision: 4 });
  });

  it("saves details only when the text actually changed", async () => {
    const user = userEvent.setup();
    const task = taskFixture({ details: "Existing notes" });
    const { onSave } = renderPanel({ task });

    const details = screen.getByLabelText("Details");
    await user.click(details);
    await user.tab();
    expect(onSave).not.toHaveBeenCalled();

    await user.clear(details);
    await user.tab();
    expect(onSave).toHaveBeenLastCalledWith(task, { details: null, expected_revision: 4 });

    await user.type(details, "Analytics export first");
    await user.tab();
    expect(onSave).toHaveBeenLastCalledWith(task, { details: "Analytics export first", expected_revision: 4 });
  });

  it("saves waiting-for only for a waiting task, and only when it changed", async () => {
    const user = userEvent.setup();
    const nextTask = taskFixture();
    const { onSave, unmount } = renderPanel({ task: nextTask });

    await user.type(screen.getByLabelText("Waiting for"), "Design review");
    await user.tab();
    expect(onSave).not.toHaveBeenCalled();
    unmount();

    const waitingTask = taskFixture({ state: "waiting", waiting_for: "Design review" });
    const second = renderPanel({ task: waitingTask });
    const field = screen.getByLabelText("Waiting for");
    expect(field).toHaveValue("Design review");

    await user.click(field);
    await user.tab();
    expect(second.onSave).not.toHaveBeenCalled();

    await user.clear(field);
    await user.type(field, "Finance sign-off");
    await user.tab();
    expect(second.onSave).toHaveBeenLastCalledWith(waitingTask, {
      waiting_for: "Finance sign-off",
      expected_revision: 4
    });
  });
});

describe("TaskDetailPanel transitions", () => {
  it("completes an open task and reopens a terminal one from the same control", async () => {
    const user = userEvent.setup();
    const openTask = taskFixture();
    const first = renderPanel({ task: openTask });

    await user.click(screen.getByRole("button", { name: "Complete task" }));
    expect(first.onTransition).toHaveBeenCalledWith(openTask, "complete", undefined);
    first.unmount();

    const cancelled = taskFixture({ state: "cancelled", cancelled_at: "2026-07-18T08:00:00Z" });
    const second = renderPanel({ task: cancelled });

    await user.click(screen.getByRole("button", { name: "Reopen task" }));
    expect(second.onTransition).toHaveBeenCalledWith(cancelled, "reopen", "inbox");
  });

  it("promotes an Inbox task through an explicit next-action control", async () => {
    const user = userEvent.setup();
    const task = taskFixture({ state: "inbox" });
    const { onTransition } = renderPanel({ task });

    const action = screen.getByRole("button", { name: "Move to Next actions" });
    action.focus();
    await user.keyboard("{Enter}");

    expect(onTransition).toHaveBeenCalledWith(task, "move", "next");
    expect(screen.getByLabelText("List")).toHaveValue("next");
    expect(screen.queryByRole("button", { name: "Move to Next actions" })).not.toBeInTheDocument();
  });

  it("moves an open task between lists and carries the live waiting-for value into a waiting move", async () => {
    const user = userEvent.setup();
    const task = taskFixture();
    const { onTransition } = renderPanel({ task });

    await user.selectOptions(screen.getByLabelText("List"), "someday");
    expect(onTransition).toHaveBeenLastCalledWith(task, "move", "someday", undefined);

    await user.type(screen.getByLabelText("Waiting for"), "Finance");
    await user.selectOptions(screen.getByLabelText("List"), "waiting");
    expect(onTransition).toHaveBeenLastCalledWith(task, "move", "waiting", "Finance");
  });

  it("offers a terminal task the reopen-to targets and ignores the inert placeholder option", async () => {
    const user = userEvent.setup();
    const task = taskFixture({ state: "completed", completed_at: "2026-07-17T08:00:00Z" });
    const { onTransition } = renderPanel({ task });

    const list = screen.getByLabelText("List");
    expect(list).toHaveValue("");
    expect(within(list).getByRole("option", { name: "Completed" })).toBeInTheDocument();
    expect(within(list).getByRole("option", { name: "Reopen to Next actions" })).toBeInTheDocument();

    await user.selectOptions(list, "next");
    expect(onTransition).toHaveBeenCalledWith(task, "reopen", "next", undefined);

    await user.selectOptions(list, "");
    expect(onTransition).toHaveBeenCalledTimes(1);
  });

  it("labels a cancelled task's inert list option as Cancelled", () => {
    renderPanel({ task: taskFixture({ state: "cancelled", cancelled_at: "2026-07-18T08:00:00Z" }) });

    expect(within(screen.getByLabelText("List")).getByRole("option", { name: "Cancelled" })).toBeInTheDocument();
  });
});

describe("TaskDetailPanel subtasks and comments", () => {
  it("reports subtask progress and toggles a subtask both ways", async () => {
    const user = userEvent.setup();
    const task = taskFixture({
      subtasks: [
        subtaskFixture(),
        subtaskFixture({ id: "subtask-2", title: "Ship the fix", state: "completed", revision: 3 })
      ]
    });
    const { onTransitionSubtask } = renderPanel({ task });

    expect(screen.getByRole("heading", { name: "Subtasks · 1 / 2" })).toBeInTheDocument();
    expect(screen.getByText("50%")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Complete Draft the copy" }));
    expect(onTransitionSubtask).toHaveBeenLastCalledWith(task, task.subtasks?.[0], "complete");

    await user.click(screen.getByRole("button", { name: "Reopen Ship the fix" }));
    expect(onTransitionSubtask).toHaveBeenLastCalledWith(task, task.subtasks?.[1], "reopen");
  });

  it("renders a projectless task with the neutral swatch and no comment list", async () => {
    const user = userEvent.setup();
    const task = taskFixture({
      project_id: null,
      state: "waiting",
      waiting_for: null,
      comments: undefined
    });
    const { onSave } = renderPanel({ task });

    expect(screen.getByLabelText("Project")).toHaveValue("");
    expect(screen.getByLabelText("Waiting for")).toHaveValue("");
    expect(screen.queryByText(/·/)).not.toBeInTheDocument();

    // A waiting task with no recorded blocker still saves the first value typed.
    await user.type(screen.getByLabelText("Waiting for"), "Finance");
    await user.tab();
    expect(onSave).toHaveBeenCalledWith(task, { waiting_for: "Finance", expected_revision: 4 });
  });

  it("drops the progress meter when a task has no subtasks", () => {
    renderPanel({ task: taskFixture({ subtasks: undefined }) });

    expect(screen.getByRole("heading", { name: "Subtasks" })).toBeInTheDocument();
    expect(screen.queryByText("%", { exact: false })).not.toBeInTheDocument();
  });

  it("creates a subtask on submit, resets the field, and ignores a blank one", async () => {
    const user = userEvent.setup();
    const task = taskFixture();
    const { onCreateSubtask } = renderPanel({ task });

    const field = screen.getByLabelText("New subtask title");
    await user.type(field, "   {Enter}");
    expect(onCreateSubtask).not.toHaveBeenCalled();

    await user.clear(field);
    await user.type(field, "Draft the copy{Enter}");
    expect(onCreateSubtask).toHaveBeenCalledWith(task, "Draft the copy");
    expect(field).toHaveValue("");
  });

  it("creates a comment on submit, resets the field, and ignores a blank one", async () => {
    const user = userEvent.setup();
    const task = taskFixture();
    const { onCreateComment } = renderPanel({ task });

    const field = screen.getByLabelText("New comment");
    await user.type(field, "  {Enter}");
    expect(onCreateComment).not.toHaveBeenCalled();

    await user.type(field, "Blocked on analytics{Enter}");
    expect(onCreateComment).toHaveBeenCalledWith(task, "Blocked on analytics");
    expect(field).toHaveValue("");
  });

  it("renders each comment with an actor initialism and a readable date, falling back to the raw value", () => {
    renderPanel({
      task: taskFixture({
        comments: [commentFixture(), commentFixture({ id: "comment-2", body: "Second note", created_at: "not-a-date" })]
      })
    });

    const formatted = new Date("2026-07-16T09:30:00Z").toLocaleDateString(undefined, {
      month: "short",
      day: "numeric"
    });
    expect(screen.getByText("Waiting on the analytics export.")).toBeInTheDocument();
    expect(screen.getByText(`US · ${formatted}`)).toBeInTheDocument();
    expect(screen.getByText("US · not-a-date")).toBeInTheDocument();
  });
});

describe("TaskDetailPanel terminal presentation", () => {
  it.each<[TaskState, string]>([
    ["completed", "Completed"],
    ["cancelled", "Cancelled"]
  ])("strikes a %s title through and keeps its list option inert", (state, label) => {
    renderPanel({ task: taskFixture({ state }) });

    expect(screen.getByLabelText("Title")).toHaveClass("line-through");
    expect(within(screen.getByLabelText("List")).getByRole("option", { name: label })).toBeInTheDocument();
  });
});
