import { type ReactNode } from "react";
import { render } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { TreeCanvas } from "../TreeCanvas";
import { useTreeStore } from "../../../stores/treeStore";
import { useUiStore } from "../../../stores/uiStore";

vi.mock("reactflow", () => ({
  __esModule: true,
  default: ({ children }: { children?: ReactNode }) => <div data-testid="reactflow">{children}</div>,
  Background: () => <div data-testid="background" />,
  MarkerType: { ArrowClosed: "arrow" },
  Position: { Top: "top", Bottom: "bottom" }
}));

vi.mock("../../../hooks/useGraphProfiler", () => ({
  useGraphProfiler: () => {}
}));

vi.mock("../BrainNode", () => ({
  BrainNode: () => <div data-testid="brain-node" />
}));

vi.mock("../../../api/hooks", () => ({
  useCreateNode: () => ({ mutate: vi.fn() }),
  useUpdateNode: () => ({ mutate: vi.fn() }),
  useDeleteNode: () => ({ mutate: vi.fn() }),
  useCreateRelation: () => ({ mutate: vi.fn() }),
  useDeleteRelation: () => ({ mutate: vi.fn() })
}));

describe("TreeCanvas hotkeys", () => {
  const registerHotkey = vi.fn();
  const unregisterHotkey = vi.fn();
  const triggerHotkey = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
    useTreeStore.getState().reset();
    useUiStore.setState((state) => ({
      ...state,
      hotkeys: {},
      lastShortcut: null,
      registerHotkey,
      unregisterHotkey,
      triggerHotkey
    }));
  });

  it("ignores Enter and Tab when nothing is selected", () => {
    render(<TreeCanvas treeId="tree-1" isLoading={false} />);

    const target = document.createElement("div");
    document.body.appendChild(target);

    const enterEvent = new KeyboardEvent("keydown", { key: "Enter", bubbles: true, cancelable: true });
    target.dispatchEvent(enterEvent);

    const tabEvent = new KeyboardEvent("keydown", { key: "Tab", bubbles: true, cancelable: true });
    target.dispatchEvent(tabEvent);

    expect(triggerHotkey).not.toHaveBeenCalled();
    expect(enterEvent.defaultPrevented).toBe(false);
    expect(tabEvent.defaultPrevented).toBe(false);
  });

  it("fires selection-aware hotkeys and prevents default behavior", () => {
    triggerHotkey.mockReturnValue(true);
    useTreeStore.getState().select({ type: "node", id: "node-1" });

    render(<TreeCanvas treeId="tree-1" isLoading={false} />);

    const target = document.createElement("div");
    document.body.appendChild(target);

    const enterEvent = new KeyboardEvent("keydown", { key: "Enter", bubbles: true, cancelable: true });
    target.dispatchEvent(enterEvent);

    const tabEvent = new KeyboardEvent("keydown", { key: "Tab", bubbles: true, cancelable: true });
    target.dispatchEvent(tabEvent);

    expect(registerHotkey.mock.calls.map(([binding]) => binding.combo)).toEqual(
      expect.arrayContaining(["enter", "tab"])
    );
    expect(triggerHotkey).toHaveBeenCalledWith("enter");
    expect(triggerHotkey).toHaveBeenCalledWith("tab");
    expect(enterEvent.defaultPrevented).toBe(true);
    expect(tabEvent.defaultPrevented).toBe(true);
  });
});
