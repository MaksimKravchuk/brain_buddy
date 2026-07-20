import type { TaskState } from "./types";

export type CreateTaskInput = {
  title: string;
  state: Exclude<TaskState, "completed" | "cancelled">;
};
