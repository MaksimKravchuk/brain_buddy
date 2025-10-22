import { create } from "zustand";

type ToastVariant = "info" | "success" | "warning" | "error";

export interface Toast {
  id: string;
  title: string;
  description?: string;
  variant: ToastVariant;
  duration: number;
  createdAt: number;
  action?: {
    label: string;
    onClick: () => void;
  };
}

type ModalKey = "createTree" | "deleteTree" | "manageVersions";
type InspectorTab = "node" | "relation" | "versions";

type ToastPayload = Omit<Toast, "id" | "createdAt" | "duration"> & {
  id?: string;
  duration?: number;
};

interface UiStoreState {
  isSidePanelCollapsed: boolean;
  inspectorTab: InspectorTab;
  modals: Record<ModalKey, boolean>;
  toasts: Toast[];
  pushToast(toast: ToastPayload): string;
  dismissToast(id: string): void;
  clearToasts(): void;
  setInspectorTab(tab: InspectorTab): void;
  toggleSidePanel(collapsed?: boolean): void;
  openModal(key: ModalKey): void;
  closeModal(key: ModalKey): void;
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
    set((state) => ({
      toasts: state.toasts.filter((toast) => toast.id !== id)
    }));
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
  }
}));
