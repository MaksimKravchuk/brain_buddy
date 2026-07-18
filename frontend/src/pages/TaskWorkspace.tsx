import { useEffect, useMemo, useRef, useState } from "react";
import {
  Archive,
  ArrowRight,
  ArrowUpDown,
  Calendar,
  Check,
  Clock,
  Inbox as InboxIcon,
  Layers2,
  Mic,
  Network,
  Plus,
  RotateCcw,
  Search,
  Square,
  X,
} from "lucide-react";

import "./TaskWorkspace.css";

/* ------------------------------------------------------------------ */
/* Types — mirror the authoritative CloudDesign demo data shape       */
/* ------------------------------------------------------------------ */

type ListId = "inbox" | "next" | "waiting" | "someday";
type AiState = "working" | "needs-you" | "review" | "offer";

type LogStep =
  | { s: "done" | "current" | "up"; text: string; time?: string; artifact?: string }
  | { kind: "ask"; text: string; actions: string[] };

type Subtask = { t: string; done: boolean };
type Comment = { who: string; ini: string; time: string; text: string };

type Task = {
  id: string;
  list: ListId;
  title: string;
  ai?: AiState;
  agent?: string;
  aiMeta?: string;
  actions?: string[];
  project?: string;
  context?: string;
  due?: string;
  waitingOn?: string;
  thinking?: number;
  subtasks?: Subtask[];
  log?: LogStep[];
  comments?: Comment[];
};

type Project = { id: string; name: string; color: string; meta: string };

type View =
  | { kind: "list"; id: ListId }
  | { kind: "review" }
  | { kind: "project"; id: string }
  | { kind: "context"; id: string };

/* ------------------------------------------------------------------ */
/* Demo data — literal port of app/bb-app.jsx (BB_PROJECTS/BB_TASKS)   */
/* ------------------------------------------------------------------ */

const BB_PROJECTS: Project[] = [
  { id: "p1", name: "Onboarding revamp", color: "#6366f1", meta: "6 tasks · 1 running on AI" },
  { id: "p2", name: "Pricing", color: "#0ea5e9", meta: "4 tasks" },
  { id: "p3", name: "Team offsite", color: "#f59e0b", meta: "3 tasks · 1 needs you" },
  { id: "p4", name: "Migrate billing to the new usage-based pricing model", color: "#10b981", meta: "2 tasks" },
];

const BB_CONTEXTS = ["@calls", "@errands", "@deep-work", "@laptop"];

const BB_TASKS: Task[] = [
  { id: "i1", list: "inbox", title: "Figure out what to do about the flaky signup emails" },
  { id: "i2", list: "inbox", title: "Sarah mentioned a grant deadline — check it" },
  { id: "i3", list: "inbox", title: "Idea: sample data preinstalled on signup" },
  { id: "i4", list: "inbox", title: "Renew passport?" },

  {
    id: "n1",
    list: "next",
    title: "Draft the launch announcement",
    ai: "working",
    agent: "Drafter",
    aiMeta: "ready in ~5 min",
    project: "Onboarding revamp",
    context: "@deep-work",
    subtasks: [
      { t: "Outline the announcement", done: true },
      { t: "Review Drafter's draft", done: false },
    ],
    log: [
      { s: "done", text: "Read the task and project notes", time: "12:04" },
      { s: "done", text: "Searched 14 sources", time: "12:06" },
      { s: "current", text: "Drafting outline" },
      { s: "up", text: "Write full draft" },
    ],
    comments: [{ who: "Priya", ini: "PK", time: "2h", text: "Keep it under 300 words." }],
  },
  { id: "n2", list: "next", title: "Call the dentist to reschedule", due: "before Fri", context: "@calls" },
  {
    id: "n3",
    list: "next",
    title: "Choose a venue for the offsite",
    ai: "needs-you",
    agent: "Scheduler",
    aiMeta: "choose a venue",
    actions: ["Choose one"],
    project: "Team offsite",
    log: [
      { s: "done", text: "Shortlisted 3 venues", time: "09:12" },
      { kind: "ask", text: "Asked you to choose a venue", actions: ["Choose one"] },
    ],
  },
  { id: "n4", list: "next", title: "Review Q3 pricing assumptions", thinking: 12, project: "Pricing", context: "@deep-work" },
  { id: "n5", list: "next", title: "Write the onboarding email sequence", ai: "offer", project: "Onboarding revamp", context: "@laptop" },
  { id: "n6", list: "next", title: "Buy stamps", context: "@errands" },

  { id: "w1", list: "waiting", title: "Contract redlines from the venue", waitingOn: "sent Tue", project: "Team offsite" },
  {
    id: "w2",
    list: "waiting",
    title: "Compare-plans research",
    ai: "review",
    agent: "Researcher",
    project: "Pricing",
    log: [
      { s: "done", text: "Searched 14 sources", time: "Tue" },
      { s: "done", text: "Drafted comparison", time: "Tue", artifact: "Comparison v2" },
      { s: "done", text: "Ready for review", time: "Tue" },
    ],
  },

  { id: "s1", list: "someday", title: "Learn enough SQL to stop asking Priya" },
  { id: "s2", list: "someday", title: "Rework the pricing page illustrations" },
  { id: "s3", list: "someday", title: "Company book club" },
];

const BB_LISTS: Record<ListId, { title: string; icon: typeof InboxIcon; hint?: string }> = {
  inbox: { title: "Inbox", icon: InboxIcon, hint: "Process these — decide the next action for each." },
  next: { title: "Next actions", icon: ArrowRight },
  waiting: { title: "Waiting for", icon: Clock },
  someday: { title: "Someday / maybe", icon: Archive },
};

let newIdCounter = 0;
const nextId = (prefix: string) => `${prefix}${++newIdCounter}`;

function groupTasksByProject(list: Task[]): { name: string; color: string | null; tasks: Task[] }[] {
  const groups: { name: string; color: string | null; tasks: Task[] }[] = [];
  const byName: Record<string, { name: string; color: string | null; tasks: Task[] }> = {};
  list.forEach((task) => {
    const name = task.project || "No project";
    if (!byName[name]) {
      const proj = BB_PROJECTS.find((p) => p.name === name);
      byName[name] = { name, color: proj ? proj.color : null, tasks: [] };
      groups.push(byName[name]);
    }
    byName[name].tasks.push(task);
  });
  groups.sort((a, b) => Number(a.name === "No project") - Number(b.name === "No project"));
  return groups;
}

/* ------------------------------------------------------------------ */
/* Small presentational primitives                                    */
/* ------------------------------------------------------------------ */

function Button({
  variant = "primary",
  size = "md",
  leftIcon,
  className = "",
  children,
  ...rest
}: {
  variant?: "primary" | "secondary" | "ghost" | "emerald";
  size?: "sm" | "md";
  leftIcon?: React.ReactNode;
  className?: string;
} & React.ButtonHTMLAttributes<HTMLButtonElement>): JSX.Element {
  return (
    <button
      type="button"
      {...rest}
      className={`bb-btn bb-btn-${variant} bb-btn-${size} ${!children ? "bb-btn-icon" : ""} ${className}`}
    >
      {leftIcon}
      {children ? <span>{children}</span> : null}
    </button>
  );
}

function Chip({
  variant = "neutral",
  icon,
  dot,
  pulse,
  onClick,
  children,
}: {
  variant?: "neutral" | "due" | "ai" | "thinking" | "needs-you";
  icon?: React.ReactNode;
  dot?: boolean;
  pulse?: boolean;
  onClick?: () => void;
  children: React.ReactNode;
}): JSX.Element {
  const cls = `task-chip v-${variant}${onClick ? " task-chip-btn" : ""}`;
  const inner = (
    <>
      {dot ? <span className={`task-dot${pulse ? " is-pulsing" : ""}`} /> : null}
      {icon}
      <span>{children}</span>
    </>
  );
  return onClick ? (
    <button type="button" className={cls} onClick={onClick}>
      {inner}
    </button>
  ) : (
    <span className={cls}>{inner}</span>
  );
}

function AgentAvatar({ title }: { title?: string }): JSX.Element {
  return (
    <span className="task-agent-avatar" title={title}>
      <SparkIcon size={12} />
    </span>
  );
}

function SparkIcon({ size = 11 }: { size?: number }): JSX.Element {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
      <path d="m12 3-1.9 5.8a2 2 0 0 1-1.3 1.3L3 12l5.8 1.9a2 2 0 0 1 1.3 1.3L12 21l1.9-5.8a2 2 0 0 1 1.3-1.3L21 12l-5.8-1.9a2 2 0 0 1-1.3-1.3Z" />
    </svg>
  );
}

/* ------------------------------------------------------------------ */
/* Task detail (expanded row) — subtasks / agent zone / comments      */
/* ------------------------------------------------------------------ */

function SubtasksSection({ task }: { task: Task }): JSX.Element {
  const [subs, setSubs] = useState<Subtask[]>(() => (task.subtasks ?? []).map((s) => ({ ...s })));
  const [adding, setAdding] = useState("");
  const toggle = (i: number) => setSubs((s) => s.map((x, j) => (j === i ? { ...x, done: !x.done } : x)));
  const add = () => {
    if (!adding.trim()) return;
    setSubs((s) => [...s, { t: adding.trim(), done: false }]);
    setAdding("");
  };
  return (
    <div className="task-detail-section">
      <span className="task-detail-label">Subtasks</span>
      {subs.map((s, i) => (
        <div key={i} className="task-subtask">
          <button
            type="button"
            className={`task-check-sm${s.done ? " is-checked" : ""}`}
            onClick={() => toggle(i)}
            aria-label="Toggle subtask"
          >
            <Check size={9} strokeWidth={3} />
          </button>
          <span className={s.done ? "task-subtask-done" : ""}>{s.t}</span>
        </div>
      ))}
      <input
        className="task-detail-input"
        placeholder="Add a subtask"
        value={adding}
        onChange={(e) => setAdding(e.target.value)}
        onKeyDown={(e) => e.key === "Enter" && add()}
      />
    </div>
  );
}

function AgentZoneSection({ task, onAction }: { task: Task; onAction: (what: string) => void }): JSX.Element {
  if (task.log) {
    return (
      <div className="task-detail-section">
        <span className="task-detail-label">Run log</span>
        <div className="task-log">
          {task.log.map((step, i) =>
            "kind" in step && step.kind === "ask" ? (
              <div key={i} className="task-log-ask">
                <div className="task-log-ask-text">{step.text}</div>
                <div className="task-inline-actions">
                  {step.actions.map((a) => (
                    <Button key={a} size="sm" variant="secondary" onClick={() => onAction(a)}>
                      {a}
                    </Button>
                  ))}
                </div>
              </div>
            ) : (
              <div key={i} className="task-log-step">
                <span className={`task-log-dot s-${"s" in step ? step.s : ""}`} />
                <span className="task-log-text">
                  {step.text}
                  {"artifact" in step && step.artifact ? (
                    <button type="button" className="task-artifact" onClick={() => onAction(step.artifact as string)}>
                      {step.artifact}
                    </button>
                  ) : null}
                </span>
                <span className="task-log-time">{"time" in step ? step.time ?? "" : ""}</span>
              </div>
            )
          )}
        </div>
      </div>
    );
  }
  return (
    <div className="task-detail-section">
      <span className="task-detail-label">Agent</span>
      <div className="task-agent-offer">
        <AgentAvatar />
        <span className="task-agent-offer-text">No agent on this task.</span>
        <span className="task-inline-actions">
          <Button size="sm" variant="emerald" onClick={() => onAction("Hand to agent")}>
            Hand to agent
          </Button>
          <Button size="sm" variant="secondary" onClick={() => onAction("Edit prompt & hand off")}>
            Edit prompt &amp; hand off
          </Button>
        </span>
      </div>
    </div>
  );
}

function CommentsSection({ task }: { task: Task }): JSX.Element {
  const [comments, setComments] = useState<Comment[]>(() => task.comments ?? []);
  const [draft, setDraft] = useState("");
  const send = () => {
    if (!draft.trim()) return;
    setComments((c) => [...c, { who: "You", ini: "TS", time: "now", text: draft.trim() }]);
    setDraft("");
  };
  return (
    <div className="task-detail-section">
      <span className="task-detail-label">Comments</span>
      {comments.map((c, i) => (
        <div key={i} className="task-comment">
          <span className="task-comment-avatar">{c.ini}</span>
          <div>
            <div className="task-comment-head">
              <b>{c.who}</b> <span className="task-log-time">{c.time}</span>
            </div>
            <div className="task-comment-text">{c.text}</div>
          </div>
        </div>
      ))}
      <input
        className="task-detail-input"
        placeholder="Add a comment"
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={(e) => e.key === "Enter" && send()}
      />
    </div>
  );
}

function TaskDetail({ task, onAction }: { task: Task; onAction: (what: string) => void }): JSX.Element {
  return (
    <section className="task-detail" aria-label="Task details">
      <SubtasksSection task={task} />
      <AgentZoneSection task={task} onAction={onAction} />
      <CommentsSection task={task} />
    </section>
  );
}

/* ------------------------------------------------------------------ */
/* Task row                                                            */
/* ------------------------------------------------------------------ */

function TaskRow({
  task,
  checked,
  onToggle,
  showProject,
  onChipClick,
  expanded,
  onExpand,
}: {
  task: Task;
  checked: boolean;
  onToggle: () => void;
  showProject: boolean;
  onChipClick: () => void;
  expanded: boolean;
  onExpand: () => void;
}): JSX.Element {
  const stateCls =
    (task.ai === "working" || task.ai === "review" || task.ai === "offer" ? " is-ai" : "") +
    (task.ai === "needs-you" ? " is-needs-you" : "") +
    (checked ? " is-done" : "");
  return (
    <article className={`task-card${stateCls}${expanded ? " is-expanded" : ""}`}>
      <div
        className="task-card-row"
        onClick={(e) => {
          const target = e.target as HTMLElement;
          if (target.closest("button") || target.closest("input")) return;
          onExpand();
        }}
      >
        <button
          type="button"
          className={`task-check${checked ? " is-checked" : ""}`}
          aria-label={checked ? `Mark ${task.title} not done` : `Complete ${task.title}`}
          onClick={onToggle}
        >
          <Check size={11} strokeWidth={3} />
        </button>
        <span className="task-card-title">{task.title}</span>
        <span className="task-card-chips">
          {task.due ? <Chip variant="due" icon={<Calendar size={11} />}>{task.due}</Chip> : null}
          {task.ai === "offer" ? (
            <Chip variant="ai" icon={<SparkIcon size={11} />} onClick={onChipClick}>
              AI can draft
            </Chip>
          ) : null}
          {task.ai === "working" ? (
            <Chip variant="ai" dot pulse>
              {task.agent} · {task.aiMeta}
            </Chip>
          ) : null}
          {task.ai === "review" ? (
            <Chip variant="ai" icon={<Check size={11} />} onClick={onChipClick}>
              Ready for review
            </Chip>
          ) : null}
          {task.ai === "needs-you" ? (
            <Chip variant="needs-you" dot>
              Needs you — {task.aiMeta}
            </Chip>
          ) : null}
          {task.thinking ? (
            <Chip variant="thinking" icon={<Network size={11} />} onClick={onExpand}>
              Thinking · {task.thinking} steps
            </Chip>
          ) : null}
        </span>
        <span className="task-card-right">
          {task.ai === "needs-you" && task.actions ? (
            <span className="task-inline-actions">
              {task.actions.map((a) => (
                <Button key={a} size="sm" variant="secondary" onClick={onChipClick}>
                  {a}
                </Button>
              ))}
            </span>
          ) : null}
          {task.agent && task.ai !== "offer" ? <AgentAvatar title={task.agent} /> : null}
          {task.waitingOn ? <span className="task-card-note">{task.waitingOn}</span> : null}
          {task.context ? <Chip variant="neutral">{task.context}</Chip> : null}
          {showProject ? <span className="task-card-project">{task.project || ""}</span> : null}
        </span>
      </div>
      {expanded ? <TaskDetail task={task} onAction={onChipClick} /> : null}
    </article>
  );
}

/* ------------------------------------------------------------------ */
/* Placeholder pane (Weekly review)                                    */
/* ------------------------------------------------------------------ */

function Placeholder({ icon, title, hint }: { icon: React.ReactNode; title: string; hint: string }): JSX.Element {
  return (
    <div className="task-placeholder">
      <div className="task-placeholder-icon">{icon}</div>
      <h2>{title}</h2>
      <p>{hint}</p>
      <span className="task-placeholder-tag">Placeholder — not designed yet</span>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Sidebar nav item                                                    */
/* ------------------------------------------------------------------ */

function NavItem({
  icon,
  label,
  active,
  onClick,
  trailing,
  wrap,
}: {
  icon: React.ReactNode;
  label: React.ReactNode;
  active?: boolean;
  onClick: () => void;
  trailing?: React.ReactNode;
  wrap?: boolean;
}): JSX.Element {
  return (
    <button
      type="button"
      className={`sidebar-item${active ? " is-selected" : ""}${wrap ? " is-wrap" : ""}`}
      aria-current={active ? "page" : undefined}
      onClick={onClick}
    >
      {icon}
      <span className="sidebar-item-label">{label}</span>
      {trailing}
    </button>
  );
}

/* ------------------------------------------------------------------ */
/* Brain Dump — literal port of app/bb-dump-core.jsx                  */
/* ------------------------------------------------------------------ */

type DumpTask = { title: string; due?: string; context?: string; ai?: AiState };

const BBD_SCRIPT: { text: string; forming?: string; task: DumpTask | null }[] = [
  {
    text: "Okay, so — first thing, I need to email the venue about catering for the offsite.",
    forming: "email the venue about catering…",
    task: { title: "Email the venue about catering" },
  },
  {
    text: "Sarah mentioned a grant deadline, I should check that before Thursday for sure.",
    forming: "check Sarah's grant deadline…",
    task: { title: "Check Sarah's grant deadline", due: "before Thu" },
  },
  {
    text: "My passport is about to expire too, so renew the passport sometime soon.",
    forming: "renew the passport…",
    task: { title: "Renew passport", context: "@errands" },
  },
  {
    text: "And book the flights for the offsite before Friday, prices keep going up.",
    forming: "book the flights before…",
    task: { title: "Book flights for the offsite", due: "before Fri" },
  },
  {
    text: "Oh — and someone still has to fix the flaky signup emails, that keeps coming back.",
    forming: "fix the flaky signup emails…",
    task: { title: "Fix the flaky signup emails", ai: "offer" },
  },
  { text: "Yeah… I think that's everything on my mind for now.", task: null },
];

type TimelineEvent =
  | { t: number; type: "word"; word: string }
  | { t: number; type: "forming"; text: string }
  | { t: number; type: "task"; task: DumpTask };

const BBD_TIMELINE: TimelineEvent[] = (() => {
  const evs: TimelineEvent[] = [];
  let t = 900;
  BBD_SCRIPT.forEach((seg) => {
    seg.text.split(" ").forEach((w, i) => {
      evs.push({ t, type: "word", word: w });
      t += 135 + (w.length > 7 ? 55 : 0) + (i % 6 === 5 ? 80 : 0);
    });
    if (seg.task) {
      evs.push({ t: t + 200, type: "forming", text: seg.forming ?? "" });
      evs.push({ t: t + 1150, type: "task", task: seg.task });
      t += 1600;
    } else {
      t += 600;
    }
  });
  return evs;
})();

function useDumpSim(running: boolean) {
  const [now, setNow] = useState(0);
  useEffect(() => {
    if (!running) return;
    const t0 = Date.now() - now;
    const id = window.setInterval(() => setNow(Date.now() - t0), 100);
    return () => window.clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [running]);

  const words: string[] = [];
  const tasks: DumpTask[] = [];
  let forming: string | null = null;
  for (const ev of BBD_TIMELINE) {
    if (ev.t > now) break;
    if (ev.type === "word") words.push(ev.word);
    else if (ev.type === "forming") forming = ev.text;
    else if (ev.type === "task") {
      tasks.push(ev.task);
      forming = null;
    }
  }
  return { elapsed: Math.floor(now / 1000), words, tasks, forming };
}

function dumpTime(s: number): string {
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

function DumpRec({ elapsed }: { elapsed: number }): JSX.Element {
  return (
    <span className="dump-rec">
      <span className="dump-rec-dot" />
      {dumpTime(elapsed)}
    </span>
  );
}

function DumpWave(): JSX.Element {
  const bars = [0.45, 0.8, 0.4, 1, 0.6, 0.9, 0.5, 0.75, 0.35, 0.85, 0.55];
  return (
    <div className="dump-wave">
      {bars.map((h, i) => (
        <span key={i} style={{ height: Math.round(h * 26), animationDelay: `${(i % 5) * 0.15}s` }} />
      ))}
    </div>
  );
}

function DumpTranscript({ words }: { words: string[] }): JSX.Element {
  const MAX = 18;
  const TAIL = 5;
  const shown = words.slice(-MAX);
  const lead = shown.slice(0, Math.max(0, shown.length - TAIL)).join(" ");
  const tail = shown.slice(-TAIL).join(" ");
  return (
    <div className="dump-transcript">
      {words.length > MAX ? "…" : ""}
      {lead ? `${lead} ` : ""}
      <span className="is-tail">{tail}</span>
      <span className="dump-caret" />
    </div>
  );
}

function DumpChips({ task }: { task: DumpTask }): JSX.Element | null {
  if (!task.due && !task.context && task.ai !== "offer") return null;
  return (
    <span className="dump-card-chips">
      {task.due ? <Chip variant="due" icon={<Calendar size={11} />}>{task.due}</Chip> : null}
      {task.ai === "offer" ? <Chip variant="ai" icon={<SparkIcon size={11} />}>AI can draft</Chip> : null}
      {task.context ? <Chip variant="neutral">{task.context}</Chip> : null}
    </span>
  );
}

function DumpCard({ task }: { task: DumpTask }): JSX.Element {
  return (
    <div className="dump-card">
      <span className="dump-card-title">{task.title}</span>
      <DumpChips task={task} />
    </div>
  );
}

function DumpStack({ sim }: { sim: ReturnType<typeof useDumpSim> }): JSX.Element {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = ref.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [sim.tasks.length, sim.forming]);
  return (
    <div className="dump-stack" ref={ref}>
      <span className="task-detail-label">Headed to inbox · {sim.tasks.length}</span>
      {sim.tasks.length === 0 && !sim.forming ? <div className="dump-hint">Tasks appear here as you speak</div> : null}
      {sim.tasks.map((t, i) => (
        <DumpCard key={i} task={t} />
      ))}
      {sim.forming ? <div className="dump-forming">{sim.forming}</div> : null}
    </div>
  );
}

type ReviewTask = DumpTask & { id: string };

function DumpReviewRow({
  task,
  onChange,
  onRemove,
  onAction,
}: {
  task: ReviewTask;
  onChange: (v: string) => void;
  onRemove: () => void;
  onAction: (what: string) => void;
}): JSX.Element {
  return (
    <div className="dump-review-row">
      <div className="dump-review-main">
        <input className="dump-review-input" value={task.title} aria-label="Task title" onChange={(e) => onChange(e.target.value)} />
        <div className="dump-review-chips">
          {task.due ? (
            <Chip variant="due" icon={<Calendar size={11} />}>
              {task.due}
            </Chip>
          ) : (
            <button type="button" className="dump-chip-add" onClick={() => onAction("Date picker")}>
              <Calendar size={11} /> Add date
            </button>
          )}
          {task.ai === "offer" ? <Chip variant="ai" icon={<SparkIcon size={11} />}>AI can draft</Chip> : null}
          {task.context ? <Chip variant="neutral">{task.context}</Chip> : null}
        </div>
      </div>
      <button type="button" className="dump-remove" onClick={onRemove} aria-label="Remove task">
        <X size={16} />
      </button>
    </div>
  );
}

function BrainDumpOverlay({
  onClose,
  onSend,
  onAction,
}: {
  onClose: () => void;
  onSend: (list: ReviewTask[]) => void;
  onAction: (what: string) => void;
}): JSX.Element {
  const [phase, setPhase] = useState<"recording" | "review">("recording");
  const [review, setReview] = useState<ReviewTask[]>([]);
  const sim = useDumpSim(phase === "recording");
  const n = sim.tasks.length;
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const returnFocusRef = useRef<HTMLElement | null>(document.activeElement as HTMLElement | null);

  useEffect(() => {
    closeButtonRef.current?.focus();
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handler);
    const elementToRefocus = returnFocusRef.current;
    return () => {
      window.removeEventListener("keydown", handler);
      elementToRefocus?.focus();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const stop = () => {
    if (!n) {
      onClose();
      return;
    }
    setReview(sim.tasks.map((t, i) => ({ ...t, id: `d${i}` })));
    setPhase("review");
  };

  return (
    <div className="dump-scrim" onClick={onClose}>
      <div className="dump-panel" onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true" aria-label="Brain dump">
        {phase === "recording" ? (
          <>
            <button type="button" className="dump-x dump-x-float" onClick={onClose} aria-label="Discard and close" ref={closeButtonRef}>
              <X size={18} />
            </button>
            <div className="dump-body">
              <div className="dump-side">
                <span className="dump-mic-badge">
                  <Mic size={22} />
                </span>
                <div>
                  <div className="dump-title">Brain dump</div>
                  <div className="dump-sub">{n ? `${n} task${n === 1 ? "" : "s"} captured` : "Speak freely — tasks are extracted as you go"}</div>
                </div>
                <DumpRec elapsed={sim.elapsed} />
                <div className="dump-side-fill" />
                <DumpTranscript words={sim.words} />
                <DumpWave />
                <Button leftIcon={<Square size={14} />} onClick={stop}>
                  {n ? `Stop & send ${n} to inbox` : "Stop"}
                </Button>
                <span className="task-caption">Nothing is saved until you stop</span>
              </div>
              <DumpStack sim={sim} />
            </div>
          </>
        ) : (
          <>
            <div className="dump-head">
              <div>
                <div className="dump-title">
                  Review {review.length} task{review.length === 1 ? "" : "s"}
                </div>
                <div className="dump-sub">Edit before they land in your inbox</div>
              </div>
              <div className="dump-head-right">
                <button type="button" className="dump-x" onClick={onClose} aria-label="Discard and close">
                  <X size={18} />
                </button>
              </div>
            </div>
            <div className="dump-stack is-review">
              <div className="dump-review-list">
                {review.map((t) => (
                  <DumpReviewRow
                    key={t.id}
                    task={t}
                    onChange={(v) => setReview((r) => r.map((x) => (x.id === t.id ? { ...x, title: v } : x)))}
                    onRemove={() => setReview((r) => r.filter((x) => x.id !== t.id))}
                    onAction={onAction}
                  />
                ))}
              </div>
            </div>
            <div className="dump-foot">
              <Button onClick={() => review.length && onSend(review)}>Send {review.length} to inbox</Button>
              <button type="button" className="dump-ghost" onClick={onClose}>
                Discard all
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Main workspace                                                     */
/* ------------------------------------------------------------------ */

export default function TaskWorkspace(): JSX.Element {
  const [view, setView] = useState<View>({ kind: "list", id: "next" });
  const [done, setDone] = useState<Record<string, boolean>>({});
  const [tasks, setTasks] = useState<Task[]>(BB_TASKS);
  const [dumpOpen, setDumpOpen] = useState(false);
  const [toast, setToast] = useState<string | null>(null);
  const [groupByProject, setGroupByProject] = useState(false);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const toastTimer = useRef<number>();

  const toggle = (id: string) => setDone((d) => ({ ...d, [id]: !d[id] }));
  const onExpand = (id: string) => setExpandedId((e) => (e === id ? null : id));
  const notify = (msg: string) => {
    setToast(msg);
    window.clearTimeout(toastTimer.current);
    toastTimer.current = window.setTimeout(() => setToast(null), 2600);
  };
  const notBuilt = (what: string) => notify(`${what} isn't built yet — placeholder`);

  const counts = useMemo(() => {
    const c: Record<ListId, number> = { inbox: 0, next: 0, waiting: 0, someday: 0 };
    tasks.forEach((x) => {
      if (!done[x.id]) c[x.list] += 1;
    });
    return c;
  }, [tasks, done]);

  const addTask = (list: ListId) => {
    const title = window.prompt("New task");
    if (!title || !title.trim()) return;
    setTasks((s) => [...s, { id: nextId("u"), list, title: title.trim() }]);
  };

  let pane: JSX.Element;

  if (view.kind === "review") {
    pane = (
      <Placeholder
        icon={<RotateCcw size={26} />}
        title="Weekly review"
        hint="A guided pass over your lists — empty the inbox, refresh next actions, decide on the somedays. Due Sunday."
      />
    );
  } else if (view.kind === "project") {
    const proj = BB_PROJECTS.find((p) => p.id === view.id) as Project;
    const projTasks = tasks.filter((x) => x.project === proj.name);
    pane = (
      <>
        <div className="pane-header">
          <div>
            <h1>{proj.name}</h1>
            <p>{proj.meta}</p>
          </div>
          <div className="pane-actions">
            <Button variant="secondary" size="sm" leftIcon={<Network size={14} />} onClick={() => notBuilt("Thinking canvas")}>
              Think
            </Button>
          </div>
        </div>
        <div className="task-list">
          {projTasks.map((task) => (
            <TaskRow
              key={task.id}
              task={task}
              checked={Boolean(done[task.id])}
              onToggle={() => toggle(task.id)}
              showProject={false}
              onChipClick={() => notBuilt("Task details")}
              expanded={expandedId === task.id}
              onExpand={() => onExpand(task.id)}
            />
          ))}
        </div>
        <button type="button" className="add-task" onClick={() => notBuilt("Add to project")}>
          <Plus size={16} />
          <span>Add a task to this project</span>
        </button>
      </>
    );
  } else if (view.kind === "context") {
    const ctxTasks = tasks.filter((x) => x.context === view.id);
    pane = (
      <>
        <div className="pane-header">
          <div>
            <h1>{view.id}</h1>
            <p>
              {ctxTasks.length} task{ctxTasks.length === 1 ? "" : "s"} across your lists
            </p>
          </div>
        </div>
        <div className="task-list">
          {ctxTasks.map((task) => (
            <TaskRow
              key={task.id}
              task={task}
              checked={Boolean(done[task.id])}
              onToggle={() => toggle(task.id)}
              showProject
              onChipClick={() => notBuilt("Task details")}
              expanded={expandedId === task.id}
              onExpand={() => onExpand(task.id)}
            />
          ))}
        </div>
      </>
    );
  } else {
    const def = BB_LISTS[view.id];
    const listTasks = tasks.filter((x) => x.list === view.id);
    const running = listTasks.filter((x) => x.ai === "working" && !done[x.id]).length;
    const meta =
      view.id === "inbox"
        ? def.hint
        : `${counts[view.id]} task${counts[view.id] === 1 ? "" : "s"}` + (running ? ` · ${running} running on AI` : "");

    pane = (
      <>
        <div className="pane-header">
          <div>
            <h1>{def.title}</h1>
            <p>{meta}</p>
          </div>
          <div className="pane-actions">
            {view.id !== "inbox" ? (
              <Button
                variant={groupByProject ? "secondary" : "ghost"}
                size="sm"
                leftIcon={<Layers2 size={14} />}
                onClick={() => setGroupByProject((g) => !g)}
              >
                Group by project
              </Button>
            ) : null}
            <Button variant="ghost" size="sm" leftIcon={<ArrowUpDown size={14} />} onClick={() => notBuilt("Sorting")}>
              Sort
            </Button>
          </div>
        </div>
        {groupByProject && view.id !== "inbox" ? (
          <div className="grouped-list">
            {groupTasksByProject(listTasks).map((g) => (
              <div key={g.name}>
                <div className="task-group-head">
                  {g.color ? <span className="task-project-dot" style={{ background: g.color }} /> : null}
                  <span className="task-detail-label task-group-label">{g.name}</span>
                  <span className="task-nav-count">{g.tasks.length}</span>
                </div>
                <div className="task-list">
                  {g.tasks.map((task) => (
                    <TaskRow
                      key={task.id}
                      task={task}
                      checked={Boolean(done[task.id])}
                      onToggle={() => toggle(task.id)}
                      showProject={false}
                      onChipClick={() => notBuilt("Task details")}
                      expanded={expandedId === task.id}
                      onExpand={() => onExpand(task.id)}
                    />
                  ))}
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="task-list">
            {listTasks.map((task) => (
              <TaskRow
                key={task.id}
                task={task}
                checked={Boolean(done[task.id])}
                onToggle={() => toggle(task.id)}
                showProject
                onChipClick={() => notBuilt("Task details")}
                expanded={expandedId === task.id}
                onExpand={() => onExpand(task.id)}
              />
            ))}
          </div>
        )}
        <button type="button" className="add-task" onClick={() => addTask(view.id)}>
          <Plus size={16} />
          <span>
            {view.id === "next" ? "Add a next action — or dump everything on your mind with the mic above" : "Add a task"}
          </span>
        </button>
      </>
    );
  }

  return (
    <main className="task-workspace">
      <header className="task-topbar">
        <span className="brand">
          <SproutIcon /> Brain Buddy
        </span>
        <div className="task-search">
          <Search size={15} />
          <input placeholder="Search tasks and trees" onKeyDown={(e) => e.key === "Enter" && notBuilt("Search")} />
        </div>
        <div className="task-topbar-right">
          <Button leftIcon={<Mic size={15} />} onClick={() => setDumpOpen(true)}>
            Brain dump
          </Button>
          <button type="button" className="avatar-button" onClick={() => notBuilt("Account menu")}>
            TS
          </button>
        </div>
      </header>

      <div className="task-workspace-body">
        <nav className="task-sidebar" aria-label="Task navigation">
          <div className="sidebar-nav">
            <NavItem
              icon={<InboxIcon size={16} />}
              label="Inbox"
              active={view.kind === "list" && view.id === "inbox"}
              onClick={() => setView({ kind: "list", id: "inbox" })}
              trailing={counts.inbox > 0 ? <span className="sidebar-badge-inbox">{counts.inbox}</span> : null}
            />
            <NavItem
              icon={<ArrowRight size={16} />}
              label="Next actions"
              active={view.kind === "list" && view.id === "next"}
              onClick={() => setView({ kind: "list", id: "next" })}
              trailing={<span className="task-nav-count">{counts.next}</span>}
            />
            <NavItem
              icon={<Clock size={16} />}
              label="Waiting for"
              active={view.kind === "list" && view.id === "waiting"}
              onClick={() => setView({ kind: "list", id: "waiting" })}
              trailing={<span className="task-nav-count">{counts.waiting}</span>}
            />
            <NavItem
              icon={<Archive size={16} />}
              label="Someday / maybe"
              active={view.kind === "list" && view.id === "someday"}
              onClick={() => setView({ kind: "list", id: "someday" })}
              trailing={<span className="task-nav-count">{counts.someday}</span>}
            />
            <NavItem
              icon={<RotateCcw size={16} />}
              label="Weekly review"
              active={view.kind === "review"}
              onClick={() => setView({ kind: "review" })}
              trailing={<span className="sidebar-chip-due-review">due Sun</span>}
            />
          </div>

          <section className="sidebar-section">
            <div className="sidebar-section-title">
              <span>Projects</span>
            </div>
            <div className="sidebar-nav" style={{ marginTop: 6 }}>
              {BB_PROJECTS.map((p) => (
                <NavItem
                  key={p.id}
                  wrap
                  icon={<span className="task-project-dot" style={{ background: p.color }} />}
                  label={p.name}
                  active={view.kind === "project" && view.id === p.id}
                  onClick={() => setView({ kind: "project", id: p.id })}
                />
              ))}
              <NavItem
                icon={<Plus size={14} color="#94a3b8" />}
                label={<span style={{ color: "#94a3b8" }}>New project</span>}
                onClick={() => notBuilt("New project")}
              />
            </div>
          </section>

          <section className="sidebar-section">
            <div className="sidebar-section-title">
              <span>Contexts</span>
            </div>
            <div className="context-pills">
              {BB_CONTEXTS.map((c) => (
                <button
                  key={c}
                  type="button"
                  className={`context-pill${view.kind === "context" && view.id === c ? " is-active" : ""}`}
                  onClick={() => setView({ kind: "context", id: c })}
                >
                  {c}
                </button>
              ))}
            </div>
          </section>
        </nav>

        <main className="task-content">
          <div className="task-content-inner">{pane}</div>
        </main>
      </div>

      {dumpOpen ? (
        <BrainDumpOverlay
          onClose={() => setDumpOpen(false)}
          onAction={notBuilt}
          onSend={(list) => {
            setTasks((s) => [
              ...s,
              ...list.map((t) => ({ id: nextId("u"), list: "inbox" as ListId, title: t.title, due: t.due, context: t.context, ai: t.ai })),
            ]);
            setDumpOpen(false);
            setView({ kind: "list", id: "inbox" });
            notify(`${list.length} task${list.length === 1 ? "" : "s"} sent to inbox`);
          }}
        />
      ) : null}

      {toast ? (
        <div className="workspace-toast" role="status">
          {toast}
        </div>
      ) : null}
    </main>
  );
}

function SproutIcon(): JSX.Element {
  return (
    <svg width={22} height={22} viewBox="0 0 24 24" fill="none" stroke="#0ea5e9" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
      <path d="M7 20h10" />
      <path d="M10 20c5.5-2.5.8-6.4 3-10" />
      <path d="M9.5 9.4c1.1.8 1.8 2.2 2.3 3.7-2 .4-3.5.4-4.8-.3-1.2-.6-2.3-1.9-3-4.2 2.8-.5 4.4 0 5.5.8z" />
      <path d="M14.1 6a7 7 0 0 0-1.1 4c1.9.1 3.3-.2 4.3-.9 1-.6 1.9-1.8 2.7-3.6-2.4-.5-4-.3-5-.1-.4.1-.7.3-.9.6z" />
    </svg>
  );
}
