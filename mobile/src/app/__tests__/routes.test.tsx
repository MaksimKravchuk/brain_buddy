import { screen, waitFor } from "@testing-library/react-native";

import { renderedRedirects, setSearchParams } from "@/test/expoRouterMock";
import {
  installFakeBackend,
  makeMe,
  makeProject,
  makeTag,
  makeTask,
  makeTaskPage,
  type FakeBackend,
} from "@/test/fakeBackend";
import { renderWithSession } from "@/test/harness";

import Index from "../index";
import ListScreen from "../list/[state]";
import ProjectScreen from "../project/[id]";
import TagScreen from "../tag/[id]";

let backend: FakeBackend;

afterEach(() => backend?.restore());

const ROUTES = {
  "GET /auth/me": () => makeMe(),
  "GET /projects": () => [makeProject({ id: "p1", name: "Wedding" })],
  "GET /tags": () => [makeTag({ id: "g1", name: "errand" })],
  "GET /tasks": () => makeTaskPage([makeTask({ id: "t1" })]),
};

describe("landing route", () => {
  it("sends a signed-in user to next actions", async () => {
    backend = installFakeBackend(ROUTES);

    await renderWithSession(<Index />);

    expect(renderedRedirects()).toEqual(["/list/next"]);
  });
});

describe("list/[state]", () => {
  it.each([
    ["inbox", "Inbox", "Inbox zero"],
    ["next", "Next actions", "No next actions"],
    ["waiting", "Waiting for", "Nothing waiting"],
    ["someday", "Someday / maybe", "Nothing parked"],
  ])("renders the %s list with its own copy", async (state, title, emptyHeadline) => {
    backend = installFakeBackend({ ...ROUTES, "GET /tasks": () => makeTaskPage([]) });
    setSearchParams({ state });

    await renderWithSession(<ListScreen />);

    expect(await screen.findByText(title)).toBeOnTheScreen();
    expect(screen.getByText(emptyHeadline)).toBeOnTheScreen();
    expect(backend.callsTo("GET", "/tasks").map((call) => call.query)).toContain(
      `state=${state}&limit=50`,
    );
  });

  it("redirects an unknown list to next actions instead of rendering nothing", async () => {
    backend = installFakeBackend(ROUTES);
    setSearchParams({ state: "archive" });

    await renderWithSession(<ListScreen />);

    expect(renderedRedirects()).toEqual(["/list/next"]);
  });

  it("redirects when the route carries no state at all", async () => {
    backend = installFakeBackend(ROUTES);
    setSearchParams({});

    await renderWithSession(<ListScreen />);

    expect(renderedRedirects()).toEqual(["/list/next"]);
  });
});

describe("project/[id]", () => {
  it("titles the screen from the route param without waiting for the fetch", async () => {
    backend = installFakeBackend(ROUTES);
    setSearchParams({ id: "p1", name: "Wedding" });

    await renderWithSession(<ProjectScreen />);

    expect(screen.getAllByText("Wedding").length).toBeGreaterThan(0);
  });

  it("falls back to the fetched project name when the route carries none", async () => {
    backend = installFakeBackend(ROUTES);
    setSearchParams({ id: "p1" });

    await renderWithSession(<ProjectScreen />);

    await waitFor(() => expect(screen.getAllByText("Wedding").length).toBeGreaterThan(0));
  });

  it("falls back to a generic title for an unknown project", async () => {
    backend = installFakeBackend({ ...ROUTES, "GET /projects": () => [] });
    setSearchParams({ id: "missing" });

    await renderWithSession(<ProjectScreen />);

    expect(screen.getAllByText("Project").length).toBeGreaterThan(0);
  });
});

describe("tag/[id]", () => {
  it("titles the screen from the route param", async () => {
    backend = installFakeBackend(ROUTES);
    setSearchParams({ id: "g1", name: "errand" });

    await renderWithSession(<TagScreen />);

    expect(screen.getAllByText("errand").length).toBeGreaterThan(0);
  });

  it("falls back to the fetched tag name, then to a generic title", async () => {
    backend = installFakeBackend(ROUTES);
    setSearchParams({ id: "g1" });
    const first = await renderWithSession(<TagScreen />);
    await waitFor(() => expect(screen.getAllByText("errand").length).toBeGreaterThan(0));
    await first.unmount();

    backend.route("GET /tags", () => []);
    setSearchParams({ id: "missing" });
    await renderWithSession(<TagScreen />);
    expect(screen.getAllByText("Tag").length).toBeGreaterThan(0);
  });
});
