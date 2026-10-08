import { onlineManager, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ProtectedRoute } from "../../../components/auth/ProtectedRoute";
import { ApiError, apiClient } from "../../../api/client";
import { reviewApi, type LastCountedReview, type ReviewSession } from "../../../api/review";
import type { ProjectResponse, TaskResponse } from "../../../api/taskTypes";
import { formatReviewDate } from "../formulation";
import { readRelease, rememberRelease } from "../releaseMemory";
import { ReviewGate } from "../ReviewGate";
import { DAY, iso, sessionFixture, signIn, stateFixture, taskFixture, zeroCounts } from "./reviewKit";

// The steps are tested on their own; here each one is a stand-in that can reach the run.
vi.mock("../steps/WinsStep", () => ({ WinsStep: () => "Wins content" }));
vi.mock("../steps/InboxStep", async () => {
  const { createElement } = await import("react");
  const { useReviewRun } = await import("../steps/reviewRun");
  const { newProgressAttempt } = await import("../../../api/review");
  return {
    InboxStep: () => {
      const run = useReviewRun();
      return createElement("button", { type: "button", onClick: () => void run.progress(newProgressAttempt(run.session.id, { inbox_processed_delta: 1 })).catch(() => undefined) }, "Count one");
    }
  };
});
vi.mock("../steps/MindSweepStep", async () => {
  const { createElement } = await import("react");
  const { useReviewRun } = await import("../steps/reviewRun");
  return {
    MindSweepStep: () => {
      const run = useReviewRun();
      return createElement("input", { "aria-label": "Mind sweep line", onChange: (event: { currentTarget: { value: string } }) => run.setUnsaved(event.currentTarget.value !== "") });
    }
  };
});
vi.mock("../steps/DecisionsStep", () => ({ DecisionsStep: () => "Decisions content" }));
vi.mock("../steps/RestOfNextStep", () => ({ RestOfNextStep: () => "Rest of Next content" }));
vi.mock("../steps/WaitingStep", () => ({ WaitingStep: () => "Waiting content" }));
vi.mock("../steps/ProjectsStep", () => ({ ProjectsStep: () => "Projects content" }));
vi.mock("../steps/SomedayStep", () => ({ SomedayStep: () => "Someday content" }));
vi.mock("../steps/DatesStep", () => ({ DatesStep: () => "Dates content" }));
vi.mock("../steps/SummaryStep", async () => {
  const { createElement } = await import("react");
  const { useReviewRun } = await import("../steps/reviewRun");
  return {
    SummaryStep: () => {
      const run = useReviewRun();
      return createElement(
        "div",
        null,
        createElement("button", { type: "button", onClick: () => void run.finish("yes", "key-done").catch(() => undefined) }, "Done"),
        createElement("button", { type: "button", onClick: () => void run.finish(null, "key-none").catch(() => undefined) }, "Done without an answer")
      );
    }
  };
});
vi.mock("../../../api/review", async () => {
  const actual = await vi.importActual<typeof import("../../../api/review")>("../../../api/review");
  return {
    ...actual,
    reviewApi: {
      ...actual.reviewApi,
      getState: vi.fn(),
      startSession: vi.fn(),
      progress: vi.fn(),
      finish: vi.fn(),
      getSession: vi.fn(),
      updateSettings: vi.fn(),
      acknowledgeExplainer: vi.fn(),
      acknowledgeParks: vi.fn()
    }
  };
});
vi.mock("../../../api/client", async () => {
  const actual = await vi.importActual<typeof import("../../../api/client")>("../../../api/client");
  return { ...actual, apiClient: { ...actual.apiClient, listTasks: vi.fn(), getTask: vi.fn(), listProjects: vi.fn() } };
});

const getState = vi.mocked(reviewApi.getState);
const startSession = vi.mocked(reviewApi.startSession);
const progress = vi.mocked(reviewApi.progress);
const finish = vi.mocked(reviewApi.finish);
const getSession = vi.mocked(reviewApi.getSession);
const updateSettings = vi.mocked(reviewApi.updateSettings);
const acknowledgeExplainer = vi.mocked(reviewApi.acknowledgeExplainer);
const acknowledgeParks = vi.mocked(reviewApi.acknowledgeParks);

function Probe(): React.JSX.Element {
  return <div data-testid="location">{useLocation().pathname}</div>;
}

function renderReview() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/review"]}>
        <Routes>
          <Route path="/review" element={<ProtectedRoute><ReviewGate /></ProtectedRoute>} />
          <Route path="*" element={<Probe />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  );
  return client;
}

const fullSteps = sessionFixture().steps;
const quickSteps = { wins: "pending", inbox: "pending", decisions: "pending", summary: "pending" } as const;
const fullAt = (current: ReviewSession["current_step"], overrides: Partial<ReviewSession> = {}) => sessionFixture({ current_step: current, ...overrides });
const quick = (overrides: Partial<ReviewSession> = {}) => sessionFixture({ mode: "quick", current_step: "wins", steps: quickSteps, ...overrides });
const lastReview: LastCountedReview = {
  session_id: "review_old",
  status: "completed",
  origin: "ios",
  ended_at: "2026-09-30T15:40:00Z",
  counts: { ...zeroCounts, done: 3, someday: 1, inbox_processed: 4 },
  clear_start: "yes"
};

async function startFull(user: ReturnType<typeof userEvent.setup>, session = sessionFixture()) {
  startSession.mockResolvedValueOnce(session);
  await user.click(await screen.findByRole("button", { name: /^Full/ }));
  await screen.findByRole("navigation", { name: "Review steps" });
}

const bar = () => screen.getByRole("banner");

beforeEach(() => {
  window.localStorage.clear();
  signIn();
  getState.mockResolvedValue(stateFixture());
  vi.mocked(apiClient.listProjects).mockResolvedValue([]);
});

afterEach(() => {
  cleanup();
  onlineManager.setOnline(true);
  vi.restoreAllMocks();
  for (const mock of [getState, startSession, progress, finish, getSession, updateSettings, acknowledgeExplainer, acknowledgeParks]) {
    mock.mockReset();
  }
  vi.mocked(apiClient.listTasks).mockReset();
  vi.mocked(apiClient.getTask).mockReset();
  vi.mocked(apiClient.listProjects).mockReset();
  window.localStorage.clear();
});

describe("020-FR-042 the /review route", () => {
  it("020-FR-042 with the flag off it asks the review nothing and leaves for the task list", async () => {
    signIn("user-off", {});
    renderReview();

    expect(await screen.findByTestId("location")).toHaveTextContent("/");
    expect(getState).not.toHaveBeenCalled();
  });

  it("020-FR-027 shows a placeholder while it checks for a review in progress, then the entry", async () => {
    let resolve: (value: ReturnType<typeof stateFixture>) => void = () => undefined;
    getState.mockReturnValueOnce(new Promise((done) => { resolve = done; }));
    renderReview();

    expect(screen.getByRole("status", { name: "Checking for a review in progress…" })).toHaveAttribute("aria-busy", "true");
    await act(async () => resolve(stateFixture()));

    expect(await screen.findByRole("heading", { name: "How much time do you have?" })).toBeInTheDocument();
  });

  it("020-FR-045 a review that cannot be loaded says so without a Ref when there is none to quote", async () => {
    getState.mockRejectedValueOnce(new Error("socket hang up"));
    renderReview();

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("We couldn't load your review. Your progress is safe.");
    expect(alert).not.toHaveTextContent("Ref");
  });

  it("020-FR-045 a review that cannot be loaded says progress is safe, with the Ref, and retries", async () => {
    const user = userEvent.setup();
    getState.mockRejectedValueOnce(new ApiError("down", 503, null, "corr_review_load"));
    renderReview();

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("We couldn't load your review. Your progress is safe.");
    expect(alert).toHaveTextContent("Ref corr_review_load");
    await user.click(within(alert).getByRole("button", { name: "Retry" }));

    expect(await screen.findByRole("heading", { name: "How much time do you have?" })).toBeInTheDocument();
  });
});

describe("020-FR-027 020-FR-029 the entry", () => {
  it("020-FR-027 offers Quick and Full with what each holds, and the last review in the bar", async () => {
    renderReview();

    expect(await screen.findByRole("button", { name: /^Quick/ })).toHaveTextContent("Wins of the week, Inbox, tasks that ask for a decision, summary.");
    expect(screen.getByRole("button", { name: /^Full/ })).toHaveTextContent("Get clear, get current, get creative");
    expect(within(bar()).getByText("Last review: 9 days ago")).toBeInTheDocument();
    expect(screen.queryByText("Pick up where you left off?")).not.toBeInTheDocument();
  });

  it("020-FR-029 Close leaves for the task list", async () => {
    const user = userEvent.setup();
    renderReview();

    await user.click(await screen.findByRole("button", { name: "Close" }));

    expect(screen.getByTestId("location")).toHaveTextContent("/tasks/next");
  });

  it("020-FR-029 a review open on any device is offered first, with its step, origin and decisions so far", async () => {
    const user = userEvent.setup();
    const open = fullAt("inbox", { origin: "ios", counts: { ...zeroCounts, done: 2, someday: 4, inbox_processed: 9 }, steps: { ...fullSteps, wins: "finished", mind_sweep: "skipped" } });
    getState.mockResolvedValue(stateFixture({ open_session: open }));
    renderReview();

    expect(await screen.findByRole("heading", { name: "Pick up where you left off?" })).toBeInTheDocument();
    expect(screen.getByText("Full review · step 3 of 10")).toBeInTheDocument();
    expect(screen.getByText(/^Started .* on iPhone\. 6 decisions made so far\.$/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Continue" }));

    expect(await screen.findByRole("navigation", { name: "Review steps" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Inbox" })).toBeInTheDocument();
    expect(startSession).not.toHaveBeenCalled();
  });

  it("020-FR-029 Start a new review replaces the open one", async () => {
    const user = userEvent.setup();
    getState.mockResolvedValue(stateFixture({ open_session: quick({ origin: "web", started_at: iso(-1000) }) }));
    renderReview();
    await screen.findByRole("heading", { name: "Pick up where you left off?" });
    expect(screen.getByText("Quick review · step 1 of 4")).toBeInTheDocument();
    expect(screen.getByText(/^Started today at \d{2}:\d{2} on the web\. 0 decisions made so far\.$/)).toBeInTheDocument();
    startSession.mockResolvedValueOnce(quick());

    await user.click(screen.getByRole("button", { name: /^Quick/ }));

    expect(startSession).toHaveBeenCalledWith({ mode: "quick", entry: "sidebar", origin: "web", replace_open: true }, expect.any(String));
    expect(await screen.findByText("Step 1 of 4")).toBeInTheDocument();
  });

  it("020-FR-027 starting a review sends the mode without replacing anything and opens its first step", async () => {
    const user = userEvent.setup();
    renderReview();
    startSession.mockResolvedValueOnce(quick());

    await user.click(await screen.findByRole("button", { name: /^Quick/ }));

    expect(startSession).toHaveBeenCalledWith({ mode: "quick", entry: "sidebar", origin: "web", replace_open: false }, expect.any(String));
    expect(await screen.findByText("Wins content")).toBeInTheDocument();
    expect(screen.getByText("Step 1 of 4")).toBeInTheDocument();
  });

  it("020-FR-045 a start that fails changes nothing, shows the Ref and retries under the same key", async () => {
    const user = userEvent.setup();
    renderReview();
    startSession.mockRejectedValueOnce(new ApiError("down", 503, null, "corr_start"));
    startSession.mockResolvedValueOnce(quick());

    await user.click(await screen.findByRole("button", { name: /^Quick/ }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Couldn't start the review.");
    expect(alert).toHaveTextContent("Ref corr_start");
    await user.click(within(alert).getByRole("button", { name: "Retry" }));

    expect(await screen.findByText("Wins content")).toBeInTheDocument();
    expect(startSession.mock.calls[1][1]).toBe(startSession.mock.calls[0][1]);
  });

  it("020-SC-007 shows the last counted review, including one finished on iPhone, with its ten counts and the answer", async () => {
    getState.mockResolvedValue(stateFixture({ last_counted_review: lastReview }));
    renderReview();

    expect(await screen.findByText(`Last review · ${formatReviewDate(lastReview.ended_at as string)} · on iPhone`)).toBeInTheDocument();
    const counts = screen.getByRole("list", { name: "Last review counts" });
    expect(within(counts).getAllByRole("listitem")).toHaveLength(10);
    expect(within(counts).getByText("Inbox processed").parentElement).toHaveTextContent("4");
    expect(screen.getByText("Clear start: Yes")).toBeInTheDocument();
  });

  it("020-SC-007 a last review without an answer or an end date says neither, and an open review hides the card", async () => {
    getState.mockResolvedValueOnce(stateFixture({ last_counted_review: { ...lastReview, ended_at: null, clear_start: "not_really", origin: "web", status: "completed" } }));
    renderReview();

    expect(await screen.findByText("Last review · on the web")).toBeInTheDocument();
    expect(screen.getByText("Clear start: Not really")).toBeInTheDocument();
    cleanup();

    getState.mockResolvedValue(stateFixture({ last_counted_review: lastReview, open_session: fullAt("wins") }));
    renderReview();
    await screen.findByRole("heading", { name: "Pick up where you left off?" });
    expect(screen.queryByRole("list", { name: "Last review counts" })).not.toBeInTheDocument();
  });

  it("020-FR-029 says an earlier review was closed after a week, keeping its decisions", async () => {
    getState.mockResolvedValue(stateFixture({ last_counted_review: { ...lastReview, status: "partial", origin: "web", ended_at: iso(-2 * DAY) } }));
    getSession.mockResolvedValue(sessionFixture({ status: "partial", started_at: iso(-12 * DAY), last_activity_at: iso(-10 * DAY), ended_at: iso(-2 * DAY), counts: { ...zeroCounts, done: 4, cancelled: 2, inbox_processed: 8 } }));
    renderReview();

    expect(await screen.findByText(`Your review from ${formatReviewDate(iso(-12 * DAY))} was closed after a week without activity. Its 6 decisions are kept.`)).toBeInTheDocument();
    expect(getSession).toHaveBeenCalledWith("review_old", expect.anything());
  });

  it.each([
    ["a review that ended within a week of its last activity", { last_activity_at: iso(-4 * DAY), ended_at: iso(-2 * DAY) }, 2],
    ["a review closed long ago", { last_activity_at: iso(-40 * DAY), ended_at: iso(-30 * DAY) }, 30]
  ])("020-FR-029 says nothing about %s", async (_label, times, endedDaysAgo) => {
    getState.mockResolvedValue(stateFixture({ last_counted_review: { ...lastReview, status: "partial", ended_at: iso(-endedDaysAgo * DAY) } }));
    getSession.mockResolvedValue(sessionFixture({ status: "partial", started_at: iso(-45 * DAY), ...times }));
    renderReview();

    await screen.findByText(/^Last review · /);
    await waitFor(() => expect(getSession).toHaveBeenCalled());
    expect(screen.queryByText(/closed after a week/)).not.toBeInTheDocument();
  });

  it("020-FR-029 a closed review that cannot be read is simply not mentioned", async () => {
    getState.mockResolvedValue(stateFixture({ last_counted_review: { ...lastReview, status: "partial", clear_start: null } }));
    getSession.mockRejectedValue(new ApiError("gone", 404, null, "corr_gone"));
    renderReview();

    await screen.findByText(/^Last review · /);
    await waitFor(() => expect(getSession).toHaveBeenCalled());
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.queryByText(/Clear start/)).not.toBeInTheDocument();
  });
});

describe("020-FR-016 020-FR-051 020-FR-015 020-FR-017 what comes before the picker", () => {
  const unseen = [{ task_id: "task-pt", formulation_id: "form_pt", parked_at: iso(-1 * DAY) }];
  const parkedTask: TaskResponse = taskFixture({ id: "task-pt", title: "Learn basic Portuguese", state: "someday", revision: 4, parked: { at: iso(-1 * DAY), formulation_id: "form_pt" } });
  const projects: ProjectResponse[] = [];

  beforeEach(() => {
    vi.mocked(apiClient.getTask).mockResolvedValue(parkedTask);
    vi.mocked(apiClient.listProjects).mockResolvedValue(projects);
  });

  it("020-FR-051 the auto-park explainer comes first while it has not been seen", async () => {
    getState.mockResolvedValue(stateFixture({ explainer_seen: false, settings: { ...stateFixture().settings, onboarded_at: null }, unseen_parks: unseen }));
    renderReview();

    expect(await screen.findByRole("dialog", { name: "How Next stays fresh" })).toBeInTheDocument();
    expect(screen.queryByRole("dialog", { name: "A weekly reset" })).not.toBeInTheDocument();
  });

  it("020-FR-016 then onboarding; Escape saves nothing and returns focus to Close", async () => {
    getState.mockResolvedValue(stateFixture({ settings: { ...stateFixture().settings, onboarded_at: null }, unseen_parks: unseen }));
    const user = userEvent.setup();
    renderReview();

    expect(await screen.findByRole("dialog", { name: "A weekly reset" })).toBeInTheDocument();
    expect(screen.queryByRole("dialog", { name: "While you were away" })).not.toBeInTheDocument();
    await user.keyboard("{Escape}");

    expect(screen.queryByRole("dialog", { name: "A weekly reset" })).not.toBeInTheDocument();
    expect(updateSettings).not.toHaveBeenCalled();
    expect(await screen.findByRole("dialog", { name: "While you were away" })).toBeInTheDocument();
  });

  it("020-FR-016 saving onboarding closes it and the picker is there", async () => {
    getState.mockResolvedValue(stateFixture({ settings: { ...stateFixture().settings, onboarded_at: null } }));
    updateSettings.mockResolvedValue({ ...stateFixture().settings, onboarded_at: iso(0), revision: 4 });
    const user = userEvent.setup();
    renderReview();

    await user.click(await screen.findByRole("button", { name: "Continue" }));
    getState.mockResolvedValue(stateFixture());

    await waitFor(() => expect(screen.queryByRole("dialog", { name: "A weekly reset" })).not.toBeInTheDocument());
    expect(screen.getByRole("heading", { name: "How much time do you have?" })).toBeInTheDocument();
  });

  it("020-FR-016 closing onboarding with Close puts focus on the entry's Close", async () => {
    getState.mockResolvedValue(stateFixture({ settings: { ...stateFixture().settings, onboarded_at: null } }));
    const user = userEvent.setup();
    renderReview();
    const dialog = await screen.findByRole("dialog", { name: "A weekly reset" });

    await user.click(within(dialog).getByRole("button", { name: "Close" }));

    await waitFor(() => expect(within(bar()).getByRole("button", { name: "Close" })).toHaveFocus());
  });

  it("020-FR-015 While you were away is the first screen of a review, and Continue acknowledges it", async () => {
    getState.mockResolvedValue(stateFixture({ unseen_parks: unseen }));
    acknowledgeParks.mockResolvedValue(undefined);
    const user = userEvent.setup();
    renderReview();

    const dialog = await screen.findByRole("dialog", { name: "While you were away" });
    expect(await within(dialog).findByText("Learn basic Portuguese")).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "Continue" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(acknowledgeParks).toHaveBeenCalledTimes(1);
  });

  it("020-FR-015 Escape closes it without acknowledging, and it does not come back in this visit", async () => {
    getState.mockResolvedValue(stateFixture({ unseen_parks: unseen }));
    const user = userEvent.setup();
    renderReview();
    await screen.findByRole("dialog", { name: "While you were away" });

    await user.keyboard("{Escape}");

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(acknowledgeParks).not.toHaveBeenCalled();
    expect(screen.getByRole("heading", { name: "How much time do you have?" })).toBeInTheDocument();
  });

  it("020-FR-051 the explainer is dismissed for this visit once it has been answered", async () => {
    getState.mockResolvedValue(stateFixture({ explainer_seen: false }));
    acknowledgeExplainer.mockResolvedValue(stateFixture());
    const user = userEvent.setup();
    renderReview();

    await user.click(await screen.findByRole("button", { name: "Got it" }));

    await waitFor(() => expect(screen.queryByRole("dialog", { name: "How Next stays fresh" })).not.toBeInTheDocument());
  });

  it("020-FR-017 restart mode comes before the picker, and starting from it records the restart entry", async () => {
    const user = userEvent.setup();
    getState.mockResolvedValue(stateFixture({ restart_mode: true, last_counted_review_at: iso(-30 * DAY) }));
    vi.mocked(apiClient.listTasks).mockResolvedValue({ items: [], next_cursor: null, has_more: false, counts_by_state: { inbox: 0, next: 0, waiting: 0, someday: 0 } });
    renderReview();

    expect(await screen.findByRole("heading", { name: "Welcome back" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Quick/ })).not.toBeInTheDocument();
    await user.click(await screen.findByRole("button", { name: "Start the review" }));
    startSession.mockResolvedValueOnce(quick({ entry: "restart" }));
    await user.click(await screen.findByRole("button", { name: /^Quick/ }));

    expect(startSession).toHaveBeenCalledWith({ mode: "quick", entry: "restart", origin: "web", replace_open: false }, expect.any(String));
  });
});

describe("020-FR-028 020-FR-052 the review shell", () => {
  it("020-FR-028 shows a non-focusable 240 px rail of the mode's steps with done, skipped and current marked, and Step N of M for narrow screens", async () => {
    const user = userEvent.setup();
    renderReview();
    const session = fullAt("inbox", { steps: { ...fullSteps, wins: "finished", mind_sweep: "skipped" } });
    await startFull(user, session);

    const rail = screen.getByRole("navigation", { name: "Review steps" });
    expect(rail).toHaveClass("w-[240px]");
    expect(rail.querySelectorAll("a, button, input, select, textarea, [tabindex]")).toHaveLength(0);
    const items = within(rail).getAllByRole("listitem");
    expect(items).toHaveLength(10);
    expect(items[0]).toHaveTextContent("Wins of the week");
    expect(items[0]).toHaveTextContent("done");
    expect(items[1]).toHaveTextContent("skipped");
    expect(items[2]).toHaveAttribute("aria-current", "step");
    expect(items[3]).not.toHaveAttribute("aria-current");
    const narrow = screen.getByText("Step 3 of 10");
    expect(narrow).toHaveClass("md:hidden");
  });

  it("020-FR-028 moves focus to the step heading when the step changes", async () => {
    const user = userEvent.setup();
    renderReview();
    await startFull(user);
    expect(screen.getByRole("heading", { name: "Wins of the week" })).toHaveFocus();
    progress.mockResolvedValueOnce(fullAt("mind_sweep", { steps: { ...fullSteps, wins: "finished" } }));

    await user.click(screen.getByRole("button", { name: "Next" }));

    expect(await screen.findByRole("heading", { name: "Mind sweep" })).toHaveFocus();
  });

  it("020-FR-029 a run with no current step shows the summary", async () => {
    const user = userEvent.setup();
    renderReview();
    await startFull(user, fullAt(null));

    expect(screen.getByRole("heading", { name: "Review done" })).toBeInTheDocument();
    expect(screen.getByText("Step 10 of 10")).toBeInTheDocument();
  });

  it("020-FR-029 Escape never closes the review", async () => {
    const user = userEvent.setup();
    renderReview();
    await startFull(user);

    await user.keyboard("{Escape}");

    expect(screen.getByRole("navigation", { name: "Review steps" })).toBeInTheDocument();
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  });

  it("020-FR-029 Next finishes the step and moves on in one change carrying a progress id; Skip step is not on the summary", async () => {
    const user = userEvent.setup();
    renderReview();
    await startFull(user, fullAt("rest_of_next", { steps: { ...fullSteps, wins: "finished", mind_sweep: "finished", inbox: "finished", decisions: "finished" } }));
    progress.mockResolvedValueOnce(fullAt("waiting"));

    await user.click(screen.getByRole("button", { name: "Next" }));

    await screen.findByText("Waiting content");
    expect(progress).toHaveBeenCalledWith({
      sessionId: "review_1",
      body: { progress_id: expect.stringMatching(/^progress_/), step: { code: "rest_of_next", status: "finished" }, current_step: "waiting" },
      key: expect.any(String)
    });
  });

  it("020-FR-034 moving on to the decisions step freezes its queue", async () => {
    const user = userEvent.setup();
    renderReview();
    await startFull(user, fullAt("inbox"));
    progress.mockResolvedValueOnce(fullAt("decisions"));

    await user.click(screen.getByRole("button", { name: "Next" }));

    await screen.findByText("Decisions content");
    expect(progress.mock.calls[0][0].body).toMatchObject({ current_step: "decisions", snapshot_decision_queue: true });
  });

  it("020-FR-029 Skip step saves the step as skipped; if that is not saved the step stays with the Ref and Retry resends the same change", async () => {
    const user = userEvent.setup();
    renderReview();
    await startFull(user);
    progress.mockRejectedValueOnce(new ApiError("down", 503, null, "corr_skip"));
    progress.mockResolvedValueOnce(fullAt("mind_sweep", { steps: { ...fullSteps, wins: "skipped" } }));

    await user.click(within(bar()).getByRole("button", { name: "Skip step" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Couldn't save that you skipped this step. Try again.");
    expect(alert).toHaveTextContent("Ref corr_skip");
    expect(screen.getByText("Wins content")).toBeInTheDocument();
    await user.click(within(alert).getByRole("button", { name: "Retry" }));

    expect(await screen.findByRole("heading", { name: "Mind sweep" })).toBeInTheDocument();
    expect(progress.mock.calls[1][0].body).toEqual(progress.mock.calls[0][0].body);
    expect(progress.mock.calls[1][0].key).toBe(progress.mock.calls[0][0].key);
    expect(progress.mock.calls[0][0].body).toMatchObject({ step: { code: "wins", status: "skipped" }, current_step: "mind_sweep" });
  });

  it("020-FR-029 a Next that is not saved says so in its own words", async () => {
    const user = userEvent.setup();
    renderReview();
    await startFull(user);
    progress.mockRejectedValueOnce(new ApiError("down", 503, null, "corr_next"));

    await user.click(screen.getByRole("button", { name: "Next" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Couldn't save that you finished this step. Try again.");
  });

  it("020-FR-029 the summary has neither Skip step nor Next, only Leave", async () => {
    const user = userEvent.setup();
    renderReview();
    await startFull(user, fullAt("summary"));

    expect(screen.getByRole("heading", { name: "Review done" })).toBeInTheDocument();
    expect(within(bar()).queryByRole("button", { name: "Skip step" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Next" })).not.toBeInTheDocument();
    expect(within(bar()).getByRole("button", { name: "Leave" })).toBeInTheDocument();
  });

  it("020-FR-052 text that has not been saved is asked about before Skip; Keep editing keeps the step, Discard moves on and clears the field", async () => {
    const user = userEvent.setup();
    renderReview();
    await startFull(user, fullAt("mind_sweep"));
    await user.type(screen.getByRole("textbox", { name: "Mind sweep line" }), "call the plumber");

    await user.click(within(bar()).getByRole("button", { name: "Skip step" }));
    const dialog = screen.getByRole("alertdialog", { name: "Discard what you typed?" });
    expect(dialog).toHaveTextContent("It hasn't been saved.");
    expect(within(dialog).getByRole("button", { name: "Keep editing" })).toHaveFocus();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    expect(progress).not.toHaveBeenCalled();
    expect(screen.getByRole("textbox", { name: "Mind sweep line" })).toHaveValue("call the plumber");

    progress.mockResolvedValueOnce(fullAt("inbox", { steps: { ...fullSteps, mind_sweep: "skipped" } }));
    await user.click(within(bar()).getByRole("button", { name: "Skip step" }));
    await user.click(screen.getByRole("button", { name: "Discard" }));

    expect(await screen.findByRole("button", { name: "Count one" })).toBeInTheDocument();
    expect(progress.mock.calls[0][0].body).toMatchObject({ step: { code: "mind_sweep", status: "skipped" } });
  });

  it("020-FR-052 Discard on a step that stays clears its field", async () => {
    const user = userEvent.setup();
    renderReview();
    await startFull(user, fullAt("mind_sweep"));
    await user.type(screen.getByRole("textbox", { name: "Mind sweep line" }), "call the plumber");

    await user.click(within(bar()).getByRole("button", { name: "Leave" }));
    await user.click(screen.getByRole("button", { name: "Discard" }));
    expect(screen.getByRole("alertdialog", { name: "Take a break?" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Keep going" }));

    expect(screen.getByRole("textbox", { name: "Mind sweep line" })).toHaveValue("");
  });
});

describe("020-FR-029 leaving the review", () => {
  it("020-FR-029 Leave asks first with focus on Keep going; Escape keeps going and returns focus to Leave", async () => {
    const user = userEvent.setup();
    renderReview();
    await startFull(user, fullAt("inbox"));

    await user.click(within(bar()).getByRole("button", { name: "Leave" }));
    const dialog = screen.getByRole("alertdialog", { name: "Take a break?" });
    expect(dialog).toHaveTextContent("Everything you've done is kept. Continue from step 3 any time, on any device.");
    expect(within(dialog).getByRole("button", { name: "Keep going" })).toHaveFocus();
    await user.keyboard("{Escape}");

    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    expect(within(bar()).getByRole("button", { name: "Leave" })).toHaveFocus();
    expect(screen.getByRole("navigation", { name: "Review steps" })).toBeInTheDocument();
  });

  it("020-FR-052 Tab stays inside the confirmation, and other keys leave it alone", async () => {
    const user = userEvent.setup();
    renderReview();
    await startFull(user, fullAt("inbox"));
    await user.click(within(bar()).getByRole("button", { name: "Leave" }));

    await user.tab();
    expect(screen.getByRole("button", { name: "Leave for now" })).toHaveFocus();
    await user.tab();
    expect(screen.getByRole("button", { name: "Keep going" })).toHaveFocus();
    await user.keyboard("{Enter}");

    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  });

  it("020-FR-029 Leave for now pauses the review, drops the remembered release and goes back to the task list", async () => {
    const user = userEvent.setup();
    rememberRelease("user-1", { kind: "inbox_remainder", bulkId: "bulk_1", sessionId: "review_1", released: 3 });
    renderReview();
    await startFull(user, fullAt("inbox"));

    await user.click(within(bar()).getByRole("button", { name: "Leave" }));
    await user.click(screen.getByRole("button", { name: "Leave for now" }));

    expect(screen.getByTestId("location")).toHaveTextContent("/tasks/next");
    expect(readRelease("user-1")).toBeNull();
    expect(finish).not.toHaveBeenCalled();
  });

  it("020-FR-029 browser Back acts as Leave; Keep going stays on the review and Back asks again", async () => {
    const user = userEvent.setup();
    const pushState = vi.spyOn(window.history, "pushState");
    renderReview();
    await startFull(user, fullAt("inbox"));
    const pushed = pushState.mock.calls.length;

    act(() => window.history.back());
    await user.click(await screen.findByRole("button", { name: "Keep going" }));

    expect(pushState.mock.calls.length).toBe(pushed + 1);
    expect(screen.getByRole("navigation", { name: "Review steps" })).toBeInTheDocument();
    act(() => window.history.back());
    expect(await screen.findByRole("alertdialog", { name: "Take a break?" })).toBeInTheDocument();
  });

  it("020-FR-052 browser Back with unsaved text asks to discard it first", async () => {
    const user = userEvent.setup();
    renderReview();
    await startFull(user, fullAt("mind_sweep"));
    await user.type(screen.getByRole("textbox", { name: "Mind sweep line" }), "call the plumber");

    act(() => window.history.back());
    await user.click(await screen.findByRole("button", { name: "Keep editing" }));
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    act(() => window.history.back());
    await user.click(await screen.findByRole("button", { name: "Discard" }));

    expect(await screen.findByRole("alertdialog", { name: "Take a break?" })).toBeInTheDocument();
  });

  it("020-FR-052 closing the tab with unsaved text gets the browser's leave warning", async () => {
    const user = userEvent.setup();
    renderReview();
    await startFull(user, fullAt("mind_sweep"));
    await user.type(screen.getByRole("textbox", { name: "Mind sweep line" }), "call the plumber");

    const unload = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(unload);

    expect(unload.defaultPrevented).toBe(true);
  });
});

describe("020-FR-029 020-SC-007 the run meets other devices", () => {
  it("020-FR-029 a review finished or replaced elsewhere replaces the step with a notice, keeping what was made here", async () => {
    const user = userEvent.setup();
    renderReview();
    await startFull(user, fullAt("inbox"));
    progress.mockResolvedValueOnce(fullAt("inbox", { status: "partial", ended_at: iso(-1 * DAY), last_activity_at: iso(-1 * DAY), counts: { ...zeroCounts, done: 2, someday: 1 } }));

    await user.click(screen.getByRole("button", { name: "Count one" }));

    const heading = await screen.findByRole("heading", { name: "This review has ended" });
    expect(heading).toHaveFocus();
    expect(screen.getByText("This review was finished or replaced on another device. Its 3 decisions are kept.")).toBeInTheDocument();
    expect(screen.queryByText("Step 3 of 10")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Open the review" }));
    expect(await screen.findByRole("heading", { name: "How much time do you have?" })).toBeInTheDocument();
  });

  it("020-FR-029 a review the idle rule closed says it was closed after a week", async () => {
    const user = userEvent.setup();
    renderReview();
    await startFull(user, fullAt("inbox"));
    progress.mockResolvedValueOnce(fullAt("inbox", { status: "abandoned", last_activity_at: iso(-20 * DAY), ended_at: iso(-12 * DAY), counts: { ...zeroCounts, done: 6 } }));

    await user.click(screen.getByRole("button", { name: "Count one" }));

    expect(await screen.findByRole("heading", { name: "This review was closed" })).toHaveFocus();
    expect(screen.getByText("This review was closed after a week without activity. Its 6 decisions are kept.")).toBeInTheDocument();
  });

  it("020-FR-029 a review that moved on elsewhere jumps to the merged step with a one-line note", async () => {
    const user = userEvent.setup();
    renderReview();
    await startFull(user, fullAt("inbox"));
    progress.mockResolvedValueOnce(fullAt("waiting", { steps: { ...fullSteps, wins: "finished", mind_sweep: "finished", inbox: "finished", decisions: "finished", rest_of_next: "finished" } }));

    await user.click(screen.getByRole("button", { name: "Count one" }));

    expect(await screen.findByText("You continued this review on another device, so it's at step 6 now.")).toBeInTheDocument();
    expect(screen.getByText("Waiting content")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Waiting for, older than 7 days" })).toHaveFocus();
  });

  it("020-FR-029 a progress change that fails reaches the step that sent it, and the run stays", async () => {
    const user = userEvent.setup();
    renderReview();
    await startFull(user, fullAt("inbox"));
    progress.mockRejectedValueOnce(new ApiError("down", 503, null, "corr_count"));

    await user.click(screen.getByRole("button", { name: "Count one" }));

    await waitFor(() => expect(progress).toHaveBeenCalledTimes(1));
    expect(screen.getByRole("button", { name: "Count one" })).toBeInTheDocument();
  });

  it("020-SC-007 020-FR-033 Done finishes the run with the answer and returns to the entry showing the last review", async () => {
    const user = userEvent.setup();
    renderReview();
    await startFull(user, fullAt("summary"));
    finish.mockResolvedValueOnce(fullAt("summary", { status: "completed", ended_at: iso(0) }));
    getState.mockResolvedValue(stateFixture({ last_counted_review: { ...lastReview, origin: "web" } }));

    await user.click(screen.getByRole("button", { name: "Done" }));

    expect(await screen.findByRole("heading", { name: "How much time do you have?" })).toBeInTheDocument();
    expect(finish).toHaveBeenCalledWith("review_1", { clear_start: "yes" }, "key-done");
    expect(await screen.findByText(/^Last review · .* · on the web$/)).toBeInTheDocument();
  });

  it("020-FR-033 a Done without an answer sends no clear_start", async () => {
    const user = userEvent.setup();
    renderReview();
    await startFull(user, fullAt("summary"));
    finish.mockResolvedValueOnce(fullAt("summary", { status: "completed_empty", ended_at: iso(0) }));

    await user.click(screen.getByRole("button", { name: "Done without an answer" }));

    await waitFor(() => expect(finish).toHaveBeenCalledWith("review_1", {}, "key-none"));
  });

  it("020-FR-033 a Done that fails stays on the summary", async () => {
    const user = userEvent.setup();
    renderReview();
    await startFull(user, fullAt("summary"));
    finish.mockRejectedValueOnce(new ApiError("down", 503, null, "corr_finish"));

    await user.click(screen.getByRole("button", { name: "Done" }));

    await waitFor(() => expect(finish).toHaveBeenCalledTimes(1));
    expect(screen.getByRole("heading", { name: "Review done" })).toBeInTheDocument();
  });

  it("020-FR-042 a progress answer that arrives after another account signed in changes nothing for it", async () => {
    const user = userEvent.setup();
    renderReview();
    await startFull(user, fullAt("inbox"));
    let resolve: (session: ReviewSession) => void = () => undefined;
    progress.mockReturnValueOnce(new Promise((done) => { resolve = done; }));
    await user.click(screen.getByRole("button", { name: "Count one" }));

    act(() => signIn("user-2"));
    await act(async () => resolve(fullAt("waiting")));

    expect(await screen.findByRole("heading", { name: "How much time do you have?" })).toBeInTheDocument();
    expect(screen.queryByText(/You continued this review/)).not.toBeInTheDocument();
  });

  it("020-FR-042 a Done answered after another account signed in does not end that account's entry", async () => {
    const user = userEvent.setup();
    renderReview();
    await startFull(user, fullAt("summary"));
    let resolve: (session: ReviewSession) => void = () => undefined;
    finish.mockReturnValueOnce(new Promise((done) => { resolve = done; }));
    await user.click(screen.getByRole("button", { name: "Done" }));

    act(() => signIn("user-2"));
    await act(async () => resolve(fullAt("summary", { status: "completed", ended_at: iso(0) })));

    expect(await screen.findByRole("heading", { name: "How much time do you have?" })).toBeInTheDocument();
    expect(screen.queryByRole("navigation", { name: "Review steps" })).not.toBeInTheDocument();
  });

  it("020-FR-040 offline the shell says decisions made so far are saved", async () => {
    const user = userEvent.setup();
    renderReview();
    await startFull(user, fullAt("inbox"));

    vi.spyOn(navigator, "onLine", "get").mockReturnValue(false);
    act(() => { window.dispatchEvent(new Event("offline")); });

    expect(screen.getByRole("status", { name: "Offline" })).toHaveTextContent("You're offline. Decisions made so far are saved. Retry when you're back online, here or on another device.");
  });
});
