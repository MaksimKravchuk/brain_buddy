import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../../../api/client";
import { inviteRequired } from "../../../api/invite";
import { modernAuthApi } from "../../../api/modernAuth";
import { useAuthStore } from "../../../stores/authStore";
import { saveProviderAttempt } from "../authFlow";
import { InviteStep } from "../InviteStep";
import { ProviderCompletionPage } from "../ProviderCompletionPage";

vi.mock("../../../api/modernAuth", () => ({ modernAuthApi: { completeProvider: vi.fn(), methods: vi.fn(), verifyEmail: vi.fn() } }));
const user = { id: "N", email: "new@test.example" };
const signedIn = { status: "signed_in", user, deletion_cancelled: false };
const reply = (status: number, body: unknown, headers: Record<string, string> = {}) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json", "X-Correlation-ID": "ref-1", ...headers } });
const fetchMock = vi.fn();
const props = () => ({ pending: "handoff-1", onSignedIn: vi.fn(), onRestart: vi.fn(), onCancel: vi.fn() });
const field = () => screen.getByLabelText("Invite code") as HTMLInputElement;
const submitCode = (code: string) => { fireEvent.change(field(), { target: { value: code } }); fireEvent.click(screen.getByRole("button", { name: "Continue" })); };

beforeEach(() => { fetchMock.mockReset(); vi.stubGlobal("fetch", fetchMock); });
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

describe("027-FR-007 invite step states (D-04 .01-.08)", () => {
  it("027-FR-007 .01 shows the heading, explanation and field, with focus on the field", () => {
    render(<InviteStep {...props()} />);
    expect(screen.getByRole("heading", { name: "Enter your invite code" })).toBeInTheDocument();
    expect(screen.getByText("Brain Buddy is invite-only. No account uses this sign-in yet. Enter your invite code to create one.")).toBeInTheDocument();
    expect(field()).toHaveFocus();
    expect(field()).toHaveAttribute("autocomplete", "off");
    expect(screen.getByRole("button", { name: "Continue" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Cancel" })).toBeInTheDocument();
  });

  it("027-FR-007 .01 Enter submits the pending handoff with the trimmed code, and Cancel abandons it", async () => {
    fetchMock.mockResolvedValue(reply(200, signedIn));
    const p = props(); render(<InviteStep {...p} />);
    fireEvent.change(field(), { target: { value: "  BB-1  " } });
    fireEvent.submit(field().closest("form") as HTMLFormElement);
    await waitFor(() => expect(p.onSignedIn).toHaveBeenCalledWith(signedIn));
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toMatch(/\/auth\/signup\/complete$/);
    expect(JSON.parse(init.body as string)).toEqual({ pending: "handoff-1", invite_code: "BB-1" });
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(p.onCancel).toHaveBeenCalledTimes(1);
  });

  it("027-FR-007 .02 submitting makes the field read-only and shows the spinner only after 300 ms", async () => {
    vi.useFakeTimers();
    let release!: (value: Response) => void;
    fetchMock.mockReturnValue(new Promise<Response>(resolve => { release = resolve; }));
    render(<InviteStep {...props()} />);
    submitCode("BB-1");
    expect(field()).toHaveAttribute("readonly");
    expect(screen.getByRole("button", { name: "Please wait…" })).toBeDisabled();
    await act(async () => { await vi.advanceTimersByTimeAsync(299); });
    expect(screen.queryByRole("status")).toBeNull();
    await act(async () => { await vi.advanceTimersByTimeAsync(1); });
    expect(screen.getByRole("status")).toBeInTheDocument();
    await act(async () => { release(reply(200, signedIn)); });
  });

  it("027-FR-007 .03 invalid and used codes share one message; code kept, focus returns to the field, reference shown", async () => {
    fetchMock.mockResolvedValue(reply(400, { message: "x", detail: { code: "INVITE_INVALID" } }));
    render(<InviteStep {...props()} />);
    submitCode("BB-7Q2K-91XD");
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("That invite code isn't valid or has already been used. Check it and try again. Reference: ref-1");
    expect(field()).toHaveValue("BB-7Q2K-91XD");
    await waitFor(() => expect(field()).toHaveFocus());
    expect(field()).toHaveAttribute("aria-invalid", "true");
    expect(field().getAttribute("aria-describedby")).toContain(alert.id);
  });

  it("027-FR-007 .04 an expired handoff hides the field and moves focus to Back to sign in", async () => {
    fetchMock.mockResolvedValue(reply(410, { detail: { code: "SIGNUP_EXPIRED" } }));
    const p = props(); render(<InviteStep {...p} />);
    submitCode("BB-1");
    expect(await screen.findByText("This sign-in has expired. Start again to create your account.")).toBeInTheDocument();
    expect(screen.queryByLabelText("Invite code")).toBeNull();
    expect(screen.queryByRole("button", { name: "Continue" })).toBeNull();
    const back = screen.getByRole("button", { name: "Back to sign in" });
    await waitFor(() => expect(back).toHaveFocus());
    fireEvent.click(back);
    expect(p.onRestart).toHaveBeenCalledTimes(1);
  });

  it("027-FR-007 .05 offline keeps the code, allows another attempt, and a later expiry shows .04", async () => {
    fetchMock.mockRejectedValueOnce(new TypeError("offline")).mockResolvedValueOnce(reply(410, {}));
    render(<InviteStep {...props()} />);
    submitCode("BB-1");
    expect(await screen.findByRole("alert")).toHaveTextContent("Couldn't reach Brain Buddy");
    expect(field()).toHaveValue("BB-1");
    await waitFor(() => expect(screen.getByRole("button", { name: "Continue" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    expect(await screen.findByRole("button", { name: "Back to sign in" })).toBeInTheDocument();
  });

  it("027-FR-007 .06 an existing account never reaches the step: a normal completion signs in", () => {
    expect(inviteRequired(new ApiError("x", 403, { message: "forbidden" }))).toBeNull();
    expect(inviteRequired(new ApiError("x", 403, { detail: { code: "INVITE_REQUIRED" } }))).toBeNull();
    expect(inviteRequired(new ApiError("x", 403, { detail: { code: "INVITE_REQUIRED", pending: "p", expires_in: 600 } }))).toEqual({ pending: "p", expiresIn: 600 });
  });

  it("027-FR-007 .07 too many attempts shows the inline error and disables Continue until Retry-After passes", async () => {
    vi.useFakeTimers();
    fetchMock.mockResolvedValue(reply(429, {}, { "Retry-After": "30" }));
    render(<InviteStep {...props()} />);
    submitCode("BB-1");
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    expect(screen.getByRole("alert")).toHaveTextContent("Too many requests. Try again in a few minutes.");
    expect(screen.getByRole("button", { name: "Continue" })).toBeDisabled();
    await act(async () => { await vi.advanceTimersByTimeAsync(30_000); });
    expect(screen.getByRole("button", { name: "Continue" })).toBeEnabled();
  });

  it("027-FR-007 .08 a 426 shows the server update message with its reference and keeps the code", async () => {
    fetchMock.mockResolvedValue(reply(426, { message: "Brain Buddy has been updated. Reload this page to continue. Nothing in your account was changed.", detail: { code: "UPGRADE_REQUIRED" } }));
    render(<InviteStep {...props()} />);
    submitCode("BB-1");
    expect(await screen.findByRole("alert")).toHaveTextContent("Brain Buddy has been updated. Reload this page to continue. Nothing in your account was changed. Reference: ref-1");
    expect(field()).toHaveValue("BB-1");
  });
});

describe("027-FR-007 INVITE_REQUIRED completion on the provider page", () => {
  const token = "a".repeat(43);
  beforeEach(() => {
    vi.mocked(modernAuthApi.completeProvider).mockReset();
    sessionStorage.clear();
    useAuthStore.setState({ user: null, status: "anon", hydrate: vi.fn(async () => { useAuthStore.setState({ user, status: "authed" }); }) });
    saveProviderAttempt({ attemptId: token, state: token, verifier: "v".repeat(43), purpose: "login", destination: "/", expiresAt: Date.now() + 60000 });
    history.replaceState(null, "", `/auth/complete#attempt=${token}&state=${token}&grant=${token}`);
  });
  afterEach(() => history.replaceState(null, "", "/"));
  const show = () => render(<MemoryRouter initialEntries={["/auth/complete"]}><Routes><Route path="/auth/complete" element={<ProviderCompletionPage />} /><Route path="/" element={<div>Workspace</div>} /><Route path="/login" element={<div>Sign in page</div>} /></Routes></MemoryRouter>);
  const required = () => new ApiError("x", 403, { message: "An invite code is required to create an account.", detail: { code: "INVITE_REQUIRED", pending: "handoff-9", expires_in: 600 } });

  it("027-FR-007 shows the step, creates the account with the code, and lands in the workspace", async () => {
    vi.mocked(modernAuthApi.completeProvider).mockRejectedValue(required());
    fetchMock.mockResolvedValue(reply(200, signedIn));
    show();
    expect(await screen.findByRole("heading", { name: "Enter your invite code" })).toBeInTheDocument();
    expect(field()).toHaveFocus();
    submitCode("BB-1");
    expect(await screen.findByText("Workspace")).toBeInTheDocument();
    expect(JSON.parse((fetchMock.mock.calls[0] as [string, RequestInit])[1].body as string)).toEqual({ pending: "handoff-9", invite_code: "BB-1" });
    expect(modernAuthApi.completeProvider).toHaveBeenCalledTimes(1);
  });

  it("027-FR-007 Cancel returns to sign-in without creating anything", async () => {
    vi.mocked(modernAuthApi.completeProvider).mockRejectedValue(required());
    show();
    fireEvent.click(await screen.findByRole("button", { name: "Cancel" }));
    expect(await screen.findByText("Sign in page")).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("027-FR-007 any other completion failure keeps the existing generic message", async () => {
    vi.mocked(modernAuthApi.completeProvider).mockRejectedValue(new ApiError("x", 403, { message: "forbidden" }));
    show();
    expect(await screen.findByRole("alert")).toHaveTextContent(/couldn't confirm whether this finished/i);
    expect(screen.queryByLabelText("Invite code")).toBeNull();
  });
});
