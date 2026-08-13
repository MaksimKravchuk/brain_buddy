/**
 * M-03 — the Tag picker, rendered.
 *
 * `pickerState.test.ts` asserts the decisions as data; this file asserts that a
 * person actually meets them on screen. Every row of design.md's M-03 state
 * table appears below as a rendered assertion, written against what a person
 * can perceive — the accessible name of a row, whether it is checked, the words
 * in a banner, whether a control is disabled and what reason it states.
 *
 * The picker is mounted inside `TaskWithTagPicker`, a stand-in for the task
 * screen it hangs off: it holds the task's Tag ids, resolves their names the way
 * `attachedEntities` does, and applies the whole intended set the picker hands
 * back (FR-002). So "the Tag was detached" is asserted as what the task ended up
 * carrying, not as an argument handed to a spy.
 */

import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react-native";
import { useState } from "react";
import { Pressable, Text } from "react-native";

import { ApiError } from "@/api/client";

import type { NamedEntity } from "../matchExisting";
import type { AttachedEntity, ListPhase } from "../pickerState";
import { TagPicker } from "../TagPicker";

const TAGS: NamedEntity[] = [
  { id: "tag_1", name: "writing" },
  { id: "tag_2", name: "deep-work" },
  { id: "tag_3", name: "errand" },
  { id: "tag_4", name: "home" },
];

/** design.md M-03 loading: "Three skeleton rows" after this grace, none before. */
const SKELETON_GRACE_MS = 300;

interface HostProps {
  /** What the device can offer. `null` is "holds no list at all". */
  tags?: readonly NamedEntity[] | null;
  /** The Tag ids the task carries. */
  attached?: readonly string[];
  /**
   * Names the device knows without the list — the stand-in for what
   * `classificationCache` last stored. Defaults to the list itself.
   */
  knownNames?: readonly NamedEntity[];
  listPhase?: ListPhase;
  online?: boolean;
  correlationId?: string;
  /** Stands in for the screen's create-and-attach; defaults to one that works. */
  onCreate?: (name: string) => Promise<NamedEntity>;
  /** What a retry recovers, if anything. */
  recovered?: readonly NamedEntity[];
}

/**
 * The task screen, reduced to the part M-03 touches: it shows the task's Tags,
 * opens the picker, and applies the set that comes back.
 */
function TaskWithTagPicker({
  tags = TAGS,
  attached: initialAttached = [],
  knownNames,
  listPhase = "loaded",
  online = true,
  correlationId,
  onCreate,
  recovered,
}: HostProps) {
  const [visible, setVisible] = useState(true);
  const [tagIds, setTagIds] = useState<readonly string[]>(initialAttached);
  const [list, setList] = useState<readonly NamedEntity[] | null>(tags);
  const [phase, setPhase] = useState<ListPhase>(listPhase);

  // The same resolution `attachedEntities` performs on the real screen: the task
  // holds ids, and a name is attached only where the device knows one. Rebuilt
  // every render on purpose — that is the identity churn the picker has to
  // survive without wiping a half-typed name.
  const names = knownNames ?? list ?? [];
  const attached: AttachedEntity[] = tagIds.map((id) => {
    const name = names.find((tag) => tag.id === id)?.name;
    return name === undefined ? { id } : { id, name };
  });
  const shown =
    attached.length === 0 ? "no Tags" : attached.map((tag) => tag.name ?? tag.id).join(", ");

  return (
    <>
      <Text>{`On the task: ${shown}`}</Text>
      <Pressable
        accessibilityRole="button"
        accessibilityLabel="Open the Tag picker"
        onPress={() => setVisible(true)}
      />
      {/* The queue draining someone else's change into this task while the
          picker is open — M-03's "a change arriving while it is open". */}
      <Pressable
        accessibilityRole="button"
        accessibilityLabel="Another device attaches errand"
        onPress={() => setTagIds(["tag_3"])}
      />
      <TagPicker
        visible={visible}
        onClose={() => setVisible(false)}
        attached={attached}
        onChange={(next) => setTagIds(next)}
        onCreate={
          onCreate ??
          (async (name: string) => {
            // FR-004 — the parent creates *and* attaches, in one action.
            const created = { id: `tag_new_${name}`, name };
            setList([...(list ?? []), created]);
            setTagIds([...tagIds, created.id]);
            return created;
          })
        }
        tags={list}
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
 * The names assistive technology reads out for the Tag rows, in the order they
 * are laid out — the check glyph is decorative, so the row's own name is the
 * whole of what is announced.
 */
function tagNames(): string[] {
  return screen.getAllByRole("checkbox").map((row) => String(row.props.accessibilityLabel));
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

describe("006-FR-002 M-03 Tag picker, default state", () => {
  it("006-FR-002 lists every Tag, checking the ones the task carries", async () => {
    await render(<TaskWithTagPicker attached={["tag_2"]} />);

    expect(screen.getByText("Tags")).toBeOnTheScreen();
    expect(tagNames()).toEqual(["writing", "deep-work", "errand", "home"]);
    expect(screen.getByLabelText("deep-work")).toBeChecked();
    expect(screen.getByLabelText("writing")).not.toBeChecked();
    expect(screen.getByText("1 Tag selected")).toBeOnTheScreen();
  });

  it("006-FR-002 offers no None row: a Tag is cleared by detaching it", async () => {
    await render(<TaskWithTagPicker />);

    expect(screen.queryByText("None")).toBeNull();
    expect(screen.queryByLabelText("No project")).toBeNull();
    expect(screen.getByText("No Tags selected")).toBeOnTheScreen();
  });

  it("006-FR-002 attaches several Tags, leaving the ones already attached alone", async () => {
    await render(<TaskWithTagPicker attached={["tag_1"]} />);

    await fireEvent.press(screen.getByLabelText("errand"));
    await fireEvent.press(screen.getByLabelText("home"));

    expect(screen.getByLabelText("writing")).toBeChecked();
    expect(screen.getByLabelText("errand")).toBeChecked();
    expect(screen.getByLabelText("home")).toBeChecked();
    expect(screen.getByText("3 Tags selected")).toBeOnTheScreen();
    expect(screen.getByText("On the task: writing, errand, home")).toBeOnTheScreen();
    // Multi-select: the sheet stays open between taps.
    expect(screen.getByText("Done")).toBeOnTheScreen();
  });

  it("006-FR-002 detaches one Tag without touching the others, and can re-attach it", async () => {
    await render(<TaskWithTagPicker attached={["tag_1", "tag_3"]} />);

    await fireEvent.press(screen.getByLabelText("writing"));

    expect(screen.getByLabelText("writing")).not.toBeChecked();
    expect(screen.getByLabelText("errand")).toBeChecked();
    expect(screen.getByText("On the task: errand")).toBeOnTheScreen();

    await fireEvent.press(screen.getByLabelText("writing"));

    expect(screen.getByText("On the task: errand, writing")).toBeOnTheScreen();
    expect(screen.getByText("2 Tags selected")).toBeOnTheScreen();
  });

  it("006-FR-002 closes on Done, keeping every toggle already applied", async () => {
    await render(<TaskWithTagPicker attached={["tag_1"]} />);

    await fireEvent.press(screen.getByLabelText("home"));
    await fireEvent.press(screen.getByText("Done"));

    expect(screen.queryByText("Tags")).toBeNull();
    expect(screen.getByText("On the task: writing, home")).toBeOnTheScreen();
  });

  it("006-FR-005 filters the rows to what was typed", async () => {
    await render(<TaskWithTagPicker />);

    await fireEvent.changeText(screen.getByLabelText("Search Tags"), "work");

    expect(tagNames()).toEqual(["deep-work"]);
  });
});

describe("006-FR-002 M-03 loading: skeleton rows only after 300 ms, never a spinner", () => {
  it("006-FR-002 shows nothing for the first 300 ms, then three placeholder rows", async () => {
    jest.useFakeTimers({ doNotFake: ["nextTick"] });
    try {
      await render(<TaskWithTagPicker tags={null} listPhase="loading" />);

      await act(async () => {
        await jest.advanceTimersByTimeAsync(SKELETON_GRACE_MS - 1);
      });
      expect(screen.queryByLabelText("Loading your Tags")).toBeNull();

      await act(async () => {
        await jest.advanceTimersByTimeAsync(1);
      });
      const skeleton = screen.getByLabelText("Loading your Tags");
      expect(skeleton).toBeOnTheScreen();
      expect(skeleton.children).toHaveLength(3);
    } finally {
      jest.useRealTimers();
    }
  });

  it("006-FR-005 offers no create row while loading: the duplicate check has no list yet", async () => {
    jest.useFakeTimers({ doNotFake: ["nextTick"] });
    try {
      await render(<TaskWithTagPicker tags={null} listPhase="loading" />);
      await act(async () => {
        await jest.advanceTimersByTimeAsync(SKELETON_GRACE_MS);
      });

      expect(screen.queryByText(/^Create /)).toBeNull();
      expect(screen.queryByRole("checkbox")).toBeNull();
    } finally {
      jest.useRealTimers();
    }
  });

  it("006-FR-002 never covers a list it already holds with placeholders", async () => {
    jest.useFakeTimers({ doNotFake: ["nextTick"] });
    try {
      // A slow refresh over the list last stored on the device.
      await render(<TaskWithTagPicker listPhase="loading" />);
      await act(async () => {
        await jest.advanceTimersByTimeAsync(5_000);
      });

      expect(screen.queryByLabelText("Loading your Tags")).toBeNull();
      expect(screen.getByLabelText("errand")).toBeOnTheScreen();
    } finally {
      jest.useRealTimers();
    }
  });
});

describe("006-FR-004 M-03 empty on a first run: the create row is present, not hidden", () => {
  it("006-FR-004 says no Tags exist yet and still offers the create row", async () => {
    await render(<TaskWithTagPicker tags={[]} />);

    expect(screen.getByText("No Tags yet")).toBeOnTheScreen();
    expect(screen.queryByRole("checkbox")).toBeNull();
    expect(screen.getByText("Create “…”")).toBeOnTheScreen();
  });

  it("006-FR-016 states in text what the empty create row is waiting for", async () => {
    await render(<TaskWithTagPicker tags={[]} />);

    expect(screen.getByLabelText("Create “…”. Type a name to create one")).toBeDisabled();
    expect(screen.getByText("Type a name to create one")).toBeOnTheScreen();
  });

  it("006-FR-004 turns the create row into a real one as soon as a name is typed", async () => {
    await render(<TaskWithTagPicker tags={[]} />);

    await fireEvent.changeText(screen.getByLabelText("Search Tags"), "reading");

    expect(screen.getByLabelText("Create “reading”")).toBeEnabled();
    expect(screen.queryByText("Type a name to create one")).toBeNull();
  });
});

describe("006-FR-005 M-03 empty, filtered to nothing", () => {
  it("006-FR-005 drops every Tag row and offers a create carrying the typed name", async () => {
    await render(<TaskWithTagPicker />);

    await fireEvent.changeText(screen.getByLabelText("Search Tags"), "reading");

    expect(screen.queryByRole("checkbox")).toBeNull();
    expect(screen.getByLabelText("Create “reading”")).toBeEnabled();
  });
});

describe("006-FR-012 M-03 error: the failure is actionable and names itself", () => {
  it("006-FR-012 states the failure with its correlation id and a retry that reloads", async () => {
    await render(
      <TaskWithTagPicker
        tags={null}
        listPhase="failed"
        correlationId="corr-4d1e"
        recovered={TAGS}
      />,
    );

    expect(screen.getByText("We couldn't load your Tags.")).toBeOnTheScreen();
    expect(screen.getByText("ref: corr-4d1e")).toBeOnTheScreen();

    await fireEvent.press(screen.getByText("Retry"));

    expect(screen.getByLabelText("errand")).toBeOnTheScreen();
    expect(screen.queryByText("We couldn't load your Tags.")).toBeNull();
  });

  it("006-FR-002 006-FR-012 keeps the attached Tags shown, and still detachable", async () => {
    await render(
      <TaskWithTagPicker
        tags={null}
        listPhase="failed"
        attached={["tag_4"]}
        knownNames={TAGS}
      />,
    );

    expect(screen.getByLabelText("home")).toBeChecked();

    await fireEvent.press(screen.getByLabelText("home"));

    expect(screen.getByText("On the task: no Tags")).toBeOnTheScreen();
  });

  it("006-FR-005 offers no create row while the list is unreadable", async () => {
    await render(<TaskWithTagPicker tags={null} listPhase="failed" />);

    expect(screen.queryByText(/^Create /)).toBeNull();
  });
});

describe("006-FR-016 M-03 offline with a list the device already holds", () => {
  it("006-FR-016 says offline in words, and still lets an existing Tag be attached", async () => {
    await render(<TaskWithTagPicker online={false} />);

    expect(
      screen.getByText(
        "Offline. You can add Tags that already exist; creating a new one needs a connection.",
      ),
    ).toBeOnTheScreen();

    await fireEvent.press(screen.getByLabelText("errand"));

    expect(screen.getByText("On the task: errand")).toBeOnTheScreen();
    expect(screen.getByText("1 Tag selected")).toBeOnTheScreen();
  });

  it("006-FR-016 disables the create row with its reason in text, before it is tapped", async () => {
    await render(<TaskWithTagPicker online={false} />);

    await fireEvent.changeText(screen.getByLabelText("Search Tags"), "reading");

    const create = screen.getByLabelText(
      "Create “reading”. Needs a connection — new Tags are named by the server",
    );
    expect(create).toBeDisabled();
    // The reason is readable, not merely announced: state is never colour alone.
    expect(
      within(create).getByText("Needs a connection — new Tags are named by the server"),
    ).toBeOnTheScreen();
    expect(within(create).getByText("Create “reading”")).toBeOnTheScreen();
  });

  it("006-FR-016 keeps the blocked create row visible rather than hiding it", async () => {
    await render(<TaskWithTagPicker online={false} tags={[]} />);

    expect(screen.getByText("Create “…”")).toBeOnTheScreen();
    expect(
      screen.getByText("Needs a connection — new Tags are named by the server"),
    ).toBeOnTheScreen();
  });
});

describe("006-FR-002 006-FR-016 M-03 offline, never fetched", () => {
  const neverFetched = { tags: null, listPhase: "loading" as ListPhase, online: false };

  it("006-FR-016 says so plainly instead of claiming the person has no Tags", async () => {
    await render(<TaskWithTagPicker {...neverFetched} />);

    expect(screen.getByText("Can't load your Tags without a connection")).toBeOnTheScreen();
    expect(screen.queryByText("No Tags yet")).toBeNull();
    // Nothing to filter, so no search field is offered — design.md's focus note.
    expect(screen.queryByLabelText("Search Tags")).toBeNull();
    expect(screen.queryByText(/^Create /)).toBeNull();
  });

  it("006-FR-002 lists the task's own Tags, sourced from the task rather than the list", async () => {
    await render(
      <TaskWithTagPicker {...neverFetched} attached={["tag_4"]} knownNames={TAGS} />,
    );

    expect(tagNames()).toEqual(["home"]);
    expect(screen.getByLabelText("home")).toBeChecked();

    await fireEvent.press(screen.getByLabelText("home"));

    // FR-002's detach never needed the full list, so a first-ever visit that
    // happens to be offline can still make it.
    expect(screen.getByText("On the task: no Tags")).toBeOnTheScreen();
  });

  it("006-FR-002 says why an attached Tag's name is missing rather than showing a blank row", async () => {
    await render(<TaskWithTagPicker {...neverFetched} attached={["tag_9"]} />);

    expect(tagNames()).toEqual(["Tag — needs a connection to show its name"]);
    expect(screen.getByText("On the task: tag_9")).toBeOnTheScreen();
  });

  it("006-FR-002 lists nothing when the task carries no Tags, and does not pretend otherwise", async () => {
    await render(<TaskWithTagPicker {...neverFetched} />);

    expect(screen.queryByRole("checkbox")).toBeNull();
    expect(screen.getByText("No Tags selected")).toBeOnTheScreen();
  });
});

describe("006-FR-005 M-03 offers an existing Tag instead of a duplicate", () => {
  it("006-FR-005 offers the Tag that already carries the typed name, @ or not", async () => {
    await render(<TaskWithTagPicker />);

    await fireEvent.changeText(screen.getByLabelText("Search Tags"), "@home");

    // The row survives the @ as well: the server strips one, so both name the
    // same Tag.
    expect(tagNames()).toEqual(["home"]);
    expect(screen.queryByText(/^Create /)).toBeNull();

    await fireEvent.press(screen.getByLabelText("Use “home” — it already exists"));

    expect(screen.getByText("On the task: home")).toBeOnTheScreen();
  });

  it("006-FR-005 says the match is already attached rather than offering it again", async () => {
    await render(<TaskWithTagPicker attached={["tag_4"]} />);

    await fireEvent.changeText(screen.getByLabelText("Search Tags"), "HOME");

    expect(screen.getByText("“home” is already attached")).toBeOnTheScreen();
    expect(screen.queryByRole("button", { name: "“home” is already attached" })).toBeNull();
  });

  it("006-FR-005 still offers a create for a name that merely starts the same", async () => {
    await render(<TaskWithTagPicker />);

    await fireEvent.changeText(screen.getByLabelText("Search Tags"), "deep");

    expect(screen.getByLabelText("Create “deep”")).toBeEnabled();
  });
});

describe("006-FR-004 M-03 create and attach in one action", () => {
  it("006-FR-004 attaches the new Tag and clears the field, leaving the sheet open", async () => {
    await render(<TaskWithTagPicker attached={["tag_1"]} />);

    await fireEvent.changeText(screen.getByLabelText("Search Tags"), "reading");
    await fireEvent.press(screen.getByLabelText("Create “reading”"));

    expect(await screen.findByText("On the task: writing, reading")).toBeOnTheScreen();
    await waitFor(() =>
      expect(screen.getByLabelText("Search Tags").props.value).toBe(""),
    );
    expect(screen.getByLabelText("reading")).toBeChecked();
    expect(screen.getByText("2 Tags selected")).toBeOnTheScreen();
    expect(screen.getByText("Done")).toBeOnTheScreen();
  });

  it("006-FR-004 stops taking taps while the create is in flight", async () => {
    const pending = deferred<NamedEntity>();
    await render(<TaskWithTagPicker onCreate={() => pending.promise} />);

    // A query that still leaves a Tag row on screen, so the freeze can be seen
    // on the rows as well as on the create row.
    await fireEvent.changeText(screen.getByLabelText("Search Tags"), "deep");
    await fireEvent.press(screen.getByLabelText("Create “deep”"));

    // The server owns the new Tag's identity, so a tap landing between the
    // request and its answer must not be applied under it.
    expect(screen.getByLabelText("Create “deep”")).toBeDisabled();
    expect(screen.getByLabelText("deep-work")).toBeDisabled();
    expect(screen.getByText("Done")).toBeDisabled();

    await fireEvent.press(screen.getByLabelText("deep-work"));
    expect(screen.getByText("On the task: no Tags")).toBeOnTheScreen();

    await fireEvent.changeText(screen.getByLabelText("Search Tags"), "deeper");
    expect(screen.getByLabelText("Search Tags").props.value).toBe("deep");

    await act(async () => {
      pending.resolve({ id: "tag_5", name: "deep" });
    });
  });

  it("006-FR-004 leaves the typed name and the task's Tags untouched when the create fails", async () => {
    await render(
      <TaskWithTagPicker
        attached={["tag_1"]}
        onCreate={() =>
          Promise.reject(
            new ApiError("Request failed", 503, {
              message: "We couldn't reach the server.",
              reference_id: "corr-6c40",
            }),
          )
        }
      />,
    );

    await fireEvent.changeText(screen.getByLabelText("Search Tags"), "reading");
    await fireEvent.press(screen.getByLabelText("Create “reading”"));

    expect(await screen.findByText("We couldn't reach the server.")).toBeOnTheScreen();
    expect(screen.getByText("ref: corr-6c40")).toBeOnTheScreen();
    // T057 — a retry costs no retyping, and the Tags did not move.
    expect(screen.getByLabelText("Search Tags").props.value).toBe("reading");
    expect(screen.getByLabelText("Create “reading”")).toBeEnabled();
    expect(screen.getByText("On the task: writing")).toBeOnTheScreen();
    expect(screen.getByText("1 Tag selected")).toBeOnTheScreen();
  });

  it("006-FR-004 drops the failure once a different name is typed", async () => {
    await render(
      <TaskWithTagPicker onCreate={() => Promise.reject(new Error("Creating that failed."))} />,
    );

    await fireEvent.changeText(screen.getByLabelText("Search Tags"), "reading");
    await fireEvent.press(screen.getByLabelText("Create “reading”"));
    expect(await screen.findByText("Creating that failed.")).toBeOnTheScreen();

    await fireEvent.changeText(screen.getByLabelText("Search Tags"), "reading list");

    expect(screen.queryByText("Creating that failed.")).toBeNull();
  });
});

describe("006-FR-002 M-03 reopening and outside changes", () => {
  it("006-FR-002 forgets the last visit's search when reopened", async () => {
    await render(<TaskWithTagPicker />);

    await fireEvent.changeText(screen.getByLabelText("Search Tags"), "work");
    await fireEvent.press(screen.getByText("Done"));
    await fireEvent.press(screen.getByLabelText("Open the Tag picker"));

    expect(screen.getByLabelText("Search Tags").props.value).toBe("");
    expect(tagNames()).toHaveLength(4);
  });

  it("006-FR-002 moves the checks when the task changes underneath, keeping a half-typed name", async () => {
    await render(<TaskWithTagPicker />);

    await fireEvent.changeText(screen.getByLabelText("Search Tags"), "e");
    await fireEvent.press(screen.getByLabelText("Another device attaches errand"));

    expect(screen.getByLabelText("Search Tags").props.value).toBe("e");
    expect(screen.getByLabelText("errand")).toBeChecked();
    expect(screen.getByText("1 Tag selected")).toBeOnTheScreen();
  });
});
