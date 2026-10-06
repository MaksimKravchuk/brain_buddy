import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import PrivacyPolicyPage from "../PrivacyPolicyPage";

function renderPolicy() {
  return render(
    <MemoryRouter initialEntries={["/privacy"]}>
      <PrivacyPolicyPage />
    </MemoryRouter>
  );
}

describe("PrivacyPolicyPage", () => {
  it("covers the GDPR-required disclosures", () => {
    renderPolicy();

    expect(screen.getByRole("heading", { name: /privacy policy/i })).toBeInTheDocument();
    for (const heading of [
      /who we are/i,
      /what we collect/i,
      /why we process it/i,
      /how long we keep it/i,
      /who else processes your data/i,
      /international transfers/i,
      /your rights/i,
      /cookies/i
    ]) {
      expect(screen.getByRole("heading", { name: heading })).toBeInTheDocument();
    }

    // Subprocessors and the single strictly-necessary cookie are named.
    expect(screen.getAllByText(/OpenAI/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Fly\.io/).length).toBeGreaterThan(0);
    expect(screen.getByText(/brainbuddy_session/)).toBeInTheDocument();
    // A working contact channel is offered.
    expect(screen.getAllByRole("link", { name: /@/ }).length).toBeGreaterThan(0);
  });

  it("009-SC-005: discloses operator account administration and the disposition of its records", () => {
    renderPolicy();

    // docs/data-retention.md names this page as the user-facing summary that
    // must stay in sync with it, so the four decided facts are pinned here:
    // the purpose, its legal basis, the content-free platform-log retention,
    // and that those records are outside both the export and account purge.
    expect(screen.getByText(/account administration/i)).toBeInTheDocument();
    expect(screen.getByText(/Art\. 6\(1\)\(f\)/)).toBeInTheDocument();
    expect(screen.getByText(/content-free line in our platform logs/i)).toBeInTheDocument();
    expect(screen.getByText(/not part of\s+your data export/i)).toBeInTheDocument();
    expect(screen.getByText(/not erased by account deletion/i)).toBeInTheDocument();
    expect(screen.getByText(/Operators never see your content/i)).toBeInTheDocument();
  });

  it("010-SC-007: names the runtime SQLite store and its disposition", () => {
    renderPolicy();

    // docs/data-retention.md names this page as the user-facing summary that
    // must stay in sync with it. The runtime store now covers six managed flags
    // (020 added weekly_review). The decided facts pinned here are what it holds,
    // that purge scrubs it, and that it is outside the export.
    expect(screen.getByText(/one SQLite store/i)).toBeInTheDocument();
    expect(screen.getByText(/covering six managed flags/i)).toBeInTheDocument();
    expect(screen.getByText(/holds only your account id per flag/i)).toBeInTheDocument();
    expect(screen.getByText(/scrubbed when your account is purged/i)).toBeInTheDocument();
    expect(screen.getByText(/covering six managed flags:.*excluded from your data export/i)).toBeInTheDocument();
  });

  it("020-FR-043: names the weekly review settings and records, their export, purge and undo window", () => {
    renderPolicy();
    const collected = screen.getByRole("heading", { name: /what we collect/i }).closest("section");
    const retention = screen.getByRole("heading", { name: /how long we keep it/i }).closest("section");

    // docs/data-retention.md (spec 020 rows): review day, time and time zone are
    // stored review settings; review records live for the account's life, are
    // exported and purged; the content-bearing undo copies last 7 days.
    expect(collected).toHaveTextContent(/weekly review/i);
    expect(collected).toHaveTextContent(/review day, time and time zone/i);
    expect(retention).toHaveTextContent(/review records.*kept until you delete your account/i);
    expect(retention).toHaveTextContent(/included in your data export and erased when your account is purged/i);
    expect(retention).toHaveTextContent(/undo copies.*7 days/i);
  });

  it("020-FR-043 020-FR-044: names the task timing data kept for every account, flag on or off", () => {
    renderPolicy();
    const collected = screen.getByRole("heading", { name: /what we collect/i }).closest("section");

    // Clock fields are written on every user's Next tasks whatever the flag
    // state, and decisions, settings and the explainer acknowledgement are
    // accepted with the flag off, so the disclosure is not conditional on it.
    expect(collected).not.toHaveTextContent(/if the weekly review is switched on for you/i);
    expect(collected).toHaveTextContent(/for every account, whether or not the\s+weekly review is switched on/i);
    expect(collected).toHaveTextContent(/when its current wording started/i);
    expect(collected).toHaveTextContent(/keep it 7 more days and your reason/i);
    expect(collected).toHaveTextContent(/the moment before which it will not move to Someday/i);
    expect(collected).toHaveTextContent(/how many times in a row its wording\s+stalled/i);
    expect(collected).toHaveTextContent(/moved to Someday automatically, when that happened/i);
    expect(collected).toHaveTextContent(/first acknowledged the weekly review's explanation/i);
    expect(collected).toHaveTextContent(/stall-reason code you pick/i);
    expect(collected).toHaveTextContent(/accepted from your devices even while the weekly review is switched off/i);
  });

  it("012-FR-007: names OpenAI's title-suggestion processing purpose", () => {
    renderPolicy();

    const processors = screen.getByRole("heading", { name: /who else processes your data/i }).closest("section");
    expect(processors).toHaveTextContent(
      /OpenAI.*title suggestions.*current task draft.*selected Project name.*prior task titles/i
    );
  });

  it("014-FR-016 / 014-SC-007: states the external-agent relay retention tiers honestly", () => {
    renderPolicy();

    // docs/data-retention.md names this page as the user-facing summary that
    // must stay in sync with it. The relay rows there decide five facts, and
    // each is pinned here in the words a user actually reads: the 30-day
    // content tier, the 90-day identifier tier, the run id that is the run's
    // correlation ID and is kept — not erased — until account deletion, the
    // 90-day audit entries, the card summary that lives for the connection's
    // lifetime and dies on disconnect, and the per-run callback address only
    // the agent itself can delete.
    const retention = screen.getByRole("heading", { name: /how long we keep it/i }).closest("section");

    expect(retention).toHaveTextContent(/supporting items you kept/i);
    expect(retention).toHaveTextContent(/deleted after 30 days/i);
    expect(retention).toHaveTextContent(/agent's task and message identifiers/i);
    expect(retention).toHaveTextContent(/for up to 90 days/i);

    expect(retention).toHaveTextContent(/correlation ID/);
    expect(retention).toHaveTextContent(/stays with the run record until you delete your account/i);
    expect(retention).toHaveTextContent(/outcomes only, never your content.*kept for 90 days/i);

    expect(retention).toHaveTextContent(
      /kept for as long as the connection exists and is erased the moment you disconnect/i
    );
    expect(retention).toHaveTextContent(/callback address we registered with the agent/i);
    expect(retention).toHaveTextContent(/only the agent can delete its copy/i);
  });

  it("017-FR-017 017-SC-008 discloses the browser-local last-used agent record and cleanup limits", () => {
    renderPolicy();
    const retention = screen.getByRole("heading", { name: /how long we keep it/i }).closest("section");

    expect(retention).toHaveTextContent(/last-used agent preference/i);
    expect(retention).toHaveTextContent(/connection ID and confirmation time/i);
    expect(retention).toHaveTextContent(/never sent to our server/i);
    expect(retention).toHaveTextContent(/not included in your data export/i);
    expect(retention).toHaveTextContent(/eligible for 30 days/i);
    expect(retention).toHaveTextContent(/sign out.*account changes.*starts.*regains focus/i);
    expect(retention).toHaveTextContent(/clear Brain Buddy site data/i);
  });

  it("019-FR-020 discloses CRT browser-local recovery scope, retention, and purge limits", () => {
    renderPolicy();
    const retention = screen.getByRole("heading", { name: /how long we keep it/i }).closest("section");

    expect(retention).toHaveTextContent(/graph\/layout content/i);
    expect(retention).toHaveTextContent(/immutable in-flight save snapshot/i);
    expect(retention).toHaveTextContent(/queued commands and idempotency-key UUID/i);
    expect(retention).toHaveTextContent(/owner\/origin\/tree-scoped/i);
    expect(retention).toHaveTextContent(/not included in your data export/i);
    expect(retention).toHaveTextContent(/30 days without edit\/use/i);
    expect(retention).toHaveTextContent(/stale draft stays outside the canvas/i);
    expect(retention).toHaveTextContent(/backup.*recover.*discard/i);
    expect(retention).toHaveTextContent(/recovering resets the inactivity window/i);
    expect(retention).toHaveTextContent(/sign-out.*account-switch.*account-deletion/i);
    expect(retention).toHaveTextContent(/active origin/i);
    expect(retention).toHaveTextContent(/server cannot purge.*other browser\/device/i);
    expect(retention).toHaveTextContent(/unencrypted.*device backups/i);
    expect(retention).toHaveTextContent(/online-first.*no cross-device offline merge/i);
  });

  it("019-FR-020 distinguishes content-free CRT observability from exported and purged data", () => {
    renderPolicy();
    const retention = screen.getByRole("heading", { name: /how long we keep it/i }).closest("section");

    expect(retention).toHaveTextContent(/CRT operational log lines/);
    expect(retention).toHaveTextContent(/correlation id.*opaque tree id.*operation.*revision/i);
    expect(retention).toHaveTextContent(/never.*graph text.*request or response bodies.*idempotency keys/i);
    expect(retention).toHaveTextContent(/hosting platform.*log window/i);
    expect(retention).toHaveTextContent(/cannot erase platform logs/i);
    expect(retention).toHaveTextContent(/excluded from.*data export/i);
  });

  it("records the date the policy last changed", () => {
    renderPolicy();
    expect(screen.getByText(/October 6, 2026/)).toBeInTheDocument();
  });

  it("links back to sign in", () => {
    renderPolicy();
    expect(screen.getByRole("link", { name: /back to sign in/i })).toHaveAttribute(
      "href",
      "/login"
    );
  });
});
