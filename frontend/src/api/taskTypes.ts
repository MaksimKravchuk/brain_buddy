export type TaskState = "inbox" | "next" | "waiting" | "someday" | "completed" | "cancelled";
export type OpenTaskState = "inbox" | "next" | "waiting" | "someday";
export type TaskPriority = "none" | "low" | "medium" | "high";
export type TaskSort = "manual" | "due" | "priority" | "title";

export interface TaskCounts {
  inbox: number;
  next: number;
  waiting: number;
  someday: number;
}

export interface TaskResponse {
  id: string;
  title: string;
  details: string | null;
  state: TaskState;
  project_id: string | null;
  tag_ids: string[];
  due_date: string | null;
  priority: TaskPriority;
  waiting_for: string | null;
  waiting_since: string | null;
  order_key: number;
  source_capture_ids: string[];
  created_at: string;
  updated_at: string;
  completed_at: string | null;
  cancelled_at: string | null;
  revision: number;
  subtasks?: TaskSubtaskResponse[];
  comments?: TaskCommentResponse[];
}

export interface TaskSubtaskResponse {
  id: string;
  title: string;
  state: "open" | "completed" | "cancelled";
  order_key: number;
  revision: number;
}

export interface TaskCommentResponse {
  id: string;
  body: string;
  actor_id: string;
  created_at: string;
  edited_at: string | null;
  revision: number;
}

export interface TaskListResponse {
  items: TaskResponse[];
  next_cursor: string | null;
  has_more: boolean;
  counts_by_state: TaskCounts;
}

export interface ProjectResponse {
  id: string;
  name: string;
  color: string | null;
  state: "active" | "completed" | "archived";
  revision: number;
  open_task_count: number;
}

export interface TagResponse {
  id: string;
  name: string;
  state: "active" | "archived" | "deleted";
  revision: number;
  open_task_count: number;
}

export interface TaskListFilters {
  state?: OpenTaskState;
  projectId?: string;
  tagId?: string;
  unassignedProject?: boolean;
  cursor?: string;
  limit?: number;
  includeCompleted?: boolean;
  includeCancelled?: boolean;
  q?: string;
  priority?: TaskPriority[];
  dueBefore?: string;
  dueOn?: string;
  dueAfter?: string;
  sort?: TaskSort;
}

export interface TaskCreateRequest {
  title: string;
  details?: string | null;
  state?: OpenTaskState;
  project_id?: string | null;
  tag_ids?: string[];
  due_date?: string | null;
  priority?: TaskPriority;
  waiting_for?: string | null;
}

export type SmartAddClassificationRef = { id: string; name?: never } | { id?: never; name: string };

export interface SmartAddTaskCreateRequest {
  title: string;
  details?: string | null;
  state?: OpenTaskState;
  waiting_for?: string | null;
  due_date?: string | null;
  priority?: TaskPriority;
  project?: SmartAddClassificationRef | null;
  tags?: SmartAddClassificationRef[];
}

export interface SmartAddTaskResponse {
  task: TaskResponse;
  project: ProjectResponse | null;
  tags: TagResponse[];
  created: {
    project_id: string | null;
    tag_ids: string[];
  };
}

export interface TitleCompletionProviderResponse {
  provider: string | null;
}

export interface TitleCompletionRequest {
  draft: string;
  project_id: string | null;
  consent: {
    external_processing_allowed: true;
    provider: string;
  };
}

export interface TitleCompletionResponse {
  request_id: string;
  candidates: [string, string, string];
}

export interface TaskUpdateRequest {
  title?: string;
  details?: string | null;
  project_id?: string | null;
  tag_ids?: string[];
  due_date?: string | null;
  priority?: TaskPriority;
  waiting_for?: string | null;
  expected_revision: number;
}

export interface TaskTransitionRequest {
  action: "move" | "complete" | "reopen" | "cancel";
  to_state?: OpenTaskState;
  waiting_for?: string | null;
  expected_revision: number;
}

export interface TaskSubtaskCreateRequest {
  title: string;
}

export interface TaskSubtaskUpdateRequest {
  title?: string;
  expected_revision: number;
}

export interface TaskSubtaskTransitionRequest {
  action: "complete" | "reopen" | "cancel";
  expected_revision: number;
}

export interface TaskCommentCreateRequest {
  body: string;
}

export interface TaskCommentUpdateRequest {
  body: string;
  expected_revision: number;
}

export type BrainDumpStatus = "recording" | "paused" | "sealing" | "fast_processing" | "accurate_transcribing" | "reconciling" | "retryable_error" | "terminal_error" | "awaiting_confirmation" | "committing" | "completed" | "cancelled";
export type BrainDumpProposalStatus = "provisional" | "wording_changing" | "ready_to_review" | "user_edited" | "reconciled" | "conflicted";

export interface BrainDumpProposalConflict {
  field: string;
  current_value: string | null;
  suggested_value: string | null;
  producer: "fast" | "accurate" | "reconciler" | "user";
  source_segment_ids: string[];
}

export interface BrainDumpProposal {
  id: string;
  ordinal: number;
  title: string;
  status: BrainDumpProposalStatus;
  source_segment_ids: string[];
  predecessor_ids?: string[];
  successor_ids?: string[];
  locked_fields?: string[];
  conflicts?: BrainDumpProposalConflict[];
  deleted: boolean;
  user_edited: boolean;
  revision: number;
}

export interface BrainDumpOperationResponse {
  id: string;
  owner_id: string;
  kind: "voice_brain_dump";
  status: BrainDumpStatus;
  consent: {
    microphone: boolean;
    external_processing_allowed: boolean;
    provider: string | null;
    providers?: string[];
    language_hints: string[];
    vocabulary: string[];
    recorded_at: string;
  };
  segments: Array<{
    id: string;
    sequence: number;
    text: string;
    stability: "interim" | "stable";
    start_ms?: number;
    end_ms?: number;
    provider_role?: "browser_preview" | "fast" | "accurate";
    provider?: string | null;
    model?: string | null;
    supersedes_segment_ids?: string[];
    created_at: string;
  }>;
  proposals: BrainDumpProposal[];
  media_ref?: string | null;
  audio_chunks?: Array<{ chunk_number: number; sha256: string; size_bytes: number }>;
  sealed_manifest_hash?: string | null;
  raw_audio_expires_at?: string | null;
  raw_audio_present?: boolean;
  working_artifacts_expires_at?: string | null;
  reconciliation_quality?: "none" | "provisional_only" | "accurate" | "conflicted";
  committable?: boolean;
  available_recovery_actions?: Array<"retry" | "review_provisional" | "reconcile_preview" | "cancel">;
  provider_runs?: Array<{
    id: string;
    role: "accurate_stt" | "reconciler";
    status: "pending" | "running" | "succeeded" | "retryable_error" | "terminal_error";
    checkpoint: "sealed" | "accurate_transcribed" | "reconciled";
    attempt: number;
    recovery_count: number;
    error: string | null;
    error_code: string | null;
    provider: string | null;
    model: string | null;
    template_version: string | null;
    estimated_cost_usd: number;
    reserved_cost_usd?: number;
    consumed_cost_usd?: number;
  }>;
  status_history?: BrainDumpStatus[];
  committed_task_ids: string[];
  created_at: string;
  updated_at: string;
  revision: number;
}

export interface BrainDumpStartRequest {
  consent: {
    microphone: boolean;
    external_processing_allowed: boolean;
    provider?: string | null;
    providers?: string[];
    language_hints: string[];
    vocabulary: string[];
  };
}

export interface BrainDumpProvidersResponse {
  accurate_stt: string | null;
  reconciler: string | null;
}

export interface BrainDumpTranscriptAppendRequest {
  segments: Array<{ sequence: number; text: string; stability: "interim" | "stable" }>;
}
