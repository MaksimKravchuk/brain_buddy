import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { apiClient, ApiError } from "../../../api/client";
import { useTaskTitleAutocomplete } from "../useTaskTitleAutocomplete";

vi.mock("../../../api/client", async () => {
  const actual = await vi.importActual<typeof import("../../../api/client")>("../../../api/client");
  return {
    ...actual,
    apiClient: {
      ...actual.apiClient,
      getTitleCompletionProvider: vi.fn(),
      generateTitleCompletions: vi.fn(),
      recordTitleCompletionAccepted: vi.fn()
    }
  };
});

const mocked = vi.mocked(apiClient, true);

describe("useTaskTitleAutocomplete", () => {
  // 012-FR-003, 012-FR-007 and 012-FR-010: consent, debounce,
  // cancellation, stale-result suppression and safe unavailable behavior.
  beforeEach(() => {
    vi.useFakeTimers();
    mocked.getTitleCompletionProvider.mockResolvedValue({ provider: "deterministic" });
    mocked.generateTitleCompletions.mockResolvedValue({
      request_id: "8f3d2f73-0e55-4f47-9f9b-1a0b6c7a9c6e",
      candidates: ["prepare launch notes today", "prepare launch notes this week", "prepare launch notes tomorrow"]
    });
    mocked.recordTitleCompletionAccepted.mockResolvedValue(undefined);
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.clearAllMocks();
  });

  it("waits exactly 350 ms and requires provider-specific consent", async () => {
    const { result } = renderHook(() =>
      useTaskTitleAutocomplete({ enabled: true, draft: "prepare launch notes", projectId: null, smartAddActive: false })
    );
    await act(async () => Promise.resolve());
    expect(result.current.provider).toBe("deterministic");
    expect(mocked.generateTitleCompletions).not.toHaveBeenCalled();

    act(() => result.current.setConsent(true));
    await act(async () => vi.advanceTimersByTimeAsync(349));
    expect(mocked.generateTitleCompletions).not.toHaveBeenCalled();
    await act(async () => vi.advanceTimersByTimeAsync(1));
    await act(async () => Promise.resolve());
    expect(result.current.candidates).toHaveLength(3);
  });

  it("aborts the active request on unmount and ignores acceptance failure", async () => {
    let signal: AbortSignal | undefined;
    mocked.generateTitleCompletions.mockImplementation((_payload, requestSignal) => {
      signal = requestSignal;
      return new Promise(() => undefined);
    });
    const { result, unmount } = renderHook(() =>
      useTaskTitleAutocomplete({ enabled: true, draft: "prepare launch notes", projectId: null, smartAddActive: false })
    );
    await act(async () => Promise.resolve());
    act(() => result.current.setConsent(true));
    await act(async () => vi.advanceTimersByTimeAsync(350));
    expect(signal?.aborted).toBe(false);
    unmount();
    expect(signal?.aborted).toBe(true);

    mocked.recordTitleCompletionAccepted.mockRejectedValueOnce(new Error("offline"));
    await expect(
      result.current.recordAcceptance("8f3d2f73-0e55-4f47-9f9b-1a0b6c7a9c6e", 1)
    ).resolves.toBeUndefined();
  });

  it("keeps capture usable and reports unavailable when discovery has no provider", async () => {
    mocked.getTitleCompletionProvider.mockResolvedValueOnce({ provider: null });
    const { result } = renderHook(() =>
      useTaskTitleAutocomplete({ enabled: true, draft: "prepare launch notes", projectId: null, smartAddActive: false })
    );

    await act(async () => Promise.resolve());

    expect(result.current.provider).toBeNull();
    expect(result.current.consent).toBe(false);
    expect(result.current.error).toBe("Suggestions unavailable.");
    expect(mocked.generateTitleCompletions).not.toHaveBeenCalled();
  });

  it("does not discover or generate while the feature flag is disabled", async () => {
    const { result } = renderHook(() =>
      useTaskTitleAutocomplete({ enabled: false, draft: "prepare launch notes", projectId: null, smartAddActive: false })
    );

    await act(async () => Promise.resolve());

    expect(result.current.provider).toBeNull();
    expect(result.current.error).toBeNull();
    expect(mocked.getTitleCompletionProvider).not.toHaveBeenCalled();
    expect(mocked.generateTitleCompletions).not.toHaveBeenCalled();
  });

  it("reports discovery failure without exposing consent", async () => {
    mocked.getTitleCompletionProvider.mockRejectedValueOnce(new Error("offline"));
    const { result } = renderHook(() =>
      useTaskTitleAutocomplete({ enabled: true, draft: "prepare launch notes", projectId: null, smartAddActive: false })
    );

    await act(async () => Promise.resolve());

    expect(result.current.provider).toBeNull();
    expect(result.current.consent).toBe(false);
    expect(result.current.error).toBe("Suggestions unavailable.");
  });

  it("preserves the correlation reference from provider discovery failure", async () => {
    mocked.getTitleCompletionProvider.mockRejectedValueOnce(
      new ApiError("unavailable", 503, {}, "discovery-reference")
    );
    const { result } = renderHook(() =>
      useTaskTitleAutocomplete({ enabled: true, draft: "prepare launch notes", projectId: null, smartAddActive: false })
    );

    await act(async () => Promise.resolve());

    expect(result.current.provider).toBeNull();
    expect(result.current.consent).toBe(false);
    expect(result.current.error).toBe("Suggestions unavailable. Reference discovery-reference.");
  });

  it("surfaces a content-free correlation reference for generation failure", async () => {
    mocked.generateTitleCompletions.mockRejectedValueOnce(
      new ApiError("unavailable", 503, {}, "safe-reference")
    );
    const { result } = renderHook(() =>
      useTaskTitleAutocomplete({ enabled: true, draft: "prepare launch notes", projectId: null, smartAddActive: false })
    );
    await act(async () => Promise.resolve());
    act(() => result.current.setConsent(true));

    await act(async () => vi.advanceTimersByTimeAsync(350));

    expect(result.current.error).toBe("Suggestions unavailable. Reference safe-reference.");
    expect(result.current.loading).toBe(false);
    expect(result.current.candidates).toEqual([]);
  });

  it("cancels candidates when consent is withdrawn", async () => {
    const { result } = renderHook(() =>
      useTaskTitleAutocomplete({ enabled: true, draft: "prepare launch notes", projectId: null, smartAddActive: false })
    );
    await act(async () => Promise.resolve());
    act(() => result.current.setConsent(true));
    await act(async () => vi.advanceTimersByTimeAsync(350));
    expect(result.current.candidates).toHaveLength(3);

    act(() => result.current.setConsent(false));

    expect(result.current.consent).toBe(false);
    expect(result.current.candidates).toEqual([]);
    expect(result.current.requestId).toBeNull();
  });

  it("never generates while Smart Add owns the composer", async () => {
    const { result } = renderHook(() =>
      useTaskTitleAutocomplete({ enabled: true, draft: "prepare launch notes", projectId: null, smartAddActive: true })
    );
    await act(async () => Promise.resolve());
    act(() => result.current.setConsent(true));

    await act(async () => vi.advanceTimersByTimeAsync(350));

    expect(mocked.generateTitleCompletions).not.toHaveBeenCalled();
  });

  it("uses one-word project context, hides raw errors, and keeps a dismissed draft quiet", async () => {
    mocked.generateTitleCompletions.mockRejectedValueOnce(new Error("provider exploded"));
    const { result } = renderHook(() =>
      useTaskTitleAutocomplete({ enabled: true, draft: "prepare", projectId: "project-1", smartAddActive: false })
    );
    await act(async () => Promise.resolve());
    act(() => result.current.setConsent(true));
    await act(async () => vi.advanceTimersByTimeAsync(350));

    expect(result.current.error).toBe("Suggestions unavailable.");
    expect(result.current.error).not.toContain("provider exploded");
    const callsBeforeDismiss = mocked.generateTitleCompletions.mock.calls.length;
    act(() => result.current.dismiss());
    await act(async () => vi.advanceTimersByTimeAsync(350));
    expect(mocked.generateTitleCompletions).toHaveBeenCalledTimes(callsBeforeDismiss);
  });

  it("resets dismissal after the draft context changes", async () => {
    const { result, rerender } = renderHook(
      ({ draft, projectId }) =>
        useTaskTitleAutocomplete({ enabled: true, draft, projectId, smartAddActive: false }),
      { initialProps: { draft: "prepare launch notes", projectId: null as string | null } }
    );
    await act(async () => Promise.resolve());
    act(() => result.current.setConsent(true));
    await act(async () => vi.advanceTimersByTimeAsync(350));
    act(() => result.current.dismiss());
    mocked.generateTitleCompletions.mockClear();

    rerender({ draft: "prepare revised notes", projectId: null });
    await act(async () => vi.advanceTimersByTimeAsync(350));
    rerender({ draft: "prepare launch notes", projectId: null });
    await act(async () => vi.advanceTimersByTimeAsync(350));

    expect(mocked.generateTitleCompletions).toHaveBeenCalledTimes(2);
    expect(mocked.generateTitleCompletions).toHaveBeenLastCalledWith(
      expect.objectContaining({ draft: "prepare launch notes" }),
      expect.any(AbortSignal)
    );
  });

  it.each(["prepare\nlaunch notes", "p".repeat(501)])(
    "rejects an ineligible draft before generation: %s",
    async (draft) => {
      const { result } = renderHook(() =>
        useTaskTitleAutocomplete({ enabled: true, draft, projectId: null, smartAddActive: false })
      );
      await act(async () => Promise.resolve());
      act(() => result.current.setConsent(true));
      await act(async () => vi.advanceTimersByTimeAsync(350));
      expect(mocked.generateTitleCompletions).not.toHaveBeenCalled();
    }
  );

  it("uses trimmed length for a 500-character project-scoped draft", async () => {
    const draft = ` ${"p".repeat(500)} `;
    const { result } = renderHook(() =>
      useTaskTitleAutocomplete({ enabled: true, draft, projectId: "project-1", smartAddActive: false })
    );
    await act(async () => Promise.resolve());
    act(() => result.current.setConsent(true));

    await act(async () => vi.advanceTimersByTimeAsync(350));

    expect(mocked.generateTitleCompletions).toHaveBeenCalledWith(
      expect.objectContaining({ draft }),
      expect.any(AbortSignal)
    );
  });

  it("ignores a successful response from an aborted earlier draft", async () => {
    let resolveRequest:
      | ((value: { request_id: string; candidates: [string, string, string] }) => void)
      | undefined;
    mocked.generateTitleCompletions.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          resolveRequest = resolve;
        })
    );
    const { result, rerender } = renderHook(
      ({ draft }) =>
        useTaskTitleAutocomplete({ enabled: true, draft, projectId: null, smartAddActive: false }),
      { initialProps: { draft: "prepare launch notes" } }
    );
    await act(async () => Promise.resolve());
    act(() => result.current.setConsent(true));
    await act(async () => vi.advanceTimersByTimeAsync(350));
    rerender({ draft: "prepare revised notes" });
    await act(async () => {
      resolveRequest?.({
        request_id: "stale",
        candidates: ["stale candidate", "stale candidate two", "stale candidate three"]
      });
      await Promise.resolve();
    });
    expect(result.current.candidates).toEqual([]);
    expect(result.current.loading).toBe(false);
  });

  it("ignores a rejected response from an aborted earlier draft", async () => {
    let rejectRequest: ((reason: Error) => void) | undefined;
    mocked.generateTitleCompletions.mockImplementationOnce(
      () =>
        new Promise((_resolve, reject) => {
          rejectRequest = reject;
        })
    );
    const { result, rerender } = renderHook(
      ({ draft }) =>
        useTaskTitleAutocomplete({ enabled: true, draft, projectId: null, smartAddActive: false }),
      { initialProps: { draft: "prepare launch notes" } }
    );
    await act(async () => Promise.resolve());
    act(() => result.current.setConsent(true));
    await act(async () => vi.advanceTimersByTimeAsync(350));
    rerender({ draft: "prepare revised notes" });
    await act(async () => {
      rejectRequest?.(new Error("stale failure"));
      await Promise.resolve();
    });
    expect(result.current.error).toBeNull();
    expect(result.current.loading).toBe(false);
  });

  it("does not update discovery state after unmount", async () => {
    let resolveDiscovery: ((value: { provider: string | null }) => void) | undefined;
    mocked.getTitleCompletionProvider.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          resolveDiscovery = resolve;
        })
    );
    const { unmount } = renderHook(() =>
      useTaskTitleAutocomplete({ enabled: true, draft: "prepare launch notes", projectId: null, smartAddActive: false })
    );
    unmount();
    await act(async () => {
      resolveDiscovery?.({ provider: "deterministic" });
      await Promise.resolve();
    });
    expect(mocked.generateTitleCompletions).not.toHaveBeenCalled();
  });

  it("does not expose discovery rejection after unmount", async () => {
    let rejectDiscovery: ((reason: Error) => void) | undefined;
    mocked.getTitleCompletionProvider.mockImplementationOnce(
      () =>
        new Promise((_resolve, reject) => {
          rejectDiscovery = reject;
        })
    );
    const { unmount } = renderHook(() =>
      useTaskTitleAutocomplete({ enabled: true, draft: "prepare launch notes", projectId: null, smartAddActive: false })
    );
    unmount();
    await act(async () => {
      rejectDiscovery?.(new Error("offline"));
      await Promise.resolve();
    });
    expect(mocked.generateTitleCompletions).not.toHaveBeenCalled();
  });
});
