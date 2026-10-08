/**
 * The shell's Next waits for the showing step's queue (design D-03): the real
 * shell with the real steps, only the network mocked. While a step's tasks are
 * loading, or failed to load, finishing the step would leave them unreviewed
 * and unseen, and would bypass the failure's Retry or Skip step.
 */
import { onlineManager, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, apiClient } from "../../../api/client";
import { reviewApi } from "../../../api/review";
import type { ReviewQueue, ReviewSession, StepCode } from "../../../api/review";
import { ShellToastContext } from "../../../components/shell/shellToast";
import { ReviewShell } from "../ReviewShell";
import { notify, sessionFixture, signIn, stateFixture } from "./reviewKit";

vi.mock("../../../api/review", async () => {
  const actual = await vi.importActual<typeof import("../../../api/review")>("../../../api/review");
  return { ...actual, reviewApi: { ...actual.reviewApi, getQueue: vi.fn(), progress: vi.fn() } };
});
vi.mock("../../../api/client", async () => {
  const actual = await vi.importActual<typeof import("../../../api/client")>("../../../api/client");
  return { ...actual, apiClient: { ...actual.apiClient, listProjects: vi.fn() } };
});

const getQueue = vi.mocked(reviewApi.getQueue);
const progress = vi.mocked(reviewApi.progress);

const empty: ReviewQueue = { items: [], meta: {} };
/** What a step reads from its queue once it has loaded: the 14 days step needs its day list. */
const loadedFor = (step: StepCode): ReviewQueue => (step === "dates" ? { items: [], meta: { days: [] } } : empty);

function deferred<T>() {
  let resolve: (value: T) => void = () => undefined;
  let reject: (error: unknown) => void = () => undefined;
  const promise = new Promise<T>((done, fail) => {
    resolve = done;
    reject = fail;
  });
  return { promise, resolve, reject };
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
/** The bar's Skip step; a load failure's banner carries a second one. */
const barSkip = () => screen.getAllByRole("button", { name: "Skip step" })[0];

/** Every step that shows a queue, with the heading its page carries. */
const QUEUE_STEPS: Array<[StepCode, string]> = [
  ["wins", "Wins of the week"],
  ["inbox", "Inbox"],
  ["decisions", "Tasks that ask for a decision"],
  ["rest_of_next", "The rest of Next"],
  ["waiting", "Waiting for, older than 7 days"],
  ["projects", "Projects without a next action"],
  ["someday", "Someday / maybe"],
  ["dates", "The next 14 days"]
];

beforeEach(() => {
  window.localStorage.clear();
  signIn();
  vi.mocked(apiClient.listProjects).mockResolvedValue([]);
});

afterEach(() => {
  cleanup();
  onlineManager.setOnline(true);
  vi.restoreAllMocks();
  getQueue.mockReset();
  progress.mockReset();
  notify.mockReset();
  window.localStorage.clear();
});

describe("020-FR-029 020-FR-045 Next waits for the step's queue to load", () => {
  it.each(QUEUE_STEPS)("020-FR-029 the %s step keeps Next disabled while its queue loads and enables it once loaded", async (step, title) => {
    const loading = deferred<ReviewQueue>();
    getQueue.mockReturnValue(loading.promise);
    renderShell(sessionFixture({ current_step: step }));
    await screen.findByRole("heading", { level: 1, name: title });

    expect(await screen.findByRole("status", { name: "Loading this step" })).toBeInTheDocument();
    expect(next()).toBeDisabled();
    expect(barSkip()).toBeEnabled();

    await act(async () => loading.resolve(loadedFor(step)));
    await waitFor(() => expect(screen.queryByRole("status", { name: "Loading this step" })).not.toBeInTheDocument());
    expect(next()).toBeEnabled();
  });

  it.each(QUEUE_STEPS)("020-FR-045 the %s step keeps Next disabled on a load failure, with Retry and Skip step on offer", async (step) => {
    getQueue.mockRejectedValue(new ApiError("down", 503, null, "corr_load"));
    renderShell(sessionFixture({ current_step: step }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("We couldn't load this step.");
    expect(alert).toHaveTextContent("Ref corr_load");
    expect(next()).toBeDisabled();
    expect(within(alert).getByRole("button", { name: "Retry" })).toBeEnabled();
    expect(within(alert).getByRole("button", { name: "Skip step" })).toBeEnabled();
    expect(barSkip()).toBeEnabled();
  });

  it("020-FR-045 a Retry that loads the queue enables Next, and the failure never finished the step", async () => {
    const user = userEvent.setup();
    getQueue.mockRejectedValueOnce(new ApiError("down", 503, null, "corr_load"));
    getQueue.mockResolvedValue(empty);
    renderShell(sessionFixture({ current_step: "waiting" }));
    const alert = await screen.findByRole("alert");
    expect(next()).toBeDisabled();

    await user.click(within(alert).getByRole("button", { name: "Retry" }));

    await waitFor(() => expect(next()).toBeEnabled());
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(progress).not.toHaveBeenCalled();
  });

  it("020-FR-029 Skip step on a load failure skips the step, and the next step starts with its own state", async () => {
    const user = userEvent.setup();
    getQueue.mockRejectedValueOnce(new ApiError("down", 503, null, "corr_load"));
    getQueue.mockReturnValue(deferred<ReviewQueue>().promise);
    progress.mockImplementation(async (attempt) =>
      sessionFixture({
        current_step: attempt.body.current_step,
        steps: { ...sessionFixture().steps, [attempt.body.step?.code as StepCode]: "skipped" }
      })
    );
    renderShell(sessionFixture({ current_step: "inbox" }));
    const alert = await screen.findByRole("alert");

    await user.click(within(alert).getByRole("button", { name: "Skip step" }));

    expect(progress.mock.calls[0][0].body).toMatchObject({ step: { code: "inbox", status: "skipped" } });
    await screen.findByRole("heading", { level: 1, name: "Tasks that ask for a decision" });
    // The decisions queue is still loading, so it holds Next itself; the failed step's hold is not what does.
    expect(await screen.findByRole("status", { name: "Loading this step" })).toBeInTheDocument();
    expect(next()).toBeDisabled();
  });

  it("020-FR-029 a hold from the step before never reaches a step without a queue", async () => {
    const user = userEvent.setup();
    getQueue.mockReturnValue(deferred<ReviewQueue>().promise);
    progress.mockImplementation(async (attempt) =>
      sessionFixture({ current_step: attempt.body.current_step, steps: { ...sessionFixture().steps, wins: "skipped" } })
    );
    renderShell(sessionFixture({ current_step: "wins" }));
    await screen.findByRole("status", { name: "Loading this step" });
    expect(next()).toBeDisabled();

    await user.click(barSkip());

    await screen.findByRole("heading", { level: 1, name: "Mind sweep" });
    expect(next()).toBeEnabled();
  });

  it("020-FR-029 the Mind sweep has no queue, so Next is never held for one", async () => {
    getQueue.mockReturnValue(deferred<ReviewQueue>().promise);
    renderShell(sessionFixture({ current_step: "mind_sweep" }));
    await screen.findByRole("heading", { level: 1, name: "Mind sweep" });

    expect(next()).toBeEnabled();
    expect(barSkip()).toBeEnabled();
    expect(getQueue).not.toHaveBeenCalled();
  });

  it("020-FR-029 the Summary has no queue and no Next", async () => {
    renderShell(sessionFixture({ current_step: "summary" }));
    await screen.findByRole("heading", { level: 1, name: "Review done" });

    expect(screen.queryByRole("button", { name: "Next" })).not.toBeInTheDocument();
    expect(getQueue).not.toHaveBeenCalled();
  });
});
