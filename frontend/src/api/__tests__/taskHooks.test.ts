import { describe, expect, it } from "vitest";

import { parseOpenTaskState, parseTaskDateView, taskKeys } from "../taskHooks";

describe("taskHooks", () => {
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
    expect(taskKeys.detail("task-1")).toEqual(["tasks", "detail", "task-1"]);
    expect(taskKeys.list({ state: "next" })).toEqual(["tasks", "list", { state: "next" }]);
    expect(taskKeys.brainDumpProviders()).toEqual(["brain-dump-providers"]);
  });

  it("keeps a detail key per task, so one task's refetch cannot serve another", () => {
    expect(taskKeys.detail("task-1")).not.toEqual(taskKeys.detail("task-2"));
  });
});
