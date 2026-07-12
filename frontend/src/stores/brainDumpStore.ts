import { create } from "zustand";

import { apiClient } from "../api/client";
import type {
  BrainDumpDraft,
  BrainDumpSessionStatus,
  ExportResult,
} from "../api/types";

interface BrainDumpState {
  sessionId: string | null;
  status: BrainDumpSessionStatus | null;
  drafts: BrainDumpDraft[];
  exportResults: ExportResult[];
  loading: boolean;
  error: string | null;

  createOrResumeSession: () => Promise<void>;
  uploadAudio: (file: Blob) => Promise<void>;
  editDraft: (draftId: string, text: string) => Promise<void>;
  deleteDraft: (draftId: string) => Promise<void>;
  saveSession: () => Promise<void>;
  reset: () => void;
}

export const useBrainDumpStore = create<BrainDumpState>((set, get) => ({
  sessionId: null,
  status: null,
  drafts: [],
  exportResults: [],
  loading: false,
  error: null,

  async createOrResumeSession() {
    set({ loading: true, error: null });
    try {
      const resp = await apiClient.createBrainDumpSession();
      set({
        sessionId: resp.id,
        status: resp.status,
        drafts: resp.drafts,
        loading: false,
      });
    } catch (err) {
      set({ loading: false, error: (err as Error).message });
    }
  },

  async uploadAudio(file: Blob) {
    const sessionId = get().sessionId;
    if (!sessionId) {
      set({ error: "No active session" });
      return;
    }
    set({ loading: true, error: null });
    try {
      const resp = await apiClient.uploadBrainDumpAudio(sessionId, file);
      set({
        status: resp.status,
        drafts: resp.drafts,
        loading: false,
      });
    } catch (err) {
      set({ loading: false, error: (err as Error).message });
    }
  },

  async editDraft(draftId: string, text: string) {
    const sessionId = get().sessionId;
    if (!sessionId) return;
    set({ loading: true, error: null });
    try {
      const resp = await apiClient.editBrainDumpDraft(sessionId, draftId, text);
      set({ drafts: resp.drafts, loading: false });
    } catch (err) {
      set({ loading: false, error: (err as Error).message });
    }
  },

  async deleteDraft(draftId: string) {
    const sessionId = get().sessionId;
    if (!sessionId) return;
    set({ loading: true, error: null });
    try {
      const resp = await apiClient.deleteBrainDumpDraft(sessionId, draftId);
      set({ drafts: resp.drafts, loading: false });
    } catch (err) {
      set({ loading: false, error: (err as Error).message });
    }
  },

  async saveSession() {
    const sessionId = get().sessionId;
    if (!sessionId) return;
    set({ loading: true, error: null });
    try {
      const resp = await apiClient.saveBrainDumpSession(sessionId);
      set({
        status: resp.status,
        exportResults: resp.export_results,
        loading: false,
      });
    } catch (err) {
      set({ loading: false, error: (err as Error).message });
    }
  },

  reset() {
    set({
      sessionId: null,
      status: null,
      drafts: [],
      exportResults: [],
      loading: false,
      error: null,
    });
  },
}));
