import { afterEach, describe, expect, it } from "vitest";

import { getApiBaseUrl } from "../../../api/client";
import { forgetRelease, readRelease, rememberRelease, type RememberedRelease } from "../releaseMemory";

const release: RememberedRelease = { kind: "inbox_remainder", bulkId: "bulk_1", sessionId: "review_1", released: 12 };
const key = `bb.reviewRelease.v1.${encodeURIComponent(getApiBaseUrl())}.user-1`;

/** A storage that refuses every call, as private mode or a full quota does. */
const refusing = {
  getItem: () => {
    throw new Error("refused");
  },
  setItem: () => {
    throw new Error("refused");
  },
  removeItem: () => {
    throw new Error("refused");
  }
} as unknown as Storage;

afterEach(() => window.localStorage.clear());

describe("020-FR-030 the release whose Undo is still offered", () => {
  it("020-FR-030 is kept per account under a review key, holding ids and a count only", () => {
    rememberRelease("user-1", release);

    expect(window.localStorage.getItem(key)).toBe(JSON.stringify(release));
    expect(readRelease("user-1")).toEqual(release);
    expect(readRelease("user-2")).toBeNull();
    forgetRelease("user-1");
    expect(readRelease("user-1")).toBeNull();
  });

  it.each([
    ["nothing stored", null],
    ["text that is not JSON", "{oops"],
    ["a value without a bulk id", JSON.stringify({ kind: "restart", released: 3 })],
    ["a count that is text", JSON.stringify({ kind: "restart", bulkId: "bulk_1", released: "3" })],
    ["an unknown kind", JSON.stringify({ kind: "other", bulkId: "bulk_1", released: 3 })]
  ])("020-FR-030 reads %s as no release", (_label, stored) => {
    if (stored !== null) {
      window.localStorage.setItem(key, stored);
    }
    expect(readRelease("user-1")).toBeNull();
  });

  it("020-FR-030 never fails the review when the browser refuses its storage", () => {
    expect(() => rememberRelease("user-1", release, refusing)).not.toThrow();
    expect(() => forgetRelease("user-1", refusing)).not.toThrow();
    expect(readRelease("user-1", refusing)).toBeNull();
  });
});
