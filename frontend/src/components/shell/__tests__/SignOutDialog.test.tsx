import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { getApiBaseUrl } from "../../../api/client";
import * as crtBoundary from "../../../features/crt/crtDraftCoordinator";
import { saveReviewDraft } from "../../../features/review/reviewFormDrafts";
import { SignOutDialog } from "../SignOutDialog";
import { loadSignOutSummary, signOutSentences, type SignOutSummary } from "../signOutSummary";

const none: SignOutSummary = { reviewDrafts: 0, crtDrafts: 0 };

function renderDialog(overrides: Partial<Parameters<typeof SignOutDialog>[0]> = {}) {
  const handlers = { onCancel: vi.fn(), onConfirm: vi.fn() };
  render(<SignOutDialog summary={none} pending={false} failed={false} {...handlers} {...overrides} />);
  return handlers;
}

beforeEach(() => {
  window.localStorage.clear();
});

afterEach(() => {
  window.localStorage.clear();
  vi.restoreAllMocks();
});

describe("Sign-out confirmation copy and behaviour", () => {
  it("020-FR-052 gives a short plain confirmation when nothing unsaved would be removed", () => {
    renderDialog();

    const dialog = screen.getByRole("alertdialog", { name: "Sign out?" });
    expect(dialog).toHaveAccessibleDescription(
      "You'll be signed out of Brain Buddy on this browser. Your tasks stay in your account."
    );
    expect(dialog).not.toHaveTextContent("will also be removed");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it.each([
    [1, "1 unsaved weekly-review draft will also be removed from this browser."],
    [2, "2 unsaved weekly-review drafts will also be removed from this browser."]
  ])("020-FR-052 names %i unsaved weekly-review draft(s) in the native apps' words", (count, sentence) => {
    renderDialog({ summary: { reviewDrafts: count, crtDrafts: 0 } });

    expect(screen.getByRole("alertdialog")).toHaveTextContent(sentence);
    expect(screen.getByRole("alertdialog")).not.toHaveTextContent("Thinking Mode");
  });

  it("020-FR-052 names unsaved Thinking Mode drafts after the review drafts", () => {
    expect(signOutSentences({ reviewDrafts: 1, crtDrafts: 1 })).toEqual([
      "You'll be signed out of Brain Buddy on this browser. Your tasks stay in your account.",
      "1 unsaved weekly-review draft will also be removed from this browser.",
      "1 unsaved Thinking Mode draft will also be removed from this browser."
    ]);
    expect(signOutSentences({ reviewDrafts: 0, crtDrafts: 3 })[1]).toBe(
      "3 unsaved Thinking Mode drafts will also be removed from this browser."
    );
  });

  it("020-FR-052 starts on Cancel, cancels on Escape, and runs Sign out only from its own button", async () => {
    const user = userEvent.setup();
    const { onCancel, onConfirm } = renderDialog();

    expect(screen.getByRole("button", { name: "Cancel" })).toHaveFocus();
    await user.keyboard("{Escape}");
    expect(onCancel).toHaveBeenCalledTimes(1);
    expect(onConfirm).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onCancel).toHaveBeenCalledTimes(2);
    await user.click(screen.getByRole("button", { name: "Sign out" }));
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  it("020-FR-052 keeps Tab and Shift+Tab inside the dialog", async () => {
    const user = userEvent.setup();
    renderDialog();
    const cancel = screen.getByRole("button", { name: "Cancel" });
    const signOut = screen.getByRole("button", { name: "Sign out" });

    await user.tab();
    expect(signOut).toHaveFocus();
    await user.tab();
    expect(cancel).toHaveFocus();
    await user.tab({ shift: true });
    expect(signOut).toHaveFocus();
  });

  it("020-FR-052 waits while signing out: both buttons disabled, Escape ignored, busy announced", async () => {
    const user = userEvent.setup();
    const { onCancel } = renderDialog({ pending: true });

    expect(screen.getByRole("alertdialog")).toHaveAttribute("aria-busy", "true");
    expect(screen.getByRole("button", { name: "Cancel" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Signing out…" })).toBeDisabled();
    await user.keyboard("{Escape}");
    expect(onCancel).not.toHaveBeenCalled();
  });

  it("020-FR-052 says the person is still signed in after a sign-out that did not finish", () => {
    renderDialog({ failed: true });

    expect(screen.getByRole("alert")).toHaveTextContent("Sign-out didn't finish. You're still signed in. Try again.");
    expect(screen.getByRole("button", { name: "Sign out" })).toBeEnabled();
  });
});

describe("Sign-out summary of unsaved local work", () => {
  it("020-FR-052 counts this account's weekly-review drafts and the Thinking Mode drafts", async () => {
    const scope = { apiOrigin: getApiBaseUrl(), accountId: "user-1" };
    saveReviewDraft(scope, { kind: "task", taskId: "t1", formulationId: "f1" }, { form: "reformulate", text: "one" });
    saveReviewDraft(scope, { kind: "project", projectId: "p1" }, { form: "first_step", text: "two" });
    saveReviewDraft({ ...scope, accountId: "user-2" }, { kind: "project", projectId: "p1" }, { form: "first_step", text: "other" });
    const count = vi.spyOn(crtBoundary, "countCrtOwnerDrafts").mockResolvedValue(4);

    await expect(loadSignOutSummary("user-1")).resolves.toEqual({ reviewDrafts: 2, crtDrafts: 4 });
    expect(count).toHaveBeenCalledWith("user-1");
  });

  it("020-FR-052 names nothing it cannot count: a refused store or an unlistable CRT store reads as none", async () => {
    const refused = vi.spyOn(window, "localStorage", "get").mockImplementation(() => { throw new Error("denied"); });
    const count = vi.spyOn(crtBoundary, "countCrtOwnerDrafts").mockResolvedValue(null);
    try {
      await expect(loadSignOutSummary("user-1")).resolves.toEqual(none);

      count.mockRejectedValue(new Error("listing"));
      await expect(loadSignOutSummary("user-1")).resolves.toEqual(none);
    } finally {
      refused.mockRestore();
    }
  });
});
