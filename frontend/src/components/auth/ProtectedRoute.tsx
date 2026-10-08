import { Fragment, type ReactNode } from "react";
import { Navigate, useLocation } from "react-router-dom";

import { useAuthStore } from "../../stores/authStore";
import { safeAuthDestination } from "../../features/auth/authFlow";

interface Props {
  children: ReactNode;
}

export function ProtectedRoute({ children }: Props): React.JSX.Element {
  const status = useAuthStore((state) => state.status);
  const location = useLocation();
  const user = useAuthStore(state => state.user);
  const destination = safeAuthDestination(location.pathname + location.search);
  const expectedOwner = new URL(destination, "https://brainbuddy.invalid").searchParams.get("expected_owner");

  if (status === "loading") {
    return (
      <div className="flex min-h-screen items-center justify-center bg-surface-base text-sm text-slate-500">
        Loading session…
      </div>
    );
  }

  if (status !== "authed" || (expectedOwner && user?.id !== expectedOwner)) {
    const parsed = new URL(destination, "https://brainbuddy.invalid");
    return <Navigate to="/login" replace state={{ from: { pathname: parsed.pathname, search: parsed.search } }} />;
  }

  // Keyed by the signed-in account: when a session refresh swaps the account
  // without leaving the page, everything below remounts, so no local state
  // (open cards, failures and their Retry, attempts, rows) outlives the
  // account it belongs to. A profile refresh of the same account keeps it.
  return <Fragment key={user?.id}>{children}</Fragment>;
}
