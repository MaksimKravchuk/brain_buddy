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

  it("links back to sign in", () => {
    renderPolicy();
    expect(screen.getByRole("link", { name: /back to sign in/i })).toHaveAttribute(
      "href",
      "/login"
    );
  });
});
