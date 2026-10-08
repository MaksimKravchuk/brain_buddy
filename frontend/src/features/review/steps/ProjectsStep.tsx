/**
 * M-19 Projects without a next action (FR-028): each active project with
 * nothing to do next gets an "Add next action" field. The navigator part of
 * US3-8 is deferred, so there is no Suggest.
 */
import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";

import { apiClient } from "../../../api/client";
import { newIdempotencyKey } from "../../../api/review";
import type { ReviewQueue } from "../../../api/review";
import { useReviewQueue } from "../../../api/reviewHooks";
import { useProjects } from "../../../api/taskHooks";
import type { ProjectResponse } from "../../../api/taskTypes";
import { buttonClass, fieldClass, FailureBanner, primaryButtonClass, QueueGate } from "./stepParts";
import { useReviewRun } from "./reviewRun";
import { useStepAction } from "./useStepAction";

export function ProjectsStep(): React.JSX.Element {
  const run = useReviewRun();
  const queue = useReviewQueue("projects", run.session.id);
  const projects = useProjects();
  const action = useStepAction();
  const [open, setOpen] = useState<ProjectResponse | null>(null);
  const [text, setText] = useState("");
  const [added, setAdded] = useState<Array<{ id: string; note: string }>>([]);
  const fieldRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (open) {
      fieldRef.current?.focus();
    }
  }, [open]);

  const close = () => {
    setOpen(null);
    setText("");
    run.setUnsaved(false);
  };

  const submit = (event: FormEvent, project: ProjectResponse) => {
    // A disabled submit button blocks implicit submission, so a submit always carries a title.
    event.preventDefault();
    const title = text.trim();
    const key = newIdempotencyKey();
    void action.run("save", "Save next action", async () => {
      await apiClient.createTask({ title, state: "next", project_id: project.id }, key);
      setAdded((current) => [...current, { id: project.id, note: `Added to ${project.name}: ${title}` }]);
      close();
    });
  };

  return (
    <QueueGate queries={[queue, projects]}>
      {() => {
        const inQueue = new Set((queue.data as ReviewQueue).items.map((task) => task.project_id));
        // A project with no open task at all is stuck too; the queue holds only the open tasks of the others.
        const stuck = (projects.data as ProjectResponse[]).filter(
          (project) => project.state === "active" && !added.some((entry) => entry.id === project.id) && (inQueue.has(project.id) || project.open_task_count === 0)
        );
        return (
          <>
            <p className="m-0 text-sm text-slate-600">A project moves only when it has something you can do next.</p>
            {action.failure ? <FailureBanner failure={action.failure} online={action.online} /> : null}
            {added.map((entry) => (
              <p key={entry.id} role="status" className="m-0 text-sm text-slate-700">{entry.note}</p>
            ))}
            {stuck.length === 0 ? (
              <p className="m-0 text-sm text-slate-600">Every active project has a next action.</p>
            ) : (
              <ul aria-label="Projects without a next action" className="m-0 flex list-none flex-col divide-y divide-slate-100 rounded-xl border border-slate-200 bg-white p-0">
                {stuck.map((project) => (
                  <li key={project.id} className="flex flex-col gap-2 px-3 py-2.5">
                    <div className="flex items-center justify-between gap-3">
                      <p className="m-0 min-w-0 break-words text-sm font-medium text-slate-900">{project.name}</p>
                      {open?.id === project.id ? null : (
                        <button type="button" aria-label={`Add next action to ${project.name}`} disabled={action.disabled} className={buttonClass} onClick={() => { setOpen(project); setText(""); }}>
                          Add next action
                        </button>
                      )}
                    </div>
                    {open?.id === project.id ? (
                      <form className="flex flex-wrap gap-2" onSubmit={(event) => submit(event, project)}>
                        <input
                          ref={fieldRef}
                          aria-label={`Next action for ${project.name}`}
                          value={text}
                          maxLength={500}
                          readOnly={action.pending !== null}
                          className={`${fieldClass} flex-1`}
                          onChange={(event) => {
                            setText(event.currentTarget.value);
                            run.setUnsaved(event.currentTarget.value.trim() !== "");
                          }}
                        />
                        <button type="submit" disabled={text.trim() === "" || action.disabled} className={primaryButtonClass}>
                          {action.pending === "save" ? "Saving…" : "Save next action"}
                        </button>
                        <button type="button" disabled={action.pending !== null} className={buttonClass} onClick={close}>Cancel</button>
                      </form>
                    ) : null}
                  </li>
                ))}
              </ul>
            )}
          </>
        );
      }}
    </QueueGate>
  );
}
