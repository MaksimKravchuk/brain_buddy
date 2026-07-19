/* istanbul ignore file -- route glue is exercised by AppRoutes tests and Playwright shell snapshots. */
import { Navigate, Route, Routes } from "react-router-dom";

import { ProtectedRoute } from "../components/auth/ProtectedRoute";
import { BrainDumpRoute } from "../features/brain-dump/BrainDumpRoute";
import { TaskListPage } from "../features/tasks/TaskListPage";
import LoginPage from "../pages/LoginPage";
import SignupPage from "../pages/SignupPage";

export function AppRoutes(): JSX.Element {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/signup" element={<SignupPage />} />
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
      <Route
        path="/brain-dump/:operationId"
        element={
          <ProtectedRoute>
            <BrainDumpRoute />
          </ProtectedRoute>
        }
      />
      <Route
        path="/brain-dump/:operationId/review"
        element={
          <ProtectedRoute>
            <BrainDumpRoute />
          </ProtectedRoute>
        }
      />
      <Route
        path="/crt/*"
        element={
          <ProtectedRoute>
            <ComingLater title="Think with CRT" />
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
    </Routes>
  );
}

function ComingLater({ title }: { title: string }): JSX.Element {
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
