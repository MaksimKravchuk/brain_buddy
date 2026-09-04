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
    // must stay in sync with it. The runtime store now covers four managed flags.
    // from a rollout file into one SQLite store; the decided facts pinned
    // here are what it holds, that purge scrubs it, and that it is outside
    // the export.
    expect(screen.getByText(/one SQLite store/i)).toBeInTheDocument();
    expect(screen.getByText(/covering four managed flags/i)).toBeInTheDocument();
    expect(screen.getByText(/holds only your account id per flag/i)).toBeInTheDocument();
    expect(screen.getByText(/scrubbed when your account is purged/i)).toBeInTheDocument();
    expect(screen.getByText(/excluded from your data export/i)).toBeInTheDocument();
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

  it("records the date the policy last changed", () => {
    renderPolicy();
    expect(screen.getByText(/September 4, 2026/)).toBeInTheDocument();
  });

  it("links back to sign in", () => {
    renderPolicy();
    expect(screen.getByRole("link", { name: /back to sign in/i })).toHaveAttribute(
      "href",
      "/login"
    );
  });
});
