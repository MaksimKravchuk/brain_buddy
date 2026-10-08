import { onlineManager, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "../../../api/client";
import { reviewApi, type ReviewSession, type ReviewQueue } from "../../../api/review";
import type { ProjectResponse, TaskResponse } from "../../../api/taskTypes";
import { ReviewShell } from "../ReviewShell";
import { DAY, iso, sessionFixture, signIn, stateFixture, taskFixture } from "./reviewKit";

// The real shell with the real steps: the discard question belongs to the shell, the forms to the steps.
vi.mock("../../../api/review", async () => {
  const actual = await vi.importActual<typeof import("../../../api/review")>("../../../api/review");
  return { ...actual, reviewApi: { ...actual.reviewApi, getQueue: vi.fn() } };
});
vi.mock("../../../api/client", async () => {
  const actual = await vi.importActual<typeof import("../../../api/client")>("../../../api/client");
  return { ...actual, apiClient: { ...actual.apiClient, listProjects: vi.fn() } };
});

const getQueue = vi.mocked(reviewApi.getQueue);
const listProjects = vi.mocked(apiClient.listProjects);

const drill = taskFixture({ id: "wait_1", title: "Pick up the drill from Sam", state: "waiting", waiting_for: "Sam", waiting_since: iso(-15 * DAY), revision: 4 });
const paper = taskFixture({ id: "inbox_1", title: "Buy printer paper", state: "inbox" });
const project: ProjectResponse = { id: "p_new", name: "New website", color: null, state: "active", revision: 1, open_task_count: 0 };

interface FormCase {
  name: string;
  step: NonNullable<ReviewSession["current_step"]>;
  items: TaskResponse[];
  open: (user: ReturnType<typeof userEvent.setup>) => Promise<void>;
  field: () => HTMLElement;
  /** The field's text before anything is typed. */
  initial: string;
  back: string;
  /** Still on screen after the form is gone. */
  stays: () => HTMLElement;
}

const cases: FormCase[] = [
  {
    name: "Waiting step: Create a follow-up",
    step: "waiting",
    items: [drill],
    open: async (user) => user.click(await screen.findByRole("button", { name: "Create a follow-up" })),
    field: () => screen.getByRole("textbox", { name: "What will you do to follow up?" }),
    initial: "",
    back: "Back",
    stays: () => screen.getByRole("heading", { name: drill.title })
  },
  {
    name: "Waiting step: Return to Next",
    step: "waiting",
    items: [drill],
    open: async (user) => user.click(await screen.findByRole("button", { name: "Return to Next" })),
    field: () => screen.getByRole("textbox", { name: "What's the next action now?" }),
    initial: drill.title,
    back: "Back",
    stays: () => screen.getByRole("heading", { name: drill.title })
  },
  {
    name: "Inbox step: Edit title",
    step: "inbox",
    items: [paper],
    open: async (user) => user.click(await screen.findByRole("button", { name: "Edit title" })),
    field: () => screen.getByRole("textbox", { name: "Title" }),
    initial: paper.title,
    back: "Back",
    stays: () => screen.getByRole("heading", { name: paper.title })
  },
  {
    name: "Inbox step: Waiting for",
    step: "inbox",
    items: [paper],
    open: async (user) => user.click(await screen.findByRole("button", { name: "Waiting for…" })),
    field: () => screen.getByRole("textbox", { name: "Who or what are you waiting for?" }),
    initial: "",
    back: "Back",
    stays: () => screen.getByRole("heading", { name: paper.title })
  },
  {
    name: "Projects step: next action",
    step: "projects",
    items: [],
    open: async (user) => user.click(await screen.findByRole("button", { name: "Add next action to New website" })),
    field: () => screen.getByRole("textbox", { name: "Next action for New website" }),
    initial: "",
    back: "Cancel",
    stays: () => screen.getByRole("button", { name: "Add next action to New website" })
  }
];

function renderShell(step: FormCase["step"], items: TaskResponse[]) {
  getQueue.mockResolvedValue({ items, meta: {} } satisfies ReviewQueue);
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter>
        <ReviewShell initial={sessionFixture({ current_step: step })} state={stateFixture()} onExit={vi.fn()} />
      </MemoryRouter>
    </QueryClientProvider>
  );
}

beforeEach(() => {
  window.localStorage.clear();
  signIn();
  listProjects.mockResolvedValue([project]);
});

afterEach(() => {
  cleanup();
  onlineManager.setOnline(true);
  vi.restoreAllMocks();
  getQueue.mockReset();
  listProjects.mockReset();
  window.localStorage.clear();
});

describe.each(cases)("020-FR-052 Back out of a form: $name", (form) => {
  async function typeIntoForm(user: ReturnType<typeof userEvent.setup>) {
    renderShell(form.step, form.items);
    await form.open(user);
    await user.type(form.field(), " edited");
  }

  it("020-FR-052 Back with typed text asks before it closes the form", async () => {
    const user = userEvent.setup();
    await typeIntoForm(user);

    await user.click(screen.getByRole("button", { name: form.back }));

    const dialog = screen.getByRole("alertdialog", { name: "Discard what you typed?" });
    expect(dialog).toHaveTextContent("It hasn't been saved.");
    expect(form.field()).toBeInTheDocument();
  });

  it("020-FR-052 confirming Discard closes the form and drops the text, and the step is left clean", async () => {
    const user = userEvent.setup();
    await typeIntoForm(user);
    await user.click(screen.getByRole("button", { name: form.back }));

    await user.click(screen.getByRole("button", { name: "Discard" }));

    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    expect(form.stays()).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Leave" }));
    expect(screen.getByRole("alertdialog", { name: "Take a break?" })).toBeInTheDocument();
  });

  it("020-FR-052 Keep editing leaves the form open with the text as it was", async () => {
    const user = userEvent.setup();
    await typeIntoForm(user);
    await user.click(screen.getByRole("button", { name: form.back }));

    await user.click(screen.getByRole("button", { name: "Keep editing" }));

    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    expect(form.field()).toHaveValue(`${form.initial} edited`);
  });

  it("020-FR-052 Back on a form with nothing typed closes at once without asking", async () => {
    const user = userEvent.setup();
    renderShell(form.step, form.items);
    await form.open(user);
    expect(form.field()).toHaveValue(form.initial);

    await user.click(screen.getByRole("button", { name: form.back }));

    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    expect(form.stays()).toBeInTheDocument();
  });
});
