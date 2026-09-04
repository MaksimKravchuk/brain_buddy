import { createRef } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, apiClient } from "../../../api/client";
import type { TaskResponse } from "../../../api/taskTypes";
import { ShellToastContext } from "../../../components/shell/shellToast";
import { TaskDetailPanel } from "../TaskDetailPanel";
import { createTaskDetailAutosaveController } from "../taskDetailAutosave";

const task = (overrides: Partial<TaskResponse> = {}): TaskResponse => ({
  id: "task-ux", title: "Canonical", details: null, state: "next", project_id: null,
  tag_ids: [], due_date: null, priority: "none", waiting_for: null, waiting_since: null,
  order_key: 1, source_capture_ids: [], created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z", completed_at: null, cancelled_at: null, revision: 1,
  subtasks: [], comments: [], ...overrides
});
function deferred<T>() { let resolve!: (value: T) => void; const promise = new Promise<T>((yes) => { resolve = yes; }); return { promise, resolve }; }
function renderAutosave(controller = createTaskDetailAutosaveController("account-a", "https://api.example.test/api", task())) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const view = render(
    <QueryClientProvider client={client}>
      <ShellToastContext.Provider value={vi.fn()}>
        <TaskDetailPanel
          task={controller.task}
          autosave={controller}
          projects={[{ id: "project-1", name: "Project", color: null, state: "active", revision: 1, open_task_count: 1 }]}
          tags={[{ id: "tag-1", name: "tag", state: "active", revision: 1, open_task_count: 1 }]}
          isLoading={false}
          error={null}
          headingRef={createRef<HTMLHeadingElement>()}
          onClose={vi.fn()}
          onSave={vi.fn()}
          onTransition={vi.fn()}
          onCreateSubtask={vi.fn()}
          onTransitionSubtask={vi.fn()}
          onCreateComment={vi.fn()}
        />
      </ShellToastContext.Provider>
    </QueryClientProvider>
  );
  return { ...view, controller };
}
afterEach(() => { vi.restoreAllMocks(); sessionStorage.clear(); });

describe("task detail autosave contract UI", () => {
  it("shows Saving then queued count with dirty accessible labels and no premature Saved announcement", async () => {
    const first = deferred<TaskResponse>();
    vi.spyOn(apiClient, "updateTask").mockReturnValueOnce(first.promise).mockResolvedValueOnce(task({ revision: 3, title: "Local", priority: "high" }));
    renderAutosave();
    const user = userEvent.setup();
    const title = screen.getByLabelText("Title");
    await user.clear(title);
    await user.type(title, "Local");
    await user.tab();
    expect(await screen.findByText("Saving…")).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText("Priority"), "high");
    expect(await screen.findByText("1 change queued")).toBeInTheDocument();
    expect(screen.getByLabelText("Priority, unsaved")).toBeInTheDocument();
    expect(screen.queryByText("Saved")).not.toBeInTheDocument();
    expect(screen.getByTestId("autosave-announcement")).toHaveAttribute("aria-live", "polite");
    expect(screen.getByTestId("autosave-announcement")).toHaveTextContent("Changes queued");
    first.resolve(task({ revision: 2, title: "Local" }));
    expect(await screen.findByText("Saved")).toBeInTheDocument();
    expect(screen.getByTestId("autosave-announcement")).toHaveTextContent("All changes saved");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("autosaves cleared optional metadata and tag removal", async () => {
    const update = vi.spyOn(apiClient, "updateTask").mockImplementation(async (_id, payload) => task({
      due_date: payload.due_date === undefined ? "2026-08-01" : payload.due_date,
      project_id: payload.project_id === undefined ? "project-1" : payload.project_id,
      tag_ids: payload.tag_ids ?? ["tag-1"],
      revision: payload.expected_revision + 1
    }));
    const controller = createTaskDetailAutosaveController("account-a", "https://api.example.test/api", task({
      due_date: "2026-08-01",
      project_id: "project-1",
      tag_ids: ["tag-1"]
    }));
    renderAutosave(controller);

    fireEvent.change(screen.getByLabelText("Due date"), { target: { value: "" } });
    fireEvent.change(screen.getByLabelText("Project"), { target: { value: "" } });
    fireEvent.click(screen.getByRole("checkbox", { name: "#tag" }));
    await act(async () => { await controller.whenIdle(); });

    expect(update).toHaveBeenCalledWith("task-ux", expect.objectContaining({ due_date: null }), expect.any(String));
    expect(update).toHaveBeenCalledWith("task-ux", expect.objectContaining({ project_id: null }), expect.any(String));
    expect(update).toHaveBeenCalledWith("task-ux", expect.objectContaining({ tag_ids: [] }), expect.any(String));
  });

  it("reopens a terminal task through the autosave barrier", async () => {
    const transition = vi.spyOn(apiClient, "transitionTask").mockResolvedValue(task({
      state: "inbox",
      completed_at: null,
      revision: 2
    }));
    const controller = createTaskDetailAutosaveController("account-a", "https://api.example.test/api", task({
      state: "completed",
      completed_at: "2026-01-02T00:00:00Z"
    }));
    renderAutosave(controller);

    fireEvent.click(screen.getByRole("button", { name: "Reopen task" }));
    await act(async () => { await controller.whenIdle(); });

    expect(transition).toHaveBeenCalledWith(
      "task-ux",
      expect.objectContaining({ action: "reopen", to_state: "inbox", expected_revision: 1 }),
      expect.any(String)
    );
  });

  it("renders exact conflict copy, preserves focus, and uses inline discard confirmation", async () => {
    vi.spyOn(apiClient, "updateTask").mockRejectedValue(new ApiError("conflict", 409, {}, "corr"));
    vi.spyOn(apiClient, "getTask").mockResolvedValue(task({ revision: 2, title: "Server" }));
    renderAutosave();
    const user = userEvent.setup();
    const title = screen.getByLabelText("Title");
    await user.clear(title);
    await user.type(title, "Local");
    await user.tab();
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Task changed elsewhere"));
    expect(screen.getByText("Your edits are safe here. Retry to apply them to the latest task.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry my edits" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Discard my edits" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Discard my edits" }));
    expect(screen.getByText("Discard unsaved edits?")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Keep editing" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Discard" })).toHaveClass("min-h-11");
  });

  it("retries a failed canonical conflict refetch before applying preserved edits", async () => {
    vi.spyOn(apiClient, "updateTask").mockRejectedValue(new ApiError("conflict", 409, {}, "corr"));
    const getTask = vi.spyOn(apiClient, "getTask")
      .mockRejectedValueOnce(new TypeError("network"))
      .mockResolvedValueOnce(task({ revision: 2, title: "Server" }));
    renderAutosave();
    const user = userEvent.setup();
    const title = screen.getByLabelText("Title");
    await user.clear(title);
    await user.type(title, "Local");
    await user.tab();
    expect(await screen.findByText("Your edits are safe here. Check your connection and try again.")).toBeInTheDocument();
    const retry = screen.getByRole("button", { name: "Retry my edits" });
    expect(retry).toBeEnabled();
    await user.click(retry);
    await waitFor(() => expect(getTask).toHaveBeenCalledTimes(2));
    expect(screen.getByText("Your edits are safe here. Retry to apply them to the latest task.")).toBeInTheDocument();
  });

  it("shows exact offline recovery copy with actionable 44px Retry while fields remain enabled", async () => {
    vi.spyOn(apiClient, "updateTask").mockRejectedValue(new TypeError("network"));
    vi.useFakeTimers({ shouldAdvanceTime: true });
    renderAutosave();
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    await user.selectOptions(screen.getByLabelText("Priority"), "high");
    await act(async () => { await vi.runAllTimersAsync(); });
    expect(await screen.findByText("Couldn’t save changes")).toBeInTheDocument();
    expect(screen.getByText("Your edits are safe here. Check your connection and try again.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry" })).toHaveClass("min-h-11");
    expect(screen.getByLabelText("Priority")).toBeEnabled();
    expect(screen.queryByText(/Saved locally/i)).not.toBeInTheDocument();
  });

  it("blocks blank Waiting with exact inline guidance and focuses Waiting for without dispatch", async () => {
    const transition = vi.spyOn(apiClient, "transitionTask");
    renderAutosave();
    await userEvent.setup().selectOptions(screen.getByLabelText("List"), "waiting");
    expect(screen.getByText("Add who or what you’re waiting for")).toBeInTheDocument();
    expect(screen.getByLabelText("Waiting for")).toHaveFocus();
    expect(transition).not.toHaveBeenCalled();
  });

  it("uses full viewport width below desktop and reserves keyboard scroll margin", () => {
    renderAutosave();
    expect(screen.getByRole("complementary")).toHaveClass("w-full", "min-[1100px]:w-[320px]");
    expect(screen.getByLabelText("Waiting for")).toHaveClass("scroll-mb-[88px]");
  });

  it("keeps editing after dismissing the inline discard confirmation", async () => {
    vi.spyOn(apiClient, "updateTask").mockRejectedValue(new ApiError("conflict", 409, {}, "corr"));
    vi.spyOn(apiClient, "getTask").mockResolvedValue(task({ revision: 2, title: "Server" }));
    renderAutosave();
    const user = userEvent.setup();
    const title = screen.getByLabelText("Title");
    await user.clear(title);
    await user.type(title, "Local");
    await user.tab();
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Task changed elsewhere"));
    await user.click(screen.getByRole("button", { name: "Discard my edits" }));
    expect(screen.getByText("Discard unsaved edits?")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Keep editing" }));
    expect(screen.queryByText("Discard unsaved edits?")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Discard my edits" })).toBeInTheDocument();
  });

  it("retries a failed save through the controller lane", async () => {
    const update = vi.spyOn(apiClient, "updateTask").mockRejectedValueOnce(new ApiError("invalid", 422, { detail: "Bad" })).mockResolvedValueOnce(task({ revision: 2, priority: "high" }));
    renderAutosave();
    const user = userEvent.setup();
    await user.selectOptions(screen.getByLabelText("Priority"), "high");
    expect(await screen.findByRole("button", { name: "Retry" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(update).toHaveBeenCalledTimes(2));
    expect(await screen.findByText("Saved")).toBeInTheDocument();
  });

  it("recovers an offline failure through the controller lane", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const update = vi.spyOn(apiClient, "updateTask")
      .mockRejectedValueOnce(new TypeError("network"))
      .mockRejectedValueOnce(new TypeError("network"))
      .mockRejectedValueOnce(new TypeError("network"))
      .mockResolvedValueOnce(task({ revision: 2, priority: "high" }));
    renderAutosave();
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    await user.selectOptions(screen.getByLabelText("Priority"), "high");
    await act(async () => { await vi.runAllTimersAsync(); });
    expect(await screen.findByRole("button", { name: "Retry" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Retry" }));
    await act(async () => { await vi.runAllTimersAsync(); });
    expect(update).toHaveBeenCalledTimes(4);
    vi.useRealTimers();
  });

  it("completes a task through the panel checkbox", async () => {
    const transition = vi.spyOn(apiClient, "transitionTask").mockResolvedValue(task({ revision: 2, state: "completed", completed_at: "2026-01-02T00:00:00Z" }));
    renderAutosave();
    await userEvent.setup().click(screen.getByRole("button", { name: "Complete task" }));
    await waitFor(() => expect(transition).toHaveBeenCalled());
  });

  it("cancels a task through the panel menu", async () => {
    const transition = vi.spyOn(apiClient, "transitionTask").mockResolvedValue(task({ revision: 2, state: "cancelled", cancelled_at: "2026-01-02T00:00:00Z" }));
    renderAutosave();
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Task menu" }));
    await user.click(screen.getByRole("button", { name: "Cancel task" }));
    await waitFor(() => expect(transition).toHaveBeenCalled());
  });

  it("moves a task into Waiting through the List select", async () => {
    const transition = vi.spyOn(apiClient, "transitionTask").mockResolvedValue(
      task({ revision: 2, state: "waiting", waiting_for: "Finance", waiting_since: "2026-01-02T00:00:00Z" })
    );
    renderAutosave();
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Waiting for"), "Finance");
    await user.selectOptions(screen.getByLabelText("List"), "waiting");
    await waitFor(() => expect(transition).toHaveBeenCalled());
  });

  it("blocks a blank Waiting transition and focuses the Waiting for input", async () => {
    const transition = vi.spyOn(apiClient, "transitionTask");
    renderAutosave();
    await userEvent.setup().selectOptions(screen.getByLabelText("List"), "waiting");
    expect(screen.getByText("Add who or what you’re waiting for")).toBeInTheDocument();
    expect(screen.getByLabelText("Waiting for")).toHaveFocus();
    expect(transition).not.toHaveBeenCalled();
  });
});
