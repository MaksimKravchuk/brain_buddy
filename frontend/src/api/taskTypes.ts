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
  context_ids: string[];
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
}

export interface TagResponse {
  id: string;
  name: string;
  state: "active" | "archived";
  revision: number;
}

export interface TaskListFilters {
  state?: OpenTaskState;
  projectId?: string;
  tagId?: string;
}
