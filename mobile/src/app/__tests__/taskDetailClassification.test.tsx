/**
 * Feature 006 on the task detail screen, rendered.
 *
 * `src/app/task/__tests__/taskDetail.test.tsx` already covers this route with
 * the rollout flag OFF — `makeMe()` ships no flags, so every test there is
 * M-01c by construction. Nothing here repeats it. What is asserted below is the
 * screen the flag turns on: M-01's four labelled rows, the last-synced footer
 * that replaced every per-change marker, the expiry notices, and the offline
 * cold start that has to reach the same screen a live session does.
 *
 * Everything is a rendered assertion over the real screen, the real session,
 * the real queue and the fake backend: what a person can read, what assistive
 * technology is given, and what the device holds afterwards. The one place a
 * device boundary is stood in for is `AccessibilityInfo` — an announcement has
 * no rendered surface, and the words spoken are exactly what SC-004 is about.
 */

import AsyncStorage from "@react-native-async-storage/async-storage";
import { act, fireEvent, screen, waitFor } from "@testing-library/react-native";
import { AccessibilityInfo } from "react-native";

import type { TaskResponse } from "@/api/types";
import { TASK_CLASSIFICATION_FLAG, flagStorageKey, identityStorageKey } from "@/auth/flagResolution";
import { DEFAULT_SERVER_URL } from "@/config/serverUrl";
import { SERVER_TIME_KEY } from "@/features/tasks/classificationQueue.storage";
import type { PendingClassificationChange } from "@/features/tasks/classificationTypes";
import { cacheKey, queueKey } from "@/features/tasks/storageKeys";
import { resetAccountNoticeDismissals } from "@/features/tasks/taskScreenState";
import { setSearchParams } from "@/test/expoRouterMock";
import {
  installFakeBackend,
  makeMe,
  makeProject,
  makeTag,
  makeTask,
  type FakeBackend,
  type RouteHandler,
} from "@/test/fakeBackend";
import { renderWithSession } from "@/test/harness";

import TaskDetailScreen from "../task/[id]";

const ACCOUNT = "user-1";
const QUEUE_KEY = queueKey(DEFAULT_SERVER_URL, ACCOUNT);
const CACHE_KEY = cacheKey(DEFAULT_SERVER_URL, ACCOUNT);

const MINUTE = 60_000;
const DAY = 24 * 60 * MINUTE;

let backend: FakeBackend;

afterEach(async () => {
  backend?.restore();
  jest.restoreAllMocks();
  // The "dismiss once" latch is module state keyed by identity, so it would
  // otherwise carry a dismissal from one test into the next.
  resetAccountNoticeDismissals();
  await AsyncStorage.clear();
});

/** What a device that cannot reach the server gets back from `fetch`. */
function unreachable(): never {
  throw new TypeError("Network request failed");
}

interface OpenOptions {
  routes?: Record<string, RouteHandler>;
  /** FR-015's rollout flag, as `/auth/me` reports it. */
  flag?: boolean;
}

/**
 * Mount the detail screen for `task` with the rollout flag on, over a server
 * that knows two projects and two Tags.
 */
async function openTask(task: TaskResponse, { routes = {}, flag = true }: OpenOptions = {}) {
  backend = installFakeBackend({
    "GET /auth/me": () =>
      makeMe({ id: ACCOUNT, feature_flags: { [TASK_CLASSIFICATION_FLAG]: flag } }),
    "GET /projects": () => [
      makeProject({ id: "p1", name: "Wedding" }),
      makeProject({ id: "p2", name: "Q3 launch" }),
    ],
    "GET /tags": () => [
      makeTag({ id: "g1", name: "errand" }),
      makeTag({ id: "g2", name: "calls" }),
    ],
    [`GET /tasks/${task.id}`]: () => task,
    ...routes,
  });
  setSearchParams({ id: task.id });
  const rendered = await renderWithSession(<TaskDetailScreen />);
  await screen.findByDisplayValue(task.title);
  return rendered;
}

/** Every button on the screen, in reading order, by its accessible name. */
function buttonNames(): string[] {
  return screen
    .getAllByRole("button")
    .map((node) => (node.props as { accessibilityLabel?: unknown }).accessibilityLabel)
    .filter((label): label is string => typeof label === "string");
}

/** The four classification rows, in reading order, as assistive tech hears them. */
function rowNames(): string[] {
  return buttonNames().filter((label) => /^(Project|Tags|Due|Priority), /.test(label));
}

function queuedChange(
  overrides: Partial<PendingClassificationChange> = {},
): PendingClassificationChange {
  const edited = new Date(Date.now() - 31 * DAY).toISOString();
  return {
    taskId: "t1",
    accountId: ACCOUNT,
    serverUrl: DEFAULT_SERVER_URL,
    value: { projectId: "p2", tagIds: undefined },
    observedRevision: 1,
    originalValue: { projectId: null, tagIds: [] },
    firstQueuedAt: edited,
    lastEditedAt: edited,
    idempotencyKey: "key-1",
    sendState: "expired",
    ...overrides,
  };
}

async function seedQueue(entries: PendingClassificationChange[]): Promise<void> {
  await AsyncStorage.setItem(QUEUE_KEY, JSON.stringify(entries));
}

/**
 * The words a screen reader is given, in order.
 *
 * The one device boundary this file stands in for: an announcement has no
 * rendered surface, and what is asserted is the sentence spoken — SC-004's
 * whole subject — never that a function was reached.
 */
function captureAnnouncements(): string[] {
  const spoken: string[] = [];
  jest
    .spyOn(AccessibilityInfo, "announceForAccessibility")
    .mockImplementation((message: string) => {
      spoken.push(message);
    });
  return spoken;
}

describe("task detail — the classification rows", () => {
  it("006-FR-001 006-FR-002 shows all four rows with muted placeholders when nothing is set", async () => {
    await openTask(
      makeTask({ id: "t1", project_id: null, tag_ids: [], due_date: null, priority: "none" }),
    );

    // Present, not hidden: today's screen drops the project and Tags entirely
    // when they are unset, which is what puts FR-001 and FR-002 out of reach
    // for exactly the tasks that need them.
    expect(await screen.findByLabelText("Project, none set")).toBeOnTheScreen();
    expect(screen.getByLabelText("Tags, none set")).toBeOnTheScreen();
    expect(screen.getByLabelText("Due, none set")).toBeOnTheScreen();
    expect(screen.getByLabelText("Priority, none set")).toBeOnTheScreen();

    expect(screen.getByText("Add a project")).toBeOnTheScreen();
    expect(screen.getByText("Add Tags")).toBeOnTheScreen();
    expect(screen.getByText("Add a date")).toBeOnTheScreen();
    expect(screen.getByText("None")).toBeOnTheScreen();
  });

  it("006-FR-001 006-FR-002 keeps the same four rows when every field is set", async () => {
    await openTask(
      makeTask({
        id: "t1",
        project_id: "p1",
        tag_ids: ["g1", "g2"],
        due_date: "2030-06-01",
        priority: "high",
      }),
    );

    expect(await screen.findByLabelText("Project, Wedding")).toBeOnTheScreen();
    expect(screen.getByLabelText("Tags, errand, calls")).toBeOnTheScreen();
    expect(screen.getByLabelText(/^Due, /)).toBeOnTheScreen();
    expect(screen.getByLabelText("Priority, High")).toBeOnTheScreen();

    // The values themselves are read as pills, and the placeholders are gone.
    expect(screen.getByText("Wedding")).toBeOnTheScreen();
    expect(screen.getByText("errand")).toBeOnTheScreen();
    expect(screen.getByText("calls")).toBeOnTheScreen();
    expect(screen.queryByText("Add a project")).toBeNull();
    expect(screen.queryByText("Add Tags")).toBeNull();
  });

  it("006-FR-001 006-FR-002 opens each field's own control from its row", async () => {
    await openTask(
      makeTask({ id: "t1", project_id: null, tag_ids: [], due_date: null, priority: "none" }),
    );

    await fireEvent.press(await screen.findByLabelText("Project, none set"));
    expect(await screen.findByText("A task has one project, or none")).toBeOnTheScreen();
    await fireEvent.press(screen.getByText("Cancel"));

    await fireEvent.press(screen.getByLabelText("Tags, none set"));
    expect(await screen.findByText("No Tags selected")).toBeOnTheScreen();
    await fireEvent.press(screen.getByText("Done"));

    await fireEvent.press(screen.getByLabelText("Due, none set"));
    expect(await screen.findByPlaceholderText("YYYY-MM-DD")).toBeOnTheScreen();
    await fireEvent.press(screen.getByLabelText("Close"));

    await fireEvent.press(screen.getByLabelText("Priority, none set"));
    expect(await screen.findByText("Medium")).toBeOnTheScreen();
    await fireEvent.press(screen.getByLabelText("Close"));
  });

  it("006-FR-001 006-FR-003 replaces the project from the row and clears it back to none", async () => {
    let stored = makeTask({ id: "t1", project_id: "p1", revision: 1 });
    await openTask(stored, {
      routes: {
        "GET /tasks/t1": () => stored,
        "PATCH /tasks/t1": (call) => {
          const body = call.body as { project_id?: string | null };
          stored = { ...stored, project_id: body.project_id ?? null, revision: stored.revision + 1 };
          return stored;
        },
      },
    });

    await fireEvent.press(await screen.findByLabelText("Project, Wedding"));
    await fireEvent.press(await screen.findByLabelText("Q3 launch"));

    expect(await screen.findByLabelText("Project, Q3 launch")).toBeOnTheScreen();
    await screen.findByText(/revision 2$/);

    // FR-003: "no project" is a value a task may hold, and clearing travels as
    // an explicit null rather than as an omitted field.
    await fireEvent.press(screen.getByLabelText("Project, Q3 launch"));
    await fireEvent.press(await screen.findByLabelText("No project"));

    expect(await screen.findByLabelText("Project, none set")).toBeOnTheScreen();
    expect(backend.callsTo("PATCH", "/tasks/t1").map((call) => call.body)).toEqual([
      { project_id: "p2", expected_revision: 1 },
      { project_id: null, expected_revision: 2 },
    ]);
  });

  it("006-FR-002 attaches and detaches Tags from the row", async () => {
    let stored = makeTask({ id: "t1", tag_ids: ["g1"], revision: 1 });
    await openTask(stored, {
      routes: {
        "GET /tasks/t1": () => stored,
        "PATCH /tasks/t1": (call) => {
          const body = call.body as { tag_ids?: string[] };
          stored = { ...stored, tag_ids: body.tag_ids ?? [], revision: stored.revision + 1 };
          return stored;
        },
      },
    });

    await fireEvent.press(await screen.findByLabelText("Tags, errand"));
    await fireEvent.press(await screen.findByLabelText("calls"));
    expect(await screen.findByLabelText("Tags, errand, calls")).toBeOnTheScreen();

    await fireEvent.press(screen.getByLabelText("errand"));
    expect(await screen.findByLabelText("Tags, calls")).toBeOnTheScreen();
    await fireEvent.press(screen.getByText("Done"));

    await waitFor(() => expect(stored.tag_ids).toEqual(["g2"]));
  });

  it("006-FR-004 creates a project from the row and attaches it in one action", async () => {
    const projects = [makeProject({ id: "p1", name: "Wedding" })];
    let stored = makeTask({ id: "t1", project_id: null, revision: 1 });
    await openTask(stored, {
      routes: {
        "GET /tasks/t1": () => stored,
        "GET /projects": () => projects,
        "POST /projects": () => {
          const created = makeProject({ id: "p9", name: "Loft rebuild" });
          projects.push(created);
          return created;
        },
        "PATCH /tasks/t1": (call) => {
          const body = call.body as { project_id?: string | null };
          stored = { ...stored, project_id: body.project_id ?? null, revision: stored.revision + 1 };
          return stored;
        },
      },
    });

    await fireEvent.press(await screen.findByLabelText("Project, none set"));
    await fireEvent.changeText(
      await screen.findByLabelText("Search or type a new name"),
      "Loft rebuild",
    );
    await fireEvent.press(await screen.findByLabelText("Create “Loft rebuild”"));

    expect(await screen.findByLabelText("Project, Loft rebuild")).toBeOnTheScreen();
    await waitFor(() => expect(stored.project_id).toBe("p9"));
  });

  it("006-FR-004 creates a Tag from the row and attaches it in one action", async () => {
    const tags = [makeTag({ id: "g1", name: "errand" })];
    let stored = makeTask({ id: "t1", tag_ids: [], revision: 1 });
    await openTask(stored, {
      routes: {
        "GET /tasks/t1": () => stored,
        "GET /tags": () => tags,
        "POST /tags": () => {
          const created = makeTag({ id: "g9", name: "deep work" });
          tags.push(created);
          return created;
        },
        "PATCH /tasks/t1": (call) => {
          const body = call.body as { tag_ids?: string[] };
          stored = { ...stored, tag_ids: body.tag_ids ?? [], revision: stored.revision + 1 };
          return stored;
        },
      },
    });

    await fireEvent.press(await screen.findByLabelText("Tags, none set"));
    await fireEvent.changeText(await screen.findByLabelText("Search Tags"), "deep work");
    await fireEvent.press(await screen.findByLabelText("Create “deep work”"));

    expect(await screen.findByLabelText("Tags, deep work")).toBeOnTheScreen();
    await waitFor(() => expect(stored.tag_ids).toEqual(["g9"]));
  });
});

describe("task detail — the presentation the rollout flag chooses", () => {
  it("006-FR-015 renders today's chips and none of this feature's rows with the flag off", async () => {
    await openTask(
      makeTask({
        id: "t1",
        project_id: "p1",
        tag_ids: ["g1"],
        due_date: "2030-06-01",
        priority: "high",
      }),
      { flag: false },
    );

    await waitFor(() => expect(screen.getByText("Wedding")).toBeOnTheScreen());
    expect(screen.getByLabelText("Change due date")).toBeOnTheScreen();
    expect(screen.getByLabelText("Change priority")).toBeOnTheScreen();
    expect(screen.getByText("errand")).toBeOnTheScreen();

    // No row labels, no placeholders, and no controls this feature added.
    expect(rowNames()).toEqual([]);
    for (const label of ["Project", "Tags", "Due", "Priority"]) {
      expect(screen.queryByText(label)).toBeNull();
    }
    // FR-015: with the flag off the queue is not even rehydrated, so the one
    // line this feature adds to the bottom of the screen is absent too.
    expect(screen.queryByText("Not synced yet")).toBeNull();
  });

  it.each([
    ["completed", "Completed"],
    ["cancelled", "Cancelled"],
  ])(
    "006-FR-015 keeps chips on a %s task rather than giving it editable rows",
    async (state, stateLabel) => {
      await openTask(
        makeTask({
          id: "t1",
          state: state as TaskResponse["state"],
          project_id: "p1",
          tag_ids: ["g1"],
          due_date: "2030-06-01",
          priority: "high",
        }),
      );

      await waitFor(() => expect(screen.getByText("Wedding")).toBeOnTheScreen());
      expect(screen.getByText(stateLabel)).toBeOnTheScreen();
      expect(rowNames()).toEqual([]);
      expect(screen.queryByText("Add a project")).toBeNull();
      expect(screen.queryByLabelText("Add due date")).toBeNull();

      // The queue is still live: the footer and the expiry notices are about
      // the device, not about this task's state.
      expect(await screen.findByText("Not synced yet")).toBeOnTheScreen();
    },
  );
});

describe("task detail — how current the screen is", () => {
  it("006-SC-004 says in words when this device last heard from the server", async () => {
    await AsyncStorage.setItem(SERVER_TIME_KEY, String(Date.now() - 14 * MINUTE));

    await openTask(makeTask({ id: "t1" }));

    expect(await screen.findByText("Last synced 14 minutes ago")).toBeOnTheScreen();
    expect(screen.getByLabelText("Last synced 14 minutes ago")).toBeOnTheScreen();
  });

  it("006-SC-004 says plainly when this device has never seen the server answer", async () => {
    await openTask(makeTask({ id: "t1" }));

    expect(await screen.findByText("Not synced yet")).toBeOnTheScreen();
  });

  it("006-SC-004 announces the footer once the words change, not once per tick", async () => {
    jest.useFakeTimers({ doNotFake: ["nextTick"] });
    const spoken = captureAnnouncements();
    try {
      await AsyncStorage.setItem(SERVER_TIME_KEY, String(Date.now() - 30_000));
      await openTask(makeTask({ id: "t1" }));
      await screen.findByText("Last synced just now");
      // The device's own memory of the last sync arrives after first paint, so
      // the words legitimately change once on the way in. Everything asserted
      // below is what happens after the screen has settled.
      spoken.length = 0;

      // Two 30 s ticks. The words cross the minute boundary on the first and
      // are unchanged on the second.
      await act(async () => {
        await jest.advanceTimersByTimeAsync(2 * 30_000);
      });

      expect(screen.getByText("Last synced 1 minute ago")).toBeOnTheScreen();
      expect(spoken).toEqual(["Last synced 1 minute ago"]);
    } finally {
      jest.useRealTimers();
    }
  });

  it("006-SC-004 stays silent while the footer's words do not change", async () => {
    jest.useFakeTimers({ doNotFake: ["nextTick"] });
    const spoken = captureAnnouncements();
    try {
      await openTask(makeTask({ id: "t1" }));
      await screen.findByText("Not synced yet");

      // Four ticks of the footer's clock on a device that has never synced.
      await act(async () => {
        await jest.advanceTimersByTimeAsync(4 * 30_000);
      });

      expect(screen.getByText("Not synced yet")).toBeOnTheScreen();
      expect(spoken).toEqual([]);
    } finally {
      jest.useRealTimers();
    }
  });
});

describe("task detail — a change made with no connection", () => {
  it("006-FR-007 shows an unsent change as made, marked in no way at all", async () => {
    // The classification drain's request never reaches the server.
    const offline = await openTask(makeTask({ id: "t1", project_id: null, tag_ids: [] }), {
      routes: { "PATCH /tasks/t1": unreachable },
    });

    await fireEvent.press(await screen.findByLabelText("Project, none set"));
    await fireEvent.press(await screen.findByLabelText("Q3 launch"));

    expect(await screen.findByLabelText("Project, Q3 launch")).toBeOnTheScreen();
    expect(screen.getByText("Q3 launch")).toBeOnTheScreen();
    for (const marker of [
      /unsent/i,
      /not sent/i,
      /pending/i,
      /queued/i,
      /waiting to send/i,
      /will send/i,
      /offline/i,
    ]) {
      expect(screen.queryByText(marker)).toBeNull();
    }
    // Exactly one thing on the whole screen mentions synchronising, and it is
    // the screen-wide footer — never a marker beside the row that changed.
    expect(screen.getAllByText(/synced/i)).toHaveLength(1);
    expect(screen.getByText("Not synced yet")).toBeOnTheScreen();

    const changedOffline = rowNames();
    await offline.unmount();
    backend.restore();

    // The same task as the server holds it. FR-007's claim is an equality: a
    // change the server has not seen is presented exactly like one it has.
    await openTask(makeTask({ id: "t1", project_id: "p2", tag_ids: [] }));
    await screen.findByLabelText("Project, Q3 launch");

    expect(changedOffline).toEqual(rowNames());
    expect(changedOffline).toEqual([
      "Project, Q3 launch",
      "Tags, none set",
      "Due, none set",
      "Priority, none set",
    ]);
  });
});

describe("task detail — work the 30-day bound discarded", () => {
  it("006-FR-018 006-SC-003 names the field, what it reverted to, and offers a labelled Dismiss", async () => {
    await seedQueue([queuedChange()]);

    await openTask(makeTask({ id: "t1", project_id: "p1", tag_ids: [] }));

    const sentence =
      "Your change to Project from 31 days ago was not sent and has been discarded. " +
      "This now shows Wedding.";
    expect(await screen.findByText(sentence)).toBeOnTheScreen();
    expect(screen.getByLabelText(sentence)).toBeOnTheScreen();
    // The row shows the server's value again — the notice is the only reason
    // that is not a value changing back on its own.
    expect(screen.getByLabelText("Project, Wedding")).toBeOnTheScreen();

    // The dismiss control is labelled, and sits immediately after the row it
    // explains rather than at the top of the screen.
    const names = buttonNames();
    expect(names[names.indexOf("Project, Wedding") + 1]).toBe("Dismiss");

    await fireEvent.press(screen.getByLabelText("Dismiss"));

    await waitFor(() => expect(screen.queryByText(sentence)).toBeNull());
    expect(await AsyncStorage.getItem(QUEUE_KEY)).toBeNull();
  });

  it("006-FR-018 anchors a discarded Tag change under the Tags row", async () => {
    await seedQueue([queuedChange({ value: { projectId: undefined, tagIds: ["g2"] } })]);

    await openTask(makeTask({ id: "t1", project_id: null, tag_ids: ["g1"] }));

    expect(
      await screen.findByText(
        "Your change to Tags from 31 days ago was not sent and has been discarded. " +
          "This now shows errand.",
      ),
    ).toBeOnTheScreen();
    const names = buttonNames();
    expect(names[names.indexOf("Tags, errand") + 1]).toBe("Dismiss");
  });

  it("006-FR-018 keeps the per-task notice on a closed task, which has no row to anchor to", async () => {
    await seedQueue([queuedChange()]);

    await openTask(makeTask({ id: "t1", state: "completed", project_id: "p1", tag_ids: [] }));

    expect(
      await screen.findByText(
        "Your change to Project from 31 days ago was not sent and has been discarded. " +
          "This now shows Wedding.",
      ),
    ).toBeOnTheScreen();
    expect(rowNames()).toEqual([]);
  });

  it("006-FR-018 states the account-wide total for a sweep this task cannot account for", async () => {
    await seedQueue([
      queuedChange({ taskId: "t1", idempotencyKey: "key-1" }),
      queuedChange({ taskId: "t2", idempotencyKey: "key-2" }),
      queuedChange({ taskId: "t3", idempotencyKey: "key-3" }),
    ]);

    await openTask(makeTask({ id: "t1", project_id: "p1", tag_ids: [] }));

    const total = "3 changes older than 30 days were not sent and have been discarded";
    expect(await screen.findByText(total)).toBeOnTheScreen();

    // It leads the screen, so its Dismiss is the first one in reading order,
    // and dismissing it leaves the per-task notice standing.
    await fireEvent.press(screen.getAllByLabelText("Dismiss")[0]);

    await waitFor(() => expect(screen.queryByText(total)).toBeNull());
    expect(screen.getByText(/^Your change to Project from 31 days ago/)).toBeOnTheScreen();
  });

  it("006-FR-018 does not repeat a total of one this screen already names in full", async () => {
    await seedQueue([queuedChange()]);

    await openTask(makeTask({ id: "t1", project_id: "p1", tag_ids: [] }));

    await screen.findByText(/^Your change to Project from 31 days ago/);
    expect(screen.queryByText(/older than 30 days/)).toBeNull();
  });
});

describe("task detail — an offline cold start", () => {
  it("006-SC-009 reaches a usable classification screen from what the device already holds", async () => {
    const savedAt = new Date().toISOString();
    await AsyncStorage.multiSet([
      [identityStorageKey(DEFAULT_SERVER_URL), JSON.stringify({ accountId: ACCOUNT, savedAt })],
      [
        flagStorageKey(DEFAULT_SERVER_URL, ACCOUNT),
        JSON.stringify({ flags: { [TASK_CLASSIFICATION_FLAG]: true }, savedAt }),
      ],
      [
        CACHE_KEY,
        JSON.stringify({
          projects: [{ id: "p1", name: "Wedding" }],
          tags: [{ id: "g1", name: "errand" }],
          fetchedAt: savedAt,
        }),
      ],
    ]);

    // Nothing the server owns answers: no profile, no flag, no lists.
    backend = installFakeBackend({
      "GET /auth/me": unreachable,
      "GET /projects": unreachable,
      "GET /tags": unreachable,
      "GET /tasks/t1": () => makeTask({ id: "t1", project_id: "p1", tag_ids: ["g1"] }),
    });
    setSearchParams({ id: "t1" });
    await renderWithSession(<TaskDetailScreen />);
    await screen.findByDisplayValue("Call the notary");

    // The rollout flag, the identity and both lists resolved from the device.
    expect(await screen.findByLabelText("Project, Wedding")).toBeOnTheScreen();
    expect(screen.getByLabelText("Tags, errand")).toBeOnTheScreen();
    expect(screen.getByText("Not synced yet")).toBeOnTheScreen();

    // Usable, not merely legible: the row opens onto the stored list, and
    // clearing — which needs no list at all — is offered.
    await fireEvent.press(screen.getByLabelText("Project, Wedding"));

    expect(
      await screen.findByText(
        "Offline. You can pick a project that already exists; " +
          "creating a new one needs a connection.",
      ),
    ).toBeOnTheScreen();
    expect(screen.getByLabelText("Wedding")).toBeOnTheScreen();
    expect(screen.getByLabelText("No project")).toBeOnTheScreen();
  });
});
