export type TaskState = "inbox" | "next" | "waiting" | "someday" | "completed" | "cancelled";
export type OpenTaskState = "inbox" | "next" | "waiting" | "someday";

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
  waiting_for: string | null;
  waiting_since: string | null;
  order_key: number;
  source_capture_ids: string[];
  created_at: string;
  updated_at: string;
  completed_at: string | null;
  revision: number;
  subtasks?: Array<{ id: string; title: string; state: string; order_key: number; revision: number }>;
  comments?: Array<{ id: string; body: string; actor_id: string; created_at: string; revision: number }>;
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
  includeCompleted?: boolean;
}

export interface TaskCreateRequest {
  title: string;
  details?: string | null;
  state?: OpenTaskState;
  project_id?: string | null;
  tag_ids?: string[];
}

export interface TaskUpdateRequest {
  title?: string;
  details?: string | null;
  project_id?: string | null;
  tag_ids?: string[];
  expected_revision: number;
}

export interface TaskTransitionRequest {
  action: "move" | "complete" | "reopen" | "cancel";
  to_state?: OpenTaskState;
  expected_revision: number;
}

export type BrainDumpStatus = "recording" | "paused" | "awaiting_confirmation" | "committing" | "completed" | "cancelled";
export type BrainDumpProposalStatus = "provisional" | "wording_changing" | "ready_to_review" | "user_edited";

export interface BrainDumpProposal {
  id: string;
  ordinal: number;
  title: string;
  status: BrainDumpProposalStatus;
  source_segment_ids: string[];
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
    recorded_at: string;
  };
  segments: Array<{ id: string; sequence: number; text: string; stability: "interim" | "stable"; created_at: string }>;
  proposals: BrainDumpProposal[];
  committed_task_ids: string[];
  created_at: string;
  updated_at: string;
  revision: number;
}

export interface BrainDumpStartRequest {
  consent: { microphone: boolean; external_processing_allowed: boolean; provider?: string | null };
}

export interface BrainDumpTranscriptAppendRequest {
  segments: Array<{ sequence: number; text: string; stability: "interim" | "stable" }>;
}
