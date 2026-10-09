/**
 * The project side of the Inbox step: the picker on the item card (attach it to
 * a project, or add one on the spot) and the "Make it a project" form.
 */
import type { FormEvent, RefObject } from "react";

import type { ProjectResponse } from "../../../api/taskTypes";
import { buttonClass, fieldClass, primaryButtonClass } from "./stepParts";

export const NEW_PROJECT = "__new__";

export interface ProjectPickerProps {
  projects: readonly ProjectResponse[];
  /** "" for no project, `NEW_PROJECT` while the name field is open, else a project id. */
  value: string;
  newName: string;
  busy: boolean;
  disabled: boolean;
  onSelect: (value: string) => void;
  onNewName: (name: string) => void;
  onAdd: (event: FormEvent) => void;
}

export function ProjectPicker({ projects, value, newName, busy, disabled, onSelect, onNewName, onAdd }: ProjectPickerProps): React.JSX.Element {
  return (
    <div className="flex flex-col gap-2">
      <label className="flex flex-col gap-1 text-sm font-medium text-slate-800">
        Project
        <select value={value} disabled={disabled} className={fieldClass} onChange={(event) => onSelect(event.currentTarget.value)}>
          <option value="">No project</option>
          {projects.map((project) => (
            <option key={project.id} value={project.id}>{project.name}</option>
          ))}
          <option value={NEW_PROJECT}>New project…</option>
        </select>
      </label>
      {value === NEW_PROJECT ? (
        <form className="flex flex-col gap-2 sm:flex-row sm:items-end" onSubmit={onAdd}>
          <label className="flex flex-1 flex-col gap-1 text-sm font-medium text-slate-800">
            New project name
            <input value={newName} maxLength={500} readOnly={busy} className={fieldClass} onChange={(event) => onNewName(event.currentTarget.value)} />
          </label>
          <button type="submit" disabled={newName.trim() === "" || disabled} className={buttonClass}>
            {busy ? "Adding…" : "Add project"}
          </button>
        </form>
      ) : null}
    </div>
  );
}

export interface ProjectDraft {
  name: string;
  outcome: string;
  action: string;
}

export interface MakeProjectFormProps {
  draft: ProjectDraft;
  /** Focused when the form opens: the first next action is what is still missing. */
  actionRef: RefObject<HTMLInputElement | null>;
  busy: boolean;
  disabled: boolean;
  onChange: (draft: ProjectDraft) => void;
  onBack: () => void;
  onSubmit: (event: FormEvent) => void;
}

export function MakeProjectForm({ draft, actionRef, busy, disabled, onChange, onBack, onSubmit }: MakeProjectFormProps): React.JSX.Element {
  return (
    <form className="flex flex-col gap-2" onSubmit={onSubmit}>
      <label className="flex flex-col gap-1 text-sm font-medium text-slate-800">
        Project name
        <input value={draft.name} maxLength={500} readOnly={busy} className={fieldClass} onChange={(event) => onChange({ ...draft, name: event.currentTarget.value })} />
      </label>
      <label className="flex flex-col gap-1 text-sm font-medium text-slate-800">
        Desired outcome (optional)
        <textarea value={draft.outcome} maxLength={1000} rows={2} readOnly={busy} className={fieldClass} onChange={(event) => onChange({ ...draft, outcome: event.currentTarget.value })} />
      </label>
      <label className="flex flex-col gap-1 text-sm font-medium text-slate-800">
        First next action
        <input ref={actionRef} value={draft.action} maxLength={500} readOnly={busy} className={fieldClass} onChange={(event) => onChange({ ...draft, action: event.currentTarget.value })} />
      </label>
      <div className="flex flex-wrap gap-2">
        <button type="button" disabled={busy} className={buttonClass} onClick={onBack}>Back</button>
        <button type="submit" disabled={draft.name.trim() === "" || draft.action.trim() === "" || disabled} className={`${primaryButtonClass} ml-auto`}>
          {busy ? "Saving…" : "Make it a project"}
        </button>
      </div>
    </form>
  );
}
