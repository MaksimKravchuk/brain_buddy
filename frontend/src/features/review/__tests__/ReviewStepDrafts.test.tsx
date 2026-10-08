import { onlineManager, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "../../../api/client";
import { reviewApi, type DecisionResponse, type ReviewQueue, type ReviewSession } from "../../../api/review";
import type { ProjectResponse, TaskResponse } from "../../../api/taskTypes";
import { ReviewShell } from "../ReviewShell";
import { DAY, iso, sessionFixture, signIn, stateFixture, taskFixture } from "./reviewKit";

// The real shell with the real steps: the drafts belong to the steps, the Discard question to the shell.
vi.mock("../../../api/review", async () => {
  const actual = await vi.importActual<typeof import("../../../api/review")>("../../../api/review");
  return { ...actual, reviewApi: { ...actual.reviewApi, getQueue: vi.fn(), decide: vi.fn(), progress: vi.fn() } };
});
vi.mock("../../../api/client", async () => {
  const actual = await vi.importActual<typeof import("../../../api/client")>("../../../api/client");
  return { ...actual, apiClient: { ...actual.apiClient, listProjects: vi.fn(), createTask: vi.fn(), transitionTask: vi.fn(), updateTask: vi.fn() } };
});

const getQueue = vi.mocked(reviewApi.getQueue);
const decide = vi.mocked(reviewApi.decide);
const progress = vi.mocked(reviewApi.progress);
const listProjects = vi.mocked(apiClient.listProjects);
const createTask = vi.mocked(apiClient.createTask);
const transitionTask = vi.mocked(apiClient.transitionTask);
const updateTask = vi.mocked(apiClient.updateTask);

const drill = taskFixture({ id: "wait_1", title: "Pick up the drill from Sam", state: "waiting", waiting_for: "Sam", waiting_since: iso(-15 * DAY), revision: 4 });
const raised = taskFixture({ id: "sd_1", title: "Build a raised bed", state: "someday", revision: 5 });
const paper = taskFixture({ id: "inbox_1", title: "Buy printer paper", state: "inbox" });
const project: ProjectResponse = { id: "p_new", name: "New website", color: null, state: "active", revision: 1, open_task_count: 0 };

const DRAFT_PREFIX = "bb.reviewFormDraft.v1.";
const draftKeys = () => Object.keys(window.localStorage).filter((key) => key.startsWith(DRAFT_PREFIX));

interface FormCase {
  name: string;
  step: NonNullable<ReviewSession["current_step"]>;
  items: TaskResponse[];
  /** The draft key's step, item and field parts. */
  key: string;
  /** The button that opens the form; none for the mind-sweep line, which is always there. */
  trigger: string | null;
  field: () => HTMLElement;
  /** What is in the field before anything is typed. */
  initial: string;
  save: string;
  /** The form's own way out; none for the mind-sweep line. */
  back: string | null;
  /** The request that saves, once it has been made. */
  saved: () => unknown;
}

const cases: FormCase[] = [
  {
    name: "Mind sweep line",
    step: "mind_sweep",
    items: [],
    key: "step.review_1.mind_sweep.line.title",
    trigger: null,
    field: () => screen.getByRole("textbox", { name: "What's on your mind?" }),
    initial: "",
    save: "Add to Inbox",
    back: null,
    saved: () => createTask.mock.calls[0]
  },
  {
    name: "Inbox step: Edit title",
    step: "inbox",
    items: [paper],
    key: "step.review_1.inbox.inbox_1.title",
    trigger: "Edit title",
    field: () => screen.getByRole("textbox", { name: "Title" }),
    initial: paper.title,
    save: "Save title",
    back: "Back",
    saved: () => updateTask.mock.calls[0]
  },
  {
    name: "Inbox step: Waiting for",
    step: "inbox",
    items: [paper],
    key: "step.review_1.inbox.inbox_1.waiting",
    trigger: "Waiting for…",
    field: () => screen.getByRole("textbox", { name: "Who or what are you waiting for?" }),
    initial: "",
    save: "Move to Waiting for",
    back: "Back",
    saved: () => transitionTask.mock.calls[0]
  },
  {
    name: "Waiting step: Create a follow-up",
    step: "waiting",
    items: [drill],
    key: "step.review_1.waiting.wait_1.follow_up",
    trigger: "Create a follow-up",
    field: () => screen.getByRole("textbox", { name: "What will you do to follow up?" }),
    initial: "",
    save: "Save follow-up",
    back: "Back",
    saved: () => decide.mock.calls[0]
  },
  {
    name: "Waiting step: Return to Next",
    step: "waiting",
    items: [drill],
    key: "step.review_1.waiting.wait_1.return_to_next",
    trigger: "Return to Next",
    field: () => screen.getByRole("textbox", { name: "What's the next action now?" }),
    initial: drill.title,
    save: "Move to Next",
    back: "Back",
    saved: () => decide.mock.calls[0]
  },
  {
    name: "Someday step: Move to Next",
    step: "someday",
    items: [raised],
    key: "step.review_1.someday.sd_1.return_to_next",
    trigger: "Move to Next",
    field: () => screen.getByRole("textbox", { name: "What's the first concrete action?" }),
    initial: raised.title,
    save: "Move to Next",
    back: "Back",
    saved: () => decide.mock.calls[0]
  },
  {
    name: "Projects step: next action",
    step: "projects",
    items: [],
    key: "step.review_1.projects.p_new.next_action",
    trigger: "Add next action to New website",
    field: () => screen.getByRole("textbox", { name: "Next action for New website" }),
    initial: "",
    save: "Save next action",
    back: "Cancel",
    saved: () => createTask.mock.calls[0]
  }
];

function renderShell(form: FormCase) {
  getQueue.mockResolvedValue({ items: form.items, meta: {} } satisfies ReviewQueue);
  progress.mockResolvedValue(sessionFixture({ current_step: form.step }));
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter>
        <ReviewShell initial={sessionFixture({ current_step: form.step })} state={stateFixture()} onExit={vi.fn()} />
      </MemoryRouter>
    </QueryClientProvider>
  );
}

/** The step has shown its content: the form's trigger, or the always-there mind-sweep line. */
async function ready(form: FormCase) {
  return form.trigger === null ? screen.findByRole("textbox", { name: "What's on your mind?" }) : screen.findByRole("button", { name: form.trigger });
}

function decided(task: TaskResponse): DecisionResponse {
  return {
    decision: { id: `decision_${task.id}`, type: "return_to_next", task_id: task.id, session_id: "review_1", decided_at: iso(0), substantive: null, stall_reason: null, ai_use: "none", yielded_auto_park: false },
    task: { ...task, revision: task.revision + 1 },
    created_task: null,
    receipt: null,
    session_counts: null
  };
}

beforeEach(() => {
  window.localStorage.clear();
  signIn();
  listProjects.mockResolvedValue([project]);
  createTask.mockResolvedValue(taskFixture({ id: "t_new", title: "Saved" }));
  updateTask.mockResolvedValue({ ...paper, revision: paper.revision + 1 });
  transitionTask.mockResolvedValue({ ...paper, state: "waiting", revision: paper.revision + 1 });
  decide.mockImplementation(async (taskId) => decided([drill, raised].find((task) => task.id === taskId) as TaskResponse));
});

afterEach(() => {
  cleanup();
  onlineManager.setOnline(true);
  vi.restoreAllMocks();
  for (const mock of [getQueue, decide, progress, listProjects, createTask, transitionTask, updateTask]) {
    mock.mockReset();
  }
  window.localStorage.clear();
});

describe.each(cases)("020-FR-052 review-step drafts: $name", (form) => {
  async function typeIntoForm(user: ReturnType<typeof userEvent.setup>) {
    const view = renderShell(form);
    const opener = await ready(form);
    if (form.trigger !== null) {
      await user.click(opener);
    }
    // An empty field takes a whole line, a prefilled one an addition.
    const suffix = form.initial === "" ? "Call Sam" : " edited";
    await user.type(form.field(), suffix);
    return { view, typed: `${form.initial}${suffix}` };
  }

  it("020-FR-052 keeps the typed text under one account-scoped key and brings it back after a remount", async () => {
    const user = userEvent.setup();
    const { view, typed } = await typeIntoForm(user);
    expect(draftKeys()).toHaveLength(1);
    expect(draftKeys()[0]).toMatch(new RegExp(`^bb\\.reviewFormDraft\\.v1\\..+\\.user-1\\.${form.key.replace(/\./g, "\\.")}$`));
    expect(JSON.parse(window.localStorage.getItem(draftKeys()[0]) as string)).toMatchObject({ text: typed });

    view.unmount();
    renderShell(form);

    expect(await screen.findByDisplayValue(typed)).toBe(form.field());
    // The restored text counts as unsaved: leaving the step asks first.
    await user.click(screen.getByRole("button", { name: "Next" }));
    expect(screen.getByRole("alertdialog", { name: "Discard what you typed?" })).toBeInTheDocument();
  });

  it("020-FR-052 clears the draft once the text is saved", async () => {
    const user = userEvent.setup();
    const { view, typed } = await typeIntoForm(user);
    expect(draftKeys()).toHaveLength(1);

    await user.click(screen.getByRole("button", { name: form.save }));

    await waitFor(() => expect(form.saved()).toBeDefined());
    await waitFor(() => expect(draftKeys()).toEqual([]));
    view.unmount();
    renderShell(form);
    await ready(form);
    expect(screen.queryByDisplayValue(typed)).not.toBeInTheDocument();
  });

  if (form.back !== null) {
    it("020-FR-052 clears the draft when the form's Back is confirmed with Discard", async () => {
      const user = userEvent.setup();
      const { view, typed } = await typeIntoForm(user);
      expect(draftKeys()).toHaveLength(1);

      await user.click(screen.getByRole("button", { name: form.back as string }));
      await user.click(screen.getByRole("button", { name: "Discard" }));

      expect(draftKeys()).toEqual([]);
      view.unmount();
      renderShell(form);
      await ready(form);
      expect(screen.queryByDisplayValue(typed)).not.toBeInTheDocument();
    });
  }

  it("020-FR-052 clears the draft when the step is left with Discard", async () => {
    const user = userEvent.setup();
    const { view, typed } = await typeIntoForm(user);
    expect(draftKeys()).toHaveLength(1);

    await user.click(screen.getByRole("button", { name: "Next" }));
    await user.click(screen.getByRole("button", { name: "Discard" }));

    expect(draftKeys()).toEqual([]);
    view.unmount();
    renderShell(form);
    await ready(form);
    expect(screen.queryByDisplayValue(typed)).not.toBeInTheDocument();
  });

  it("020-FR-052 never writes a draft under another account's scope", async () => {
    const user = userEvent.setup();
    const { typed } = await typeIntoForm(user);
    const before = draftKeys();
    expect(before).toHaveLength(1);

    // The session changes account under the open step. A step that keeps its field on screen
    // (the queues are per account, so most go back to loading) writes nothing more, for anyone.
    act(() => signIn("user-2"));
    for (const field of screen.queryAllByRole("textbox")) {
      await user.type(field, " and more");
    }

    expect(draftKeys()).toEqual(before);
    expect(draftKeys().some((key) => key.includes(".user-2."))).toBe(false);
    expect(JSON.parse(window.localStorage.getItem(before[0]) as string)).toMatchObject({ text: typed });
  });
});

describe("020-FR-052 review-step drafts: who owns a draft", () => {
  it("020-FR-052 another account does not see a draft it did not write", async () => {
    const user = userEvent.setup();
    const [mindSweep] = cases;
    const view = renderShell(mindSweep);
    await user.type(await ready(mindSweep), "Call the plumber");
    expect(draftKeys()).toHaveLength(1);
    view.unmount();

    signIn("user-2");
    renderShell(mindSweep);

    expect(await ready(mindSweep)).toHaveValue("");
  });
});
