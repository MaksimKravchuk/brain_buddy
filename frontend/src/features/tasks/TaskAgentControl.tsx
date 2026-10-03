import { AlertTriangle, Bot, Check, ChevronDown, Circle, Clock3 } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import type { AgentConnectionResponse, AgentRunSummaryResponse } from "../../api/agentTypes";
import type { TaskResponse } from "../../api/taskTypes";
import { compactRunLabel, compactTaskRunStateLabel } from "../agents/agentCopy";

function statusClasses(label: string, needsUser: boolean): string {
  const normalized = label.toLowerCase();
  if (needsUser) return "border-needs-you-border text-needs-you-fg";
  if (normalized.includes("failed")) return "border-rose-200 text-rose-700";
  if (normalized.includes("reported") || normalized.includes("complete")) return "border-emerald-200 text-emerald-700";
  if (normalized.includes("running")) return "border-sky-200 text-sky-700";
  return "border-slate-200 text-slate-500";
}

function StatusIcon({ label }: { label: string }): React.JSX.Element {
  const normalized = label.toLowerCase();
  if (normalized.includes("failed")) return <AlertTriangle className="h-3.5 w-3.5" aria-hidden />;
  if (normalized.includes("reported") || normalized.includes("complete")) return <Check className="h-3.5 w-3.5" aria-hidden />;
  if (normalized.includes("queued")) return <Clock3 className="h-3.5 w-3.5" aria-hidden />;
  return <Circle className="h-3.5 w-3.5" aria-hidden />;
}

function connectionLabel(connection: AgentConnectionResponse, duplicates: Set<string>): string {
  if (!duplicates.has(connection.name)) return connection.name;
  try {
    return `${connection.name} · ${new URL(connection.agent_address).hostname}`;
  } catch {
    return `${connection.name} · ${connection.agent_address}`;
  }
}

export function TaskAgentControl({
  task,
  run,
  relayEnabled,
  connections,
  preferredConnectionId,
  onReview,
  onOpenTask
}: {
  task: TaskResponse;
  run?: AgentRunSummaryResponse;
  relayEnabled: boolean;
  connections: readonly AgentConnectionResponse[];
  preferredConnectionId?: string;
  onReview: (connectionId: string) => void;
  onOpenTask: () => void;
}): React.JSX.Element | null {
  const [menuOpen, setMenuOpen] = useState(false);
  const rootRef = useRef<HTMLSpanElement>(null);
  const chooserRef = useRef<HTMLButtonElement>(null);
  const menuItemRefs = useRef<Array<HTMLButtonElement | null>>([]);
  const pendingMenuFocusRef = useRef<"first" | "last">("first");
  const eligible = connections.filter((connection) => connection.ready_for_handoff);
  const preferred = eligible.find((connection) => connection.id === preferredConnectionId) ?? eligible[0];

  useEffect(() => {
    if (!menuOpen) return;
    const items = menuItemRefs.current.filter((item): item is HTMLButtonElement => Boolean(item));
    const target = pendingMenuFocusRef.current === "last" ? items[items.length - 1] : items[0];
    target?.focus();
    const close = (event: MouseEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setMenuOpen(false);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [menuOpen]);

  if (run) {
    const status = compactTaskRunStateLabel(run.primary_state_label);
    const fullStatus = compactRunLabel(run);
    return (
      <button
        type="button"
        data-agent-assigned-control={task.id}
        className={`grid h-7 w-[184px] shrink-0 grid-cols-[14px_minmax(0,62px)_4px_14px_minmax(0,1fr)] items-center gap-1 rounded-lg border bg-white px-2 text-xs font-medium ${statusClasses(run.primary_state_label, run.needs_user)}`}
        aria-label={`Open ${task.title}. Agent ${run.agent_name}. ${fullStatus}`}
        title={`${run.agent_name} · ${fullStatus}`}
        onClick={onOpenTask}
      >
        <Bot className="h-3.5 w-3.5 text-slate-500" aria-hidden />
        <span className="truncate text-left text-slate-700">{run.agent_name}</span>
        <span className="text-slate-300" aria-hidden>·</span>
        <StatusIcon label={run.primary_state_label} />
        <span className="truncate text-left">{status}</span>
      </button>
    );
  }

  if (!relayEnabled || !preferred || task.state === "completed" || task.state === "cancelled") return null;

  const nameCounts = new Map<string, number>();
  for (const connection of eligible) nameCounts.set(connection.name, (nameCounts.get(connection.name) ?? 0) + 1);
  const duplicates = new Set([...nameCounts].filter(([, count]) => count > 1).map(([name]) => name));

  return (
    <span ref={rootRef} className="relative inline-flex h-7 shrink-0" onKeyDown={(event) => {
      if (event.key === "Escape" && menuOpen) {
        event.preventDefault();
        event.stopPropagation();
        setMenuOpen(false);
        chooserRef.current?.focus();
        return;
      }
      if (!menuOpen && event.currentTarget.contains(event.target as Node) && (event.key === "ArrowDown" || event.key === "ArrowUp")) {
        event.preventDefault();
        pendingMenuFocusRef.current = event.key === "ArrowUp" ? "last" : "first";
        setMenuOpen(true);
        return;
      }
      if (menuOpen && ["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) {
        const items = menuItemRefs.current.filter((item): item is HTMLButtonElement => Boolean(item));
        if (!items.length) return;
        event.preventDefault();
        const currentIndex = items.indexOf(document.activeElement as HTMLButtonElement);
        const nextIndex = event.key === "Home"
          ? 0
          : event.key === "End"
            ? items.length - 1
            : event.key === "ArrowDown"
              ? (currentIndex + 1 + items.length) % items.length
              : (currentIndex - 1 + items.length) % items.length;
        items[nextIndex]?.focus();
      }
    }}>
      <button
        type="button"
        className="inline-flex h-7 w-9 items-center justify-center rounded-l-lg border border-r-0 border-slate-200 bg-white text-slate-500 transition-colors hover:bg-slate-50 hover:text-slate-800 focus-visible:z-10 focus-visible:outline focus-visible:outline-2 focus-visible:outline-brand-primary"
        aria-label={`Hand ${task.title} to ${preferred.name}`}
        title={`Hand to ${preferred.name}`}
        onClick={() => onReview(preferred.id)}
      >
        <Bot className="h-3.5 w-3.5" aria-hidden />
      </button>
      <button
        ref={chooserRef}
        type="button"
        className="inline-flex h-7 w-6 items-center justify-center rounded-r-lg border border-slate-200 bg-white text-slate-400 transition-colors hover:bg-slate-50 hover:text-slate-700 focus-visible:z-10 focus-visible:outline focus-visible:outline-2 focus-visible:outline-brand-primary"
        aria-label={`Choose agent for ${task.title}`}
        aria-expanded={menuOpen}
        aria-haspopup="menu"
        onClick={() => {
          pendingMenuFocusRef.current = "first";
          setMenuOpen((open) => !open);
        }}
      >
        <ChevronDown className="h-3 w-3" aria-hidden />
      </button>
      {menuOpen ? (
        <span role="menu" aria-label="Choose agent" className="absolute right-0 top-8 z-40 min-w-44 rounded-lg border border-slate-200 bg-white p-1 shadow-floating">
          {eligible.map((connection, index) => (
            <button
              key={connection.id}
              ref={(item) => { menuItemRefs.current[index] = item; }}
              type="button"
              role="menuitem"
              className="block w-full rounded-md px-2.5 py-1.5 text-left text-xs text-slate-700 hover:bg-slate-50 focus:bg-slate-50 focus:outline-none"
              onClick={() => {
                setMenuOpen(false);
                onReview(connection.id);
              }}
            >
              {connectionLabel(connection, duplicates)}
            </button>
          ))}
        </span>
      ) : null}
    </span>
  );
}
