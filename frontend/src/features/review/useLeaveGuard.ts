/**
 * Leave guard for the decision dialog (FR-052, design D-02 "browser Back /
 * route change", plan US1 "Web").
 *
 * The app uses the declarative `BrowserRouter`, so react-router's `useBlocker`
 * is not available. Instead the dialog pushes one history entry (same URL, the
 * router's own state kept) when it opens; browser Back pops that entry and is
 * reported as `onBack`, which the dialog treats exactly like Close (asking
 * first when a field is dirty, and calling `rearm` on "Keep editing"). Closing
 * any other way pops the entry again. While a field is dirty, a tab close or
 * reload gets the browser's leave warning. In-app links, dirty or not, are
 * reported as `onNavigate` instead of being followed, so the dialog can
 * replace its entry with the link's route.
 */
import { useCallback, useEffect, useLayoutEffect, useRef } from "react";

export interface LeaveGuardTarget {
  history: Pick<History, "pushState" | "back" | "state">;
  location: Pick<Location, "href" | "origin">;
  addEventListener: Window["addEventListener"];
  removeEventListener: Window["removeEventListener"];
  dispatchEvent: Window["dispatchEvent"];
}

const MARKER = "bbReviewDialog";
let tokens = 0;

function stateRecord(state: unknown): Record<string, unknown> {
  return typeof state === "object" && state !== null ? (state as Record<string, unknown>) : {};
}

export function useLeaveGuard({
  dirty,
  onBack,
  onNavigate,
  target = window
}: {
  dirty: boolean;
  /** Browser Back left the dialog's entry: handle it as Close. */
  onBack: () => void;
  /**
   * A same-origin link was clicked; it was not followed. The caller asks
   * first when dirty, then calls `release` and navigates with `replace`.
   */
  onNavigate?: (href: string) => void;
  target?: LeaveGuardTarget;
}): { rearm: () => void; release: () => void } {
  const latest = useRef({ dirty, onBack, onNavigate });
  useLayoutEffect(() => {
    latest.current = { dirty, onBack, onNavigate };
  });
  const tokenRef = useRef("");
  const armedRef = useRef(false);

  const push = useCallback(() => {
    target.history.pushState({ ...stateRecord(target.history.state), [MARKER]: tokenRef.current }, "", target.location.href);
    armedRef.current = true;
  }, [target]);

  useEffect(() => {
    tokens += 1;
    tokenRef.current = `review-dialog-${tokens}`;
    push();
    const onOurEntry = () => stateRecord(target.history.state)[MARKER] === tokenRef.current;
    const onPopState = () => {
      if (!armedRef.current || onOurEntry()) {
        return;
      }
      armedRef.current = false;
      latest.current.onBack();
    };
    const onBeforeUnload = (event: BeforeUnloadEvent) => {
      if (latest.current.dirty) {
        event.preventDefault();
        event.returnValue = "";
      }
    };
    // Every same-origin link goes through `onNavigate`, dirty or not: the
    // dialog decides whether to ask, and then replaces its own entry with the
    // link's route, so Back afterwards does not land on that entry first.
    const onClick = (event: MouseEvent) => {
      const navigate = latest.current.onNavigate;
      const modified = event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey;
      if (!navigate || event.defaultPrevented || modified) {
        return;
      }
      const anchor = event.target instanceof Element ? event.target.closest("a[href]") : null;
      if (!(anchor instanceof HTMLAnchorElement) || anchor.target === "_blank" || anchor.origin !== target.location.origin) {
        return;
      }
      event.preventDefault();
      event.stopPropagation();
      navigate(`${anchor.pathname}${anchor.search}${anchor.hash}`);
    };
    target.addEventListener("popstate", onPopState);
    target.addEventListener("beforeunload", onBeforeUnload);
    target.addEventListener("click", onClick, true);
    return () => {
      target.removeEventListener("popstate", onPopState);
      target.removeEventListener("beforeunload", onBeforeUnload);
      target.removeEventListener("click", onClick, true);
      if (armedRef.current && onOurEntry()) {
        target.history.back();
      }
      armedRef.current = false;
    };
  }, [push, target]);

  const release = useCallback(() => {
    armedRef.current = false;
  }, []);
  return { rearm: push, release };
}
