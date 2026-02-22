import { create } from "zustand";

type ToastVariant = "info" | "success" | "warning" | "error";

export interface Toast {
  id: string;
  title: string;
  description?: string;
  variant: ToastVariant;
  duration: number;
  createdAt: number;
  dismissing: boolean;
  action?: {
    label: string;
    onClick: () => void;
  };
}

type ModalKey = "createTree" | "deleteTree" | "manageVersions";
type InspectorTab = "node" | "relation" | "versions";

type ToastPayload = Omit<Toast, "id" | "createdAt" | "duration" | "dismissing"> & {
  id?: string;
  duration?: number;
};

export interface HotkeyBinding {
  id: string;
  combo: string;
  description: string;
  handler: () => void;
}

interface UiStoreState {
  isSidePanelCollapsed: boolean;
  inspectorTab: InspectorTab;
  modals: Record<ModalKey, boolean>;
  toasts: Toast[];
  hotkeys: Record<string, HotkeyBinding>;
  lastShortcut: string | null;
  pushToast(toast: ToastPayload): string;
  dismissToast(id: string): void;
  clearToasts(): void;
  setInspectorTab(tab: InspectorTab): void;
  toggleSidePanel(collapsed?: boolean): void;
  openModal(key: ModalKey): void;
  closeModal(key: ModalKey): void;
  registerHotkey(binding: HotkeyBinding): void;
  unregisterHotkey(id: string): void;
  triggerHotkey(combo: string): boolean;
}

function generateId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `toast-${Math.random().toString(36).slice(2, 10)}`;
}

export const useUiStore = create<UiStoreState>((set, get) => ({
  isSidePanelCollapsed: false,
  inspectorTab: "node",
  modals: {
    createTree: false,
    deleteTree: false,
    manageVersions: false
  },
  hotkeys: {},
  lastShortcut: null,
  toasts: [],

  pushToast(payload) {
    const id = payload.id ?? generateId();
    const toast: Toast = {
      id,
      title: payload.title,
      description: payload.description,
      variant: payload.variant,
      duration: payload.duration ?? (payload.action ? 0 : 5000),
      createdAt: Date.now(),
      dismissing: false,
      action: payload.action
    };
    set((state) => ({
      toasts: [...state.toasts.filter((item) => item.id !== id), toast]
    }));

    if (toast.duration > 0 && typeof window !== "undefined") {
      window.setTimeout(() => {
        get().dismissToast(id);
      }, toast.duration);
    }

    return id;
  },

  dismissToast(id) {
    const toast = get().toasts.find((t) => t.id === id);
    if (!toast || toast.dismissing) return;

    set((state) => ({
      toasts: state.toasts.map((t) => (t.id === id ? { ...t, dismissing: true } : t))
    }));

    if (typeof window !== "undefined") {
      window.setTimeout(() => {
        set((state) => ({
          toasts: state.toasts.filter((t) => !(t.id === id && t.dismissing))
        }));
      }, 200);
    }
  },

  clearToasts() {
    set(() => ({ toasts: [] }));
  },

  setInspectorTab(tab) {
    set(() => ({ inspectorTab: tab }));
  },

  toggleSidePanel(collapsed) {
    set((state) => ({
      isSidePanelCollapsed: collapsed ?? !state.isSidePanelCollapsed
    }));
  },

  openModal(key) {
    set((state) => ({
      modals: { ...state.modals, [key]: true }
    }));
  },

  closeModal(key) {
    set((state) => ({
      modals: { ...state.modals, [key]: false }
    }));
  },

  registerHotkey(binding) {
    set((state) => ({
      hotkeys: { ...state.hotkeys, [binding.id]: binding }
    }));
  },

  unregisterHotkey(id) {
    set((state) => {
      if (!state.hotkeys[id]) {
        return {};
      }
      const next = { ...state.hotkeys };
      delete next[id];
      return { hotkeys: next };
    });
  },

  triggerHotkey(combo) {
    const binding = Object.values(get().hotkeys).find((item) => item.combo.toLowerCase() === combo.toLowerCase());
    if (!binding) {
      return false;
    }
    binding.handler();
    set(() => ({ lastShortcut: combo }));
    return true;
  }
}));
