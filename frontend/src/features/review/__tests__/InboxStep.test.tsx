import { onlineManager } from "@tanstack/react-query";
import { act, cleanup, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, apiClient } from "../../../api/client";
import { reviewApi, type ReviewQueue } from "../../../api/review";
import type { TaskResponse } from "../../../api/taskTypes";
import { forgetRelease, readRelease, rememberRelease } from "../releaseMemory";
import { InboxStep } from "../steps/InboxStep";
import { lastToast, notify, renderInRun, sessionFixture, signIn, taskFixture } from "./reviewKit";

vi.mock("../../../api/review", async () => {
  const actual = await vi.importActual<typeof import("../../../api/review")>("../../../api/review");
  return { ...actual, reviewApi: { ...actual.reviewApi, getQueue: vi.fn(), bulkRelease: vi.fn(), undoBulkRelease: vi.fn() } };
});
vi.mock("../../../api/client", async () => {
  const actual = await vi.importActual<typeof import("../../../api/client")>("../../../api/client");
  return { ...actual, apiClient: { ...actual.apiClient, transitionTask: vi.fn(), updateTask: vi.fn(), getTask: vi.fn() } };
});

const getQueue = vi.mocked(reviewApi.getQueue);
const bulkRelease = vi.mocked(reviewApi.bulkRelease);
const undoBulkRelease = vi.mocked(reviewApi.undoBulkRelease);
const transitionTask = vi.mocked(apiClient.transitionTask);
const updateTask = vi.mocked(apiClient.updateTask);
const getTask = vi.mocked(apiClient.getTask);

const inbox = (id: string, title: string, revision = 3): TaskResponse => taskFixture({ id, title, state: "inbox", revision });
const paper = inbox("inbox_1", "Buy printer paper");
const dentist = inbox("inbox_2", "Call the dentist");
const passport = inbox("inbox_3", "Renew passport");
const queue = (items: TaskResponse[]): ReviewQueue => ({ items, meta: {} });
const many = (count: number) => Array.from({ length: count }, (_, index) => inbox(`inbox_${index + 1}`, `Item number ${index + 1}`, index + 1));

const choice = (name: string | RegExp) => within(screen.getByRole("group", { name: "Choices" })).getByRole("button", { name });

beforeEach(() => {
  window.localStorage.clear();
  signIn();
  transitionTask.mockImplementation(async (id, payload) => ({
    ...taskFixture({ id }),
    state: payload.action === "complete" ? "completed" : payload.action === "cancel" ? "cancelled" : (payload.to_state ?? "inbox"),
    revision: payload.expected_revision + 1
  }));
});

afterEach(() => {
  cleanup();
  onlineManager.setOnline(true);
  vi.restoreAllMocks();
  getQueue.mockReset();
  bulkRelease.mockReset();
  undoBulkRelease.mockReset();
  transitionTask.mockReset();
  updateTask.mockReset();
  getTask.mockReset();
  notify.mockReset();
  window.localStorage.clear();
});

describe("020-FR-034 Inbox step: one item at a time", () => {
  it("020-FR-034 shows the position, the item and the six web choices in order", async () => {
    getQueue.mockResolvedValueOnce(queue([paper, dentist, passport]));
    renderInRun(<InboxStep />);

    expect(await screen.findByRole("heading", { name: "Buy printer paper" })).toBeInTheDocument();
    expect(screen.getByText("Item 1 of 3")).toBeInTheDocument();
    expect(screen.getByText("Is it actionable? Choose where it belongs.")).toBeInTheDocument();
    expect(within(screen.getByRole("group", { name: "Choices" })).getAllByRole("button").map((button) => button.textContent)).toEqual([
      "Next actions", "Waiting for…", "Someday / maybe", "DoneUnder 2 minutes? Do it now.", "Cancel", "Edit title"
    ]);
  });

  it.each([
    ["Next actions", { action: "move", to_state: "next" }, "“Buy printer paper” moved to Next actions", "Undo: Moved to Next actions Buy printer paper"],
    ["Someday / maybe", { action: "move", to_state: "someday" }, "“Buy printer paper” moved to Someday / maybe", "Undo: Moved to Someday / maybe Buy printer paper"],
    [/^Done/, { action: "complete" }, "“Buy printer paper” done", "Undo: Marked done Buy printer paper"],
    ["Cancel", { action: "cancel" }, "“Buy printer paper” cancelled", "Undo: Cancelled Buy printer paper"]
  ] as const)("020-FR-030 %s is one tap: it moves the item, counts it in the run and offers Undo", async (name, body, message, undoLabel) => {
    const user = userEvent.setup();
    getQueue.mockResolvedValueOnce(queue([paper, dentist, passport]));
    const { run } = renderInRun(<InboxStep />);
    await screen.findByRole("heading", { name: "Buy printer paper" });

    await user.click(choice(name));

    expect(transitionTask).toHaveBeenCalledWith("inbox_1", { ...body, expected_revision: 3 }, expect.any(String));
    expect(await screen.findByRole("heading", { name: "Call the dentist" })).toHaveFocus();
    expect(screen.getByText("Item 2 of 3")).toBeInTheDocument();
    expect(vi.mocked(run.progress).mock.calls[0][0].body).toEqual({ inbox_processed_delta: 1, progress_id: expect.stringMatching(/^progress_/) });
    expect(lastToast()[0]).toBe(message);
    expect(lastToast()[1]?.action?.accessibleLabel).toBe(undoLabel);
  });

  it("020-FR-048 Undo returns the item to the Inbox, becomes current again and takes one off the count", async () => {
    const user = userEvent.setup();
    getQueue.mockResolvedValueOnce(queue([paper, dentist]));
    const { run } = renderInRun(<InboxStep />);
    await screen.findByRole("heading", { name: "Buy printer paper" });
    await user.click(choice("Next actions"));
    await screen.findByRole("heading", { name: "Call the dentist" });

    await act(async () => lastToast()[1]?.action?.onAction());

    expect(transitionTask).toHaveBeenLastCalledWith("inbox_1", { action: "move", to_state: "inbox", expected_revision: 4 }, expect.any(String));
    expect(await screen.findByRole("heading", { name: "Buy printer paper" })).toHaveFocus();
    expect(screen.getByText("Item 1 of 2")).toBeInTheDocument();
    expect(vi.mocked(run.progress).mock.calls[1][0].body).toEqual({ inbox_processed_delta: -1, progress_id: expect.stringMatching(/^progress_/) });
    expect(lastToast()[0]).toBe("“Buy printer paper” is back in your Inbox");
  });

  it("020-FR-048 Undo of Done reopens the item into the Inbox", async () => {
    const user = userEvent.setup();
    getQueue.mockResolvedValueOnce(queue([paper, dentist]));
    renderInRun(<InboxStep />);
    await screen.findByRole("heading", { name: "Buy printer paper" });
    await user.click(choice(/^Done/));
    await screen.findByRole("heading", { name: "Call the dentist" });

    await act(async () => lastToast()[1]?.action?.onAction());

    expect(transitionTask).toHaveBeenLastCalledWith("inbox_1", { action: "reopen", to_state: "inbox", expected_revision: 4 }, expect.any(String));
  });

  it("020-FR-048 an Undo that fails says so with the Ref and changes nothing", async () => {
    const user = userEvent.setup();
    getQueue.mockResolvedValueOnce(queue([paper, dentist]));
    renderInRun(<InboxStep />);
    await screen.findByRole("heading", { name: "Buy printer paper" });
    await user.click(choice("Next actions"));
    await screen.findByRole("heading", { name: "Call the dentist" });
    transitionTask.mockRejectedValueOnce(new ApiError("Conflict", 409, null, "corr_undo_inbox"));

    await act(async () => lastToast()[1]?.action?.onAction());

    expect(lastToast()[0]).toBe("Couldn't undo. Nothing was changed. Ref corr_undo_inbox");
    expect(screen.getByRole("heading", { name: "Call the dentist" })).toBeInTheDocument();
  });

  it("020-FR-048 an Undo whose transition fails sends no count change and leaves the item processed", async () => {
    const user = userEvent.setup();
    getQueue.mockResolvedValueOnce(queue([paper, dentist]));
    const { run } = renderInRun(<InboxStep />);
    await screen.findByRole("heading", { name: "Buy printer paper" });
    await user.click(choice("Next actions"));
    await screen.findByRole("heading", { name: "Call the dentist" });
    transitionTask.mockRejectedValueOnce(new ApiError("Conflict", 409, null, "corr_no_transition"));

    await act(async () => lastToast()[1]?.action?.onAction());

    expect(lastToast()[0]).toBe("Couldn't undo. Nothing was changed. Ref corr_no_transition");
    expect(run.progress).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("heading", { name: "Call the dentist" })).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("020-FR-048 an Undo whose count is not saved shows the item again with the Ref, and Retry resends only that count under the same id", async () => {
    const user = userEvent.setup();
    getQueue.mockResolvedValueOnce(queue([paper, dentist]));
    const progress = vi.fn(async () => undefined).mockResolvedValueOnce(undefined).mockRejectedValueOnce(new ApiError("down", 503, null, "corr_undo_count"));
    renderInRun(<InboxStep />, { progress });
    await screen.findByRole("heading", { name: "Buy printer paper" });
    await user.click(choice("Next actions"));
    await screen.findByRole("heading", { name: "Call the dentist" });

    await act(async () => lastToast()[1]?.action?.onAction());

    expect(transitionTask).toHaveBeenCalledTimes(2);
    expect(await screen.findByRole("heading", { name: "Buy printer paper" })).toHaveFocus();
    expect(screen.getByText("Item 1 of 2")).toBeInTheDocument();
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("“Buy printer paper” is back in your Inbox, but the processed count didn't go down.");
    expect(alert).toHaveTextContent("Ref corr_undo_count");

    await user.click(within(alert).getByRole("button", { name: "Retry" }));

    await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument());
    expect(transitionTask).toHaveBeenCalledTimes(2);
    expect(progress).toHaveBeenCalledTimes(3);
    const bodies = progress.mock.calls.map((call) => (call as unknown as [{ body: { inbox_processed_delta: number; progress_id: string } }])[0].body);
    expect(bodies[2]).toEqual({ inbox_processed_delta: -1, progress_id: bodies[1].progress_id });
    expect(screen.getByRole("heading", { name: "Buy printer paper" })).toBeInTheDocument();
  });

  it("020-FR-034 Waiting for asks who or what first and moves the item there", async () => {
    const user = userEvent.setup();
    getQueue.mockResolvedValueOnce(queue([paper, dentist]));
    const { run } = renderInRun(<InboxStep />);
    await screen.findByRole("heading", { name: "Buy printer paper" });

    await user.click(choice("Waiting for…"));
    const field = screen.getByRole("textbox", { name: "Who or what are you waiting for?" });
    expect(field).toHaveFocus();
    expect(screen.getByRole("button", { name: "Move to Waiting for" })).toBeDisabled();
    await user.type(field, "the shop");
    expect(run.setUnsaved).toHaveBeenLastCalledWith(true);
    await user.click(screen.getByRole("button", { name: "Move to Waiting for" }));

    expect(transitionTask).toHaveBeenCalledWith("inbox_1", { action: "move", to_state: "waiting", waiting_for: "the shop", expected_revision: 3 }, expect.any(String));
    expect(await screen.findByRole("heading", { name: "Call the dentist" })).toBeInTheDocument();
    expect(run.setUnsaved).toHaveBeenLastCalledWith(false);
  });

  it("020-FR-034 Edit title saves the new title and keeps the item current; Back drops the form", async () => {
    const user = userEvent.setup();
    getQueue.mockResolvedValueOnce(queue([paper]));
    updateTask.mockResolvedValueOnce({ ...paper, title: "Buy A4 printer paper", revision: 4 });
    const { run } = renderInRun(<InboxStep />);
    await screen.findByRole("heading", { name: "Buy printer paper" });

    await user.click(choice("Edit title"));
    await user.click(screen.getByRole("button", { name: "Back" }));
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    await user.click(choice("Edit title"));
    const field = screen.getByRole("textbox", { name: "Title" });
    expect(field).toHaveValue("Buy printer paper");
    await user.clear(field);
    await user.type(field, "Buy A4 printer paper");
    expect(run.setUnsaved).toHaveBeenLastCalledWith(true);
    await user.click(screen.getByRole("button", { name: "Save title" }));

    expect(updateTask).toHaveBeenCalledWith("inbox_1", { title: "Buy A4 printer paper", expected_revision: 3 }, expect.any(String));
    expect(await screen.findByRole("heading", { name: "Buy A4 printer paper" })).toBeInTheDocument();
    expect(run.setUnsaved).toHaveBeenLastCalledWith(false);
    await user.click(choice("Next actions"));
    expect(transitionTask).toHaveBeenCalledWith("inbox_1", { action: "move", to_state: "next", expected_revision: 4 }, expect.any(String));
  });

  it("020-FR-045 a choice shows Saving… on its own button only, and a failure keeps the item with the Ref and retries under the same key", async () => {
    const user = userEvent.setup();
    getQueue.mockResolvedValueOnce(queue([paper, dentist]));
    let fail: (error: unknown) => void = () => undefined;
    transitionTask.mockReturnValueOnce(new Promise((_resolve, reject) => { fail = reject; }));
    renderInRun(<InboxStep />);
    await screen.findByRole("heading", { name: "Buy printer paper" });

    await user.click(choice("Next actions"));
    expect(choice(/Saving…/)).toBeInTheDocument();
    expect(choice("Someday / maybe")).toBeDisabled();
    await act(async () => fail(new ApiError("down", 503, null, "corr_inbox_choice")));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Couldn't save “Next actions”. Nothing was changed.");
    expect(alert).toHaveTextContent("Ref corr_inbox_choice");
    expect(screen.getByRole("heading", { name: "Buy printer paper" })).toBeInTheDocument();
    await user.click(within(alert).getByRole("button", { name: "Retry" }));

    expect(await screen.findByRole("heading", { name: "Call the dentist" })).toBeInTheDocument();
    expect(transitionTask.mock.calls[1][2]).toBe(transitionTask.mock.calls[0][2]);
  });

  it("020-FR-048 a count that is not saved after the move shows the item as processed with the Ref, and Retry resends only the count under the same id", async () => {
    const user = userEvent.setup();
    getQueue.mockResolvedValueOnce(queue([paper, dentist]));
    const progress = vi.fn(async () => undefined).mockRejectedValueOnce(new ApiError("down", 503, null, "corr_count"));
    renderInRun(<InboxStep />, { progress });
    await screen.findByRole("heading", { name: "Buy printer paper" });

    await user.click(choice("Next actions"));

    expect(await screen.findByRole("heading", { name: "Call the dentist" })).toHaveFocus();
    expect(screen.getByText("Item 2 of 2")).toBeInTheDocument();
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("“Buy printer paper” moved to Next actions, but the processed count didn't go up.");
    expect(alert).toHaveTextContent("Ref corr_count");
    expect(notify).not.toHaveBeenCalled();
    await user.click(within(alert).getByRole("button", { name: "Retry" }));

    await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument());
    expect(transitionTask).toHaveBeenCalledTimes(1);
    expect(progress).toHaveBeenCalledTimes(2);
    const bodies = progress.mock.calls.map((call) => (call as unknown as [{ body: { inbox_processed_delta: number; progress_id: string } }])[0].body);
    expect(bodies[1]).toEqual({ inbox_processed_delta: 1, progress_id: bodies[0].progress_id });
    expect(lastToast()[0]).toBe("“Buy printer paper” moved to Next actions");
    expect(lastToast()[1]?.action?.accessibleLabel).toBe("Undo: Moved to Next actions Buy printer paper");
    expect(screen.getByRole("heading", { name: "Call the dentist" })).toBeInTheDocument();
  });

  it("020-FR-048 a count that is not saved for the last item still ends the step on its processed total, with the Retry", async () => {
    const user = userEvent.setup();
    getQueue.mockResolvedValueOnce(queue([paper]));
    const progress = vi.fn(async () => undefined).mockRejectedValueOnce(new ApiError("down", 503, null, "corr_count_last"));
    renderInRun(<InboxStep />, { progress });
    await screen.findByRole("heading", { name: "Buy printer paper" });

    await user.click(choice("Next actions"));

    expect(await screen.findByText("1 item processed")).toBeInTheDocument();
    expect(await screen.findByRole("alert")).toHaveTextContent("Ref corr_count_last");
  });

  it("020-FR-045 a move that fails keeps the item and sends no count; its Retry moves it once under the same key and then counts it", async () => {
    const user = userEvent.setup();
    getQueue.mockResolvedValueOnce(queue([paper, dentist]));
    transitionTask.mockRejectedValueOnce(new ApiError("down", 503, null, "corr_move"));
    const { run } = renderInRun(<InboxStep />);
    await screen.findByRole("heading", { name: "Buy printer paper" });

    await user.click(choice("Next actions"));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Couldn't save “Next actions”. Nothing was changed.");
    expect(run.progress).not.toHaveBeenCalled();
    await user.click(within(alert).getByRole("button", { name: "Retry" }));

    expect(await screen.findByRole("heading", { name: "Call the dentist" })).toBeInTheDocument();
    expect(transitionTask.mock.calls[1][2]).toBe(transitionTask.mock.calls[0][2]);
    expect(run.progress).toHaveBeenCalledTimes(1);
  });

  it("020-FR-011 an item changed elsewhere is named, stays in the Inbox, is not counted and the review moves on", async () => {
    const user = userEvent.setup();
    getQueue.mockResolvedValueOnce(queue([paper, dentist]));
    transitionTask.mockRejectedValueOnce(new ApiError("Conflict", 409, { message: "stale", detail: { resource: "task", id: "inbox_1" } }, "corr_stale_inbox"));
    getTask.mockResolvedValueOnce({ ...paper, state: "someday", revision: 5 });
    const { run } = renderInRun(<InboxStep />);
    await screen.findByRole("heading", { name: "Buy printer paper" });

    await user.click(choice("Next actions"));

    expect(await screen.findByRole("heading", { name: "Call the dentist" })).toBeInTheDocument();
    expect(screen.getByRole("status", { name: "Changed elsewhere" })).toHaveTextContent("“Buy printer paper” was changed on another device, so it stayed in Inbox.");
    expect(run.progress).not.toHaveBeenCalled();
    expect(notify).not.toHaveBeenCalled();
  });

  it("020-FR-011 when the last item changed elsewhere the step still says so and that nothing was processed", async () => {
    const user = userEvent.setup();
    getQueue.mockResolvedValueOnce(queue([paper]));
    transitionTask.mockRejectedValueOnce(new ApiError("Conflict", 409, { message: "stale", detail: { resource: "task", id: "inbox_1" } }, "corr_stale_last"));
    getTask.mockResolvedValueOnce({ ...paper, state: "someday", revision: 5 });
    renderInRun(<InboxStep />);
    await screen.findByRole("heading", { name: "Buy printer paper" });

    await user.click(choice("Next actions"));

    expect(await screen.findByText("0 items processed")).toBeInTheDocument();
    expect(screen.getByRole("status", { name: "Changed elsewhere" })).toHaveTextContent("“Buy printer paper” was changed on another device, so it stayed in Inbox.");
  });

  it("020-FR-052 an item whose revision moved but whose wording did not keeps its Waiting-for text and retries on the new revision", async () => {
    const user = userEvent.setup();
    getQueue.mockResolvedValueOnce(queue([paper, dentist]));
    transitionTask.mockRejectedValueOnce(new ApiError("Conflict", 409, { message: "stale", detail: { resource: "task", id: "inbox_1" } }, "corr_notes"));
    getTask.mockResolvedValueOnce({ ...paper, details: "from the shop", revision: 6 });
    const { run } = renderInRun(<InboxStep />);
    await screen.findByRole("heading", { name: "Buy printer paper" });
    await user.click(choice("Waiting for…"));
    await user.type(screen.getByRole("textbox", { name: "Who or what are you waiting for?" }), "the shop");

    await user.click(screen.getByRole("button", { name: "Move to Waiting for" }));

    expect(await screen.findByRole("status", { name: "Changed elsewhere" })).toHaveTextContent("“Buy printer paper” was changed on another device, so nothing was moved. It's still in Inbox; choose again.");
    expect(screen.getByRole("heading", { name: "Buy printer paper" })).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Who or what are you waiting for?" })).toHaveValue("the shop");
    expect(Object.keys(window.localStorage).some((key) => key.endsWith(".inbox_1.waiting"))).toBe(true);
    expect(run.setUnsaved).not.toHaveBeenLastCalledWith(false);
    await user.click(screen.getByRole("button", { name: "Move to Waiting for" }));

    expect(await screen.findByRole("heading", { name: "Call the dentist" })).toBeInTheDocument();
    expect(transitionTask).toHaveBeenLastCalledWith("inbox_1", { action: "move", to_state: "waiting", waiting_for: "the shop", expected_revision: 6 }, expect.any(String));
    expect(transitionTask.mock.calls[1][2]).not.toBe(transitionTask.mock.calls[0][2]);
    expect(Object.keys(window.localStorage).some((key) => key.endsWith(".inbox_1.waiting"))).toBe(false);
  });

  it("020-FR-011 an item reworded elsewhere is left there and its typed Waiting-for text is dropped with it", async () => {
    const user = userEvent.setup();
    getQueue.mockResolvedValueOnce(queue([paper, dentist]));
    transitionTask.mockRejectedValueOnce(new ApiError("Conflict", 409, { message: "stale", detail: { resource: "task", id: "inbox_1" } }, "corr_reworded"));
    getTask.mockResolvedValueOnce({ ...paper, title: "Buy A3 plotter paper", revision: 6 });
    renderInRun(<InboxStep />);
    await screen.findByRole("heading", { name: "Buy printer paper" });
    await user.click(choice("Waiting for…"));
    await user.type(screen.getByRole("textbox", { name: "Who or what are you waiting for?" }), "the shop");

    await user.click(screen.getByRole("button", { name: "Move to Waiting for" }));

    expect(await screen.findByRole("heading", { name: "Call the dentist" })).toBeInTheDocument();
    expect(screen.getByRole("status", { name: "Changed elsewhere" })).toHaveTextContent("“Buy printer paper” was changed on another device, so it stayed in Inbox.");
    expect(Object.keys(window.localStorage).some((key) => key.endsWith(".inbox_1.waiting"))).toBe(false);
  });

  it("020-FR-011 an item that cannot be read again after a stale answer is left as it is", async () => {
    const user = userEvent.setup();
    getQueue.mockResolvedValueOnce(queue([paper, dentist]));
    transitionTask.mockRejectedValueOnce(new ApiError("Conflict", 409, { message: "stale", detail: { resource: "task", id: "inbox_1" } }, "corr_unreadable"));
    getTask.mockRejectedValueOnce(new ApiError("down", 503, null, "corr_read"));
    renderInRun(<InboxStep />);
    await screen.findByRole("heading", { name: "Buy printer paper" });

    await user.click(choice("Next actions"));

    expect(await screen.findByRole("heading", { name: "Call the dentist" })).toBeInTheDocument();
    expect(screen.getByRole("status", { name: "Changed elsewhere" })).toHaveTextContent("“Buy printer paper” was changed on another device, so it stayed in Inbox.");
  });

  it("020-FR-042 a choice answered after another account signed in sends no count and shows no Undo", async () => {
    const user = userEvent.setup();
    getQueue.mockResolvedValueOnce(queue([paper, dentist]));
    let resolve: (task: TaskResponse) => void = () => undefined;
    transitionTask.mockReturnValueOnce(new Promise((done) => { resolve = done; }));
    const { run } = renderInRun(<InboxStep />);
    await screen.findByRole("heading", { name: "Buy printer paper" });
    await user.click(choice("Next actions"));

    act(() => signIn("user-2"));
    await act(async () => resolve({ ...paper, state: "next", revision: 4 }));

    expect(run.progress).not.toHaveBeenCalled();
    expect(notify).not.toHaveBeenCalled();
    act(() => signIn("user-1"));
  });

  it("020-FR-042 a stale answer read again after another account signed in changes nothing", async () => {
    const user = userEvent.setup();
    getQueue.mockResolvedValueOnce(queue([paper, dentist]));
    transitionTask.mockRejectedValueOnce(new ApiError("Conflict", 409, { message: "stale", detail: { resource: "task", id: "inbox_1" } }, "corr_stale_switch"));
    let resolve: (task: TaskResponse) => void = () => undefined;
    getTask.mockReturnValueOnce(new Promise((done) => { resolve = done; }));
    renderInRun(<InboxStep />);
    await screen.findByRole("heading", { name: "Buy printer paper" });
    await user.click(choice("Next actions"));

    act(() => signIn("user-2"));
    await act(async () => resolve({ ...paper, state: "someday", revision: 5 }));

    expect(screen.queryByRole("status", { name: "Changed elsewhere" })).not.toBeInTheDocument();
    expect(notify).not.toHaveBeenCalled();
    act(() => signIn("user-1"));
  });

  it("020-FR-042 a count answered after another account signed in shows no Undo", async () => {
    const user = userEvent.setup();
    getQueue.mockResolvedValueOnce(queue([paper, dentist]));
    let resolve: () => void = () => undefined;
    const progress = vi.fn(() => new Promise<undefined>((done) => { resolve = () => done(undefined); }));
    renderInRun(<InboxStep />, { progress });
    await screen.findByRole("heading", { name: "Buy printer paper" });
    await user.click(choice("Next actions"));
    await waitFor(() => expect(progress).toHaveBeenCalledTimes(1));

    act(() => signIn("user-2"));
    await act(async () => resolve());

    expect(notify).not.toHaveBeenCalled();
    act(() => signIn("user-1"));
  });

  it("020-FR-042 an Undo answered after another account signed in says nothing", async () => {
    const user = userEvent.setup();
    getQueue.mockResolvedValueOnce(queue([paper, dentist]));
    renderInRun(<InboxStep />);
    await screen.findByRole("heading", { name: "Buy printer paper" });
    await user.click(choice("Next actions"));
    await screen.findByRole("heading", { name: "Call the dentist" });
    const toasts = notify.mock.calls.length;
    let resolve: (task: TaskResponse) => void = () => undefined;
    transitionTask.mockReturnValueOnce(new Promise((done) => { resolve = done; }));
    act(() => { void lastToast()[1]?.action?.onAction(); });

    act(() => signIn("user-2"));
    await act(async () => resolve({ ...paper, state: "inbox", revision: 5 }));

    expect(notify.mock.calls.length).toBe(toasts);
    act(() => signIn("user-1"));
  });

  it("020-FR-040 the choices are disabled while offline", async () => {
    getQueue.mockResolvedValueOnce(queue([paper]));
    renderInRun(<InboxStep />);
    await screen.findByRole("heading", { name: "Buy printer paper" });

    vi.spyOn(navigator, "onLine", "get").mockReturnValue(false);
    act(() => { window.dispatchEvent(new Event("offline")); });

    expect(choice("Next actions")).toBeDisabled();
  });

  it("020-FR-029 an empty Inbox finishes with nothing to decide", async () => {
    getQueue.mockResolvedValueOnce(queue([]));
    renderInRun(<InboxStep />);

    expect(await screen.findByText("Inbox is empty")).toBeInTheDocument();
    expect(screen.getByText("Nothing to process.")).toBeInTheDocument();
  });

  it("020-FR-034 after the last item the step says how many were processed", async () => {
    const user = userEvent.setup();
    getQueue.mockResolvedValueOnce(queue([paper]));
    renderInRun(<InboxStep />);
    await screen.findByRole("heading", { name: "Buy printer paper" });

    await user.click(choice("Next actions"));

    expect(await screen.findByText("1 item processed")).toBeInTheDocument();
  });
});

describe("020-FR-030 Inbox step: more than 15 items", () => {
  const sixteen = many(16);

  it("020-FR-030 offers three choices first, and Process 10 now stops after ten", async () => {
    const user = userEvent.setup();
    getQueue.mockResolvedValueOnce(queue(sixteen));
    renderInRun(<InboxStep />);

    const group = await screen.findByRole("group", { name: "Your Inbox is long" });
    expect(within(group).getAllByRole("button").map((button) => button.textContent)).toEqual([
      "Process 10 now", "Process all 16", "Process 10, release the rest to Someday"
    ]);
    await user.click(within(group).getByRole("button", { name: "Process 10 now" }));
    expect(screen.getByText("Item 1 of 10")).toBeInTheDocument();
    for (let index = 0; index < 10; index += 1) {
      await user.click(choice("Someday / maybe"));
    }

    expect(await screen.findByText("10 items processed")).toBeInTheDocument();
    expect(bulkRelease).not.toHaveBeenCalled();
  });

  it("020-FR-030 Process all runs through every item", async () => {
    const user = userEvent.setup();
    getQueue.mockResolvedValueOnce(queue(many(16)));
    renderInRun(<InboxStep />);

    await user.click(await screen.findByRole("button", { name: "Process all 16" }));

    expect(screen.getByText("Item 1 of 16")).toBeInTheDocument();
  });

  async function processTenAndRelease(user: ReturnType<typeof userEvent.setup>) {
    await user.click(await screen.findByRole("button", { name: "Process 10, release the rest to Someday" }));
    for (let index = 0; index < 10; index += 1) {
      await user.click(choice("Someday / maybe"));
    }
  }

  it("020-FR-030 after ten it releases the rest to Someday, says so with Undo and keeps the release for a reload", async () => {
    const user = userEvent.setup();
    getQueue.mockResolvedValueOnce(queue(many(16)));
    bulkRelease.mockResolvedValueOnce({ id: "bulk_inbox_1", released: many(6).map((task, index) => ({ task_id: `inbox_${index + 11}`, revision_after: 20 + index })), skipped: [] });
    const { run } = renderInRun(<InboxStep />);

    await processTenAndRelease(user);

    expect(await screen.findByText("10 items processed · 6 released to Someday / maybe")).toBeInTheDocument();
    expect(bulkRelease).toHaveBeenCalledWith(
      { kind: "inbox_remainder", session_id: "review_1", items: many(16).slice(10).map((task) => ({ task_id: task.id, expected_revision: task.revision })) },
      expect.any(String)
    );
    expect(screen.getByRole("button", { name: "Undo the release" })).toBeInTheDocument();
    expect(readRelease("user-1")).toEqual({ kind: "inbox_remainder", bulkId: "bulk_inbox_1", sessionId: run.session.id, released: 6 });
  });

  it("020-FR-030 the release still follows when the tenth item needed a Retry", async () => {
    const user = userEvent.setup();
    getQueue.mockResolvedValueOnce(queue(many(16)));
    bulkRelease.mockResolvedValueOnce({ id: "bulk_inbox_1", released: [{ task_id: "inbox_11", revision_after: 20 }], skipped: [] });
    renderInRun(<InboxStep />);
    await user.click(await screen.findByRole("button", { name: "Process 10, release the rest to Someday" }));
    for (let index = 0; index < 9; index += 1) {
      await user.click(choice("Someday / maybe"));
    }
    transitionTask.mockRejectedValueOnce(new ApiError("down", 503, null, "corr_tenth"));

    await user.click(choice("Someday / maybe"));
    await user.click(within(await screen.findByRole("alert")).getByRole("button", { name: "Retry" }));

    expect(await screen.findByText("10 items processed · 1 released to Someday / maybe")).toBeInTheDocument();
    expect(bulkRelease).toHaveBeenCalledTimes(1);
  });

  it("020-FR-030 names the items the release left where they were", async () => {
    const user = userEvent.setup();
    getQueue.mockResolvedValueOnce(queue(many(16)));
    bulkRelease.mockResolvedValueOnce({ id: "bulk_inbox_1", released: [{ task_id: "inbox_11", revision_after: 20 }], skipped: [{ task_id: "inbox_12", reason: "stale" }, { task_id: "inbox_13", reason: "not_eligible" }] });
    renderInRun(<InboxStep />);

    await processTenAndRelease(user);

    expect(await screen.findByText("10 items processed · 1 released to Someday / maybe")).toBeInTheDocument();
    expect(screen.getByText("2 changed on another device and stayed in Inbox.")).toBeInTheDocument();
  });

  it("020-FR-045 a release that fails changes nothing, shows the Ref and retries under the same key", async () => {
    const user = userEvent.setup();
    getQueue.mockResolvedValueOnce(queue(many(16)));
    bulkRelease.mockRejectedValueOnce(new ApiError("down", 503, null, "corr_release"));
    bulkRelease.mockResolvedValueOnce({ id: "bulk_inbox_1", released: [{ task_id: "inbox_11", revision_after: 20 }], skipped: [] });
    renderInRun(<InboxStep />);

    await processTenAndRelease(user);
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Couldn't release the rest of your Inbox. Nothing was moved.");
    expect(alert).toHaveTextContent("Ref corr_release");
    await user.click(within(alert).getByRole("button", { name: "Retry" }));

    expect(await screen.findByText("10 items processed · 1 released to Someday / maybe")).toBeInTheDocument();
    expect(bulkRelease.mock.calls[1][1]).toBe(bulkRelease.mock.calls[0][1]);
  });

  it("020-FR-030 Undo the release puts the items back and says so", async () => {
    const user = userEvent.setup();
    getQueue.mockResolvedValueOnce(queue(many(16)));
    bulkRelease.mockResolvedValueOnce({ id: "bulk_inbox_1", released: many(6).map((task, index) => ({ task_id: `inbox_${index + 11}`, revision_after: 20 + index })), skipped: [] });
    undoBulkRelease.mockResolvedValueOnce({ restored: many(6).map((task, index) => `inbox_${index + 11}`), skipped: [] });
    renderInRun(<InboxStep />);
    await processTenAndRelease(user);

    await user.click(await screen.findByRole("button", { name: "Undo the release" }));

    expect(undoBulkRelease).toHaveBeenCalledWith("bulk_inbox_1", expect.any(String));
    expect(await screen.findByText("Undone. All 6 are back in your Inbox.")).toBeInTheDocument();
    expect(readRelease("user-1")).toBeNull();
  });

  it("020-FR-030 an Undo that could restore only some names the rest", async () => {
    const user = userEvent.setup();
    getQueue.mockResolvedValueOnce(queue(many(16)));
    bulkRelease.mockResolvedValueOnce({ id: "bulk_inbox_1", released: many(6).map((task, index) => ({ task_id: `inbox_${index + 11}`, revision_after: 20 + index })), skipped: [] });
    undoBulkRelease.mockResolvedValueOnce({ restored: ["inbox_11", "inbox_12", "inbox_13", "inbox_14"], skipped: [{ task_id: "inbox_15", reason: "stale" }, { task_id: "inbox_16", reason: "stale" }] });
    renderInRun(<InboxStep />);
    await processTenAndRelease(user);

    await user.click(await screen.findByRole("button", { name: "Undo the release" }));

    expect(await screen.findByText("4 are back in your Inbox. 2 changed on another device and stayed in Someday / maybe.")).toBeInTheDocument();
  });

  it("020-FR-045 an Undo that fails keeps the release offered, with the Ref and Retry", async () => {
    const user = userEvent.setup();
    getQueue.mockResolvedValueOnce(queue(many(16)));
    bulkRelease.mockResolvedValueOnce({ id: "bulk_inbox_1", released: many(6).map((task, index) => ({ task_id: `inbox_${index + 11}`, revision_after: 20 + index })), skipped: [] });
    undoBulkRelease.mockRejectedValueOnce(new ApiError("down", 503, null, "corr_undo_release"));
    undoBulkRelease.mockResolvedValueOnce({ restored: ["inbox_11"], skipped: [] });
    renderInRun(<InboxStep />);
    await processTenAndRelease(user);

    await user.click(await screen.findByRole("button", { name: "Undo the release" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Couldn't undo the release. The 6 items are still in Someday / maybe.");
    expect(alert).toHaveTextContent("Ref corr_undo_release");
    expect(screen.getByRole("button", { name: "Undo the release" })).toBeInTheDocument();
    await user.click(within(alert).getByRole("button", { name: "Retry" }));

    await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument());
    expect(undoBulkRelease.mock.calls[1][1]).toBe(undoBulkRelease.mock.calls[0][1]);
  });

  it("020-FR-030 after a tab reload the step reopens on the release with Undo still offered", async () => {
    rememberRelease("user-1", { kind: "inbox_remainder", bulkId: "bulk_inbox_1", sessionId: "review_1", released: 12 });
    getQueue.mockResolvedValueOnce(queue([]));
    renderInRun(<InboxStep />);

    expect(await screen.findByText("12 items were released to Someday / maybe.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Undo the release" })).toBeInTheDocument();
  });

  it("020-FR-030 once the step has been left the earlier release is no longer offered", async () => {
    rememberRelease("user-1", { kind: "inbox_remainder", bulkId: "bulk_inbox_1", sessionId: "review_1", released: 12 });
    getQueue.mockResolvedValueOnce(queue([]));
    renderInRun(<InboxStep />, { session: sessionFixture({ steps: { ...sessionFixture().steps, inbox: "finished" } }) });

    expect(await screen.findByText("Inbox is empty")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Undo the release" })).not.toBeInTheDocument();
    forgetRelease("user-1");
  });
});
