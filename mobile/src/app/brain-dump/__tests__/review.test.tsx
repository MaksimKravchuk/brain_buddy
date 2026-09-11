import { act, fireEvent, screen, waitFor } from "@testing-library/react-native";
import { Alert, AppState, type AlertButton } from "react-native";

import { ToastHost } from "@/components/ToastHost";
import { makeOperation, makeProposal } from "@/test/brainDump";
import { uuidNumber } from "@/test/expoCryptoMock";
import { routerSpy, setSearchParams } from "@/test/expoRouterMock";
import {
  FakeHttpError,
  installFakeBackend,
  makeMe,
  type FakeBackend,
  type RouteHandler,
} from "@/test/fakeBackend";
import { renderWithSession } from "@/test/harness";

import BrainDumpOperationScreen from "../[operationId]";

let backend: FakeBackend;
let alertSpy: jest.SpyInstance<void, Parameters<typeof Alert.alert>>;

beforeEach(() => {
  jest.useFakeTimers({ doNotFake: ["nextTick"] });
  // The platform dialog is a device boundary: record what the screen asked it
  // to show, and let each test answer it by hand.
  alertSpy = jest.spyOn(Alert, "alert").mockImplementation(() => undefined);
});

afterEach(() => {
  jest.useRealTimers();
  alertSpy.mockRestore();
  backend?.restore();
});

function review(routes: Record<string, RouteHandler>) {
  backend = installFakeBackend({ "GET /auth/me": () => makeMe(), ...routes });
  setSearchParams({ operationId: "op-1" });
  return renderWithSession(
    <ToastHost>
      <BrainDumpOperationScreen />
    </ToastHost>,
  );
}

/** Let the poll timer fire and its fetch settle. */
async function advancePoll(ms = 10_000) {
  // The async variant yields between timers, so the fetch a timer starts is
  // awaited before the next one is considered.
  await act(async () => {
    await jest.advanceTimersByTimeAsync(ms);
  });
}

/** The answers of the latest confirmation the screen raised, safe answer first. */
function latestConfirmation(): { keep: AlertButton; discard: AlertButton } {
  const buttons = alertSpy.mock.lastCall?.[2] ?? [];
  expect(buttons).toHaveLength(2);
  const [keep, discard] = buttons;
  return { keep, discard };
}

/** Choose one answer of the confirmation, as the platform would on a tap. */
async function answer(button: AlertButton) {
  await act(async () => {
    button.onPress?.();
  });
}

const DISCARD_REVIEW_DIALOG = [
  "Discard all tasks?",
  "Nothing is saved to Inbox and the recording is deleted.",
  [
    { text: "Keep reviewing", style: "cancel" },
    { text: "Discard all tasks", style: "destructive", onPress: expect.any(Function) },
  ],
  { cancelable: true },
] as const;

const DISCARD_RECORDING_DIALOG = [
  "Discard this recording?",
  "The audio and transcript are deleted and nothing is saved.",
  [
    { text: "Keep", style: "cancel" },
    { text: "Discard recording", style: "destructive", onPress: expect.any(Function) },
  ],
  { cancelable: true },
] as const;

function cancelCalls() {
  return backend.callsTo("POST", "/brain-dump-operations/op-1/cancel");
}

const AWAITING = makeOperation({
  status: "awaiting_confirmation",
  committable: true,
  proposals: [
    makeProposal({ id: "p1", ordinal: 1, title: "Call the notary" }),
    makeProposal({ id: "p2", ordinal: 2, title: "Book the venue" }),
  ],
});

describe("brain dump review — loading", () => {
  it("shows a load failure with a retry that refetches", async () => {
    let attempts = 0;
    await review({
      "GET /brain-dump-operations/op-1": () => {
        attempts += 1;
        if (attempts === 1) {
          return new FakeHttpError(503, { message: "Temporarily unavailable" });
        }
        return AWAITING;
      },
    });

    expect(await screen.findByText("Temporarily unavailable")).toBeOnTheScreen();

    await fireEvent.press(screen.getByText("Retry"));

    expect(await screen.findByText("Review 2 tasks")).toBeOnTheScreen();
  });

  it("names the processing stage while the server works, then shows the review", async () => {
    let calls = 0;
    await review({
      "GET /brain-dump-operations/op-1": () => {
        calls += 1;
        return calls === 1
          ? makeOperation({ status: "accurate_transcribing" })
          : AWAITING;
      },
    });

    expect(await screen.findByText("Improving transcript…")).toBeOnTheScreen();

    await advancePoll(2000);

    expect(await screen.findByText("Review 2 tasks")).toBeOnTheScreen();
  });

  it("keeps polling through a transient fetch failure", async () => {
    let calls = 0;
    await review({
      "GET /brain-dump-operations/op-1": () => {
        calls += 1;
        if (calls === 1) {
          return makeOperation({ status: "reconciling" });
        }
        if (calls === 2) {
          throw new TypeError("Network request failed");
        }
        return AWAITING;
      },
    });

    await screen.findByText("Reconciling tasks…");
    await advancePoll(2000);
    await advancePoll(4000);

    expect(await screen.findByText("Review 2 tasks")).toBeOnTheScreen();
  });

  it("refetches when the app comes back to the foreground", async () => {
    // Swapped by hand rather than with jest.spyOn: the swap has to be undone
    // for the rest of the file, and the surrounding `clearMocks` lifecycle
    // makes a spy's restoration harder to reason about than an assignment.
    const listeners: ((state: string) => void)[] = [];
    const original = AppState.addEventListener;
    (AppState as { addEventListener: unknown }).addEventListener = (
      _type: string,
      handler: (state: string) => void,
    ) => {
      listeners.push(handler);
      return { remove: () => {} };
    };

    try {
      let calls = 0;
      await review({
        "GET /brain-dump-operations/op-1": () => {
          calls += 1;
          return calls === 1 ? makeOperation({ status: "sealing" }) : AWAITING;
        },
      });
      await screen.findByText("Finishing upload…");

      // Backgrounding stops the poll; returning refetches at once rather than
      // waiting out the backoff.
      await act(async () => {
        listeners.forEach((handler) => handler("background"));
      });
      await act(async () => {
        listeners.forEach((handler) => handler("active"));
      });

      expect(await screen.findByText("Review 2 tasks")).toBeOnTheScreen();
    } finally {
      (AppState as { addEventListener: unknown }).addEventListener = original;
    }
  });
});

describe("brain dump review — proposals", () => {
  it("lists the undeleted proposals in ordinal order", async () => {
    await review({
      "GET /brain-dump-operations/op-1": () =>
        makeOperation({
          status: "awaiting_confirmation",
          committable: true,
          proposals: [
            makeProposal({ id: "p2", ordinal: 2, title: "Second" }),
            makeProposal({ id: "p1", ordinal: 1, title: "First" }),
            makeProposal({ id: "p3", ordinal: 3, title: "Gone", deleted: true }),
          ],
        }),
    });

    expect(await screen.findByText("Review 2 tasks")).toBeOnTheScreen();
    expect(screen.queryByDisplayValue("Gone")).toBeNull();
    expect(screen.getByDisplayValue("First")).toBeOnTheScreen();
  });

  it("015-FR-005 says nothing was proposed, shows what was heard, and offers no confirm on an empty review", async () => {
    const at = "2026-01-01T00:00:00Z";
    await review({
      "GET /brain-dump-operations/op-1": () =>
        makeOperation({
          status: "awaiting_confirmation",
          committable: true,
          proposals: [],
          segments: [
            // Out of spoken order on purpose; the preview hypothesis s1 is
            // superseded by the accurate s4, and the interim s3 was never the record.
            { id: "s2", sequence: 2, text: "Ну…", stability: "stable", created_at: at },
            {
              id: "s1",
              sequence: 1,
              text: "Tak",
              stability: "stable",
              provider_role: "browser_preview",
              created_at: at,
            },
            { id: "s3", sequence: 3, text: "надо", stability: "interim", created_at: at },
            {
              id: "s4",
              sequence: 4,
              text: "Так, надо…",
              stability: "stable",
              provider_role: "accurate",
              supersedes_segment_ids: ["s1"],
              created_at: at,
            },
          ],
        }),
    });

    expect(await screen.findByText("No tasks to review")).toBeOnTheScreen();
    expect(
      screen.getByText("No tasks were proposed from this dump. Discard it to record again."),
    ).toBeOnTheScreen();
    expect(screen.queryByText(/^Review \d/)).toBeNull();
    // Absent, not disabled: there is nothing to save.
    expect(screen.queryByText(/^Confirm /)).toBeNull();

    expect(screen.getByText("What was heard")).toBeOnTheScreen();
    expect(screen.getByText("Ну…")).toBeOnTheScreen();
    expect(screen.getByText("Так, надо…")).toBeOnTheScreen();
    expect(screen.queryByText("Tak")).toBeNull();
    expect(screen.queryByText("надо")).toBeNull();

    // The one exit left still asks first.
    await fireEvent.press(screen.getByText("Discard all"));
    expect(alertSpy).toHaveBeenCalledWith(...DISCARD_REVIEW_DIALOG);
    expect(cancelCalls()).toHaveLength(0);
  });

  it("015-FR-005 says when no transcript was captured for an empty review", async () => {
    await review({
      "GET /brain-dump-operations/op-1": () =>
        makeOperation({ status: "awaiting_confirmation", proposals: [] }),
    });

    expect(await screen.findByText("No tasks to review")).toBeOnTheScreen();
    expect(screen.getByText("What was heard")).toBeOnTheScreen();
    expect(screen.getByText("No transcript was captured for this recording.")).toBeOnTheScreen();
    expect(screen.queryByText(/^Confirm /)).toBeNull();
  });

  it("patches an edited title with the operation revision", async () => {
    await review({
      "GET /brain-dump-operations/op-1": () => ({ ...AWAITING, revision: 6 }),
      "PATCH /brain-dump-operations/op-1/proposals/p1": () => ({ ...AWAITING, revision: 7 }),
    });
    const input = await screen.findByDisplayValue("Call the notary");

    await fireEvent.changeText(input, "  Call the registrar  ");
    await fireEvent(input, "endEditing");

    await waitFor(() =>
      expect(backend.callsTo("PATCH", "/brain-dump-operations/op-1/proposals/p1")).toHaveLength(1),
    );
    expect(backend.callsTo("PATCH", "/brain-dump-operations/op-1/proposals/p1")[0].body).toEqual({
      title: "Call the registrar",
      expected_revision: 6,
    });
  });

  it("does not patch a title that did not change", async () => {
    await review({ "GET /brain-dump-operations/op-1": () => AWAITING });
    const input = await screen.findByDisplayValue("Call the notary");

    await fireEvent(input, "endEditing");

    expect(backend.callsTo("PATCH", "/brain-dump-operations/op-1/proposals/p1")).toHaveLength(0);
  });

  it("serializes concurrent proposal edits so each carries the previous revision", async () => {
    let revision = 6;
    await review({
      "GET /brain-dump-operations/op-1": () => ({ ...AWAITING, revision }),
      "PATCH /brain-dump-operations/op-1/proposals/p1": () => {
        revision += 1;
        return { ...AWAITING, revision };
      },
      "PATCH /brain-dump-operations/op-1/proposals/p2": () => {
        revision += 1;
        return { ...AWAITING, revision };
      },
    });
    await screen.findByDisplayValue("Call the notary");

    await fireEvent.press(screen.getAllByLabelText("Remove proposal")[0]);
    await fireEvent.press(screen.getAllByLabelText("Remove proposal")[1]);

    await waitFor(() =>
      expect(backend.callsTo("PATCH", "/brain-dump-operations/op-1/proposals/p2")).toHaveLength(1),
    );
    expect(backend.callsTo("PATCH", "/brain-dump-operations/op-1/proposals/p1")[0].body).toEqual({
      deleted: true,
      expected_revision: 6,
    });
    expect(backend.callsTo("PATCH", "/brain-dump-operations/op-1/proposals/p2")[0].body).toEqual({
      deleted: true,
      expected_revision: 7,
    });
  });

  it("shows a failed edit and re-reads the server copy", async () => {
    await review({
      "GET /brain-dump-operations/op-1": () => AWAITING,
      "PATCH /brain-dump-operations/op-1/proposals/p1": () =>
        new FakeHttpError(409, { message: "Someone else edited this dump" }),
    });
    await screen.findByDisplayValue("Call the notary");

    await fireEvent.press(screen.getAllByLabelText("Remove proposal")[0]);

    expect(await screen.findByText("Someone else edited this dump")).toBeOnTheScreen();
    await waitFor(() =>
      expect(backend.callsTo("GET", "/brain-dump-operations/op-1").length).toBeGreaterThan(1),
    );
  });

  it("resolves a conflict either way and blocks confirm until it is gone", async () => {
    const conflicted = makeOperation({
      status: "awaiting_confirmation",
      committable: true,
      revision: 2,
      proposals: [
        makeProposal({
          id: "p1",
          title: "Call the notary",
          status: "conflicted",
          conflicts: [
            {
              field: "title",
              current_value: "Call the notary",
              suggested_value: "Call the registrar",
              producer: "reconciler",
              source_segment_ids: [],
            },
          ],
        }),
      ],
    });
    await review({
      "GET /brain-dump-operations/op-1": () => conflicted,
      "PATCH /brain-dump-operations/op-1/proposals/p1": () => conflicted,
    });

    expect(await screen.findByText("Resolve 1 conflict before confirming.")).toBeOnTheScreen();
    expect(screen.getByText("Suggested title: Call the registrar")).toBeOnTheScreen();
    expect(screen.getByText("Needs a decision")).toBeOnTheScreen();

    await fireEvent.press(screen.getByText("Confirm 1 addition"));
    expect(backend.callsTo("POST", "/brain-dump-operations/op-1/commit")).toHaveLength(0);

    await fireEvent.press(screen.getByText("Use suggestion"));
    await waitFor(() =>
      expect(backend.callsTo("PATCH", "/brain-dump-operations/op-1/proposals/p1")).toHaveLength(1),
    );
    expect(backend.callsTo("PATCH", "/brain-dump-operations/op-1/proposals/p1")[0].body).toEqual({
      conflict_resolution: "accept",
      expected_revision: 2,
    });

    await fireEvent.press(screen.getByText("Keep mine"));
    await waitFor(() =>
      expect(backend.callsTo("PATCH", "/brain-dump-operations/op-1/proposals/p1")).toHaveLength(2),
    );
    expect(backend.callsTo("PATCH", "/brain-dump-operations/op-1/proposals/p1")[1].body).toEqual({
      conflict_resolution: "keep",
      expected_revision: 2,
    });
  });

  it("marks a proposal the user has already edited", async () => {
    await review({
      "GET /brain-dump-operations/op-1": () =>
        makeOperation({
          status: "awaiting_confirmation",
          proposals: [makeProposal({ id: "p1", user_edited: true })],
        }),
    });

    expect(await screen.findByText("Edited by you")).toBeOnTheScreen();
  });

  it("015-FR-010 015-SC-007 warns when only provisional wording was available", async () => {
    await review({
      "GET /brain-dump-operations/op-1": () => ({
        ...AWAITING,
        reconciliation_quality: "provisional_only" as const,
      }),
    });

    expect(await screen.findByText(/Provisional only/)).toBeOnTheScreen();
  });

  it("015-FR-010 015-SC-007 keeps the provisional warning up while the dump is not yet committable", async () => {
    await review({
      "GET /brain-dump-operations/op-1": () => ({
        ...AWAITING,
        committable: false,
        reconciliation_quality: "provisional_only" as const,
      }),
    });

    expect(await screen.findByText(/Provisional only/)).toBeOnTheScreen();

    // The warning is about wording quality, not commit readiness: confirm
    // stays blocked until the server says otherwise.
    await fireEvent.press(screen.getByText("Confirm 2 additions"));
    expect(backend.callsTo("POST", "/brain-dump-operations/op-1/commit")).toHaveLength(0);
  });

  it("offers to delete the retained audio under that name, saying when it expires", async () => {
    await review({
      "GET /brain-dump-operations/op-1": () => ({
        ...AWAITING,
        revision: 4,
        raw_audio_present: true,
        raw_audio_expires_at: "2026-03-01T12:00:00Z",
      }),
      "POST /brain-dump-operations/op-1/delete_raw_audio": () => ({
        ...AWAITING,
        raw_audio_present: false,
      }),
    });

    expect(await screen.findByText(/^Recording kept until /)).toBeOnTheScreen();
    // It removes the retained audio only, so it is not named like a discard.
    expect(screen.queryByLabelText("Delete recording")).toBeNull();
    await fireEvent.press(screen.getByLabelText("Delete retained audio"));

    await waitFor(() =>
      expect(backend.callsTo("POST", "/brain-dump-operations/op-1/delete_raw_audio")).toHaveLength(1),
    );
    expect(
      backend.callsTo("POST", "/brain-dump-operations/op-1/delete_raw_audio")[0].body,
    ).toEqual({ expected_revision: 4 });
  });

  it("says the recording is kept temporarily when no expiry is given", async () => {
    await review({
      "GET /brain-dump-operations/op-1": () => ({ ...AWAITING, raw_audio_present: true }),
    });

    expect(await screen.findByText("Recording kept temporarily")).toBeOnTheScreen();
  });
});

describe("brain dump review — commit and discard", () => {
  it("commits, waits out the committing status, and leaves with a count", async () => {
    let calls = 0;
    await review({
      "GET /brain-dump-operations/op-1": () => {
        calls += 1;
        return calls <= 1
          ? { ...AWAITING, revision: 5 }
          : // Higher revision than the commit response: a poll result that did
            // not advance the revision is discarded as out-of-order.
            makeOperation({
              status: "completed",
              revision: 7,
              committed_task_ids: ["t1", "t2"],
            });
      },
      "POST /brain-dump-operations/op-1/commit": () =>
        makeOperation({ status: "committing", revision: 6 }),
    });
    await screen.findByText("Review 2 tasks");

    await fireEvent.press(screen.getByText("Confirm 2 additions"));

    // The commit left the operation in "committing"; the screen shows that
    // stage and polls it out.
    expect(await screen.findByText("Saving to inbox…")).toBeOnTheScreen();
    expect(backend.callsTo("POST", "/brain-dump-operations/op-1/commit")[0].body).toEqual({
      expected_revision: 5,
    });

    await advancePoll(2000);

    expect(routerSpy().dismissAll).toHaveBeenCalled();
    // Once on the completed screen and once in the toast.
    expect(await screen.findAllByText("Saved 2 to inbox")).toHaveLength(2);
  });

  it("leaves immediately when the commit response is already completed", async () => {
    await review({
      "GET /brain-dump-operations/op-1": () => AWAITING,
      "POST /brain-dump-operations/op-1/commit": () =>
        makeOperation({ status: "completed", committed_task_ids: ["t1"], revision: 9 }),
    });
    await screen.findByText("Review 2 tasks");

    await fireEvent.press(screen.getByText("Confirm 2 additions"));

    await waitFor(() => expect(routerSpy().dismissAll).toHaveBeenCalled());
    expect(await screen.findAllByText("Saved 1 to inbox")).toHaveLength(2);
  });

  it("reports a failed commit and stays on the review", async () => {
    await review({
      "GET /brain-dump-operations/op-1": () => AWAITING,
      "POST /brain-dump-operations/op-1/commit": () =>
        new FakeHttpError(500, { message: "Could not save these" }),
    });
    await screen.findByText("Review 2 tasks");

    await fireEvent.press(screen.getByText("Confirm 2 additions"));

    expect(await screen.findByText("Could not save these")).toBeOnTheScreen();
    expect(routerSpy().dismissAll).not.toHaveBeenCalled();
  });

  it("015-FR-007 015-SC-004 asks before discarding all from the review sheet and cancels only once confirmed", async () => {
    await review({
      "GET /brain-dump-operations/op-1": () => ({ ...AWAITING, revision: 4 }),
      "POST /brain-dump-operations/op-1/cancel": () => makeOperation({ status: "cancelled" }),
    });
    await screen.findByText("Review 2 tasks");

    await fireEvent.press(screen.getByText("Discard all"));

    expect(alertSpy).toHaveBeenCalledWith(...DISCARD_REVIEW_DIALOG);
    expect(cancelCalls()).toHaveLength(0);

    await answer(latestConfirmation().discard);

    await waitFor(() => expect(cancelCalls()).toHaveLength(1));
    expect(cancelCalls()[0].body).toEqual({ expected_revision: 4 });
    expect(routerSpy().dismissAll).toHaveBeenCalled();
    expect(await screen.findByText("Dump discarded — nothing was saved")).toBeOnTheScreen();
  });

  it("015-FR-007 keeps reviewing, with nothing posted, when the safe answer is chosen", async () => {
    await review({ "GET /brain-dump-operations/op-1": () => AWAITING });
    await screen.findByText("Review 2 tasks");

    await fireEvent.press(screen.getByText("Discard all"));
    await answer(latestConfirmation().keep);

    expect(cancelCalls()).toHaveLength(0);
    expect(routerSpy().dismissAll).not.toHaveBeenCalled();
    expect(screen.getByText("Review 2 tasks")).toBeOnTheScreen();
    expect(screen.getByDisplayValue("Call the notary")).toBeOnTheScreen();
  });

  it("015-FR-007 015-SC-004 names the header control as a discard and asks before cancelling from it", async () => {
    await review({
      "GET /brain-dump-operations/op-1": () => ({ ...AWAITING, revision: 3 }),
      "POST /brain-dump-operations/op-1/cancel": () => makeOperation({ status: "cancelled" }),
    });
    await screen.findByText("Review 2 tasks");

    // A control named Close must not delete a recording.
    expect(screen.queryByLabelText("Close")).toBeNull();
    await fireEvent.press(screen.getByLabelText("Discard recording"));

    expect(alertSpy).toHaveBeenCalledWith(...DISCARD_REVIEW_DIALOG);
    expect(cancelCalls()).toHaveLength(0);

    await answer(latestConfirmation().keep);
    expect(cancelCalls()).toHaveLength(0);
    expect(screen.getByText("Review 2 tasks")).toBeOnTheScreen();

    await fireEvent.press(screen.getByLabelText("Discard recording"));
    expect(alertSpy).toHaveBeenCalledTimes(2);
    await answer(latestConfirmation().discard);

    await waitFor(() => expect(cancelCalls()).toHaveLength(1));
    expect(cancelCalls()[0].body).toEqual({ expected_revision: 3 });
    expect(cancelCalls()[0].headers["Idempotency-Key"]).toBe(uuidNumber(1));
    expect(routerSpy().dismissAll).toHaveBeenCalled();
  });
});

describe("brain dump review — terminal states", () => {
  it("shows the saved count for an already completed dump", async () => {
    await review({
      "GET /brain-dump-operations/op-1": () =>
        makeOperation({ status: "completed", committed_task_ids: ["a", "b", "c"] }),
    });

    expect(await screen.findByText("Saved 3 to inbox")).toBeOnTheScreen();

    await fireEvent.press(screen.getByText("Done"));
    expect(routerSpy().dismissAll).toHaveBeenCalled();
  });

  it("shows a cancelled dump as discarded", async () => {
    await review({
      "GET /brain-dump-operations/op-1": () => makeOperation({ status: "cancelled" }),
    });

    expect(await screen.findByText("Dump discarded")).toBeOnTheScreen();
    await fireEvent.press(screen.getByText("Done"));
    expect(routerSpy().dismissAll).toHaveBeenCalled();
  });

  it("offers the server's recovery actions on a retryable failure", async () => {
    await review({
      "GET /brain-dump-operations/op-1": () =>
        makeOperation({
          status: "retryable_error",
          revision: 3,
          available_recovery_actions: ["retry", "review_provisional", "cancel"],
          provider_runs: [
            {
              id: "r1",
              role: "accurate_stt",
              status: "retryable_error",
              checkpoint: "sealed",
              attempt: 1,
              recovery_count: 0,
              error: "The transcription provider timed out.",
            },
          ],
        } as never),
      "POST /brain-dump-operations/op-1/retry": () => makeOperation({ status: "sealing" }),
    });

    expect(await screen.findByText("Processing hit a snag")).toBeOnTheScreen();
    expect(screen.getByText("The transcription provider timed out.")).toBeOnTheScreen();
    // Gated on the server naming it, not on any recovery being offered.
    expect(screen.queryByText("Extract tasks from the browser transcript")).toBeNull();

    await fireEvent.press(screen.getByText("Try again"));
    await waitFor(() =>
      expect(backend.callsTo("POST", "/brain-dump-operations/op-1/retry")).toHaveLength(1),
    );
  });

  it("hides recovery actions the server did not offer", async () => {
    await review({
      "GET /brain-dump-operations/op-1": () =>
        makeOperation({ status: "failed", available_recovery_actions: [] } as never),
    });

    expect(await screen.findByText("Couldn't finish")).toBeOnTheScreen();
    expect(screen.queryByText("Try again")).toBeNull();
    expect(screen.queryByText("Review provisional tasks")).toBeNull();
    expect(screen.queryByText("Extract tasks from the browser transcript")).toBeNull();
    // Discarding is always available.
    expect(screen.getByText("Discard everything")).toBeOnTheScreen();
  });

  it("015-FR-007 015-SC-004 asks before discarding a failed recording and cancels only once confirmed", async () => {
    await review({
      "GET /brain-dump-operations/op-1": () =>
        makeOperation({
          status: "failed",
          revision: 5,
          available_recovery_actions: ["cancel"],
        } as never),
      "POST /brain-dump-operations/op-1/cancel": () => makeOperation({ status: "cancelled" }),
    });
    await screen.findByText("Couldn't finish");

    await fireEvent.press(screen.getByText("Discard everything"));

    expect(alertSpy).toHaveBeenCalledWith(...DISCARD_RECORDING_DIALOG);
    expect(cancelCalls()).toHaveLength(0);

    // The safe answer leaves the failed recording, and its audio, where it was.
    await answer(latestConfirmation().keep);
    expect(cancelCalls()).toHaveLength(0);
    expect(routerSpy().dismissAll).not.toHaveBeenCalled();
    expect(screen.getByText("Couldn't finish")).toBeOnTheScreen();

    await fireEvent.press(screen.getByText("Discard everything"));
    expect(alertSpy).toHaveBeenCalledTimes(2);
    await answer(latestConfirmation().discard);

    await waitFor(() => expect(cancelCalls()).toHaveLength(1));
    expect(cancelCalls()[0].body).toEqual({ expected_revision: 5 });
    expect(routerSpy().dismissAll).toHaveBeenCalled();
    expect(await screen.findByText("Dump discarded — nothing was saved")).toBeOnTheScreen();
  });

  it("falls back to the error code, then to generic guidance", async () => {
    const withCode = makeOperation({
      status: "failed",
      provider_runs: [
        {
          id: "r1",
          role: "reconciler",
          status: "terminal_error",
          checkpoint: "accurate_transcribed",
          attempt: 2,
          recovery_count: 1,
          error_code: "provider_quota_exhausted",
        },
      ],
    } as never);
    const first = await review({ "GET /brain-dump-operations/op-1": () => withCode });
    expect(await screen.findByText("provider_quota_exhausted")).toBeOnTheScreen();
    await first.unmount();

    backend.route("GET /brain-dump-operations/op-1", () =>
      makeOperation({ status: "failed" } as never),
    );
    await review({
      "GET /brain-dump-operations/op-1": () => makeOperation({ status: "failed" } as never),
    });
    expect(
      await screen.findByText(
        "The audio was kept — choose one of the options below, or discard everything.",
      ),
    ).toBeOnTheScreen();
  });

  it("can hand a failed dump to provisional review", async () => {
    await review({
      "GET /brain-dump-operations/op-1": () =>
        makeOperation({
          status: "failed",
          available_recovery_actions: ["review_provisional", "cancel"],
        } as never),
      "POST /brain-dump-operations/op-1/review_provisional": () => AWAITING,
    });
    await screen.findByText("Couldn't finish");

    await fireEvent.press(screen.getByText("Review provisional tasks"));

    await waitFor(() =>
      expect(
        backend.callsTo("POST", "/brain-dump-operations/op-1/review_provisional"),
      ).toHaveLength(1),
    );
  });

  it("015-FR-009 offers to extract tasks from the browser transcript when the server advertises it", async () => {
    await review({
      "GET /brain-dump-operations/op-1": () =>
        makeOperation({
          status: "terminal_error",
          available_recovery_actions: ["reconcile_preview", "cancel"],
        }),
    });
    await screen.findByText("Couldn't finish");

    expect(screen.getByText("Extract tasks from the browser transcript")).toBeOnTheScreen();
    expect(
      screen.getByText(
        "Sends the browser transcript to the consented task-extraction provider. The result is provisional and is reviewed before anything is saved.",
      ),
    ).toBeOnTheScreen();
    // Only the advertised recoveries show; discarding always does.
    expect(screen.queryByText("Try again")).toBeNull();
    expect(screen.queryByText("Review provisional tasks")).toBeNull();
    expect(screen.getByText("Discard everything")).toBeOnTheScreen();
  });

  it("015-FR-009 015-FR-010 015-SC-006 015-SC-007 posts reconcile_preview with the current revision, waits out reconciling, and reviews the provisional tasks", async () => {
    let calls = 0;
    await review({
      "GET /brain-dump-operations/op-1": () => {
        calls += 1;
        return calls <= 1
          ? makeOperation({
              status: "terminal_error",
              revision: 3,
              available_recovery_actions: ["reconcile_preview", "cancel"],
            })
          : {
              ...AWAITING,
              revision: 5,
              committable: false,
              reconciliation_quality: "provisional_only" as const,
            };
      },
      "POST /brain-dump-operations/op-1/reconcile_preview": () =>
        makeOperation({ status: "reconciling", revision: 4 }),
    });
    await screen.findByText("Couldn't finish");

    await fireEvent.press(screen.getByText("Extract tasks from the browser transcript"));

    // The command left the operation reconciling; the screen shows that stage
    // and polls it out, exactly as it does after retry or commit.
    expect(await screen.findByText("Reconciling tasks…")).toBeOnTheScreen();
    const posted = backend.callsTo("POST", "/brain-dump-operations/op-1/reconcile_preview");
    expect(posted).toHaveLength(1);
    expect(posted[0].body).toEqual({ expected_revision: 3 });
    expect(posted[0].headers["Idempotency-Key"]).toBe(uuidNumber(1));

    await advancePoll(2000);

    expect(await screen.findByText("Review 2 tasks")).toBeOnTheScreen();
    expect(screen.getByText(/Provisional only/)).toBeOnTheScreen();
  });
});
