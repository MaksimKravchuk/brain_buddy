/**
 * The running review holds Next, Skip step, Leave and the browser Back while a
 * write of the showing step is in flight (FR-048): the real shell with the real
 * Inbox and Decisions steps, and only the network mocked.
 */
import { onlineManager, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, apiClient } from "../../../api/client";
import { reviewApi, type DecisionResponse, type ReviewQueue, type ReviewSession } from "../../../api/review";
import type { TaskResponse } from "../../../api/taskTypes";
import { ShellToastContext } from "../../../components/shell/shellToast";
import { ReviewShell } from "../ReviewShell";
import { askingTask, iso, lastToast, notify, sessionFixture, signIn, stateFixture, taskFixture } from "./reviewKit";

vi.mock("../../../api/review", async () => {
  const actual = await vi.importActual<typeof import("../../../api/review")>("../../../api/review");
  return { ...actual, reviewApi: { ...actual.reviewApi, getQueue: vi.fn(), decide: vi.fn(), undoDecision: vi.fn(), progress: vi.fn(), bulkRelease: vi.fn(), undoBulkRelease: vi.fn() } };
});
vi.mock("../../../api/client", async () => {
  const actual = await vi.importActual<typeof import("../../../api/client")>("../../../api/client");
  return { ...actual, apiClient: { ...actual.apiClient, transitionTask: vi.fn(), updateTask: vi.fn(), getTask: vi.fn(), listProjects: vi.fn() } };
});

const getQueue = vi.mocked(reviewApi.getQueue);
const decide = vi.mocked(reviewApi.decide);
const undoDecision = vi.mocked(reviewApi.undoDecision);
const progress = vi.mocked(reviewApi.progress);
const transitionTask = vi.mocked(apiClient.transitionTask);

function deferred<T>() {
  let resolve: (value: T) => void = () => undefined;
  let reject: (error: unknown) => void = () => undefined;
  const promise = new Promise<T>((done, fail) => {
    resolve = done;
    reject = fail;
  });
  return { promise, resolve, reject };
}

const bathroom = askingTask("task_bath", "Renovate the bathroom");
const cv = askingTask("task_cv", "Update the CV");
const paper: TaskResponse = taskFixture({ id: "inbox_1", title: "Buy printer paper", state: "inbox", revision: 3 });
const dentist: TaskResponse = taskFixture({ id: "inbox_2", title: "Call the dentist", state: "inbox", revision: 3 });
const queue = (items: TaskResponse[]): ReviewQueue => ({ items, meta: {} });

function released(task: TaskResponse): DecisionResponse {
  return {
    decision: { id: `decision_${task.id}`, type: "someday", task_id: task.id, session_id: "review_1", decided_at: iso(0), substantive: null, stall_reason: null, ai_use: "none", yielded_auto_park: false },
    task: { ...task, revision: task.revision + 1, state: "someday", formulation: null },
    created_task: null,
    receipt: null,
    session_counts: null
  };
}

function renderShell(session: ReviewSession) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ShellToastContext.Provider value={notify}>
        <MemoryRouter>
          <ReviewShell initial={session} state={stateFixture()} onExit={vi.fn()} />
        </MemoryRouter>
      </ShellToastContext.Provider>
    </QueryClientProvider>
  );
}

const next = () => screen.getByRole("button", { name: "Next" });
const skip = () => screen.getByRole("button", { name: "Skip step" });
const leave = () => screen.getByRole("button", { name: "Leave" });
const held = () => [next(), skip(), leave()];
const expectHeld = () => held().forEach((button) => expect(button).toBeDisabled());
const expectFree = () => held().forEach((button) => expect(button).toBeEnabled());
const inDecisions = () => sessionFixture({ current_step: "decisions" });
const inInbox = () => sessionFixture({ current_step: "inbox" });

beforeEach(() => {
  window.localStorage.clear();
  signIn();
  vi.mocked(apiClient.listProjects).mockResolvedValue([]);
});

afterEach(() => {
  cleanup();
  onlineManager.setOnline(true);
  vi.restoreAllMocks();
  for (const mock of [getQueue, decide, undoDecision, progress, transitionTask, vi.mocked(reviewApi.bulkRelease), vi.mocked(reviewApi.undoBulkRelease)]) {
    mock.mockReset();
  }
  notify.mockReset();
  window.localStorage.clear();
});

describe("020-FR-048 the shell waits for the step's writes", () => {
  it("020-FR-048 Next, Skip step and Leave stay disabled while a decision saves, and come back when it lands", async () => {
    const user = userEvent.setup();
    getQueue.mockResolvedValue(queue([bathroom, cv]));
    const saving = deferred<DecisionResponse>();
    decide.mockReturnValueOnce(saving.promise);
    renderShell(inDecisions());
    await screen.findByRole("region", { name: "Renovate the bathroom" });
    expectFree();

    await user.click(within(screen.getByRole("group", { name: "Decisions" })).getByRole("button", { name: /^Release to Someday/ }));

    expectHeld();
    await act(async () => saving.resolve(released(bathroom)));
    expect(await screen.findByRole("region", { name: "Update the CV" })).toBeInTheDocument();
    expectFree();
  });

  it("020-FR-048 a decision that fails frees the bar again with its error and Retry still on the card", async () => {
    const user = userEvent.setup();
    getQueue.mockResolvedValue(queue([bathroom, cv]));
    decide.mockRejectedValueOnce(new ApiError("down", 503, null, "corr_decide"));
    renderShell(inDecisions());
    await screen.findByRole("region", { name: "Renovate the bathroom" });

    await user.click(within(screen.getByRole("group", { name: "Decisions" })).getByRole("button", { name: /^Release to Someday/ }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Ref corr_decide");
    expect(within(alert).getByRole("button", { name: "Retry" })).toBeEnabled();
    expectFree();
    expect(screen.getByRole("region", { name: "Renovate the bathroom" })).toBeInTheDocument();
  });

  it("020-FR-048 a Retry holds the bar again until it settles", async () => {
    const user = userEvent.setup();
    getQueue.mockResolvedValue(queue([bathroom, cv]));
    decide.mockRejectedValueOnce(new ApiError("down", 503, null, "corr_retry"));
    const again = deferred<DecisionResponse>();
    decide.mockReturnValueOnce(again.promise);
    renderShell(inDecisions());
    await screen.findByRole("region", { name: "Renovate the bathroom" });
    await user.click(within(screen.getByRole("group", { name: "Decisions" })).getByRole("button", { name: /^Release to Someday/ }));
    await user.click(within(await screen.findByRole("alert")).getByRole("button", { name: "Retry" }));

    expectHeld();
    await act(async () => again.resolve(released(bathroom)));
    await screen.findByRole("region", { name: "Update the CV" });
    expectFree();
  });

  it("020-FR-048 Not now holds the bar while its progress change saves, and a failure frees it", async () => {
    const user = userEvent.setup();
    getQueue.mockResolvedValue(queue([bathroom, cv]));
    const saving = deferred<ReviewSession>();
    progress.mockReturnValueOnce(saving.promise);
    renderShell(inDecisions());
    await screen.findByRole("region", { name: "Renovate the bathroom" });

    await user.click(screen.getByRole("button", { name: "Not now" }));
    expectHeld();
    await act(async () => saving.reject(new ApiError("down", 503, null, "corr_not_now")));

    expect(await screen.findByText(/Ref corr_not_now/)).toBeInTheDocument();
    expectFree();
    expect(screen.getByRole("region", { name: "Renovate the bathroom" })).toBeInTheDocument();
  });

  it("020-FR-048 the Inbox holds the bar for the move and then for the processed count", async () => {
    const user = userEvent.setup();
    getQueue.mockResolvedValue(queue([paper, dentist]));
    const moving = deferred<TaskResponse>();
    transitionTask.mockReturnValueOnce(moving.promise);
    const counting = deferred<ReviewSession>();
    progress.mockReturnValueOnce(counting.promise);
    renderShell(inInbox());
    await screen.findByRole("heading", { name: "Buy printer paper" });

    await user.click(within(screen.getByRole("group", { name: "Choices" })).getByRole("button", { name: "Next actions" }));
    expectHeld();
    await act(async () => moving.resolve({ ...paper, state: "next", revision: 4 }));
    await screen.findByRole("heading", { name: "Call the dentist" });
    // The item is processed, but the count is still on its way: still held.
    expectHeld();
    await act(async () => counting.resolve(sessionFixture({ current_step: "inbox", counts: { ...sessionFixture().counts, inbox_processed: 1 } })));

    await waitFor(() => expectFree());
    expect(progress.mock.calls[0][0].body).toMatchObject({ inbox_processed_delta: 1 });
  });

  it("020-FR-048 a count that fails frees the bar and leaves its Retry on the step", async () => {
    const user = userEvent.setup();
    getQueue.mockResolvedValue(queue([paper, dentist]));
    transitionTask.mockResolvedValueOnce({ ...paper, state: "next", revision: 4 });
    progress.mockRejectedValueOnce(new ApiError("down", 503, null, "corr_count"));
    renderShell(inInbox());
    await screen.findByRole("heading", { name: "Buy printer paper" });

    await user.click(within(screen.getByRole("group", { name: "Choices" })).getByRole("button", { name: "Next actions" }));

    expect(await screen.findByText(/Ref corr_count/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry" })).toBeEnabled();
    expectFree();
  });

  it("020-FR-048 Undo holds the bar from the moment it is pressed, even after the card is gone", async () => {
    const user = userEvent.setup();
    getQueue.mockResolvedValue(queue([bathroom, cv]));
    decide.mockResolvedValueOnce(released(bathroom));
    renderShell(inDecisions());
    await screen.findByRole("region", { name: "Renovate the bathroom" });
    await user.click(within(screen.getByRole("group", { name: "Decisions" })).getByRole("button", { name: /^Release to Someday/ }));
    await screen.findByRole("region", { name: "Update the CV" });
    expectFree();
    const undoing = deferred<Awaited<ReturnType<typeof reviewApi.undoDecision>>>();
    undoDecision.mockReturnValueOnce(undoing.promise);

    act(() => void lastToast()[1]?.action?.onAction());

    expectHeld();
    await act(async () => undoing.resolve({ task: { ...bathroom, revision: 9 }, undone_decision_id: "decision_task_bath", deleted_task_id: null, session_counts: null }));
    expect(await screen.findByRole("region", { name: "Renovate the bathroom" })).toBeInTheDocument();
    expectFree();
  });

  it("020-FR-048 an Undo that fails frees the bar again", async () => {
    const user = userEvent.setup();
    getQueue.mockResolvedValue(queue([bathroom, cv]));
    decide.mockResolvedValueOnce(released(bathroom));
    renderShell(inDecisions());
    await screen.findByRole("region", { name: "Renovate the bathroom" });
    await user.click(within(screen.getByRole("group", { name: "Decisions" })).getByRole("button", { name: /^Release to Someday/ }));
    await screen.findByRole("region", { name: "Update the CV" });
    undoDecision.mockRejectedValueOnce(new ApiError("down", 503, null, "corr_undo"));

    await act(async () => lastToast()[1]?.action?.onAction());

    await waitFor(() => expectFree());
    expect(lastToast()[0]).toContain("Couldn't undo");
  });

  it("020-FR-048 browser Back while a write saves stays on the step; once it settles, Back asks as before", async () => {
    const user = userEvent.setup();
    getQueue.mockResolvedValue(queue([bathroom, cv]));
    const saving = deferred<DecisionResponse>();
    decide.mockReturnValueOnce(saving.promise);
    renderShell(inDecisions());
    await screen.findByRole("region", { name: "Renovate the bathroom" });
    await user.click(within(screen.getByRole("group", { name: "Decisions" })).getByRole("button", { name: /^Release to Someday/ }));

    act(() => window.history.back());
    await waitFor(() => expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument());
    expect(screen.getByRole("navigation", { name: "Review steps" })).toBeInTheDocument();
    await act(async () => saving.resolve(released(bathroom)));
    await screen.findByRole("region", { name: "Update the CV" });

    act(() => window.history.back());
    expect(await screen.findByRole("alertdialog", { name: "Take a break?" })).toBeInTheDocument();
  });

  it("020-FR-048 while the bar's own Skip step saves, browser Back stays put and a tab close is warned", async () => {
    const user = userEvent.setup();
    getQueue.mockResolvedValue(queue([bathroom, cv]));
    const skipping = deferred<ReviewSession>();
    progress.mockReturnValueOnce(skipping.promise);
    renderShell(inDecisions());
    await screen.findByRole("region", { name: "Renovate the bathroom" });

    await user.click(skip());
    expect(progress.mock.calls[0][0].body).toMatchObject({ step: { code: "decisions", status: "skipped" } });
    act(() => window.history.back());
    await waitFor(() => expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument());
    const unload = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(unload);
    expect(unload.defaultPrevented).toBe(true);

    await act(async () => skipping.resolve(sessionFixture({ current_step: "decisions" })));
    await waitFor(() => expect(leave()).toBeEnabled());
    act(() => window.history.back());
    expect(await screen.findByRole("alertdialog", { name: "Take a break?" })).toBeInTheDocument();
  });

  it("020-FR-048 closing the tab while a write saves gets the browser's leave warning", async () => {
    const user = userEvent.setup();
    getQueue.mockResolvedValue(queue([bathroom, cv]));
    const saving = deferred<DecisionResponse>();
    decide.mockReturnValueOnce(saving.promise);
    renderShell(inDecisions());
    await screen.findByRole("region", { name: "Renovate the bathroom" });
    const quiet = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(quiet);
    expect(quiet.defaultPrevented).toBe(false);

    await user.click(within(screen.getByRole("group", { name: "Decisions" })).getByRole("button", { name: /^Release to Someday/ }));
    const unload = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(unload);

    expect(unload.defaultPrevented).toBe(true);
    await act(async () => saving.resolve(released(bathroom)));
  });

  it("020-FR-048 Leave stays available offline, where a write fails and settles", async () => {
    getQueue.mockResolvedValue(queue([bathroom, cv]));
    renderShell(inDecisions());
    await screen.findByRole("region", { name: "Renovate the bathroom" });

    vi.spyOn(navigator, "onLine", "get").mockReturnValue(false);
    act(() => {
      window.dispatchEvent(new Event("offline"));
    });

    expect(leave()).toBeEnabled();
    expect(next()).toBeDisabled();
  });
});
