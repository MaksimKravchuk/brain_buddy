import { useLayoutEffect, useRef } from "react";

export function useTaskCompletionAnimation(scope: string, view: string) {
  const containerRef = useRef<HTMLDivElement>(null);
  const context = `${scope}:${view}`;
  const contextRef = useRef(context);
  const animations = useRef(new Map<HTMLElement, Animation>());
  // Each list is an `overflow-hidden` card, so a row travelling into another
  // list would be clipped by its new card and appear to wipe in from an edge.
  // The cards are unclipped only while a row is in flight.
  const unclipped = useRef(new Set<HTMLElement>());
  const restoreClipping = () => {
    unclipped.current.forEach((list) => { list.style.overflow = ""; });
    unclipped.current.clear();
  };
  const pending = useRef<{
    taskId: string;
    rectangles: Map<string, DOMRect>;
    focusedButton: HTMLElement | null;
  } | null>(null);

  const rows = () => Array.from(containerRef.current?.querySelectorAll<HTMLElement>("[data-task-id]") ?? []);

  const capture = (taskId: string, focusedButton: HTMLElement | null = null) => {
    if (contextRef.current !== context) return;
    const currentRows = rows();
    const completing = currentRows.find((row) => row.dataset.taskId === taskId);
    if (!completing || completing.dataset.taskState === "completed" || completing.dataset.taskState === "cancelled") return;
    const active = document.activeElement;
    pending.current = {
      taskId,
      rectangles: new Map(currentRows.map((row) => [row.dataset.taskId ?? "", row.getBoundingClientRect()])),
      focusedButton: focusedButton ?? (active instanceof HTMLButtonElement && completing.contains(active) ? active : null)
    };
  };

  useLayoutEffect(() => {
    const cancelAnimations = () => {
      animations.current.forEach((animation) => animation.cancel());
      animations.current.clear();
      restoreClipping();
    };
    if (contextRef.current !== context) {
      contextRef.current = context;
      pending.current = null;
      cancelAnimations();
      return;
    }
    const snapshot = pending.current;
    if (!snapshot) return;
    const currentRows = rows();
    const completed = currentRows.find((row) => row.dataset.taskId === snapshot.taskId);
    if (completed?.dataset.taskState !== "completed") return;
    pending.current = null;
    // Capture uses current visual rectangles, including an unfinished transform.
    // Cancel only now, so the next rectangles describe the final layout.
    cancelAnimations();
    if (!window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      for (const row of currentRows) {
        const previous = snapshot.rectangles.get(row.dataset.taskId ?? "");
        if (!previous) continue;
        const current = row.getBoundingClientRect();
        const x = previous.left - current.left;
        const y = previous.top - current.top;
        if (x === 0 && y === 0) continue;
        const list = row.closest<HTMLElement>('[role="list"]');
        if (list && !unclipped.current.has(list)) {
          list.style.overflow = "visible";
          unclipped.current.add(list);
        }
        const animation = row.animate([
          { transform: `translate(${x}px, ${y}px)` },
          { transform: "translate(0px, 0px)" }
        ], { duration: 380, easing: "cubic-bezier(0.22, 1, 0.36, 1)" });
        animations.current.set(row, animation);
        animation.onfinish = () => {
          animations.current.delete(row);
          if (animations.current.size === 0) restoreClipping();
        };
      }
    }
    if (snapshot.focusedButton && (document.activeElement === document.body || document.activeElement === snapshot.focusedButton)) {
      completed.querySelector<HTMLAnchorElement>("a")?.focus({ preventScroll: true });
    }
  });

  useLayoutEffect(() => {
    const activeAnimations = animations.current;
    const activeUnclipped = unclipped.current;
    return () => {
      activeAnimations.forEach((animation) => animation.cancel());
      activeAnimations.clear();
      activeUnclipped.forEach((list) => { list.style.overflow = ""; });
      activeUnclipped.clear();
    };
  }, []);

  return { containerRef, capture };
}
