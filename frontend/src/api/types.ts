export interface Position {
  x: number;
  y: number;
}

export type NodeType = "parent" | "child";
export type HighlightState = "none" | "cause_candidate" | "effect_spanning";
export type RelationKind = "why";

export interface RelationCounts {
  up_count: number;
  down_count: number;
}

export interface NodeResponse {
  id: string;
  label: string;
  type: NodeType;
  position: Position;
  highlight_state: HighlightState;
  relation_counts: RelationCounts;
}

export interface NodeCreateRequest {
  label: string;
  type: NodeType;
  position: Position;
  highlight_state?: HighlightState;
}

export interface NodeUpdateRequest {
  label?: string;
  type?: NodeType;
  position?: Position;
  highlight_state?: HighlightState;
}

export interface RelationResponse {
  id: string;
  source_node_id: string;
  target_node_id: string;
  kind: RelationKind;
  created_at: string;
  // Legacy fallbacks
  source_id?: string;
  target_id?: string;
  from_id?: string;
  to_id?: string;
}

export interface RelationCreateRequest {
  source_node_id: string;
  target_node_id: string;
  kind?: RelationKind;
  // Legacy fallbacks
  source_id?: string;
  target_id?: string;
  from_id?: string;
  to_id?: string;
}

export interface RelationUpdateRequest {
  source_node_id?: string;
  target_node_id?: string;
  kind?: RelationKind;
  // Legacy fallbacks
  source_id?: string;
  target_id?: string;
  from_id?: string;
  to_id?: string;
}

export interface VersionDiffSummary {
  nodes_added: number;
  nodes_removed: number;
  nodes_modified: number;
  relations_added: number;
  relations_removed: number;
  relations_modified: number;
}

export interface VersionListItem {
  id: string;
  label: string;
  created_at: string;
  author?: string | null;
  notes?: string | null;
  diff_summary?: VersionDiffSummary | null;
  conflict_count: number;
}

export interface VersionCreateRequest {
  label?: string | null;
  author?: string | null;
  notes?: string | null;
}

export interface TreeMetadata {
  version: number;
  created_at: string;
  updated_at: string;
  layout?: Record<string, unknown> | null;
  owner_id?: string | null;
}

export interface TreeListItem {
  id: string;
  name: string;
  updated_at: string;
  owner_id?: string | null;
}

export interface TreeDetailResponse {
  id: string;
  name: string;
  metadata: TreeMetadata;
  nodes: NodeResponse[];
  relations: RelationResponse[];
  owner_id?: string | null;
}

export type TreeImportPayload = TreeDetailResponse;

export interface TreeCreateRequest {
  name: string;
  owner_id?: string | null;
  metadata?: TreeMetadata;
  nodes?: NodeResponse[];
  relations?: RelationResponse[];
}

export interface TreeUpdateRequest {
  name: string;
  metadata: TreeMetadata;
  nodes: NodeResponse[];
  relations: RelationResponse[];
  owner_id?: string | null;
}

export interface TreeImportRequest {
  tree: TreeImportPayload;
}

export interface TreeExportResponse {
  tree: TreeDetailResponse;
}

export interface ValidationResponse {
  node_id: string;
  provider: string;
  confidence: number;
  summary: string;
  checked_at: string;
}

export interface ValidationHistoryResponse {
  items: ValidationResponse[];
}

export interface ValidationRequest {
  provider?: string | null;
  prompt_overrides?: Record<string, unknown> | null;
}

export type FeedbackStatus = "success" | "failed" | "pending";

export interface AiFeedbackRequest {
  consent: boolean;
  provider?: string | null;
  request_id?: string | null;
}

export interface AiFeedbackResponse {
  status: FeedbackStatus;
  summary: string | null;
  recommendations: string[];
  request_id?: string | null;
}
