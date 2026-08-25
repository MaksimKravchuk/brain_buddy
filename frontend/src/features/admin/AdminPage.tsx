import { useState } from "react";
import { useAdminStatus } from "../../api/adminHooks";
import { ApiError } from "../../api/client";
import { useProjects, useTags, useTaskList } from "../../api/taskHooks";
import { AppShell } from "../../components/shell/AppShell";
import { Button } from "../../components/ui/Button";
import { SectionCard } from "../../components/ui/SettingsSection";
import { AdminFeatureFlagsSection } from "./AdminFeatureFlagsSection";
import { AdminUsersSection } from "./AdminUsersSection";

const emptyCounts = { inbox: 0, next: 0, waiting: 0, someday: 0 };

export function AdminPage(): React.JSX.Element {
  const countsQuery = useTaskList({ state: "next", limit: 1 });
  const projectsQuery = useProjects();
  const tagsQuery = useTags();
  const adminStatus = useAdminStatus();
  const isOperator = adminStatus.isSuccess && adminStatus.data?.is_operator === true;
  const denialStatus = adminStatus.error instanceof ApiError ? adminStatus.error.status : null;
  const isConfirmedDenial = denialStatus === 403 || denialStatus === 404;
  const couldNotVerify = adminStatus.isError && !isConfirmedDenial;

  return (
    <AppShell counts={countsQuery.data?.counts_by_state ?? emptyCounts} projects={projectsQuery.data ?? []} tags={tagsQuery.data ?? []}>
      <div className="mx-auto flex max-w-[680px] flex-col gap-5 pb-12">
        <header>
          <h1 className="text-title font-semibold text-slate-900">Admin</h1>
          <p className="mt-1 text-sm text-slate-500">Manage member accounts and runtime feature flags.</p>
        </header>
        {adminStatus.isPending ? <p role="status" className="text-sm text-slate-500">Checking access…</p> : isOperator ? <AdminTabs /> : couldNotVerify ? <AccessUnverified onRetry={() => void adminStatus.refetch()} /> : <AccessDenied />}
      </div>
    </AppShell>
  );
}

function AdminTabs(): React.JSX.Element {
  const [tab, setTab] = useState<"users" | "flags">("users");
  const onTabKeyDown = (event: React.KeyboardEvent<HTMLButtonElement>) => {
    const next = event.key === "ArrowRight" || event.key === "ArrowDown" ? "flags" : event.key === "ArrowLeft" || event.key === "ArrowUp" ? "users" : null;
    if (next === null) return;
    event.preventDefault();
    setTab(next);
    const target = next === "flags" ? event.currentTarget.nextElementSibling : event.currentTarget.previousElementSibling;
    if (target instanceof HTMLElement) target.focus();
  };
  return (
    <div className="flex flex-col gap-4">
      <div role="tablist" aria-label="Admin sections" className="flex gap-2 border-b border-slate-200">
        <button role="tab" id="admin-users-tab" aria-controls="admin-users-panel" aria-selected={tab === "users"} tabIndex={tab === "users" ? 0 : -1} onClick={() => setTab("users")} onKeyDown={onTabKeyDown} className="px-3 py-2 text-sm">Users</button>
        <button role="tab" id="admin-flags-tab" aria-controls="admin-flags-panel" aria-selected={tab === "flags"} tabIndex={tab === "flags" ? 0 : -1} onClick={() => setTab("flags")} onKeyDown={onTabKeyDown} className="px-3 py-2 text-sm">Feature flags</button>
      </div>
      {tab === "users" ? <div role="tabpanel" id="admin-users-panel" aria-labelledby="admin-users-tab"><AdminUsersSection /></div> : null}
      {tab === "flags" ? <div role="tabpanel" id="admin-flags-panel" aria-labelledby="admin-flags-tab"><AdminFeatureFlagsSection /></div> : null}
    </div>
  );
}

function AccessDenied(): React.JSX.Element {
  return <SectionCard tone="danger" title="Access denied" description="This account is not authorized for the admin portal.">{null}</SectionCard>;
}

function AccessUnverified({ onRetry }: { onRetry: () => void }): React.JSX.Element {
  return <SectionCard title="Couldn't verify access" description="Couldn't verify access. Try again."><Button type="button" variant="secondary" size="md" onClick={onRetry}>Try again</Button></SectionCard>;
}
