import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { getApiBaseUrl } from "../../../api/client";
import { useAuthStore } from "../../../stores/authStore";
import { loadStepDraft, saveStepDraft } from "../reviewFormDrafts";
import { useReviewDrafts } from "../useReviewDrafts";
import { signIn } from "./reviewKit";

const DRAFT_PREFIX = "bb.reviewFormDraft.v1.";
const draftKeys = () => Object.keys(window.localStorage).filter((key) => key.startsWith(DRAFT_PREFIX));

beforeEach(() => {
  window.localStorage.clear();
  signIn();
});

afterEach(() => {
  window.localStorage.clear();
  act(() => useAuthStore.setState({ user: null, status: "loading" }));
});

describe("020-FR-052 the drafts hook of a review step", () => {
  it("020-FR-052 saves, loads and clears one field, and an unchanged text is no draft", () => {
    const { result } = renderHook(() => useReviewDrafts("review_1", "inbox"));

    result.current.save("t1", "title", "Buy paper edited", "Buy paper");
    expect(result.current.load("t1", "title")).toBe("Buy paper edited");
    expect(result.current.load("t1", "waiting")).toBeNull();

    result.current.save("t1", "title", "Buy paper", "Buy paper");
    expect(result.current.load("t1", "title")).toBeNull();

    result.current.save("t1", "title", "again");
    result.current.clear("t1", "title");
    expect(draftKeys()).toEqual([]);
  });

  it("020-FR-052 clears only its own step of its own run", () => {
    const { result } = renderHook(() => useReviewDrafts("review_1", "inbox"));
    const scope = { apiOrigin: getApiBaseUrl(), accountId: "user-1" };
    result.current.save("t1", "title", "one");
    result.current.save("t2", "waiting", "two");
    const other = { sessionId: "review_1", step: "waiting", itemId: "t1", field: "title" };
    saveStepDraft(scope, other, "elsewhere");
    saveStepDraft(scope, { ...other, sessionId: "review_2", step: "inbox" }, "another run");

    result.current.clearAll();

    expect(draftKeys()).toHaveLength(2);
    expect(loadStepDraft(scope, other)).toBe("elsewhere");
  });

  it("020-FR-052 once the account has changed it writes and removes nothing", () => {
    const { result } = renderHook(() => useReviewDrafts("review_1", "inbox"));
    result.current.save("t1", "title", "mine");
    const before = draftKeys();

    act(() => signIn("user-2"));
    result.current.save("t1", "title", "not mine");
    result.current.save("t2", "title", "not mine either");
    result.current.clear("t1", "title");
    result.current.clearAll();

    expect(draftKeys()).toEqual(before);
    expect(draftKeys().some((key) => key.includes(".user-2."))).toBe(false);
    expect(result.current.load("t1", "title")).toBe("mine");
  });
});
