import { fireEvent, screen, waitFor } from "@testing-library/react-native";

import type { TaskResponse } from "@/api/types";
import { setSearchParams } from "@/test/expoRouterMock";
import {
  FakeHttpError,
  installFakeBackend,
  makeMe,
  makeProject,
  makeTag,
  makeTask,
  type FakeBackend,
} from "@/test/fakeBackend";
import { renderWithSession } from "@/test/harness";

import TaskDetailScreen from "../[id]";

let backend: FakeBackend;

afterEach(() => backend?.restore());

const BASE_ROUTES = {
  "GET /auth/me": () => makeMe({ email: "dana.reid@example.test" }),
  "GET /projects": () => [makeProject({ id: "p1", name: "Wedding" })],
  "GET /tags": () => [makeTag({ id: "g1", name: "errand" })],
};

/** Mount the detail screen for `task`, with any extra routes merged in. */
async function openTask(
  task: TaskResponse,
  routes: Record<string, (call: never) => unknown> = {},
) {
  backend = installFakeBackend({
    ...BASE_ROUTES,
    [`GET /tasks/${task.id}`]: () => task,
    ...routes,
  } as never);
  setSearchParams({ id: task.id, from: "Next actions" });
  const rendered = await renderWithSession(<TaskDetailScreen />);
  await screen.findByDisplayValue(task.title);
  return rendered;
}

describe("task detail — loading and failure", () => {
  it("shows neither the editor nor an error while the task is still loading", async () => {
    backend = installFakeBackend({
      ...BASE_ROUTES,
      // Never settles: the request stays in flight for the whole test.
      "GET /tasks/t1": () => new Promise<never>(() => {}),
    });
    setSearchParams({ id: "t1" });

    await renderWithSession(<TaskDetailScreen />);

    expect(screen.queryByPlaceholderText("Task title")).toBeNull();
    expect(screen.queryByText("Retry")).toBeNull();
  });

  it("surfaces a load failure with a retry", async () => {
    backend = installFakeBackend({
      ...BASE_ROUTES,
      "GET /tasks/t1": () => new FakeHttpError(404, { message: "Task not found" }),
    });
    setSearchParams({ id: "t1" });

    await renderWithSession(<TaskDetailScreen />);

    expect(await screen.findByText("Task not found")).toBeOnTheScreen();

    backend.route("GET /tasks/t1", () => makeTask({ id: "t1", title: "Recovered" }));
    await fireEvent.press(screen.getByText("Retry"));

    expect(await screen.findByDisplayValue("Recovered")).toBeOnTheScreen();
  });
});

describe("task detail — title, details and waiting", () => {
  it("saves a trimmed, changed title with the task's revision", async () => {
    await openTask(makeTask({ id: "t1", revision: 3 }), {
      "PATCH /tasks/t1": () => makeTask({ id: "t1", title: "Call the registrar", revision: 4 }),
    });

    const input = screen.getByPlaceholderText("Task title");
    await fireEvent.changeText(input, "  Call the registrar  ");
    await fireEvent(input, "endEditing");

    await waitFor(() => expect(backend.callsTo("PATCH", "/tasks/t1")).toHaveLength(1));
    expect(backend.callsTo("PATCH", "/tasks/t1")[0].body).toEqual({
      title: "Call the registrar",
      expected_revision: 3,
    });
  });

  it("does not save a title that only lost whitespace", async () => {
    await openTask(makeTask({ id: "t1", title: "Call the notary" }));

    const input = screen.getByPlaceholderText("Task title");
    await fireEvent.changeText(input, "  Call the notary  ");
    await fireEvent(input, "endEditing");

    expect(backend.callsTo("PATCH", "/tasks/t1")).toHaveLength(0);
  });

  it("restores the server title when the field is emptied", async () => {
    await openTask(makeTask({ id: "t1", title: "Call the notary" }));

    const input = screen.getByPlaceholderText("Task title");
    await fireEvent.changeText(input, "   ");
    await fireEvent(input, "endEditing");

    expect(backend.callsTo("PATCH", "/tasks/t1")).toHaveLength(0);
    expect(screen.getByDisplayValue("Call the notary")).toBeOnTheScreen();
  });

  it("opens the details editor from the ghost affordance and saves what was typed", async () => {
    await openTask(makeTask({ id: "t1", details: null }), {
      "PATCH /tasks/t1": () => makeTask({ id: "t1", details: "Ring at 9", revision: 2 }),
    });

    await fireEvent.press(screen.getByText("Add details…"));
    const editor = screen.getByPlaceholderText("Notes, links, context…");
    await fireEvent.changeText(editor, "Ring at 9");
    await fireEvent(editor, "endEditing");

    await waitFor(() => expect(backend.callsTo("PATCH", "/tasks/t1")).toHaveLength(1));
    expect(backend.callsTo("PATCH", "/tasks/t1")[0].body).toMatchObject({ details: "Ring at 9" });
  });

  it("clears details to null when the editor is emptied", async () => {
    await openTask(makeTask({ id: "t1", details: "Old note" }), {
      "PATCH /tasks/t1": () => makeTask({ id: "t1", details: null, revision: 2 }),
    });

    const editor = screen.getByDisplayValue("Old note");
    await fireEvent.changeText(editor, "   ");
    await fireEvent(editor, "endEditing");

    await waitFor(() => expect(backend.callsTo("PATCH", "/tasks/t1")).toHaveLength(1));
    expect(backend.callsTo("PATCH", "/tasks/t1")[0].body).toMatchObject({ details: null });
  });

  it("collects waiting_for only on a waiting task, and saves the trimmed value", async () => {
    await openTask(
      makeTask({ id: "t1", state: "waiting", waiting_for: "Dana", waiting_since: "2026-01-02T00:00:00Z" }),
      { "PATCH /tasks/t1": () => makeTask({ id: "t1", state: "waiting", waiting_for: "Sam" }) },
    );

    const input = screen.getByDisplayValue("Dana");
    await fireEvent.changeText(input, "  Sam  ");
    await fireEvent(input, "endEditing");

    await waitFor(() => expect(backend.callsTo("PATCH", "/tasks/t1")).toHaveLength(1));
    expect(backend.callsTo("PATCH", "/tasks/t1")[0].body).toMatchObject({ waiting_for: "Sam" });
  });

  it("has no waiting field on a task that is not waiting", async () => {
    await openTask(makeTask({ id: "t1", state: "next" }));

    expect(screen.queryByPlaceholderText("Who or what are you waiting on?")).toBeNull();
  });
});

describe("task detail — chips", () => {
  it("offers add affordances when the metadata is empty", async () => {
    await openTask(makeTask({ id: "t1", due_date: null, priority: "none" }));

    expect(screen.getByLabelText("Add due date")).toBeOnTheScreen();
    expect(screen.getByLabelText("Set priority")).toBeOnTheScreen();
  });

  it("shows the existing metadata, the project and the tags", async () => {
    await openTask(
      makeTask({
        id: "t1",
        due_date: "2030-06-01",
        priority: "high",
        project_id: "p1",
        tag_ids: ["g1"],
      }),
    );

    expect(screen.getByLabelText("Change due date")).toBeOnTheScreen();
    expect(screen.getByLabelText("Change priority")).toBeOnTheScreen();
    await waitFor(() => expect(screen.getByText("Wedding")).toBeOnTheScreen());
    expect(screen.getByText("errand")).toBeOnTheScreen();
  });

  it("labels a terminal task with its state and offers no add affordances", async () => {
    await openTask(makeTask({ id: "t1", state: "completed" }));

    expect(screen.getByText("Completed")).toBeOnTheScreen();
    expect(screen.queryByLabelText("Add due date")).toBeNull();
    expect(screen.queryByLabelText("Set priority")).toBeNull();
  });

  it("sets a due date from the Today shortcut", async () => {
    await openTask(makeTask({ id: "t1", due_date: null }), {
      "PATCH /tasks/t1": () => makeTask({ id: "t1", due_date: "2030-01-01" }),
    });

    await fireEvent.press(screen.getByLabelText("Add due date"));
    await fireEvent.press(screen.getByText("Today"));

    await waitFor(() => expect(backend.callsTo("PATCH", "/tasks/t1")).toHaveLength(1));
    expect(backend.callsTo("PATCH", "/tasks/t1")[0].body).toMatchObject({
      due_date: expect.stringMatching(/^\d{4}-\d{2}-\d{2}$/),
    });
  });

  it("accepts a typed ISO date and rejects anything else", async () => {
    await openTask(makeTask({ id: "t1", due_date: null }), {
      "PATCH /tasks/t1": () => makeTask({ id: "t1", due_date: "2030-06-01" }),
    });

    await fireEvent.press(screen.getByLabelText("Add due date"));
    const field = screen.getByPlaceholderText("YYYY-MM-DD");

    await fireEvent.changeText(field, "1 June");
    await fireEvent(field, "submitEditing");
    expect(backend.callsTo("PATCH", "/tasks/t1")).toHaveLength(0);

    await fireEvent.changeText(field, "2030-06-01");
    await fireEvent(field, "submitEditing");
    await waitFor(() => expect(backend.callsTo("PATCH", "/tasks/t1")).toHaveLength(1));
    expect(backend.callsTo("PATCH", "/tasks/t1")[0].body).toMatchObject({ due_date: "2030-06-01" });
  });

  it("clears an existing due date", async () => {
    await openTask(makeTask({ id: "t1", due_date: "2030-06-01" }), {
      "PATCH /tasks/t1": () => makeTask({ id: "t1", due_date: null }),
    });

    await fireEvent.press(screen.getByLabelText("Change due date"));
    await fireEvent.press(screen.getByText("Clear due date"));

    await waitFor(() => expect(backend.callsTo("PATCH", "/tasks/t1")).toHaveLength(1));
    expect(backend.callsTo("PATCH", "/tasks/t1")[0].body).toMatchObject({ due_date: null });
  });

  it("saves a newly chosen priority", async () => {
    await openTask(makeTask({ id: "t1", priority: "none" }), {
      "PATCH /tasks/t1": () => makeTask({ id: "t1", priority: "low" }),
    });

    await fireEvent.press(screen.getByLabelText("Set priority"));
    await fireEvent.press(screen.getByText("Low"));

    await waitFor(() => expect(backend.callsTo("PATCH", "/tasks/t1")).toHaveLength(1));
    expect(backend.callsTo("PATCH", "/tasks/t1")[0].body).toMatchObject({ priority: "low" });
  });

  it("skips the save when the already-selected priority is picked again", async () => {
    await openTask(makeTask({ id: "t1", priority: "high" }));

    await fireEvent.press(screen.getByLabelText("Change priority"));
    // The only selected option in the sheet is the task's current priority.
    await fireEvent.press(screen.getByRole("button", { selected: true }));

    expect(backend.callsTo("PATCH", "/tasks/t1")).toHaveLength(0);
  });
});

describe("task detail — subtasks and comments", () => {
  it("adds a trimmed subtask and clears the field", async () => {
    await openTask(makeTask({ id: "t1", subtasks: [] }), {
      "POST /tasks/t1/subtasks": () => ({
        id: "s1",
        title: "Ring the venue",
        state: "open",
        order_key: 1,
        revision: 1,
      }),
    });

    const field = screen.getByPlaceholderText("Add a subtask");
    await fireEvent.changeText(field, "  Ring the venue  ");
    await fireEvent(field, "submitEditing");

    await waitFor(() => expect(backend.callsTo("POST", "/tasks/t1/subtasks")).toHaveLength(1));
    expect(backend.callsTo("POST", "/tasks/t1/subtasks")[0].body).toEqual({
      title: "Ring the venue",
    });
  });

  it("ignores an empty subtask submission", async () => {
    await openTask(makeTask({ id: "t1", subtasks: [] }));

    const field = screen.getByPlaceholderText("Add a subtask");
    await fireEvent.changeText(field, "   ");
    await fireEvent(field, "submitEditing");

    expect(backend.callsTo("POST", "/tasks/t1/subtasks")).toHaveLength(0);
  });

  it("completes an open subtask and reopens a completed one", async () => {
    await openTask(
      makeTask({
        id: "t1",
        subtasks: [
          { id: "s1", title: "Open one", state: "open", order_key: 1, revision: 2 },
          { id: "s2", title: "Done one", state: "completed", order_key: 2, revision: 5 },
        ],
      }),
      {
        "POST /tasks/t1/subtasks/s1/transitions": () => ({
          id: "s1",
          title: "Open one",
          state: "completed",
          order_key: 1,
          revision: 3,
        }),
        "POST /tasks/t1/subtasks/s2/transitions": () => ({
          id: "s2",
          title: "Done one",
          state: "open",
          order_key: 2,
          revision: 6,
        }),
      },
    );

    await fireEvent.press(screen.getByLabelText("Complete subtask"));
    await waitFor(() =>
      expect(backend.callsTo("POST", "/tasks/t1/subtasks/s1/transitions")).toHaveLength(1),
    );
    expect(backend.callsTo("POST", "/tasks/t1/subtasks/s1/transitions")[0].body).toEqual({
      action: "complete",
      expected_revision: 2,
    });

    await fireEvent.press(screen.getByLabelText("Reopen subtask"));
    await waitFor(() =>
      expect(backend.callsTo("POST", "/tasks/t1/subtasks/s2/transitions")).toHaveLength(1),
    );
    expect(backend.callsTo("POST", "/tasks/t1/subtasks/s2/transitions")[0].body).toEqual({
      action: "reopen",
      expected_revision: 5,
    });
  });

  it("does not offer to toggle a cancelled subtask", async () => {
    await openTask(
      makeTask({
        id: "t1",
        subtasks: [{ id: "s1", title: "Dropped", state: "cancelled", order_key: 1, revision: 1 }],
      }),
    );

    await fireEvent.press(screen.getByLabelText("Complete subtask"));

    expect(backend.callsTo("POST", "/tasks/t1/subtasks/s1/transitions")).toHaveLength(0);
  });

  it("posts a trimmed comment", async () => {
    await openTask(makeTask({ id: "t1", comments: [] }), {
      "POST /tasks/t1/comments": () => ({
        id: "c1",
        body: "Left a voicemail",
        actor_id: "u1",
        created_at: new Date().toISOString(),
        edited_at: null,
        revision: 1,
      }),
    });

    const field = screen.getByPlaceholderText("Add a comment");
    await fireEvent.changeText(field, "  Left a voicemail  ");
    await fireEvent(field, "submitEditing");

    await waitFor(() => expect(backend.callsTo("POST", "/tasks/t1/comments")).toHaveLength(1));
    expect(backend.callsTo("POST", "/tasks/t1/comments")[0].body).toEqual({
      body: "Left a voicemail",
    });
  });

  it("renders existing comments with initials and an edited marker", async () => {
    await openTask(
      makeTask({
        id: "t1",
        comments: [
          {
            id: "c1",
            body: "Left a voicemail",
            actor_id: "u1",
            created_at: new Date(Date.now() - 3 * 3_600_000).toISOString(),
            edited_at: new Date().toISOString(),
            revision: 2,
          },
        ],
      }),
    );

    expect(screen.getByText("Left a voicemail")).toBeOnTheScreen();
    expect(screen.getByText("DR")).toBeOnTheScreen();
    expect(screen.getByText("3h · edited")).toBeOnTheScreen();
  });
});

describe("task detail — lifecycle", () => {
  it("completes the task from the checkbox", async () => {
    await openTask(makeTask({ id: "t1", revision: 2 }), {
      "POST /tasks/t1/transitions": () => makeTask({ id: "t1", state: "completed", revision: 3 }),
    });

    await fireEvent.press(screen.getByLabelText("Complete task"));

    await waitFor(() => expect(backend.callsTo("POST", "/tasks/t1/transitions")).toHaveLength(1));
    expect(backend.callsTo("POST", "/tasks/t1/transitions")[0].body).toEqual({
      action: "complete",
      expected_revision: 2,
    });
  });

  it("moves the task to a chosen list", async () => {
    await openTask(makeTask({ id: "t1", state: "inbox", revision: 2 }), {
      "POST /tasks/t1/transitions": () => makeTask({ id: "t1", state: "next", revision: 3 }),
    });

    await fireEvent.press(screen.getByText("Move to…"));
    await fireEvent.press(screen.getByText("Next"));
    await fireEvent.press(screen.getByText("Move"));

    await waitFor(() => expect(backend.callsTo("POST", "/tasks/t1/transitions")).toHaveLength(1));
    expect(backend.callsTo("POST", "/tasks/t1/transitions")[0].body).toEqual({
      action: "move",
      to_state: "next",
      expected_revision: 2,
    });
  });

  it("refuses a move to waiting without naming who, and says why", async () => {
    await openTask(makeTask({ id: "t1", state: "inbox", revision: 2 }));

    await fireEvent.press(screen.getByText("Move to…"));
    await fireEvent.press(screen.getByText("Waiting"));
    await fireEvent.press(screen.getByText("Move"));

    expect(backend.callsTo("POST", "/tasks/t1/transitions")).toHaveLength(0);
    expect(
      screen.getByText("Waiting for requires who or what you are waiting on."),
    ).toBeOnTheScreen();
  });

  it("moves to waiting once who is named", async () => {
    await openTask(makeTask({ id: "t1", state: "inbox", revision: 2 }), {
      "POST /tasks/t1/transitions": () => makeTask({ id: "t1", state: "waiting", revision: 3 }),
    });

    await fireEvent.press(screen.getByText("Move to…"));
    await fireEvent.press(screen.getByText("Waiting"));
    await fireEvent.changeText(
      screen.getByPlaceholderText("Who or what are you waiting on?"),
      "Dana",
    );
    await fireEvent.press(screen.getByText("Move"));

    await waitFor(() => expect(backend.callsTo("POST", "/tasks/t1/transitions")).toHaveLength(1));
    expect(backend.callsTo("POST", "/tasks/t1/transitions")[0].body).toEqual({
      action: "move",
      to_state: "waiting",
      waiting_for: "Dana",
      expected_revision: 2,
    });
  });

  it("cancels the task", async () => {
    await openTask(makeTask({ id: "t1", revision: 2 }), {
      "POST /tasks/t1/transitions": () => makeTask({ id: "t1", state: "cancelled", revision: 3 }),
    });

    await fireEvent.press(screen.getByText("Cancel task"));

    await waitFor(() => expect(backend.callsTo("POST", "/tasks/t1/transitions")).toHaveLength(1));
    expect(backend.callsTo("POST", "/tasks/t1/transitions")[0].body).toEqual({
      action: "cancel",
      expected_revision: 2,
    });
  });

  it("reopens a completed task into an explicitly chosen list", async () => {
    await openTask(makeTask({ id: "t1", state: "completed", revision: 4 }), {
      "POST /tasks/t1/transitions": () => makeTask({ id: "t1", state: "next", revision: 5 }),
    });

    expect(screen.queryByText("Move to…")).toBeNull();
    await fireEvent.press(screen.getByText("Reopen…"));
    await fireEvent.press(screen.getByText("Next"));
    await fireEvent.press(screen.getByText("Reopen"));

    await waitFor(() => expect(backend.callsTo("POST", "/tasks/t1/transitions")).toHaveLength(1));
    expect(backend.callsTo("POST", "/tasks/t1/transitions")[0].body).toEqual({
      action: "reopen",
      to_state: "next",
      expected_revision: 4,
    });
  });

  it("explains a 409 as a concurrent change rather than a raw error", async () => {
    await openTask(makeTask({ id: "t1", revision: 2 }), {
      "PATCH /tasks/t1": () => new FakeHttpError(409, { message: "Revision mismatch" }),
    });

    const input = screen.getByPlaceholderText("Task title");
    await fireEvent.changeText(input, "Something else");
    await fireEvent(input, "endEditing");

    expect(
      await screen.findByText(
        "This task changed elsewhere. The latest version is shown — review and retry your edit.",
      ),
    ).toBeOnTheScreen();
    expect(screen.queryByText("Revision mismatch")).toBeNull();
  });

  it("shows a non-conflict save failure as an error banner", async () => {
    await openTask(makeTask({ id: "t1", revision: 2 }), {
      "PATCH /tasks/t1": () => new FakeHttpError(500, { message: "Storage is unavailable" }),
    });

    const input = screen.getByPlaceholderText("Task title");
    await fireEvent.changeText(input, "Something else");
    await fireEvent(input, "endEditing");

    expect(await screen.findByText("Storage is unavailable")).toBeOnTheScreen();
  });

  it("shows the created date and revision in the footer", async () => {
    await openTask(makeTask({ id: "t1", revision: 7, created_at: "2026-02-03T10:00:00Z" }));

    expect(screen.getByText(/revision 7$/)).toBeOnTheScreen();
  });
});
