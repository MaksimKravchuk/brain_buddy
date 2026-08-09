import { Navigate, Route, Routes, useLocation } from "react-router-dom";

import { ProtectedRoute } from "../components/auth/ProtectedRoute";
import { AccountSettingsPage } from "../features/account/AccountSettingsPage";
import { AgentSettingsGate } from "../features/agents/AgentSettingsGate";
import { BrainDumpGate } from "../features/brain-dump/BrainDumpGate";
import type { BrainDumpLocationState } from "../features/brain-dump/brainDumpNavigation";
import { TaskListPage } from "../features/tasks/TaskListPage";
import LoginPage from "../pages/LoginPage";
import PrivacyPolicyPage from "../pages/PrivacyPolicyPage";
import SignupPage from "../pages/SignupPage";

// Brain dump is a modal over the workspace, so its routes render twice: the
// first <Routes> resolves whatever view stays *behind* the panel, and the second
// resolves the panel itself. Opening it from the top bar stamps the current
// location onto the history entry as `backgroundLocation`, so the list the user
// was on stays visible underneath. A deep link or reload has no such state —
// then the first <Routes> falls back to the default list as the backdrop, which
// keeps the operation recoverable from its URL alone.
export function AppRoutes(): React.JSX.Element {
  const location = useLocation();
  const backgroundLocation = (location.state as BrainDumpLocationState | null)?.backgroundLocation;

  return (
    <>
      <Routes location={backgroundLocation ?? location}>{workspaceRoutes()}</Routes>
      <Routes>
        <Route
          path="/brain-dump/:operationId"
          element={
            <ProtectedRoute>
              <BrainDumpGate />
            </ProtectedRoute>
          }
        />
        <Route
          path="/brain-dump/:operationId/review"
          element={
            <ProtectedRoute>
              <BrainDumpGate />
            </ProtectedRoute>
          }
        />
      </Routes>
    </>
  );
}

function workspaceRoutes(): React.JSX.Element {
  return (
    <>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/signup" element={<SignupPage />} />
      {/* Public on purpose: the policy must be readable before signing up, and
          the catch-all below would otherwise bounce signed-out visitors. */}
      <Route path="/privacy" element={<PrivacyPolicyPage />} />
      <Route
        path="/settings/account"
        element={
          <ProtectedRoute>
            <AccountSettingsPage />
          </ProtectedRoute>
        }
      />
      <Route
        path="/settings/agents"
        element={
          <ProtectedRoute>
            <AgentSettingsGate />
          </ProtectedRoute>
        }
      />
      <Route
        path="/"
        element={
          <ProtectedRoute>
            <TaskListPage mode="state" />
          </ProtectedRoute>
        }
      />
      <Route
        path="/tasks/:state"
        element={
          <ProtectedRoute>
            <TaskListPage mode="state" />
          </ProtectedRoute>
        }
      />
      <Route
        path="/tasks/:state/:taskId"
        element={
          <ProtectedRoute>
            <TaskListPage mode="state" />
          </ProtectedRoute>
        }
      />
      <Route
        path="/projects/:projectId"
        element={
          <ProtectedRoute>
            <TaskListPage mode="project" />
          </ProtectedRoute>
        }
      />
      <Route
        path="/projects/:projectId/:taskId"
        element={
          <ProtectedRoute>
            <TaskListPage mode="project" />
          </ProtectedRoute>
        }
      />
      <Route
        path="/tags/:tagId"
        element={
          <ProtectedRoute>
            <TaskListPage mode="tag" />
          </ProtectedRoute>
        }
      />
      <Route
        path="/tags/:tagId/:taskId"
        element={
          <ProtectedRoute>
            <TaskListPage mode="tag" />
          </ProtectedRoute>
        }
      />
      {/* Backdrop for a brain dump opened directly rather than from the top bar.
          The panel itself is rendered by the overlay <Routes> in AppRoutes. */}
      <Route
        path="/brain-dump/*"
        element={
          <ProtectedRoute>
            <TaskListPage mode="state" />
          </ProtectedRoute>
        }
      />
      <Route
        path="/crt/*"
        element={
          <ProtectedRoute>
            <ComingLater title="Thinking Mode" />
          </ProtectedRoute>
        }
      />
      <Route
        path="*"
        element={
          <ProtectedRoute>
            <Navigate to="/" replace />
          </ProtectedRoute>
        }
      />
    </>
  );
}

function ComingLater({ title }: { title: string }): React.JSX.Element {
  return (
    <main className="flex min-h-screen items-center justify-center bg-surface-base px-6 text-center">
      <section className="rounded-2xl border border-slate-200 bg-white px-8 py-10 shadow-raised">
        <p className="text-xs font-semibold uppercase tracking-[0.06em] text-brand-primary">Coming later</p>
        <h1 className="mt-2 text-title font-semibold text-slate-900">{title}</h1>
        <p className="mt-2 max-w-md text-sm text-slate-600">
          This workspace is intentionally unavailable while the canonical GTD flow remains focused.
        </p>
      </section>
    </main>
  );
}
