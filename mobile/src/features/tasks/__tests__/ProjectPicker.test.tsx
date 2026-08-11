/**
 * M-02 — the project picker, rendered.
 *
 * `pickerState.test.ts` asserts the decisions as data; this file asserts that a
 * person actually meets them on screen. Every row of design.md's M-02 state
 * table appears below as a rendered assertion, and each one is written against
 * what a person can perceive — the accessible name of a row, the words in a
 * banner, whether a control is disabled and what reason it states — rather than
 * against which callback fired.
 *
 * The picker is mounted inside `TaskWithProjectPicker`, a stand-in for the task
 * screen it hangs off. That host owns the task's project and applies what the
 * picker chooses, exactly as `app/task/[id].tsx` does, so "the project was
 * cleared" can be asserted as the value the task ended up showing rather than as
 * an argument handed to a spy.
 */

import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react-native";
import { useState } from "react";
import { Pressable, Text } from "react-native";

import { ApiError } from "@/api/client";

import type { NamedEntity } from "../matchExisting";
import type { AttachedEntity, ListPhase } from "../pickerState";
import { ProjectPicker } from "../ProjectPicker";

const PROJECTS: NamedEntity[] = [
  { id: "project_1", name: "Onboarding drop-off" },
  { id: "project_2", name: "Q3 planning" },
  { id: "project_3", name: "Personal admin" },
];

/** design.md M-02 loading: "Three skeleton rows" after this grace, none before. */
const SKELETON_GRACE_MS = 300;

interface HostProps {
  /** What the device can offer. `null` is "holds no list at all". */
  projects?: readonly NamedEntity[] | null;
  value?: AttachedEntity | null;
  listPhase?: ListPhase;
  online?: boolean;
  correlationId?: string;
  /** Stands in for the screen's create-and-attach; defaults to one that works. */
  onCreate?: (name: string) => Promise<NamedEntity>;
  /** What a retry recovers, if anything. */
  recovered?: readonly NamedEntity[];
}

/**
 * The task screen, reduced to the part M-02 touches: it shows the task's
 * project, opens the picker, and applies what comes back.
 */
function TaskWithProjectPicker({
  projects = PROJECTS,
  value: initialValue = null,
  listPhase = "loaded",
  online = true,
  correlationId,
  onCreate,
  recovered,
}: HostProps) {
  const [visible, setVisible] = useState(true);
  const [value, setValue] = useState<AttachedEntity | null>(initialValue);
  const [list, setList] = useState<readonly NamedEntity[] | null>(projects);
  const [phase, setPhase] = useState<ListPhase>(listPhase);

  const nameOf = (id: string) => list?.find((project) => project.id === id)?.name;
  const shown = value === null ? "no project" : (value.name ?? value.id);

  return (
    <>
      <Text>{`On the task: ${shown}`}</Text>
      <Pressable
        accessibilityRole="button"
        accessibilityLabel="Open the project picker"
        onPress={() => setVisible(true)}
      />
      {/* The queue draining someone else's change into this task while the
          picker is open — M-02's "a change arriving while it is open". */}
      <Pressable
        accessibilityRole="button"
        accessibilityLabel="Another device sets Personal admin"
        onPress={() => setValue({ id: "project_3", name: "Personal admin" })}
      />
      <ProjectPicker
        visible={visible}
        onClose={() => setVisible(false)}
        value={value}
        onSelect={(projectId) => {
          setValue(
            projectId === null
              ? null
              : { id: projectId, ...(nameOf(projectId) === undefined ? {} : { name: nameOf(projectId)! }) },
          );
        }}
        onCreate={
          onCreate ??
          (async (name: string) => {
            // FR-004 — the parent creates *and* attaches, in one action.
            const created = { id: `project_new_${name}`, name };
            setList([...(list ?? []), created]);
            setValue(created);
            return created;
          })
        }
        projects={list}
        listPhase={phase}
        online={online}
        onRetry={() => {
          setList(recovered ?? list);
          setPhase(recovered ? "loaded" : "failed");
        }}
        {...(correlationId === undefined ? {} : { correlationId })}
      />
    </>
  );
}

/**
 * The names assistive technology reads out for the option rows, in the order
 * they are laid out — the check glyph is decorative, so the row's own name is
 * the whole of what is announced.
 */
function optionNames(): string[] {
  return screen.getAllByRole("radio").map((row) => String(row.props.accessibilityLabel));
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

describe("006-FR-001 006-FR-003 M-02 project picker, default state", () => {
  it("006-FR-001 lists None first, checked, then every project the device holds", async () => {
    await render(<TaskWithProjectPicker />);

    expect(screen.getByText("Project")).toBeOnTheScreen();
    expect(optionNames()).toEqual([
      "No project",
      "Onboarding drop-off",
      "Q3 planning",
      "Personal admin",
    ]);
    expect(screen.getByLabelText("No project")).toBeChecked();
    expect(screen.getByText("None")).toBeOnTheScreen();
    expect(screen.getByText("A task has one project, or none")).toBeOnTheScreen();
  });

  it("006-FR-003 checks the task's own project, and only it", async () => {
    await render(
      <TaskWithProjectPicker value={{ id: "project_2", name: "Q3 planning" }} />,
    );

    expect(screen.getByLabelText("Q3 planning")).toBeChecked();
    expect(screen.getByLabelText("No project")).not.toBeChecked();
    expect(screen.getByLabelText("Onboarding drop-off")).not.toBeChecked();
  });

  it("006-FR-003 puts the chosen project on the task, replacing the previous one", async () => {
    await render(
      <TaskWithProjectPicker value={{ id: "project_1", name: "Onboarding drop-off" }} />,
    );

    await fireEvent.press(screen.getByLabelText("Q3 planning"));

    expect(screen.getByText("On the task: Q3 planning")).toBeOnTheScreen();
    // Choosing closes the picker: there is nothing left to confirm.
    expect(screen.queryByLabelText("Q3 planning")).toBeNull();

    await fireEvent.press(screen.getByLabelText("Open the project picker"));
    expect(screen.getByLabelText("Q3 planning")).toBeChecked();
    expect(screen.getByLabelText("Onboarding drop-off")).not.toBeChecked();
  });

  it("006-FR-001 clears the project from the None row", async () => {
    await render(
      <TaskWithProjectPicker value={{ id: "project_2", name: "Q3 planning" }} />,
    );

    await fireEvent.press(screen.getByLabelText("No project"));

    expect(screen.getByText("On the task: no project")).toBeOnTheScreen();

    await fireEvent.press(screen.getByLabelText("Open the project picker"));
    expect(screen.getByLabelText("No project")).toBeChecked();
  });

  it("006-FR-005 filters the rows to what was typed, and leaves the rest reachable", async () => {
    await render(<TaskWithProjectPicker />);

    await fireEvent.changeText(
      screen.getByLabelText("Search or type a new name"),
      "planning",
    );

    expect(optionNames()).toEqual(["Q3 planning"]);

    await fireEvent.changeText(screen.getByLabelText("Search or type a new name"), "");
    expect(optionNames()).toHaveLength(4);
  });

  it("006-FR-001 closes on Cancel without changing the task", async () => {
    await render(
      <TaskWithProjectPicker value={{ id: "project_2", name: "Q3 planning" }} />,
    );

    await fireEvent.press(screen.getByText("Cancel"));

    expect(screen.queryByText("Project")).toBeNull();
    expect(screen.getByText("On the task: Q3 planning")).toBeOnTheScreen();
  });
});

describe("006-FR-001 M-02 loading: skeleton rows only after 300 ms, never a spinner", () => {
  it("006-FR-001 shows nothing for the first 300 ms, then three placeholder rows", async () => {
    jest.useFakeTimers({ doNotFake: ["nextTick"] });
    try {
      await render(<TaskWithProjectPicker projects={null} listPhase="loading" />);

      await act(async () => {
        await jest.advanceTimersByTimeAsync(SKELETON_GRACE_MS - 1);
      });
      expect(screen.queryByLabelText("Loading your projects")).toBeNull();

      await act(async () => {
        await jest.advanceTimersByTimeAsync(1);
      });
      const skeleton = screen.getByLabelText("Loading your projects");
      expect(skeleton).toBeOnTheScreen();
      expect(skeleton.children).toHaveLength(3);
    } finally {
      jest.useRealTimers();
    }
  });

  it("006-FR-005 offers no create row while loading: the duplicate check has no list yet", async () => {
    jest.useFakeTimers({ doNotFake: ["nextTick"] });
    try {
      await render(<TaskWithProjectPicker projects={null} listPhase="loading" />);
      await act(async () => {
        await jest.advanceTimersByTimeAsync(SKELETON_GRACE_MS);
      });

      expect(screen.queryByText(/^Create /)).toBeNull();
      expect(screen.queryByRole("radio")).toBeNull();
    } finally {
      jest.useRealTimers();
    }
  });

  it("006-FR-001 never covers a list it already holds with placeholders", async () => {
    jest.useFakeTimers({ doNotFake: ["nextTick"] });
    try {
      // A slow refresh over the list last stored on the device.
      await render(<TaskWithProjectPicker listPhase="loading" />);
      await act(async () => {
        await jest.advanceTimersByTimeAsync(5_000);
      });

      expect(screen.queryByLabelText("Loading your projects")).toBeNull();
      expect(screen.getByLabelText("Q3 planning")).toBeOnTheScreen();
    } finally {
      jest.useRealTimers();
    }
  });
});

describe("006-FR-004 M-02 empty on a first run: the rows are present, not hidden", () => {
  it("006-FR-004 says no projects exist yet, and still offers None and the create row", async () => {
    await render(<TaskWithProjectPicker projects={[]} />);

    expect(screen.getByText("No projects yet")).toBeOnTheScreen();
    expect(optionNames()).toEqual(["No project"]);
    expect(screen.getByText("Create “…”")).toBeOnTheScreen();
  });

  it("006-FR-016 states in text what the empty create row is waiting for", async () => {
    await render(<TaskWithProjectPicker projects={[]} />);

    const create = screen.getByLabelText("Create “…”. Type a name to create one");
    expect(create).toBeDisabled();
    expect(screen.getByText("Type a name to create one")).toBeOnTheScreen();
  });

  it("006-FR-004 turns the create row into a real one as soon as a name is typed", async () => {
    await render(<TaskWithProjectPicker projects={[]} />);

    await fireEvent.changeText(
      screen.getByLabelText("Search or type a new name"),
      "Q4 planning",
    );

    const create = screen.getByLabelText("Create “Q4 planning”");
    expect(create).toBeEnabled();
    expect(screen.queryByText("Type a name to create one")).toBeNull();
  });
});

describe("006-FR-005 M-02 empty, filtered to nothing", () => {
  it("006-FR-005 drops every project row and offers a create carrying the typed name", async () => {
    await render(<TaskWithProjectPicker />);

    await fireEvent.changeText(
      screen.getByLabelText("Search or type a new name"),
      "Q4 planning",
    );

    expect(screen.queryByRole("radio")).toBeNull();
    expect(screen.getByLabelText("Create “Q4 planning”")).toBeEnabled();
  });
});

describe("006-FR-012 M-02 error: the failure is actionable and names itself", () => {
  it("006-FR-012 states the failure with its correlation id and a retry that reloads", async () => {
    await render(
      <TaskWithProjectPicker
        projects={null}
        listPhase="failed"
        correlationId="corr-7f3a"
        recovered={PROJECTS}
      />,
    );

    expect(screen.getByText("We couldn't load your projects.")).toBeOnTheScreen();
    expect(screen.getByText("ref: corr-7f3a")).toBeOnTheScreen();

    await fireEvent.press(screen.getByText("Retry"));

    expect(screen.getByLabelText("Q3 planning")).toBeOnTheScreen();
    expect(screen.queryByText("We couldn't load your projects.")).toBeNull();
  });

  it("006-FR-001 006-FR-012 keeps the task's project shown, and still clearable", async () => {
    await render(
      <TaskWithProjectPicker
        projects={null}
        listPhase="failed"
        value={{ id: "project_2", name: "Q3 planning" }}
      />,
    );

    expect(screen.getByLabelText("Q3 planning")).toBeChecked();

    await fireEvent.press(screen.getByLabelText("No project"));

    expect(screen.getByText("On the task: no project")).toBeOnTheScreen();
  });

  it("006-FR-005 offers no create row while the list is unreadable", async () => {
    await render(<TaskWithProjectPicker projects={null} listPhase="failed" />);

    expect(screen.queryByText(/^Create /)).toBeNull();
  });
});

describe("006-FR-016 M-02 offline with a list the device already holds", () => {
  it("006-FR-016 says offline in words, and still lets an existing project be chosen", async () => {
    await render(<TaskWithProjectPicker online={false} />);

    expect(
      screen.getByText(
        "Offline. You can pick a project that already exists; creating a new one needs a connection.",
      ),
    ).toBeOnTheScreen();

    await fireEvent.press(screen.getByLabelText("Personal admin"));

    expect(screen.getByText("On the task: Personal admin")).toBeOnTheScreen();
  });

  it("006-FR-016 disables the create row with its reason in text, before it is tapped", async () => {
    await render(<TaskWithProjectPicker online={false} />);

    await fireEvent.changeText(
      screen.getByLabelText("Search or type a new name"),
      "Q4 planning",
    );

    const create = screen.getByLabelText(
      "Create “Q4 planning”. Needs a connection — new projects are named by the server",
    );
    expect(create).toBeDisabled();
    // The reason is readable, not merely announced: state is never colour alone.
    expect(
      within(create).getByText("Needs a connection — new projects are named by the server"),
    ).toBeOnTheScreen();
    expect(within(create).getByText("Create “Q4 planning”")).toBeOnTheScreen();
  });

  it("006-FR-016 keeps the blocked create row visible rather than hiding it", async () => {
    await render(<TaskWithProjectPicker online={false} projects={[]} />);

    expect(screen.getByText("Create “…”")).toBeOnTheScreen();
    expect(
      screen.getByText("Needs a connection — new projects are named by the server"),
    ).toBeOnTheScreen();
  });
});

describe("006-FR-001 006-FR-016 M-02 offline, never fetched", () => {
  const neverFetched = { projects: null, listPhase: "loading" as ListPhase, online: false };

  it("006-FR-016 says so plainly instead of claiming the person has no projects", async () => {
    await render(<TaskWithProjectPicker {...neverFetched} />);

    expect(
      screen.getByText("Can't load your projects without a connection"),
    ).toBeOnTheScreen();
    expect(screen.queryByText("No projects yet")).toBeNull();
    // Nothing to filter, so no search field is offered — design.md's focus note.
    expect(screen.queryByLabelText("Search or type a new name")).toBeNull();
    expect(screen.queryByText(/^Create /)).toBeNull();
  });

  it("006-FR-001 keeps None available: clearing needs no fetched list", async () => {
    await render(
      <TaskWithProjectPicker {...neverFetched} value={{ id: "project_9" }} />,
    );

    // The device holds the id but not the name, and says which it is.
    expect(optionNames()).toEqual([
      "No project",
      "Project — needs a connection to show its name",
    ]);
    expect(
      screen.getByLabelText("Project — needs a connection to show its name"),
    ).toBeChecked();

    await fireEvent.press(screen.getByLabelText("No project"));

    expect(screen.getByText("On the task: no project")).toBeOnTheScreen();
  });
});

describe("006-FR-005 M-02 offers an existing project instead of a duplicate", () => {
  it("006-FR-005 offers the project that already carries the typed name", async () => {
    await render(<TaskWithProjectPicker />);

    await fireEvent.changeText(
      screen.getByLabelText("Search or type a new name"),
      "q3 PLANNING",
    );

    expect(screen.queryByText(/^Create /)).toBeNull();

    await fireEvent.press(screen.getByLabelText("Use “Q3 planning” — it already exists"));

    expect(screen.getByText("On the task: Q3 planning")).toBeOnTheScreen();
  });

  it("006-FR-005 says the match is already this task's project rather than offering it again", async () => {
    await render(
      <TaskWithProjectPicker value={{ id: "project_2", name: "Q3 planning" }} />,
    );

    await fireEvent.changeText(
      screen.getByLabelText("Search or type a new name"),
      "Q3 planning",
    );

    expect(screen.getByText("“Q3 planning” is already this task's project")).toBeOnTheScreen();
    expect(
      screen.queryByRole("button", { name: "“Q3 planning” is already this task's project" }),
    ).toBeNull();
  });

  it("006-FR-005 still offers a create for a name that merely starts the same", async () => {
    await render(<TaskWithProjectPicker />);

    await fireEvent.changeText(screen.getByLabelText("Search or type a new name"), "Q3");

    expect(screen.getByLabelText("Create “Q3”")).toBeEnabled();
  });
});

describe("006-FR-004 M-02 create and attach in one action", () => {
  it("006-FR-004 attaches the new project and closes", async () => {
    await render(<TaskWithProjectPicker projects={[]} />);

    await fireEvent.changeText(
      screen.getByLabelText("Search or type a new name"),
      "Q4 planning",
    );
    await fireEvent.press(screen.getByLabelText("Create “Q4 planning”"));

    await waitFor(() => expect(screen.queryByText("Project")).toBeNull());
    expect(screen.getByText("On the task: Q4 planning")).toBeOnTheScreen();

    await fireEvent.press(screen.getByLabelText("Open the project picker"));
    // The typed name is gone and the new project carries the check.
    expect(screen.getByLabelText("Q4 planning")).toBeChecked();
    expect(screen.getByLabelText("Search or type a new name").props.value).toBe("");
  });

  it("006-FR-004 stops taking taps while the create is in flight", async () => {
    const pending = deferred<NamedEntity>();
    await render(
      <TaskWithProjectPicker onCreate={() => pending.promise} />,
    );

    // A query that still leaves a project row on screen, so the freeze can be
    // seen on the rows as well as on the create row.
    await fireEvent.changeText(screen.getByLabelText("Search or type a new name"), "planning");
    await fireEvent.press(screen.getByLabelText("Create “planning”"));

    // The server owns the new project's identity, so a tap landing between the
    // request and its answer must not be applied under it.
    expect(screen.getByLabelText("Create “planning”")).toBeDisabled();
    expect(screen.getByLabelText("Q3 planning")).toBeDisabled();
    expect(screen.getByText("Cancel")).toBeDisabled();

    await fireEvent.press(screen.getByLabelText("Q3 planning"));
    expect(screen.getByText("On the task: no project")).toBeOnTheScreen();

    await fireEvent.changeText(screen.getByLabelText("Search or type a new name"), "Q5");
    expect(screen.getByLabelText("Search or type a new name").props.value).toBe("planning");

    await act(async () => {
      pending.resolve({ id: "project_4", name: "planning" });
    });
  });

  it("006-FR-004 leaves the typed name and the task's project untouched when the create fails", async () => {
    await render(
      <TaskWithProjectPicker
        value={{ id: "project_1", name: "Onboarding drop-off" }}
        onCreate={() =>
          Promise.reject(
            new ApiError("Request failed", 503, {
              message: "We couldn't reach the server.",
              reference_id: "corr-91b2",
            }),
          )
        }
      />,
    );

    await fireEvent.changeText(
      screen.getByLabelText("Search or type a new name"),
      "Q4 planning",
    );
    await fireEvent.press(screen.getByLabelText("Create “Q4 planning”"));

    expect(await screen.findByText("We couldn't reach the server.")).toBeOnTheScreen();
    expect(screen.getByText("ref: corr-91b2")).toBeOnTheScreen();
    // T057 — a retry costs no retyping, and the classification did not move.
    expect(screen.getByLabelText("Search or type a new name").props.value).toBe("Q4 planning");
    expect(screen.getByLabelText("Create “Q4 planning”")).toBeEnabled();
    expect(screen.getByText("On the task: Onboarding drop-off")).toBeOnTheScreen();
  });

  it("006-FR-004 drops the failure once a different name is typed", async () => {
    await render(
      <TaskWithProjectPicker
        onCreate={() => Promise.reject(new Error("Creating that failed."))}
      />,
    );

    await fireEvent.changeText(
      screen.getByLabelText("Search or type a new name"),
      "Q4 planning",
    );
    await fireEvent.press(screen.getByLabelText("Create “Q4 planning”"));
    expect(await screen.findByText("Creating that failed.")).toBeOnTheScreen();

    await fireEvent.changeText(
      screen.getByLabelText("Search or type a new name"),
      "Q5 planning",
    );

    expect(screen.queryByText("Creating that failed.")).toBeNull();
  });
});

describe("006-FR-003 M-02 reopening and outside changes", () => {
  it("006-FR-003 forgets the last visit's search when reopened", async () => {
    await render(<TaskWithProjectPicker />);

    await fireEvent.changeText(
      screen.getByLabelText("Search or type a new name"),
      "planning",
    );
    await fireEvent.press(screen.getByText("Cancel"));
    await fireEvent.press(screen.getByLabelText("Open the project picker"));

    expect(screen.getByLabelText("Search or type a new name").props.value).toBe("");
    expect(optionNames()).toHaveLength(4);
  });

  it("006-FR-003 moves the check when the task changes underneath, keeping a half-typed name", async () => {
    await render(<TaskWithProjectPicker />);

    await fireEvent.changeText(screen.getByLabelText("Search or type a new name"), "admin");
    await fireEvent.press(screen.getByLabelText("Another device sets Personal admin"));

    expect(screen.getByLabelText("Search or type a new name").props.value).toBe("admin");
    expect(screen.getByLabelText("Personal admin")).toBeChecked();
  });
});
