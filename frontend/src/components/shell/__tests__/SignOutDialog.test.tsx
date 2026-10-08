import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { getApiBaseUrl } from "../../../api/client";
import * as crtBoundary from "../../../features/crt/crtDraftCoordinator";
import { saveReviewDraft } from "../../../features/review/reviewFormDrafts";
import { SignOutDialog } from "../SignOutDialog";
import { loadSignOutSummary, signOutSentences, type SignOutSummary } from "../signOutSummary";

const none: SignOutSummary = { unsavedWork: false };

function renderDialog(overrides: Partial<Parameters<typeof SignOutDialog>[0]> = {}) {
  const handlers = { onCancel: vi.fn(), onConfirm: vi.fn() };
  render(<SignOutDialog summary={none} pending={false} notice={null} {...handlers} {...overrides} />);
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
  it("020-FR-052 gives a short plain confirmation when nothing unsaved would be lost", () => {
    renderDialog();

    const dialog = screen.getByRole("alertdialog", { name: "Sign out?" });
    expect(dialog).toHaveAccessibleDescription(
      "You'll be signed out of Brain Buddy on this browser. Your tasks stay in your account."
    );
    expect(dialog).not.toHaveTextContent("will be lost");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("020-FR-052 warns once, in general words, that unsaved changes in this browser will be lost", () => {
    renderDialog({ summary: { unsavedWork: true } });

    expect(screen.getByRole("alertdialog")).toHaveAccessibleDescription(
      "You'll be signed out of Brain Buddy on this browser. Your tasks stay in your account. " +
        "Unsaved changes in this browser will be lost: they have not been saved to your account."
    );
    expect(signOutSentences({ unsavedWork: true })).toHaveLength(2);
    expect(signOutSentences({ unsavedWork: false })).toHaveLength(1);
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

  it("020-FR-052 while signing out Tab and Shift+Tab neither throw nor leave the dialog", async () => {
    const user = userEvent.setup();
    renderDialog({ pending: true });
    const dialog = screen.getByRole("alertdialog");

    expect(dialog).toHaveFocus();
    await user.tab();
    expect(dialog).toHaveFocus();
    await user.tab({ shift: true });
    expect(dialog).toHaveFocus();
  });

  it("020-FR-052 says the person is still signed in after a sign-out that did not finish, or that something changed", () => {
    const { unmount } = render(<SignOutDialog summary={none} pending={false} notice="failed" onCancel={vi.fn()} onConfirm={vi.fn()} />);

    expect(screen.getByRole("alert")).toHaveTextContent("Sign-out didn't finish. You're still signed in. Try again.");
    expect(screen.getByRole("button", { name: "Sign out" })).toBeEnabled();
    unmount();

    render(<SignOutDialog summary={{ unsavedWork: true }} pending={false} notice="changed" onCancel={vi.fn()} onConfirm={vi.fn()} />);
    expect(screen.getByRole("alert")).toHaveTextContent("Something changed since this opened. Check and confirm again.");
  });
});

describe("Sign-out summary of unsaved local work", () => {
  it("020-FR-052 reports unsaved work from this account's weekly-review drafts alone", async () => {
    vi.spyOn(crtBoundary, "countCrtOwnerDrafts").mockResolvedValue(0);
    const scope = { apiOrigin: getApiBaseUrl(), accountId: "user-1" };
    saveReviewDraft({ ...scope, accountId: "user-2" }, { kind: "project", projectId: "p1" }, { form: "first_step", text: "other" });
    await expect(loadSignOutSummary("user-1")).resolves.toEqual({ unsavedWork: false });

    saveReviewDraft(scope, { kind: "task", taskId: "t1", formulationId: "f1" }, { form: "reformulate", text: "one" });
    await expect(loadSignOutSummary("user-1")).resolves.toEqual({ unsavedWork: true });
  });

  it("020-FR-052 reports unsaved work from Thinking Mode drafts alone", async () => {
    const count = vi.spyOn(crtBoundary, "countCrtOwnerDrafts").mockResolvedValue(4);

    await expect(loadSignOutSummary("user-1")).resolves.toEqual({ unsavedWork: true });
    expect(count).toHaveBeenCalledWith("user-1");
  });

  it("020-FR-052 reports nothing it cannot read: a refused store or an unlistable CRT store reads as none", async () => {
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
