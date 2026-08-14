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

  it("records the date the policy last changed", () => {
    renderPolicy();
    expect(screen.getByText(/August 13, 2026/)).toBeInTheDocument();
  });

  it("links back to sign in", () => {
    renderPolicy();
    expect(screen.getByRole("link", { name: /back to sign in/i })).toHaveAttribute(
      "href",
      "/login"
    );
  });
});
