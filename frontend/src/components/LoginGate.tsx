import { type FormEvent, type ReactNode, useState } from "react";

import { apiClient, hasApiKey, setApiKey } from "../api/client";
import { useMe } from "../api/hooks";

interface LoginGateProps {
  children: ReactNode;
}

export function LoginGate({ children }: LoginGateProps): JSX.Element {
  const meQuery = useMe();

  if (hasApiKey() && meQuery.isLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center text-sm text-slate-500">
        Authenticating…
      </div>
    );
  }

  if (hasApiKey() && meQuery.isSuccess) {
    return <>{children}</>;
  }

  return <ApiKeyForm error={meQuery.error ? "Invalid API key. Please try again." : undefined} />;
}

function ApiKeyForm({ error: externalError }: { error?: string }): JSX.Element {
  const [key, setKey] = useState("");
  const [validating, setValidating] = useState(false);
  const [error, setError] = useState<string | null>(externalError ?? null);

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    const trimmed = key.trim();
    if (!trimmed) {
      return;
    }

    setValidating(true);
    setError(null);
    setApiKey(trimmed);

    try {
      await apiClient.getMe();
      window.location.reload();
    } catch {
      setApiKey(null);
      setError("Invalid API key. Please try again.");
      setValidating(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-surface-base">
      <form
        onSubmit={handleSubmit}
        className="w-full max-w-sm rounded-xl border border-slate-200 bg-white p-8 shadow-lg"
      >
        <h1 className="mb-2 text-xl font-bold text-slate-900">Brain Buddy</h1>
        <p className="mb-6 text-sm text-slate-500">Enter your API key to continue.</p>

        <label htmlFor="api-key-input" className="mb-1 block text-xs font-medium text-slate-700">
          API Key
        </label>
        <input
          id="api-key-input"
          type="password"
          value={key}
          onChange={(e) => setKey(e.target.value)}
          placeholder="your-api-key"
          autoFocus
          className="mb-4 w-full rounded-md border border-slate-300 px-3 py-2 text-sm shadow-sm focus:border-brand-primary focus:outline-none focus:ring-2 focus:ring-brand-primary/20"
        />

        {error && <p className="mb-3 text-xs text-red-600">{error}</p>}

        <button
          type="submit"
          disabled={validating || !key.trim()}
          className="w-full rounded-md bg-brand-primary px-4 py-2 text-sm font-semibold text-white shadow-sm transition hover:bg-brand-primary/90 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {validating ? "Verifying…" : "Sign in"}
        </button>
      </form>
    </div>
  );
}
