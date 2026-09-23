import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import { ApiError } from "../../api/client";
import { crtApi } from "../../api/crt";
import { useAuthStore } from "../../stores/authStore";
import { CrtWorkspace } from "./CrtWorkspace";

type ExposureState =
  | { kind: "checking" }
  | { kind: "exposed" }
  | { kind: "disabled" }
  | { kind: "degraded"; referenceId?: string };

const MINIMUM_CRT_WIDTH = 1024;

function exposureReason(error: unknown): string | undefined {
  if (!(error instanceof ApiError) || typeof error.payload !== "object" || error.payload === null) {
    return undefined;
  }

  const payload = error.payload as { detail?: unknown; reason?: unknown };
  if (typeof payload.reason === "string") {
    return payload.reason;
  }
  if (typeof payload.detail === "object" && payload.detail !== null) {
    const detail = payload.detail as { reason?: unknown };
    return typeof detail.reason === "string" ? detail.reason : undefined;
  }
  return undefined;
}

function classifyExposureError(error: unknown): ExposureState {
  if (error instanceof ApiError && error.status === 404 && exposureReason(error) === "crt_canvas_disabled") {
    return { kind: "disabled" };
  }
  return {
    kind: "degraded",
    referenceId: error instanceof ApiError ? error.correlationId : undefined
  };
}

type UnsupportedWidthBoundaryProps = Readonly<{
  headingRef: React.RefObject<HTMLHeadingElement | null>;
  onBack: () => void;
}>;

function UnsupportedWidthBoundary({ headingRef, onBack }: UnsupportedWidthBoundaryProps): React.JSX.Element {
  return (
    <main className="flex min-h-screen w-full max-w-full items-center justify-center overflow-x-hidden bg-surface-base px-6 text-center">
      <section className="w-full max-w-md rounded-2xl border border-slate-200 bg-white px-8 py-10 shadow-raised">
        <p className="text-xs font-semibold uppercase tracking-[0.06em] text-brand-primary">Thinking Mode</p>
        <h1 ref={headingRef} tabIndex={-1} className="mt-2 text-title font-semibold text-slate-900">
          Thinking Mode needs a wider window
        </h1>
        <p className="mt-2 text-sm text-slate-600">
          Use a window at least 1024 px wide to edit this tree. Your BrainBuddy tasks and saved trees are unchanged.
        </p>
        <button
          type="button"
          className="mt-6 w-full rounded-lg bg-brand-primary px-4 py-3 text-sm font-semibold text-white"
          onClick={onBack}
        >
          Back to Tasks
        </button>
        <p className="mt-3 text-xs text-slate-500">The canvas is not loaded at this width.</p>
      </section>
    </main>
  );
}

export function CrtGate(): React.JSX.Element {
  const user = useAuthStore((state) => state.user);
  const navigate = useNavigate();
  const headingRef = useRef<HTMLHeadingElement>(null);
  const lastExposedUserRef = useRef<typeof user>(null);
  const hasExposedUserRef = useRef(false);
  const [isSupportedWidth, setIsSupportedWidth] = useState(
    () => typeof window === "undefined" || window.innerWidth >= MINIMUM_CRT_WIDTH
  );
  const [retryCount, setRetryCount] = useState(0);
  const [exposure, setExposure] = useState<ExposureState>({ kind: "checking" });

  useEffect(() => {
    const handleResize = () => {
      setIsSupportedWidth(window.innerWidth >= MINIMUM_CRT_WIDTH);
    };

    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, []);

  useEffect(() => {
    const exposedUserChanged = hasExposedUserRef.current && lastExposedUserRef.current !== user;
    if (!isSupportedWidth && !exposedUserChanged) {
      return;
    }
    if (hasExposedUserRef.current && lastExposedUserRef.current === user) {
      return;
    }

    const controller = new AbortController();
    let active = true;
    setExposure({ kind: "checking" });

    void crtApi.probeCrtExposure(controller.signal).then(
      () => {
        if (active) {
          hasExposedUserRef.current = true;
          lastExposedUserRef.current = user;
          setExposure({ kind: "exposed" });
        }
      },
      (error: unknown) => {
        if (!active) {
          return;
        }
        setExposure(classifyExposureError(error));
      }
    );

    return () => {
      active = false;
      controller.abort();
    };
  }, [retryCount, user, isSupportedWidth]);

  useEffect(() => {
    if (!isSupportedWidth || exposure.kind === "disabled" || exposure.kind === "degraded") {
      headingRef.current?.focus();
    }
  }, [exposure.kind, isSupportedWidth]);

  if (!isSupportedWidth && exposure.kind !== "exposed") {
    return <UnsupportedWidthBoundary headingRef={headingRef} onBack={() => navigate("/")} />;
  }

  if (exposure.kind === "checking") {
    return (
      <main className="flex min-h-screen items-center justify-center bg-surface-base px-6 text-center">
        <section aria-live="polite" className="rounded-2xl border border-slate-200 bg-white px-8 py-10 shadow-raised">
          <h1 ref={headingRef} tabIndex={-1} className="text-title font-semibold text-slate-900">
            Checking Thinking Mode access…
          </h1>
          <p className="mt-2 text-sm text-slate-600" role="status">
            No tree content is loaded until access is confirmed.
          </p>
        </section>
      </main>
    );
  }

  if (exposure.kind === "disabled") {
    return (
      <main className="flex min-h-screen items-center justify-center bg-surface-base px-6 text-center">
        <section className="rounded-2xl border border-slate-200 bg-white px-8 py-10 shadow-raised">
          <p className="text-xs font-semibold uppercase tracking-[0.06em] text-brand-primary">Thinking Mode</p>
          <h1 ref={headingRef} tabIndex={-1} className="mt-2 text-title font-semibold text-slate-900">
            Thinking Mode isn't available for this account
          </h1>
          <p className="mt-2 max-w-md text-sm text-slate-600">
            Existing BrainBuddy work is unchanged.
          </p>
          <button
            type="button"
            className="mt-6 rounded-lg bg-brand-primary px-4 py-2 text-sm font-semibold text-white"
            onClick={() => navigate("/")}
          >
            Back to Tasks
          </button>
        </section>
      </main>
    );
  }

  if (exposure.kind === "degraded") {
    return (
      <main className="flex min-h-screen items-center justify-center bg-surface-base px-6 text-center">
        <section aria-live="polite" className="rounded-2xl border border-amber-200 bg-white px-8 py-10 shadow-raised">
          <p className="text-xs font-semibold uppercase tracking-[0.06em] text-amber-700">Thinking Mode</p>
          <h1 ref={headingRef} tabIndex={-1} className="mt-2 text-title font-semibold text-slate-900">
            Thinking Mode is temporarily unavailable
          </h1>
          <p className="mt-2 max-w-md text-sm text-slate-600">We couldn't check access safely.</p>
          {exposure.referenceId ? (
            <label className="mt-4 block text-left text-xs font-semibold text-slate-600">
              Support reference
              <input
                aria-label="Support reference"
                className="mt-1 block w-full rounded border border-slate-300 px-2 py-1 font-mono text-xs text-slate-700"
                readOnly
                value={exposure.referenceId}
                onFocus={(event) => event.currentTarget.select()}
              />
            </label>
          ) : null}
          <div className="mt-6 flex justify-center gap-3">
            <button
              type="button"
              className="rounded-lg bg-brand-primary px-4 py-2 text-sm font-semibold text-white"
              onClick={() => {
                setExposure({ kind: "checking" });
                setRetryCount((count) => count + 1);
              }}
            >
              Retry
            </button>
            <button
              type="button"
              className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-semibold text-slate-700"
              onClick={() => navigate("/")}
            >
              Back to Tasks
            </button>
          </div>
        </section>
      </main>
    );
  }

  return (
    <>
      <div hidden={!isSupportedWidth} aria-hidden={!isSupportedWidth}>
        <CrtWorkspace />
      </div>
      {!isSupportedWidth ? <UnsupportedWidthBoundary headingRef={headingRef} onBack={() => navigate("/")} /> : null}
    </>
  );
}
