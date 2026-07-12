// vNext API types — ADR-0001 capture/review/thinking/execution contracts

export type CaptureKind = "task" | "note" | "question" | "problem_candidate";
export type CaptureItemState =
  | "proposed"
  | "needs_clarification"
  | "approved"
  | "deferred"
  | "completed"
  | "deleted";

export interface CaptureItemResponse {
  id: string;
  source_capture_id: string;
  current_text: string;
  review_state: CaptureItemState;
  kind: CaptureKind;
  source_text: string;
  created_at: string;
  updated_at: string;
  revision: number;
}

export interface CaptureSessionResponse {
  id: string;
  status: string;
  input_kind: string;
  atomic_capture_ids: string[];
  created_at: string;
  updated_at: string;
}

export interface CaptureSessionDetailResponse {
  session: CaptureSessionResponse;
  captures: CaptureItemResponse[];
}

export interface CaptureSessionCreateRequest {
  text: string;
}

export type CaptureDecisionAction =
  | "edit"
  | "clarify"
  | "approve"
  | "defer"
  | "complete"
  | "delete";

export interface CaptureDecisionRequest {
  action: CaptureDecisionAction;
  new_text?: string;
  expected_revision?: number;
}

export type ReviewOutcomeAction =
  | "keep"
  | "edit"
  | "delete"
  | "defer"
  | "route"
  | "promote_to_crt";

export interface ReviewOutcomeRequest {
  action: ReviewOutcomeAction;
  reason?: string;
  avoidance_reason?: string;
  new_text?: string;
}

export interface ReviewOutcomeResponse {
  id: string;
  weekly_review_id: string;
  atomic_capture_id: string;
  action: ReviewOutcomeAction;
  reason?: string | null;
  avoidance_reason?: string | null;
  decided_at: string;
}

export interface WeeklyReviewResponse {
  id: string;
  status: string;
  period_start: string;
  period_end: string;
  item_ids: string[];
  outcome_count: number;
  started_at: string;
  completed_at?: string | null;
}

export interface WeeklyReviewDetailResponse {
  review: WeeklyReviewResponse;
  items: CaptureItemResponse[];
  outcomes: Array<{
    id: string;
    atomic_capture_id: string;
    action: ReviewOutcomeAction;
    reason?: string | null;
    avoidance_reason?: string | null;
    decided_at: string;
  }>;
}

export interface ReviewSummaryResponse {
  review_id: string;
  total_items: number;
  kept: number;
  edited: number;
  deferred: number;
  deleted: number;
  routed: number;
  promoted: number;
  completed_at: string;
}

export interface ProblemCandidateResponse {
  id: string;
  source_capture_ids: string[];
  title: string;
  context: string;
  signal: string;
  signal_reasons: string[];
  status: string;
  created_at: string;
  updated_at: string;
}

export interface CandidateCreateRequest {
  title: string;
  context?: string;
  source_capture_ids?: string[];
  signal?: "manual" | "repeated" | "complex";
  signal_reasons?: string[];
}

export interface CrtPromotionResponse {
  id: string;
  problem_candidate_id: string;
  status: string;
  tree_id?: string | null;
  root_node_id?: string | null;
  source_capture_ids: string[];
  requested_at: string;
  completed_at?: string | null;
}

export interface EvidenceResultResponse {
  id: string;
  source: string;
  kind: string;
  title: string;
  summary?: string | null;
  uri?: string | null;
  atomic_capture_ids: string[];
  tree_id?: string | null;
  observed_at: string;
  recorded_at: string;
}

export interface EvidenceResultCreateRequest {
  source?: "external_task_tracker" | "crt" | "manual";
  kind: "evidence" | "result";
  title: string;
  summary?: string;
  uri?: string;
  atomic_capture_ids: string[];
  tree_id?: string;
}
