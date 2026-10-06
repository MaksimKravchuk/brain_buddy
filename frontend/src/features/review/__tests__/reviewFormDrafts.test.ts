import { act } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useAuthStore } from "../../../stores/authStore";
import {
  clearReviewLocalState,
  DRAFT_MAX_AGE_MS,
  loadReviewDraft,
  removeOtherFormulationDrafts,
  removeReviewDraft,
  reviewDraftKey,
  saveReviewDraft,
  subscribeReviewLocalCleanup,
  sweepReviewDrafts
} from "../reviewFormDrafts";

const scope = { apiOrigin: "http://localhost:3000/api", accountId: "user_1" };
const otherScope = { apiOrigin: "http://localhost:3000/api", accountId: "user_2" };
const task = { kind: "task", taskId: "task_9f3c", formulationId: "form_a" } as const;
const now = new Date("2026-10-09T14:02:00Z");
const sentinel = "SENTINEL draft wording: call the landlord about the leak";

const consoleSpies = [vi.spyOn(console, "info"), vi.spyOn(console, "warn"), vi.spyOn(console, "error"), vi.spyOn(console, "log")];
const fetchSpy = vi.fn();

beforeEach(() => {
  window.localStorage.clear();
  vi.stubGlobal("fetch", fetchSpy);
  for (const spy of consoleSpies) spy.mockImplementation(() => undefined);
});

afterEach(() => {
  window.localStorage.clear();
  vi.unstubAllGlobals();
  fetchSpy.mockReset();
  for (const spy of consoleSpies) spy.mockReset();
  act(() => useAuthStore.setState({ user: null, status: "loading" }));
});

describe("020-FR-052 browser-local review form drafts", () => {
  it("020-FR-052 keys a draft by origin, account, task and formulation, and a project's next action by project", () => {
    expect(reviewDraftKey(scope, task)).toBe("bb.reviewFormDraft.v1.http%3A%2F%2Flocalhost%3A3000%2Fapi.user_1.task_9f3c.form_a");
    expect(reviewDraftKey(scope, { kind: "project", projectId: "project_1a" })).toBe(
      "bb.reviewFormDraft.v1.http%3A%2F%2Flocalhost%3A3000%2Fapi.user_1.project.project_1a"
    );
  });

  it("020-FR-052 restores the typed text and the form it belongs to", () => {
    saveReviewDraft(scope, task, { form: "reformulate", text: sentinel }, now);

    expect(loadReviewDraft(scope, task, now)).toEqual({ form: "reformulate", text: sentinel, savedAt: now.toISOString() });
    expect(loadReviewDraft(otherScope, task, now)).toBeNull();
    expect(loadReviewDraft(scope, { ...task, formulationId: "form_b" }, now)).toBeNull();
  });

  it("020-FR-052 stamps and checks drafts with the current time by default", () => {
    saveReviewDraft(scope, task, { form: "extend", text: "fresh" });
    expect(loadReviewDraft(scope, task)?.text).toBe("fresh");
    sweepReviewDrafts(scope);
    expect(loadReviewDraft(scope, task)?.form).toBe("extend");
  });

  it("020-FR-052 removes the draft on save or discard, and an empty field leaves none behind", () => {
    saveReviewDraft(scope, task, { form: "waiting", text: sentinel }, now);
    removeReviewDraft(scope, task);
    expect(window.localStorage.length).toBe(0);

    saveReviewDraft(scope, task, { form: "waiting", text: sentinel }, now);
    saveReviewDraft(scope, task, { form: "waiting", text: "" }, now);
    expect(window.localStorage.length).toBe(0);
  });

  it("020-FR-052 drops the drafts of earlier wordings of a task when its formulation changed", () => {
    saveReviewDraft(scope, task, { form: "first_step", text: "old" }, now);
    saveReviewDraft(scope, { ...task, taskId: "task_other" }, { form: "first_step", text: "keep" }, now);
    saveReviewDraft(scope, { ...task, formulationId: "form_b" }, { form: "extend", text: "current" }, now);

    removeOtherFormulationDrafts(scope, task.taskId, "form_b");
    expect(loadReviewDraft(scope, task, now)).toBeNull();
    expect(loadReviewDraft(scope, { ...task, formulationId: "form_b" }, now)?.text).toBe("current");
    expect(loadReviewDraft(scope, { ...task, taskId: "task_other" }, now)?.text).toBe("keep");

    removeOtherFormulationDrafts(scope, task.taskId, null);
    expect(loadReviewDraft(scope, { ...task, formulationId: "form_b" }, now)).toBeNull();
  });

  it("020-FR-052 expires a draft after 7 days, on read and in the startup or focus sweep", () => {
    saveReviewDraft(scope, task, { form: "reformulate", text: "a week old" }, now);
    const later = new Date(now.getTime() + DRAFT_MAX_AGE_MS);
    expect(loadReviewDraft(scope, task, new Date(later.getTime() - 1))?.text).toBe("a week old");
    expect(loadReviewDraft(scope, task, later)).toBeNull();
    expect(window.localStorage.length).toBe(0);

    saveReviewDraft(scope, task, { form: "reformulate", text: "old" }, now);
    saveReviewDraft(scope, { ...task, taskId: "task_fresh" }, { form: "reformulate", text: "fresh" }, later);
    window.localStorage.setItem("bb.taskDetailDraft.v1.unrelated", "kept");
    sweepReviewDrafts(scope, later);
    expect(loadReviewDraft(scope, task, now)).toBeNull();
    expect(loadReviewDraft(scope, { ...task, taskId: "task_fresh" }, later)?.text).toBe("fresh");
    expect(window.localStorage.getItem("bb.taskDetailDraft.v1.unrelated")).toBe("kept");
  });

  it("020-FR-052 the sweep removes another account's drafts, which is how an account switch clears them", () => {
    saveReviewDraft(otherScope, task, { form: "reformulate", text: "someone else's" }, now);
    saveReviewDraft(scope, task, { form: "reformulate", text: "mine" }, now);

    sweepReviewDrafts(scope, now);

    expect(loadReviewDraft(otherScope, task, now)).toBeNull();
    expect(loadReviewDraft(scope, task, now)?.text).toBe("mine");
  });

  it("020-FR-052 discards a corrupt or foreign-shaped entry instead of showing it", () => {
    const key = reviewDraftKey(scope, task);
    for (const corrupt of ["not json", JSON.stringify({ form: "reformulate" }), JSON.stringify({ form: "poem", text: "x", savedAt: now.toISOString() }), JSON.stringify(null)]) {
      window.localStorage.setItem(key, corrupt);
      expect(loadReviewDraft(scope, task, now)).toBeNull();
      expect(window.localStorage.getItem(key)).toBeNull();
    }
    window.localStorage.setItem(key, "not json");
    sweepReviewDrafts(scope, now);
    expect(window.localStorage.getItem(key)).toBeNull();
  });

  it("020-FR-052 clears every review key of an account on sign-out or account switch", () => {
    saveReviewDraft(scope, task, { form: "reformulate", text: sentinel }, now);
    saveReviewDraft(otherScope, task, { form: "reformulate", text: "other" }, now);
    window.localStorage.setItem("bb.reviewWywaLastShown.v1.http%3A%2F%2Flocalhost%3A3000%2Fapi.user_1", "2026-10-09");
    window.localStorage.setItem("bb.reviewLastZone.v1.http%3A%2F%2Flocalhost%3A3000%2Fapi.user_1", "Europe/Berlin");

    clearReviewLocalState(scope);

    expect(Object.keys(window.localStorage)).toEqual([reviewDraftKey(otherScope, task)]);
  });

  it("020-FR-052 watches the session: sign-out and an account switch clear the departing account's review keys", () => {
    act(() => useAuthStore.setState({ user: { id: "user_1", email: "a@example.test" }, status: "authed" }));
    const stop = subscribeReviewLocalCleanup();
    saveReviewDraft({ apiOrigin: "http://localhost:3000/api", accountId: "user_1" }, task, { form: "reformulate", text: "a" }, now);

    act(() => useAuthStore.setState({ user: { id: "user_1", email: "renamed@example.test" } }));
    expect(window.localStorage.length).toBe(1);

    act(() => useAuthStore.setState({ user: { id: "user_2", email: "b@example.test" } }));
    expect(window.localStorage.length).toBe(0);

    saveReviewDraft({ apiOrigin: "http://localhost:3000/api", accountId: "user_2" }, task, { form: "reformulate", text: "b" }, now);
    act(() => useAuthStore.setState({ user: null, status: "anon" }));
    expect(window.localStorage.length).toBe(0);

    stop();
    act(() => useAuthStore.setState({ user: { id: "user_3", email: "c@example.test" } }));
    saveReviewDraft({ apiOrigin: "http://localhost:3000/api", accountId: "user_3" }, task, { form: "reformulate", text: "c" }, now);
    act(() => useAuthStore.setState({ user: null }));
    expect(window.localStorage.length).toBe(1);
  });

  it("020-FR-052 survives a browser that refuses storage, and never sends or logs the text", () => {
    const refusing = {
      getItem: () => { throw new Error("denied"); },
      setItem: () => { throw new Error("quota"); },
      removeItem: () => { throw new Error("denied"); },
      key: () => { throw new Error("denied"); },
      get length(): number { throw new Error("denied"); }
    } as unknown as Storage;

    expect(() => saveReviewDraft(scope, task, { form: "reformulate", text: sentinel }, now, refusing)).not.toThrow();
    expect(loadReviewDraft(scope, task, now, refusing)).toBeNull();
    expect(() => removeReviewDraft(scope, task, refusing)).not.toThrow();
    expect(() => sweepReviewDrafts(scope, now, refusing)).not.toThrow();
    expect(() => clearReviewLocalState(scope, refusing)).not.toThrow();
    expect(() => removeOtherFormulationDrafts(scope, "task_9f3c", "form_a", refusing)).not.toThrow();

    saveReviewDraft(scope, task, { form: "reformulate", text: sentinel }, now);
    loadReviewDraft(scope, task, now);
    expect(fetchSpy).not.toHaveBeenCalled();
    for (const spy of consoleSpies) expect(spy).not.toHaveBeenCalled();
  });
});
