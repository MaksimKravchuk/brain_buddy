/* istanbul ignore file -- route glue is exercised by AppRoutes tests and Playwright shell snapshots. */
import { Navigate, Route, Routes } from "react-router-dom";

import { ProtectedRoute } from "../components/auth/ProtectedRoute";
import { BrainDumpRoute } from "../features/brain-dump/BrainDumpRoute";
import { TaskListPage } from "../features/tasks/TaskListPage";
import LoginPage from "../pages/LoginPage";
import SignupPage from "../pages/SignupPage";
import TaskWorkspace from "../pages/TaskWorkspace";
import TreeWorkspace from "../pages/TreeWorkspace";

export function AppRoutes(): JSX.Element {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/signup" element={<SignupPage />} />
      <Route
        path="/"
        element={
          <ProtectedRoute>
            <TaskWorkspace />
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
            <TreeWorkspace />
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
