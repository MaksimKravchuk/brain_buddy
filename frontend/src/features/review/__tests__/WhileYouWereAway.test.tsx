import { onlineManager, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, apiClient } from "../../../api/client";
import { reviewApi, type UnseenPark } from "../../../api/review";
import { getTaskCacheScope, taskKeys } from "../../../api/taskHooks";
import type { ProjectResponse, TaskResponse } from "../../../api/taskTypes";
import { useAuthStore } from "../../../stores/authStore";
import { formatReviewDate } from "../formulation";
import { WhileYouWereAway } from "../WhileYouWereAway";

vi.mock("../../../api/client", async () => {
  const actual = await vi.importActual<typeof import("../../../api/client")>("../../../api/client");
  return { ...actual, apiClient: { ...actual.apiClient, getTask: vi.fn(), listProjects: vi.fn(), transitionTask: vi.fn() } };
});
vi.mock("../../../api/review", async () => {
  const actual = await vi.importActual<typeof import("../../../api/review")>("../../../api/review");
  return { ...actual, reviewApi: { ...actual.reviewApi, acknowledgeParks: vi.fn(), getState: vi.fn() } };
});
const getTask = vi.mocked(apiClient.getTask);
const listProjects = vi.mocked(apiClient.listProjects);
const transitionTask = vi.mocked(apiClient.transitionTask);
const acknowledgeParks = vi.mocked(reviewApi.acknowledgeParks);

const projects: ProjectResponse[] = [
  { id: "project-personal", name: "Personal", color: null, state: "active", revision: 1, open_task_count: 1 },
  { id: "project-home", name: "Home", color: null, state: "active", revision: 1, open_task_count: 1 },
  { id: "project-old", name: "Old flat", color: null, state: "archived", revision: 3, open_task_count: 0 }
];

function parked(id: string, title: string, projectId: string | null, parkedAt: string): TaskResponse {
  return {
    id,
    title,
    details: null,
    state: "someday",
    project_id: projectId,
    tag_ids: [],
    due_date: null,
    priority: "none",
    waiting_for: null,
    waiting_since: null,
    order_key: 1,
    source_capture_ids: [],
    created_at: "2026-08-01T10:00:00Z",
    updated_at: parkedAt,
    completed_at: null,
    cancelled_at: null,
    revision: 5,
    formulation: null,
    parked: { at: parkedAt, formulation_id: `form_${id}` }
  };
}

const portuguese = parked("task-pt", "Learn basic Portuguese", "project-personal", "2026-10-08T09:14:03Z");
const garage = parked("task-garage", "Clean out the garage", "project-home", "2026-10-08T09:14:05Z");
const cv = parked("task-cv", "Update the CV", null, "2026-10-06T09:14:00Z");
const router = parked("task-router", "Return the old router", "project-old", "2026-10-08T09:14:07Z");
const park = (task: TaskResponse): UnseenPark => ({ task_id: task.id, formulation_id: `form_${task.id}`, parked_at: task.parked?.at as string });

const onDone = vi.fn();

function renderDialog(tasks: TaskResponse[], parks: UnseenPark[] = tasks.map(park), load?: (id: string) => Promise<TaskResponse>) {
  getTask.mockImplementation(load ?? (async (id) => {
    const task = tasks.find((candidate) => candidate.id === id);
    if (!task) throw new ApiError("Not found", 404, null, "corr_missing");
    return task;
  }));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <WhileYouWereAway parks={parks} onDone={onDone} />
    </QueryClientProvider>
  );
  return client;
}

const dialog = () => screen.getByRole("dialog", { name: "While you were away" });
const row = (title: string) => screen.getByRole("listitem", { name: title });

beforeEach(() => {
  act(() => {
    useAuthStore.setState({ user: { id: "user-1", email: "max@example.test", feature_flags: { weekly_review: true } }, status: "authed" });
  });
  listProjects.mockResolvedValue(projects);
  transitionTask.mockImplementation(async (id, payload) => ({ ...(await getTask(id)), state: "next", parked: null, revision: payload.expected_revision + 1 }));
});

afterEach(() => {
  cleanup();
  onlineManager.setOnline(true);
  vi.restoreAllMocks();
  getTask.mockReset();
  listProjects.mockReset();
  transitionTask.mockReset();
  acknowledgeParks.mockReset();
  onDone.mockReset();
});

describe("020-FR-015 While you were away dialog", () => {
  it("020-FR-015 lists each parked task with its day and project, focus on the heading", async () => {
    renderDialog([portuguese, garage, cv]);

    expect(screen.getByRole("heading", { name: "While you were away" })).toHaveFocus();
    expect(dialog()).toHaveAttribute("aria-modal", "true");
    expect(dialog()).toHaveTextContent("These 3 tasks stayed undecided, so they moved to Someday / maybe to keep Next honest. Nothing was deleted. Bring back anything that still matters.");
    await screen.findByText("Learn basic Portuguese");
    await waitFor(() => expect(within(row("Learn basic Portuguese")).getByText(`Parked ${formatReviewDate(portuguese.parked?.at as string)} · Personal`)).toBeInTheDocument());
    expect(within(row("Update the CV")).getByText(`Parked ${formatReviewDate(cv.parked?.at as string)} · no project`)).toBeInTheDocument();
    expect(within(row("Clean out the garage")).getByRole("button", { name: "Return Clean out the garage to Next" })).toHaveTextContent("Return to Next");
    expect(screen.getByRole("button", { name: "Return all 3 to Next" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Continue" })).toBeInTheDocument();
  });

  it("020-FR-015 returns one task, showing Returning… on that row only, then confirms it in words", async () => {
    const user = userEvent.setup();
    let release: () => void = () => undefined;
    transitionTask.mockImplementationOnce((_id, payload) => new Promise((resolve) => {
      release = () => resolve({ ...garage, state: "next", parked: null, revision: payload.expected_revision + 1 });
    }));
    renderDialog([portuguese, garage, cv]);

    await user.click(await screen.findByRole("button", { name: "Return Clean out the garage to Next" }));
    expect(within(row("Clean out the garage")).getByText("Returning…")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Return Learn basic Portuguese to Next" })).toBeEnabled();
    expect(transitionTask).toHaveBeenCalledWith("task-garage", { action: "move", to_state: "next", expected_revision: 5 }, expect.any(String));

    await act(async () => release());
    expect(within(row("Clean out the garage")).getByText("Back in Next with a fresh start")).toBeInTheDocument();
    expect(within(row("Clean out the garage")).getByText("Returned")).toBeInTheDocument();
    expect(within(row("Clean out the garage")).queryByRole("button")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Return both to Next" })).toBeInTheDocument();
  });

  it("020-FR-015 020-FR-042 a return answered after the account signed out and another signed in leaves the new account's caches alone", async () => {
    const user = userEvent.setup();
    let release: () => void = () => undefined;
    transitionTask.mockImplementationOnce((_id, payload) => new Promise((resolve) => {
      release = () => resolve({ ...cv, state: "next", parked: null, revision: payload.expected_revision + 1 });
    }));
    const client = renderDialog([portuguese, cv]);
    await user.click(await screen.findByRole("button", { name: "Return Update the CV to Next" }));

    act(() => useAuthStore.setState({ user: { id: "user-2", email: "b@example.test", feature_flags: { weekly_review: true } }, status: "authed" }));
    // B's Someday list, which happens to hold a task with the same id.
    const listB = [...taskKeys.lists(getTaskCacheScope("user-2")), { state: "someday" }];
    const seeded = { pages: [{ items: [{ ...cv, title: "B's copy" }] }], pageParams: [null] };
    client.setQueryData(listB, seeded);
    await act(async () => release());

    expect(client.getQueryData(listB)).toEqual(seeded);
    expect(client.getQueryState(listB)?.isInvalidated).toBe(false);
    expect(client.getQueryData(taskKeys.detail(cv.id, getTaskCacheScope("user-1")))).toEqual(cv);
  });

  it("020-FR-015 returning waits until the projects are known, so an archived project's task is never offered back", async () => {
    let releaseProjects: () => void = () => undefined;
    listProjects.mockReset();
    listProjects.mockImplementationOnce(() => new Promise((resolve) => {
      releaseProjects = () => resolve(projects);
    }));
    renderDialog([portuguese, garage, router]);

    await screen.findByText("Return the old router");
    for (const name of ["Return Learn basic Portuguese to Next", "Return Clean out the garage to Next", "Return Return the old router to Next"]) {
      expect(screen.getByRole("button", { name })).toBeDisabled();
    }
    expect(screen.getByRole("button", { name: "Return all 3 to Next" })).toBeDisabled();
    expect(within(row("Return the old router")).getByText(`Parked ${formatReviewDate(router.parked?.at as string)}`)).toBeInTheDocument();
    expect(within(dialog()).queryByText(/no project/)).not.toBeInTheDocument();

    await act(async () => releaseProjects());

    expect(await within(row("Return the old router")).findByRole("button", { name: "Return unavailable: project Old flat is archived" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Return Learn basic Portuguese to Next" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Return both to Next" })).toBeEnabled();
    expect(transitionTask).not.toHaveBeenCalled();
  });

  it("020-FR-015 020-FR-045 projects that fail to load keep returning disabled, say so with the Ref, and Retry loads them", async () => {
    const user = userEvent.setup();
    listProjects.mockReset();
    listProjects.mockRejectedValueOnce(new ApiError("Server Error", 500, null, "corr_projects")).mockResolvedValueOnce(projects);
    renderDialog([portuguese, garage, router]);

    const alert = await screen.findByText("We couldn't load your projects, so tasks can't be returned yet.");
    expect(alert.parentElement).toHaveTextContent("Ref corr_projects");
    expect(screen.getByRole("button", { name: "Return Return the old router to Next" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Return all 3 to Next" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Continue" })).toBeEnabled();

    await user.click(within(alert.parentElement as HTMLElement).getByRole("button", { name: "Retry" }));

    expect(await within(row("Return the old router")).findByRole("button", { name: "Return unavailable: project Old flat is archived" })).toBeInTheDocument();
    expect(screen.queryByText("We couldn't load your projects, so tasks can't be returned yet.")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Return both to Next" })).toBeEnabled();
  });

  it("020-FR-045 a failed return says so on its row with the Ref, and Retry resends it", async () => {
    const user = userEvent.setup();
    transitionTask.mockRejectedValueOnce(new ApiError("Couldn't reach Brain Buddy", 0, null, "corr_return"));
    renderDialog([portuguese, cv]);

    await user.click(await screen.findByRole("button", { name: "Return Update the CV to Next" }));

    const message = await within(row("Update the CV")).findByRole("alert");
    expect(message).toHaveTextContent("Couldn't return “Update the CV” to Next. It's still in Someday / maybe.");
    expect(message).toHaveTextContent("Ref corr_return");
    await user.click(within(message).getByRole("button", { name: "Retry" }));

    await within(row("Update the CV")).findByText("Returned");
    expect(transitionTask.mock.calls[1][2]).toBe(transitionTask.mock.calls[0][2]);
  });

  it("020-FR-011 a task changed on another device is left as it is there", async () => {
    const user = userEvent.setup();
    transitionTask.mockRejectedValueOnce(new ApiError("Conflict", 409, { message: "stale", detail: { resource: "task", id: "task-cv" } }, "corr_stale"));
    renderDialog([portuguese, cv]);
    await screen.findByRole("button", { name: "Return Update the CV to Next" });
    getTask.mockResolvedValueOnce({ ...cv, state: "next", parked: null, revision: 7 });

    await user.click(screen.getByRole("button", { name: "Return Update the CV to Next" }));

    expect(await screen.findByText("“Update the CV” changed on another device, so it was left as it is there.")).toBeInTheDocument();
    expect(within(row("Update the CV")).getByText("Now in Next actions")).toBeInTheDocument();
    expect(within(row("Update the CV")).queryByRole("button")).not.toBeInTheDocument();
  });

  it("020-FR-011 a changed task whose current list cannot be read is still left alone", async () => {
    const user = userEvent.setup();
    transitionTask.mockRejectedValueOnce(new ApiError("Conflict", 409, null, "corr_stale"));
    renderDialog([portuguese, cv]);
    await screen.findByRole("button", { name: "Return Update the CV to Next" });
    getTask.mockRejectedValueOnce(new Error("offline"));

    await user.click(screen.getByRole("button", { name: "Return Update the CV to Next" }));

    expect(await screen.findByText("“Update the CV” changed on another device, so it was left as it is there.")).toBeInTheDocument();
    expect(within(row("Update the CV")).getByText("Now in Someday / maybe")).toBeInTheDocument();
  });

  it("020-FR-015 Return all brings back every returnable task and names the one an archived project holds", async () => {
    const user = userEvent.setup();
    renderDialog([portuguese, garage, cv, router]);

    const archived = await within(await screen.findByRole("listitem", { name: "Return the old router" })).findByRole("button", { name: "Return unavailable: project Old flat is archived" });
    expect(archived).toHaveAttribute("aria-disabled", "true");
    expect(archived).toHaveTextContent("Project archived");
    expect(within(row("Return the old router")).getByText(`Parked ${formatReviewDate(router.parked?.at as string)} · Old flat (archived)`)).toBeInTheDocument();
    await user.click(archived);
    expect(transitionTask).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "Return all 3 to Next" }));

    expect(await screen.findByText("3 tasks are back in Next. “Return the old router” stayed in Someday because its project “Old flat” is archived. Restore the project first to bring it back.")).toBeInTheDocument();
    expect(transitionTask).toHaveBeenCalledTimes(3);
    expect(transitionTask.mock.calls.map(([id]) => id)).toEqual(["task-pt", "task-garage", "task-cv"]);
  });

  it("020-FR-015 offers Return all only while at least two tasks can still go back", async () => {
    const user = userEvent.setup();
    renderDialog([portuguese, garage, router]);
    await screen.findByRole("button", { name: "Return unavailable: project Old flat is archived" });
    await user.click(await screen.findByRole("button", { name: "Return Learn basic Portuguese to Next" }));
    await within(row("Learn basic Portuguese")).findByText("Returned");

    expect(screen.queryByRole("button", { name: /Return the other|Return both/ })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Return Clean out the garage to Next" }));
    await within(row("Clean out the garage")).findByText("Returned");
    expect(screen.queryByText(/back in Next\./)).not.toBeInTheDocument();
  });

  it("020-FR-015 Return all names a row that failed on that row and claims nothing for it", async () => {
    const user = userEvent.setup();
    transitionTask
      .mockImplementationOnce(async (_id, payload) => ({ ...portuguese, state: "next", parked: null, revision: payload.expected_revision + 1 }))
      .mockRejectedValueOnce(new ApiError("Server Error", 500, null, "corr_all"));
    renderDialog([portuguese, cv]);

    await user.click(await screen.findByRole("button", { name: "Return both to Next" }));

    expect(await within(row("Update the CV")).findByRole("alert")).toHaveTextContent("Ref corr_all");
    expect(within(row("Learn basic Portuguese")).getByText("Returned")).toBeInTheDocument();
    expect(screen.queryByText(/back in Next/)).not.toBeInTheDocument();
  });

  it("020-FR-015 Return the other N after one was returned, and one archived row left behind, counts every task back in Next", async () => {
    const user = userEvent.setup();
    renderDialog([portuguese, garage, cv, router, parked("task-shed", "Paint the shed", "project-home", "2026-10-07T09:00:00Z")]);
    await user.click(await screen.findByRole("button", { name: "Return Update the CV to Next" }));
    await within(row("Update the CV")).findByText("Returned");

    await user.click(screen.getByRole("button", { name: "Return the other 3 to Next" }));

    expect(await screen.findByText("4 tasks are back in Next. “Return the old router” stayed in Someday because its project “Old flat” is archived. Restore the project first to bring it back.")).toBeInTheDocument();
    expect(transitionTask).toHaveBeenCalledTimes(4);
  });

  it("020-FR-015 Return all where only one could go back reads in the singular", async () => {
    const user = userEvent.setup();
    transitionTask
      .mockImplementationOnce(async (_id, payload) => ({ ...portuguese, state: "next", parked: null, revision: payload.expected_revision + 1 }))
      .mockRejectedValueOnce(new ApiError("Server Error", 500, null, "corr_one"));
    renderDialog([portuguese, garage, router]);
    await screen.findByRole("button", { name: "Return unavailable: project Old flat is archived" });

    await user.click(await screen.findByRole("button", { name: "Return both to Next" }));

    expect(await screen.findByText("1 task is back in Next. “Return the old router” stayed in Someday because its project “Old flat” is archived. Restore the project first to bring it back.")).toBeInTheDocument();
  });

  it("020-FR-015 Return all with nothing in the way says all are back", async () => {
    const user = userEvent.setup();
    renderDialog([portuguese, garage]);

    await user.click(await screen.findByRole("button", { name: "Return both to Next" }));

    expect(await screen.findByText("All 2 are back in Next with a fresh start.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Return/ })).not.toBeInTheDocument();
  });

  it("020-FR-015 a single park reads in the singular and needs no Return all", async () => {
    renderDialog([cv]);
    expect(dialog()).toHaveTextContent("This task stayed undecided, so it moved to Someday / maybe to keep Next honest. Nothing was deleted. Bring it back if it still matters.");
    await screen.findByRole("button", { name: "Return Update the CV to Next" });
    expect(screen.queryByRole("button", { name: /Return all|Return both/ })).not.toBeInTheDocument();
  });

  it("020-FR-040 offline the list stays and returning is disabled with the reason", async () => {
    vi.spyOn(navigator, "onLine", "get").mockReturnValue(false);
    renderDialog([portuguese, garage]);

    expect(await screen.findByRole("button", { name: "Return Learn basic Portuguese to Next" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Return both to Next" })).toBeDisabled();
    expect(dialog()).toHaveTextContent("You're offline. Returning tasks needs a connection.");
  });

  it("020-FR-015 Continue marks every park seen, including one whose task could not be loaded", async () => {
    const user = userEvent.setup();
    acknowledgeParks.mockResolvedValueOnce(undefined);
    const gone: UnseenPark = { task_id: "task-gone", formulation_id: "form_task-gone", parked_at: "2026-10-07T09:00:00Z" };
    renderDialog([portuguese], [park(portuguese), gone]);

    await screen.findByText("Learn basic Portuguese");
    await user.click(screen.getByRole("button", { name: "Continue" }));

    await waitFor(() => expect(onDone).toHaveBeenCalledWith(true));
    expect(acknowledgeParks).toHaveBeenCalledWith(
      { items: [{ task_id: "task-pt", formulation_id: "form_task-pt" }, { task_id: "task-gone", formulation_id: "form_task-gone" }] },
      expect.any(String)
    );
    expect(screen.queryByText("Update the CV")).not.toBeInTheDocument();
  });

  it("020-FR-015 Continue waits until every park's task has loaded, and never marks a park seen that it could not show", async () => {
    const user = userEvent.setup();
    acknowledgeParks.mockResolvedValueOnce(undefined);
    const gone: UnseenPark = { task_id: "task-gone", formulation_id: "form_task-gone", parked_at: "2026-10-07T09:00:00Z" };
    let releaseGarage: () => void = () => undefined;
    let failCv: () => void = () => undefined;
    renderDialog([portuguese], [park(portuguese), park(garage), park(cv), gone], (id) => {
      if (id === garage.id) return new Promise((resolve) => { releaseGarage = () => resolve(garage); });
      if (id === cv.id) return new Promise((_resolve, reject) => { failCv = () => reject(new ApiError("Server Error", 503, null, "corr_load")); });
      if (id === portuguese.id) return Promise.resolve(portuguese);
      return Promise.reject(new ApiError("Not found", 404, null, "corr_missing"));
    });

    await screen.findByText("Learn basic Portuguese");
    expect(screen.getByRole("button", { name: "Continue" })).toBeDisabled();

    await act(async () => releaseGarage());
    await screen.findByText("Clean out the garage");
    expect(screen.getByRole("button", { name: "Continue" })).toBeDisabled();

    await act(async () => failCv());
    await waitFor(() => expect(screen.getByRole("button", { name: "Continue" })).toBeEnabled());
    await user.click(screen.getByRole("button", { name: "Continue" }));

    await waitFor(() => expect(onDone).toHaveBeenCalledWith(true));
    // The transiently unreadable park stays unseen, so it comes back next time;
    // the one whose task is gone (404) is confirmed and marked seen.
    expect(acknowledgeParks).toHaveBeenCalledWith(
      {
        items: [
          { task_id: "task-pt", formulation_id: "form_task-pt" },
          { task_id: "task-garage", formulation_id: "form_task-garage" },
          { task_id: "task-gone", formulation_id: "form_task-gone" }
        ]
      },
      expect.any(String)
    );
  });

  it("020-FR-015 when no park's task could be read, Continue closes without marking anything seen", async () => {
    const user = userEvent.setup();
    renderDialog([], [park(cv)], () => Promise.reject(new ApiError("Couldn't reach Brain Buddy", 0, null, "corr_net")));

    await waitFor(() => expect(screen.getByRole("button", { name: "Continue" })).toBeEnabled());
    await user.click(screen.getByRole("button", { name: "Continue" }));

    expect(onDone).toHaveBeenCalledWith(false);
    expect(acknowledgeParks).not.toHaveBeenCalled();
  });

  it("020-FR-045 failures without a reference show no empty Ref line", async () => {
    const user = userEvent.setup();
    transitionTask.mockRejectedValueOnce(new Error("socket hang up"));
    acknowledgeParks.mockRejectedValueOnce(new Error("socket hang up"));
    renderDialog([portuguese, cv]);

    await user.click(await screen.findByRole("button", { name: "Return Update the CV to Next" }));
    const message = await within(row("Update the CV")).findByRole("alert");
    expect(message).toHaveTextContent("Couldn't return “Update the CV” to Next. It's still in Someday / maybe.");
    expect(message).not.toHaveTextContent(/Ref/);

    await user.click(screen.getByRole("button", { name: "Continue" }));
    const alert = await screen.findByText("Couldn't save that you've seen these. Try again.");
    expect(alert.parentElement).not.toHaveTextContent(/Ref/);
  });

  it("020-FR-045 Continue not saved keeps the dialog with the Ref; Retry sends the same request", async () => {
    const user = userEvent.setup();
    acknowledgeParks.mockRejectedValueOnce(new ApiError("Server Error", 500, null, "corr_ack")).mockResolvedValueOnce(undefined);
    renderDialog([portuguese, cv]);

    await screen.findByText("Update the CV");
    await user.click(screen.getByRole("button", { name: "Continue" }));

    const alert = await screen.findByText("Couldn't save that you've seen these. Try again.");
    expect(alert.parentElement).toHaveTextContent("Ref corr_ack");
    expect(onDone).not.toHaveBeenCalled();
    await user.click(within(alert.parentElement as HTMLElement).getByRole("button", { name: "Retry" }));

    await waitFor(() => expect(onDone).toHaveBeenCalledWith(true));
    expect(acknowledgeParks.mock.calls[1]).toEqual(acknowledgeParks.mock.calls[0]);
  });

  it.each([
    ["Escape", async (user: ReturnType<typeof userEvent.setup>) => user.keyboard("{Escape}")],
    ["Close", async (user: ReturnType<typeof userEvent.setup>) => user.click(screen.getByRole("button", { name: "Close" }))]
  ])("020-FR-015 %s closes without marking anything seen", async (_label, close) => {
    const user = userEvent.setup();
    renderDialog([portuguese, cv]);

    await close(user);

    expect(onDone).toHaveBeenCalledWith(false);
    expect(acknowledgeParks).not.toHaveBeenCalled();
  });

  it("020-FR-015 keeps focus inside the dialog", async () => {
    const user = userEvent.setup();
    renderDialog([portuguese, cv]);
    await screen.findByRole("button", { name: "Return Learn basic Portuguese to Next" });

    const close = screen.getByRole("button", { name: "Close" });
    const continueButton = screen.getByRole("button", { name: "Continue" });
    continueButton.focus();
    await user.tab();
    expect(close).toHaveFocus();
    await user.tab({ shift: true });
    expect(continueButton).toHaveFocus();
    screen.getByRole("heading", { name: "While you were away" }).focus();
    await user.tab({ shift: true });
    expect(continueButton).toHaveFocus();
    await user.tab();
    await user.tab();
    expect(screen.getByRole("button", { name: "Return Learn basic Portuguese to Next" })).toHaveFocus();
  });
});
