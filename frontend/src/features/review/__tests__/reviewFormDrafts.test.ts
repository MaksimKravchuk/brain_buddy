import { act } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useAuthStore } from "../../../stores/authStore";
import {
  bindReviewLocalState,
  clearReviewLocalState,
  countUnsavedReviewDrafts,
  DRAFT_MAX_AGE_MS,
  loadReviewDraft,
  loadStepDraft,
  removeOtherFormulationDrafts,
  removeReviewDraft,
  removeStepDraft,
  removeStepDrafts,
  reviewDraftKey,
  reviewStepDraftKey,
  saveReviewDraft,
  saveStepDraft,
  subscribeReviewLocalCleanup,
  sweepReviewLocalState
} from "../reviewFormDrafts";

const scope = { apiOrigin: "http://localhost:3000/api", accountId: "user_1" };
const otherScope = { apiOrigin: "http://localhost:3000/api", accountId: "user_2" };
const task = { kind: "task", taskId: "task_9f3c", formulationId: "form_a" } as const;
const stepField = { sessionId: "review_1", step: "inbox", itemId: "task_9f3c", field: "title" } as const;
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
    sweepReviewLocalState(scope);
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
    sweepReviewLocalState(scope, later);
    expect(loadReviewDraft(scope, task, now)).toBeNull();
    expect(loadReviewDraft(scope, { ...task, taskId: "task_fresh" }, later)?.text).toBe("fresh");
    expect(window.localStorage.getItem("bb.taskDetailDraft.v1.unrelated")).toBe("kept");
  });

  it("020-FR-052 the sweep removes another account's drafts, which is how an account switch clears them", () => {
    saveReviewDraft(otherScope, task, { form: "reformulate", text: "someone else's" }, now);
    saveReviewDraft(scope, task, { form: "reformulate", text: "mine" }, now);

    sweepReviewLocalState(scope, now);

    expect(loadReviewDraft(otherScope, task, now)).toBeNull();
    expect(loadReviewDraft(scope, task, now)?.text).toBe("mine");
  });

  it("020-FR-052 020-FR-015 the sweep also removes another account's While-you-were-away day and last zone", () => {
    const wywa = (account: string) => `bb.reviewWywaLastShown.v1.http%3A%2F%2Flocalhost%3A3000%2Fapi.${account}`;
    const zone = (account: string) => `bb.reviewLastZone.v1.http%3A%2F%2Flocalhost%3A3000%2Fapi.${account}`;
    for (const account of ["user_1", "user_2", "user_10"]) {
      window.localStorage.setItem(wywa(account), "2026-10-09");
      window.localStorage.setItem(zone(account), "Europe/Berlin");
    }
    window.localStorage.setItem("bb.reviewSomethingUnversioned", "left alone");

    sweepReviewLocalState(scope, now);

    expect(Object.keys(window.localStorage).sort()).toEqual([wywa("user_1"), zone("user_1"), "bb.reviewSomethingUnversioned"].sort());
  });

  it("020-FR-052 with no account signed in the sweep removes only expired drafts, of any account", () => {
    const later = new Date(now.getTime() + DRAFT_MAX_AGE_MS);
    saveReviewDraft(scope, task, { form: "reformulate", text: "old" }, now);
    saveReviewDraft(otherScope, task, { form: "reformulate", text: "fresh" }, later);
    window.localStorage.setItem("bb.reviewWywaLastShown.v1.http%3A%2F%2Flocalhost%3A3000%2Fapi.user_1", "2026-10-09");

    sweepReviewLocalState(null, later);

    expect(loadReviewDraft(scope, task, later)).toBeNull();
    expect(loadReviewDraft(otherScope, task, later)?.text).toBe("fresh");
    expect(window.localStorage.getItem("bb.reviewWywaLastShown.v1.http%3A%2F%2Flocalhost%3A3000%2Fapi.user_1")).toBe("2026-10-09");
  });

  it("020-FR-052 020-FR-042 the app-wide binding sweeps at start and cleans up on sign-out whatever the weekly_review flag says", () => {
    const apiOrigin = "http://localhost:3000/api";
    const expired = new Date(Date.now() - DRAFT_MAX_AGE_MS - 1000);
    saveReviewDraft({ apiOrigin, accountId: "user_1" }, task, { form: "reformulate", text: "expired" }, expired);
    saveReviewDraft({ apiOrigin, accountId: "user_1" }, { ...task, taskId: "task_fresh" }, { form: "reformulate", text: "fresh" });
    saveReviewDraft({ apiOrigin, accountId: "user_2" }, task, { form: "reformulate", text: "other" });
    window.localStorage.setItem(`bb.reviewWywaLastShown.v1.${encodeURIComponent(apiOrigin)}.user_2`, "2026-10-09");

    // App start: nobody is signed in yet, and the flag is not known.
    const unbind = bindReviewLocalState(apiOrigin);
    expect(loadReviewDraft({ apiOrigin, accountId: "user_1" }, task)).toBeNull();
    expect(window.localStorage.length).toBe(3);

    // Signed in without the weekly_review flag: another account's keys go.
    act(() => useAuthStore.setState({ user: { id: "user_1", email: "a@example.test", feature_flags: {} }, status: "authed" }));
    expect(Object.keys(window.localStorage)).toEqual([reviewDraftKey({ apiOrigin, accountId: "user_1" }, { ...task, taskId: "task_fresh" })]);

    // A window focus sweeps again.
    window.localStorage.setItem(`bb.reviewLastZone.v1.${encodeURIComponent(apiOrigin)}.user_3`, "UTC");
    window.dispatchEvent(new Event("focus"));
    expect(window.localStorage.length).toBe(1);

    // clearSession (the 401 path) clears the departing account's keys, flag or not.
    window.localStorage.setItem(`bb.reviewWywaLastShown.v1.${encodeURIComponent(apiOrigin)}.user_1`, "2026-10-09");
    act(() => {
      useAuthStore.getState().clearSession();
    });
    expect(window.localStorage.length).toBe(0);

    unbind();
    window.dispatchEvent(new Event("focus"));
    act(() => useAuthStore.setState({ user: { id: "user_4", email: "d@example.test" }, status: "authed" }));
    saveReviewDraft({ apiOrigin, accountId: "user_4" }, task, { form: "reformulate", text: "kept" });
    act(() => useAuthStore.setState({ user: null, status: "anon" }));
    expect(window.localStorage.length).toBe(1);
  });

  it("020-FR-052 discards a corrupt or foreign-shaped entry instead of showing it", () => {
    const key = reviewDraftKey(scope, task);
    for (const corrupt of ["not json", JSON.stringify({ form: "reformulate" }), JSON.stringify({ form: "poem", text: "x", savedAt: now.toISOString() }), JSON.stringify(null)]) {
      window.localStorage.setItem(key, corrupt);
      expect(loadReviewDraft(scope, task, now)).toBeNull();
      expect(window.localStorage.getItem(key)).toBeNull();
    }
    window.localStorage.setItem(key, "not json");
    sweepReviewLocalState(scope, now);
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

  it("020-FR-052 counts the unsaved drafts a sign-out removes: this account's, with text, not expired, read-only", () => {
    saveReviewDraft(scope, task, { form: "reformulate", text: sentinel }, now);
    saveReviewDraft(scope, { kind: "project", projectId: "project_1a" }, { form: "first_step", text: "call" }, now);
    saveStepDraft(scope, stepField, "step text", now);
    saveReviewDraft(otherScope, task, { form: "reformulate", text: "another account" }, now);
    saveReviewDraft(scope, { ...task, taskId: "task_old" }, { form: "waiting", text: "stale" }, new Date(now.getTime() - DRAFT_MAX_AGE_MS));
    window.localStorage.setItem(`${reviewDraftKey(scope, { ...task, taskId: "task_empty" })}`, JSON.stringify({ form: "waiting", text: "", savedAt: now.toISOString() }));
    window.localStorage.setItem(`${reviewDraftKey(scope, { ...task, taskId: "task_bad" })}`, "not json");
    window.localStorage.setItem("bb.reviewWywaLastShown.v1.http%3A%2F%2Flocalhost%3A3000%2Fapi.user_1", "2026-10-09");
    const before = window.localStorage.length;

    expect(countUnsavedReviewDrafts(scope, now)).toBe(3);
    expect(countUnsavedReviewDrafts(otherScope, now)).toBe(1);
    expect(countUnsavedReviewDrafts({ ...scope, accountId: "user_3" }, now)).toBe(0);
    expect(window.localStorage.length).toBe(before);

    window.localStorage.clear();
    saveReviewDraft(scope, task, { form: "reformulate", text: sentinel });
    expect(countUnsavedReviewDrafts(scope)).toBe(1);
  });

  it("020-FR-052 counts nothing in a browser that refuses storage", () => {
    const refusing = {
      getItem: () => { throw new Error("denied"); },
      key: () => { throw new Error("denied"); },
      get length(): number { throw new Error("denied"); }
    } as unknown as Storage;

    expect(countUnsavedReviewDrafts(scope, now, refusing)).toBe(0);
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

  it("020-FR-052 keeps a review step's field under its own run, step, item and field, never meeting a task or project key", () => {
    expect(reviewStepDraftKey(scope, stepField)).toBe(
      "bb.reviewFormDraft.v1.http%3A%2F%2Flocalhost%3A3000%2Fapi.user_1.step.review_1.inbox.task_9f3c.title"
    );
    saveStepDraft(scope, stepField, "typed", now);
    saveReviewDraft(scope, task, { form: "reformulate", text: "wording" }, now);

    expect(loadStepDraft(scope, stepField, now)).toBe("typed");
    expect(loadStepDraft(scope, { ...stepField, field: "waiting" }, now)).toBeNull();
    expect(loadStepDraft(otherScope, stepField, now)).toBeNull();
    removeOtherFormulationDrafts(scope, "task_9f3c", null);
    expect(loadStepDraft(scope, stepField, now)).toBe("typed");
    removeStepDraft(scope, stepField);
    expect(loadStepDraft(scope, stepField, now)).toBeNull();
    saveStepDraft(scope, stepField, "typed", now);
    saveStepDraft(scope, stepField, "", now);
    expect(loadStepDraft(scope, stepField, now)).toBeNull();
  });

  it("020-FR-052 expires a step field's draft after 7 days, and the sweep and sign-out clear it like any other", () => {
    saveStepDraft(scope, stepField, "a week old", now);
    saveStepDraft(otherScope, stepField, "someone else's", now);
    const later = new Date(now.getTime() + DRAFT_MAX_AGE_MS);
    expect(loadStepDraft(scope, stepField, new Date(later.getTime() - 1))).toBe("a week old");
    expect(loadStepDraft(scope, stepField, later)).toBeNull();

    saveStepDraft(scope, stepField, "fresh", later);
    sweepReviewLocalState(scope, later);
    expect(loadStepDraft(scope, stepField, later)).toBe("fresh");
    expect(loadStepDraft(otherScope, stepField, later)).toBeNull();

    clearReviewLocalState(scope);
    expect(window.localStorage.length).toBe(0);
  });

  it("020-FR-052 removes every field draft of one step of one run and no other", () => {
    saveStepDraft(scope, stepField, "one", now);
    saveStepDraft(scope, { ...stepField, itemId: "task_other", field: "waiting" }, "two", now);
    saveStepDraft(scope, { ...stepField, step: "waiting" }, "other step", now);
    saveStepDraft(scope, { ...stepField, sessionId: "review_2" }, "other run", now);
    saveStepDraft(otherScope, stepField, "other account", now);

    removeStepDrafts(scope, "review_1", "inbox");

    expect(loadStepDraft(scope, stepField, now)).toBeNull();
    expect(loadStepDraft(scope, { ...stepField, step: "waiting" }, now)).toBe("other step");
    expect(loadStepDraft(scope, { ...stepField, sessionId: "review_2" }, now)).toBe("other run");
    expect(loadStepDraft(otherScope, stepField, now)).toBe("other account");
    expect(window.localStorage.length).toBe(3);
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
    expect(() => sweepReviewLocalState(scope, now, refusing)).not.toThrow();
    expect(() => clearReviewLocalState(scope, refusing)).not.toThrow();
    expect(() => removeOtherFormulationDrafts(scope, "task_9f3c", "form_a", refusing)).not.toThrow();
    expect(() => saveStepDraft(scope, stepField, sentinel, now, refusing)).not.toThrow();
    expect(loadStepDraft(scope, stepField, now, refusing)).toBeNull();
    expect(() => removeStepDraft(scope, stepField, refusing)).not.toThrow();
    expect(() => removeStepDrafts(scope, "review_1", "inbox", refusing)).not.toThrow();

    saveReviewDraft(scope, task, { form: "reformulate", text: sentinel }, now);
    loadReviewDraft(scope, task, now);
    expect(fetchSpy).not.toHaveBeenCalled();
    for (const spy of consoleSpies) expect(spy).not.toHaveBeenCalled();
  });
});
