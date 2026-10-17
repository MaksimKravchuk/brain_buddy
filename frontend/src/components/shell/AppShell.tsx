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
  X
} from "lucide-react";
import { CarryOnMark } from "../brand/CarryOnMark";
import { useCallback, useEffect, useRef, useState } from "react";
import type { ComponentType, KeyboardEvent as ReactKeyboardEvent, ReactNode, RefObject } from "react";
import { createPortal } from "react-dom";
import { Link, NavLink, useLocation, useNavigate, useNavigationType, useSearchParams } from "react-router-dom";

import type { OpenTaskState, ProjectResponse, TagResponse, TaskCounts } from "../../api/taskTypes";
import { hasFeatureFlag } from "../../api/auth";
import { useAuthStore } from "../../stores/authStore";
import { useReviewState } from "../../api/reviewHooks";
import { lastReviewText } from "../../features/review/lastReview";
import { ReviewStartupDialogs } from "../../features/review/ReviewStartupDialogs";
import {
  ACTION_TOAST_MS,
  findShortcutLabel,
  isFindShortcut,
  isTextEntryTarget,
  isUndoShortcut,
  ShellToastContext,
  TEXT_TOAST_MS,
  undoShortcutLabel
} from "./shellToast";
import type { ShellNotify, ShellToastAction } from "./shellToast";
import { SignOutDialog } from "./SignOutDialog";
import { UpdateRequiredToast } from "./UpdateRequiredToast";
import { loadSignOutSummary, type SignOutSummary } from "./signOutSummary";

interface AppShellProps {
  children: ReactNode;
  /** Overlay detail surface, outside the inert workspace. */
  panel?: ReactNode;
  panelModal?: boolean;
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

type SidebarProps = AppShellProps;

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

// Fallback project dots use the dust mark role, never a palette colour.
const fallbackProjectColor = "var(--role-mark-open)";

// Sidebar create/rename popovers. Inputs are 16px below `lg`, where the sidebar
// lives in the touch drawer: iOS zooms the page into any smaller focused field.
const popoverClass =
  "z-50 w-56 rounded-card bg-card p-2 motion-safe:animate-scale-fade-in";
const popoverInputClass =
  "min-w-0 rounded-control bg-quiet px-3 py-1.5 text-base text-ink outline-hidden transition-colors duration-200 ease-smooth placeholder:text-ink-muted focus-visible:shadow-ring-focus lg:text-co-meta";
const popoverPrimaryClass =
  "rounded-control bg-ink px-3 py-1.5 text-co-meta font-semibold text-ground transition-colors duration-200 ease-smooth hover:bg-ink/85 disabled:opacity-50";
const popoverDangerClass =
  "rounded-control bg-quiet px-3 py-1.5 text-co-meta font-medium text-danger transition-colors duration-200 ease-smooth hover:bg-quiet-pressed";

const navRowClass = (active: boolean, tall = false): string =>
  `flex ${tall ? "min-h-[34px] py-1" : "h-[34px]"} w-full items-center gap-2.5 rounded-card px-2.5 text-left text-co-meta transition-colors duration-200 ease-smooth ${
    active ? "bg-card font-semibold text-ink" : "font-normal text-ink hover:bg-quiet-pressed/40"
  }`;

function SectionLabel({ children }: { children: ReactNode }): React.JSX.Element {
  return <div className="px-2.5 pb-1 text-co-meta text-ink-muted">{children}</div>;
}

export function SoonChip(): React.JSX.Element {
  return (
    <span aria-hidden className="rounded-control bg-quiet px-2 py-0.5 text-co-meta font-medium text-ink">
      Soon
    </span>
  );
}

/** The shell's toast host: `notify` for descendants, the toast itself on screen. */
export function ShellToastProvider({ children }: { children: ReactNode }): React.JSX.Element {
  const [toast, setToast] = useState<ShellToastState | null>(null);
  const toastIdRef = useRef(0);
  // Each toast gets its own id, so a newer one remounts the view with a fresh
  // timer and an older one's Undo can never fire for the newer message.
  const notify = useCallback<ShellNotify>((message, options) => {
    toastIdRef.current += 1;
    const id = toastIdRef.current;
    setToast({ id, message, action: options?.action });
    return () => setToast((showing) => (showing?.id === id ? null : showing));
  }, []);
  const dismissToast = useCallback(() => setToast(null), []);
  return (
    <ShellToastContext.Provider value={notify}>
      {children}
      {toast ? <ShellToastView key={toast.id} toast={toast} onDismiss={dismissToast} /> : null}
    </ShellToastContext.Provider>
  );
}

/** The working "Weekly review" entry with its neutral recap (FR-038); no recap line until the state is known. */
function WeeklyReviewLink(): React.JSX.Element {
  const recap = lastReviewText(useReviewState().data);
  return (
    <NavLink to="/review" className={({ isActive }) => navRowClass(isActive, true)}>
      <RotateCcw className="h-4 w-4 shrink-0 text-mark-open" aria-hidden />
      <span className="min-w-0 flex-1">
        <span className="block truncate">Weekly review</span>
        {recap ? <span className="block truncate text-co-meta font-normal text-ink-muted">{recap}</span> : null}
      </span>
    </NavLink>
  );
}

export function AppShell(props: AppShellProps): React.JSX.Element {
  const { children, panel, panelModal } = props;
  const [isDrawerOpen, setIsDrawerOpen] = useState(false);
  const navigationTriggerRef = useRef<HTMLButtonElement>(null);
  const location = useLocation();
  const weeklyReviewEnabled = useAuthStore((state) => hasFeatureFlag(state.user, "weekly_review"));
  const closeDrawer = useCallback(() => {
    setIsDrawerOpen(false);
    navigationTriggerRef.current?.focus();
  }, []);

  // Browser history can select a task while navigation is open. Do not leave
  // that drawer active behind the sheet; typing a search (same path, new
  // query) keeps it open. Adjusted during render so the dismissal lands in the
  // same commit as the new location (react-hooks/set-state-in-effect).
  const [renderedPathname, setRenderedPathname] = useState(location.pathname);
  if (renderedPathname !== location.pathname) {
    setRenderedPathname(location.pathname);
    setIsDrawerOpen(false);
  }

  return (
    <ShellToastProvider>
      <div className="min-h-screen bg-ground text-ink">
        <div inert={panelModal}>
          <TopBar onOpenDrawer={() => setIsDrawerOpen(true)} navigationTriggerRef={navigationTriggerRef} />
          <DeletionCancelledBanner />
          <div className="flex h-[calc(100vh-56px)] min-h-0 overflow-hidden">
            <aside className="hidden w-[248px] shrink-0 pb-3 pl-3 lg:block">
              <div className="h-full overflow-y-auto rounded-card co-glass px-3 pb-6 pt-4">
                <Sidebar {...props} />
              </div>
            </aside>
            <main className="min-w-0 flex-1 overflow-y-auto px-4 py-5 sm:px-6 lg:px-8 lg:pb-16 lg:pt-8">
              {children}
            </main>
          </div>
          <NavigationDrawer {...props} open={isDrawerOpen} onClose={closeDrawer} />
        </div>
        {/* 027 D-02: the update-required alert registers the 426 handler, so it
            mounts once here. It sits outside the inert workspace so a modal panel
            never silences or disables it. */}
        <UpdateRequiredToast />
        {panel}
        {/* Spec 020: the explainer, then While you were away, only while the flag is on. */}
        {weeklyReviewEnabled ? <ReviewStartupDialogs /> : null}
      </div>
    </ShellToastProvider>
  );
}

interface ShellToastState {
  id: number;
  message: string;
  action?: ShellToastAction;
}

/**
 * One toast. A text toast keeps its original 2.6 s, centred. An action toast
 * (the decision Undo, FR-048) sits bottom-left for about 5 s; hover or focus
 * holds it, and Ctrl/Cmd+Z outside a text field runs the action.
 */
function ShellToastView({ toast, onDismiss }: { toast: ShellToastState; onDismiss: () => void }): React.JSX.Element {
  const { action } = toast;
  const remainingRef = useRef(action ? ACTION_TOAST_MS : TEXT_TOAST_MS);
  const startedAtRef = useRef(0);
  const timerRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const holdsRef = useRef(0);

  const run = useCallback(() => {
    startedAtRef.current = Date.now();
    timerRef.current = setTimeout(onDismiss, remainingRef.current);
  }, [onDismiss]);

  useEffect(() => {
    run();
    return () => clearTimeout(timerRef.current);
  }, [run]);

  useEffect(() => {
    if (!action) {
      return;
    }
    const onKeyDown = (event: KeyboardEvent) => {
      if (!isUndoShortcut(event) || isTextEntryTarget(event.target)) {
        return;
      }
      event.preventDefault();
      onDismiss();
      action.onAction();
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [action, onDismiss]);

  if (!action) {
    return (
      <div
        role="status"
        className="fixed bottom-6 left-1/2 z-[200] w-max max-w-[calc(100vw-2rem)] -translate-x-1/2 rounded-card bg-ink px-4 py-2.5 text-center text-co-meta text-ground motion-safe:animate-fade-in-up"
      >
        {toast.message}
      </div>
    );
  }

  // Hover and focus each hold the toast; it resumes with the time it had left.
  const hold = () => {
    holdsRef.current += 1;
    if (holdsRef.current === 1) {
      clearTimeout(timerRef.current);
      remainingRef.current -= Date.now() - startedAtRef.current;
    }
  };
  const release = () => {
    holdsRef.current -= 1;
    if (holdsRef.current === 0) {
      run();
    }
  };
  const hintId = `shell-toast-hint-${toast.id}`;

  return (
    <div
      role="status"
      aria-describedby={hintId}
      onMouseEnter={hold}
      onMouseLeave={release}
      onFocus={hold}
      onBlur={release}
      className="fixed bottom-6 left-6 z-[200] flex max-w-[calc(100vw-3rem)] items-center gap-2 rounded-card bg-ink py-1 pl-4 pr-1 text-co-meta text-ground motion-safe:animate-fade-in-up"
    >
      <span className="min-w-0">{toast.message}</span>
      <button
        type="button"
        aria-label={action.accessibleLabel}
        className="inline-flex min-h-11 min-w-11 shrink-0 items-center justify-center rounded-control px-3 text-co-meta font-semibold text-ground underline transition-colors duration-200 ease-smooth hover:bg-ground/15"
        onClick={() => {
          onDismiss();
          action.onAction();
        }}
      >
        {action.label}
      </button>
      <span id={hintId} className="sr-only">{`${action.accessibleLabel} (${undoShortcutLabel()})`}</span>
    </div>
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
      className="flex items-center justify-between gap-3 bg-quiet px-4 py-2 text-co-meta text-warning"
    >
      <span>Welcome back — your scheduled account deletion has been cancelled.</span>
      <button
        type="button"
        aria-label="Dismiss deletion notice"
        className="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-control text-warning hover:bg-quiet-pressed"
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
  // The sign-out confirmation (020-FR-052): set while it is on screen.
  const [signOutSummary, setSignOutSummary] = useState<SignOutSummary | null>(null);
  const [signingOut, setSigningOut] = useState(false);
  const [signOutNotice, setSignOutNotice] = useState<"failed" | "changed" | null>(null);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const initial = (user?.display_name?.[0] ?? user?.email?.[0])?.toUpperCase() ?? "M";
  const reloadSignOutSummary = () => loadSignOutSummary(user?.id ?? "");

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
        triggerRef.current?.focus();
      }
    };
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  const requestSignOut = async () => {
    setOpen(false);
    setSignOutNotice(null);
    setSignOutSummary(await reloadSignOutSummary());
  };
  const cancelSignOut = useCallback(() => {
    setSignOutSummary(null);
    triggerRef.current?.focus();
  }, []);
  const confirmSignOut = async (shown: SignOutSummary) => {
    setSigningOut(true);
    setSignOutNotice(null);
    if (!shown.unsavedWork) {
      // Unsaved work that appeared since the dialog opened (another tab) was not
      // warned about: show the warning and wait for a second confirmation.
      const fresh = await reloadSignOutSummary();
      if (fresh.unsavedWork) {
        setSigningOut(false);
        setSignOutSummary(fresh);
        setSignOutNotice("changed");
        return;
      }
    }
    let signedOut = false;
    try {
      // This dialog is the one confirmation: logout() must not ask again, and
      // refuses (removing nothing) if it finds Thinking Mode drafts this dialog did not warn about.
      signedOut = await logout({ lossConfirmed: shown.unsavedWork });
    } catch {
      // A refused cleanup or a server error: the session is still in place.
    }
    if (signedOut) {
      setSigningOut(false);
      setSignOutSummary(null);
      navigate("/login");
      return;
    }
    // Not signed out. If the cause is work that appeared between the check
    // above and the cleanup, say so instead of a generic failure.
    const fresh = shown.unsavedWork ? shown : await reloadSignOutSummary();
    setSigningOut(false);
    if (fresh.unsavedWork && !shown.unsavedWork) {
      setSignOutSummary(fresh);
      setSignOutNotice("changed");
    } else {
      setSignOutNotice("failed");
    }
  };

  const itemClass =
    "flex w-full items-center gap-2.5 rounded-control px-2.5 py-2 text-left text-co-meta text-ink transition-colors duration-200 ease-smooth hover:bg-quiet";

  return (
    <div ref={containerRef} className="relative">
      <button
        ref={triggerRef}
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        // The signed-in email stays in the accessible name: e2e helpers (and
        // screen-reader users) identify the session by it.
        aria-label={user?.email ? `Account menu for ${user.email}` : "Account menu"}
        className="account-menu-trigger flex h-8 w-8 items-center justify-center rounded-full bg-quiet text-co-meta font-semibold text-ink transition-[background-color] duration-200 ease-smooth hover:bg-quiet-pressed"
        onClick={() => setOpen((value) => !value)}
      >
        {initial}
      </button>
      {open ? (
        <div
          role="menu"
          aria-label="Account"
          className="absolute right-0 top-[calc(100%+8px)] z-50 w-60 origin-top-right rounded-card bg-card p-1.5 motion-safe:animate-scale-fade-in"
        >
          <div className="px-2.5 py-2">
            <p className="truncate text-co-meta font-medium text-ink">
              {user?.display_name ?? user?.email ?? "Signed in"}
            </p>
            {user?.display_name && user?.email ? (
              <p className="truncate text-co-meta text-ink-muted">{user.email}</p>
            ) : null}
          </div>
          <div className="my-1 h-2" aria-hidden />
          <button
            type="button"
            role="menuitem"
            className={itemClass}
            onClick={() => {
              setOpen(false);
              navigate("/settings/account");
            }}
          >
            <Settings className="h-4 w-4 text-mark-open" aria-hidden /> Account settings
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
            <Bot className="h-4 w-4 text-mark-open" aria-hidden /> Connected agents
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
            <FileText className="h-4 w-4 text-mark-open" aria-hidden /> Privacy policy
          </button>
          {/* No admin entry here, deliberately (spec 009 PD-1, 009-FR-010/011):
              `/admin` is reached by typing the URL. A menu item would mean every
              member's shell issues an operator capability probe on load, which
              both changes a member-facing screen and floods the denial log the
              feature relies on as a signal. */}
          <div className="my-1 h-2" aria-hidden />
          <button
            type="button"
            role="menuitem"
            className={itemClass}
            onClick={() => void requestSignOut()}
          >
            <LogOut className="h-4 w-4 text-mark-open" aria-hidden /> Sign out
          </button>
        </div>
      ) : null}
      {signOutSummary
        ? createPortal(
            <SignOutDialog
              summary={signOutSummary}
              pending={signingOut}
              notice={signOutNotice}
              onCancel={cancelSignOut}
              onConfirm={() => void confirmSignOut(signOutSummary)}
            />,
            document.body
          )
        : null}
    </div>
  );
}

function TaskSearch({ className, onSubmit, findShortcut = false }: {
  className: string;
  onSubmit?: () => void;
  /** Ctrl/Cmd+O focuses this field from anywhere outside a modal (only the top bar's copy). */
  findShortcut?: boolean;
}): React.JSX.Element {
  const navigate = useNavigate();
  const location = useLocation();
  const [searchParams] = useSearchParams();
  const searchQuery = searchParams.get("q") ?? "";
  const navigationType = useNavigationType();
  const searchInputRef = useRef<HTMLInputElement>(null);
  const [searchValue, setSearchValue] = useState(searchQuery);

  useEffect(() => {
    // Router transitions must not replace text still being typed. History
    // navigation and the inactive search surface still follow the URL.
    if (navigationType !== "REPLACE" || document.activeElement !== searchInputRef.current) {
      setSearchValue(searchQuery);
    }
  }, [searchQuery, navigationType]);

  useEffect(() => {
    if (!findShortcut) return;
    const onKeyDown = (event: KeyboardEvent) => {
      const input = searchInputRef.current;
      if (!input || !isFindShortcut(event)) return;
      if (Array.from(document.querySelectorAll('[role="dialog"][aria-modal="true"], dialog[open]')).some((modal) => !modal.closest('[inert], [aria-hidden="true"]'))) return;
      input.focus();
      // A field hidden at this width cannot take focus: the browser keeps its own Ctrl/Cmd+O.
      if (document.activeElement !== input) return;
      event.preventDefault();
      input.select();
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [findShortcut]);

  const updateSearch = (value: string) => {
    setSearchValue(value);
    const next = new URLSearchParams(searchParams);
    if (value.trim()) {
      next.set("q", value.trim());
    } else {
      next.delete("q");
    }
    navigate({ pathname: location.pathname, search: next.toString() ? `?${next.toString()}` : "" }, { replace: true });
  };

  return (
    <form
      role="search"
      className={className}
      onSubmit={(event) => {
        event.preventDefault();
        onSubmit?.();
      }}
    >
      <label className="flex h-11 min-w-0 flex-1 cursor-text items-center gap-2 rounded-control bg-card px-3 text-ink-muted transition-[background-color,box-shadow] duration-200 ease-smooth focus-within:shadow-ring-focus md:h-[34px]">
        <Search className="h-[15px] w-[15px] shrink-0" aria-hidden />
        <input
          ref={searchInputRef}
          type="search"
          placeholder="Search tasks"
          aria-label="Search tasks"
          aria-keyshortcuts={findShortcut ? "Control+O Meta+O" : undefined}
          value={searchValue}
          onChange={(event) => updateSearch(event.currentTarget.value)}
          className="min-w-0 flex-1 bg-transparent text-base text-ink outline-hidden placeholder:text-ink-muted focus-visible:shadow-none md:text-co-meta"
        />
        {findShortcut ? (
          <kbd aria-hidden className="shrink-0 font-sans text-xs text-ink-muted">{findShortcutLabel()}</kbd>
        ) : null}
      </label>
      {onSubmit ? (
        <button type="submit" className="h-11 shrink-0 rounded-control bg-ink px-4 text-co-meta font-semibold text-ground transition-colors duration-200 ease-smooth hover:bg-ink/85 active:scale-[0.98]">
          Search
        </button>
      ) : null}
    </form>
  );
}

function TopBar({ onOpenDrawer, navigationTriggerRef }: {
  onOpenDrawer: () => void;
  navigationTriggerRef: RefObject<HTMLButtonElement | null>;
}): React.JSX.Element {
  const navigate = useNavigate();
  const location = useLocation();

  return (
    <header
      className="relative z-30 flex h-14 items-center gap-2 px-4 max-[359px]:gap-1 max-[359px]:px-2 sm:gap-4 sm:px-5"
      style={{ height: "56px" }}
    >
      <button
        ref={navigationTriggerRef}
        type="button"
        className="inline-flex h-11 w-11 items-center justify-center rounded-control text-ink-muted hover:bg-quiet hover:text-ink max-[359px]:shrink-0 lg:hidden"
        aria-label="Open task navigation"
        onClick={onOpenDrawer}
      >
        <Menu className="h-5 w-5" />
      </button>
      <Link to="/tasks/next" className="flex shrink-0 items-center gap-2 whitespace-nowrap font-voice text-xl text-ink">
        <CarryOnMark className="h-[26px] w-[26px] text-ink max-[359px]:hidden" />
        <span>Carry On</span>
      </Link>
      <TaskSearch className="hidden w-[340px] max-w-[32vw] md:flex" findShortcut />
      <div className="ml-auto flex shrink-0 items-center gap-2 max-[359px]:gap-1 sm:gap-3">
        <button
          type="button"
          className="inline-flex h-9 shrink-0 items-center gap-2 whitespace-nowrap rounded-control bg-card px-3 text-co-meta font-medium text-ink transition-colors duration-200 ease-smooth hover:bg-quiet active:scale-[0.98] max-[359px]:px-2 sm:px-4"
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
      <button type="button" className="absolute inset-0 bg-ink/30 motion-safe:animate-fade-in" aria-label="Close task navigation" onClick={onClose} />
      <div className="absolute inset-y-0 left-0 flex w-[min(320px,calc(100vw-32px))] flex-col bg-ground px-3 pb-6 pt-3 motion-safe:animate-drawer-in-left">
        <div className="mb-2 flex h-11 items-center justify-between px-2">
          <span className="text-co-meta font-semibold text-ink">Navigation</span>
          <button
            ref={closeButtonRef}
            type="button"
            className="-mr-2 inline-flex h-10 w-10 items-center justify-center rounded-control text-ink-muted transition-colors duration-200 ease-smooth hover:bg-card hover:text-ink"
            aria-label="Close task navigation"
            onClick={onClose}
          >
            <X className="h-5 w-5" />
          </button>
        </div>
        <TaskSearch className="mb-3 flex gap-2 px-2 md:hidden" onSubmit={onClose} />
        <div
          className="min-h-0 flex-1 overflow-y-auto rounded-card co-glass px-3 pb-6 pt-4"
          onClick={(event) => {
            const target = event.target as HTMLElement;
            if (target.closest("a")) {
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
  onDeleteTag
}: SidebarProps): React.JSX.Element {
  const [newProjectName, setNewProjectName] = useState("");
  const [projectEdits, setProjectEdits] = useState<Record<string, string>>({});
  const [newTagName, setNewTagName] = useState("");
  const [tagEdits, setTagEdits] = useState<Record<string, string>>({});
  const [openPopover, setOpenPopover] = useState<string | null>(null);
  const user = useAuthStore((state) => state.user);
  const hasCrtCanvas = hasFeatureFlag(user, "crt_canvas");
  const hasWeeklyReview = hasFeatureFlag(user, "weekly_review");

  const closePopover = () => setOpenPopover(null);
  const popoverKeyDown = (event: ReactKeyboardEvent) => {
    if (event.key === "Escape") {
      event.stopPropagation();
      closePopover();
    }
  };

  return (
    <nav aria-label="Task navigation" className="flex flex-col gap-5 text-co-meta">
      <ul className="space-y-0.5">
        {listItems.map((item) => (
          <li key={item.state}>
            <NavLink
              to={`/tasks/${item.state}`}
              className={({ isActive }) => navRowClass(isActive || activeState === item.state)}
            >
              <item.icon className="h-4 w-4 shrink-0 text-mark-open" aria-hidden />
              <span className="min-w-0 flex-1 truncate">{item.label}</span>
              {item.state === "inbox" ? (
                counts.inbox > 0 ? (
                  <span className="min-w-[20px] text-center text-co-meta tabular-nums text-ink-muted">{counts.inbox}</span>
                ) : null
              ) : (
                <span className="min-w-[20px] text-center text-co-meta tabular-nums text-ink-muted">{counts[item.state]}</span>
              )}
            </NavLink>
          </li>
        ))}
        <li>
          {hasWeeklyReview ? (
            <WeeklyReviewLink />
          ) : (
            <button
              type="button"
              disabled
              aria-label="Weekly review — Coming soon"
              className="flex h-[34px] w-full cursor-not-allowed items-center gap-2.5 rounded-card px-2.5 text-left text-co-meta text-ink-muted"
            >
              <RotateCcw className="h-4 w-4 shrink-0" aria-hidden />
              <span className="min-w-0 flex-1 truncate">Weekly review</span>
              <SoonChip />
            </button>
          )}
        </li>
        <li>
          {hasCrtCanvas ? (
            <NavLink to="/crt" className={({ isActive }) => navRowClass(isActive)}>
              <Network className="h-4 w-4 shrink-0 text-mark-open" aria-hidden />
              <span className="min-w-0 flex-1 truncate">Thinking Mode</span>
            </NavLink>
          ) : (
            <button
              type="button"
              disabled
              aria-label="Thinking Mode — Coming soon"
              className="flex h-[34px] w-full cursor-not-allowed items-center gap-2.5 rounded-card px-2.5 text-left text-co-meta text-ink-muted"
            >
              <Network className="h-4 w-4 shrink-0" aria-hidden />
              <span className="min-w-0 flex-1 truncate">Thinking Mode</span>
              <SoonChip />
            </button>
          )}
        </li>
      </ul>

      <div>
        <SectionLabel>Dates</SectionLabel>
        <ul className="space-y-0.5">
          {dateItems.map((item) => (
            <li key={item.path}>
              <NavLink to={item.path} className={({ isActive }) => navRowClass(isActive)}>
                <item.icon className="h-4 w-4 shrink-0 text-mark-open" aria-hidden />
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
            projects.map((project) => {
              const color = project.color ?? fallbackProjectColor;
              const popoverId = `project-${project.id}`;
              return (
                <li key={project.id} className="group relative">
                  <NavLink
                    to={`/projects/${project.id}`}
                    className={`flex min-h-[34px] w-full items-start gap-2.5 rounded-card px-2.5 py-[7px] pr-7 text-co-meta transition-colors duration-200 ease-smooth ${
                      activeProjectId === project.id
                        ? "bg-card font-semibold text-ink"
                        : "text-ink hover:bg-quiet-pressed/40"
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
                        className="absolute right-1 top-[7px] hidden h-5 w-5 items-center justify-center rounded-control text-ink-muted hover:bg-quiet-pressed hover:text-ink focus-visible:inline-flex group-focus-within:inline-flex group-hover:inline-flex max-lg:inline-flex"
                        onClick={() => setOpenPopover(openPopover === popoverId ? null : popoverId)}
                      >
                        <MoreHorizontal className="h-3.5 w-3.5" aria-hidden />
                      </button>
                      {openPopover === popoverId ? (
                        <div
                          role="dialog"
                          aria-label={`Edit project ${project.name}`}
                          className={`absolute right-0 top-8 origin-top-right ${popoverClass}`}
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
                              className={popoverInputClass}
                              value={projectEdits[project.id] ?? project.name}
                              onChange={(event) => {
                                const value = event.currentTarget.value;
                                setProjectEdits((current) => ({ ...current, [project.id]: value }));
                              }}
                            />
                            <div className="flex gap-1.5">
                              <button type="submit" className={`flex-1 ${popoverPrimaryClass}`}>
                                Rename
                              </button>
                              <button
                                type="button"
                                className={`flex-1 ${popoverDangerClass}`}
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
            <li className="px-2.5 py-2 text-co-meta text-ink-muted">No active projects yet</li>
          )}
          {onCreateProject ? (
            <li className="relative">
              <button
                type="button"
                aria-label="New project"
                aria-expanded={openPopover === "new-project"}
                className="flex h-[34px] w-full items-center gap-2.5 rounded-card px-2.5 text-left text-co-meta text-ink-muted transition-colors duration-200 ease-smooth hover:bg-quiet-pressed/40 hover:text-ink"
                onClick={() => setOpenPopover(openPopover === "new-project" ? null : "new-project")}
              >
                <Plus className="h-3.5 w-3.5 shrink-0" aria-hidden />
                <span className="min-w-0 flex-1 truncate">New project</span>
              </button>
              {openPopover === "new-project" ? (
                <div
                  role="dialog"
                  aria-label="Create project"
                  className={`absolute left-0 top-9 origin-top-left ${popoverClass}`}
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
                      className={popoverInputClass}
                      placeholder="New project"
                      value={newProjectName}
                      onChange={(event) => setNewProjectName(event.currentTarget.value)}
                    />
                    <button
                      type="submit"
                      className={popoverPrimaryClass}
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
                      className={`max-w-full truncate rounded-control px-2.5 py-[3px] text-co-meta transition-colors duration-200 ease-smooth ${
                        onRenameTag || onDeleteTag ? "max-lg:pr-6" : ""
                      } ${
                        activeTagId === tag.id
                          ? "bg-ink font-medium text-ground"
                          : "bg-quiet text-ink hover:bg-quiet-pressed"
                      }`}
                    >
                      {tag.name.startsWith("@") ? tag.name : `#${tag.name.replace(/^#/, "")}`}
                    </NavLink>
                    {onRenameTag || onDeleteTag ? (
                      // A hover badge on the desktop sidebar. In the touch drawer
                      // there is no hover, so it sits inside the pill's end instead
                      // of floating over the neighbouring pills.
                      <button
                        type="button"
                        aria-label={`Tag options ${tag.name}`}
                        aria-expanded={openPopover === popoverId}
                        className="absolute -right-1.5 -top-1.5 hidden h-4 w-4 items-center justify-center rounded-full bg-quiet text-ink-muted transition-colors duration-200 ease-smooth hover:text-ink group-focus-within:inline-flex group-hover:inline-flex max-lg:right-1 max-lg:top-1/2 max-lg:inline-flex max-lg:h-5 max-lg:w-5 max-lg:-translate-y-1/2 max-lg:bg-transparent"
                        onClick={() => setOpenPopover(openPopover === popoverId ? null : popoverId)}
                      >
                        <MoreHorizontal className="h-2.5 w-2.5 max-lg:h-3.5 max-lg:w-3.5" aria-hidden />
                      </button>
                    ) : null}
                  </span>
                  {onRenameTag || onDeleteTag ? (
                    openPopover === popoverId ? (
                      <div
                        role="dialog"
                        aria-label={`Edit tag ${tag.name}`}
                        className={`absolute bottom-full right-0 mb-1 origin-bottom-right ${popoverClass}`}
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
                              className={popoverInputClass}
                              value={tagEdits[tag.id] ?? tag.name}
                              onChange={(event) => {
                                const value = event.currentTarget.value;
                                setTagEdits((current) => ({ ...current, [tag.id]: value }));
                              }}
                            />
                            <div className="flex gap-1.5">
                              <button type="submit" className={`flex-1 ${popoverPrimaryClass}`}>
                                Rename
                              </button>
                              <button
                                type="button"
                                className={`flex-1 ${popoverDangerClass}`}
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
            <span className="text-co-meta text-ink-muted">No tags yet</span>
          )}
          {onCreateTag ? (
            <span className="relative inline-flex">
              <button
                type="button"
                aria-label="New tag"
                aria-expanded={openPopover === "new-tag"}
                className="rounded-control bg-transparent px-2.5 py-[3px] text-co-meta text-ink-muted transition-colors duration-200 ease-smooth hover:bg-quiet-pressed/40 hover:text-ink"
                onClick={() => setOpenPopover(openPopover === "new-tag" ? null : "new-tag")}
              >
                New tag
              </button>
              {openPopover === "new-tag" ? (
                <div
                  role="dialog"
                  aria-label="Create tag"
                  className={`absolute left-0 top-7 origin-top-left ${popoverClass}`}
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
                      className={popoverInputClass}
                      placeholder="New tag"
                      value={newTagName}
                      onChange={(event) => setNewTagName(event.currentTarget.value)}
                    />
                    <button
                      type="submit"
                      className={popoverPrimaryClass}
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
