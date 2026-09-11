import { afterEach, describe, expect, it, vi } from "vitest";

import * as clientModule from "../client";
import { useAuthStore } from "../../stores/authStore";

import { parseOpenTaskState, parseTaskDateView, taskKeys } from "../taskHooks";

describe("taskHooks", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    useAuthStore.setState({ user: null, status: "loading" });
  });

  it("016-FR-003 isolates list keys by captured account and API origin", () => {
    const origin = vi.spyOn(clientModule, "getApiBaseUrl").mockReturnValue("https://first.example/api");
    useAuthStore.setState({ user: { id: "owner-a", email: "a@example.test" } });
    const first = taskKeys.list({ includeCompleted: true });
    useAuthStore.setState({ user: { id: "owner-b", email: "b@example.test" } });
    const second = taskKeys.list({ includeCompleted: true });
    expect(first).not.toEqual(second);
    origin.mockReturnValue("https://second.example/api");
    expect(taskKeys.list({ includeCompleted: true })).not.toEqual(second);
  });
  it("parses supported open task states and falls back to next", () => {
    expect(parseOpenTaskState("inbox")).toBe("inbox");
    expect(parseOpenTaskState("next")).toBe("next");
    expect(parseOpenTaskState("waiting")).toBe("waiting");
    expect(parseOpenTaskState("someday")).toBe("someday");
    expect(parseOpenTaskState(undefined)).toBe("next");
    expect(parseOpenTaskState("completed")).toBe("next");
  });

  it("recognises the three date views and nothing else", () => {
    expect(parseTaskDateView("overdue")).toBe("overdue");
    expect(parseTaskDateView("today")).toBe("today");
    expect(parseTaskDateView("upcoming")).toBe("upcoming");
    expect(parseTaskDateView("inbox")).toBeUndefined();
    expect(parseTaskDateView(undefined)).toBeUndefined();
  });

  // Cache keys are how a write invalidates the right reads. Two collections
  // that share a key refetch each other's data; one that drifts from `all`
  // stops being invalidated at all.
  it("namespaces every task cache key under the same root", () => {
    expect(taskKeys.all).toEqual(["tasks"]);
    expect(taskKeys.projects()).toEqual(["tasks", "projects"]);
    expect(taskKeys.tags()).toEqual(["tasks", "tags"]);
    const scope = { accountId: null, apiOrigin: clientModule.getApiBaseUrl() };
    expect(taskKeys.detail("task-1")).toEqual(["tasks", "detail", scope, "task-1"]);
    expect(taskKeys.list({ state: "next" })).toEqual(["tasks", "list", scope, { state: "next" }]);
    expect(taskKeys.brainDumpProviders()).toEqual(["brain-dump-providers"]);
  });

  it("keeps a detail key per task, so one task's refetch cannot serve another", () => {
    expect(taskKeys.detail("task-1")).not.toEqual(taskKeys.detail("task-2"));
  });
});
