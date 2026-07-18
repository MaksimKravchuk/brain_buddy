import { useEffect, useMemo, useRef, useState } from "react";
import {
  ChevronDown,
  CircleHelp,
  Clock3,
  FileText,
  Inbox,
  Lightbulb,
  ListChecks,
  LoaderCircle,
  Menu,
  Mic,
  Plus,
  RotateCcw,
  Search,
  Send,
  Sparkles,
  Sprout,
  UserRound,
  UsersRound,
  X,
} from "lucide-react";

import "./TaskWorkspace.css";

type ViewId =
  | "inbox"
  | "next"
  | "waiting"
  | "someday"
  | "review"
  | "onboarding"
  | "pricing"
  | "offsite"
  | "billing"
  | "calls"
  | "errands"
  | "deep-work"
  | "laptop";

type TaskState =
  | "default"
  | "thinking"
  | "working"
  | "review"
  | "offer"
  | "needs-you";

type BrainDumpState = "recording" | "captured" | "review";

type Task = {
  id: string;
  title: string;
  project: string;
  context?: string;
  note?: string;
  due?: string;
  state?: TaskState;
  completed?: boolean;
};

const navItems: Array<{ id: ViewId; label: string; count?: number; icon: typeof Inbox }> = [
  { id: "inbox", label: "Inbox", count: 4, icon: Inbox },
  { id: "next", label: "Next actions", count: 6, icon: ListChecks },
  { id: "waiting", label: "Waiting for", count: 2, icon: Clock3 },
  { id: "someday", label: "Someday / maybe", count: 3, icon: Lightbulb },
  { id: "review", label: "Weekly review", icon: RotateCcw },
];

const projects: Array<{ id: ViewId; label: string; count: number; color: string }> = [
  { id: "onboarding", label: "Onboarding revamp", count: 6, color: "#6366f1" },
  { id: "pricing", label: "Pricing", count: 4, color: "#0ea5e9" },
  { id: "offsite", label: "Team offsite", count: 3, color: "#f59e0b" },
  {
    id: "billing",
    label: "Migrate billing to the new usage-based pricing model",
    count: 2,
    color: "#10b981",
  },
];

const contexts: Array<{ id: ViewId; label: string }> = [
  { id: "calls", label: "@calls" },
  { id: "errands", label: "@errands" },
  { id: "deep-work", label: "@deep-work" },
  { id: "laptop", label: "@laptop" },
];

const sourceTasks: Record<ViewId, Task[]> = {
  next: [
    { id: "n1", title: "Draft the launch announcement", project: "Onboarding revamp", context: "@deep-work", state: "working" },
    { id: "n2", title: "Call the dentist to reschedule", project: "No project", context: "@calls", due: "before Fri" },
    { id: "n3", title: "Choose a venue for the offsite", project: "Team offsite", state: "needs-you" },
    { id: "n4", title: "Review Q3 pricing assumptions", project: "Pricing", context: "@deep-work", state: "thinking" },
    { id: "n5", title: "Write the onboarding email sequence", project: "Onboarding revamp", context: "@laptop", state: "offer" },
    { id: "n6", title: "Buy stamps", project: "No project", context: "@errands" },
  ],
  inbox: [
    { id: "i1", title: "Figure out what to do about the flaky signup emails", project: "Inbox" },
    { id: "i2", title: "Sarah mentioned a grant deadline — check it", project: "Inbox" },
    { id: "i3", title: "Idea: sample data preinstalled on signup", project: "Inbox" },
    { id: "i4", title: "Renew passport?", project: "Inbox" },
  ],
  waiting: [
    { id: "t2", title: "Contract redlines from the venue", project: "Team offsite", note: "sent Tue" },
    { id: "p2", title: "Compare-plans research", project: "Pricing", state: "review" },
  ],
  someday: [
    { id: "s1", title: "Learn enough SQL to stop asking Priya", project: "No project" },
    { id: "s2", title: "Rework the pricing page illustrations", project: "No project" },
    { id: "s3", title: "Company book club", project: "No project" },
  ],
  review: [],
  onboarding: [
    { id: "n1", title: "Draft the launch announcement", project: "Onboarding revamp", context: "@deep-work", state: "working" },
    { id: "n5", title: "Write the onboarding email sequence", project: "Onboarding revamp", context: "@laptop", state: "offer" },
  ],
  pricing: [
    { id: "n4", title: "Review Q3 pricing assumptions", project: "Pricing", context: "@deep-work", state: "thinking" },
    { id: "p2", title: "Compare-plans research", project: "Pricing", state: "review" },
  ],
  offsite: [
    { id: "n3", title: "Choose a venue for the offsite", project: "Team offsite", state: "needs-you" },
    { id: "t2", title: "Contract redlines from the venue", project: "Team offsite", note: "sent Tue" },
  ],
  billing: [],
  calls: [{ id: "n2", title: "Call the dentist to reschedule", project: "No project", context: "@calls", due: "before Fri" }],
  errands: [{ id: "e1", title: "Buy stamps", project: "No project", context: "@errands" }],
  "deep-work": [
    { id: "n1", title: "Draft the launch announcement", project: "Onboarding revamp", context: "@deep-work", state: "working" },
    { id: "n4", title: "Review Q3 pricing assumptions", project: "Pricing", context: "@deep-work", state: "thinking" },
  ],
  laptop: [{ id: "n5", title: "Write the onboarding email sequence", project: "Onboarding revamp", context: "@laptop", state: "offer" }],
};

const paneMeta: Partial<Record<ViewId, string>> = {
  inbox: "4 unprocessed tasks",
  waiting: "2 tasks waiting on someone else",
  someday: "3 tasks you may want to revisit",
  onboarding: "6 tasks · 1 running on AI",
  pricing: "4 tasks",
  offsite: "3 tasks · 1 needs you",
  billing: "2 tasks",
  calls: "1 task across your lists",
  errands: "1 task across your lists",
  "deep-work": "2 tasks across your lists",
  laptop: "1 task across your lists",
};

const sourceCountBaselines: Partial<Record<ViewId, number>> = {
  inbox: 4,
  next: 6,
  waiting: 2,
  someday: 3,
  onboarding: 6,
  pricing: 4,
  offsite: 3,
  billing: 2,
  calls: 1,
  errands: 1,
  "deep-work": 2,
  laptop: 1,
};

function titleFor(view: ViewId): string {
  if (view === "next") return "Next actions";
  if (view === "review") return "Weekly review";
  return [...navItems, ...projects, ...contexts].find((item) => item.id === view)?.label ?? "Next actions";
}

function stateLabel(state?: TaskState): string | null {
  if (!state || state === "default") return null;
  return state === "needs-you"
    ? "Needs you — choose a venue"
    : state === "thinking"
      ? "Thinking · 12 steps"
      : state === "working"
        ? "Drafter · ready in ~5 min"
        : state === "review"
          ? "Ready for review"
          : "AI can draft";
}

function TaskCard({
  task,
  completed,
  onToggle,
  showProject,
  compact,
  expanded,
  onExpand,
}: {
  task: Task;
  completed: boolean;
  onToggle: () => void;
  showProject: boolean;
  compact: boolean;
  expanded: boolean;
  onExpand: () => void;
}): JSX.Element {
  const state = task.state ?? "default";
  const isAgentTask = state === "working" || state === "review" || state === "offer";
  return (
    <article className={`task-card task-card--${state} ${compact ? "is-compact" : ""} ${completed ? "is-completed" : ""} ${expanded ? "is-expanded" : ""}`}>
      <div className="task-card__row">
        <input aria-label={`Complete ${task.title}`} checked={completed} className="task-check" onChange={onToggle} type="checkbox" />
        <span className="task-card__title">{task.title}</span>
        <div className="task-card__chips">
          {stateLabel(state) && (state === "thinking" || state === "review" || state === "offer" ? <button aria-expanded={expanded} className={`task-chip task-chip--${state}`} onClick={onExpand} type="button"><span className="task-chip__dot" />{stateLabel(state)}</button> : <span className={`task-chip task-chip--${state}`}><span className={state !== "needs-you" ? "task-chip__dot" : ""} />{stateLabel(state)}</span>)}
          {isAgentTask && <span aria-label={`AI working on ${task.title}`} className="task-agent"><Sparkles size={14} /></span>}
          {task.due && <span className="task-chip task-chip--due">{task.due}</span>}
          {task.context && <span className="task-chip">{task.context}</span>}
          {state === "needs-you" && <button className="task-needs-action" onClick={onExpand} type="button">Choose one</button>}
        </div>
        {showProject && task.project !== "No project" && <span className="task-card__project">{task.project}</span>}
      </div>
      {task.note && <p className="task-card__note">{task.note}</p>}
      {expanded && <TaskDetail state={state} />}
    </article>
  );
}

function TaskDetail({ state }: { state: TaskState }): JSX.Element {
  return (
    <section className="task-detail" aria-label="Task details">
      <div className="task-detail__section"><strong>Subtasks</strong><label><input checked readOnly type="checkbox" /> Read the supporting notes</label><label><input type="checkbox" /> Share a concise update</label><input aria-label="Add a subtask" className="task-detail__input" placeholder="+ Add a subtask" /></div>
      <div className="task-detail__section"><strong>Run log</strong><div className="run-log"><span className="run-log__done" /> Brief created <time>10:24</time></div><div className="run-log"><span className="run-log__current" /> Agent is checking context <time>Now</time></div><div className="run-log"><span className="run-log__upcoming" /> Handoff scheduled <time>Upcoming</time></div></div>
      <div className="needs-you"><CircleHelp size={16} /><span>Which venue should be prioritized for the team?</span><button type="button">Choose</button></div>
      <div className="agent-offer"><LoaderCircle size={16} /><span>Brain Buddy has a proposed handoff ready for you.</span><button type="button">Review</button></div>
      <a className="artifact-link" href="#task-artifact"><FileText size={14} /> Open task artifact</a>
      <div className="comment"><span className="comment__avatar">TS</span><div><strong>Tom</strong><p>I added the key context here for review.</p></div></div>
      <button className="add-comment" type="button">+ Add a comment</button>
    </section>
  );
}

function BrainDumpOverlay({ onClose, onSend, initialState }: { onClose: () => void; onSend: () => void; initialState: BrainDumpState }): JSX.Element {
  const [state] = useState<BrainDumpState>(initialState);
  const [items, setItems] = useState(["Follow up on the new pricing notes"]);
  const panelRef = useRef<HTMLDivElement>(null);
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const returnFocusRef = useRef<HTMLElement | null>(document.activeElement as HTMLElement | null);
  const remove = (index: number) => setItems((current) => current.filter((_, itemIndex) => itemIndex !== index));

  useEffect(() => {
    closeButtonRef.current?.focus();
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onClose();
        return;
      }
      if (event.key !== "Tab") return;
      const focusable = Array.from(panelRef.current?.querySelectorAll<HTMLElement>("button, [href], input, select, textarea, [tabindex]:not([tabindex='-1'])") ?? []).filter((element) => !element.hasAttribute("disabled"));
      if (focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      returnFocusRef.current?.focus();
    };
  }, [onClose]);

  return (
    <div aria-modal="true" className="brain-dump-scrim" role="dialog" aria-label="Brain dump">
      <div className="brain-dump-panel" ref={panelRef}>
        {state === "review" ? (
          <><header className="brain-dump-header"><span className="brain-dump-mic"><Mic size={20} /></span><div><h2>Brain dump</h2><p>Review the tasks we found</p></div><button aria-label="Close brain dump" className="icon-button" onClick={onClose} ref={closeButtonRef} type="button"><X size={18} /></button></header><div className="brain-dump-review"><div className="brain-dump-review__head"><h3>Ready to send</h3><span>{items.length} task{items.length === 1 ? "" : "s"}</span></div><div className="brain-dump-review__grid">{items.map((item, index) => <div className="review-card" key={item}><input aria-label={`Task ${index + 1}`} defaultValue={item} /><button type="button">Add date</button><button aria-label={`Remove ${item}`} onClick={() => remove(index)} type="button"><X size={16} /></button></div>)}</div><footer><button className="text-button" onClick={onClose} type="button">Discard all</button><button className="primary-button" onClick={onSend} type="button"><Send size={15} /> Send to inbox</button></footer></div></>
        ) : (
          <div className="brain-dump-recording"><aside><span className="recording-mic"><Mic size={26} /></span><h2>Brain dump</h2><p>Speak freely — tasks are extracted as you go</p><div className="recording-status"><span /><time>0:00</time></div><div className="recording-spacer" /><div className="transcript-caret" aria-hidden="true" /><div className="waveform" aria-label="Recording waveform">▁▃▅▂▆▄▇▃▅▂</div><button className="primary-button" onClick={onClose} type="button">Stop</button><p>Nothing is saved until you stop</p></aside><section className="captured-tasks"><button aria-label="Close brain dump" className="icon-button brain-dump-recording__close" onClick={onClose} ref={closeButtonRef} type="button"><X size={18} /></button>{state === "captured" ? <><p className="transcript"><span>“</span> I should follow up on the new pricing notes and check in with Maya.</p><div className="captured-card"><span className="captured-card__label">Captured task</span><strong>Follow up on the new pricing notes</strong></div><div className="forming-card"><span className="task-chip__dot" /> Forming another task…</div></> : <><strong className="captured-tasks__heading">HEADED TO INBOX · 0</strong><div className="no-captured-tasks"><p>Tasks appear here as you speak</p></div></>}</section></div>
        )}
      </div>
    </div>
  );
}

export default function TaskWorkspace(): JSX.Element {
  const [view, setView] = useState<ViewId>("next");
  const [grouped, setGrouped] = useState(false);

  const [completed, setCompleted] = useState<Record<string, boolean>>({});
  const [expanded, setExpanded] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [brainDumpOpen, setBrainDumpOpen] = useState(false);
  const [brainDumpState, setBrainDumpState] = useState<BrainDumpState>("recording");
  const [sentInboxTasks, setSentInboxTasks] = useState<Task[]>([]);
  const tasks = useMemo(
    () => (view === "inbox" ? [...sourceTasks.inbox, ...sentInboxTasks] : sourceTasks[view]),
    [sentInboxTasks, view]
  );
  const countFor = (target: ViewId): number => {
    if (target !== "next" && target !== "inbox") return sourceCountBaselines[target] ?? sourceTasks[target].length;
    const targetTasks = target === "inbox" ? [...sourceTasks.inbox, ...sentInboxTasks] : sourceTasks[target];
    const completedInTarget = targetTasks.filter((task) => completed[task.id]).length;
    return (sourceCountBaselines[target] ?? targetTasks.length) + (target === "inbox" ? sentInboxTasks.length : 0) - completedInTarget;
  };
  const metadataFor = (target: ViewId): string | undefined => {
    const count = countFor(target);
    if (target === "next") return `${count} tasks${completed.n1 ? "" : " · 1 running on AI"}`;
    if (target === "inbox") return undefined;
    if (target === "onboarding") return "6 tasks · 1 running on AI";
    if (target === "offsite") return "3 tasks · 1 needs you";
    if (target === "pricing" || target === "billing" || target === "waiting" || target === "someday") return `${count} tasks`;
    return paneMeta[target];
  };
  const isProject = projects.some((project) => project.id === view);
  const isContext = contexts.some((context) => context.id === view);
  const showProject = view === "next" || view === "waiting";
  const selectView = (nextView: ViewId) => { setView(nextView); setExpanded(null); setGrouped(false); };
  const showToast = (message: string) => { setToast(message); window.setTimeout(() => setToast(null), 2500); };
  const showPlaceholder = (what: string) => showToast(`${what} isn't built yet — placeholder`);
  const groupedTasks = Object.entries(tasks.reduce<Record<string, Task[]>>((result, task) => { (result[task.project] ??= []).push(task); return result; }, {}));

  useEffect(() => {
    const showBrainDumpState = (event: Event) => {
      const state = (event as CustomEvent<BrainDumpState>).detail;
      if (state !== "recording" && state !== "captured" && state !== "review") return;
      setBrainDumpState(state);
      setBrainDumpOpen(true);
    };
    window.addEventListener("brainbuddy:brain-dump-state", showBrainDumpState);
    return () => window.removeEventListener("brainbuddy:brain-dump-state", showBrainDumpState);
  }, []);

  return (
    <main className="task-workspace">
      <header className="task-topbar"><div className="brand"><Sprout size={22} /><span>Brain Buddy</span></div><label className="task-search"><Search size={15} /><input onKeyDown={(event) => event.key === "Enter" && showPlaceholder("Search")} placeholder="Search tasks and trees" /></label><div className="task-topbar__right"><button className="brain-dump-button" onClick={() => { setBrainDumpState("recording"); setBrainDumpOpen(true); }} type="button"><Mic size={15} /> Brain dump</button><button aria-label="Account" className="avatar-button" onClick={() => showPlaceholder("Account menu")}>TS</button></div></header>
      <div className="task-workspace__body">
        <aside className="task-sidebar" aria-label="Task navigation">
          <nav>{navItems.map(({ id, label, icon: Icon }) => <button aria-current={view === id ? "page" : undefined} className={`sidebar-item ${view === id ? "is-selected" : ""}`} key={id} onClick={() => selectView(id)} type="button"><Icon size={16} /><span>{label}</span>{id === "inbox" ? <b className="inbox-count">{countFor(id)}</b> : id === "review" ? <b className="review-due">due Sun</b> : <em>{countFor(id)}</em>}</button>)}</nav>
          <section className="sidebar-section"><div className="sidebar-section__title"><span>Projects</span><button aria-label="New project" className="icon-button" onClick={() => showPlaceholder("New project")} type="button"><Plus size={15} /></button></div>{projects.map((project) => <button aria-current={view === project.id ? "page" : undefined} className={`sidebar-item sidebar-project ${view === project.id ? "is-selected" : ""}`} key={project.id} onClick={() => selectView(project.id)} type="button"><i style={{ background: project.color }} /><span>{project.label}</span><em>{countFor(project.id)}</em></button>)}</section>
          <section className="sidebar-section"><div className="sidebar-section__title"><span>Contexts</span></div><div className="context-pills">{contexts.map((context) => <button aria-current={view === context.id ? "page" : undefined} className={view === context.id ? "is-selected" : ""} key={context.id} onClick={() => selectView(context.id)} type="button">{context.label}</button>)}</div></section>
        </aside>
        <section className="task-content">
          {view === "review" ? (
            <WeeklyReview />
          ) : (
            <>
              <header className="pane-header">
                <div><h1>{titleFor(view)}</h1><p>{metadataFor(view)}</p></div>
                <div className="pane-actions">
                  {(view === "next" || view === "waiting") && <button aria-pressed={grouped} className="secondary-button" onClick={() => setGrouped((current) => !current)} type="button"><Menu size={15} /> Group by project</button>}
                  {isProject && <button className="secondary-button" onClick={() => showPlaceholder("Think")} type="button">Think</button>}
                  {(view === "next" || view === "inbox" || view === "waiting" || view === "someday") && <button className="secondary-button" onClick={() => showPlaceholder("Sorting")} type="button">Sort <ChevronDown size={15} /></button>}
                </div>
              </header>
              {view === "inbox" && <div className="inbox-hint">Process these — decide the next action for each.</div>}
              {grouped ? (
                <div className="grouped-list">{groupedTasks.map(([project, group]) => <section className="task-group" key={project}><h2><i />{project}<span>{group.length}</span></h2>{group.map((task) => <TaskCard compact={false} completed={Boolean(completed[task.id])} expanded={expanded === task.id} key={task.id} onExpand={() => setExpanded(expanded === task.id ? null : task.id)} onToggle={() => setCompleted((items) => ({ ...items, [task.id]: !items[task.id] }))} showProject={false} task={task} />)}</section>)}</div>
              ) : (
                <div className="task-list">{tasks.map((task) => <TaskCard compact={false} completed={Boolean(completed[task.id])} expanded={expanded === task.id} key={task.id} onExpand={() => setExpanded(expanded === task.id ? null : task.id)} onToggle={() => setCompleted((items) => ({ ...items, [task.id]: !items[task.id] }))} showProject={showProject} task={task} />)}</div>
              )}
              {!isContext && <button className="add-task" type="button"><Plus size={16} /> {view === "next" ? "Add a next action — or dump everything on your mind with the mic above" : isProject ? "Add a task to this project" : "Add a task"}</button>}
            </>
          )}
        </section>
      </div>
      {toast && <div className="workspace-toast" role="status">{toast}</div>}
      {brainDumpOpen && <BrainDumpOverlay initialState={brainDumpState} key={brainDumpState} onClose={() => setBrainDumpOpen(false)} onSend={() => { setBrainDumpOpen(false); setSentInboxTasks((current) => [...current, { id: `inbox-sent-${current.length + 1}`, title: "Follow up on the new pricing notes", project: "Inbox" }]); selectView("inbox"); showToast("1 task sent to inbox"); }} />}
    </main>
  );
}

function WeeklyReview(): JSX.Element {
  return <div className="weekly-review"><span><RotateCcw size={26} /></span><h1>Weekly review</h1><p>A guided pass over your lists — empty the inbox, refresh next actions, decide on the somedays. Due Sunday.</p><b>PLACEHOLDER — NOT DESIGNED YET</b></div>;
}
