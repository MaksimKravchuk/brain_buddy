export interface Position {
  x: number;
  y: number;
}

export interface TimestampMetadata {
  created_at: string;
  updated_at: string;
  author?: string | null;
}

export interface VisualState {
  color?: string | null;
  highlight?: boolean;
}

export interface ValidationState {
  confidence: number;
  provider: string;
  last_checked: string;
}

export interface NodeResponse {
  id: string;
  label: string;
  position: Position;
  metadata: TimestampMetadata;
  visual?: VisualState | null;
  validation?: ValidationState | null;
  incoming_count: number;
  outgoing_count: number;
}

export interface NodeCreateRequest {
  label: string;
  position: Position;
  visual?: VisualState | null;
}

export interface NodeUpdateRequest {
  label?: string;
  position?: Position;
  visual?: VisualState | null;
}

export interface RelationResponse {
  id: string;
  source_id: string;
  target_id: string;
  question_label: string;
  notes?: string | null;
  metadata: TimestampMetadata;
}

export interface RelationCreateRequest {
  source_id: string;
  target_id: string;
  question_label?: string;
  notes?: string | null;
}

export interface RelationUpdateRequest {
  source_id?: string;
  target_id?: string;
  question_label?: string;
  notes?: string | null;
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

export interface TreeListItem {
  id: string;
  title: string;
  description?: string | null;
  updated_at: string;
}

export interface TreeDetailResponse {
  id: string;
  title: string;
  description?: string | null;
  created_at: string;
  updated_at: string;
  nodes: NodeResponse[];
  relations: RelationResponse[];
  versions: VersionListItem[];
}

export interface TreeCreateRequest {
  title: string;
  description?: string | null;
}

export interface TreeUpdateRequest {
  title?: string;
  description?: string | null;
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
