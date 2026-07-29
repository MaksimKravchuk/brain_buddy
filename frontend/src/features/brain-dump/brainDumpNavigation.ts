import { useCallback } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import type { Location } from "react-router-dom";

// Brain dump is a modal over the workspace, not a screen of its own — matching
// `BBDumpOverlay` in the Claude Design prototype. It still owns a URL so a
// reload or a shared link can recover the operation (the URL is the only
// operation reference the client keeps), so its routes render the overlay *on
// top of* a background route rather than instead of it. `AppRoutes` reads
// `backgroundLocation` off the history entry to decide which view stays behind.
export interface BrainDumpLocationState {
  backgroundLocation?: Location;
}

/**
 * The location the workspace should return to when the overlay closes, or
 * `undefined` when this entry was opened directly (deep link, reload) and so has
 * nothing behind it in history.
 */
function useBrainDumpBackgroundLocation(): Location | undefined {
  const location = useLocation();
  return (location.state as BrainDumpLocationState | null)?.backgroundLocation;
}

/**
 * Dismisses the overlay. Steps back in history when it was opened from the
 * workspace so the underlying view and its scroll position are restored;
 * otherwise routes to the default list, since there is nothing to go back to.
 */
export function useCloseBrainDump(): () => void {
  const navigate = useNavigate();
  const background = useBrainDumpBackgroundLocation();

  return useCallback(() => {
    if (background) {
      navigate(-1);
      return;
    }
    navigate("/tasks/next", { replace: true });
  }, [background, navigate]);
}
