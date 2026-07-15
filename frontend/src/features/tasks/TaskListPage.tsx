import { AlertTriangle, Plus, RotateCcw, SlidersHorizontal } from "lucide-react";
import { useMemo } from "react";
import { useParams } from "react-router-dom";

import { parseOpenTaskState, useProjects, useTags, useTaskList } from "../../api/taskHooks";
import type { OpenTaskState, ProjectResponse, TagResponse, TaskCounts, TaskResponse } from "../../api/taskTypes";
import { AppShell } from "../../components/shell/AppShell";
import { getErrorMessage } from "../../utils/error";

const stateLabels: Record<OpenTaskState, string> = {
  inbox: "Inbox",
  next: "Next actions",
  waiting: "Waiting for",
  someday: "Someday / maybe"
};

const emptyCounts: TaskCounts = { inbox: 0, next: 0, waiting: 0, someday: 0 };

export function TaskListPage({ mode }: { mode?: "state" | "project" | "tag" }): JSX.Element {
  const params = useParams();
  const state = mode === "state" || !mode ? parseOpenTaskState(params.state) : undefined;
  const projectId = mode === "project" ? params.projectId : undefined;
  const tagId = mode === "tag" ? params.tagId : undefined;

  const taskQuery = useTaskList({ state, projectId, tagId });
  const projectsQuery = useProjects();
  const tagsQuery = useTags();

  const projects = projectsQuery.data ?? [];
  const tags = tagsQuery.data ?? [];
  const tasks = taskQuery.data?.items ?? [];
  const counts = taskQuery.data?.counts_by_state ?? emptyCounts;

  const title = useMemo(() => {
    if (projectId) {
      return projects.find((project) => project.id === projectId)?.name ?? "Project";
    }
    if (tagId) {
      const tag = tags.find((item) => item.id === tagId)?.name ?? "tag";
      return `@${tag.replace(/^@/, "")}`;
    }
    return stateLabels[state ?? "next"];
  }, [projectId, projects, state, tagId, tags]);

  const taskNoun = counts[state ?? "next"] === 1 ? "task" : "tasks";
  const subtitle = state ? `${counts[state]} ${taskNoun}` : `${tasks.length} ${tasks.length === 1 ? "task" : "tasks"}`;

  const hasFrameError = taskQuery.isError || projectsQuery.isError || tagsQuery.isError;

  return (
    <AppShell
      counts={counts}
      projects={projects}
      tags={tags}
      activeState={state}
      activeProjectId={projectId}
      activeTagId={tagId}
    >
      <section aria-labelledby="task-list-title" className="mx-auto max-w-5xl">
        <div className="mb-4 flex flex-wrap items-baseline gap-3">
          <h1 id="task-list-title" className="m-0 text-title font-semibold text-slate-900">
            {title}
          </h1>
          <span className="text-xs text-slate-600">{subtitle}</span>
          <button
            type="button"
            className="ml-auto inline-flex h-8 items-center gap-1.5 rounded-lg px-3 text-xs text-slate-600 hover:bg-slate-100"
            disabled
          >
            <SlidersHorizontal className="h-3.5 w-3.5" aria-hidden />
            Sort by tag
          </button>
        </div>

        {hasFrameError ? (
          <ErrorState
            message={getErrorMessage(taskQuery.error ?? projectsQuery.error ?? tagsQuery.error)}
            onRetry={() => {
              void taskQuery.refetch();
              void projectsQuery.refetch();
              void tagsQuery.refetch();
            }}
          />
        ) : taskQuery.isLoading || projectsQuery.isLoading || tagsQuery.isLoading ? (
          <LoadingState label={title} />
        ) : tasks.length ? (
          <TaskList tasks={tasks} projects={projects} tags={tags} />
        ) : (
          <EmptyState state={state} />
        )}
      </section>
    </AppShell>
  );
}

function TaskList({ tasks, projects, tags }: { tasks: TaskResponse[]; projects: ProjectResponse[]; tags: TagResponse[] }): JSX.Element {
  const projectById = new Map(projects.map((project) => [project.id, project]));
  const tagById = new Map(tags.map((tag) => [tag.id, tag]));

  return (
    <div className="flex flex-col gap-2" role="list" aria-label="Tasks">
      {tasks.map((task) => {
        const project = task.project_id ? projectById.get(task.project_id) : undefined;
        const taskTags = task.context_ids.map((id) => tagById.get(id)).filter((tag): tag is TagResponse => Boolean(tag));
        return <TaskRow key={task.id} task={task} project={project} tags={taskTags} />;
      })}
      <button
        type="button"
        className="mt-3 flex min-h-11 items-center gap-2 rounded-xl border border-dashed border-slate-200 bg-slate-50/70 px-4 text-left text-xs text-slate-600 hover:border-slate-300 hover:text-slate-900"
        disabled
      >
        <Plus className="h-3.5 w-3.5" aria-hidden />
        Add a next action — or dump everything on your mind with the mic above
      </button>
    </div>
  );
}

function TaskRow({ task, project, tags }: { task: TaskResponse; project?: ProjectResponse; tags: TagResponse[] }): JSX.Element {
  return (
    <article
      className="flex min-h-[48px] flex-col gap-2 rounded-xl border border-slate-200 bg-white px-4 py-3 shadow-soft transition hover:shadow-raised sm:flex-row sm:items-center sm:gap-3"
      role="listitem"
    >
      <button
        type="button"
        className="h-[18px] w-[18px] shrink-0 rounded-full border border-[1.5px] border-slate-300 bg-white"
        aria-label={`Complete ${task.title}`}
        disabled
      />
      <div className="min-w-0 flex-1 text-sm font-medium text-slate-900">{task.title}</div>
      {task.due_date ? (
        <span className="w-fit rounded-full border border-rose-200 bg-rose-50 px-2 py-0.5 text-[11px] text-rose-700">
          {formatDueDate(task.due_date)}
        </span>
      ) : null}
      <div className="flex flex-wrap items-center gap-2 sm:ml-auto">
        {tags.map((tag) => (
          <span key={tag.id} className="rounded-full bg-slate-100 px-2.5 py-0.5 text-xs text-slate-600">
            @{tag.name.replace(/^@/, "")}
          </span>
        ))}
        {project ? <span className="text-[11px] text-slate-500 sm:w-[120px] sm:text-right">{project.name}</span> : null}
      </div>
    </article>
  );
}

function LoadingState({ label }: { label: string }): JSX.Element {
  return (
    <div className="space-y-2" aria-label={`Loading ${label}`}>
      {[0, 1, 2, 3].map((item) => (
        <div key={item} className="h-12 animate-pulse rounded-xl border border-slate-200 bg-white" />
      ))}
    </div>
  );
}

function EmptyState({ state }: { state?: OpenTaskState }): JSX.Element {
  const label = state ? stateLabels[state] : "This view";
  return (
    <div className="rounded-xl border border-dashed border-slate-200 bg-white/70 px-5 py-8 text-center text-sm text-slate-600">
      <p className="font-medium text-slate-900">{label} is clear</p>
      <p className="mt-1">Use Brain dump when you are ready to capture what's on your mind.</p>
    </div>
  );
}

function ErrorState({ message, onRetry }: { message: string; onRetry: () => void }): JSX.Element {
  return (
    <div className="rounded-xl border border-rose-200 bg-rose-50 px-5 py-4 text-sm text-rose-900" role="alert">
      <div className="flex items-start gap-3">
        <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0" aria-hidden />
        <div className="min-w-0 flex-1">
          <p className="font-semibold">We couldn't load tasks</p>
          <p className="mt-1 text-rose-800">{message}</p>
          <button type="button" className="mt-3 inline-flex h-9 items-center gap-2 rounded-lg bg-white px-3 font-medium text-rose-800 shadow-soft" onClick={onRetry}>
            <RotateCcw className="h-4 w-4" aria-hidden />
            Retry
          </button>
        </div>
      </div>
    </div>
  );
}

function formatDueDate(value: string): string {
  if (!value) {
    return "due";
  }
  const date = new Date(`${value}T00:00:00Z`);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleDateString(undefined, { month: "short", day: "numeric", timeZone: "UTC" });
}
