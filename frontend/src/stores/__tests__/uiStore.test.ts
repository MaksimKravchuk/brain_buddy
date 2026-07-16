import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useUiStore } from "../uiStore";

const resetUiStore = () => {
  useUiStore.setState({
    isSidePanelCollapsed: false,
    inspectorTab: "node",
    modals: {
      createTree: false,
      renameTree: false,
      deleteTree: false,
      manageVersions: false
    },
    toasts: [],
    hotkeys: {},
    lastShortcut: null
  });
};

describe("uiStore hotkeys", () => {
  beforeEach(() => {
    resetUiStore();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("falls back to a generated toast ID when crypto is unavailable", () => {
    vi.stubGlobal("crypto", undefined);

    const id = useUiStore.getState().pushToast({ title: "Saved", variant: "success" });

    expect(id).toMatch(/^toast-/);
  });

  it("registers and triggers hotkeys case-insensitively", () => {
    let count = 0;
    const { registerHotkey, triggerHotkey } = useUiStore.getState();

    registerHotkey({
      id: "create-node",
      combo: "meta+shift+n",
      description: "Create node",
      handler: () => {
        count += 1;
      }
    });

    const triggered = triggerHotkey("META+SHIFT+N");

    expect(triggered).toBe(true);
    expect(count).toBe(1);
    expect(useUiStore.getState().lastShortcut?.toLowerCase()).toBe("meta+shift+n");
  });

  it("unregisters hotkeys to prevent triggering", () => {
    const { registerHotkey, unregisterHotkey, triggerHotkey } = useUiStore.getState();
    let fired = false;

    registerHotkey({
      id: "zoom-out",
      combo: "ctrl+-",
      description: "Zoom out",
      handler: () => {
        fired = true;
      }
    });

    unregisterHotkey("zoom-out");
    unregisterHotkey("missing");

    const triggered = triggerHotkey("ctrl+-");

    expect(triggered).toBe(false);
    expect(fired).toBe(false);
  });

  it("manages toast lifecycles, panel state, and modal state", () => {
    vi.useFakeTimers();
    const store = useUiStore.getState();
    const firstId = store.pushToast({ title: "Saved", variant: "success" });
    const actionId = store.pushToast({
      id: "action",
      title: "Needs review",
      variant: "warning",
      action: { label: "Review", onClick: () => undefined }
    });

    expect(firstId).toBeTruthy();
    expect(useUiStore.getState().toasts.find((toast) => toast.id === firstId)?.duration).toBe(5000);
    expect(useUiStore.getState().toasts.find((toast) => toast.id === actionId)?.duration).toBe(0);

    store.dismissToast(firstId);
    store.dismissToast(firstId);
    expect(useUiStore.getState().toasts.find((toast) => toast.id === firstId)?.dismissing).toBe(true);
    vi.advanceTimersByTime(200);
    expect(useUiStore.getState().toasts.find((toast) => toast.id === firstId)).toBeUndefined();

    const expiringId = store.pushToast({ id: "expiring", title: "Expiring", variant: "info", duration: 50 });
    expect(expiringId).toBe("expiring");
    vi.advanceTimersByTime(50);
    expect(useUiStore.getState().toasts.find((toast) => toast.id === "expiring")?.dismissing).toBe(true);
    vi.advanceTimersByTime(200);
    expect(useUiStore.getState().toasts.find((toast) => toast.id === "expiring")).toBeUndefined();

    store.setInspectorTab("versions");
    store.toggleSidePanel();
    store.toggleSidePanel(false);
    store.openModal("createTree");
    store.closeModal("createTree");
    expect(useUiStore.getState()).toMatchObject({
      inspectorTab: "versions",
      isSidePanelCollapsed: false,
      modals: { createTree: false }
    });
    store.clearToasts();
    expect(useUiStore.getState().toasts).toEqual([]);
    vi.useRealTimers();
  });
});
