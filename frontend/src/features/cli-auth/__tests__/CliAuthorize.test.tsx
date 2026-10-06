import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { ApiError } from "../../../api/client";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useAuthStore } from "../../../stores/authStore";
import { safeAuthDestination } from "../../auth/authFlow";
import { CliAuthorizeEntry, CliAuthorizePage } from "../CliAuthorizePage";
import { captureCode, retainedCode } from "../code";
import { cliAuthApi } from "../api";

vi.mock("../api", () => ({ cliAuthApi: { request: vi.fn(), decision: vi.fn() } }));
const show = () => render(<MemoryRouter><CliAuthorizePage /></MemoryRouter>);
const request = { user_code: "ABCD-EFGH", client_name: "BrainBuddy CLI", created_at: new Date().toISOString(), expires_at: new Date(Date.now() + 600000).toISOString(), state: "pending" as const };

describe("024-FR-013 browser approval and safe return", () => {
  beforeEach(() => {
    sessionStorage.clear(); vi.clearAllMocks();
    useAuthStore.setState({ status: "authed", user: { id: "A", email: "a@example.com", feature_flags: { cli_auth: true } } });
    vi.mocked(cliAuthApi.request).mockResolvedValue(request);
    vi.mocked(cliAuthApi.decision).mockResolvedValue({ state: "approved" });
  });
  afterEach(() => { sessionStorage.clear(); vi.restoreAllMocks(); vi.useRealTimers(); history.replaceState(null, "", "/"); });
  it("captures only a short code before signed-out navigation and clears the fragment", async () => {
    useAuthStore.setState({ user: null, status: "anon" });
    history.replaceState(null, "", "/cli/authorize#user_code=ABCD-EFGH");
    render(<MemoryRouter initialEntries={["/cli/authorize#user_code=ABCD-EFGH"]}><Routes><Route path="/cli/authorize" element={<CliAuthorizeEntry />} /><Route path="/login" element={<div>Shared sign in</div>} /></Routes></MemoryRouter>);
    expect(await screen.findByText("Shared sign in")).toBeInTheDocument();
    expect(location.hash).toBe("");
    expect(retainedCode()?.userCode).toBe("ABCD-EFGH");
    expect(cliAuthApi.decision).not.toHaveBeenCalled();
  });
  it("shows the acting account and requires an explicit approval", async () => {
    captureCode("#user_code=ABCD-EFGH"); show();
    expect(await screen.findByText("a@example.com")).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "Approve access" })).toBeEnabled();
    expect(cliAuthApi.decision).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Approve access" }));
    expect(await screen.findByRole("status")).toHaveTextContent("Access approved");
    expect(cliAuthApi.decision).toHaveBeenCalledWith("ABCD-EFGH", "approve", expect.any(AbortSignal));
    expect(retainedCode()).toBeNull();
  });
  it("keeps an uncertain decision recoverable without claiming approval", async () => {
    vi.mocked(cliAuthApi.decision).mockRejectedValue(new Error("private-sentinel"));
    captureCode("#user_code=ABCD-EFGH"); show();
    fireEvent.click(await screen.findByRole("button", { name: "Approve access" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("could not confirm");
    expect(screen.queryByText("private-sentinel")).not.toBeInTheDocument();
    expect(retainedCode()?.userCode).toBe("ABCD-EFGH");
  });
  it("expires tab state after ten minutes and falls back to manual entry", () => {
    vi.useFakeTimers(); captureCode("#user_code=ABCD-EFGH"); vi.advanceTimersByTime(600001);
    expect(retainedCode()).toBeNull(); show();
    expect(screen.getByLabelText("Code from your CLI")).toBeInTheDocument();
    expect(cliAuthApi.request).not.toHaveBeenCalled();
  });
  it("does not fetch or approve when the effective flag is absent", () => {
    useAuthStore.setState({ user: { id: "A", email: "a@example.com" }, status: "authed" });
    captureCode("#user_code=ABCD-EFGH"); show();
    expect(screen.getByRole("alert")).toHaveTextContent("not available");
    expect(cliAuthApi.request).not.toHaveBeenCalled();
    expect(retainedCode()).toBeNull();
  });
  it("allows only the exact internal return route and never retains private proof", () => {
    expect(safeAuthDestination("/cli/authorize")).toBe("/cli/authorize");
    for (const input of ["//evil.example/cli/authorize", "https://evil.example/cli/authorize", "/cli/authorize/other", "/\\evil.example/cli/authorize"]) expect(safeAuthDestination(input)).toBe("/");
    expect(safeAuthDestination("/cli/authorize?redirect=https://evil.example#secret")).toBe("/cli/authorize");
    captureCode("#device_code=" + "p".repeat(43) + "&user_code=ABCD-EFGH");
    expect(retainedCode()).toBeNull();
  });
  it("supports manual entry after invalid or missing fragment", async () => {
    captureCode("#user_code=INVALID"); show();
    fireEvent.change(screen.getByLabelText("Code from your CLI"), { target: { value: "ABCD-EFGH" } });
    fireEvent.click(screen.getByRole("button", { name: "Check code" }));
    await waitFor(() => expect(cliAuthApi.request).toHaveBeenCalledWith("ABCD-EFGH", expect.any(AbortSignal)));
  });
  it.each(["approved", "denied", "consumed"] as const)("announces an already %s request without another decision", async state => {
    vi.mocked(cliAuthApi.request).mockResolvedValue({ ...request, state });
    captureCode("#user_code=ABCD-EFGH"); show();
    expect(await screen.findByRole("status")).toHaveTextContent(state === "denied" ? "Access denied" : "already approved");
    expect(cliAuthApi.decision).not.toHaveBeenCalled();
    expect(retainedCode()).toBeNull();
  });
  it.each([404, 403, 0])("recovers from lookup status %s with fixed nonreflecting copy", async status => {
    vi.mocked(cliAuthApi.request).mockRejectedValue(status ? new ApiError("private-sentinel", status, null, "12345678-1234-4234-8234-123456789abc") : new Error("private-sentinel"));
    captureCode("#user_code=ABCD-EFGH"); show();
    expect(await screen.findByRole("alert")).toHaveTextContent(status === 404 ? "unavailable or expired" : "could not check");
    if (status) expect(screen.getByRole("alert")).toHaveTextContent("Reference: 12345678-1234-4234-8234-123456789abc");
    expect(screen.queryByText("private-sentinel")).not.toBeInTheDocument();
    vi.mocked(cliAuthApi.request).mockResolvedValue(request);
    fireEvent.click(screen.getByRole("button", { name: "Check code again" }));
    expect(await screen.findByRole("button", { name: "Approve access" })).toBeEnabled();
  });
  it("keeps an uncertain decision recoverable with its safe reference", async () => {
    vi.mocked(cliAuthApi.decision).mockRejectedValue(new ApiError("private-sentinel", 503, null, "12345678-1234-4234-8234-123456789abc"));
    captureCode("#user_code=ABCD-EFGH"); show();
    fireEvent.click(await screen.findByRole("button", { name: "Approve access" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("could not confirm");
    expect(screen.getByRole("alert")).toHaveTextContent("Reference: 12345678-1234-4234-8234-123456789abc");
    expect(screen.queryByText("private-sentinel")).not.toBeInTheDocument();
    expect(retainedCode()?.userCode).toBe("ABCD-EFGH");
  });
  it.each([{ expires_at: "invalid" }, { expires_at: "2000-01-01T00:00:00Z" }, { user_code: "JKLM-NPQR" }, { client_name: "Foreign client" }])("rejects malformed or expired request metadata %j", async override => {
    vi.mocked(cliAuthApi.request).mockResolvedValue({ ...request, ...override });
    captureCode("#user_code=ABCD-EFGH"); show();
    expect(await screen.findByRole("alert")).toHaveTextContent("could not check");
    expect(screen.queryByRole("button", { name: "Approve access" })).not.toBeInTheDocument();
  });
  it("requires a valid manual code and announces an explicit denial", async () => {
    show();
    fireEvent.change(screen.getByLabelText("Code from your CLI"), { target: { value: "IO01-ABCD" } });
    fireEvent.click(screen.getByRole("button", { name: "Check code" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("eight-character code");
    expect(cliAuthApi.request).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText("Code from your CLI"), { target: { value: "ABCD-EFGH" } });
    fireEvent.click(screen.getByRole("button", { name: "Check code" }));
    vi.mocked(cliAuthApi.decision).mockResolvedValue({ state: "denied" });
    fireEvent.click(await screen.findByRole("button", { name: "Deny access" }));
    expect(await screen.findByRole("status")).toHaveTextContent("Access denied");
    expect(retainedCode()).toBeNull();
  });
  it("expires while the approval screen is open and erases the retained code", async () => {
    vi.mocked(cliAuthApi.request).mockResolvedValue({ ...request, expires_at: new Date(Date.now() + 1000).toISOString() });
    captureCode("#user_code=ABCD-EFGH"); show();
    await screen.findByRole("button", { name: "Approve access" });
    expect(await screen.findByRole("status", {}, { timeout: 2000 })).toHaveTextContent("expired");
    expect(retainedCode()).toBeNull();
  });
  it("cancels an in-flight lookup and ignores its late response", async () => {
    let finish: ((value: typeof request) => void) | undefined;
    vi.mocked(cliAuthApi.request).mockImplementation(() => new Promise(resolve => { finish = resolve; }));
    captureCode("#user_code=ABCD-EFGH"); show();
    await waitFor(() => expect(cliAuthApi.request).toHaveBeenCalled());
    const signal = vi.mocked(cliAuthApi.request).mock.calls[0][1];
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(signal.aborted).toBe(true);
    await act(async () => finish?.(request));
    expect(screen.getByRole("status")).toHaveTextContent("cancelled");
    expect(screen.queryByRole("button", { name: "Approve access" })).not.toBeInTheDocument();
  });
  it("keeps malformed decision metadata uncertain and preserves the code", async () => {
    vi.mocked(cliAuthApi.decision).mockResolvedValue({ state: "unexpected" } as unknown as Awaited<ReturnType<typeof cliAuthApi.decision>>);
    captureCode("#user_code=ABCD-EFGH"); show();
    fireEvent.click(await screen.findByRole("button", { name: "Approve access" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("could not confirm");
    expect(retainedCode()?.userCode).toBe("ABCD-EFGH");
  });
  it("treats cancellation during a decision as uncertain and allows a fresh lookup", async () => {
    let finish: ((value: { state: "approved" }) => void) | undefined;
    vi.mocked(cliAuthApi.decision).mockImplementation(() => new Promise(resolve => { finish = resolve; }));
    captureCode("#user_code=ABCD-EFGH"); show();
    fireEvent.click(await screen.findByRole("button", { name: "Approve access" }));
    await waitFor(() => expect(cliAuthApi.decision).toHaveBeenCalled());
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.getByRole("alert")).toHaveTextContent("could not confirm your decision");
    expect(retainedCode()?.userCode).toBe("ABCD-EFGH");
    expect(vi.mocked(cliAuthApi.decision).mock.calls[0][2].aborted).toBe(true);
    await act(async () => finish?.({ state: "approved" }));
    expect(screen.queryByText(/Access approved/)).not.toBeInTheDocument();
    vi.mocked(cliAuthApi.request).mockResolvedValue({ ...request, state: "approved" });
    fireEvent.click(screen.getByRole("button", { name: "Check code again" }));
    expect(await screen.findByRole("status")).toHaveTextContent("already approved");
    expect(cliAuthApi.decision).toHaveBeenCalledTimes(1);
  });
});
