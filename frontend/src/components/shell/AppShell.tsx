import {
  AlertTriangle,
  Archive,
  ArrowRight,
  Bot,
  CalendarDays,
  CalendarRange,
  Clock,
  FileText,
  Inbox,
  LogOut,
  Menu,
  Mic,
  MoreHorizontal,
  Network,
  Plus,
  RotateCcw,
  Search,
  Settings,
  Sprout,
  X
} from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import type { ComponentType, KeyboardEvent as ReactKeyboardEvent, ReactNode } from "react";
import { Link, NavLink, useLocation, useNavigate, useSearchParams } from "react-router-dom";

import type { OpenTaskState, ProjectResponse, TagResponse, TaskCounts } from "../../api/taskTypes";
import { useAuthStore } from "../../stores/authStore";
import { ShellToastContext } from "./shellToast";

interface AppShellProps {
  children: ReactNode;
  /** Right-side detail panel (prototype `bbs-detail`), rendered beside the content pane. */
  panel?: ReactNode;
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

type SidebarProps = AppShellProps & {
  weeklyReviewOpen: boolean;
  onOpenWeeklyReview: () => void;
};

const listItems: Array<{ state: OpenTaskState; label: string; icon: ComponentType<{ className?: string }> }> = [
  { state: "inbox", label: "Inbox", icon: Inbox },
  { state: "next", label: "Next actions", icon: ArrowRight },
  { state: "waiting", label: "Waiting for", icon: Clock },
  { state: "someday", label: "Someday / maybe", icon: Archive }
];

const dateItems: Array<{ path: string; label: string; icon: ComponentType<{ className?: string }> }> = [
  { path: "/tasks/overdue", label: "Overdue", icon: AlertTriangle },
  { path: "/tasks/today", label: "Today", icon: CalendarDays },
  { path: "/tasks/upcoming", label: "Upcoming", icon: CalendarRange }
];

const fallbackProjectColors = ["#0ea5e9", "#6366f1", "#94a3b8", "#10b981"];

const navRowClass = (active: boolean): string =>
  `flex h-[34px] w-full items-center gap-2.5 rounded-lg px-2.5 text-left text-sm font-medium transition-colors duration-200 ease-smooth ${
    active ? "bg-white text-slate-900 shadow-soft" : "text-slate-600 hover:bg-surface-sunken hover:text-slate-900"
  }`;

function SectionLabel({ children }: { children: ReactNode }): React.JSX.Element {
  return <div className="px-2.5 pb-1.5 text-[10px] font-semibold uppercase tracking-[0.06em] text-slate-500">{children}</div>;
}

export function SoonChip(): React.JSX.Element {
  return (
    <span aria-hidden className="rounded-full border border-slate-200 bg-surface-sunken px-[7px] py-[2px] text-[10px] font-semibold text-slate-600">
      Soon
    </span>
  );
}

export function AppShell(props: AppShellProps): React.JSX.Element {
  const { children, panel } = props;
  const [isDrawerOpen, setIsDrawerOpen] = useState(false);
  const [weeklyReviewOpen, setWeeklyReviewOpen] = useState(false);
  const [toast, setToast] = useState<string | null>(null);
  const toastTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const location = useLocation();

  const notify = useCallback((message: string) => {
    setToast(message);
    if (toastTimerRef.current) {
      clearTimeout(toastTimerRef.current);
    }
    toastTimerRef.current = setTimeout(() => setToast(null), 2600);
  }, []);

  useEffect(() => {
    return () => {
      if (toastTimerRef.current) {
        clearTimeout(toastTimerRef.current);
      }
    };
  }, []);

  useEffect(() => {
    setWeeklyReviewOpen(false);
  }, [location.pathname, location.search]);

  const sidebarProps: SidebarProps = {
    ...props,
    weeklyReviewOpen,
    onOpenWeeklyReview: () => setWeeklyReviewOpen(true)
  };

  return (
    <ShellToastContext.Provider value={notify}>
      <div className="min-h-screen bg-surface-base text-slate-900">
        <TopBar onOpenDrawer={() => setIsDrawerOpen(true)} />
        <DeletionCancelledBanner />
        <div className="flex h-[calc(100vh-56px)] min-h-0 overflow-hidden">
          <aside className="hidden w-[248px] shrink-0 overflow-y-auto border-r border-slate-200 px-3 pb-6 pt-4 lg:block">
            <Sidebar {...sidebarProps} />
          </aside>
          <main className="min-w-0 flex-1 overflow-y-auto px-4 py-5 sm:px-6 lg:px-8 lg:pb-16 lg:pt-8">
            {weeklyReviewOpen ? <WeeklyReviewPlaceholder /> : children}
          </main>
          {weeklyReviewOpen ? null : panel}
        </div>
        <NavigationDrawer {...sidebarProps} open={isDrawerOpen} onClose={() => setIsDrawerOpen(false)} />
        {toast ? (
          <div
            role="status"
            className="fixed bottom-6 left-1/2 z-[200] -translate-x-1/2 whitespace-nowrap rounded-[12px] border border-slate-200 bg-white/95 px-4 py-2.5 text-[13px] text-slate-700 shadow-floating backdrop-blur motion-safe:animate-fade-in-up"
          >
            {toast}
          </div>
        ) : null}
      </div>
    </ShellToastContext.Provider>
  );
}

function WeeklyReviewPlaceholder(): React.JSX.Element {
  return (
    <section aria-label="Weekly review placeholder" className="mx-auto max-w-[760px]">
      <div className="flex flex-col items-center gap-2 rounded-xl border-[1.5px] border-dashed border-slate-300 px-8 py-14 text-center">
        <div className="mb-2 flex h-14 w-14 items-center justify-center rounded-full bg-info-bg text-brand-primary">
          <RotateCcw className="h-[26px] w-[26px]" aria-hidden />
        </div>
        <h2 className="m-0 text-[28px] font-semibold leading-[1.15] tracking-[-0.02em] text-slate-900">
          Weekly review — coming soon
        </h2>
        <p className="m-0 max-w-[400px] text-sm leading-normal text-slate-500">
          A guided pass over your lists — empty the inbox, refresh next actions, decide on the somedays. We&apos;re
          still building this one.
        </p>
        <span className="mt-3 rounded-full bg-surface-sunken px-2.5 py-[3px] text-[10px] font-semibold uppercase tracking-[0.06em] text-slate-400">
          Placeholder — not designed yet
        </span>
      </div>
    </section>
  );
}

function DeletionCancelledBanner(): React.JSX.Element | null {
  const notice = useAuthStore((state) => state.deletionCancelledNotice);
  const dismiss = useAuthStore((state) => state.dismissDeletionNotice);
  if (!notice) {
    return null;
  }
  return (
    <div
      role="status"
      className="flex items-center justify-between gap-3 border-b border-amber-200 bg-amber-50 px-4 py-2 text-sm text-amber-800"
    >
      <span>Welcome back — your scheduled account deletion has been cancelled.</span>
      <button
        type="button"
        aria-label="Dismiss deletion notice"
        className="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-amber-700 hover:bg-amber-100"
        onClick={dismiss}
      >
        <X className="h-4 w-4" aria-hidden />
      </button>
    </div>
  );
}

function AccountMenu(): React.JSX.Element {
  const navigate = useNavigate();
  const user = useAuthStore((state) => state.user);
  const logout = useAuthStore((state) => state.logout);
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const initial = (user?.display_name?.[0] ?? user?.email?.[0])?.toUpperCase() ?? "M";

  useEffect(() => {
    if (!open) {
      return;
    }
    const onPointerDown = (event: MouseEvent) => {
      if (!containerRef.current?.contains(event.target as Node)) {
        setOpen(false);
      }
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  const itemClass =
    "flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-left text-sm text-slate-700 transition-colors duration-200 ease-smooth hover:bg-surface-sunken hover:text-slate-900";

  return (
    <div ref={containerRef} className="relative">
      <button
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        // The signed-in email stays in the accessible name: e2e helpers (and
        // screen-reader users) identify the session by it.
        aria-label={user?.email ? `Account menu for ${user.email}` : "Account menu"}
        className="account-menu-trigger flex h-8 w-8 items-center justify-center rounded-full bg-sky-100 text-xs font-semibold text-sky-700 transition-shadow duration-200 ease-smooth hover:shadow-soft"
        onClick={() => setOpen((value) => !value)}
      >
        {initial}
      </button>
      {open ? (
        <div
          role="menu"
          aria-label="Account"
          className="absolute right-0 top-[calc(100%+8px)] z-50 w-60 rounded-xl border border-slate-200 bg-white p-1.5 shadow-floating"
        >
          <div className="px-2.5 py-2">
            <p className="truncate text-sm font-medium text-slate-900">
              {user?.display_name ?? user?.email ?? "Signed in"}
            </p>
            {user?.display_name && user?.email ? (
              <p className="truncate text-xs text-slate-500">{user.email}</p>
            ) : null}
          </div>
          <div className="my-1 h-px bg-slate-100" aria-hidden />
          <button
            type="button"
            role="menuitem"
            className={itemClass}
            onClick={() => {
              setOpen(false);
              navigate("/settings/account");
            }}
          >
            <Settings className="h-4 w-4 text-slate-500" aria-hidden /> Account settings
          </button>
          <button
            type="button"
            role="menuitem"
            className={itemClass}
            onClick={() => {
              setOpen(false);
              navigate("/settings/agents");
            }}
          >
            <Bot className="h-4 w-4 text-slate-500" aria-hidden /> Connected agents
          </button>
          <button
            type="button"
            role="menuitem"
            className={itemClass}
            onClick={() => {
              setOpen(false);
              navigate("/privacy");
            }}
          >
            <FileText className="h-4 w-4 text-slate-500" aria-hidden /> Privacy policy
          </button>
          {/* No admin entry here, deliberately (spec 009 PD-1, 009-FR-010/011):
              `/admin` is reached by typing the URL. A menu item would mean every
              member's shell issues an operator capability probe on load, which
              both changes a member-facing screen and floods the denial log the
              feature relies on as a signal. */}
          <div className="my-1 h-px bg-slate-100" aria-hidden />
          <button
            type="button"
            role="menuitem"
            className={itemClass}
            onClick={async () => {
              setOpen(false);
              await logout();
              navigate("/login");
            }}
          >
            <LogOut className="h-4 w-4 text-slate-500" aria-hidden /> Sign out
          </button>
        </div>
      ) : null}
    </div>
  );
}

function TopBar({ onOpenDrawer }: { onOpenDrawer: () => void }): React.JSX.Element {
  const navigate = useNavigate();
  const location = useLocation();
  const [searchParams] = useSearchParams();
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
      className="relative z-30 flex h-14 items-center gap-2 border-b border-slate-200 bg-white/90 px-4 backdrop-blur sm:gap-4 sm:px-5"
      style={{ height: "56px" }}
    >
      <button
        type="button"
        className="inline-flex h-11 w-11 items-center justify-center rounded-lg text-slate-600 hover:bg-slate-100 lg:hidden"
        aria-label="Open task navigation"
        onClick={onOpenDrawer}
      >
        <Menu className="h-5 w-5" />
      </button>
      <Link to="/tasks/next" className="flex shrink-0 items-center gap-2 whitespace-nowrap text-sm font-semibold tracking-[-0.005em] text-slate-900 sm:text-[15px]">
        <Sprout className="h-[22px] w-[22px] text-brand-primary" aria-hidden />
        <span>Brain Buddy</span>
      </Link>
      <label className="hidden h-[34px] w-[340px] max-w-[32vw] items-center gap-2 rounded-lg border border-transparent bg-surface-sunken px-3 text-slate-400 transition-colors duration-200 ease-smooth focus-within:border-brand-primary focus-within:bg-white md:flex">
        <Search className="h-[15px] w-[15px] shrink-0" aria-hidden />
        <input
          type="search"
          placeholder="Search tasks"
          aria-label="Search tasks"
          value={searchQuery}
          onChange={(event) => updateSearch(event.currentTarget.value)}
          className="min-w-0 flex-1 bg-transparent text-sm text-slate-900 placeholder:text-slate-400"
        />
      </label>
      <div className="ml-auto flex shrink-0 items-center gap-2 sm:gap-3">
        <button
          type="button"
          className="inline-flex h-9 shrink-0 items-center gap-2 whitespace-nowrap rounded-lg bg-brand-primary px-3 text-sm font-medium text-white shadow-soft transition-colors duration-200 ease-smooth hover:bg-brand-primary-hover active:scale-[0.98] sm:px-4"
          // Stamping the current location makes brain dump open as a modal over
          // this view instead of replacing it — see AppRoutes.
          onClick={() => navigate("/brain-dump/new", { state: { backgroundLocation: location } })}
        >
          <Mic className="h-[15px] w-[15px]" aria-hidden />
          Brain dump
        </button>
        <AccountMenu />
      </div>
    </header>
  );
}

type NavigationDrawerProps = SidebarProps & { open: boolean; onClose: () => void };

function NavigationDrawer({ open, onClose, ...props }: NavigationDrawerProps): React.JSX.Element | null {
  const closeButtonRef = useRef<HTMLButtonElement | null>(null);

  useEffect(() => {
    if (!open) {
      return;
    }
    closeButtonRef.current?.focus();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onClose();
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [open, onClose]);

  if (!open) {
    return null;
  }

  return (
    <div className="fixed inset-0 z-40 lg:hidden" role="dialog" aria-modal="true" aria-label="Task navigation">
      <button type="button" className="absolute inset-0 bg-slate-900/30" aria-label="Close task navigation" onClick={onClose} />
      <div className="absolute inset-y-0 left-0 flex w-[min(320px,calc(100vw-32px))] flex-col bg-surface-base px-3 pb-6 pt-3 shadow-floating">
        <div className="mb-2 flex h-11 items-center justify-between px-2">
          <span className="text-sm font-semibold text-slate-900">Navigation</span>
          <button
            ref={closeButtonRef}
            type="button"
            className="inline-flex h-10 w-10 items-center justify-center rounded-lg text-slate-600 hover:bg-white"
            aria-label="Close task navigation"
            onClick={onClose}
          >
            <X className="h-5 w-5" />
          </button>
        </div>
        <div
          className="min-h-0 flex-1 overflow-y-auto"
          onClick={(event) => {
            const target = event.target as HTMLElement;
            if (target.closest("a, [data-drawer-dismiss]")) {
              onClose();
            }
          }}
        >
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
  onDeleteTag,
  weeklyReviewOpen,
  onOpenWeeklyReview
}: SidebarProps): React.JSX.Element {
  const [newProjectName, setNewProjectName] = useState("");
  const [projectEdits, setProjectEdits] = useState<Record<string, string>>({});
  const [newTagName, setNewTagName] = useState("");
  const [tagEdits, setTagEdits] = useState<Record<string, string>>({});
  const [openPopover, setOpenPopover] = useState<string | null>(null);

  const closePopover = () => setOpenPopover(null);
  const popoverKeyDown = (event: ReactKeyboardEvent) => {
    if (event.key === "Escape") {
      event.stopPropagation();
      closePopover();
    }
  };

  return (
    <nav aria-label="Task navigation" className="flex flex-col gap-5 text-sm">
      <ul className="space-y-0.5">
        {listItems.map((item) => (
          <li key={item.state}>
            <NavLink
              to={`/tasks/${item.state}`}
              className={({ isActive }) => navRowClass(!weeklyReviewOpen && (isActive || activeState === item.state))}
            >
              <item.icon className="h-4 w-4 shrink-0" aria-hidden />
              <span className="min-w-0 flex-1 truncate">{item.label}</span>
              {item.state === "inbox" ? (
                counts.inbox > 0 ? (
                  <span className="inline-flex h-[18px] min-w-[20px] items-center justify-center rounded-full bg-brand-primary px-1.5 text-[11px] font-semibold text-white">
                    {counts.inbox}
                  </span>
                ) : null
              ) : (
                <span className="min-w-[20px] text-center text-xs font-medium text-slate-400">{counts[item.state]}</span>
              )}
            </NavLink>
          </li>
        ))}
        <li>
          <button
            type="button"
            aria-label="Weekly review"
            data-drawer-dismiss
            className={navRowClass(weeklyReviewOpen)}
            onClick={onOpenWeeklyReview}
          >
            <RotateCcw className="h-4 w-4 shrink-0" aria-hidden />
            <span className="min-w-0 flex-1 truncate">Weekly review</span>
            <SoonChip />
          </button>
        </li>
        <li>
          <button
            type="button"
            disabled
            aria-label="Thinking Mode — Coming soon"
            className="flex h-[34px] w-full cursor-not-allowed items-center gap-2.5 rounded-lg px-2.5 text-left text-sm font-medium text-slate-400"
          >
            <Network className="h-4 w-4 shrink-0" aria-hidden />
            <span className="min-w-0 flex-1 truncate">Thinking Mode</span>
            <SoonChip />
          </button>
        </li>
      </ul>

      <div>
        <SectionLabel>Dates</SectionLabel>
        <ul className="space-y-0.5">
          {dateItems.map((item) => (
            <li key={item.path}>
              <NavLink to={item.path} className={({ isActive }) => navRowClass(!weeklyReviewOpen && isActive)}>
                <item.icon className="h-4 w-4 shrink-0" aria-hidden />
                <span className="min-w-0 flex-1 truncate">{item.label}</span>
              </NavLink>
            </li>
          ))}
        </ul>
      </div>

      <div>
        <SectionLabel>Projects</SectionLabel>
        <ul className="space-y-0.5">
          {projects.length ? (
            projects.map((project, index) => {
              const color = project.color ?? fallbackProjectColors[index % fallbackProjectColors.length];
              const popoverId = `project-${project.id}`;
              return (
                <li key={project.id} className="group relative">
                  <NavLink
                    to={`/projects/${project.id}`}
                    className={`flex min-h-[34px] w-full items-start gap-2.5 rounded-lg px-2.5 py-[7px] pr-7 text-sm font-medium transition-colors duration-200 ease-smooth ${
                      !weeklyReviewOpen && activeProjectId === project.id
                        ? "bg-white text-slate-900 shadow-soft"
                        : "text-slate-600 hover:bg-surface-sunken hover:text-slate-900"
                    }`}
                  >
                    <span className="mt-[5px] h-2 w-2 shrink-0 rounded-full" style={{ backgroundColor: color }} aria-hidden />
                    <span className="line-clamp-2 min-w-0 flex-1 leading-[1.35]">{project.name}</span>
                  </NavLink>
                  {onRenameProject || onArchiveProject ? (
                    <>
                      <button
                        type="button"
                        aria-label={`Project options ${project.name}`}
                        aria-expanded={openPopover === popoverId}
                        className="absolute right-1 top-[7px] hidden h-5 w-5 items-center justify-center rounded-md text-slate-400 hover:bg-slate-200/70 hover:text-slate-600 focus-visible:inline-flex group-focus-within:inline-flex group-hover:inline-flex max-lg:inline-flex"
                        onClick={() => setOpenPopover(openPopover === popoverId ? null : popoverId)}
                      >
                        <MoreHorizontal className="h-3.5 w-3.5" aria-hidden />
                      </button>
                      {openPopover === popoverId ? (
                        <div
                          role="dialog"
                          aria-label={`Edit project ${project.name}`}
                          className="absolute right-0 top-8 z-50 w-56 rounded-2xl border border-slate-200 bg-white p-2 shadow-floating"
                          onKeyDown={popoverKeyDown}
                        >
                          <form
                            className="flex flex-col gap-2"
                            onSubmit={(event) => {
                              event.preventDefault();
                              const name = (projectEdits[project.id] ?? project.name).trim();
                              if (name && name !== project.name) {
                                onRenameProject?.(project, name);
                              }
                              closePopover();
                            }}
                          >
                            <input
                              aria-label={`Project name ${project.name}`}
                              className="min-w-0 rounded-md border border-slate-200 bg-white px-2 py-1.5 text-xs"
                              value={projectEdits[project.id] ?? project.name}
                              onChange={(event) => {
                                const value = event.currentTarget.value;
                                setProjectEdits((current) => ({ ...current, [project.id]: value }));
                              }}
                            />
                            <div className="flex gap-1.5">
                              <button type="submit" className="flex-1 rounded-md bg-brand-primary px-2 py-1.5 text-xs font-semibold text-white">
                                Rename
                              </button>
                              <button
                                type="button"
                                className="flex-1 rounded-md border border-rose-200 bg-white px-2 py-1.5 text-xs text-rose-600"
                                onClick={() => {
                                  onArchiveProject?.(project);
                                  closePopover();
                                }}
                              >
                                Archive
                              </button>
                            </div>
                          </form>
                        </div>
                      ) : null}
                    </>
                  ) : null}
                </li>
              );
            })
          ) : (
            <li className="px-2.5 py-2 text-xs text-slate-500">No active projects yet</li>
          )}
          {onCreateProject ? (
            <li className="relative">
              <button
                type="button"
                aria-label="New project"
                aria-expanded={openPopover === "new-project"}
                className="flex h-[34px] w-full items-center gap-2.5 rounded-lg px-2.5 text-left text-sm font-medium text-slate-400 transition-colors duration-200 ease-smooth hover:bg-surface-sunken hover:text-slate-600"
                onClick={() => setOpenPopover(openPopover === "new-project" ? null : "new-project")}
              >
                <Plus className="h-3.5 w-3.5 shrink-0" aria-hidden />
                <span className="min-w-0 flex-1 truncate">New project</span>
              </button>
              {openPopover === "new-project" ? (
                <div
                  role="dialog"
                  aria-label="Create project"
                  className="absolute left-0 top-9 z-50 w-56 rounded-2xl border border-slate-200 bg-white p-2 shadow-floating"
                  onKeyDown={popoverKeyDown}
                >
                  <form
                    className="flex flex-col gap-2"
                    onSubmit={(event) => {
                      event.preventDefault();
                      if (newProjectName.trim()) {
                        onCreateProject(newProjectName.trim());
                        setNewProjectName("");
                        closePopover();
                      }
                    }}
                  >
                    <input
                      autoFocus
                      aria-label="New project name"
                      className="min-w-0 rounded-md border border-slate-200 bg-white px-2 py-1.5 text-xs"
                      placeholder="New project"
                      value={newProjectName}
                      onChange={(event) => setNewProjectName(event.currentTarget.value)}
                    />
                    <button
                      type="submit"
                      className="rounded-md bg-brand-primary px-2 py-1.5 text-xs font-semibold text-white disabled:opacity-50"
                      disabled={!newProjectName.trim()}
                    >
                      Add
                    </button>
                  </form>
                </div>
              ) : null}
            </li>
          ) : null}
        </ul>
      </div>

      <div>
        <SectionLabel>Tags</SectionLabel>
        <div className="relative flex flex-wrap gap-1.5 px-2.5">
          {tags.length ? (
            tags.map((tag) => {
              const popoverId = `tag-${tag.id}`;
              return (
                <span key={tag.id} className="group inline-flex max-w-full">
                  <span className="relative inline-flex min-w-0 max-w-full">
                    {/* A pill is a single-line shape: a long tag wrapped to two lines
                        inside a rounded-full border reads as broken. Truncate instead
                        and carry the full name in `title` — the link text itself is
                        untouched, so the accessible name stays complete. */}
                    <NavLink
                      to={`/tags/${tag.id}`}
                      title={tag.name}
                      className={`max-w-full truncate rounded-full border px-2.5 py-[3px] text-xs font-medium transition-colors duration-200 ease-smooth ${
                        !weeklyReviewOpen && activeTagId === tag.id
                          ? "border-brand-primary bg-info-bg text-info-fg"
                          : "border-slate-200 bg-white text-slate-600 hover:border-slate-300 hover:text-slate-900"
                      }`}
                    >
                      {tag.name.startsWith("@") ? tag.name : `#${tag.name.replace(/^#/, "")}`}
                    </NavLink>
                    {onRenameTag || onDeleteTag ? (
                      <button
                        type="button"
                        aria-label={`Tag options ${tag.name}`}
                        aria-expanded={openPopover === popoverId}
                        className="absolute -right-1.5 -top-1.5 hidden h-4 w-4 items-center justify-center rounded-full border border-slate-200 bg-white text-slate-500 shadow-soft group-focus-within:inline-flex group-hover:inline-flex max-lg:inline-flex"
                        onClick={() => setOpenPopover(openPopover === popoverId ? null : popoverId)}
                      >
                        <MoreHorizontal className="h-2.5 w-2.5" aria-hidden />
                      </button>
                    ) : null}
                  </span>
                  {onRenameTag || onDeleteTag ? (
                    openPopover === popoverId ? (
                      <div
                        role="dialog"
                        aria-label={`Edit tag ${tag.name}`}
                        className="absolute bottom-full right-0 z-50 mb-1 w-56 rounded-2xl border border-slate-200 bg-white p-2 shadow-floating"
                        onKeyDown={popoverKeyDown}
                      >
                          <form
                            className="flex flex-col gap-2"
                            onSubmit={(event) => {
                              event.preventDefault();
                              const name = (tagEdits[tag.id] ?? tag.name).trim();
                              if (name && name !== tag.name) {
                                onRenameTag?.(tag, name);
                              }
                              closePopover();
                            }}
                          >
                            <input
                              aria-label={`Tag name ${tag.name}`}
                              className="min-w-0 rounded-md border border-slate-200 bg-white px-2 py-1.5 text-xs"
                              value={tagEdits[tag.id] ?? tag.name}
                              onChange={(event) => {
                                const value = event.currentTarget.value;
                                setTagEdits((current) => ({ ...current, [tag.id]: value }));
                              }}
                            />
                            <div className="flex gap-1.5">
                              <button type="submit" className="flex-1 rounded-md bg-brand-primary px-2 py-1.5 text-xs font-semibold text-white">
                                Rename
                              </button>
                              <button
                                type="button"
                                className="flex-1 rounded-md border border-rose-200 bg-white px-2 py-1.5 text-xs text-rose-600"
                                onClick={() => {
                                  onDeleteTag?.(tag);
                                  closePopover();
                                }}
                              >
                                Delete
                              </button>
                            </div>
                          </form>
                      </div>
                    ) : null
                  ) : null}
                </span>
              );
            })
          ) : (
            <span className="text-xs text-slate-500">No tags yet</span>
          )}
          {onCreateTag ? (
            <span className="relative inline-flex">
              <button
                type="button"
                aria-label="New tag"
                aria-expanded={openPopover === "new-tag"}
                className="rounded-full border border-dashed border-slate-300 bg-transparent px-2.5 py-[3px] text-xs font-medium text-slate-400 transition-colors duration-200 ease-smooth hover:border-slate-400 hover:text-slate-600"
                onClick={() => setOpenPopover(openPopover === "new-tag" ? null : "new-tag")}
              >
                New tag
              </button>
              {openPopover === "new-tag" ? (
                <div
                  role="dialog"
                  aria-label="Create tag"
                  className="absolute left-0 top-7 z-50 w-56 rounded-2xl border border-slate-200 bg-white p-2 shadow-floating"
                  onKeyDown={popoverKeyDown}
                >
                  <form
                    className="flex flex-col gap-2"
                    onSubmit={(event) => {
                      event.preventDefault();
                      if (newTagName.trim()) {
                        onCreateTag(newTagName.trim());
                        setNewTagName("");
                        closePopover();
                      }
                    }}
                  >
                    <input
                      autoFocus
                      aria-label="New tag name"
                      className="min-w-0 rounded-md border border-slate-200 bg-white px-2 py-1.5 text-xs"
                      placeholder="New tag"
                      value={newTagName}
                      onChange={(event) => setNewTagName(event.currentTarget.value)}
                    />
                    <button
                      type="submit"
                      className="rounded-md bg-brand-primary px-2 py-1.5 text-xs font-semibold text-white disabled:opacity-50"
                      disabled={!newTagName.trim()}
                    >
                      Add
                    </button>
                  </form>
                </div>
              ) : null}
            </span>
          ) : null}
        </div>
      </div>
    </nav>
  );
}
