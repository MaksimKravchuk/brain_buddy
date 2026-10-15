import { act, render, renderHook, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "../../../api/client";
import { SPINNER_ONSET_MS, UPDATE_REQUIRED_MESSAGE, useSpinnerOnset } from "../shellToast";
import { UpdateRequiredToast } from "../UpdateRequiredToast";

function reply(status: number, body: unknown, headers: Record<string, string> = {}, json = true): Response {
  return new Response(json ? JSON.stringify(body) : String(body), {
    status,
    headers: { "Content-Type": json ? "application/json" : "text/plain", ...headers }
  });
}

async function send(response: Response): Promise<void> {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response));
  await act(async () => {
    await apiClient.listTasks().catch(() => undefined);
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("027-FR-018 update-required alert toast (D-02)", () => {
  it("027-FR-018 shows a persistent role=alert with the server message and reference on an explicit 426", async () => {
    render(<UpdateRequiredToast />);
    expect(screen.queryByRole("alert")).toBeNull();
    await send(reply(426, { code: "UPGRADE_REQUIRED", message: "Reload now." }, { "X-Correlation-ID": "cid-1" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Reload now. (ref: cid-1)");
    expect(screen.getByRole("button", { name: "Reload" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Dismiss" })).toBeVisible();
    expect(screen.getByRole("alert").contains(document.activeElement)).toBe(false);
  });

  it("027-FR-018 reads the code from detail, the reference from the body, and falls back to the web copy", async () => {
    render(<UpdateRequiredToast />);
    await send(reply(426, { detail: { code: "UPGRADE_REQUIRED" }, reference_id: "body-ref" }));
    expect(screen.getByRole("alert")).toHaveTextContent(`${UPDATE_REQUIRED_MESSAGE} (ref: body-ref)`);
  });

  it("027-FR-018 shows the copy with no reference when none is sent", async () => {
    render(<UpdateRequiredToast />);
    await send(reply(426, { code: "UPGRADE_REQUIRED", reference_id: 7 }));
    expect(screen.getByRole("alert").textContent).toContain(UPDATE_REQUIRED_MESSAGE);
    expect(screen.getByRole("alert").textContent).not.toContain("ref:");
  });

  it.each([
    ["a 5xx", reply(503, { code: "UPGRADE_REQUIRED" })],
    ["a 426 without the code", reply(426, { code: "OTHER", detail: "x" })],
    ["a 426 with an unreadable body", reply(426, "nope", {}, false)],
    ["a 426 with a null body", reply(426, null)],
    ["a 426 with a non-object detail", reply(426, { detail: "UPGRADE_REQUIRED" })],
    ["a 403", reply(403, { code: "UPGRADE_REQUIRED" })]
  ])("027-FR-018 stays hidden for %s", async (_name, response) => {
    render(<UpdateRequiredToast />);
    await send(response);
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("027-FR-018 stays hidden when the network fails", async () => {
    render(<UpdateRequiredToast />);
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("offline")));
    await act(async () => {
      await apiClient.listTasks().catch(() => undefined);
    });
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("027-FR-018 does not auto-dismiss and shows one toast at a time, again after Dismiss", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    render(<UpdateRequiredToast />);
    await send(reply(426, { code: "UPGRADE_REQUIRED", message: "First." }));
    await send(reply(426, { code: "UPGRADE_REQUIRED", message: "Second." }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(60_000);
    });
    expect(screen.getAllByRole("alert")).toHaveLength(1);
    expect(screen.getByRole("alert")).toHaveTextContent("Second.");
    await userEvent.setup({ advanceTimers: vi.advanceTimersByTime }).click(screen.getByRole("button", { name: "Dismiss" }));
    expect(screen.queryByRole("alert")).toBeNull();
    await send(reply(426, { code: "UPGRADE_REQUIRED", message: "Third." }));
    expect(screen.getByRole("alert")).toHaveTextContent("Third.");
  });

  it("027-FR-018 Reload runs the injected reload and, by default, reloads the page", async () => {
    const user = userEvent.setup();
    const onReload = vi.fn();
    const first = render(<UpdateRequiredToast onReload={onReload} />);
    await send(reply(426, { code: "UPGRADE_REQUIRED" }));
    await user.click(screen.getByRole("button", { name: "Reload" }));
    expect(onReload).toHaveBeenCalledTimes(1);
    first.unmount();

    const reload = vi.fn();
    vi.stubGlobal("location", { ...window.location, reload });
    render(<UpdateRequiredToast />);
    await send(reply(426, { code: "UPGRADE_REQUIRED" }));
    await user.click(screen.getByRole("button", { name: "Reload" }));
    expect(reload).toHaveBeenCalledTimes(1);
  });

  it("027-FR-018 Escape dismisses from inside the toast and moves focus to the top bar's first control", async () => {
    const user = userEvent.setup();
    render(
      <>
        <header>
          <button type="button">Menu</button>
        </header>
        <UpdateRequiredToast />
      </>
    );
    await send(reply(426, { code: "UPGRADE_REQUIRED" }));
    await user.tab();
    await user.tab();
    expect(screen.getByRole("button", { name: "Reload" })).toHaveFocus();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.getByRole("button", { name: "Menu" })).toHaveFocus();
  });

  it("027-FR-018 Dismiss with focus outside the toast leaves focus alone and tolerates a missing top bar", async () => {
    const user = userEvent.setup();
    render(<UpdateRequiredToast />);
    await send(reply(426, { code: "UPGRADE_REQUIRED" }));
    await user.tab();
    await user.tab();
    await user.click(screen.getByRole("button", { name: "Dismiss" }));
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("027-FR-018 Escape on the page dismisses, but not from a text field or while a dialog is open", async () => {
    const user = userEvent.setup();
    render(
      <>
        <input aria-label="Title" />
        <UpdateRequiredToast />
      </>
    );
    await send(reply(426, { code: "UPGRADE_REQUIRED" }));
    await user.click(screen.getByLabelText("Title"));
    await user.keyboard("{Escape}");
    expect(screen.getByRole("alert")).toBeVisible();

    const dialog = document.createElement("div");
    dialog.setAttribute("role", "dialog");
    document.body.appendChild(dialog);
    await user.click(document.body);
    await user.keyboard("{Escape}");
    expect(screen.getByRole("alert")).toBeVisible();
    dialog.remove();

    await user.keyboard("a");
    await user.keyboard("{Enter}");
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("027-FR-018 stops listening once unmounted, so a later refusal shows nothing", async () => {
    const view = render(<UpdateRequiredToast />);
    view.unmount();
    await send(reply(426, { code: "UPGRADE_REQUIRED" }));
    expect(screen.queryByRole("alert")).toBeNull();
  });
});

describe("027-FR-018 spinner onset (D-02.02)", () => {
  it("027-FR-018 shows the spinner only after 300 ms of pending and resets when the request ends", () => {
    vi.useFakeTimers();
    const { result, rerender } = renderHook(({ pending }) => useSpinnerOnset(pending), {
      initialProps: { pending: true }
    });
    expect(result.current).toBe(false);
    act(() => void vi.advanceTimersByTime(SPINNER_ONSET_MS - 1));
    expect(result.current).toBe(false);
    act(() => void vi.advanceTimersByTime(1));
    expect(result.current).toBe(true);
    rerender({ pending: false });
    expect(result.current).toBe(false);
    rerender({ pending: true });
    expect(result.current).toBe(false);
  });
});
