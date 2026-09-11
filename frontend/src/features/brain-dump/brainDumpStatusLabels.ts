// Human-readable operation status labels. Shared by the recording route and the
// flag-off privacy surface so the two never disagree about what a status means.
export const operationStatusLabels: Record<string, string> = {
  recording: "Recording",
  paused: "Paused",
  sealing: "Sealing audio",
  // Legacy stage kept for operations persisted before the browser-preview lane
  // stopped deriving drafts; the server no longer enters it.
  fast_processing: "Processing audio",
  accurate_transcribing: "Improving transcript",
  reconciling: "Reconciling tasks",
  committing: "Saving tasks",
  awaiting_confirmation: "Awaiting review",
  retryable_error: "Needs attention",
  terminal_error: "Could not be processed",
  completed: "Saved to Inbox",
  cancelled: "Discarded"
};

// Server statuses during which the operation advances without any client action.
export const processingStatuses = ["sealing", "fast_processing", "accurate_transcribing", "reconciling", "committing"] as const;
