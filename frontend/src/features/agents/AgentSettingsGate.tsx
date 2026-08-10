import { hasFeatureFlag } from "../../api/auth";
import { useProjects, useTags, useTaskList } from "../../api/taskHooks";
import type { TaskCounts } from "../../api/taskTypes";
import { AppShell } from "../../components/shell/AppShell";
import { useAuthStore } from "../../stores/authStore";
import { AgentSettingsPage } from "./AgentSettingsPage";

const emptyCounts: TaskCounts = { inbox: 0, next: 0, waiting: 0, someday: 0 };

/**
 * Rollout gate for the external-agent relay.
 *
 * The backend answers 404 on every `/agent-*` route while `external_agent_relay`
 * is OFF, so the gate keeps the client from asking at all: an off rollout should
 * read as "not turned on", never as a broken page. Fails closed — a missing flag
 * is OFF (see `hasFeatureFlag`).
 */
export function AgentSettingsGate(): React.JSX.Element {
  const user = useAuthStore((state) => state.user);

  if (hasFeatureFlag(user, "external_agent_relay")) {
    return <AgentSettingsPage />;
  }

  return <AgentRelayOffPage />;
}

function AgentRelayOffPage(): React.JSX.Element {
  const countsQuery = useTaskList({ state: "next", limit: 1 });
  const projectsQuery = useProjects();
  const tagsQuery = useTags();

  return (
    <AppShell
      counts={countsQuery.data?.counts_by_state ?? emptyCounts}
      projects={projectsQuery.data ?? []}
      tags={tagsQuery.data ?? []}
    >
      <div className="mx-auto flex max-w-[680px] flex-col gap-5 pb-12">
        <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-soft">
          <p className="text-xs font-semibold uppercase tracking-[0.06em] text-brand-primary">
            Not available yet
          </p>
          <h1 className="mt-2 text-title font-semibold text-slate-900">External agents are off</h1>
          <p className="mt-2 text-sm text-slate-600">
            This workspace does not have the external-agent relay enabled yet. It will appear here
            once it is turned on for your account.
          </p>
        </section>
      </div>
    </AppShell>
  );
}
