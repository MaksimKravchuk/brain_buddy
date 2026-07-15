import { Navigate, Route, Routes } from "react-router-dom";

import { ProtectedRoute } from "../components/auth/ProtectedRoute";
import { BrainDumpRoute } from "../features/brain-dump/BrainDumpRoute";
import { TaskListPage } from "../features/tasks/TaskListPage";
import LoginPage from "../pages/LoginPage";
import SignupPage from "../pages/SignupPage";
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
            <Navigate to="/tasks/next" replace />
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
        path="/projects/:projectId"
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
            <Navigate to="/tasks/next" replace />
          </ProtectedRoute>
        }
      />
    </Routes>
  );
}
