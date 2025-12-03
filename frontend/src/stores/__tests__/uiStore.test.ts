import { beforeEach, describe, expect, it } from "vitest";

import { useUiStore } from "../uiStore";

const resetUiStore = () => {
  useUiStore.setState({
    isSidePanelCollapsed: false,
    inspectorTab: "node",
    modals: {
      createTree: false,
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

    const triggered = triggerHotkey("ctrl+-");

    expect(triggered).toBe(false);
    expect(fired).toBe(false);
  });
});
