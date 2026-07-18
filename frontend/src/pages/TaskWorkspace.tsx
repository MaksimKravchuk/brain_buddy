import { useMemo, useState } from "react";
import {
  BellRing,
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
  MoreHorizontal,
  Plus,
  RotateCcw,
  Search,
  Send,
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

type TaskState = "default" | "working" | "review" | "offer" | "needs-you";

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
    { id: "n4", title: "Review Q3 pricing assumptions", project: "Pricing", context: "@deep-work", state: "review" },
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
    { id: "w1", title: "Contract redlines from the venue", project: "Team offsite", note: "sent Tue" },
    { id: "w2", title: "Compare-plans research", project: "Pricing", state: "review" },
  ],
  someday: [
    { id: "s1", title: "Learn enough SQL to stop asking Priya", project: "No project" },
    { id: "s2", title: "Rework the pricing page illustrations", project: "No project" },
    { id: "s3", title: "Company book club", project: "No project" },
  ],
  review: [],
  onboarding: [
    { id: "o1", title: "Draft the launch announcement", project: "Onboarding revamp", context: "@deep-work", state: "working" },
    { id: "o2", title: "Write the onboarding email sequence", project: "Onboarding revamp", context: "@laptop", state: "offer" },
  ],
  pricing: [
    { id: "p1", title: "Review Q3 pricing assumptions", project: "Pricing", context: "@deep-work", state: "review" },
  ],
  offsite: [
    { id: "t1", title: "Choose a venue for the offsite", project: "Team offsite", state: "needs-you" },
  ],
  billing: [],
  calls: [{ id: "c1", title: "Call the dentist to reschedule", project: "No project", context: "@calls", due: "before Fri" }],
  errands: [{ id: "e1", title: "Buy stamps", project: "No project", context: "@errands" }],
  "deep-work": [
    { id: "d1", title: "Draft the launch announcement", project: "Onboarding revamp", context: "@deep-work", state: "working" },
    { id: "d2", title: "Review Q3 pricing assumptions", project: "Pricing", context: "@deep-work", state: "review" },
  ],
  laptop: [{ id: "l1", title: "Write the onboarding email sequence", project: "Onboarding revamp", context: "@laptop", state: "offer" }],
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

function titleFor(view: ViewId): string {
  if (view === "next") return "Next actions";
  if (view === "review") return "Weekly review";
  return [...navItems, ...projects, ...contexts].find((item) => item.id === view)?.label ?? "Next actions";
}

function stateLabel(state?: TaskState): string | null {
  if (!state || state === "default") return null;
  return state === "needs-you" ? "Needs you" : state === "working" ? "Working" : state === "review" ? "Ready for review" : "Offer ready";
}

function TaskCard({
  task,
  completed,
  onToggle,
  showProject,
  expanded,
  onExpand,
}: {
  task: Task;
  completed: boolean;
  onToggle: () => void;
  showProject: boolean;
  expanded: boolean;
  onExpand: () => void;
}): JSX.Element {
  const state = task.state ?? "default";
  return (
    <article className={`task-card task-card--${state} ${completed ? "is-completed" : ""} ${expanded ? "is-expanded" : ""}`}>
      <div className="task-card__row">
        <input aria-label={`Complete ${task.title}`} checked={completed} className="task-check" onChange={onToggle} type="checkbox" />
        <button aria-expanded={expanded} className="task-card__title" onClick={onExpand} type="button">
          {task.title}
        </button>
        <div className="task-card__chips">
          {task.context && <span className="task-chip">{task.context}</span>}
          {task.due && <span className="task-chip task-chip--due">{task.due}</span>}
          {stateLabel(state) && <span className={`task-chip task-chip--${state}`}><span className={state !== "needs-you" ? "task-chip__dot" : ""} />{stateLabel(state)}</span>}
        </div>
        {showProject && <span className="task-card__project">{task.project}</span>}
        <button aria-label={`More options for ${task.title}`} className="icon-button task-card__more" type="button"><MoreHorizontal size={17} /></button>
      </div>
      {task.note && <p className="task-card__note">{task.note}</p>}
      {expanded && <TaskDetail state={state} />}
    </article>
  );
}

function TaskDetail({ state }: { state: TaskState }): JSX.Element {
  return (
    <section className="task-detail" aria-label="Task details">
      <div className="task-detail__section"><strong>Subtasks</strong><label><input type="checkbox" /> Read the supporting notes</label><label><input type="checkbox" /> Share a concise update</label><input aria-label="Add a subtask" className="task-detail__input" placeholder="+ Add a subtask" /></div>
      <div className="task-detail__section"><strong>Run log</strong><div className="run-log"><span className="run-log__done" /> Brief created <time>10:24</time></div><div className="run-log"><span className="run-log__current" /> Agent is checking context <time>Now</time></div></div>
      {state === "needs-you" && <div className="needs-you"><CircleHelp size={16} /><span>Which venue should be prioritized for the team?</span><button type="button">Choose</button></div>}
      {(state === "working" || state === "offer") && <div className="agent-offer"><LoaderCircle size={16} /><span>Brain Buddy has a proposed handoff ready for you.</span><button type="button">Review</button></div>}
      <a className="artifact-link" href="#task-artifact"><FileText size={14} /> Open task artifact</a>
      <div className="comment"><span className="comment__avatar">TS</span><div><strong>Tom</strong><p>I added the key context here for review.</p></div></div>
      <button className="add-comment" type="button">+ Add a comment</button>
    </section>
  );
}

function BrainDumpOverlay({ onClose, onSend }: { onClose: () => void; onSend: () => void }): JSX.Element {
  const [reviewing, setReviewing] = useState(false);
  const [items, setItems] = useState(["Follow up on the new pricing notes"]);
  const remove = (index: number) => setItems((current) => current.filter((_, itemIndex) => itemIndex !== index));

  return (
    <div aria-modal="true" className="brain-dump-scrim" role="dialog" aria-label="Brain dump">
      <div className="brain-dump-panel">
        <header className="brain-dump-header"><span className="brain-dump-mic"><Mic size={20} /></span><div><h2>Brain dump</h2><p>{reviewing ? "Review the tasks we found" : "Talk it out — we will turn it into clear next actions"}</p></div><button aria-label="Close brain dump" className="icon-button" onClick={onClose} type="button"><X size={18} /></button></header>
        {reviewing ? (
          <div className="brain-dump-review"><div className="brain-dump-review__head"><h3>Ready to send</h3><span>{items.length} task{items.length === 1 ? "" : "s"}</span></div><div className="brain-dump-review__grid">{items.map((item, index) => <div className="review-card" key={item}><input aria-label={`Task ${index + 1}`} defaultValue={item} /><button type="button">Add date</button><button aria-label={`Remove ${item}`} onClick={() => remove(index)} type="button"><X size={16} /></button></div>)}</div><footer><button className="text-button" onClick={onClose} type="button">Discard all</button><button className="primary-button" onClick={onSend} type="button"><Send size={15} /> Send to inbox</button></footer></div>
        ) : (
          <div className="brain-dump-recording"><aside><span className="recording-mic"><Mic size={26} /></span><div className="recording-status"><span /> Recording <time>0:14</time></div><p>Say what is on your mind. We will keep the useful parts.</p><div className="waveform" aria-label="Recording waveform">▁▃▅▂▆▄▇▃▅▂</div><div className="recording-spacer" /><button className="secondary-button" onClick={() => setReviewing(true)} type="button">Stop</button><button className="primary-button" onClick={() => setReviewing(true)} type="button"><Send size={15} /> Stop &amp; send</button></aside><section className="captured-tasks"><p className="transcript"><span>“</span> I should follow up on the new pricing notes and check in with Maya.</p><div className="captured-card"><span className="captured-card__label">Captured task</span><strong>Follow up on the new pricing notes</strong></div><div className="forming-card"><span className="task-chip__dot" /> Forming another task…</div></section></div>
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
  const [sentInboxTask, setSentInboxTask] = useState(false);
  const tasks = useMemo(() => sourceTasks[view], [view]);
  const visibleInboxCount = sourceTasks.inbox.length - Object.entries(completed).filter(([id, value]) => value && id.startsWith("i")).length + (sentInboxTask ? 1 : 0);
  const isProject = projects.some((project) => project.id === view);
  const isContext = contexts.some((context) => context.id === view);
  const showProject = view === "next" || isContext || view === "waiting";
  const selectView = (nextView: ViewId) => { setView(nextView); setExpanded(null); setGrouped(false); };
  const showToast = (message: string) => { setToast(message); window.setTimeout(() => setToast(null), 2500); };
  const showPlaceholder = (what: string) => showToast(`${what} isn't built yet — placeholder`);
  const groupedTasks = Object.entries(tasks.reduce<Record<string, Task[]>>((result, task) => { (result[task.project] ??= []).push(task); return result; }, {}));

  return (
    <main className="task-workspace">
      <header className="task-topbar"><div className="brand"><Sprout size={22} /><span>Brain Buddy</span></div><label className="task-search"><Search size={15} /><input onKeyDown={(event) => event.key === "Enter" && showPlaceholder("Search")} placeholder="Search tasks and trees" /><kbd>⌘ K</kbd></label><div className="task-topbar__right"><button className="brain-dump-button" onClick={() => setBrainDumpOpen(true)} type="button"><Mic size={15} /> Brain dump</button><button aria-label="Account" className="avatar-button" onClick={() => showPlaceholder("Account menu")}>TS</button></div></header>
      <div className="task-workspace__body">
        <aside className="task-sidebar" aria-label="Task navigation">
          <nav>{navItems.map(({ id, label, count, icon: Icon }) => <button aria-current={view === id ? "page" : undefined} className={`sidebar-item ${view === id ? "is-selected" : ""}`} key={id} onClick={() => selectView(id)} type="button"><Icon size={16} /><span>{label}</span>{id === "inbox" ? <b className="inbox-count">{visibleInboxCount}</b> : id === "review" ? <b className="review-due">Due Sunday</b> : count ? <em>{count}</em> : null}</button>)}</nav>
          <section className="sidebar-section"><div className="sidebar-section__title"><span>Projects</span><button aria-label="New project" className="icon-button" onClick={() => showPlaceholder("New project")} type="button"><Plus size={15} /></button></div>{projects.map((project) => <button aria-current={view === project.id ? "page" : undefined} className={`sidebar-item sidebar-project ${view === project.id ? "is-selected" : ""}`} key={project.id} onClick={() => selectView(project.id)} type="button"><i style={{ background: project.color }} /><span>{project.label}</span><em>{project.count}</em></button>)}</section>
          <section className="sidebar-section"><div className="sidebar-section__title"><span>Contexts</span></div><div className="context-pills">{contexts.map((context) => <button aria-current={view === context.id ? "page" : undefined} className={view === context.id ? "is-selected" : ""} key={context.id} onClick={() => selectView(context.id)} type="button">{context.label}</button>)}</div></section>
        </aside>
        <section className="task-content">
          {view === "review" ? (
            <WeeklyReview />
          ) : (
            <>
              <header className="pane-header">
                <div><h1>{titleFor(view)}</h1><p>{view === "next" ? "6 tasks across your active projects" : paneMeta[view]}</p></div>
                <div className="pane-actions">
                  {view === "next" && <button aria-pressed={grouped} className="secondary-button" onClick={() => setGrouped((current) => !current)} type="button"><Menu size={15} /> Group by project</button>}
                  <button aria-label="Sort tasks" className="secondary-button" onClick={() => showPlaceholder("Sorting")} type="button">Sort <ChevronDown size={15} /></button>
                </div>
              </header>
              {view === "inbox" && <div className="inbox-hint"><Inbox size={16} /> These are unprocessed thoughts. Decide what each one means before it gets lost.</div>}
              {grouped ? (
                <div className="grouped-list">{groupedTasks.map(([project, group]) => <section className="task-group" key={project}><h2><i />{project}<span>{group.length}</span></h2>{group.map((task) => <TaskCard completed={Boolean(completed[task.id])} expanded={expanded === task.id} key={task.id} onExpand={() => setExpanded(expanded === task.id ? null : task.id)} onToggle={() => setCompleted((items) => ({ ...items, [task.id]: !items[task.id] }))} showProject={false} task={task} />)}</section>)}</div>
              ) : (
                <div className="task-list">{tasks.map((task) => <TaskCard completed={Boolean(completed[task.id])} expanded={expanded === task.id} key={task.id} onExpand={() => setExpanded(expanded === task.id ? null : task.id)} onToggle={() => setCompleted((items) => ({ ...items, [task.id]: !items[task.id] }))} showProject={showProject} task={task} />)}</div>
              )}
              {view !== "billing" && <button className="add-task" type="button"><Plus size={16} /> {view === "next" ? "Add a next action — or dump everything on your mind with the mic above" : "Add a task"}</button>}
            </>
          )}
        </section>
      </div>
      {toast && <div className="workspace-toast" role="status">{toast}</div>}
      {brainDumpOpen && <BrainDumpOverlay onClose={() => setBrainDumpOpen(false)} onSend={() => { setBrainDumpOpen(false); setSentInboxTask(true); selectView("inbox"); showToast("1 task sent to inbox"); }} />}
    </main>
  );
}

function WeeklyReview(): JSX.Element {
  return <div className="weekly-review"><span><RotateCcw size={26} /></span><h1>Weekly review</h1><p>A guided pass to help you reset, notice what matters, and prepare for the week ahead. <strong>Due Sunday</strong></p><b>Coming later</b></div>;
}
