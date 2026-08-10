import { fireEvent, screen, waitFor } from "@testing-library/react-native";

import {
  FakeHttpError,
  installFakeBackend,
  makeCounts,
  makeProject,
  makeTag,
  makeTask,
  makeTaskPage,
  type FakeBackend,
} from "@/test/fakeBackend";
import { uuidNumber } from "@/test/expoCryptoMock";
import { routerSpy } from "@/test/expoRouterMock";
import { renderWithSession } from "@/test/harness";

import { TaskListScreen } from "../TaskListScreen";

let backend: FakeBackend;

afterEach(() => backend?.restore());

const SIGNED_IN = { "GET /auth/me": () => ({ id: "u1", email: "dana@example.test", feature_flags: {} }) };
const NO_CLASSIFICATIONS = { "GET /projects": () => [], "GET /tags": () => [] };

/** Every query string the screen sent to the task list endpoint. */
function listQueries(): string[] {
  return backend.callsTo("GET", "/tasks").map((call) => call.query);
}

function nextList() {
  return (
    <TaskListScreen
      title="Next actions"
      state="next"
      emptyHeadline="No next actions"
      emptyHint="Add a next action."
    />
  );
}

describe("TaskListScreen", () => {
  it("lists the tasks the server returned with their project and tag names", async () => {
    backend = installFakeBackend({
      ...SIGNED_IN,
      "GET /projects": () => [makeProject({ id: "p1", name: "Wedding" })],
      "GET /tags": () => [makeTag({ id: "g1", name: "errand" })],
      "GET /tasks": () =>
        makeTaskPage([
          makeTask({ id: "t1", title: "Call the notary", project_id: "p1", tag_ids: ["g1"] }),
          makeTask({ id: "t2", title: "Book the venue" }),
        ]),
    });

    await renderWithSession(nextList());

    expect(await screen.findByText("Call the notary")).toBeOnTheScreen();
    expect(screen.getByText("Book the venue")).toBeOnTheScreen();
    await waitFor(() => expect(screen.getByText("Wedding")).toBeOnTheScreen());
    expect(screen.getByText("errand")).toBeOnTheScreen();
  });

  it("asks the server for the list's own state", async () => {
    backend = installFakeBackend({
      ...SIGNED_IN,
      ...NO_CLASSIFICATIONS,
      "GET /tasks": () => makeTaskPage([]),
    });

    await renderWithSession(nextList());

    await waitFor(() => expect(listQueries()).toContain("state=next&limit=50"));
  });

  it("shows the empty state when the list has no tasks", async () => {
    backend = installFakeBackend({
      ...SIGNED_IN,
      ...NO_CLASSIFICATIONS,
      "GET /tasks": () => makeTaskPage([]),
    });

    await renderWithSession(nextList());

    expect(await screen.findByText("No next actions")).toBeOnTheScreen();
    expect(screen.getByText("Add a next action.")).toBeOnTheScreen();
  });

  it("surfaces a load failure with a retry that refetches", async () => {
    backend = installFakeBackend({
      ...SIGNED_IN,
      ...NO_CLASSIFICATIONS,
      "GET /tasks": () => new FakeHttpError(500, { message: "Server exploded" }, "corr-9"),
    });

    await renderWithSession(nextList());

    expect(await screen.findByText("Server exploded")).toBeOnTheScreen();
    expect(screen.getByText("ref: corr-9")).toBeOnTheScreen();

    backend.route("GET /tasks", () => makeTaskPage([makeTask({ title: "Recovered task" })]));
    await fireEvent.press(screen.getByText("Retry"));

    expect(await screen.findByText("Recovered task")).toBeOnTheScreen();
  });

  it("opens a task, carrying the list title as the back destination", async () => {
    backend = installFakeBackend({
      ...SIGNED_IN,
      ...NO_CLASSIFICATIONS,
      "GET /tasks": () => makeTaskPage([makeTask({ id: "t7", title: "Call the notary" })]),
    });

    await renderWithSession(nextList());
    await fireEvent.press(await screen.findByLabelText("Call the notary"));

    expect(routerSpy().push).toHaveBeenCalledWith({
      pathname: "/task/[id]",
      params: { id: "t7", from: "Next actions" },
    });
  });

  it("completes a task through the transition endpoint with its revision", async () => {
    backend = installFakeBackend({
      ...SIGNED_IN,
      ...NO_CLASSIFICATIONS,
      "GET /tasks": () => makeTaskPage([makeTask({ id: "t7", revision: 4 })]),
      "POST /tasks/t7/transitions": () => makeTask({ id: "t7", state: "completed", revision: 5 }),
    });

    await renderWithSession(nextList());
    await fireEvent.press(await screen.findByLabelText("Complete task"));

    await waitFor(() => expect(backend.callsTo("POST", "/tasks/t7/transitions")).toHaveLength(1));
    const call = backend.callsTo("POST", "/tasks/t7/transitions")[0];
    expect(call.body).toEqual({ action: "complete", expected_revision: 4 });
    expect(call.headers["Idempotency-Key"]).toBe(uuidNumber(1));
  });

  it("reports a failed completion instead of silently dropping it", async () => {
    backend = installFakeBackend({
      ...SIGNED_IN,
      ...NO_CLASSIFICATIONS,
      "GET /tasks": () => makeTaskPage([makeTask({ id: "t7" })]),
      "POST /tasks/t7/transitions": () =>
        new FakeHttpError(409, { message: "That task changed while you were looking at it." }),
    });

    await renderWithSession(nextList());
    await fireEvent.press(await screen.findByLabelText("Complete task"));

    expect(
      await screen.findByText("That task changed while you were looking at it."),
    ).toBeOnTheScreen();
  });

  it("counts what it has, and marks the count as partial while more pages remain", async () => {
    backend = installFakeBackend({
      ...SIGNED_IN,
      ...NO_CLASSIFICATIONS,
      "GET /tasks": () => ({
        items: [makeTask({ id: "t1" })],
        next_cursor: "cursor-2",
        has_more: true,
        counts_by_state: makeCounts({ next: 40 }),
      }),
    });

    await renderWithSession(nextList());

    expect(await screen.findByText("1+ tasks")).toBeOnTheScreen();
  });

  it("says 'task' in the singular only when the list is complete", async () => {
    backend = installFakeBackend({
      ...SIGNED_IN,
      ...NO_CLASSIFICATIONS,
      "GET /tasks": () => makeTaskPage([makeTask({ id: "t1" })]),
    });

    await renderWithSession(nextList());

    expect(await screen.findByText("1 task")).toBeOnTheScreen();
  });

  it("tells the inbox to process rather than counting it", async () => {
    backend = installFakeBackend({
      ...SIGNED_IN,
      ...NO_CLASSIFICATIONS,
      "GET /tasks": () => makeTaskPage([makeTask({ id: "t1", state: "inbox" })]),
    });

    await renderWithSession(
      <TaskListScreen title="Inbox" state="inbox" emptyHeadline="Inbox zero" />,
    );

    expect(await screen.findByText("Process these — decide the next action for each.")).toBeOnTheScreen();
  });

  it("scopes a project list to the project and drops the redundant project name", async () => {
    backend = installFakeBackend({
      ...SIGNED_IN,
      // The project's name differs from the screen title, so a project name on
      // the row would be visible as its own text.
      "GET /projects": () => [makeProject({ id: "p1", name: "Wedding" })],
      "GET /tags": () => [],
      "GET /tasks": () => makeTaskPage([makeTask({ id: "t1", project_id: "p1" })]),
    });

    await renderWithSession(
      <TaskListScreen
        title="Wedding plans"
        projectId="p1"
        mode="sub"
        emptyHeadline="No open tasks"
      />,
    );

    await screen.findByText("Call the notary");
    expect(listQueries()).toContain("project_id=p1&limit=50");
    expect(screen.queryByText("Wedding")).toBeNull();
  });

  it("scopes a tag list to the tag, drops the tag pill, and says it spans the lists", async () => {
    backend = installFakeBackend({
      ...SIGNED_IN,
      "GET /projects": () => [],
      "GET /tags": () => [makeTag({ id: "g1", name: "errand" })],
      "GET /tasks": () => makeTaskPage([makeTask({ id: "t1", tag_ids: ["g1"] })]),
    });

    await renderWithSession(
      <TaskListScreen title="Tagged" tagId="g1" mode="sub" emptyHeadline="No open tasks" />,
    );

    expect(await screen.findByText("1 task across your lists")).toBeOnTheScreen();
    expect(listQueries()).toContain("tag_id=g1&limit=50");
    expect(screen.queryByText("errand")).toBeNull();
  });

  it("offers the drawer on a root list and a back chevron on a sub list", async () => {
    backend = installFakeBackend({
      ...SIGNED_IN,
      ...NO_CLASSIFICATIONS,
      "GET /tasks": () => makeTaskPage([]),
    });

    const root = await renderWithSession(nextList());
    expect(screen.getByLabelText("Menu")).toBeOnTheScreen();
    await root.unmount();

    await renderWithSession(
      <TaskListScreen title="Wedding" projectId="p1" mode="sub" emptyHeadline="No open tasks" />,
    );
    expect(screen.getByLabelText("Back")).toBeOnTheScreen();
    expect(screen.queryByLabelText("Menu")).toBeNull();
  });

  it("fetches the next page when the list is scrolled to the end", async () => {
    backend = installFakeBackend({
      ...SIGNED_IN,
      ...NO_CLASSIFICATIONS,
      "GET /tasks": (call) =>
        call.query.includes("cursor=cursor-2")
          ? makeTaskPage([makeTask({ id: "t2", title: "Second page task" })])
          : {
              items: [makeTask({ id: "t1", title: "First page task" })],
              next_cursor: "cursor-2",
              has_more: true,
              counts_by_state: makeCounts({ next: 2 }),
            },
    });

    const { container } = await renderWithSession(nextList());
    await screen.findByText("First page task");

    // The virtualized list only knows it has reached the end once it has been
    // told its own size, which no layout pass provides under the test renderer.
    const [list] = container.queryAll((node) => node.type === "RCTScrollView");
    await fireEvent(list, "layout", {
      nativeEvent: { layout: { width: 100, height: 100 } },
    });
    await fireEvent(list, "contentSizeChange", 100, 500);
    await fireEvent.scroll(list, {
      nativeEvent: {
        contentOffset: { y: 500 },
        contentSize: { height: 500, width: 100 },
        layoutMeasurement: { height: 100, width: 100 },
      },
    });

    expect(await screen.findByText("Second page task")).toBeOnTheScreen();
    expect(listQueries().some((query) => query.includes("cursor=cursor-2"))).toBe(true);
  });

  it("collects waiting_for before adding to the waiting list", async () => {
    backend = installFakeBackend({
      ...SIGNED_IN,
      ...NO_CLASSIFICATIONS,
      "GET /tasks": () => makeTaskPage([]),
      "POST /tasks": () => makeTask({ id: "new", state: "waiting" }),
    });

    await renderWithSession(
      <TaskListScreen
        title="Waiting for"
        state="waiting"
        emptyHeadline="Nothing waiting"
      />,
    );
    await fireEvent.press(await screen.findByText("Add a task"));

    await fireEvent.changeText(screen.getByPlaceholderText("What needs doing?"), "Contract back");
    await fireEvent.press(screen.getByText("Add to waiting"));
    expect(backend.callsTo("POST", "/tasks")).toHaveLength(0);

    await fireEvent.changeText(
      screen.getByPlaceholderText("Who or what are you waiting on?"),
      "  Dana  ",
    );
    await fireEvent.press(screen.getByText("Add to waiting"));

    await waitFor(() => expect(backend.callsTo("POST", "/tasks")).toHaveLength(1));
    expect(backend.callsTo("POST", "/tasks")[0].body).toEqual({
      title: "Contract back",
      state: "waiting",
      waiting_for: "Dana",
    });
  });

  it("labels the someday list's add button in full, and carries the classification", async () => {
    backend = installFakeBackend({
      ...SIGNED_IN,
      ...NO_CLASSIFICATIONS,
      "GET /tasks": () => makeTaskPage([]),
      "POST /tasks": () => makeTask({ id: "new" }),
    });

    await renderWithSession(
      <TaskListScreen title="Wedding" projectId="p1" tagId="g1" emptyHeadline="No open tasks" />,
    );
    await fireEvent.press(await screen.findByText("Add a task to this project"));

    await fireEvent.changeText(screen.getByPlaceholderText("What needs doing?"), "Book the venue");
    await fireEvent.press(screen.getByText("Add to inbox"));

    await waitFor(() => expect(backend.callsTo("POST", "/tasks")).toHaveLength(1));
    expect(backend.callsTo("POST", "/tasks")[0].body).toEqual({
      title: "Book the venue",
      state: "inbox",
      project_id: "p1",
      tag_ids: ["g1"],
    });
  });

  it("reports a failed quick add without closing the sheet", async () => {
    backend = installFakeBackend({
      ...SIGNED_IN,
      ...NO_CLASSIFICATIONS,
      "GET /tasks": () => makeTaskPage([]),
      "POST /tasks": () => new FakeHttpError(422, { message: "Title is too long" }),
    });

    await renderWithSession(nextList());
    await fireEvent.press(
      await screen.findByText("Add a next action — or dump everything with the mic"),
    );
    await fireEvent.changeText(
      screen.getByPlaceholderText(
        "Add a next action — or dump everything on your mind with the mic above",
      ),
      "Book the venue",
    );
    await fireEvent.press(screen.getByText("Add to next"));

    expect(await screen.findByText("Title is too long")).toBeOnTheScreen();
  });

  it("adds a task through quick add and closes the sheet on success", async () => {
    backend = installFakeBackend({
      ...SIGNED_IN,
      ...NO_CLASSIFICATIONS,
      "GET /tasks": () => makeTaskPage([]),
      "POST /tasks": () => makeTask({ id: "new", title: "Book the venue" }),
    });

    await renderWithSession(nextList());
    await fireEvent.press(
      await screen.findByText("Add a next action — or dump everything with the mic"),
    );

    const input = screen.getByPlaceholderText(
      "Add a next action — or dump everything on your mind with the mic above",
    );
    await fireEvent.changeText(input, "  Book the venue  ");
    await fireEvent.press(screen.getByText("Add to next"));

    await waitFor(() => expect(backend.callsTo("POST", "/tasks")).toHaveLength(1));
    expect(backend.callsTo("POST", "/tasks")[0].body).toEqual({
      title: "Book the venue",
      state: "next",
    });
  });
});
