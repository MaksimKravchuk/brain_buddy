import { fireEvent, screen, waitFor } from "@testing-library/react-native";

import { routerSpy, setSearchParams } from "@/test/expoRouterMock";
import {
  FakeHttpError,
  installFakeBackend,
  makeMe,
  makeProject,
  makeTag,
  makeTask,
  makeTaskPage,
  type FakeBackend,
  type RouteHandler,
} from "@/test/fakeBackend";
import { renderWithSession } from "@/test/harness";

import HistoryScreen from "../history";

let backend: FakeBackend;

afterEach(() => backend?.restore());

function history(kind: string | undefined, routes: Record<string, RouteHandler> = {}) {
  backend?.restore();
  backend = installFakeBackend({
    "GET /auth/me": () => makeMe(),
    "GET /projects": () => [makeProject({ id: "p1", name: "Wedding" })],
    "GET /tags": () => [makeTag({ id: "g1", name: "errand" })],
    "GET /tasks": () => makeTaskPage([]),
    ...routes,
  });
  setSearchParams(kind === undefined ? {} : { kind });
  return renderWithSession(<HistoryScreen />);
}

describe("history", () => {
  it("shows completed tasks by default and asks the server for only that state", async () => {
    await history(undefined, {
      "GET /tasks": () =>
        makeTaskPage([makeTask({ id: "t1", title: "Called the notary", state: "completed" })]),
    });

    expect(await screen.findByText("Called the notary")).toBeOnTheScreen();
    expect(
      screen.getByText("Finished tasks stay here with their history."),
    ).toBeOnTheScreen();
    expect(backend.callsTo("GET", "/tasks").map((call) => call.query)).toContain(
      "state=completed&limit=50",
    );
    expect(backend.callsTo("GET", "/agent-run-summaries").map((call) => call.query)).toContain(
      "task_id=t1",
    );
  });

  it("shows cancelled tasks when the route asks for them", async () => {
    await history("cancelled", {
      "GET /tasks": () =>
        makeTaskPage([makeTask({ id: "t1", title: "Dropped idea", state: "cancelled" })]),
    });

    expect(await screen.findByText("Dropped idea")).toBeOnTheScreen();
    expect(
      screen.getByText("Tasks you decided not to do stay reviewable here."),
    ).toBeOnTheScreen();
    expect(backend.callsTo("GET", "/tasks").map((call) => call.query)).toContain(
      "state=cancelled&limit=50",
    );
  });

  it("falls back to completed for an unrecognised kind", async () => {
    await history("nonsense");

    expect(await screen.findByText("Nothing completed yet")).toBeOnTheScreen();
  });

  it("has its own empty copy per kind", async () => {
    const first = await history(undefined);
    expect(await screen.findByText("Nothing completed yet")).toBeOnTheScreen();
    await first.unmount();

    await history("cancelled");
    expect(await screen.findByText("Nothing cancelled")).toBeOnTheScreen();
  });

  it("surfaces a load failure with a retry", async () => {
    await history(undefined, {
      "GET /tasks": () => new FakeHttpError(500, { message: "History is unavailable" }),
    });

    expect(await screen.findByText("History is unavailable")).toBeOnTheScreen();

    backend.route("GET /tasks", () =>
      makeTaskPage([makeTask({ id: "t1", title: "Called the notary", state: "completed" })]),
    );
    await fireEvent.press(screen.getByText("Retry"));

    expect(await screen.findByText("Called the notary")).toBeOnTheScreen();
  });

  it("opens terminal rows in task detail so the relay timeline remains reachable", async () => {
    await history(undefined, {
      "GET /tasks": () =>
        makeTaskPage([makeTask({ id: "t1", title: "Called the notary", state: "completed" })]),
    });

    await fireEvent.press(await screen.findByLabelText("Called the notary"));

    expect(routerSpy().push).toHaveBeenCalledWith({
      pathname: "/task/[id]",
      params: { id: "t1", from: "Completed" },
    });
    expect(screen.queryByText("Reopen into")).not.toBeOnTheScreen();
  });

  it("reopens a task into an explicitly chosen list", async () => {
    await history(undefined, {
      "GET /tasks": () =>
        makeTaskPage([
          makeTask({ id: "t1", title: "Called the notary", state: "completed", revision: 4 }),
        ]),
      "POST /tasks/t1/transitions": () => makeTask({ id: "t1", state: "next", revision: 5 }),
    });

    await fireEvent.press(await screen.findByLabelText("Reopen task"));
    await fireEvent.press(await screen.findByText("Next"));
    await fireEvent.press(screen.getByText("Reopen"));

    await waitFor(() => expect(backend.callsTo("POST", "/tasks/t1/transitions")).toHaveLength(1));
    expect(backend.callsTo("POST", "/tasks/t1/transitions")[0].body).toEqual({
      action: "reopen",
      to_state: "next",
      expected_revision: 4,
    });
  });

  it("opens the same reopen sheet from the checkbox", async () => {
    await history(undefined, {
      "GET /tasks": () =>
        makeTaskPage([makeTask({ id: "t1", title: "Called the notary", state: "completed" })]),
    });

    await fireEvent.press(await screen.findByLabelText("Reopen task"));

    expect(await screen.findByText("Reopen into")).toBeOnTheScreen();
  });

  it("requires who is being waited on before reopening into waiting", async () => {
    await history(undefined, {
      "GET /tasks": () =>
        makeTaskPage([makeTask({ id: "t1", title: "Called the notary", state: "completed" })]),
    });

    await fireEvent.press(await screen.findByLabelText("Reopen task"));
    await fireEvent.press(await screen.findByText("Waiting"));
    await fireEvent.press(screen.getByText("Reopen"));

    expect(backend.callsTo("POST", "/tasks/t1/transitions")).toHaveLength(0);
    expect(
      screen.getByText("Waiting for requires who or what you are waiting on."),
    ).toBeOnTheScreen();

    await fireEvent.changeText(
      screen.getByPlaceholderText("Who or what are you waiting on?"),
      "Dana",
    );
    await fireEvent.press(screen.getByText("Reopen"));

    await waitFor(() => expect(backend.callsTo("POST", "/tasks/t1/transitions")).toHaveLength(1));
    expect(backend.callsTo("POST", "/tasks/t1/transitions")[0].body).toMatchObject({
      to_state: "waiting",
      waiting_for: "Dana",
    });
  });

  it("keeps the sheet open and reports a failed reopen, rather than closing silently", async () => {
    await history(undefined, {
      "GET /tasks": () =>
        makeTaskPage([makeTask({ id: "t1", title: "Called the notary", state: "completed" })]),
      "POST /tasks/t1/transitions": () =>
        new FakeHttpError(409, { message: "That task changed elsewhere." }),
    });

    await fireEvent.press(await screen.findByLabelText("Reopen task"));
    await fireEvent.press(await screen.findByText("Next"));
    await fireEvent.press(screen.getByText("Reopen"));

    expect(await screen.findByText("That task changed elsewhere.")).toBeOnTheScreen();
  });

  it("closes the sheet without reopening", async () => {
    await history(undefined, {
      "GET /tasks": () =>
        makeTaskPage([makeTask({ id: "t1", title: "Called the notary", state: "completed" })]),
    });

    await fireEvent.press(await screen.findByLabelText("Reopen task"));
    await screen.findByText("Reopen into");

    await fireEvent.press(screen.getByLabelText("Close"));

    await waitFor(() => expect(screen.queryByText("Reopen into")).toBeNull());
    expect(backend.callsTo("POST", "/tasks/t1/transitions")).toHaveLength(0);
  });
});
