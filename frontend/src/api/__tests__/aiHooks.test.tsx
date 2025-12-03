import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, act } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ReactNode } from "react";

import { apiClient, ApiError } from "../client";
import { useAiFeedback } from "../hooks";
import type { AiFeedbackResponse } from "../types";
import { useUiStore } from "../../stores/uiStore";

function createWrapper(queryClient: QueryClient) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
  };
}

describe("ai feedback hook", () => {
  let queryClient: QueryClient;

  beforeEach(() => {
    queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } }
    });
  });

  afterEach(() => {
    queryClient.clear();
    vi.restoreAllMocks();
    useUiStore.getState().clearToasts();
  });

  it("requests AI feedback with consent", async () => {
    const response: AiFeedbackResponse = {
      status: "success",
      summary: "Tree summary",
      recommendations: ["Do something"],
      request_id: "req-1"
    };
    const spy = vi.spyOn(apiClient, "aiFeedback").mockResolvedValue(response);

    const { result } = renderHook(() => useAiFeedback("tree-1"), { wrapper: createWrapper(queryClient) });

    let data: AiFeedbackResponse | undefined;
    await act(async () => {
      data = await result.current.mutateAsync({ consent: true });
    });

    expect(spy).toHaveBeenCalledWith("tree-1", { consent: true });
    expect(data).toEqual(response);
  });

  it("surfaces errors via toast", async () => {
    const error = new ApiError("boom", 500, { detail: "provider down" }, "corr-123");
    vi.spyOn(apiClient, "aiFeedback").mockRejectedValue(error);

    const { result } = renderHook(() => useAiFeedback("tree-err"), { wrapper: createWrapper(queryClient) });

    await act(async () => {
      await expect(result.current.mutateAsync({ consent: true })).rejects.toThrow("boom");
    });

    const toast = useUiStore.getState().toasts.find((item) => item.title === "AI feedback failed");
    expect(toast?.description).toContain("provider down");
  });
});
