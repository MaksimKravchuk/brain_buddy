import { fireEvent, render, screen, waitFor } from "@testing-library/react-native";
import { Text } from "react-native";

import { AddTaskRow } from "@/components/shell/AddTaskRow";
import { Drawer } from "@/components/shell/Drawer";
import { PaneHead } from "@/components/shell/PaneHead";
import { TopBar } from "@/components/shell/TopBar";
import { routerSpy, setPathname } from "@/test/expoRouterMock";
import {
  installFakeBackend,
  makeCounts,
  makeMe,
  makeProject,
  makeTag,
  makeTaskPage,
  type FakeBackend,
  type RouteHandler,
} from "@/test/fakeBackend";
import { renderWithSession } from "@/test/harness";

let backend: FakeBackend;

afterEach(() => backend?.restore());

function signedIn(routes: Record<string, RouteHandler> = {}) {
  backend = installFakeBackend({
    "GET /auth/me": () => makeMe({ email: "dana.reid@example.test" }),
    "GET /projects": () => [],
    "GET /tags": () => [],
    "GET /tasks": () => makeTaskPage([]),
    ...routes,
  });
}

describe("PaneHead", () => {
  it("renders a title, and the meta line only when there is one", async () => {
    await render(<PaneHead title="Next actions" meta="3 tasks" />);
    expect(screen.getByText("Next actions")).toBeOnTheScreen();
    expect(screen.getByText("3 tasks")).toBeOnTheScreen();

    await render(<PaneHead title="Next actions" />);
    expect(screen.queryByText("3 tasks")).toBeNull();
  });

  it("renders actions when given, and omits the slot otherwise", async () => {
    await render(<PaneHead title="Next actions" actions={<Text>Edit</Text>} />);
    expect(screen.getByText("Edit")).toBeOnTheScreen();

    await render(<PaneHead title="Next actions" />);
    expect(screen.queryByText("Edit")).toBeNull();
  });
});

describe("AddTaskRow", () => {
  it("shows its label and reports the press", async () => {
    const onPress = jest.fn();

    await render(<AddTaskRow label="Add a task" onPress={onPress} />);
    await fireEvent.press(screen.getByText("Add a task"));

    expect(onPress).toHaveBeenCalledTimes(1);
  });
});

describe("TopBar", () => {
  it("offers the menu on a root view and calls back the handler", async () => {
    signedIn();
    const onMenu = jest.fn();

    await renderWithSession(<TopBar leading="menu" onMenu={onMenu} />);
    await fireEvent.press(screen.getByLabelText("Menu"));

    expect(onMenu).toHaveBeenCalledTimes(1);
    expect(screen.queryByLabelText("Back")).toBeNull();
  });

  it("goes back from a sub view and shows its title", async () => {
    signedIn();

    await renderWithSession(<TopBar leading="back" title="Wedding" />);
    await fireEvent.press(screen.getByLabelText("Back"));

    expect(routerSpy().back).toHaveBeenCalledTimes(1);
    expect(screen.getByText("Wedding")).toBeOnTheScreen();
  });

  it("hides the mic until the account has the voice flag", async () => {
    signedIn();
    const withoutVoice = await renderWithSession(<TopBar leading="menu" showActions />);
    expect(screen.queryByLabelText("Brain dump")).toBeNull();
    await withoutVoice.unmount();

    backend.route("GET /auth/me", () => makeMe({ feature_flags: { voice_brain_dump: true } }));
    await renderWithSession(<TopBar leading="menu" showActions />);

    await fireEvent.press(screen.getByLabelText("Brain dump"));
    expect(routerSpy().push).toHaveBeenCalledWith("/brain-dump");
  });

  it("opens settings from the account avatar, initialled from the email", async () => {
    signedIn();

    await renderWithSession(<TopBar leading="menu" showActions />);

    expect(screen.getByText("DR")).toBeOnTheScreen();
    await fireEvent.press(screen.getByLabelText("Account"));
    expect(routerSpy().push).toHaveBeenCalledWith("/settings");
  });

  it("initials a single-word address from its first two letters", async () => {
    signedIn({ "GET /auth/me": () => makeMe({ email: "dana@example.test" }) });

    await renderWithSession(<TopBar leading="menu" showActions />);

    expect(screen.getByText("DA")).toBeOnTheScreen();
  });

  it("shows a placeholder rather than blank initials when signed out", async () => {
    signedIn({
      "GET /auth/me": () => {
        throw new TypeError("Network request failed");
      },
    });

    await renderWithSession(<TopBar leading="menu" showActions />);

    expect(screen.getByText("·")).toBeOnTheScreen();
  });

  it("hides the actions entirely on a back view", async () => {
    signedIn();

    await renderWithSession(<TopBar leading="back" title="Wedding" />);

    expect(screen.queryByLabelText("Account")).toBeNull();
  });
});

describe("Drawer", () => {
  it("lists the four GTD lists with their open counts", async () => {
    signedIn({
      "GET /tasks": () => ({
        items: [],
        next_cursor: null,
        has_more: false,
        counts_by_state: makeCounts({ inbox: 3, next: 12, waiting: 1, someday: 0 }),
      }),
    });

    await renderWithSession(<Drawer open onClose={jest.fn()} />);

    expect(screen.getByText("Inbox")).toBeOnTheScreen();
    expect(screen.getByText("Next actions")).toBeOnTheScreen();
    expect(screen.getByText("Waiting for")).toBeOnTheScreen();
    expect(screen.getByText("Someday / maybe")).toBeOnTheScreen();
    await waitFor(() => expect(screen.getByText("12")).toBeOnTheScreen());
    expect(screen.getByText("3")).toBeOnTheScreen();
  });

  it("navigates to a list and closes itself", async () => {
    signedIn();
    const onClose = jest.fn();

    await renderWithSession(<Drawer open onClose={onClose} />);
    await fireEvent.press(screen.getByText("Waiting for"));

    expect(onClose).toHaveBeenCalledTimes(1);
    expect(routerSpy().push).toHaveBeenCalledWith("/list/waiting");
  });

  it("lists only active projects and tags", async () => {
    signedIn({
      "GET /projects": () => [
        makeProject({ id: "p1", name: "Wedding", state: "active" }),
        makeProject({ id: "p2", name: "Old move", state: "archived" }),
      ],
      "GET /tags": () => [
        makeTag({ id: "g1", name: "errand", state: "active" }),
        makeTag({ id: "g2", name: "stale", state: "archived" }),
      ],
    });

    await renderWithSession(<Drawer open onClose={jest.fn()} />);

    await waitFor(() => expect(screen.getByText("Wedding")).toBeOnTheScreen());
    expect(screen.queryByText("Old move")).toBeNull();
    expect(screen.getByText("errand")).toBeOnTheScreen();
    expect(screen.queryByText("stale")).toBeNull();
  });

  it("opens a project and a tag by id", async () => {
    signedIn({
      "GET /projects": () => [makeProject({ id: "p1", name: "Wedding" })],
      "GET /tags": () => [makeTag({ id: "g1", name: "errand" })],
    });

    await renderWithSession(<Drawer open onClose={jest.fn()} />);
    await waitFor(() => expect(screen.getByText("Wedding")).toBeOnTheScreen());

    await fireEvent.press(screen.getByText("Wedding"));
    expect(routerSpy().push).toHaveBeenCalledWith({
      pathname: "/project/[id]",
      params: { id: "p1", name: "Wedding" },
    });

    await fireEvent.press(screen.getByText("errand"));
    expect(routerSpy().push).toHaveBeenCalledWith({
      pathname: "/tag/[id]",
      params: { id: "g1", name: "errand" },
    });
  });

  it("reaches the completed and cancelled history views", async () => {
    signedIn();

    await renderWithSession(<Drawer open onClose={jest.fn()} />);

    await fireEvent.press(screen.getByText("Completed"));
    expect(routerSpy().push).toHaveBeenCalledWith({
      pathname: "/history",
      params: { kind: "completed" },
    });

    await fireEvent.press(screen.getByText("Cancelled"));
    expect(routerSpy().push).toHaveBeenCalledWith({
      pathname: "/history",
      params: { kind: "cancelled" },
    });
  });

  it("closes from the scrim without navigating", async () => {
    signedIn();
    const onClose = jest.fn();

    await renderWithSession(<Drawer open onClose={onClose} />);
    await fireEvent.press(screen.getByLabelText("Close menu"));

    expect(onClose).toHaveBeenCalledTimes(1);
    expect(routerSpy().push).not.toHaveBeenCalled();
  });

  it("marks the list the user is already on", async () => {
    signedIn();
    setPathname("/list/next");

    await renderWithSession(<Drawer open onClose={jest.fn()} />);

    expect(screen.getByText("Next actions")).toBeOnTheScreen();
  });
});
