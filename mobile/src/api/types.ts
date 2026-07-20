/*
 * Application-facing aliases over the generated OpenAPI snapshot. Do not add
 * hand-written server payload types here; refresh openapi.generated.ts instead.
 */
import type { components } from "./openapi.generated";

type Schemas = components["schemas"];

export type User = Schemas["MeResponse"];
export type SessionCredential = Omit<Schemas["SessionCredentialResponse"], "token_type"> & {
  token_type: "Bearer";
};
export type Task = Schemas["TaskResponse"];
export type TaskState = Task["state"];
export type TaskList = Omit<Schemas["TaskListResponse"], "items"> & { items: Task[] };
export type Project = Schemas["ProjectResponse"];
export type Tag = Schemas["TagResponse"];
