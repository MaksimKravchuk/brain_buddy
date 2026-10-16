import { useCallback, useEffect, useRef, useState } from "react";

import { setUpdateRequiredHandler } from "../../api/client";
import type { UpdateRequiredNotice } from "../../api/client";
import { isTextEntryTarget, UPDATE_REQUIRED_MESSAGE } from "./shellToast";

/**
 * 027 D-02: the persistent update-required alert. It never auto-dismisses and
 * never takes focus; one shows at a time and a later refusal shows it again.
 * Mount it right after the top bar so DOM order matches its place at top centre.
 */
export function UpdateRequiredToast({
  onReload = () => window.location.reload()
}: {
  onReload?: () => void;
}): React.JSX.Element | null {
  const [notice, setNotice] = useState<UpdateRequiredNotice | null>(null);
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setUpdateRequiredHandler(setNotice);
    return () => setUpdateRequiredHandler(null);
  }, []);

  const dismiss = useCallback(() => {
    if (rootRef.current?.contains(document.activeElement)) {
      document.querySelector<HTMLElement>("header button, header a")?.focus();
    }
    setNotice(null);
  }, []);

  useEffect(() => {
    if (!notice) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      const inside = rootRef.current?.contains(event.target as Node) ?? false;
      if (!inside && (isTextEntryTarget(event.target) || document.querySelector('[role="dialog"], dialog[open]'))) return;
      dismiss();
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [notice, dismiss]);

  if (!notice) return null;
  const text = `${notice.message || UPDATE_REQUIRED_MESSAGE}${notice.referenceId ? ` (ref: ${notice.referenceId})` : ""}`;
  return (
    <div
      ref={rootRef}
      role="alert"
      className="fixed left-1/2 top-16 z-[200] flex max-w-[calc(100vw-2rem)] -translate-x-1/2 items-center gap-2 co-glass-dense rounded-card py-1 pl-4 pr-1 text-co-meta text-ink motion-safe:animate-fade-in-up"
    >
      <span className="min-w-0">{text}</span>
      <button
        type="button"
        className="inline-flex min-h-11 min-w-11 shrink-0 items-center justify-center rounded-lg px-3 text-co-meta font-semibold text-ink hover:bg-quiet"
        onClick={onReload}
      >
        Reload
      </button>
      <button
        type="button"
        className="inline-flex min-h-11 min-w-11 shrink-0 items-center justify-center rounded-lg px-3 text-co-meta font-semibold text-ink-muted hover:bg-sunken"
        onClick={dismiss}
      >
        Dismiss
      </button>
    </div>
  );
}
