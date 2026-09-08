import { createElement, useEffect } from "react";
import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useTaskCompletionAnimation } from "../useTaskCompletionAnimation";

let capture: (id: string) => void;
let reduced = false;
const motions: Array<{ element: HTMLElement; frames: Keyframe[]; options: KeyframeAnimationOptions; cancel: ReturnType<typeof vi.fn>; finish: () => void }> = [];
const visualTops = new Map<string, number>();

function Harness({ completed = false, secondCompleted = false, scope = "owner-a", view = "next" }: {
  completed?: boolean;
  secondCompleted?: boolean;
  scope?: string;
  view?: string;
}) {
  const animation = useTaskCompletionAnimation(scope, view);
  // Expose the hook's API to the test after commit rather than during render
  // (react-hooks/globals); RTL's act() flushes this effect before render() returns.
  useEffect(() => {
    capture = animation.capture;
  });
  const row = (id: string, done: boolean, top: number) => createElement("article", {
    key: id, "data-task-id": id, "data-task-state": done ? "completed" : "next", "data-top": top
  }, done ? createElement("span", null, "Completed") : createElement("button", { "aria-label": `Complete ${id}` }, "Complete"), createElement("a", { href: `#${id}` }, id));
  return createElement("div", { ref: animation.containerRef },
    createElement("section", { key: "open" }, !completed && row("first", false, 0), !secondCompleted && row("second", false, completed ? 0 : 50)),
    createElement("section", { key: "completed" }, completed && row("first", true, secondCompleted ? 0 : 70), secondCompleted && row("second", true, 70))
  );
}

beforeEach(() => {
  motions.length = 0;
  visualTops.clear();
  reduced = false;
  vi.stubGlobal("matchMedia", vi.fn(() => ({ matches: reduced, addEventListener: vi.fn(), removeEventListener: vi.fn() })));
  vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(function (this: HTMLElement) {
    const top = visualTops.get(this.dataset.taskId ?? "") ?? Number(this.dataset.top ?? 0);
    return { x: 0, y: top, left: 0, top, right: 200, bottom: top + 40, width: 200, height: 40, toJSON: () => ({}) };
  });
  Object.defineProperty(HTMLElement.prototype, "animate", { configurable: true, value: vi.fn(function (this: HTMLElement, frames: Keyframe[], options: KeyframeAnimationOptions) {
    const animation = { cancel: vi.fn(), onfinish: null as (() => void) | null };
    motions.push({ element: this, frames, options, cancel: animation.cancel, finish: () => animation.onfinish?.() });
    return animation;
  }) });
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  delete (HTMLElement.prototype as Partial<HTMLElement>).animate;
});

describe("016 canonical completion movement", () => {
  it("016-FR-002 016-SC-002 moves the real completed row across parents and displaced controls over 380ms", () => {
    const page = render(createElement(Harness));
    expect(motions).toHaveLength(0);
    act(() => capture("first"));
    expect(motions).toHaveLength(0);
    page.rerender(createElement(Harness, { completed: true }));
    expect(motions).toHaveLength(2);
    expect(motions.find((motion) => motion.element.dataset.taskId === "first")?.frames).toEqual([{ transform: "translate(0px, -70px)" }, { transform: "translate(0px, 0px)" }]);
    expect(motions.find((motion) => motion.element.dataset.taskId === "second")?.frames).toEqual([{ transform: "translate(0px, 50px)" }, { transform: "translate(0px, 0px)" }]);
    for (const motion of motions) {
      expect(motion.options).toMatchObject({ duration: 380, easing: "cubic-bezier(0.22, 1, 0.36, 1)" });
      expect(document.contains(motion.element)).toBe(true);
      expect(motion.element.style.pointerEvents).not.toBe("none");
    }
    expect(screen.getAllByRole("link")).toHaveLength(2);
  });

  it("016-FR-003 transfers a removed completion button's focus without scrolling even across grouped parents", () => {
    const page = render(createElement(Harness));
    screen.getByRole("button", { name: "Complete first" }).focus();
    const focus = vi.spyOn(HTMLElement.prototype, "focus");
    act(() => capture("first"));
    page.rerender(createElement(Harness, { completed: true }));
    expect(screen.getByRole("link", { name: "first" })).toHaveFocus();
    expect(focus).toHaveBeenLastCalledWith({ preventScroll: true });
  });

  it("016-FR-002 016-SC-002 replaces overlapping animations from current visual positions", () => {
    const page = render(createElement(Harness));
    act(() => capture("first"));
    page.rerender(createElement(Harness, { completed: true }));
    const previous = [...motions];
    visualTops.set("first", 30);
    visualTops.set("second", 25);
    act(() => capture("second"));
    visualTops.clear();
    page.rerender(createElement(Harness, { completed: true, secondCompleted: true }));
    expect(motions).toHaveLength(4);
    for (const motion of previous) expect(motion.cancel).toHaveBeenCalledTimes(1);
    expect(motions[motions.length - 1]?.frames[0]).toEqual({ transform: "translate(0px, -45px)" });
    page.unmount();
    for (const motion of motions.slice(2)) expect(motion.cancel).toHaveBeenCalledTimes(1);
  });

  it("016-FR-002 applies reduced-motion ordering instantly while retaining keyboard focus", () => {
    reduced = true;
    const page = render(createElement(Harness));
    screen.getByRole("button", { name: "Complete first" }).focus();
    act(() => capture("first"));
    page.rerender(createElement(Harness, { completed: true }));
    expect(motions).toHaveLength(0);
    expect(screen.getByRole("link", { name: "first" })).toHaveFocus();
  });

  it("016-FR-002 does not replay motion for load, filter, paging or a stale owner's capture", () => {
    const page = render(createElement(Harness, { completed: true }));
    page.rerender(createElement(Harness));
    page.rerender(createElement(Harness, { completed: true }));
    expect(motions).toHaveLength(0);
    page.rerender(createElement(Harness));
    act(() => capture("first"));
    page.rerender(createElement(Harness, { completed: true, view: "tag" }));
    expect(motions).toHaveLength(0);
    page.rerender(createElement(Harness));
    const oldCapture = capture;
    page.rerender(createElement(Harness, { scope: "owner-b" }));
    act(() => oldCapture("first"));
    page.rerender(createElement(Harness, { completed: true, scope: "owner-b" }));
    expect(motions).toHaveLength(0);
  });
});
