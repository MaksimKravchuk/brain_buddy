import { onlineManager } from "@tanstack/react-query";
import { act, cleanup, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, apiClient } from "../../../api/client";
import { reviewApi, type DecisionResponse, type QueueMeta, type ReviewQueue } from "../../../api/review";
import type { ProjectResponse, TaskResponse } from "../../../api/taskTypes";
import { DatesStep } from "../steps/DatesStep";
import type { ReviewRun } from "../steps/reviewRun";
import { MindSweepStep } from "../steps/MindSweepStep";
import { ProjectsStep } from "../steps/ProjectsStep";
import { RestOfNextStep } from "../steps/RestOfNextStep";
import { SomedayStep } from "../steps/SomedayStep";
import { SummaryStep } from "../steps/SummaryStep";
import { WaitingStep } from "../steps/WaitingStep";
import { WinsStep } from "../steps/WinsStep";
import { DAY, iso, lastToast, notify, renderInRun, sessionFixture, signIn, stateFixture, taskFixture, zeroCounts } from "./reviewKit";

vi.mock("../../../api/review", async () => {
  const actual = await vi.importActual<typeof import("../../../api/review")>("../../../api/review");
  return { ...actual, reviewApi: { ...actual.reviewApi, getQueue: vi.fn(), decide: vi.fn(), undoDecision: vi.fn() } };
});
vi.mock("../../../api/client", async () => {
  const actual = await vi.importActual<typeof import("../../../api/client")>("../../../api/client");
  return { ...actual, apiClient: { ...actual.apiClient, createTask: vi.fn(), listProjects: vi.fn(), getTask: vi.fn() } };
});

const getQueue = vi.mocked(reviewApi.getQueue);
const decide = vi.mocked(reviewApi.decide);
const undoDecision = vi.mocked(reviewApi.undoDecision);
const createTask = vi.mocked(apiClient.createTask);
const listProjects = vi.mocked(apiClient.listProjects);

const queue = (items: TaskResponse[], meta: QueueMeta = {}): ReviewQueue => ({ items, meta });

beforeEach(() => {
  window.localStorage.clear();
  signIn();
  listProjects.mockResolvedValue([]);
});

afterEach(() => {
  cleanup();
  onlineManager.setOnline(true);
  vi.restoreAllMocks();
  getQueue.mockReset();
  decide.mockReset();
  undoDecision.mockReset();
  createTask.mockReset();
  listProjects.mockReset();
  notify.mockReset();
  window.localStorage.clear();
});

describe("020-FR-028 a step's queue loads before it shows", () => {
  it("020-FR-028 shows a placeholder while the step loads and the step's content once it has", async () => {
    let resolve: (value: ReviewQueue) => void = () => undefined;
    getQueue.mockReturnValueOnce(new Promise((done) => { resolve = done; }));
    renderInRun(<WinsStep />);

    expect(screen.getByRole("status", { name: "Loading this step" })).toHaveAttribute("aria-busy", "true");
    await act(async () => resolve(queue([], { count: 0 })));

    await waitFor(() => expect(screen.queryByRole("status", { name: "Loading this step" })).not.toBeInTheDocument());
    expect(screen.getByText(/A quiet week/)).toBeInTheDocument();
    expect(getQueue).toHaveBeenCalledWith("wins", "review_1", expect.anything());
  });

  it("020-FR-045 a failed load keeps the progress safe, shows the Ref, retries, and can skip the step", async () => {
    const user = userEvent.setup();
    getQueue.mockRejectedValueOnce(new ApiError("Review request failed", 503, null, "corr_step_load"));
    getQueue.mockResolvedValueOnce(queue([], { count: 0 }));
    const { run } = renderInRun(<WinsStep />);

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("We couldn't load this step. Your progress is safe.");
    expect(alert).toHaveTextContent("Ref corr_step_load");
    await user.click(within(alert).getByRole("button", { name: "Skip step" }));
    expect(run.skipStep).toHaveBeenCalledTimes(1);

    await user.click(within(alert).getByRole("button", { name: "Retry" }));
    expect(await screen.findByText(/A quiet week/)).toBeInTheDocument();
    expect(getQueue).toHaveBeenCalledTimes(2);
  });
});

describe("020-FR-028 Wins of the week", () => {
  it("020-FR-028 counts what was finished and lists it", async () => {
    getQueue.mockResolvedValueOnce(queue([taskFixture({ id: "w1", title: "Measure the bathroom wall", state: "completed" }), taskFixture({ id: "w2", title: "Send the invoice", state: "completed" })], { count: 12 }));
    renderInRun(<WinsStep />);

    expect(await screen.findByText("This week you finished 12 things")).toBeInTheDocument();
    expect(screen.getByText("Measure the bathroom wall")).toBeInTheDocument();
    expect(screen.getByText("Send the invoice")).toBeInTheDocument();
  });

  it("020-FR-028 says one thing in the singular", async () => {
    getQueue.mockResolvedValueOnce(queue([taskFixture({ id: "w1", title: "Send the invoice", state: "completed" })], { count: 1 }));
    renderInRun(<WinsStep />);

    expect(await screen.findByText("This week you finished 1 thing")).toBeInTheDocument();
  });

  it("020-FR-028 a quiet week gets a kind line and no zero", async () => {
    getQueue.mockResolvedValueOnce(queue([], { count: 0 }));
    const { container } = renderInRun(<WinsStep />);

    expect(await screen.findByText("A quiet week… Taking a few minutes now is how next week gets easier.")).toBeInTheDocument();
    expect(container.textContent).not.toMatch(/\b0\b/);
  });
});

describe("020-FR-052 Mind sweep", () => {
  it("020-FR-028 adds each line to the Inbox, lists it and clears the field", async () => {
    const user = userEvent.setup();
    createTask.mockResolvedValueOnce(taskFixture({ id: "t_call", title: "Call the plumber" }));
    const { run } = renderInRun(<MindSweepStep />);

    expect(screen.getByText("What's on your mind? Get it out of your head. Don't sort it yet.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add to Inbox" })).toBeDisabled();
    await user.type(screen.getByRole("textbox", { name: "What's on your mind?" }), "Call the plumber");
    expect(run.setUnsaved).toHaveBeenLastCalledWith(true);
    await user.click(screen.getByRole("button", { name: "Add to Inbox" }));

    expect(createTask).toHaveBeenCalledWith({ title: "Call the plumber", state: "inbox" }, expect.any(String));
    expect(await screen.findByRole("listitem")).toHaveTextContent("Call the plumber");
    expect(screen.getByRole("textbox", { name: "What's on your mind?" })).toHaveValue("");
    expect(run.setUnsaved).toHaveBeenLastCalledWith(false);
  });

  it("020-FR-052 a failed add keeps the typed line, shows the Ref and retries under the same key", async () => {
    const user = userEvent.setup();
    createTask.mockRejectedValueOnce(new ApiError("down", 503, null, "corr_add"));
    createTask.mockResolvedValueOnce(taskFixture({ id: "t_call", title: "Call the plumber" }));
    renderInRun(<MindSweepStep />);

    await user.type(screen.getByRole("textbox", { name: "What's on your mind?" }), "Call the plumber{Enter}");

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Couldn't save “Add to Inbox”. Nothing was changed.");
    expect(alert).toHaveTextContent("Ref corr_add");
    expect(screen.getByRole("textbox", { name: "What's on your mind?" })).toHaveValue("Call the plumber");
    await user.click(within(alert).getByRole("button", { name: "Retry" }));

    expect(await screen.findByRole("listitem")).toHaveTextContent("Call the plumber");
    expect(createTask.mock.calls[1][1]).toBe(createTask.mock.calls[0][1]);
  });

  it("020-FR-042 an add that fails after another account signed in leaves no failure to retry", async () => {
    const user = userEvent.setup();
    let fail: (error: unknown) => void = () => undefined;
    createTask.mockReturnValueOnce(new Promise((_done, reject) => { fail = reject; }));
    renderInRun(<MindSweepStep />);
    await user.type(screen.getByRole("textbox", { name: "What's on your mind?" }), "Call the plumber{Enter}");

    act(() => signIn("user-2"));
    await act(async () => fail(new ApiError("down", 503, null, "corr_other_account")));

    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    act(() => signIn("user-1"));
  });

  it("020-FR-040 adding is disabled while offline", async () => {
    const user = userEvent.setup();
    renderInRun(<MindSweepStep />);
    await user.type(screen.getByRole("textbox", { name: "What's on your mind?" }), "Call the plumber");

    vi.spyOn(navigator, "onLine", "get").mockReturnValue(false);
    act(() => { window.dispatchEvent(new Event("offline")); });

    expect(screen.getByRole("button", { name: "Add to Inbox" })).toBeDisabled();
  });
});

describe("020-FR-031 The rest of Next", () => {
  it("020-FR-031 shows the count, the pace and the weeks of work, and no limit", async () => {
    getQueue.mockResolvedValueOnce(queue([taskFixture({ id: "n1", title: "Plan the trip", state: "next" })], { next_count: 41, weekly_average_4w: 9, weeks_of_history: 9, implied_weeks: 4.555 }));
    renderInRun(<RestOfNextStep />);

    expect(await screen.findByText("41 next actions")).toBeInTheDocument();
    expect(screen.getByText("9 done per week, last 4 weeks")).toBeInTheDocument();
    expect(screen.getByText("~4½ weeks of work at that pace")).toBeInTheDocument();
    expect(screen.getByText(/No limit\. Just a mirror/)).toBeInTheDocument();
    expect(screen.getByText("Plan the trip")).toBeInTheDocument();
  });

  it.each([
    [3, "~3 weeks of work at that pace"],
    [0.2, "~½ week of work at that pace"],
    [1, "~1 week of work at that pace"]
  ])("020-FR-031 rounds %s weeks to the nearest half", async (implied, text) => {
    getQueue.mockResolvedValueOnce(queue([], { next_count: 5, weekly_average_4w: 2, weeks_of_history: 8, implied_weeks: implied }));
    renderInRun(<RestOfNextStep />);

    expect(await screen.findByText(text)).toBeInTheDocument();
  });

  it("020-FR-031 with under four weeks of history it shows only the count and says why", async () => {
    getQueue.mockResolvedValueOnce(queue([], { next_count: 12, weekly_average_4w: null, weeks_of_history: 2, implied_weeks: null }));
    renderInRun(<RestOfNextStep />);

    expect(await screen.findByText("12 next actions")).toBeInTheDocument();
    expect(screen.getByText("After a few weeks of finished tasks, this will also show your weekly pace and how many weeks of work Next holds.")).toBeInTheDocument();
    expect(screen.queryByText(/done per week/)).not.toBeInTheDocument();
  });

  it("020-FR-031 an empty Next says so", async () => {
    getQueue.mockResolvedValueOnce(queue([], { next_count: 0, weekly_average_4w: null, weeks_of_history: 0, implied_weeks: null }));
    renderInRun(<RestOfNextStep />);

    expect(await screen.findByText("Next is empty.")).toBeInTheDocument();
  });
});

describe("020-FR-028 Projects without a next action", () => {
  const projects: ProjectResponse[] = [
    { id: "p_flat", name: "Flat", color: null, state: "active", revision: 1, open_task_count: 2 },
    { id: "p_new", name: "New website", color: null, state: "active", revision: 1, open_task_count: 0 },
    { id: "p_busy", name: "Garden", color: null, state: "active", revision: 1, open_task_count: 3 },
    { id: "p_old", name: "Old flat", color: null, state: "archived", revision: 1, open_task_count: 0 }
  ];

  it("020-FR-028 lists active projects with no next action, including empty ones, and not archived or busy ones", async () => {
    listProjects.mockResolvedValue(projects);
    getQueue.mockResolvedValueOnce(queue([taskFixture({ id: "s1", state: "someday", project_id: "p_flat" }), taskFixture({ id: "s2", state: "waiting", project_id: "p_flat" })]));
    renderInRun(<ProjectsStep />);

    const list = await screen.findByRole("list", { name: "Projects without a next action" });
    expect(within(list).getAllByRole("listitem").map((item) => item.querySelector("p")?.textContent)).toEqual(["Flat", "New website"]);
    expect(screen.getByText("A project moves only when it has something you can do next.")).toBeInTheDocument();
  });

  it("020-FR-028 020-FR-052 adds a next action to a project, keeping unsaved text flagged until it is saved", async () => {
    const user = userEvent.setup();
    listProjects.mockResolvedValue(projects);
    getQueue.mockResolvedValueOnce(queue([]));
    createTask.mockResolvedValueOnce(taskFixture({ id: "t_new", title: "Draft the home page", state: "next", project_id: "p_new" }));
    const { run } = renderInRun(<ProjectsStep />);

    await user.click(await screen.findByRole("button", { name: "Add next action to New website" }));
    const field = screen.getByRole("textbox", { name: "Next action for New website" });
    expect(field).toHaveFocus();
    await user.type(field, "Draft the home page");
    expect(run.setUnsaved).toHaveBeenLastCalledWith(true);
    await user.click(screen.getByRole("button", { name: "Save next action" }));

    expect(createTask).toHaveBeenCalledWith({ title: "Draft the home page", state: "next", project_id: "p_new" }, expect.any(String));
    expect(await screen.findByText("Added to New website: Draft the home page")).toBeInTheDocument();
    expect(run.setUnsaved).toHaveBeenLastCalledWith(false);
    expect(screen.getByText("Every active project has a next action.")).toBeInTheDocument();
  });

  it("020-FR-045 a failed save keeps the text, names the Ref and retries under the same key; Cancel drops the field", async () => {
    const user = userEvent.setup();
    listProjects.mockResolvedValue(projects);
    getQueue.mockResolvedValueOnce(queue([]));
    createTask.mockRejectedValueOnce(new ApiError("down", 503, null, "corr_project"));
    createTask.mockResolvedValueOnce(taskFixture({ id: "t_new", title: "Draft", state: "next", project_id: "p_new" }));
    renderInRun(<ProjectsStep />);

    await user.click(await screen.findByRole("button", { name: "Add next action to New website" }));
    await user.type(screen.getByRole("textbox", { name: "Next action for New website" }), "Draft{Enter}");
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Ref corr_project");
    await user.click(within(alert).getByRole("button", { name: "Retry" }));
    expect(await screen.findByText("Added to New website: Draft")).toBeInTheDocument();
    expect(createTask.mock.calls[1][1]).toBe(createTask.mock.calls[0][1]);
  });

  it("020-FR-052 Cancel closes the open field and clears the unsaved flag", async () => {
    const user = userEvent.setup();
    listProjects.mockResolvedValue(projects);
    getQueue.mockResolvedValueOnce(queue([]));
    const { run } = renderInRun(<ProjectsStep />);

    await user.click(await screen.findByRole("button", { name: "Add next action to New website" }));
    await user.type(screen.getByRole("textbox", { name: "Next action for New website" }), "Draft");
    await user.click(screen.getByRole("button", { name: "Cancel" }));

    expect(screen.queryByRole("textbox", { name: "Next action for New website" })).not.toBeInTheDocument();
    expect(run.setUnsaved).toHaveBeenLastCalledWith(false);
  });

  it("020-FR-028 says every project has a next action when none is stuck", async () => {
    listProjects.mockResolvedValue([projects[2]]);
    getQueue.mockResolvedValueOnce(queue([]));
    renderInRun(<ProjectsStep />);

    expect(await screen.findByText("Every active project has a next action.")).toBeInTheDocument();
  });

  it("020-FR-045 projects that cannot be loaded fail the step the same way as its queue", async () => {
    listProjects.mockRejectedValue(new ApiError("down", 503, null, "corr_projects"));
    getQueue.mockResolvedValue(queue([]));
    renderInRun(<ProjectsStep />);

    expect(await screen.findByRole("alert")).toHaveTextContent("Ref corr_projects");
  });
});

describe("020-FR-028 The next 14 days", () => {
  it("020-FR-028 groups what is due by day with the list each task is in", async () => {
    getQueue.mockResolvedValueOnce(queue(
      [taskFixture({ id: "d1", title: "Send the invoice", state: "next" }), taskFixture({ id: "d2", title: "Call Sam back", state: "waiting" })],
      { days: [{ day: "2026-10-12", task_ids: ["d1"] }, { day: "2026-10-14", task_ids: ["d2"] }] }
    ));
    renderInRun(<DatesStep />);

    const first = await screen.findByRole("group", { name: "Mon 12 Oct" });
    expect(within(first).getByText("Send the invoice")).toBeInTheDocument();
    expect(within(first).getByText("Next actions")).toBeInTheDocument();
    const second = screen.getByRole("group", { name: "Wed 14 Oct" });
    expect(within(second).getByText("Call Sam back")).toBeInTheDocument();
    expect(within(second).getByText("Waiting for")).toBeInTheDocument();
  });

  it("020-FR-028 a clear two weeks says so", async () => {
    getQueue.mockResolvedValueOnce(queue([], { days: [] }));
    renderInRun(<DatesStep />);

    expect(await screen.findByText("A clear two weeks")).toBeInTheDocument();
    expect(screen.getByText("Nothing has a due date in the next 14 days.")).toBeInTheDocument();
  });
});

describe("020-FR-033 Summary", () => {
  const counts = { ...zeroCounts, done: 3, reformulated: 2, first_step: 2, waiting: 1, someday: 4, cancelled: 1, inbox_processed: 10, kept: 3, moved_to_next: 2 };
  const finish = vi.fn<ReviewRun["finish"]>(async () => undefined);

  afterEach(() => finish.mockReset());

  it("020-FR-033 shows the ten counts in their fixed order, zero ones dimmed, and the next review", () => {
    renderInRun(<SummaryStep />, { finish, session: sessionFixture({ counts }), state: stateFixture({ next_review_at: "2026-10-16T14:00:00Z" }) });

    const list = screen.getByRole("list", { name: "Decisions in this review" });
    const items = within(list).getAllByRole("listitem");
    expect(items.map((item) => item.textContent)).toEqual([
      "Done3", "Reformulated2", "First step2", "Waiting for1", "Someday / maybe4",
      "Cancelled1", "Kept 7 more days0", "Inbox processed10", "Kept as is3", "Moved to Next2"
    ]);
    expect(items[6]).toHaveClass("text-slate-500");
    expect(items[0]).not.toHaveClass("text-slate-500");
    expect(list).toHaveClass("grid-cols-2", "md:grid-cols-4");
    expect(screen.getByText(/^Next review: Fri 16 Oct, \d{2}:\d{2}$/)).toBeInTheDocument();
  });

  it("020-FR-033 all zero counts become one calm line instead of a grid of zeros", () => {
    renderInRun(<SummaryStep />, { finish });

    expect(screen.getByText("Nothing needed changing this time.")).toBeInTheDocument();
    expect(screen.queryByRole("list", { name: "Decisions in this review" })).not.toBeInTheDocument();
  });

  it("020-FR-029 a review finished without any step shows the same calm screen, with no wording about not counting", () => {
    const skipped = sessionFixture({ steps: { wins: "skipped", mind_sweep: "skipped", inbox: "skipped", decisions: "skipped", rest_of_next: "skipped", waiting: "skipped", projects: "skipped", someday: "skipped", dates: "skipped", summary: "pending" } });
    const { container } = renderInRun(<SummaryStep />, { finish, session: skipped });

    expect(screen.getByText(/^Next review: /)).toBeInTheDocument();
    expect(screen.getByText("Clear how to start the week?")).toBeInTheDocument();
    expect(container.textContent).not.toMatch(/does(?:n['’]t| not) count|not counted|didn['’]t count|skipped (?:every|all)|nothing was reviewed|you missed/i);
  });

  it("020-FR-033 the optional question is answered with a neutral acknowledgement, and Done sends the answer", async () => {
    const user = userEvent.setup();
    renderInRun(<SummaryStep />, { finish, session: sessionFixture({ counts }) });

    const group = screen.getByRole("group", { name: /Clear how to start the week\?/ });
    expect(within(group).getByRole("button", { name: "Yes" })).toHaveAttribute("aria-pressed", "false");
    await user.click(within(group).getByRole("button", { name: "Not really" }));
    expect(within(group).getByRole("button", { name: "Not really" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText("Thanks. Noted for this review.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Yes" }));
    await user.click(screen.getByRole("button", { name: "Done" }));

    expect(finish).toHaveBeenCalledWith("yes", expect.any(String));
  });

  it("020-FR-033 Done without an answer sends none", async () => {
    const user = userEvent.setup();
    renderInRun(<SummaryStep />, { finish });

    await user.click(screen.getByRole("button", { name: "Done" }));

    expect(finish).toHaveBeenCalledWith(null, expect.any(String));
  });

  it("020-FR-045 a failed Done keeps the screen, shows the Ref and retries under the same key", async () => {
    const user = userEvent.setup();
    finish.mockRejectedValueOnce(new ApiError("down", 503, null, "corr_done"));
    renderInRun(<SummaryStep />, { finish });

    await user.click(screen.getByRole("button", { name: "Done" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Couldn't save “Done”. Nothing was changed.");
    expect(alert).toHaveTextContent("Ref corr_done");
    await user.click(within(alert).getByRole("button", { name: "Retry" }));

    await waitFor(() => expect(finish).toHaveBeenCalledTimes(2));
    expect(finish.mock.calls[1][1]).toBe(finish.mock.calls[0][1]);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});

describe("020-FR-032 Waiting for, older than 7 days", () => {
  const drill = taskFixture({ id: "wait_1", title: "Pick up the drill from Sam", state: "waiting", waiting_for: "Sam", waiting_since: iso(-15 * DAY), revision: 4 });
  const tiles = taskFixture({ id: "wait_2", title: "Quote for the bathroom tiles", state: "waiting", waiting_for: "the tile shop", waiting_since: iso(-20 * DAY), revision: 6 });

  function decided(task: TaskResponse, type: string, after: Partial<TaskResponse>, createdTask: TaskResponse | null = null): DecisionResponse {
    return {
      decision: { id: `decision_${task.id}`, type, task_id: task.id, session_id: "review_1", decided_at: iso(0), substantive: null, stall_reason: null, ai_use: "none", yielded_auto_park: false },
      task: { ...task, revision: task.revision + 1, ...after },
      created_task: createdTask,
      receipt: null,
      session_counts: null
    };
  }

  it("020-FR-032 shows one task at a time with who it waits on and four decisions that stack at 390 px", async () => {
    getQueue.mockResolvedValueOnce(queue([drill, tiles]));
    renderInRun(<WaitingStep />);

    expect(await screen.findByRole("heading", { name: "Pick up the drill from Sam" })).toBeInTheDocument();
    expect(screen.getByText("1 of 2 · Waiting for more than 7 days")).toBeInTheDocument();
    expect(screen.getByText(/^Waiting on: Sam · since .* \(15 days\)$/)).toBeInTheDocument();
    const group = screen.getByRole("group", { name: "Decisions" });
    expect(within(group).getAllByRole("button").map((button) => button.textContent)).toEqual([
      "Keep waitingChecks in again in 7 days", "Create a follow-up", "Return to Next", "Cancel task"
    ]);
    expect(group).toHaveClass("flex-col", "sm:flex-row");
  });

  it("020-FR-048 Keep waiting is one tap with an Undo, then the next task; Undo brings the first back", async () => {
    const user = userEvent.setup();
    getQueue.mockResolvedValueOnce(queue([drill, tiles]));
    decide.mockResolvedValueOnce(decided(drill, "keep_waiting", {}));
    undoDecision.mockResolvedValueOnce({ task: { ...drill, revision: 6 }, undone_decision_id: "decision_wait_1", deleted_task_id: null, session_counts: null });
    renderInRun(<WaitingStep />);

    await user.click(await screen.findByRole("button", { name: /^Keep waiting/ }));

    expect(decide).toHaveBeenCalledWith("wait_1", { type: "keep_waiting", expected_revision: 4, session_id: "review_1" }, expect.any(String));
    expect(await screen.findByRole("heading", { name: "Quote for the bathroom tiles" })).toHaveFocus();
    expect(lastToast()[0]).toBe("“Pick up the drill from Sam” kept waiting · checks in again in 7 days");
    expect(lastToast()[1]?.action?.accessibleLabel).toBe("Undo: Kept waiting Pick up the drill from Sam");

    await act(async () => lastToast()[1]?.action?.onAction());

    expect(undoDecision).toHaveBeenCalledWith("decision_wait_1", { expected_task_revision: 5 }, expect.any(String));
    expect(await screen.findByRole("heading", { name: "Pick up the drill from Sam" })).toBeInTheDocument();
    expect(screen.getByText("1 of 2 · Waiting for more than 7 days")).toBeInTheDocument();
  });

  it("020-FR-032 a follow-up needs a title, creates it with the decision and reports unsaved text", async () => {
    const user = userEvent.setup();
    getQueue.mockResolvedValueOnce(queue([drill]));
    decide.mockResolvedValueOnce(decided(drill, "follow_up", {}, taskFixture({ id: "task_fu", title: "Text Sam about the drill", state: "next" })));
    const { run } = renderInRun(<WaitingStep />);

    await user.click(await screen.findByRole("button", { name: "Create a follow-up" }));
    const field = screen.getByRole("textbox", { name: "What will you do to follow up?" });
    expect(field).toHaveFocus();
    expect(screen.getByRole("button", { name: "Save follow-up" })).toBeDisabled();
    await user.type(field, "Text Sam about the drill");
    expect(run.setUnsaved).toHaveBeenLastCalledWith(true);
    await user.click(screen.getByRole("button", { name: "Save follow-up" }));

    expect(decide).toHaveBeenCalledWith("wait_1", { type: "follow_up", expected_revision: 4, title: "Text Sam about the drill", session_id: "review_1" }, expect.any(String));
    await waitFor(() => expect(lastToast()[0]).toBe("Follow-up added: “Text Sam about the drill”"));
    expect(run.setUnsaved).toHaveBeenLastCalledWith(false);
    expect(await screen.findByText("All caught up.")).toBeInTheDocument();
  });

  it("020-FR-032 Return to Next prefills the title and Back drops the form", async () => {
    const user = userEvent.setup();
    getQueue.mockResolvedValueOnce(queue([drill]));
    decide.mockResolvedValueOnce(decided(drill, "return_to_next", { state: "next" }));
    renderInRun(<WaitingStep />);

    await user.click(await screen.findByRole("button", { name: "Return to Next" }));
    const field = screen.getByRole("textbox", { name: "What's the next action now?" });
    expect(field).toHaveValue("Pick up the drill from Sam");
    await user.click(screen.getByRole("button", { name: "Back" }));
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Return to Next" }));
    await user.clear(screen.getByRole("textbox", { name: "What's the next action now?" }));
    await user.type(screen.getByRole("textbox", { name: "What's the next action now?" }), "Fetch the drill from Sam");
    await user.click(screen.getByRole("button", { name: "Move to Next" }));

    expect(decide).toHaveBeenCalledWith("wait_1", { type: "return_to_next", expected_revision: 4, title: "Fetch the drill from Sam", session_id: "review_1" }, expect.any(String));
    await waitFor(() => expect(lastToast()[0]).toBe("“Pick up the drill from Sam” moved to Next actions"));
  });

  it("020-FR-032 Cancel task is one tap", async () => {
    const user = userEvent.setup();
    getQueue.mockResolvedValueOnce(queue([drill]));
    decide.mockResolvedValueOnce(decided(drill, "cancel", { state: "cancelled" }));
    renderInRun(<WaitingStep />);

    await user.click(await screen.findByRole("button", { name: "Cancel task" }));

    expect(decide).toHaveBeenCalledWith("wait_1", { type: "cancel", expected_revision: 4, session_id: "review_1" }, expect.any(String));
    await waitFor(() => expect(lastToast()[0]).toBe("“Pick up the drill from Sam” cancelled"));
  });

  it("020-FR-045 a failed decision keeps the task current, shows the Ref and retries under the same key", async () => {
    const user = userEvent.setup();
    getQueue.mockResolvedValueOnce(queue([drill]));
    decide.mockRejectedValueOnce(new ApiError("down", 503, null, "corr_keep"));
    decide.mockResolvedValueOnce(decided(drill, "keep_waiting", {}));
    renderInRun(<WaitingStep />);

    await user.click(await screen.findByRole("button", { name: /^Keep waiting/ }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Couldn't save “Keep waiting”. Nothing was changed.");
    expect(alert).toHaveTextContent("Ref corr_keep");
    expect(screen.getByRole("heading", { name: "Pick up the drill from Sam" })).toBeInTheDocument();
    await user.click(within(alert).getByRole("button", { name: "Retry" }));

    await waitFor(() => expect(screen.getByText("All caught up.")).toBeInTheDocument());
    expect(decide.mock.calls[1][2]).toBe(decide.mock.calls[0][2]);
  });

  it("020-FR-011 a task changed elsewhere is left as it is there, named, and the review moves on", async () => {
    const user = userEvent.setup();
    getQueue.mockResolvedValueOnce(queue([drill, tiles]));
    decide.mockRejectedValueOnce(new ApiError("Conflict", 409, { message: "stale", detail: { resource: "task", id: "wait_1" } }, "corr_stale"));
    renderInRun(<WaitingStep />);

    await user.click(await screen.findByRole("button", { name: /^Keep waiting/ }));

    expect(await screen.findByRole("heading", { name: "Quote for the bathroom tiles" })).toBeInTheDocument();
    expect(screen.getByRole("status", { name: "Changed elsewhere" })).toHaveTextContent("“Pick up the drill from Sam” changed on another device, so it was left as it is there.");
  });

  it("020-FR-011 when the last task changed elsewhere the step says so and that it is all caught up", async () => {
    const user = userEvent.setup();
    getQueue.mockResolvedValueOnce(queue([drill]));
    decide.mockRejectedValueOnce(new ApiError("Conflict", 409, { message: "stale", detail: { resource: "task", id: "wait_1" } }, "corr_stale_last"));
    renderInRun(<WaitingStep />);

    await user.click(await screen.findByRole("button", { name: /^Keep waiting/ }));

    expect(await screen.findByText("All caught up.")).toBeInTheDocument();
    expect(screen.getByRole("status", { name: "Changed elsewhere" })).toHaveTextContent("“Pick up the drill from Sam” changed on another device, so it was left as it is there.");
  });

  it("020-FR-032 an archived project blocks the follow-up with its reason", async () => {
    const user = userEvent.setup();
    getQueue.mockResolvedValueOnce(queue([drill]));
    decide.mockRejectedValueOnce(new ApiError("Bad", 400, { message: "x", detail: { reason: "project_archived" } }, "corr_arch"));
    renderInRun(<WaitingStep />);

    await user.click(await screen.findByRole("button", { name: "Create a follow-up" }));
    await user.type(screen.getByRole("textbox", { name: "What will you do to follow up?" }), "Text Sam{Enter}");

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Restore this archived project before creating a follow-up in it.");
    expect(alert).toHaveTextContent("Ref corr_arch");
    expect(within(alert).queryByRole("button", { name: "Retry" })).not.toBeInTheDocument();
  });

  it("020-FR-048 an Undo the server refuses says so with the Ref and the card stays gone", async () => {
    const user = userEvent.setup();
    getQueue.mockResolvedValueOnce(queue([drill, tiles]));
    decide.mockResolvedValueOnce(decided(drill, "keep_waiting", {}));
    undoDecision.mockRejectedValueOnce(new ApiError("Conflict", 409, { message: "x", detail: { reason: "undo_unavailable" } }, "corr_undo"));
    vi.mocked(apiClient.getTask).mockResolvedValueOnce({ ...drill, state: "someday" });
    renderInRun(<WaitingStep />);

    await user.click(await screen.findByRole("button", { name: /^Keep waiting/ }));
    await screen.findByRole("heading", { name: "Quote for the bathroom tiles" });
    await act(async () => lastToast()[1]?.action?.onAction());

    expect(lastToast()[0]).toBe("Couldn't undo: “Pick up the drill from Sam” changed on another device. It's in Someday / maybe now. Ref corr_undo");
    expect(screen.getByRole("heading", { name: "Quote for the bathroom tiles" })).toBeInTheDocument();
  });

  it("020-FR-032 nothing to chase says so", async () => {
    getQueue.mockResolvedValueOnce(queue([]));
    renderInRun(<WaitingStep />);

    expect(await screen.findByText("Nothing to chase")).toBeInTheDocument();
  });
});

describe("020-FR-032 Someday / maybe", () => {
  const raised = taskFixture({ id: "sd_1", title: "Build a raised bed", state: "someday", revision: 5 });
  const parked = taskFixture({ id: "sd_2", title: "Learn basic Portuguese", state: "someday", revision: 9, parked: { at: "2026-08-20T09:00:00Z", formulation_id: "form_pt" } });

  function decided(task: TaskResponse, type: string, after: Partial<TaskResponse>): DecisionResponse {
    return {
      decision: { id: `decision_${task.id}`, type, task_id: task.id, session_id: "review_1", decided_at: iso(0), substantive: null, stall_reason: null, ai_use: "none", yielded_auto_park: false },
      task: { ...task, revision: task.revision + 1, ...after },
      created_task: null,
      receipt: null,
      session_counts: null
    };
  }

  it("020-FR-032 shows one of at most seven tasks, says an auto-parked one was parked automatically, and offers three decisions", async () => {
    getQueue.mockResolvedValueOnce(queue([raised, parked], { eligible_total: 9, shown: 2 }));
    renderInRun(<SomedayStep />);

    expect(await screen.findByRole("heading", { name: "Build a raised bed" })).toBeInTheDocument();
    expect(screen.getByText("1 of 2 · Someday / maybe, not looked at lately")).toBeInTheDocument();
    expect(within(screen.getByRole("group", { name: "Decisions" })).getAllByRole("button").map((button) => button.textContent)).toEqual([
      "Keep in SomedayLooks again in 30 days", "Move to Next", "Cancel task"
    ]);
    expect(screen.queryByText(/Parked automatically/)).not.toBeInTheDocument();
  });

  it("020-FR-032 keeping a task reports it with its 30 days, and the next one says it was parked automatically", async () => {
    const user = userEvent.setup();
    getQueue.mockResolvedValueOnce(queue([raised, parked], { eligible_total: 2, shown: 2 }));
    decide.mockResolvedValueOnce(decided(raised, "keep_someday", {}));
    renderInRun(<SomedayStep />);

    await user.click(await screen.findByRole("button", { name: /^Keep in Someday/ }));

    expect(decide).toHaveBeenCalledWith("sd_1", { type: "keep_someday", expected_revision: 5, session_id: "review_1" }, expect.any(String));
    expect(await screen.findByText("Parked automatically on Thu 20 Aug")).toBeInTheDocument();
    expect(lastToast()[0]).toBe("“Build a raised bed” kept in Someday · looks again in 30 days");
    expect(lastToast()[1]?.action?.accessibleLabel).toBe("Undo: Kept in Someday Build a raised bed");
  });

  it("020-FR-032 Move to Next asks for a concrete first action and saves it", async () => {
    const user = userEvent.setup();
    getQueue.mockResolvedValueOnce(queue([raised], { eligible_total: 1, shown: 1 }));
    decide.mockResolvedValueOnce(decided(raised, "return_to_next", { state: "next" }));
    const { run } = renderInRun(<SomedayStep />);

    await user.click(await screen.findByRole("button", { name: "Move to Next" }));
    const field = screen.getByRole("textbox", { name: "What's the first concrete action?" });
    await user.clear(field);
    await user.type(field, "Buy four boards");
    expect(run.setUnsaved).toHaveBeenLastCalledWith(true);
    await user.click(screen.getByRole("button", { name: "Move to Next" }));

    expect(decide).toHaveBeenCalledWith("sd_1", { type: "return_to_next", expected_revision: 5, title: "Buy four boards", session_id: "review_1" }, expect.any(String));
    await waitFor(() => expect(lastToast()[0]).toBe("“Build a raised bed” moved to Next actions"));
  });

  it("020-FR-032 nothing needing a look says so", async () => {
    getQueue.mockResolvedValueOnce(queue([], { eligible_total: 0, shown: 0 }));
    renderInRun(<SomedayStep />);

    expect(await screen.findByText("Nothing in Someday needs a look this week.")).toBeInTheDocument();
  });
});
