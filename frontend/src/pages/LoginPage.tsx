import { useState, type FormEvent } from "react";
import { Link, Navigate, useLocation, useNavigate } from "react-router-dom";
import { Sprout } from "lucide-react";

import { ApiError } from "../api/client";
import { Button } from "../components/ui/Button";
import { useAuthStore } from "../stores/authStore";

type LocationState = {
  from?: { pathname: string };
  /** Purge date stamped by the delete-account flow so we can explain the grace period. */
  deletionScheduled?: string;
} | null;

export default function LoginPage(): React.JSX.Element {
  const status = useAuthStore((state) => state.status);
  const login = useAuthStore((state) => state.login);
  const navigate = useNavigate();
  const location = useLocation();
  const redirectTo = (location.state as LocationState)?.from?.pathname ?? "/";
  const deletionScheduledFor = useAuthStore((state) => state.deletionScheduledFor);
  const deletionScheduled =
    (location.state as LocationState)?.deletionScheduled ?? deletionScheduledFor ?? undefined;

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  if (status === "authed") {
    return <Navigate to={redirectTo} replace />;
  }

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await login({ email, password });
      navigate(redirectTo, { replace: true });
    } catch (err) {
      if (err instanceof ApiError && err.status === 429) {
        setError("Too many login attempts. Try again in a few minutes.");
      } else {
        setError("Invalid email or password.");
      }
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <AuthLayout title="Sign in to Brain Buddy">
      {deletionScheduled ? (
        <p
          role="status"
          className="mb-4 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800"
        >
          Your account is deactivated and will be permanently deleted on{" "}
          {new Date(deletionScheduled).toLocaleDateString()}. Sign back in before then to cancel
          the deletion.
        </p>
      ) : null}
      <form className="flex flex-col gap-4" onSubmit={handleSubmit}>
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-slate-700">Email</span>
          <input
            type="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="rounded-md border border-slate-200 bg-white px-3 py-2 text-slate-900 shadow-soft transition-colors duration-200 ease-smooth focus:border-brand-primary focus:outline-none"
            autoComplete="email"
          />
        </label>
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-slate-700">Password</span>
          <input
            type="password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="rounded-md border border-slate-200 bg-white px-3 py-2 text-slate-900 shadow-soft transition-colors duration-200 ease-smooth focus:border-brand-primary focus:outline-none"
            autoComplete="current-password"
          />
        </label>
        {error ? <p className="text-sm text-rose-600">{error}</p> : null}
        <Button type="submit" variant="primary" size="md" isLoading={submitting}>
          Sign in
        </Button>
        <p className="text-center text-xs text-slate-500">
          Have an invite code?{" "}
          <Link to="/signup" className="text-brand-primary underline">
            Create an account
          </Link>
        </p>
      </form>
    </AuthLayout>
  );
}

export function AuthLayout({
  title,
  children
}: {
  title: string;
  children: React.ReactNode;
}): React.JSX.Element {
  return (
    <div className="flex min-h-screen items-center justify-center bg-surface-base px-4">
      <div className="w-full max-w-sm rounded-2xl border border-slate-200 bg-surface-raised p-7 shadow-raised">
        <div className="mb-3 flex items-center justify-center gap-2 text-subtitle font-semibold text-slate-900">
          <Sprout className="h-5 w-5 text-brand-primary" aria-hidden="true" />
          <span>Brain Buddy</span>
        </div>
        <h1 className="mb-5 text-center text-title font-semibold text-slate-900">
          {title}
        </h1>
        {children}
        <p className="mt-4 text-center text-xs text-slate-400">
          <Link to="/privacy" className="underline">
            Privacy policy
          </Link>
        </p>
      </div>
    </div>
  );
}
