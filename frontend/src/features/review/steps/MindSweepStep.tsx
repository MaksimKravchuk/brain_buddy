/** M-14 Mind sweep: capture anything on the mind into the Inbox, unsorted (FR-028, FR-052). */
import { useEffect, useState } from "react";
import type { FormEvent } from "react";

import { apiClient } from "../../../api/client";
import { newIdempotencyKey } from "../../../api/review";
import { useReviewDrafts } from "../useReviewDrafts";
import { fieldClass, FailureBanner, primaryButtonClass } from "./stepParts";
import { useReviewRun } from "./reviewRun";
import { useStepAction } from "./useStepAction";

/** The one line of this step: it is about no task, so it has one fixed item and field. */
const LINE = { item: "line", field: "title" } as const;

export function MindSweepStep(): React.JSX.Element {
  const run = useReviewRun();
  const action = useStepAction();
  const drafts = useReviewDrafts(run.session.id, "mind_sweep");
  // A line typed before a reload or a closed tab comes back (FR-052).
  const [text, setText] = useState(() => drafts.load(LINE.item, LINE.field) ?? "");
  const [added, setAdded] = useState<string[]>([]);

  useEffect(() => {
    if (text.trim() !== "") {
      run.setUnsaved(true);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- once per opened step: only a restored line is unsaved text before anything is typed.
  }, []);

  const submit = (event: FormEvent) => {
    // A disabled submit button blocks implicit submission, so a submit always carries a line.
    event.preventDefault();
    const title = text.trim();
    const key = newIdempotencyKey();
    void action.run("add", "Add to Inbox", async () => {
      const created = await apiClient.createTask({ title, state: "inbox" }, key);
      setAdded((current) => [...current, created.title]);
      setText("");
      drafts.clear(LINE.item, LINE.field);
      run.setUnsaved(false);
    });
  };

  return (
    <>
      <p className="m-0 text-sm text-slate-600">What&apos;s on your mind? Get it out of your head. Don&apos;t sort it yet.</p>
      {action.failure ? <FailureBanner failure={action.failure} online={action.online} /> : null}
      <form className="flex gap-2" onSubmit={submit}>
        <input
          aria-label="What's on your mind?"
          value={text}
          maxLength={500}
          readOnly={action.pending !== null}
          className={fieldClass}
          onChange={(event) => {
            setText(event.currentTarget.value);
            drafts.save(LINE.item, LINE.field, event.currentTarget.value);
            run.setUnsaved(event.currentTarget.value.trim() !== "");
          }}
        />
        <button type="submit" disabled={text.trim() === "" || action.disabled} className={primaryButtonClass}>
          {action.pending === "add" ? "Saving…" : "Add to Inbox"}
        </button>
      </form>
      {added.length > 0 ? (
        <ul className="m-0 flex list-none flex-col divide-y divide-slate-100 rounded-xl border border-slate-200 bg-white p-0 text-sm text-slate-800">
          {added.map((title, index) => (
            <li key={`${index}-${title}`} className="px-3 py-2.5">{title}</li>
          ))}
        </ul>
      ) : null}
    </>
  );
}
