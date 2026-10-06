import { useRef, useState, type FormEvent } from "react";
import { Link, Navigate, useNavigate, useLocation } from "react-router-dom";

import { ApiError } from "../api/client";
import { Button } from "../components/ui/Button";
import { useAuthStore } from "../stores/authStore";
import { AuthLayout } from "./LoginPage";
import { AuthEntry } from "../features/auth/AuthEntry";

const PASSWORD_MIN_LENGTH = 12;

export default function SignupPage(): React.JSX.Element {
  const status = useAuthStore((state) => state.status);
  const signup = useAuthStore((state) => state.signup);
  const navigate = useNavigate();
  const location = useLocation();
  const [legacy, setLegacy] = useState(new URLSearchParams(location.search).get("invite") === "1");

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [inviteCode, setInviteCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const submittingRef = useRef(false);
  const [submitting, setSubmitting] = useState(false);

  if (status === "authed") {
    return <Navigate to="/" replace />;
  }

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    if (submittingRef.current) return;
    setError(null);

    if (password.length < PASSWORD_MIN_LENGTH) {
      setError(`Password must be at least ${PASSWORD_MIN_LENGTH} characters.`);
      return;
    }

    submittingRef.current = true;
    setSubmitting(true);
    try {
      await signup({ email, password, invite_code: inviteCode.trim() });
      navigate("/", { replace: true });
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.status === 400) {
          setError("Invite code is invalid or already used.");
        } else if (err.status === 409) {
          setError("An account with that email already exists.");
        } else {
          setError("Signup failed. Please try again.");
        }
      } else {
        setError("Signup failed. Please try again.");
      }
    } finally {
      submittingRef.current = false;
      setSubmitting(false);
    }
  };

  return (
    <AuthLayout title="Create your account">
      {!legacy ? <><AuthEntry destination="/" /><Button className="mt-4 min-h-11" onClick={() => setLegacy(true)}>Use a password and invite code</Button></> : <form className="flex flex-col gap-4" onSubmit={handleSubmit}>
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-slate-700">Email</span>
          <input
            type="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="min-h-11 rounded-md border border-slate-200 bg-white px-3 py-2 text-slate-900 shadow-soft transition-colors duration-200 ease-smooth focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-sky-700"
            autoComplete="email"
          />
        </label>
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-slate-700">Password</span>
          <input
            type="password"
            required
            minLength={PASSWORD_MIN_LENGTH}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="min-h-11 rounded-md border border-slate-200 bg-white px-3 py-2 text-slate-900 shadow-soft transition-colors duration-200 ease-smooth focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-sky-700"
            autoComplete="new-password"
          />
          <span className="text-xs text-slate-500">
            At least {PASSWORD_MIN_LENGTH} characters. Longer is better.
          </span>
        </label>
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-slate-700">Invite code</span>
          <input
            type="text"
            required
            value={inviteCode}
            onChange={(e) => setInviteCode(e.target.value)}
            className="min-h-11 rounded-md border border-slate-200 bg-white px-3 py-2 font-mono text-slate-900 shadow-soft transition-colors duration-200 ease-smooth focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-sky-700"
            autoComplete="off"
          />
        </label>
        {error ? <p role="alert" className="text-sm text-rose-700">{error}</p> : null}
        <Button className="min-h-11" type="submit" variant="primary" size="md" isLoading={submitting}>
          Create account
        </Button>
        <p className="text-center text-xs text-slate-500">
          Already have an account?{" "}
          <Link to="/login" className="text-brand-primary underline">
            Sign in
          </Link>
        </p>
      </form>}
    </AuthLayout>
  );
}
