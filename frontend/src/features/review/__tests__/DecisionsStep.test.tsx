import { onlineManager } from "@tanstack/react-query";
import { act, cleanup, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, apiClient } from "../../../api/client";
import { reviewApi, type DecisionResponse, type ReviewQueue } from "../../../api/review";
import type { TaskResponse } from "../../../api/taskTypes";
import { DecisionsStep } from "../steps/DecisionsStep";
import { askingTask, iso, lastToast, notify, renderInRun, signIn } from "./reviewKit";

vi.mock("../../../api/review", async () => {
  const actual = await vi.importActual<typeof import("../../../api/review")>("../../../api/review");
  return { ...actual, reviewApi: { ...actual.reviewApi, getQueue: vi.fn(), decide: vi.fn(), undoDecision: vi.fn() } };
});
vi.mock("../../../api/client", async () => {
  const actual = await vi.importActual<typeof import("../../../api/client")>("../../../api/client");
  return { ...actual, apiClient: { ...actual.apiClient, getTask: vi.fn(), listProjects: vi.fn() } };
});

const getQueue = vi.mocked(reviewApi.getQueue);
const decide = vi.mocked(reviewApi.decide);
const undoDecision = vi.mocked(reviewApi.undoDecision);

const bathroom = askingTask("task_bath", "Renovate the bathroom", { project_id: "project-home" });
const cv = askingTask("task_cv", "Update the CV");
const garage = askingTask("task_garage", "Clean out the garage");
const bathroomClock = bathroom.formulation as NonNullable<TaskResponse["formulation"]>;
const queue = (items: TaskResponse[]): ReviewQueue => ({ items, meta: {} });

function decided(task: TaskResponse, type: string, after: Partial<TaskResponse>): DecisionResponse {
  return {
    decision: { id: `decision_${task.id}`, type, task_id: task.id, session_id: "review_1", decided_at: iso(0), substantive: null, stall_reason: null, ai_use: "none", yielded_auto_park: false },
    task: { ...task, revision: task.revision + 1, ...after },
    created_task: null,
    receipt: null,
    session_counts: null
  };
}

const card = (title: string) => screen.getByRole("region", { name: title });
const decisionButton = (name: RegExp | string) => within(screen.getByRole("group", { name: "Decisions" })).getByRole("button", { name });

beforeEach(() => {
  window.localStorage.clear();
  signIn();
  vi.mocked(apiClient.listProjects).mockResolvedValue([{ id: "project-home", name: "Home", color: null, state: "active", revision: 1, open_task_count: 3 }]);
});

afterEach(() => {
  cleanup();
  onlineManager.setOnline(true);
  vi.restoreAllMocks();
  getQueue.mockReset();
  decide.mockReset();
  undoDecision.mockReset();
  notify.mockReset();
  window.localStorage.clear();
});

describe("020-FR-034 Decisions step: the card inline", () => {
  it("020-FR-034 shows the first card in place, without a dialog or Close, with the earliest asking first", async () => {
    getQueue.mockResolvedValueOnce(queue([bathroom, cv, garage]));
    renderInRun(<DecisionsStep />);

    expect(await screen.findByRole("region", { name: "Renovate the bathroom" })).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Close" })).not.toBeInTheDocument();
    expect(screen.getByText("1 of 3 · earliest-asking first")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Renovate the bathroom" })).toBeInTheDocument();
    expect(within(screen.getByRole("group", { name: "Decisions" })).getAllByRole("button")).toHaveLength(7);
    expect(getQueue).toHaveBeenCalledWith("decisions", "review_1", expect.anything());
  });

  it("020-FR-052 Escape on the card does nothing; inside a form it returns to the card, asking first when text was typed", async () => {
    const user = userEvent.setup();
    getQueue.mockResolvedValueOnce(queue([bathroom]));
    const { run } = renderInRun(<DecisionsStep />);
    await screen.findByRole("region", { name: "Renovate the bathroom" });

    await user.keyboard("{Escape}");
    expect(card("Renovate the bathroom")).toBeInTheDocument();
    expect(decide).not.toHaveBeenCalled();

    await user.click(decisionButton(/^Find a first step/));
    await user.type(screen.getByRole("textbox", { name: "First step" }), "Measure");
    expect(run.setUnsaved).toHaveBeenLastCalledWith(true);
    await user.keyboard("{Escape}");
    expect(screen.getByRole("button", { name: "Keep editing" })).toHaveFocus();
    await user.keyboard("{Escape}");
    expect(screen.getByRole("textbox", { name: "First step" })).toHaveValue("Measure");
    await user.click(screen.getByRole("button", { name: "Back" }));
    await user.click(screen.getByRole("button", { name: "Discard" }));

    expect(within(screen.getByRole("group", { name: "Decisions" })).getAllByRole("button")).toHaveLength(7);
    expect(run.setUnsaved).toHaveBeenLastCalledWith(false);
  });

  it("020-FR-006 number keys work on the inline card too and the decision carries the run's id", async () => {
    const user = userEvent.setup();
    getQueue.mockResolvedValueOnce(queue([bathroom, cv]));
    decide.mockResolvedValueOnce(decided(bathroom, "someday", { state: "someday", formulation: null }));
    renderInRun(<DecisionsStep />);
    await screen.findByRole("region", { name: "Renovate the bathroom" });

    await user.keyboard("5");

    expect(decide).toHaveBeenCalledWith("task_bath", { type: "someday", expected_revision: 7, formulation_id: "form_task_bath", session_id: "review_1" }, expect.any(String));
  });

  it("020-FR-048 after a decision the next card comes up with focus on its title, and Undo brings the first card back", async () => {
    const user = userEvent.setup();
    getQueue.mockResolvedValueOnce(queue([bathroom, cv]));
    decide.mockResolvedValueOnce(decided(bathroom, "someday", { state: "someday", formulation: null }));
    undoDecision.mockResolvedValueOnce({ task: { ...bathroom, revision: 9 }, undone_decision_id: "decision_task_bath", deleted_task_id: null, session_counts: null });
    renderInRun(<DecisionsStep />);
    await screen.findByRole("region", { name: "Renovate the bathroom" });

    await user.click(decisionButton(/^Release to Someday/));

    const next = await screen.findByRole("region", { name: "Update the CV" });
    expect(within(next).getByRole("heading", { name: "Update the CV" })).toHaveFocus();
    expect(screen.getByText("2 of 2 · earliest-asking first")).toBeInTheDocument();
    expect(lastToast()[0]).toBe("“Renovate the bathroom” released to Someday");

    await act(async () => lastToast()[1]?.action?.onAction());

    const back = await screen.findByRole("region", { name: "Renovate the bathroom" });
    expect(within(back).getByRole("heading", { name: "Renovate the bathroom" })).toHaveFocus();
    expect(screen.getByText("1 of 2 · earliest-asking first")).toBeInTheDocument();
    expect(undoDecision).toHaveBeenCalledWith("decision_task_bath", { expected_task_revision: 8 }, expect.any(String));
  });

  it("020-FR-050 Not now passes the card, sets the task aside in the run and keeps it asking", async () => {
    const user = userEvent.setup();
    getQueue.mockResolvedValueOnce(queue([bathroom, cv]));
    const { run } = renderInRun(<DecisionsStep />);
    await screen.findByRole("region", { name: "Renovate the bathroom" });

    await user.click(screen.getByRole("button", { name: "Not now" }));

    expect(await screen.findByRole("region", { name: "Update the CV" })).toBeInTheDocument();
    expect(vi.mocked(run.progress).mock.calls[0][0].body).toEqual({ set_aside_task_id: "task_bath", progress_id: expect.stringMatching(/^progress_/) });
    expect(decide).not.toHaveBeenCalled();
  });

  it("020-FR-045 a Not now that is not saved stays on the card with the Ref and retries the same change", async () => {
    const user = userEvent.setup();
    getQueue.mockResolvedValueOnce(queue([bathroom, cv]));
    const progress = vi.fn(async () => undefined).mockRejectedValueOnce(new ApiError("down", 503, null, "corr_not_now"));
    renderInRun(<DecisionsStep />, { progress });
    await screen.findByRole("region", { name: "Renovate the bathroom" });

    await user.click(screen.getByRole("button", { name: "Not now" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Couldn't save “Not now”. Nothing was changed.");
    expect(alert).toHaveTextContent("Ref corr_not_now");
    expect(card("Renovate the bathroom")).toBeInTheDocument();
    await user.click(within(alert).getByRole("button", { name: "Retry" }));

    expect(await screen.findByRole("region", { name: "Update the CV" })).toBeInTheDocument();
    const bodies = progress.mock.calls.map((call) => (call as unknown as [{ body: { progress_id: string } }])[0].body.progress_id);
    expect(bodies[1]).toBe(bodies[0]);
  });

  it("020-FR-002 SC-002 020-SC-002 all decided says so and shows nothing is waiting", async () => {
    const user = userEvent.setup();
    getQueue.mockResolvedValueOnce(queue([bathroom, cv]));
    decide.mockResolvedValueOnce(decided(bathroom, "someday", { state: "someday", formulation: null }));
    decide.mockResolvedValueOnce(decided(cv, "cancel", { state: "cancelled", formulation: null }));
    renderInRun(<DecisionsStep />);
    await screen.findByRole("region", { name: "Renovate the bathroom" });

    await user.click(decisionButton(/^Release to Someday/));
    await screen.findByRole("region", { name: "Update the CV" });
    await user.click(decisionButton(/^Cancel task/));

    expect(await screen.findByText("All 2 decided")).toBeInTheDocument();
    expect(screen.getByText("Nothing in Next is waiting for a decision now.")).toBeInTheDocument();
  });

  it("020-FR-002 a card saved anyway counts as decided but the step says it still asks", async () => {
    const user = userEvent.setup();
    getQueue.mockResolvedValueOnce(queue([bathroom]));
    decide.mockResolvedValueOnce(decided(bathroom, "reformulate", { title: "Renovate the Bathroom" }));
    renderInRun(<DecisionsStep />);
    await screen.findByRole("region", { name: "Renovate the bathroom" });

    await user.click(decisionButton(/^Reformulate/));
    const field = screen.getByRole("textbox", { name: "New wording" });
    await user.clear(field);
    await user.type(field, "Renovate the Bathroom");
    await user.click(screen.getByRole("button", { name: "Save anyway" }));

    expect(await screen.findByText("All 1 decided")).toBeInTheDocument();
    expect(screen.getByText("1 kept its wording, so it still asks for a decision.")).toBeInTheDocument();
  });

  it("020-FR-002 several cards saved anyway are counted in the plural", async () => {
    const user = userEvent.setup();
    getQueue.mockResolvedValueOnce(queue([bathroom, cv]));
    decide.mockResolvedValueOnce(decided(bathroom, "reformulate", { title: "Renovate the Bathroom" }));
    decide.mockResolvedValueOnce(decided(cv, "reformulate", { title: "Update the cv" }));
    renderInRun(<DecisionsStep />);
    await screen.findByRole("region", { name: "Renovate the bathroom" });

    for (const wording of ["Renovate the Bathroom", "Update the cv"]) {
      await user.click(decisionButton(/^Reformulate/));
      const field = screen.getByRole("textbox", { name: "New wording" });
      await user.clear(field);
      await user.type(field, wording);
      await user.click(screen.getByRole("button", { name: "Save anyway" }));
    }

    expect(await screen.findByText("All 2 decided")).toBeInTheDocument();
    expect(screen.getByText("2 kept their wording, so they still ask for a decision.")).toBeInTheDocument();
  });

  it("020-FR-052 Tab moves on from the inline card instead of cycling inside it", async () => {
    const user = userEvent.setup();
    getQueue.mockResolvedValueOnce(queue([bathroom]));
    renderInRun(<DecisionsStep />);
    await screen.findByRole("region", { name: "Renovate the bathroom" });

    decisionButton(/^Keep 7 more days/).focus();
    await user.tab();

    expect(screen.getByRole("button", { name: "Not now" })).toHaveFocus();
  });

  it("020-FR-050 when some were passed the step says how many still ask and that auto-park continues", async () => {
    const user = userEvent.setup();
    getQueue.mockResolvedValueOnce(queue([bathroom, cv, garage]));
    decide.mockResolvedValueOnce(decided(cv, "cancel", { state: "cancelled", formulation: null }));
    renderInRun(<DecisionsStep />);
    await screen.findByRole("region", { name: "Renovate the bathroom" });

    await user.click(screen.getByRole("button", { name: "Not now" }));
    await screen.findByRole("region", { name: "Update the CV" });
    await user.click(decisionButton(/^Cancel task/));
    await screen.findByRole("region", { name: "Clean out the garage" });
    await user.click(screen.getByRole("button", { name: "Not now" }));

    expect(await screen.findByText("1 of 3 decided")).toBeInTheDocument();
    expect(screen.getByText("2 still ask for a decision. They stay in Next whenever you're ready, and move to Someday on their usual date if nothing is decided.")).toBeInTheDocument();
  });

  it("020-FR-029 nothing asking finishes with nothing to decide", async () => {
    getQueue.mockResolvedValueOnce(queue([]));
    renderInRun(<DecisionsStep />);

    expect(await screen.findByText("Nothing asks for a decision")).toBeInTheDocument();
  });

  it("020-FR-011 a card whose task changed elsewhere says so in place and Not now still moves on", async () => {
    const user = userEvent.setup();
    getQueue.mockResolvedValueOnce(queue([bathroom, cv]));
    decide.mockRejectedValueOnce(new ApiError("Conflict", 409, { message: "stale", detail: { resource: "task", id: "task_bath" } }, "corr_stale_card"));
    vi.mocked(apiClient.getTask).mockResolvedValueOnce({ ...bathroom, title: "Renovate the bathroom upstairs", revision: 9 });
    renderInRun(<DecisionsStep />);
    await screen.findByRole("region", { name: "Renovate the bathroom" });

    await user.click(decisionButton(/^Release to Someday/));

    expect(await screen.findByRole("heading", { name: "Task changed elsewhere" })).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("button", { name: "Not now" })).toBeEnabled());
    await user.click(screen.getByRole("button", { name: "Not now" }));
    expect(await screen.findByRole("region", { name: "Update the CV" })).toBeInTheDocument();
  });

  it("020-FR-048 resuming after a reload skips the cards the server already settled and shows the first one that still asks", async () => {
    const user = userEvent.setup();
    const moved = { ...cv, state: "someday" as const, formulation: null, revision: 9 };
    const cancelled = { ...garage, state: "cancelled" as const, formulation: null, revision: 9 };
    const reformulated = askingTask("task_new", "Fix the gutter", { formulation: { ...bathroomClock, id: "form_fresh", started_at: iso(-1000), ageing_at: iso(7 * 86_400_000), ask_at: iso(13 * 86_400_000), park_due_at: iso(20 * 86_400_000) } });
    const extended = askingTask("task_ext", "Order the tiles", { formulation: { ...bathroomClock, extended_at: iso(-1000), extension_reason: "waiting for a quote", paused_until: iso(6 * 86_400_000) } });
    getQueue.mockResolvedValueOnce(queue([moved, cancelled, reformulated, extended, bathroom]));
    renderInRun(<DecisionsStep />);

    expect(await screen.findByRole("region", { name: "Renovate the bathroom" })).toBeInTheDocument();
    expect(screen.getByText("5 of 5 · earliest-asking first")).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Update the CV" })).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Not now" }));

    expect(await screen.findByText("4 of 5 decided")).toBeInTheDocument();
    expect(screen.getByText(/^1 still ask for a decision\./)).toBeInTheDocument();
    expect(decide).not.toHaveBeenCalled();
  });

  it("020-FR-048 a card saved anyway before a reload is not asked again and is not counted twice", async () => {
    const user = userEvent.setup();
    getQueue.mockResolvedValueOnce(queue([bathroom, cv]));
    decide.mockResolvedValueOnce(decided(bathroom, "reformulate", { title: "Renovate the Bathroom" }));
    const first = renderInRun(<DecisionsStep />);
    await screen.findByRole("region", { name: "Renovate the bathroom" });
    await user.click(decisionButton(/^Reformulate/));
    const field = screen.getByRole("textbox", { name: "New wording" });
    await user.clear(field);
    await user.type(field, "Renovate the Bathroom");
    await user.click(screen.getByRole("button", { name: "Save anyway" }));
    await screen.findByRole("region", { name: "Update the CV" });
    first.unmount();

    getQueue.mockResolvedValueOnce(queue([{ ...bathroom, title: "Renovate the Bathroom", revision: 8 }, cv]));
    renderInRun(<DecisionsStep />);

    expect(await screen.findByRole("region", { name: "Update the CV" })).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Renovate the Bathroom" })).not.toBeInTheDocument();
    expect(screen.getByText("2 of 2 · earliest-asking first")).toBeInTheDocument();
    await user.click(decisionButton(/^Release to Someday/));
    expect(decide).toHaveBeenCalledTimes(2);
  });

  it("020-FR-002 after a reload a card saved anyway still counts as decided and the step says it still asks", async () => {
    const user = userEvent.setup();
    getQueue.mockResolvedValueOnce(queue([bathroom]));
    decide.mockResolvedValueOnce(decided(bathroom, "reformulate", { title: "Renovate the Bathroom" }));
    const first = renderInRun(<DecisionsStep />);
    await screen.findByRole("region", { name: "Renovate the bathroom" });
    await user.click(decisionButton(/^Reformulate/));
    const field = screen.getByRole("textbox", { name: "New wording" });
    await user.clear(field);
    await user.type(field, "Renovate the Bathroom");
    await user.click(screen.getByRole("button", { name: "Save anyway" }));
    await screen.findByText("All 1 decided");
    first.unmount();

    getQueue.mockResolvedValueOnce(queue([{ ...bathroom, title: "Renovate the Bathroom", revision: 8 }]));
    renderInRun(<DecisionsStep />);

    expect(await screen.findByText("All 1 decided")).toBeInTheDocument();
    expect(screen.getByText("1 kept its wording, so it still asks for a decision.")).toBeInTheDocument();
    expect(decide).toHaveBeenCalledTimes(1);
  });

  it("020-FR-050 a card set aside with Not now stays set aside after a reload", async () => {
    const user = userEvent.setup();
    getQueue.mockResolvedValueOnce(queue([bathroom, cv]));
    const first = renderInRun(<DecisionsStep />);
    await screen.findByRole("region", { name: "Renovate the bathroom" });
    await user.click(screen.getByRole("button", { name: "Not now" }));
    await screen.findByRole("region", { name: "Update the CV" });
    first.unmount();

    getQueue.mockResolvedValueOnce(queue([bathroom, cv]));
    renderInRun(<DecisionsStep />);

    expect(await screen.findByRole("region", { name: "Update the CV" })).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Renovate the bathroom" })).not.toBeInTheDocument();
  });

  it("020-FR-048 Undo of a card saved anyway brings it back after a reload too", async () => {
    const user = userEvent.setup();
    getQueue.mockResolvedValueOnce(queue([bathroom, cv]));
    decide.mockResolvedValueOnce(decided(bathroom, "reformulate", { title: "Renovate the Bathroom" }));
    undoDecision.mockResolvedValueOnce({ task: { ...bathroom, revision: 9 }, undone_decision_id: "decision_task_bath", deleted_task_id: null, session_counts: null });
    const first = renderInRun(<DecisionsStep />);
    await screen.findByRole("region", { name: "Renovate the bathroom" });
    await user.click(decisionButton(/^Reformulate/));
    const field = screen.getByRole("textbox", { name: "New wording" });
    await user.clear(field);
    await user.type(field, "Renovate the Bathroom");
    await user.click(screen.getByRole("button", { name: "Save anyway" }));
    await screen.findByRole("region", { name: "Update the CV" });
    await act(async () => lastToast()[1]?.action?.onAction());
    await screen.findByRole("region", { name: "Renovate the bathroom" });
    first.unmount();

    getQueue.mockResolvedValueOnce(queue([{ ...bathroom, revision: 9 }, cv]));
    renderInRun(<DecisionsStep />);

    expect(await screen.findByRole("region", { name: "Renovate the bathroom" })).toBeInTheDocument();
    expect(screen.getByText("1 of 2 · earliest-asking first")).toBeInTheDocument();
  });

  it("020-FR-048 what a browser remembers is for the wording it was made on: a new formulation asks again", async () => {
    const user = userEvent.setup();
    getQueue.mockResolvedValueOnce(queue([bathroom]));
    const first = renderInRun(<DecisionsStep />);
    await screen.findByRole("region", { name: "Renovate the bathroom" });
    await user.click(screen.getByRole("button", { name: "Not now" }));
    await screen.findByText("0 of 1 decided");
    first.unmount();

    const reworded = { ...bathroom, formulation: { ...bathroomClock, id: "form_task_bath_2" } };
    getQueue.mockResolvedValueOnce(queue([reworded]));
    renderInRun(<DecisionsStep />);

    expect(await screen.findByRole("region", { name: "Renovate the bathroom" })).toBeInTheDocument();
  });
});
