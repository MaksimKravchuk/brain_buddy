import { act } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { useAuthStore } from "../../../stores/authStore";
import { subscribeReviewLocalCleanup } from "../reviewFormDrafts";
import {
  localDay,
  markWhileAwayShown,
  readWhileAwayLastShown,
  shouldShowWhileAway,
  whileAwayLastShownKey,
  type WhileAwayContext
} from "../wywaPresentation";
import flowVectors from "./review_flow_vectors.json";

const scope = { apiOrigin: "http://localhost:3000/api", accountId: "user_1" };

afterEach(() => {
  window.localStorage.clear();
  act(() => useAuthStore.setState({ user: null, status: "loading" }));
});

describe("020-FR-015 While you were away: once a day at web open", () => {
  it.each(flowVectors.while_away.map((vector) => [vector.id, vector] as const))(
    "020-FR-015 %s decides like iOS and the server",
    (_id, vector) => {
      expect(
        shouldShowWhileAway({
          context: vector.context as WhileAwayContext,
          hasUnseen: vector.has_unseen,
          lastShownDay: vector.last_shown_day,
          today: vector.today
        })
      ).toBe(vector.expect);
    }
  );

  it("020-FR-015 keeps the last-shown day under the account's key, as a local calendar day with no content", () => {
    expect(whileAwayLastShownKey(scope)).toBe("bb.reviewWywaLastShown.v1.http%3A%2F%2Flocalhost%3A3000%2Fapi.user_1");
    expect(readWhileAwayLastShown(scope)).toBeNull();

    markWhileAwayShown(scope, "2026-10-09");

    expect(window.localStorage.getItem(whileAwayLastShownKey(scope))).toBe("2026-10-09");
    expect(readWhileAwayLastShown(scope)).toBe("2026-10-09");
    expect(readWhileAwayLastShown({ ...scope, accountId: "user_2" })).toBeNull();
  });

  it("020-FR-015 reads the local calendar day, not the UTC one", () => {
    const lateEvening = new Date(2026, 9, 9, 23, 30);
    expect(localDay(lateEvening)).toBe("2026-10-09");
    expect(localDay(new Date(2026, 0, 5, 0, 1))).toBe("2026-01-05");
    expect(localDay()).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  });

  it("020-FR-015 the key is removed on sign-out", () => {
    act(() => useAuthStore.setState({ user: { id: "user_1", email: "a@example.test" }, status: "authed" }));
    const stop = subscribeReviewLocalCleanup();
    markWhileAwayShown(scope, "2026-10-09");

    act(() => useAuthStore.setState({ user: null, status: "anon" }));

    expect(window.localStorage.getItem(whileAwayLastShownKey(scope))).toBeNull();
    stop();
  });

  it("020-FR-015 a browser that refuses storage still shows the dialog and never throws", () => {
    const refusing = {
      getItem: () => { throw new Error("denied"); },
      setItem: () => { throw new Error("quota"); }
    } as unknown as Storage;
    expect(readWhileAwayLastShown(scope, refusing)).toBeNull();
    expect(() => markWhileAwayShown(scope, "2026-10-09", refusing)).not.toThrow();
  });
});
