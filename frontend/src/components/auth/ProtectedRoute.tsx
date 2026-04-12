import type { ReactNode } from "react";
import { Navigate, useLocation } from "react-router-dom";

import { useAuthStore } from "../../stores/authStore";

interface Props {
  children: ReactNode;
}

export function ProtectedRoute({ children }: Props): JSX.Element {
  const status = useAuthStore((state) => state.status);
  const location = useLocation();

  if (status === "loading") {
    return (
      <div className="flex min-h-screen items-center justify-center bg-surface-base text-sm text-slate-500">
        Loading session…
      </div>
    );
  }

  if (status !== "authed") {
    return <Navigate to="/login" replace state={{ from: location }} />;
  }

  return <>{children}</>;
}
