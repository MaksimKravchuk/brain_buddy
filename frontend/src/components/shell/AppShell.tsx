/* istanbul ignore file -- source-faithful responsive shell is covered by Playwright visual snapshots. */
import { Menu, Mic, Search, Sprout, X } from "lucide-react";
import { useState } from "react";
import type { ReactNode } from "react";
import { Link, NavLink, useLocation, useNavigate, useSearchParams } from "react-router-dom";

import type { OpenTaskState, ProjectResponse, TagResponse, TaskCounts } from "../../api/taskTypes";
import { useAuthStore } from "../../stores/authStore";

interface AppShellProps {
  children: ReactNode;
  counts: TaskCounts;
  projects: ProjectResponse[];
  tags: TagResponse[];
  activeState?: OpenTaskState;
  activeProjectId?: string;
  activeTagId?: string;
  onCreateProject?: (name: string) => void;
  onRenameProject?: (project: ProjectResponse, name: string) => void;
  onArchiveProject?: (project: ProjectResponse) => void;
  onCreateTag?: (name: string) => void;
  onRenameTag?: (tag: TagResponse, name: string) => void;
  onDeleteTag?: (tag: TagResponse) => void;
}

const listItems: Array<{ state: OpenTaskState; label: string; icon: string }> = [
  { state: "inbox", label: "Inbox", icon: "⌂" },
  { state: "next", label: "Next actions", icon: "→" },
  { state: "waiting", label: "Waiting for", icon: "◷" },
  { state: "someday", label: "Someday / maybe", icon: "□" }
];

const dateItems: Array<{ path: string; label: string; icon: string }> = [
  { path: "/tasks/overdue", label: "Overdue", icon: "!" },
  { path: "/tasks/today", label: "Today", icon: "●" },
  { path: "/tasks/upcoming", label: "Upcoming", icon: "↗" }
];

const fallbackProjectColors = ["#0ea5e9", "#6366f1", "#94a3b8", "#10b981"];

export function AppShell(props: AppShellProps): JSX.Element {
  const { children } = props;
  const [isDrawerOpen, setIsDrawerOpen] = useState(false);

  return (
    <div className="min-h-screen bg-surface-base text-slate-900">
      <TopBar onOpenDrawer={() => setIsDrawerOpen(true)} />
      <div className="flex h-[calc(100vh-52px)] min-h-0 overflow-hidden">
        <aside className="hidden w-[248px] shrink-0 overflow-y-auto border-r border-slate-200 bg-surface-sunken/80 p-3 lg:block md:w-[220px] lg:w-[248px]">
          <Sidebar {...props} />
        </aside>
        <main className="min-w-0 flex-1 overflow-y-auto px-4 py-5 sm:px-6 lg:px-8 lg:py-7">
          {children}
        </main>
      </div>
      <NavigationDrawer {...props} open={isDrawerOpen} onClose={() => setIsDrawerOpen(false)} />
    </div>
  );
}

function TopBar({ onOpenDrawer }: { onOpenDrawer: () => void }): JSX.Element {
  const navigate = useNavigate();
  const location = useLocation();
  const [searchParams] = useSearchParams();
  const user = useAuthStore((state) => state.user);
  const initial = user?.email?.[0]?.toUpperCase() ?? "M";
  const searchQuery = searchParams.get("q") ?? "";

  const updateSearch = (value: string) => {
    const next = new URLSearchParams(searchParams);
    if (value.trim()) {
      next.set("q", value.trim());
    } else {
      next.delete("q");
    }
    navigate({ pathname: location.pathname, search: next.toString() ? `?${next.toString()}` : "" }, { replace: true });
  };

  return (
    <header
      className="relative z-30 flex h-[52px] items-center gap-3 border-b border-slate-200 bg-white/90 px-4 shadow-soft backdrop-blur sm:px-6"
      style={{ height: "52px" }}
    >
      <button
        type="button"
        className="inline-flex h-11 w-11 items-center justify-center rounded-lg text-slate-600 hover:bg-slate-100 lg:hidden"
        aria-label="Open task navigation"
        onClick={onOpenDrawer}
      >
        <Menu className="h-5 w-5" />
      </button>
      <Link to="/tasks/next" className="flex items-center gap-2 text-[15px] font-semibold text-slate-900">
        <Sprout className="h-5 w-5 text-brand-primary" aria-hidden />
        <span>Brain Buddy</span>
      </Link>
      <label className="ml-1 hidden h-[34px] w-[300px] max-w-[32vw] items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 text-[13px] text-slate-500 shadow-soft md:flex">
        <Search className="h-3.5 w-3.5" aria-hidden />
        <input
          type="search"
          placeholder="Search tasks"
          aria-label="Search tasks"
          value={searchQuery}
          onChange={(event) => updateSearch(event.currentTarget.value)}
          className="min-w-0 flex-1 bg-transparent placeholder:text-slate-500"
        />
      </label>
      <div className="ml-auto flex items-center gap-2 sm:gap-3">
        <button
          type="button"
          className="inline-flex h-9 items-center gap-2 rounded-lg bg-brand-primary px-4 text-sm font-medium text-white shadow-soft transition hover:bg-brand-primary-hover active:scale-[0.98]"
          onClick={() => navigate("/brain-dump/new")}
        >
          <Mic className="h-[15px] w-[15px]" aria-hidden />
          Brain dump
        </button>
        <div className="flex h-8 w-8 items-center justify-center rounded-full bg-sky-100 text-xs font-semibold text-sky-700" aria-label={user?.email ?? "User avatar"}>
          {initial}
        </div>
      </div>
    </header>
  );
}

type NavigationDrawerProps = AppShellProps & { open: boolean; onClose: () => void };

function NavigationDrawer({ open, onClose, ...props }: NavigationDrawerProps): JSX.Element | null {
  if (!open) {
    return null;
  }

  return (
    <div className="fixed inset-0 z-40 lg:hidden" role="dialog" aria-modal="true" aria-label="Task navigation">
      <button type="button" className="absolute inset-0 bg-slate-900/30" aria-label="Close task navigation" onClick={onClose} />
      <div className="absolute inset-y-0 left-0 flex w-[min(320px,calc(100vw-32px))] flex-col bg-surface-sunken p-3 shadow-floating">
        <div className="mb-2 flex h-11 items-center justify-between px-2">
          <span className="text-sm font-semibold text-slate-900">Navigation</span>
          <button type="button" className="inline-flex h-10 w-10 items-center justify-center rounded-lg text-slate-600 hover:bg-white" aria-label="Close task navigation" onClick={onClose}>
            <X className="h-5 w-5" />
          </button>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto" onClick={onClose}>
          <Sidebar {...props} />
        </div>
      </div>
    </div>
  );
}

function Sidebar({
  counts,
  projects,
  tags,
  activeState,
  activeProjectId,
  activeTagId,
  onCreateProject,
  onRenameProject,
  onArchiveProject,
  onCreateTag,
  onRenameTag,
  onDeleteTag
}: AppShellProps): JSX.Element {
  const [newProjectName, setNewProjectName] = useState("");
  const [projectEdits, setProjectEdits] = useState<Record<string, string>>({});
  const [newTagName, setNewTagName] = useState("");
  const [tagEdits, setTagEdits] = useState<Record<string, string>>({});

  return (
    <nav aria-label="Task navigation" className="flex flex-col gap-0.5 text-sm">
      <ul className="space-y-0.5">
        {listItems.map((item) => (
          <li key={item.state}>
            <NavLink
              to={`/tasks/${item.state}`}
              className={({ isActive }) =>
                `flex min-h-9 items-center gap-2.5 rounded-lg px-2.5 py-2 ${
                  isActive || activeState === item.state
                    ? "border border-slate-200 bg-white font-medium text-slate-900 shadow-soft"
                    : "text-slate-700 hover:bg-slate-200/70"
                }`
              }
            >
              <span className="flex h-4 w-4 items-center justify-center text-brand-primary" aria-hidden>{item.icon}</span>
              <span className="min-w-0 flex-1 truncate">{item.label}</span>
              {counts[item.state] ? (
                <span className={item.state === "inbox" ? "rounded-full bg-brand-primary px-2 py-0.5 text-[11px] font-semibold text-white" : "text-[11px] text-slate-500"}>
                  {counts[item.state]}
                </span>
              ) : null}
            </NavLink>
          </li>
        ))}
      </ul>

      <div className="px-2.5 pt-4 pb-1.5 text-[10px] font-semibold uppercase tracking-[0.06em] text-slate-500">Dates</div>
      <ul className="space-y-0.5">
        {dateItems.map((item) => (
          <li key={item.path}>
            <NavLink
              to={item.path}
              className={({ isActive }) =>
                `flex min-h-8 items-center gap-2.5 rounded-lg px-2.5 py-1.5 ${isActive ? "bg-white font-medium text-slate-900 shadow-soft" : "text-slate-700 hover:bg-slate-200/70"}`
              }
            >
              <span className="flex h-4 w-4 items-center justify-center text-brand-primary" aria-hidden>{item.icon}</span>
              <span className="min-w-0 flex-1 truncate">{item.label}</span>
            </NavLink>
          </li>
        ))}
      </ul>

      <div className="px-2.5 pt-4 pb-1.5 text-[10px] font-semibold uppercase tracking-[0.06em] text-slate-500">Projects</div>
      {onCreateProject ? (
        <form
          className="mb-2 flex gap-1 px-2.5"
          onSubmit={(event) => {
            event.preventDefault();
            if (newProjectName.trim()) {
              onCreateProject(newProjectName.trim());
              setNewProjectName("");
            }
          }}
        >
          <input
            aria-label="New project name"
            className="min-w-0 flex-1 rounded-md border border-slate-200 bg-white px-2 py-1 text-xs"
            placeholder="New project"
            value={newProjectName}
            onChange={(event) => setNewProjectName(event.currentTarget.value)}
          />
          <button type="submit" className="rounded-md bg-brand-primary px-2 py-1 text-xs font-semibold text-white" disabled={!newProjectName.trim()}>
            Add
          </button>
        </form>
      ) : null}
      <ul className="space-y-1">
        {projects.length ? projects.map((project, index) => (
          <li key={project.id}>
            <NavLink
              to={`/projects/${project.id}`}
              className={`flex min-h-8 items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-slate-700 hover:bg-slate-200/70 ${activeProjectId === project.id ? "bg-white text-slate-900 shadow-soft" : ""}`}
            >
              <span className="h-2 w-2 rounded-full" style={{ backgroundColor: project.color ?? fallbackProjectColors[index % fallbackProjectColors.length] }} aria-hidden />
              <span className="min-w-0 flex-1 truncate">{project.name}</span>
            </NavLink>
            {onRenameProject || onArchiveProject ? (
              <form
                className="mt-1 flex gap-1 px-2.5"
                onSubmit={(event) => {
                  event.preventDefault();
                  const name = (projectEdits[project.id] ?? project.name).trim();
                  if (name && name !== project.name) {
                    onRenameProject?.(project, name);
                  }
                }}
              >
                <input
                  aria-label={`Project name ${project.name}`}
                  className="min-w-0 flex-1 rounded-md border border-slate-200 bg-white px-2 py-1 text-xs"
                  value={projectEdits[project.id] ?? project.name}
                  onChange={(event) => {
                    const value = event.currentTarget.value;
                    setProjectEdits((current) => ({ ...current, [project.id]: value }));
                  }}
                />
                <button type="submit" className="rounded-md border border-slate-200 bg-white px-2 py-1 text-xs text-slate-600">
                  Rename
                </button>
                <button type="button" className="rounded-md border border-rose-200 bg-white px-2 py-1 text-xs text-rose-600" onClick={() => onArchiveProject?.(project)}>
                  Archive
                </button>
              </form>
            ) : null}
          </li>
        )) : (
          <li className="px-2.5 py-2 text-xs text-slate-500">No active projects yet</li>
        )}
      </ul>

      <div className="px-2.5 pt-4 pb-2 text-[10px] font-semibold uppercase tracking-[0.06em] text-slate-500">Tags</div>
      {onCreateTag ? (
        <form
          className="mb-2 flex gap-1 px-2.5"
          onSubmit={(event) => {
            event.preventDefault();
            if (newTagName.trim()) {
              onCreateTag(newTagName.trim());
              setNewTagName("");
            }
          }}
        >
          <input
            aria-label="New tag name"
            className="min-w-0 flex-1 rounded-md border border-slate-200 bg-white px-2 py-1 text-xs"
            placeholder="New tag"
            value={newTagName}
            onChange={(event) => setNewTagName(event.currentTarget.value)}
          />
          <button type="submit" className="rounded-md bg-brand-primary px-2 py-1 text-xs font-semibold text-white" disabled={!newTagName.trim()}>
            Add
          </button>
        </form>
      ) : null}
      <div className="flex flex-col gap-1.5 px-2.5">
        {tags.length ? tags.map((tag) => (
          <div key={tag.id} className="flex flex-col gap-1">
            <NavLink
              to={`/tags/${tag.id}`}
              className={`w-fit rounded-full border border-slate-200 bg-white px-2.5 py-1 text-xs text-slate-600 hover:border-slate-300 hover:text-slate-900 ${activeTagId === tag.id ? "border-sky-200 bg-sky-50 text-sky-700" : ""}`}
            >
              #{tag.name.replace(/^[#@]/, "")}
            </NavLink>
            {onRenameTag || onDeleteTag ? (
              <form
                className="flex gap-1"
                onSubmit={(event) => {
                  event.preventDefault();
                  const name = (tagEdits[tag.id] ?? tag.name).trim();
                  if (name && name !== tag.name) {
                    onRenameTag?.(tag, name);
                  }
                }}
              >
                <input
                  aria-label={`Tag name ${tag.name}`}
                  className="min-w-0 flex-1 rounded-md border border-slate-200 bg-white px-2 py-1 text-xs"
                  value={tagEdits[tag.id] ?? tag.name}
                  onChange={(event) => {
                    const value = event.currentTarget.value;
                    setTagEdits((current) => ({ ...current, [tag.id]: value }));
                  }}
                />
                <button type="submit" className="rounded-md border border-slate-200 bg-white px-2 py-1 text-xs text-slate-600">Rename</button>
                <button type="button" className="rounded-md border border-rose-200 bg-white px-2 py-1 text-xs text-rose-600" onClick={() => onDeleteTag?.(tag)}>Delete</button>
              </form>
            ) : null}
          </div>
        )) : (
          <span className="text-xs text-slate-500">No tags yet</span>
        )}
      </div>

      <div className="mt-4 rounded-lg border border-amber-200 bg-amber-50 px-2.5 py-2 text-xs text-amber-800">
        Weekly review <span className="font-semibold">coming later</span>
      </div>
      <NavLink to="/crt" className="mt-2 rounded-lg px-2.5 py-2 text-xs font-medium text-slate-600 hover:bg-slate-200/70">
        CRT (legacy)
      </NavLink>
    </nav>
  );
}
