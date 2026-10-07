import { onlineManager, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { BrowserRouter, Link, MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, apiClient } from "../../../api/client";
import { reviewApi, type DecisionResponse } from "../../../api/review";
import { taskKeys } from "../../../api/taskHooks";
import type { TaskResponse } from "../../../api/taskTypes";
import { ShellToastContext, type ShellNotify, type ShellToastOptions } from "../../../components/shell/shellToast";
import { useAuthStore } from "../../../stores/authStore";
import { DecisionDialog, type DecisionOutcome } from "../DecisionDialog";
import { formatReviewDate } from "../formulation";
import { loadReviewDraft, reviewDraftKey, saveReviewDraft } from "../reviewFormDrafts";

vi.mock("../../../api/review", async () => {
  const actual = await vi.importActual<typeof import("../../../api/review")>("../../../api/review");
  return { ...actual, reviewApi: { ...actual.reviewApi, decide: vi.fn(), undoDecision: vi.fn() } };
});
vi.mock("../../../api/client", async () => {
  const actual = await vi.importActual<typeof import("../../../api/client")>("../../../api/client");
  return { ...actual, apiClient: { ...actual.apiClient, getTask: vi.fn() } };
});

const decide = vi.mocked(reviewApi.decide);
const undoDecision = vi.mocked(reviewApi.undoDecision);
const getTask = vi.mocked(apiClient.getTask);

const DAY = 86_400_000;
const NOW = Date.now();
const iso = (offsetMs: number) => new Date(NOW + offsetMs).toISOString();
const scope = { apiOrigin: "http://localhost:3000/api", accountId: "user-1" };

function asksTask(overrides: Partial<TaskResponse> = {}, formulation: Partial<NonNullable<TaskResponse["formulation"]>> = {}): TaskResponse {
  return {
    id: "task-1",
    title: "Renovate the bathroom",
    details: null,
    state: "next",
    project_id: "project-home",
    tag_ids: [],
    due_date: null,
    priority: "none",
    waiting_for: null,
    waiting_since: null,
    order_key: 1,
    source_capture_ids: [],
    created_at: iso(-20 * DAY),
    updated_at: iso(-15 * DAY),
    completed_at: null,
    cancelled_at: null,
    revision: 7,
    formulation: {
      id: "form_a",
      started_at: iso(-15 * DAY),
      extended_at: null,
      extension_reason: null,
      park_floor_at: null,
      consecutive_stalled: 0,
      ageing_at: iso(-8 * DAY),
      ask_at: iso(-1 * DAY),
      park_due_at: iso(6 * DAY),
      paused_until: null,
      ...formulation
    },
    parked: null,
    ...overrides
  };
}

function decided(task: TaskResponse, type: string, after: Partial<TaskResponse>): DecisionResponse {
  return {
    decision: {
      id: "decision_1",
      type,
      task_id: task.id,
      session_id: null,
      decided_at: iso(0),
      substantive: null,
      stall_reason: null,
      ai_use: "none",
      yielded_auto_park: false
    },
    task: { ...task, revision: task.revision + 1, formulation: null, ...after },
    created_task: null,
    receipt: null,
    session_counts: null
  };
}

const notify = vi.fn<ShellNotify>();
const onClose = vi.fn<(outcome: DecisionOutcome) => void>();

function LocationProbe(): React.JSX.Element {
  const location = useLocation();
  return <div data-testid="location">{location.pathname}</div>;
}

function renderDialog(task: TaskResponse, { client = new QueryClient({ defaultOptions: { queries: { retry: false } } }), projectName = "Home" as string | null } = {}) {
  const view = render(
    <QueryClientProvider client={client}>
      <ShellToastContext.Provider value={notify}>
        <MemoryRouter initialEntries={["/tasks/next"]}>
          <LocationProbe />
          <Link to="/projects/project-home">Home project</Link>
          <Routes>
            <Route path="*" element={<DecisionDialog task={task} projectName={projectName} onClose={onClose} />} />
          </Routes>
        </MemoryRouter>
      </ShellToastContext.Provider>
    </QueryClientProvider>
  );
  return { ...view, client };
}

const dialog = () => screen.getByRole("dialog", { name: "Renovate the bathroom" });
const decisionButton = (name: RegExp | string) => within(screen.getByRole("group", { name: "Decisions" })).getByRole("button", { name });
const lastToast = (): [string, ShellToastOptions | undefined] => notify.mock.calls[notify.mock.calls.length - 1] as [string, ShellToastOptions | undefined];

beforeEach(() => {
  window.localStorage.clear();
  act(() => {
    useAuthStore.setState({ user: { id: "user-1", email: "max@example.test" }, status: "authed" });
  });
  vi.spyOn(navigator, "onLine", "get").mockReturnValue(true);
});

/** The dialog pops its own history entry on unmount; let that traversal land. */
const settleHistory = () => act(() => new Promise<void>((resolve) => setTimeout(resolve, 20)));

afterEach(async () => {
  cleanup();
  await settleHistory();
  // React Query's onlineManager hears the same events; a test that went
  // offline must not leave every later mutation paused.
  onlineManager.setOnline(true);
  vi.restoreAllMocks();
  decide.mockReset();
  undoDecision.mockReset();
  getTask.mockReset();
  notify.mockReset();
  onClose.mockReset();
  window.localStorage.clear();
  act(() => {
    useAuthStore.setState({ user: null, status: "loading" });
  });
});

describe("020-FR-006 decision dialog: the card", () => {
  it("020-FR-006 opens as a 560 px modal with focus on the title and seven decisions in fixed order, numbered", () => {
    renderDialog(asksTask());

    const panel = dialog();
    expect(panel).toHaveAttribute("aria-modal", "true");
    expect(panel).toHaveClass("sm:w-[560px]");
    expect(screen.getByRole("heading", { name: "Renovate the bathroom" })).toHaveFocus();
    expect(within(panel).getByText("Asks for a decision")).toBeInTheDocument();
    expect(within(panel).getByText("15 days in Next · Home")).toBeInTheDocument();
    expect(within(panel).getByText("This wording hasn't moved. That usually means the wording needs work, not you.")).toBeInTheDocument();

    const decisions = within(screen.getByRole("group", { name: "Decisions" })).getAllByRole("button");
    expect(decisions.map((button) => button.textContent)).toEqual([
      "Done1",
      "ReformulateSay what you'll actually do2",
      "Find a first stepSomething you could start in 10 minutes3",
      "Move to Waiting for…4",
      "Release to SomedayNot now. Bring it back any time5",
      "Cancel taskStays findable under Cancelled6",
      "Keep 7 more daysOnce, with a reason7"
    ]);
    const reasons = within(screen.getByRole("group", { name: "What got in the way, optional" })).getAllByRole("button");
    expect(reasons.map((reason) => [reason.textContent, reason.getAttribute("aria-pressed")])).toEqual([
      ["Unclear", "false"],
      ["Too big", "false"],
      ["Missing information", "false"],
      ["Waiting on someone", "false"],
      ["Unpleasant / no energy", "false"],
      ["No longer matters", "false"]
    ]);
  });

  it("020-FR-007 a reason recommends a decision without disabling any, and a second press clears it", async () => {
    const user = userEvent.setup();
    renderDialog(asksTask());

    await user.click(screen.getByRole("button", { name: "Too big" }));
    expect(screen.getByRole("button", { name: "Too big" })).toHaveAttribute("aria-pressed", "true");
    expect(decisionButton(/Find a first step/)).toHaveTextContent("Recommended");
    expect(within(screen.getByRole("group", { name: "Decisions" })).getAllByText("Recommended")).toHaveLength(1);
    for (const button of within(screen.getByRole("group", { name: "Decisions" })).getAllByRole("button")) {
      expect(button).toBeEnabled();
    }

    await user.click(screen.getByRole("button", { name: "No longer matters" }));
    expect(decisionButton(/Cancel task/)).toHaveTextContent("Recommended");
    expect(screen.getByRole("button", { name: "Too big" })).toHaveAttribute("aria-pressed", "false");

    await user.click(screen.getByRole("button", { name: "No longer matters" }));
    expect(screen.queryByText("Recommended")).not.toBeInTheDocument();
  });

  it("020-FR-006 Done saves with the task revision only, pending on its own row, then offers Undo and closes", async () => {
    const user = userEvent.setup();
    const task = asksTask();
    let resolve: (value: DecisionResponse) => void = () => undefined;
    decide.mockReturnValueOnce(new Promise((done) => { resolve = done; }));
    renderDialog(task);

    await user.click(decisionButton(/^Done/));

    expect(decide).toHaveBeenCalledWith("task-1", { type: "complete", expected_revision: 7 }, expect.any(String));
    expect(decisionButton(/^Done/)).toHaveTextContent("Saving…");
    expect(decisionButton(/^Reformulate/)).toBeDisabled();
    expect(screen.getByRole("button", { name: "Too big" })).toBeDisabled();

    await act(async () => resolve(decided(task, "complete", { state: "completed" })));

    const [message, options] = lastToast();
    expect(message).toBe("“Renovate the bathroom” done");
    expect(options?.action?.label).toBe("Undo");
    expect(options?.action?.accessibleLabel).toBe("Undo: Marked done Renovate the bathroom");
    expect(onClose).toHaveBeenCalledWith({ kind: "decided", task: expect.objectContaining({ state: "completed" }), leftNext: true });
  });

  it.each([
    ["Release to Someday", "someday", "“Renovate the bathroom” released to Someday", "Undo: Released to Someday Renovate the bathroom", { state: "someday" }, true],
    ["Cancel task", "cancel", "“Renovate the bathroom” cancelled", "Undo: Cancelled Renovate the bathroom", { state: "cancelled" }, true]
  ] as const)("020-FR-006 %s is one tap, carries the wording and the chosen reason", async (label, type, message, undoLabel, after, leftNext) => {
    const user = userEvent.setup();
    const task = asksTask();
    decide.mockResolvedValueOnce(decided(task, type, after));
    renderDialog(task);

    await user.click(screen.getByRole("button", { name: "Missing information" }));
    await user.click(decisionButton(new RegExp(`^${label}`)));

    await waitFor(() => expect(onClose).toHaveBeenCalled());
    const expectedBody = type === "someday"
      ? { type, expected_revision: 7, formulation_id: "form_a", stall_reason: "missing_info" }
      : { type, expected_revision: 7, stall_reason: "missing_info" };
    expect(decide).toHaveBeenCalledWith("task-1", expectedBody, expect.any(String));
    expect(lastToast()[0]).toBe(message);
    expect(lastToast()[1]?.action?.accessibleLabel).toBe(undoLabel);
    expect(onClose).toHaveBeenCalledWith(expect.objectContaining({ kind: "decided", leftNext }));
  });

  it("020-FR-006 shows Moves to Someday tomorrow on a task within 24 hours of its park, and a project-less meta line", () => {
    renderDialog(asksTask({}, { park_due_at: iso(12 * 60 * 60 * 1000) }), { projectName: null });
    expect(within(dialog()).getByText("Moves to Someday tomorrow")).toBeInTheDocument();
    expect(within(dialog()).getByText("15 days in Next · no project")).toBeInTheDocument();
  });

  it("020-FR-040 at 390 px the dialog is a full-height sheet", () => {
    renderDialog(asksTask());
    expect(dialog()).toHaveClass("h-full", "w-full", "sm:h-auto");
  });
});

describe("020-FR-006 decision dialog: the follow-up forms", () => {
  it("020-FR-006 Reformulate is prefilled, disabled until changed, and saves a substantive wording", async () => {
    const user = userEvent.setup();
    const task = asksTask();
    decide.mockResolvedValueOnce(decided(task, "reformulate", { title: "Get 3 quotes for the bathroom" }));
    renderDialog(task);

    await user.click(decisionButton(/^Reformulate/));
    const field = screen.getByRole("textbox", { name: "New wording" });
    expect(field).toHaveValue("Renovate the bathroom");
    expect(field).toHaveFocus();
    expect(screen.getByText("What will you actually do?")).toBeInTheDocument();
    expect(screen.getByText("Name a visible action. A new wording starts a fresh clock.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save new wording" })).toBeDisabled();

    await user.clear(field);
    await user.type(field, "Get 3 quotes for the bathroom");
    await user.click(screen.getByRole("button", { name: "Save new wording" }));

    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(decide).toHaveBeenCalledWith(
      "task-1",
      { type: "reformulate", expected_revision: 7, formulation_id: "form_a", title: "Get 3 quotes for the bathroom" },
      expect.any(String)
    );
    expect(lastToast()[0]).toBe("New wording saved: “Get 3 quotes for the bathroom”");
    expect(lastToast()[1]?.action?.accessibleLabel).toBe("Undo: Reworded Renovate the bathroom");
  });

  it("020-FR-002 a capitals-or-punctuation edit says so before saving and is saved anyway as the same wording", async () => {
    const user = userEvent.setup();
    const task = asksTask();
    decide.mockResolvedValueOnce(decided(task, "reformulate", { title: "Renovate the Bathroom.", formulation: task.formulation }));
    renderDialog(task);

    await user.click(decisionButton(/^Reformulate/));
    const field = screen.getByRole("textbox", { name: "New wording" });
    await user.clear(field);
    await user.type(field, "Renovate the Bathroom.");

    expect(screen.getByText("Only capitals or punctuation changed, so this is still the same wording and the clock keeps running.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Save anyway" }));

    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(lastToast()[0]).toBe("“Renovate the Bathroom.” saved; the clock keeps running");
    expect(onClose).toHaveBeenCalledWith(expect.objectContaining({ leftNext: false }));
  });

  it("020-FR-006 Find a first step shows what the notes will keep and saves only with text", async () => {
    const user = userEvent.setup();
    const task = asksTask();
    decide.mockResolvedValueOnce(decided(task, "first_step", { title: "Measure the bathroom walls" }));
    renderDialog(task);

    await user.click(decisionButton(/^Find a first step/));
    expect(screen.getByText("What's the very first thing you'd do?")).toBeInTheDocument();
    expect(screen.getByText("Was: Renovate the bathroom")).toBeInTheDocument();
    const field = screen.getByRole("textbox", { name: "First step" });
    expect(field).toHaveAttribute("placeholder", "Something you could start in 10 minutes");
    expect(screen.getByRole("button", { name: "Save first step" })).toBeDisabled();
    await user.type(field, "   {Enter}");
    expect(screen.getByRole("button", { name: "Save first step" })).toBeDisabled();
    expect(decide).not.toHaveBeenCalled();
    await user.clear(field);
    await user.type(field, "  Measure the bathroom walls ");
    await user.click(screen.getByRole("button", { name: "Save first step" }));

    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(decide).toHaveBeenCalledWith(
      "task-1",
      { type: "first_step", expected_revision: 7, formulation_id: "form_a", title: "Measure the bathroom walls" },
      expect.any(String)
    );
    expect(lastToast()[0]).toBe("First step saved: “Measure the bathroom walls”");
  });

  it("020-FR-006 Move to Waiting for asks who or what, and Back returns to the card with the reason kept", async () => {
    const user = userEvent.setup();
    const task = asksTask();
    decide.mockResolvedValueOnce(decided(task, "waiting", { state: "waiting", waiting_for: "Landlord" }));
    renderDialog(task);

    await user.click(screen.getByRole("button", { name: "Waiting on someone" }));
    await user.click(decisionButton(/^Move to Waiting for/));
    expect(screen.getByText("Who or what are you waiting for?")).toBeInTheDocument();
    expect(screen.getByText("It moves to Waiting for. The review checks in on it after 7 days.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Back" }));
    expect(screen.getByRole("button", { name: "Waiting on someone" })).toHaveAttribute("aria-pressed", "true");

    await user.click(decisionButton(/^Move to Waiting for/));
    expect(screen.getByRole("button", { name: "Move to Waiting for" })).toBeDisabled();
    await user.type(screen.getByRole("textbox", { name: "Waiting for" }), "Landlord");
    await user.click(screen.getByRole("button", { name: "Move to Waiting for" }));

    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(decide).toHaveBeenCalledWith(
      "task-1",
      { type: "waiting", expected_revision: 7, formulation_id: "form_a", stall_reason: "waiting_on_someone", waiting_for: "Landlord" },
      expect.any(String)
    );
    expect(lastToast()[0]).toBe("“Renovate the bathroom” moved to Waiting for");
  });

  it("020-FR-009 Keep 7 more days needs a reason and names the dates from today", async () => {
    const user = userEvent.setup();
    const task = asksTask();
    decide.mockResolvedValueOnce(decided(task, "extend", { formulation: { ...(task.formulation as NonNullable<TaskResponse["formulation"]>), extended_at: iso(0) } }));
    renderDialog(task);

    await user.click(decisionButton(/^Keep 7 more days/));
    const until = formatReviewDate(iso(7 * DAY));
    const parks = formatReviewDate(iso(14 * DAY));
    expect(screen.getByText("Why does this wording still fit?")).toBeInTheDocument();
    expect(screen.getByText(`Asks again on ${until}. If still undecided, it moves to Someday on ${parks}. You can do this once for this wording.`)).toBeInTheDocument();
    const keep = screen.getByRole("button", { name: `Keep until ${until}` });
    expect(keep).toBeDisabled();
    expect(keep).toHaveAccessibleDescription("Add a reason to continue");

    await user.type(screen.getByRole("textbox", { name: "Reason, required" }), "Starting after the landlord replies");
    expect(keep).toBeEnabled();
    expect(screen.queryByText("Add a reason to continue")).not.toBeInTheDocument();
    await user.click(keep);

    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(decide).toHaveBeenCalledWith(
      "task-1",
      { type: "extend", expected_revision: 7, formulation_id: "form_a", reason: "Starting after the landlord replies" },
      expect.any(String)
    );
    expect(lastToast()[0]).toBe(`“Renovate the bathroom” kept until ${until}`);
    expect(lastToast()[1]?.action?.accessibleLabel).toBe("Undo: Kept 7 more days Renovate the bathroom");
  });

  it("020-FR-009 an extended wording offers no second extension and says why", () => {
    renderDialog(asksTask({}, { extended_at: iso(-4 * DAY), extension_reason: "Waiting to measure the sink first" }));

    const decisions = within(screen.getByRole("group", { name: "Decisions" })).getAllByRole("button");
    expect(decisions).toHaveLength(6);
    expect(decisions[5]).toHaveTextContent("6");
    expect(screen.queryByRole("button", { name: /Keep 7 more days/ })).not.toBeInTheDocument();
    expect(screen.getByText("You've already kept this wording 7 more days once.")).toBeInTheDocument();
    expect(screen.getByText(`15 days in Next · Home · kept 7 more days on ${formatReviewDate(iso(-4 * DAY))}`)).toBeInTheDocument();
  });
});

describe("020-FR-006 decision dialog: keyboard", () => {
  it("020-FR-006 number keys pick the decision shown beside them, never inside a text field", async () => {
    const user = userEvent.setup();
    const task = asksTask();
    decide.mockResolvedValueOnce(decided(task, "complete", { state: "completed" }));
    renderDialog(task);

    await user.keyboard("3");
    expect(screen.getByRole("textbox", { name: "First step" })).toHaveFocus();
    await user.keyboard("1");
    expect(screen.getByRole("textbox", { name: "First step" })).toHaveValue("1");
    expect(decide).not.toHaveBeenCalled();
    await user.clear(screen.getByRole("textbox", { name: "First step" }));
    await user.click(screen.getByRole("button", { name: "Back" }));

    await user.keyboard("9");
    await user.keyboard("{Control>}1{/Control}");
    expect(decide).not.toHaveBeenCalled();
    await user.keyboard("1");
    await waitFor(() => expect(decide).toHaveBeenCalledWith("task-1", { type: "complete", expected_revision: 7 }, expect.any(String)));
  });

  it("020-FR-009 key 7 does nothing when the extension is not offered", async () => {
    const user = userEvent.setup();
    renderDialog(asksTask({}, { extended_at: iso(-4 * DAY), extension_reason: "Sink first" }));
    screen.getByRole("heading", { name: "Renovate the bathroom" }).focus();
    await user.keyboard("7");
    expect(screen.getByRole("group", { name: "Decisions" })).toBeInTheDocument();
    await user.keyboard("6");
    await waitFor(() => expect(decide).toHaveBeenCalledWith("task-1", { type: "cancel", expected_revision: 7 }, expect.any(String)));
  });

  it("020-FR-010 Escape on the card closes with no change; Close and the scrim do the same", async () => {
    const user = userEvent.setup();
    const first = renderDialog(asksTask());
    await user.keyboard("{Escape}");
    expect(onClose).toHaveBeenLastCalledWith({ kind: "closed" });
    first.unmount();
    await settleHistory();

    const second = renderDialog(asksTask());
    await user.click(screen.getByRole("button", { name: "Close" }));
    expect(onClose).toHaveBeenCalledTimes(2);
    second.unmount();
    await settleHistory();

    renderDialog(asksTask());
    fireEvent.click(screen.getByTestId("decision-dialog-scrim"));
    expect(onClose).toHaveBeenCalledTimes(3);
    expect(decide).not.toHaveBeenCalled();
  });

  it("020-FR-052 Escape inside a clean form returns to the card; inside a dirty form it asks first, focus on Keep editing", async () => {
    const user = userEvent.setup();
    renderDialog(asksTask());

    await user.click(decisionButton(/^Find a first step/));
    await user.keyboard("{Escape}");
    expect(screen.getByRole("group", { name: "Decisions" })).toBeInTheDocument();
    expect(onClose).not.toHaveBeenCalled();

    await user.click(decisionButton(/^Find a first step/));
    await user.type(screen.getByRole("textbox", { name: "First step" }), "Measure");
    await user.keyboard("{Escape}");
    const confirm = screen.getByRole("alertdialog", { name: "Discard your new wording?" });
    expect(within(confirm).getByText("It hasn't been saved.")).toBeInTheDocument();
    expect(within(confirm).getByRole("button", { name: "Keep editing" })).toHaveFocus();

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "First step" })).toHaveValue("Measure");
    expect(screen.getByRole("textbox", { name: "First step" })).toHaveFocus();

    await user.keyboard("{Escape}");
    await user.click(screen.getByRole("button", { name: "Discard" }));
    expect(screen.getByRole("group", { name: "Decisions" })).toBeInTheDocument();
    expect(loadReviewDraft(scope, { kind: "task", taskId: "task-1", formulationId: "form_a" })).toBeNull();
    expect(onClose).not.toHaveBeenCalled();
  });

  it("020-FR-052 Close with unsaved text asks first; Keep editing stays, Discard closes", async () => {
    const user = userEvent.setup();
    renderDialog(asksTask());
    await user.click(decisionButton(/^Reformulate/));
    await user.type(screen.getByRole("textbox", { name: "New wording" }), " today");

    await user.click(screen.getByRole("button", { name: "Close" }));
    await user.click(screen.getByRole("button", { name: "Keep editing" }));
    expect(onClose).not.toHaveBeenCalled();
    expect(screen.getByRole("textbox", { name: "New wording" })).toHaveValue("Renovate the bathroom today");

    fireEvent.click(screen.getByTestId("decision-dialog-scrim"));
    await user.click(screen.getByRole("button", { name: "Discard" }));
    expect(onClose).toHaveBeenCalledWith({ kind: "closed" });
  });

  it("020-FR-006 traps focus inside the dialog and inside the confirmation", async () => {
    const user = userEvent.setup();
    renderDialog(asksTask());

    const close = screen.getByRole("button", { name: "Close" });
    const last = decisionButton(/^Keep 7 more days/);
    last.focus();
    await user.tab();
    expect(close).toHaveFocus();
    await user.tab({ shift: true });
    expect(last).toHaveFocus();
    screen.getByRole("heading", { name: "Renovate the bathroom" }).focus();
    await user.tab({ shift: true });
    expect(last).toHaveFocus();

    await user.click(decisionButton(/^Reformulate/));
    await user.type(screen.getByRole("textbox", { name: "New wording" }), "!");
    await user.click(close);
    const keep = screen.getByRole("button", { name: "Keep editing" });
    const discard = screen.getByRole("button", { name: "Discard" });
    await user.tab();
    expect(discard).toHaveFocus();
    await user.tab();
    expect(keep).toHaveFocus();
    await user.tab({ shift: true });
    expect(discard).toHaveFocus();
    await user.keyboard("a");
    expect(screen.getByRole("alertdialog")).toBeInTheDocument();
  });
});

describe("020-FR-011 decision dialog: refusals and failures", () => {
  it("020-FR-011 a stale decision applies nothing and shows the current version beside the old one", async () => {
    const user = userEvent.setup();
    const task = asksTask();
    const now = asksTask({ title: "Get 3 quotes for the bathroom", revision: 9 }, { id: "form_b" });
    decide
      .mockRejectedValueOnce(new ApiError("Conflict", 409, { message: "stale", detail: { resource: "task", id: "task-1" } }, "corr_stale"))
      .mockResolvedValueOnce(decided(now, "someday", { state: "someday" }));
    getTask.mockResolvedValueOnce(now);
    renderDialog(task);

    await user.click(screen.getByRole("button", { name: "Unclear" }));
    await user.click(decisionButton(/^Release to Someday/));

    expect(await screen.findByRole("heading", { name: "Task changed elsewhere" })).toBeInTheDocument();
    expect(screen.getByText("Nothing was applied. Here's the current version. Decide again if it still needs it.")).toBeInTheDocument();
    expect(screen.getByText("Renovate the bathroom", { selector: "dd" })).toBeInTheDocument();
    expect(screen.getByText("Get 3 quotes for the bathroom", { selector: "dd" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Unclear" })).toHaveAttribute("aria-pressed", "true");

    await user.click(decisionButton(/^Release to Someday/));
    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(decide).toHaveBeenLastCalledWith(
      "task-1",
      { type: "someday", expected_revision: 9, formulation_id: "form_b", stall_reason: "unclear" },
      expect.any(String)
    );
  });

  it("020-FR-011 a stale answer puts the current task into the list and detail caches, so closing cannot reopen the obsolete card", async () => {
    const user = userEvent.setup();
    const task = asksTask();
    const now = asksTask({ title: "Get 3 quotes for the bathroom", revision: 9 }, { id: "form_b" });
    decide.mockRejectedValueOnce(new ApiError("Conflict", 409, { message: "stale", detail: { resource: "task", id: "task-1" } }, "corr_stale"));
    getTask.mockResolvedValueOnce(now);
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const list = [...taskKeys.lists(), { state: "next" }];
    client.setQueryData(taskKeys.detail("task-1"), task);
    client.setQueryData(list, { pages: [{ items: [task] }], pageParams: [null] });
    renderDialog(task, { client });

    await user.click(decisionButton(/^Release to Someday/));
    await screen.findByRole("heading", { name: "Task changed elsewhere" });

    expect(client.getQueryData(taskKeys.detail("task-1"))).toEqual(now);
    expect(client.getQueryData(list)).toEqual({ pages: [{ items: [now] }], pageParams: [null] });
  });

  it("020-FR-011 a stale answer whose current task cannot be read marks the task caches for a refetch", async () => {
    const user = userEvent.setup();
    const task = asksTask();
    decide.mockRejectedValueOnce(new ApiError("Conflict", 409, { message: "stale", detail: { resource: "task", id: "task-1" } }, "corr_stale"));
    getTask.mockRejectedValueOnce(new Error("offline"));
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    client.setQueryData(taskKeys.detail("task-1"), task);
    renderDialog(task, { client });

    await user.click(decisionButton(/^Release to Someday/));
    await screen.findByRole("heading", { name: "Task changed elsewhere" });

    expect(client.getQueryState(taskKeys.detail("task-1"))?.isInvalidated).toBe(true);
  });

  it("020-FR-011 after a stale answer the heading and the dialog's name show the current title", async () => {
    const user = userEvent.setup();
    const now = asksTask({ title: "Get 3 quotes for the bathroom", revision: 9 }, { id: "form_b" });
    decide.mockRejectedValueOnce(new ApiError("Conflict", 409, { message: "stale", detail: { resource: "task", id: "task-1" } }, "corr_stale"));
    getTask.mockResolvedValueOnce(now);
    renderDialog(asksTask());

    await user.click(decisionButton(/^Release to Someday/));

    expect(await screen.findByRole("heading", { name: "Task changed elsewhere" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 2, name: "Get 3 quotes for the bathroom" })).toBeInTheDocument();
    expect(screen.getByRole("dialog", { name: "Get 3 quotes for the bathroom" })).toBeInTheDocument();
    expect(screen.queryByRole("dialog", { name: "Renovate the bathroom" })).not.toBeInTheDocument();
  });

  it("020-FR-011 a stale card whose current version cannot be loaded keeps the title it showed", async () => {
    const user = userEvent.setup();
    decide.mockRejectedValueOnce(new ApiError("Conflict", 409, { message: "stale", detail: { resource: "task", id: "task-1" } }, "corr_stale"));
    getTask.mockRejectedValueOnce(new Error("offline"));
    renderDialog(asksTask());

    await user.click(decisionButton(/^Release to Someday/));

    expect(await screen.findByRole("heading", { name: "Task changed elsewhere" })).toBeInTheDocument();
    expect(screen.getByRole("dialog", { name: "Renovate the bathroom" })).toBeInTheDocument();
  });

  it("020-FR-011 a stale card whose task no longer asks says so and keeps only Close", async () => {
    const user = userEvent.setup();
    decide.mockRejectedValueOnce(new ApiError("Conflict", 409, null, "corr_stale"));
    getTask.mockResolvedValueOnce(asksTask({ state: "waiting", revision: 9, formulation: null }));
    renderDialog(asksTask());

    await user.click(decisionButton(/^Done/));

    expect(await screen.findByText("This task no longer asks for a decision. You can close the card.")).toBeInTheDocument();
    expect(screen.queryByRole("group", { name: "Decisions" })).not.toBeInTheDocument();
    expect(screen.queryByText("Was")).toBeInTheDocument();
  });

  it("020-FR-011 a stale card whose current version cannot be loaded still applies nothing", async () => {
    const user = userEvent.setup();
    decide.mockRejectedValueOnce(new ApiError("Conflict", 409, null, "corr_stale"));
    getTask.mockRejectedValueOnce(new ApiError("Gone", 404, null, "corr_gone"));
    renderDialog(asksTask());

    await user.click(decisionButton(/^Done/));

    expect(await screen.findByRole("heading", { name: "Task changed elsewhere" })).toBeInTheDocument();
    expect(screen.getByText("This task no longer asks for a decision. You can close the card.")).toBeInTheDocument();
    expect(screen.queryByText("Was")).not.toBeInTheDocument();
  });

  it("020-FR-045 a failed save changes nothing, shows the Ref and retries with the same key", async () => {
    const user = userEvent.setup();
    const task = asksTask();
    decide
      .mockRejectedValueOnce(new ApiError("Couldn't reach Brain Buddy", 0, null, "corr_2b9e41d7"))
      .mockResolvedValueOnce(decided(task, "complete", { state: "completed" }));
    renderDialog(task);

    await user.click(decisionButton(/^Done/));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Couldn't save your decision. Nothing was changed.");
    expect(alert).toHaveTextContent("Ref corr_2b9e41d7");
    await user.click(within(alert).getByRole("button", { name: "Retry" }));

    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(decide.mock.calls[1][2]).toBe(decide.mock.calls[0][2]);
    expect(decide.mock.calls[1][1]).toEqual(decide.mock.calls[0][1]);
  });

  it("020-FR-045 020-FR-052 editing the text after a failed save clears the failure, so Retry never sends the old text", async () => {
    const user = userEvent.setup();
    const task = asksTask();
    decide
      .mockRejectedValueOnce(new ApiError("Couldn't reach Brain Buddy", 0, null, "corr_old"))
      .mockResolvedValueOnce(decided(task, "first_step", { title: "Measure the walls" }));
    renderDialog(task);
    await user.click(decisionButton(/^Find a first step/));
    await user.type(screen.getByRole("textbox", { name: "First step" }), "Measure");
    await user.click(screen.getByRole("button", { name: "Save first step" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Ref corr_old");

    await user.type(screen.getByRole("textbox", { name: "First step" }), " the walls");

    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Save first step" }));
    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(decide.mock.calls[1][1]).toMatchObject({ title: "Measure the walls" });
    expect(decide.mock.calls[1][2]).not.toBe(decide.mock.calls[0][2]);
  });

  it("020-FR-040 020-FR-045 Retry is disabled while offline", async () => {
    const user = userEvent.setup();
    const online = vi.spyOn(navigator, "onLine", "get").mockReturnValue(true);
    decide.mockRejectedValueOnce(new ApiError("Couldn't reach Brain Buddy", 0, null, "corr_off"));
    renderDialog(asksTask());
    await user.click(decisionButton(/^Done/));
    const alert = await screen.findByRole("alert");

    online.mockReturnValue(false);
    act(() => {
      window.dispatchEvent(new Event("offline"));
    });

    expect(within(alert).getByRole("button", { name: "Retry" })).toBeDisabled();
    online.mockReturnValue(true);
    act(() => {
      window.dispatchEvent(new Event("online"));
    });
    expect(within(alert).getByRole("button", { name: "Retry" })).toBeEnabled();
  });

  it("020-FR-045 a failure without a reference shows no empty Ref line", async () => {
    const user = userEvent.setup();
    decide.mockRejectedValueOnce(new Error("socket hang up"));
    renderDialog(asksTask());

    await user.click(decisionButton(/^Done/));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Couldn't save your decision. Nothing was changed.");
    expect(alert).not.toHaveTextContent(/Ref/);
  });

  it.each([
    ["applied", (task: TaskResponse) => Promise.resolve(decided(task, "first_step", { title: "Measure" }))],
    ["refused", () => Promise.reject(new ApiError("Server Error", 500, null, "corr_late"))]
  ])("020-FR-048 020-FR-042 a decision answered (%s) after the session switched account shows, closes and discards nothing", async (_label, answer) => {
    const user = userEvent.setup();
    const task = asksTask();
    let release: () => void = () => undefined;
    decide.mockImplementationOnce(() => new Promise((resolve, reject) => {
      release = () => {
        answer(task).then(resolve, reject);
      };
    }));
    renderDialog(task);
    await user.click(decisionButton(/^Find a first step/));
    await user.type(screen.getByRole("textbox", { name: "First step" }), "Measure");
    await user.click(screen.getByRole("button", { name: "Save first step" }));
    await waitFor(() => expect(decide).toHaveBeenCalledTimes(1));

    act(() => {
      useAuthStore.setState({ user: { id: "user-2", email: "b@example.test" }, status: "authed" });
    });
    await act(async () => release());
    await act(() => new Promise<void>((resolve) => setTimeout(resolve, 20)));

    expect(notify).not.toHaveBeenCalled();
    expect(onClose).not.toHaveBeenCalled();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(loadReviewDraft(scope, { kind: "task", taskId: "task-1", formulationId: "form_a" })?.text).toBe("Measure");
  });

  it("020-FR-045 a decision the task's list no longer allows says so with the Ref and no retry", async () => {
    const user = userEvent.setup();
    decide.mockRejectedValueOnce(new ApiError("Bad", 400, { message: "x", detail: { reason: "decision_not_allowed" } }, "corr_7f3a"));
    renderDialog(asksTask());

    await user.click(decisionButton(/^Release to Someday/));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("This decision isn't available for this task's current list. Nothing was changed.");
    expect(alert).toHaveTextContent("Ref corr_7f3a");
    expect(within(alert).queryByRole("button", { name: "Retry" })).not.toBeInTheDocument();
  });

  it("020-FR-045 notes that would grow too long keep the first-step form open with the typed step", async () => {
    const user = userEvent.setup();
    decide.mockRejectedValueOnce(new ApiError("Bad", 400, { message: "x", detail: { reason: "details_too_long" } }, "corr_long"));
    renderDialog(asksTask());

    await user.click(decisionButton(/^Find a first step/));
    await user.type(screen.getByRole("textbox", { name: "First step" }), "Measure");
    await user.click(screen.getByRole("button", { name: "Save first step" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("The notes would be too long with the old title added. Shorten the notes, then try again. Nothing was changed.");
    expect(alert).toHaveTextContent("Ref corr_long");
    expect(screen.getByRole("textbox", { name: "First step" })).toHaveValue("Measure");
  });

  it("020-FR-040 offline: decisions are disabled with the reason, reasons still work", async () => {
    const user = userEvent.setup();
    vi.spyOn(navigator, "onLine", "get").mockReturnValue(false);
    renderDialog(asksTask());

    expect(screen.getByText("You're offline. Decisions need a connection on the web.")).toBeInTheDocument();
    for (const button of within(screen.getByRole("group", { name: "Decisions" })).getAllByRole("button")) {
      expect(button).toBeDisabled();
    }
    await user.click(screen.getByRole("button", { name: "Too big" }));
    expect(screen.getByRole("button", { name: "Too big" })).toHaveAttribute("aria-pressed", "true");
    await user.keyboard("1");
    expect(decide).not.toHaveBeenCalled();
  });

  it("020-FR-040 going offline with a form open disables its save", async () => {
    const user = userEvent.setup();
    const online = vi.spyOn(navigator, "onLine", "get").mockReturnValue(true);
    renderDialog(asksTask());
    await user.click(decisionButton(/^Find a first step/));
    await user.type(screen.getByRole("textbox", { name: "First step" }), "Measure");

    online.mockReturnValue(false);
    act(() => {
      window.dispatchEvent(new Event("offline"));
    });

    expect(screen.getByRole("button", { name: "Save first step" })).toBeDisabled();
    expect(screen.getByText("You're offline. Decisions need a connection on the web.")).toBeInTheDocument();
  });
});

describe("020-FR-005 decision dialog: the third stalled wording", () => {
  it("020-FR-005 offers Someday gently, without the canvas when Thinking Mode is off", async () => {
    const user = userEvent.setup();
    const task = asksTask({}, { consecutive_stalled: 2 });
    decide.mockResolvedValueOnce(decided(task, "someday", { state: "someday" }));
    renderDialog(task);

    expect(screen.getByText("This is the third wording in a row that has stalled. Sometimes the task isn't the problem. It may help to set it aside, or to look at what's underneath.")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Think it through" })).not.toBeInTheDocument();
    await user.click(within(screen.getByRole("region", { name: "Third stalled wording" })).getByRole("button", { name: "Release to Someday" }));

    await waitFor(() => expect(decide).toHaveBeenCalledWith("task-1", { type: "someday", expected_revision: 7, formulation_id: "form_a" }, expect.any(String)));
  });

  it("020-FR-005 links to the thinking canvas only when crt_canvas is effective", () => {
    act(() => {
      useAuthStore.setState({ user: { id: "user-1", email: "max@example.test", feature_flags: { crt_canvas: true } } });
    });
    renderDialog(asksTask({}, { consecutive_stalled: 3 }));
    expect(screen.getByRole("link", { name: "Think it through" })).toHaveAttribute("href", "/crt");
  });

  it("020-FR-005 020-FR-052 Think it through on a clean card replaces the dialog's history entry, so one Back returns to the list", async () => {
    const user = userEvent.setup();
    act(() => {
      useAuthStore.setState({ user: { id: "user-1", email: "max@example.test", feature_flags: { crt_canvas: true } } });
    });
    window.history.replaceState(null, "", "/tasks/next");
    // The open state lives above the routes, so coming back to the list does not reopen the card.
    function App(): React.JSX.Element {
      const [open, setOpen] = useState(true);
      return (
        <BrowserRouter>
          <Routes>
            <Route
              path="/tasks/next"
              element={
                <>
                  <h1>Next actions</h1>
                  {open ? <DecisionDialog task={asksTask({}, { consecutive_stalled: 3 })} projectName="Home" onClose={() => setOpen(false)} /> : null}
                </>
              }
            />
            <Route path="/crt" element={<h1>Thinking canvas</h1>} />
          </Routes>
        </BrowserRouter>
      );
    }
    render(
      <QueryClientProvider client={new QueryClient()}>
        <ShellToastContext.Provider value={notify}>
          <App />
        </ShellToastContext.Provider>
      </QueryClientProvider>
    );
    expect((window.history.state as Record<string, unknown>).bbReviewDialog).toEqual(expect.any(String));

    await user.click(screen.getByRole("link", { name: "Think it through" }));

    expect(await screen.findByRole("heading", { name: "Thinking canvas" })).toBeInTheDocument();
    act(() => window.history.back());
    expect(await screen.findByRole("heading", { name: "Next actions" })).toBeInTheDocument();
    expect(window.location.pathname).toBe("/tasks/next");
    expect((window.history.state as Record<string, unknown> | null)?.bbReviewDialog).toBeUndefined();
  });
});

describe("020-FR-048 decision dialog: Undo", () => {
  async function decideAndGetUndo(task: TaskResponse, after: Partial<TaskResponse>, client?: QueryClient) {
    const user = userEvent.setup();
    decide.mockResolvedValueOnce(decided(task, "someday", after));
    renderDialog(task, client ? { client } : undefined);
    await user.click(decisionButton(/^Release to Someday/));
    await waitFor(() => expect(onClose).toHaveBeenCalled());
    const action = lastToast()[1]?.action;
    if (!action) throw new Error("no Undo offered");
    return action;
  }

  it("020-FR-048 Undo asks the server with the decided revision and puts its task back in the caches", async () => {
    const task = asksTask();
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const action = await decideAndGetUndo(task, { state: "someday" }, client);
    undoDecision.mockResolvedValueOnce({ task: { ...task, revision: 9 }, undone_decision_id: "decision_1", deleted_task_id: null, session_counts: null });

    await act(async () => action.onAction());

    expect(undoDecision).toHaveBeenCalledWith("decision_1", { expected_task_revision: 8 }, expect.any(String));
    expect(client.getQueryData(taskKeys.detail("task-1"))).toEqual(expect.objectContaining({ state: "next", revision: 9 }));
    expect(lastToast()).toEqual(["“Renovate the bathroom” is back as it was"]);
  });

  it.each([
    ["applied", (release: (task: TaskResponse) => void, _fail: (error: unknown) => void, task: TaskResponse) => release({ ...task, revision: 9 })],
    ["refused", (_release: (task: TaskResponse) => void, fail: (error: unknown) => void) => fail(new ApiError("Server Error", 500, null, "corr_late"))]
  ])("020-FR-048 an Undo answered (%s) after the account signed out and another signed in writes and says nothing", async (_label, settle) => {
    const task = asksTask();
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const action = await decideAndGetUndo(task, { state: "someday" }, client);
    let release: (task: TaskResponse) => void = () => undefined;
    let fail: (error: unknown) => void = () => undefined;
    undoDecision.mockReturnValueOnce(new Promise((resolve, reject) => {
      release = (restored) => resolve({ task: restored, undone_decision_id: "decision_1", deleted_task_id: null, session_counts: null });
      fail = reject;
    }));
    const toastsBefore = notify.mock.calls.length;

    let undoing: Promise<void> = Promise.resolve();
    act(() => {
      undoing = Promise.resolve(action.onAction());
    });
    act(() => useAuthStore.setState({ user: { id: "user-2", email: "b@example.test" }, status: "authed" }));
    const scopeB = { accountId: "user-2", apiOrigin: scope.apiOrigin };
    client.setQueryData(taskKeys.detail(task.id, scopeB), { ...task, title: "B's copy" });
    await act(async () => {
      settle(release, fail, task);
      await undoing;
      await new Promise((resolve) => setTimeout(resolve, 0));
    });

    expect(client.getQueryData(taskKeys.detail(task.id, scopeB))).toEqual({ ...task, title: "B's copy" });
    expect(client.getQueryState(taskKeys.detail(task.id, scopeB))?.isInvalidated).toBe(false);
    expect(notify.mock.calls.length).toBe(toastsBefore);
  });

  it("020-FR-048 an Undo that can no longer apply says where the task is now, with the Ref", async () => {
    const task = asksTask();
    const action = await decideAndGetUndo(task, { state: "someday" });
    undoDecision.mockRejectedValueOnce(new ApiError("Conflict", 409, { message: "x", detail: { reason: "undo_unavailable" } }, "corr_undo"));
    getTask.mockResolvedValueOnce({ ...task, state: "someday", revision: 10 });

    await act(async () => action.onAction());

    expect(lastToast()).toEqual(["Couldn't undo: “Renovate the bathroom” changed on another device. It's in Someday / maybe now. Ref corr_undo"]);
  });

  it("020-FR-048 falls back to the decided list when the current one cannot be read", async () => {
    const task = asksTask();
    const action = await decideAndGetUndo(task, { state: "someday" });
    undoDecision.mockRejectedValueOnce(new ApiError("Conflict", 409, null, "corr_undo2"));
    getTask.mockRejectedValueOnce(new Error("offline"));

    await act(async () => action.onAction());

    expect(lastToast()).toEqual(["Couldn't undo: “Renovate the bathroom” changed on another device. It's in Someday / maybe now. Ref corr_undo2"]);
  });

  it("020-FR-048 an Undo that was already applied elsewhere is quietly accepted", async () => {
    const task = asksTask();
    const action = await decideAndGetUndo(task, { state: "someday" });
    const toastsBefore = notify.mock.calls.length;
    undoDecision.mockRejectedValueOnce(new ApiError("Not found", 404, { message: "x", detail: { resource: "review_decision", id: "decision_1" } }, "corr_404"));

    await act(async () => action.onAction());

    expect(notify.mock.calls.length).toBe(toastsBefore);
  });

  it.each([
    ["the backend's own resource name", { resource: "Review decision", id: "decision_1" }],
    ["no id", { resource: "Review decision" }],
    ["any casing", { resource: "REVIEW_DECISION", id: "decision_1" }]
  ])("020-FR-048 an Undo answered 404 for the decision (%s) is the undo already applied, and stays quiet", async (_label, detail) => {
    const task = asksTask();
    const action = await decideAndGetUndo(task, { state: "someday" });
    const toastsBefore = notify.mock.calls.length;
    undoDecision.mockRejectedValueOnce(new ApiError("Not found", 404, { message: "x", detail }, "corr_404"));

    await act(async () => action.onAction());

    expect(notify.mock.calls.length).toBe(toastsBefore);
  });

  it.each([
    ["a deleted task", { message: "x", detail: { resource: "Task", id: "task-1" } }],
    ["another decision", { message: "x", detail: { resource: "Review decision", id: "decision_other" } }],
    ["another resource", { message: "x", detail: { resource: "Project", id: "project-home" } }],
    ["no detail", { message: "Not found" }],
    ["no body", null]
  ])("020-FR-048 020-FR-045 an Undo answered 404 for %s is a failure with the Ref, not a success", async (_label, payload) => {
    const task = asksTask();
    const action = await decideAndGetUndo(task, { state: "someday" });
    undoDecision.mockRejectedValueOnce(new ApiError("Not found", 404, payload, "corr_gone"));

    await act(async () => action.onAction());

    expect(lastToast()).toEqual(["Couldn't undo. Nothing was changed. Ref corr_gone"]);
  });

  it("020-FR-048 an Undo that fails for another reason changes nothing and shows the Ref", async () => {
    const task = asksTask();
    const action = await decideAndGetUndo(task, { state: "someday" });
    undoDecision.mockRejectedValueOnce(new ApiError("Unavailable", 0, null, "corr_net"));

    await act(async () => action.onAction());

    expect(lastToast()).toEqual(["Couldn't undo. Nothing was changed. Ref corr_net"]);
  });

  it("020-FR-048 020-FR-045 an Undo failure without a reference never shows \"Ref undefined\"", async () => {
    const task = asksTask();
    const action = await decideAndGetUndo(task, { state: "someday" });
    undoDecision.mockRejectedValueOnce(new Error("socket hang up"));

    await act(async () => action.onAction());

    expect(lastToast()).toEqual(["Couldn't undo. Nothing was changed."]);
    cleanup();
    await settleHistory();

    const second = await decideAndGetUndo(task, { state: "someday" });
    undoDecision.mockRejectedValueOnce(new ApiError("Conflict", 409, null));
    getTask.mockResolvedValueOnce({ ...task, state: "someday", revision: 10 });

    await act(async () => second.onAction());

    expect(lastToast()).toEqual(["Couldn't undo: “Renovate the bathroom” changed on another device. It's in Someday / maybe now."]);
  });
});

describe("020-FR-052 decision dialog: drafts and the leave guard", () => {
  it("020-FR-052 keeps typed text as a draft for this wording and restores it when the dialog reopens", async () => {
    const user = userEvent.setup();
    const first = renderDialog(asksTask());
    await user.click(decisionButton(/^Keep 7 more days/));
    await user.type(screen.getByRole("textbox", { name: "Reason, required" }), "Landlord replies Monday");
    expect(loadReviewDraft(scope, { kind: "task", taskId: "task-1", formulationId: "form_a" })).toEqual(
      expect.objectContaining({ form: "extend", text: "Landlord replies Monday" })
    );
    first.unmount();
    await settleHistory();

    renderDialog(asksTask());
    expect(screen.getByRole("textbox", { name: "Reason, required" })).toHaveValue("Landlord replies Monday");
    expect(screen.getByText("Your unsaved text is back.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Clear" }));
    expect(screen.getByRole("textbox", { name: "Reason, required" })).toHaveValue("");
    expect(screen.queryByText("Your unsaved text is back.")).not.toBeInTheDocument();
    expect(loadReviewDraft(scope, { kind: "task", taskId: "task-1", formulationId: "form_a" })).toBeNull();
  });

  it("020-FR-052 restores a reformulation draft into its prefilled form, and drops drafts of an older wording", async () => {
    saveReviewDraft(scope, { kind: "task", taskId: "task-1", formulationId: "form_a" }, { form: "reformulate", text: "Call three builders" });
    saveReviewDraft(scope, { kind: "task", taskId: "task-1", formulationId: "form_old" }, { form: "waiting", text: "stale" });
    const user = userEvent.setup();
    renderDialog(asksTask());

    expect(screen.getByRole("textbox", { name: "New wording" })).toHaveValue("Call three builders");
    expect(window.localStorage.getItem(reviewDraftKey(scope, { kind: "task", taskId: "task-1", formulationId: "form_old" }))).toBeNull();
    await user.click(screen.getByRole("button", { name: "Clear" }));
    expect(screen.getByRole("textbox", { name: "New wording" })).toHaveValue("Renovate the bathroom");
  });

  it("020-FR-052 a saved decision removes its draft", async () => {
    const user = userEvent.setup();
    const task = asksTask();
    decide.mockResolvedValueOnce(decided(task, "waiting", { state: "waiting" }));
    renderDialog(task);
    await user.click(decisionButton(/^Move to Waiting for/));
    await user.type(screen.getByRole("textbox", { name: "Waiting for" }), "Anna");
    await user.click(screen.getByRole("button", { name: "Move to Waiting for" }));
    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(window.localStorage.length).toBe(0);
  });

  it("020-FR-052 browser Back closes a clean dialog like Close", async () => {
    renderDialog(asksTask());
    act(() => window.history.back());
    await waitFor(() => expect(onClose).toHaveBeenCalledWith({ kind: "closed" }));
  });

  it("020-FR-052 browser Back with unsaved text asks first; Keep editing keeps the dialog and its entry", async () => {
    const user = userEvent.setup();
    const pushState = vi.spyOn(window.history, "pushState");
    renderDialog(asksTask());
    await user.click(decisionButton(/^Find a first step/));
    await user.type(screen.getByRole("textbox", { name: "First step" }), "Measure");

    act(() => window.history.back());
    const keep = await screen.findByRole("button", { name: "Keep editing" });
    await user.click(keep);
    expect(pushState).toHaveBeenCalledTimes(2);
    expect(onClose).not.toHaveBeenCalled();

    act(() => window.history.back());
    await user.click(await screen.findByRole("button", { name: "Discard" }));
    expect(onClose).toHaveBeenCalledWith({ kind: "closed" });
  });

  it("020-FR-052 browser Back, then Escape on the confirmation, keeps the guard: a second Back asks again", async () => {
    const user = userEvent.setup();
    const pushState = vi.spyOn(window.history, "pushState");
    renderDialog(asksTask());
    await user.click(decisionButton(/^Find a first step/));
    await user.type(screen.getByRole("textbox", { name: "First step" }), "Measure");

    act(() => window.history.back());
    await screen.findByRole("button", { name: "Keep editing" });
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "First step" })).toHaveFocus();
    expect(pushState).toHaveBeenCalledTimes(2);

    act(() => window.history.back());
    expect(await screen.findByRole("alertdialog", { name: "Discard your new wording?" })).toBeInTheDocument();
    expect(onClose).not.toHaveBeenCalled();
    expect(screen.getByRole("textbox", { name: "First step" })).toHaveValue("Measure");
  });

  it("020-FR-052 020-FR-042 drafts stay under the account the dialog was opened for, even if the session changes under it", async () => {
    const user = userEvent.setup();
    renderDialog(asksTask());
    await user.click(decisionButton(/^Find a first step/));
    await user.type(screen.getByRole("textbox", { name: "First step" }), "Mea");

    act(() => {
      useAuthStore.setState({ user: { id: "user-2", email: "other@example.test" }, status: "authed" });
    });
    await user.type(screen.getByRole("textbox", { name: "First step" }), "sure");

    const target = { kind: "task", taskId: "task-1", formulationId: "form_a" } as const;
    expect(loadReviewDraft({ ...scope, accountId: "user-2" }, target)).toBeNull();
    expect(loadReviewDraft(scope, target)?.text).toBe("Measure");
  });

  it("020-FR-052 an in-app link with unsaved text asks first, and Discard follows it", async () => {
    const user = userEvent.setup();
    renderDialog(asksTask());
    await user.click(decisionButton(/^Find a first step/));
    await user.type(screen.getByRole("textbox", { name: "First step" }), "Measure");

    fireEvent.click(screen.getByRole("link", { name: "Home project" }));
    expect(screen.getByTestId("location")).toHaveTextContent("/tasks/next");
    await user.click(screen.getByRole("button", { name: "Discard" }));

    expect(onClose).toHaveBeenCalledWith({ kind: "closed" });
    expect(screen.getByTestId("location")).toHaveTextContent("/projects/project-home");
  });
});
