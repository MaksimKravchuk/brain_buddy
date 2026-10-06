import { act, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { modernAuthApi } from "../../../api/modernAuth";
import { useAuthStore } from "../../../stores/authStore";
import { saveProviderAttempt } from "../authFlow";
import { ProviderCompletionPage } from "../ProviderCompletionPage";

vi.mock("../../../api/modernAuth", () => ({ modernAuthApi: { completeProvider: vi.fn(), methods: vi.fn() } }));
const token = "a".repeat(43);
const originalHydrate = useAuthStore.getState().hydrate;
function pending(owner = "A") {
  saveProviderAttempt({ attemptId: token, state: token, verifier: "v".repeat(43), purpose: "link", expectedOwner: owner, action: "link:google", destination: `/settings/account?expected_owner=${owner}`, expiresAt: Date.now() + 60000 });
  history.replaceState(null, "", `/auth/complete#attempt=${token}&state=${token}&grant=${token}`);
}
const show = () => render(<MemoryRouter initialEntries={["/auth/complete"]}><Routes><Route path="/auth/complete" element={<ProviderCompletionPage />} /><Route path="/settings/account" element={<div>Methods metadata</div>} /></Routes></MemoryRouter>);
describe("023-FR-006/015/021 callback owner and one-use handoff", () => {
  beforeEach(() => { vi.clearAllMocks(); sessionStorage.clear(); useAuthStore.setState({ user: null, status: "loading" }); });
  afterEach(() => { useAuthStore.setState({ hydrate: originalHydrate }); history.replaceState(null, "", "/"); vi.restoreAllMocks(); });
  it("clears the URL before waiting for cold session hydration and completes once for the same owner", async () => {
    let resolve!: () => void;
    useAuthStore.setState({ hydrate: vi.fn(() => new Promise<void>(done => { resolve = () => { useAuthStore.setState({ user: { id: "A", email: "a@test.example" }, status: "authed" }); done(); }; })) });
    vi.mocked(modernAuthApi.completeProvider).mockResolvedValue({ status: "linked", user: { id: "A", email: "a@test.example" } });
    pending(); show();
    expect(location.hash).toBe(""); expect(sessionStorage.length).toBe(0);
    expect(modernAuthApi.completeProvider).not.toHaveBeenCalled();
    await act(async () => resolve());
    expect(await screen.findByText("Methods metadata")).toBeInTheDocument();
    expect(modernAuthApi.completeProvider).toHaveBeenCalledTimes(1);
  });
  it("023-FR-015 waits for the session that superseded the callback hydration", async () => {
    const hydrate = vi.fn(async () => {});
    useAuthStore.setState({ hydrate });
    vi.mocked(modernAuthApi.completeProvider).mockResolvedValue({ status: "linked", user: { id: "A", email: "a@test.example" } });
    pending(); show();
    await waitFor(() => expect(hydrate).toHaveBeenCalledTimes(1));
    expect(screen.queryByRole("alert")).toBeNull();
    expect(modernAuthApi.completeProvider).not.toHaveBeenCalled();
    await act(async () => { useAuthStore.setState({ user: { id: "A", email: "a@test.example" }, status: "authed" }); });
    expect(await screen.findByText("Methods metadata")).toBeInTheDocument();
    expect(modernAuthApi.completeProvider).toHaveBeenCalledTimes(1);
  });
  it("stops when another tab changed the cookie owner, without submitting the handoff", async () => {
    useAuthStore.setState({ hydrate: vi.fn(async () => { useAuthStore.setState({ user: { id: "B", email: "b@test.example" }, status: "authed" }); }) });
    pending(); show();
    expect(await screen.findByRole("alert")).toHaveTextContent(/couldn't confirm whether linking finished/i);
    expect(modernAuthApi.completeProvider).not.toHaveBeenCalled();
  });
  it("does not replay a one-use handoff after a lost response", async () => {
    useAuthStore.setState({ user: { id: "A", email: "a@test.example" }, status: "authed" });
    vi.mocked(modernAuthApi.completeProvider).mockRejectedValue(new TypeError("offline"));
    pending(); show();
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(/check your sign-in methods/i));
    expect(modernAuthApi.completeProvider).toHaveBeenCalledTimes(1);
    expect(sessionStorage.length).toBe(0);
  });
});
