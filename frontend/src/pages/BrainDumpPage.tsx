import { useEffect, useRef, useState } from "react";

import { useBrainDumpStore } from "../stores/brainDumpStore";
import { useAuthStore } from "../stores/authStore";

export default function BrainDumpPage(): JSX.Element {
  const {
    sessionId,
    status,
    drafts,
    exportResults,
    loading,
    error,
    createOrResumeSession,
    uploadAudio,
    editDraft,
    deleteDraft,
    saveSession,
    reset,
  } = useBrainDumpStore();

  const authed = useAuthStore((s) => s.status === "authed");
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editText, setEditText] = useState("");

  useEffect(() => {
    if (authed && !sessionId) {
      void createOrResumeSession();
    }
  }, [authed, sessionId, createOrResumeSession]);

  const handleFileSelect = async (
    event: React.ChangeEvent<HTMLInputElement>
  ) => {
    const file = event.target.files?.[0];
    if (file) {
      await uploadAudio(file);
    }
    if (fileInputRef.current) {
      fileInputRef.current.value = "";
    }
  };

  const startEdit = (draftId: string, currentText: string) => {
    setEditingId(draftId);
    setEditText(currentText);
  };

  const submitEdit = async () => {
    if (editingId) {
      await editDraft(editingId, editText);
      setEditingId(null);
      setEditText("");
    }
  };

  const cancelEdit = () => {
    setEditingId(null);
    setEditText("");
  };

  if (!authed) {
    return <div>Please sign in to use Brain Dump.</div>;
  }

  if (status === "completed") {
    return (
      <div className="brain-dump-completed">
        <h1>Brain Dump Saved</h1>
        <p>{exportResults.length} task(s) exported to RTM Inbox.</p>
        <ul>
          {exportResults.map((r) => (
            <li key={r.draft_id}>
              {r.success ? "✓" : "✗"} {r.external_ref ?? r.error}
            </li>
          ))}
        </ul>
        <button
          onClick={() => reset()}
          className="px-4 py-2 rounded bg-blue-600 text-white"
        >
          New Brain Dump
        </button>
      </div>
    );
  }

  return (
    <div className="brain-dump-page p-4 max-w-2xl mx-auto">
      <h1 className="text-2xl font-bold mb-4">Brain Dump</h1>

      {error && (
        <div className="error-message text-red-600 mb-4">{error}</div>
      )}

      {/* Voice recording / upload */}
      <div className="voice-section mb-6">
        <input
          ref={fileInputRef}
          type="file"
          accept="audio/*"
          onChange={handleFileSelect}
          disabled={loading}
          data-testid="audio-file-input"
        />
        <p className="text-sm text-gray-500 mt-1">
          Record audio or select an audio file to transcribe.
        </p>
      </div>

      {/* Drafts review */}
      {drafts.length > 0 && (
        <div className="drafts-section">
          <h2 className="text-lg font-semibold mb-2">Drafts</h2>
          <ul className="space-y-2">
            {drafts.map((draft) => (
              <li
                key={draft.id}
                className="draft-item flex items-center gap-2 p-2 border rounded"
              >
                {editingId === draft.id ? (
                  <>
                    <input
                      type="text"
                      value={editText}
                      onChange={(e) => setEditText(e.target.value)}
                      className="flex-1 border rounded px-2 py-1"
                      data-testid={`edit-input-${draft.id}`}
                    />
                    <button
                      onClick={submitEdit}
                      className="px-2 py-1 rounded bg-green-600 text-white text-sm"
                      data-testid={`save-edit-${draft.id}`}
                    >
                      Save
                    </button>
                    <button
                      onClick={cancelEdit}
                      className="px-2 py-1 rounded bg-gray-400 text-white text-sm"
                      data-testid={`cancel-edit-${draft.id}`}
                    >
                      Cancel
                    </button>
                  </>
                ) : (
                  <>
                    <span className="flex-1">{draft.text}</span>
                    <button
                      onClick={() => startEdit(draft.id, draft.text)}
                      className="px-2 py-1 rounded bg-blue-600 text-white text-sm"
                      data-testid={`edit-btn-${draft.id}`}
                    >
                      Edit
                    </button>
                    <button
                      onClick={() => deleteDraft(draft.id)}
                      className="px-2 py-1 rounded bg-red-600 text-white text-sm"
                      data-testid={`delete-btn-${draft.id}`}
                    >
                      Delete
                    </button>
                  </>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Actions */}
      <div className="actions-section mt-6 flex gap-4">
        <button
          onClick={() => fileInputRef.current?.click()}
          disabled={loading}
          className="px-4 py-2 rounded bg-blue-600 text-white disabled:opacity-50"
          data-testid="record-more-btn"
        >
          Add More Voice
        </button>
        <button
          onClick={() => saveSession()}
          disabled={loading || drafts.length === 0}
          className="px-4 py-2 rounded bg-green-600 text-white disabled:opacity-50"
          data-testid="save-session-btn"
        >
          Save Session
        </button>
      </div>
    </div>
  );
}
