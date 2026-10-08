import { act, fireEvent, render, renderHook, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useLeaveGuard, type LeaveGuardTarget } from "../useLeaveGuard";

/** A history with real entries, whose Back pops one and fires popstate. */
function fakeTarget(href = "http://localhost:3000/tasks/next", initialState: unknown = { idx: 3, key: "k3" }) {
  const events = new EventTarget();
  const entries: Array<{ state: unknown; url: string }> = [{ state: initialState, url: href }];
  let index = 0;
  const history = {
    get state() {
      return entries[index].state;
    },
    get length() {
      return entries.length;
    },
    pushState: vi.fn((state: unknown, _title: string, url?: string | URL | null) => {
      entries.splice(index + 1);
      entries.push({ state, url: String(url ?? entries[index].url) });
      index += 1;
    }),
    back: vi.fn(() => {
      if (index === 0) return;
      index -= 1;
      events.dispatchEvent(new PopStateEvent("popstate", { state: entries[index].state }));
    })
  };
  const target = Object.assign(events, {
    history,
    location: { get href() { return entries[index].url; }, origin: "http://localhost:3000" }
  }) as unknown as LeaveGuardTarget;
  /** The person pressing the browser's Back button. */
  const pressBack = () => act(() => history.back());
  return { target, history, entries: () => entries.slice(0, index + 1), pressBack };
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("020-FR-052 leave guard for the decision dialog", () => {
  it("020-FR-052 pushes one history entry on open, keeping the URL and the router's state", () => {
    const { target, history, entries } = fakeTarget();
    renderHook(() => useLeaveGuard({ dirty: false, onBack: vi.fn(), target }));

    expect(history.pushState).toHaveBeenCalledTimes(1);
    expect(entries()).toHaveLength(2);
    expect(entries()[1].url).toBe("http://localhost:3000/tasks/next");
    expect(entries()[1].state).toMatchObject({ idx: 3, key: "k3" });
  });

  it("020-FR-052 works from an entry the router has not stamped yet", () => {
    const { target, entries, pressBack } = fakeTarget("http://localhost:3000/tasks/next", null);
    const onBack = vi.fn();
    renderHook(() => useLeaveGuard({ dirty: false, onBack, target }));

    expect(entries()).toHaveLength(2);
    pressBack();
    expect(onBack).toHaveBeenCalledTimes(1);
  });

  it("020-FR-052 treats browser Back as Close, and only once", () => {
    const { target, pressBack } = fakeTarget();
    const onBack = vi.fn();
    renderHook(() => useLeaveGuard({ dirty: false, onBack, target }));

    // A popstate that lands on the dialog's own entry (Forward) is not a Back.
    act(() => target.dispatchEvent(new PopStateEvent("popstate", { state: null })));
    expect(onBack).not.toHaveBeenCalled();

    pressBack();
    expect(onBack).toHaveBeenCalledTimes(1);

    // A popstate that is not leaving our entry (another listener's own
    // navigation) is not a second Back.
    act(() => target.dispatchEvent(new PopStateEvent("popstate", { state: null })));
    expect(onBack).toHaveBeenCalledTimes(1);
  });

  it("020-FR-052 re-pushes the entry when the person keeps editing after Back", () => {
    const { target, history, entries, pressBack } = fakeTarget();
    const onBack = vi.fn();
    const { result } = renderHook(() => useLeaveGuard({ dirty: true, onBack, target }));

    pressBack();
    expect(onBack).toHaveBeenCalledTimes(1);
    act(() => result.current.rearm());
    expect(history.pushState).toHaveBeenCalledTimes(2);
    expect(entries()).toHaveLength(2);

    pressBack();
    expect(onBack).toHaveBeenCalledTimes(2);
  });

  it("020-FR-052 removes its own entry when the dialog closes another way", () => {
    const { target, history, entries } = fakeTarget();
    const onBack = vi.fn();
    const { unmount } = renderHook(() => useLeaveGuard({ dirty: false, onBack, target }));

    unmount();

    expect(history.back).toHaveBeenCalledTimes(1);
    expect(entries()).toHaveLength(1);
    expect(onBack).not.toHaveBeenCalled();
  });

  it("020-FR-052 leaves history alone on close when Back already consumed the entry, or the route moved on", () => {
    const consumed = fakeTarget();
    const first = renderHook(() => useLeaveGuard({ dirty: false, onBack: vi.fn(), target: consumed.target }));
    consumed.pressBack();
    first.unmount();
    expect(consumed.history.back).toHaveBeenCalledTimes(1);

    const moved = fakeTarget();
    const second = renderHook(() => useLeaveGuard({ dirty: false, onBack: vi.fn(), target: moved.target }));
    act(() => moved.history.pushState({ idx: 4, key: "k4" }, "", "http://localhost:3000/crt"));
    second.unmount();
    expect(moved.history.back).not.toHaveBeenCalled();
  });

  it("020-FR-052 lets a release hand the entry to the router instead of popping it", () => {
    const { target, history } = fakeTarget();
    const { result, unmount } = renderHook(() => useLeaveGuard({ dirty: false, onBack: vi.fn(), target }));

    act(() => result.current.release());
    unmount();

    expect(history.back).not.toHaveBeenCalled();
  });

  it("020-FR-052 warns before the tab closes or reloads, only while a field is dirty", () => {
    const { target } = fakeTarget();
    const { rerender } = renderHook(({ dirty }) => useLeaveGuard({ dirty, onBack: vi.fn(), target }), {
      initialProps: { dirty: false }
    });

    const clean = new Event("beforeunload", { cancelable: true });
    target.dispatchEvent(clean);
    expect(clean.defaultPrevented).toBe(false);

    rerender({ dirty: true });
    const dirty = new Event("beforeunload", { cancelable: true });
    target.dispatchEvent(dirty);
    expect(dirty.defaultPrevented).toBe(true);
  });

  it("020-FR-052 sends in-app links through the same check while dirty, and lets everything else through", () => {
    const onNavigate = vi.fn();
    const { rerender } = render(<Links dirty onNavigate={onNavigate} />);

    const internal = screen.getByRole("link", { name: "Think it through" });
    const allowed = fireEvent.click(internal);
    expect(allowed).toBe(false);
    expect(onNavigate).toHaveBeenCalledWith("/crt");

    expect(fireEvent.click(screen.getByRole("link", { name: "Elsewhere" }))).toBe(true);
    expect(fireEvent.click(screen.getByRole("link", { name: "New tab" }))).toBe(true);
    for (const modifier of [{ metaKey: true }, { ctrlKey: true }, { shiftKey: true }, { altKey: true }, { button: 1 }]) {
      expect(fireEvent.click(internal, modifier)).toBe(true);
    }
    expect(fireEvent.click(screen.getByRole("button", { name: "Not a link" }))).toBe(true);
    act(() => {
      window.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
    });
    const handledElsewhere = new MouseEvent("click", { bubbles: true, cancelable: true });
    handledElsewhere.preventDefault();
    internal.dispatchEvent(handledElsewhere);
    expect(onNavigate).toHaveBeenCalledTimes(1);

    rerender(<Links dirty={false} onNavigate={onNavigate} />);
    expect(onNavigate).toHaveBeenCalledTimes(1);
  });

  it("020-FR-052 020-FR-005 sends a clean in-app link through the guard too, so the dialog can hand over its history entry", () => {
    const onNavigate = vi.fn();
    render(<Links dirty={false} onNavigate={onNavigate} />);

    expect(fireEvent.click(screen.getByRole("link", { name: "Think it through" }))).toBe(false);
    expect(onNavigate).toHaveBeenCalledWith("/crt");
    expect(fireEvent.click(screen.getByRole("link", { name: "Elsewhere" }))).toBe(true);
    expect(onNavigate).toHaveBeenCalledTimes(1);
  });

  it("020-FR-052 guards the real browser window by default", () => {
    const pushState = vi.spyOn(window.history, "pushState");
    const back = vi.spyOn(window.history, "back").mockImplementation(() => undefined);
    const { unmount } = renderHook(() => useLeaveGuard({ dirty: true, onBack: vi.fn() }));

    expect(pushState).toHaveBeenCalledTimes(1);
    const leaving = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(leaving);
    expect(leaving.defaultPrevented).toBe(true);

    unmount();
    expect(back).toHaveBeenCalledTimes(1);
  });

  it("020-FR-052 lets a dirty in-app link through when no navigation handler is given", () => {
    render(<Links dirty />);
    expect(fireEvent.click(screen.getByRole("link", { name: "Think it through" }))).toBe(true);
  });
});

// Clicks reach the real window; history goes to a fake one.
const hybrid = {
  history: fakeTarget().target.history,
  location: { href: window.location.href, origin: window.location.origin },
  addEventListener: window.addEventListener.bind(window),
  removeEventListener: window.removeEventListener.bind(window),
  dispatchEvent: window.dispatchEvent.bind(window)
} as unknown as LeaveGuardTarget;
const noBack = vi.fn();

function Links({ dirty, onNavigate }: { dirty: boolean; onNavigate?: (href: string) => void }): React.JSX.Element {
  useLeaveGuard({ dirty, onBack: noBack, onNavigate, target: hybrid });
  return (
    <div>
      <a href="/crt">Think it through</a>
      <a href="https://example.com/away">Elsewhere</a>
      <a href="/crt" target="_blank">New tab</a>
      <button type="button">Not a link</button>
    </div>
  );
}
