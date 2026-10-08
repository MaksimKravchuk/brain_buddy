import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, apiClient } from "../../../api/client";
import { reviewApi } from "../../../api/review";
import type { TaskResponse } from "../../../api/taskTypes";
import { readRelease, rememberRelease } from "../releaseMemory";
import { RestartStep } from "../steps/RestartStep";
import { DAY, askingTask, iso, signIn, stateFixture } from "./reviewKit";

vi.mock("../../../api/review", async () => {
  const actual = await vi.importActual<typeof import("../../../api/review")>("../../../api/review");
  return { ...actual, reviewApi: { ...actual.reviewApi, bulkRelease: vi.fn(), undoBulkRelease: vi.fn() } };
});
vi.mock("../../../api/client", async () => {
  const actual = await vi.importActual<typeof import("../../../api/client")>("../../../api/client");
  return { ...actual, apiClient: { ...actual.apiClient, listTasks: vi.fn() } };
});

const bulkRelease = vi.mocked(reviewApi.bulkRelease);
const undoBulkRelease = vi.mocked(reviewApi.undoBulkRelease);
const listTasks = vi.mocked(apiClient.listTasks);

/** A Next task whose wording started `days` ago. */
function aged(id: string, title: string, days: number, formulation: Partial<NonNullable<TaskResponse["formulation"]>> = {}): TaskResponse {
  const task = askingTask(id, title);
  return { ...task, revision: 4, formulation: { ...(task.formulation as NonNullable<TaskResponse["formulation"]>), started_at: iso(-days * DAY), ...formulation } };
}

const old1 = aged("n1", "Update the CV", 40);
const old2 = aged("n2", "Sort the garage", 35);
const old3 = aged("n3", "Plan the trip", 30);
const young = aged("n4", "Call Sam", 10);
const paused = aged("n5", "Pay the tax", 50, { paused_until: iso(3 * DAY) });
const unclocked: TaskResponse = { ...old1, id: "n6", title: "No clock yet", formulation: null };
const page = (items: TaskResponse[], more: { cursor: string | null } = { cursor: null }) => ({
  items,
  next_cursor: more.cursor,
  has_more: more.cursor !== null,
  counts_by_state: { inbox: 0, next: items.length, waiting: 0, someday: 0 }
});

const onContinue = vi.fn();

function renderStep(state = stateFixture({ restart_mode: true, last_counted_review_at: iso(-26 * DAY) })) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <RestartStep state={state} onContinue={onContinue} />
    </QueryClientProvider>
  );
}

beforeEach(() => {
  window.localStorage.clear();
  signIn();
  listTasks.mockResolvedValue(page([old1, old2, old3, young, paused, unclocked]));
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  bulkRelease.mockReset();
  undoBulkRelease.mockReset();
  listTasks.mockReset();
  onContinue.mockReset();
  window.localStorage.clear();
});

describe("020-FR-017 restart mode", () => {
  it("020-FR-017 welcomes the person neutrally and counts the Next actions older than four weeks", async () => {
    renderStep();

    expect(await screen.findByRole("heading", { name: "Welcome back" })).toHaveFocus();
    expect(screen.getByText("Your last review was 26 days ago. Gaps happen. Let's make Next fit the week ahead.")).toBeInTheDocument();
    expect(await screen.findByText("3 next actions are older than 4 weeks")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Release 3 to Someday" })).toBeInTheDocument();
  });

  it("020-FR-017 reads every page of Next", async () => {
    listTasks.mockResolvedValueOnce(page([old1], { cursor: "page2" })).mockResolvedValueOnce(page([old2]));
    renderStep();

    expect(await screen.findByText("2 next actions are older than 4 weeks")).toBeInTheDocument();
    expect(listTasks.mock.calls.map(([filters]) => filters)).toEqual([{ state: "next" }, { state: "next", cursor: "page2" }]);
  });

  it("020-FR-017 See which ones lists them read-only with their age", async () => {
    const user = userEvent.setup();
    renderStep();

    await user.click(await screen.findByRole("button", { name: "See which ones" }));

    const list = screen.getByRole("list", { name: "Next actions older than 4 weeks" });
    expect(within(list).getAllByRole("listitem").map((item) => item.textContent)).toEqual([
      "Update the CV40 days", "Sort the garage35 days", "Plan the trip30 days"
    ]);
    await user.click(screen.getByRole("button", { name: "Hide the list" }));
    expect(screen.queryByRole("list", { name: "Next actions older than 4 weeks" })).not.toBeInTheDocument();
  });

  it("020-FR-017 Keep them goes straight on without releasing anything", async () => {
    const user = userEvent.setup();
    renderStep();

    await user.click(await screen.findByRole("button", { name: "Keep them" }));

    expect(onContinue).toHaveBeenCalledTimes(1);
    expect(bulkRelease).not.toHaveBeenCalled();
  });

  it("020-FR-048 while the release is on its way Keep them waits, so its answer and Undo stay on screen", async () => {
    const user = userEvent.setup();
    let resolve: (value: Awaited<ReturnType<typeof reviewApi.bulkRelease>>) => void = () => undefined;
    bulkRelease.mockReturnValueOnce(new Promise((done) => { resolve = done; }));
    renderStep();

    await user.click(await screen.findByRole("button", { name: "Release 3 to Someday" }));
    const keep = screen.getByRole("button", { name: "Keep them" });
    expect(keep).toBeDisabled();
    await user.click(keep);
    expect(onContinue).not.toHaveBeenCalled();

    await act(async () => resolve({ id: "bulk_restart_1", released: [{ task_id: "n1", revision_after: 5 }], skipped: [] }));
    expect(await screen.findByRole("button", { name: "Undo the 1" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Start the review" })).toBeEnabled();
  });

  it("020-FR-048 while an Undo is on its way Start the review waits", async () => {
    const user = userEvent.setup();
    bulkRelease.mockResolvedValueOnce({ id: "bulk_restart_1", released: [{ task_id: "n1", revision_after: 5 }], skipped: [] });
    let resolveUndo: (value: Awaited<ReturnType<typeof reviewApi.undoBulkRelease>>) => void = () => undefined;
    undoBulkRelease.mockReturnValueOnce(new Promise((done) => { resolveUndo = done; }));
    renderStep();

    await user.click(await screen.findByRole("button", { name: "Release 3 to Someday" }));
    await user.click(await screen.findByRole("button", { name: "Undo the 1" }));
    expect(screen.getByRole("button", { name: "Start the review" })).toBeDisabled();
    expect(onContinue).not.toHaveBeenCalled();
    await act(async () => resolveUndo({ restored: ["n1"], skipped: [] }));
  });

  it("020-FR-017 releasing shows Releasing…, then the new Next count with Undo and the way on", async () => {
    const user = userEvent.setup();
    let resolve: (value: Awaited<ReturnType<typeof reviewApi.bulkRelease>>) => void = () => undefined;
    bulkRelease.mockReturnValueOnce(new Promise((done) => { resolve = done; }));
    renderStep();

    await user.click(await screen.findByRole("button", { name: "Release 3 to Someday" }));
    expect(screen.getByRole("button", { name: "Releasing…" })).toBeDisabled();
    expect(bulkRelease).toHaveBeenCalledWith(
      { kind: "restart", items: [{ task_id: "n1", expected_revision: 4 }, { task_id: "n2", expected_revision: 4 }, { task_id: "n3", expected_revision: 4 }] },
      expect.any(String)
    );
    await act(async () => resolve({ id: "bulk_restart_1", released: [{ task_id: "n1", revision_after: 5 }, { task_id: "n2", revision_after: 5 }, { task_id: "n3", revision_after: 5 }], skipped: [] }));

    expect(await screen.findByText("3 tasks released to Someday / maybe. Next now holds 3 tasks.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Undo the 3" })).toBeInTheDocument();
    expect(readRelease("user-1")).toEqual({ kind: "restart", bulkId: "bulk_restart_1", sessionId: null, released: 3 });

    await user.click(screen.getByRole("button", { name: "Start the review" }));
    expect(onContinue).toHaveBeenCalledTimes(1);
    expect(readRelease("user-1")).toBeNull();
  });

  it("020-FR-011 tasks that changed meanwhile stay in Next, named, and Undo covers only the released", async () => {
    const user = userEvent.setup();
    bulkRelease.mockResolvedValueOnce({ id: "bulk_restart_1", released: [{ task_id: "n1", revision_after: 5 }], skipped: [{ task_id: "n2", reason: "stale" }, { task_id: "n3", reason: "not_eligible" }] });
    renderStep();

    await user.click(await screen.findByRole("button", { name: "Release 3 to Someday" }));

    expect(await screen.findByText("1 task released to Someday / maybe. Next now holds 5 tasks.")).toBeInTheDocument();
    expect(screen.getByText("2 tasks changed on another device in the meantime, so they stayed in Next.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Undo the 1" })).toBeInTheDocument();
  });

  it("020-FR-045 a release that fails moves nothing, shows the Ref and retries under the same key", async () => {
    const user = userEvent.setup();
    bulkRelease.mockRejectedValueOnce(new ApiError("down", 503, null, "corr_restart"));
    bulkRelease.mockResolvedValueOnce({ id: "bulk_restart_1", released: [{ task_id: "n1", revision_after: 5 }], skipped: [] });
    renderStep();

    await user.click(await screen.findByRole("button", { name: "Release 3 to Someday" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Couldn't release these tasks. Nothing was moved.");
    expect(alert).toHaveTextContent("Ref corr_restart");
    await user.click(within(alert).getByRole("button", { name: "Retry" }));

    expect(await screen.findByText("1 task released to Someday / maybe. Next now holds 5 tasks.")).toBeInTheDocument();
    expect(bulkRelease.mock.calls[1][1]).toBe(bulkRelease.mock.calls[0][1]);
  });

  it("020-FR-017 Undo puts every task back in Next as it was", async () => {
    const user = userEvent.setup();
    bulkRelease.mockResolvedValueOnce({ id: "bulk_restart_1", released: [{ task_id: "n1", revision_after: 5 }, { task_id: "n2", revision_after: 5 }, { task_id: "n3", revision_after: 5 }], skipped: [] });
    undoBulkRelease.mockResolvedValueOnce({ restored: ["n1", "n2", "n3"], skipped: [] });
    renderStep();
    await user.click(await screen.findByRole("button", { name: "Release 3 to Someday" }));

    await user.click(await screen.findByRole("button", { name: "Undo the 3" }));

    expect(await screen.findByText("Undone. All 3 are back in Next as they were.")).toBeInTheDocument();
    expect(undoBulkRelease).toHaveBeenCalledWith("bulk_restart_1", expect.any(String));
    expect(readRelease("user-1")).toBeNull();
    expect(screen.getByRole("button", { name: "Start the review" })).toBeInTheDocument();
  });

  it("020-FR-017 an Undo that could restore only some names the others", async () => {
    const user = userEvent.setup();
    bulkRelease.mockResolvedValueOnce({ id: "bulk_restart_1", released: [{ task_id: "n1", revision_after: 5 }, { task_id: "n2", revision_after: 5 }, { task_id: "n3", revision_after: 5 }], skipped: [] });
    undoBulkRelease.mockResolvedValueOnce({ restored: ["n1", "n2"], skipped: [{ task_id: "n3", reason: "stale" }] });
    renderStep();
    await user.click(await screen.findByRole("button", { name: "Release 3 to Someday" }));

    await user.click(await screen.findByRole("button", { name: "Undo the 3" }));

    expect(await screen.findByText("2 are back in Next. 1 changed on another device and stayed in Someday / maybe.")).toBeInTheDocument();
  });

  it("020-FR-045 an Undo that fails keeps Undo offered with the Ref and Retry", async () => {
    const user = userEvent.setup();
    bulkRelease.mockResolvedValueOnce({ id: "bulk_restart_1", released: [{ task_id: "n1", revision_after: 5 }, { task_id: "n2", revision_after: 5 }, { task_id: "n3", revision_after: 5 }], skipped: [] });
    undoBulkRelease.mockRejectedValueOnce(new ApiError("down", 503, null, "corr_undo_restart"));
    undoBulkRelease.mockResolvedValueOnce({ restored: ["n1", "n2", "n3"], skipped: [] });
    renderStep();
    await user.click(await screen.findByRole("button", { name: "Release 3 to Someday" }));

    await user.click(await screen.findByRole("button", { name: "Undo the 3" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Couldn't undo the release. The 3 tasks are still in Someday / maybe.");
    expect(alert).toHaveTextContent("Ref corr_undo_restart");
    expect(screen.getByRole("button", { name: "Undo the 3" })).toBeInTheDocument();
    await user.click(within(alert).getByRole("button", { name: "Retry" }));

    expect(await screen.findByText("Undone. All 3 are back in Next as they were.")).toBeInTheDocument();
    expect(undoBulkRelease.mock.calls[1][1]).toBe(undoBulkRelease.mock.calls[0][1]);
  });

  it("020-FR-017 after a tab reload the screen reopens on the release with Undo still offered", async () => {
    rememberRelease("user-1", { kind: "restart", bulkId: "bulk_restart_1", sessionId: null, released: 17 });
    renderStep();

    expect(await screen.findByText("17 tasks were released to Someday / maybe.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Undo the 17" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Start the review" })).toBeInTheDocument();
  });

  it("020-FR-017 someone set up but never reviewed gets the same offer with no wording about having been away", async () => {
    const { container } = renderStep(stateFixture({ restart_mode: true, last_counted_review_at: null, settings: { ...stateFixture().settings, onboarded_at: iso(-25 * DAY) } }));

    expect(await screen.findByRole("heading", { name: "Your first review" })).toBeInTheDocument();
    expect(screen.getByText("Let's make Next fit the week ahead.")).toBeInTheDocument();
    expect(await screen.findByText("3 next actions are older than 4 weeks")).toBeInTheDocument();
    expect(container.textContent).not.toMatch(/welcome back|gaps happen|were away|been away|your last review|days ago/i);
  });

  it("020-FR-017 with nothing older than four weeks it goes straight in", async () => {
    const user = userEvent.setup();
    listTasks.mockResolvedValue(page([young, paused]));
    renderStep();

    expect(await screen.findByText("Nothing in Next is older than 4 weeks, so let's go straight in.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Start the review" }));
    expect(onContinue).toHaveBeenCalledTimes(1);
  });

  it("020-FR-045 when Next cannot be read it says so with the Ref, retries, and still lets the review start", async () => {
    const user = userEvent.setup();
    listTasks.mockReset();
    listTasks.mockRejectedValueOnce(new ApiError("down", 503, null, "corr_next_read"));
    listTasks.mockResolvedValueOnce(page([old1]));
    renderStep();

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("We couldn't check your Next actions.");
    expect(alert).toHaveTextContent("Ref corr_next_read");
    await user.click(within(alert).getByRole("button", { name: "Start the review" }));
    expect(onContinue).toHaveBeenCalledTimes(1);
    await user.click(within(alert).getByRole("button", { name: "Retry" }));

    expect(await screen.findByText("1 next action is older than 4 weeks")).toBeInTheDocument();
  });
});
