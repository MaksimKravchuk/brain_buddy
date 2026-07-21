import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, waitFor } from "@testing-library/react-native";
import type { ReactNode } from "react";

import { MobileApiError } from "@/api/client";
import type { Task } from "@/api/types";
import { mobileAllure, withAllure } from "@/test/allureTaxonomy";
import { TaskDetailScreen } from "../TaskDetailScreen";

const mockRouterBack = jest.fn();
jest.mock("expo-router", () => ({
  router: { back: () => mockRouterBack(), push: jest.fn(), replace: jest.fn() },
}));

const mockUseAuth = jest.fn();
jest.mock("@/auth/AuthProvider", () => ({
  useAuth: () => mockUseAuth(),
}));

function makeTask(overrides: Partial<Task> = {}): Task {
  return {
    id: "t1",
    title: "Call the plumber",
    state: "next",
    priority: "none",
    order_key: 0,
    created_at: "2026-07-20T00:00:00Z",
    updated_at: "2026-07-20T00:00:00Z",
    revision: 1,
    ...overrides,
  };
}

// react-query's notifyManager batches mutation-status notifications one
// macrotask past onSuccess/onError. Flush it inside act() so it never lands
// as an update outside of act() after a test's own assertions return.
async function flushMutationNotify() {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

async function renderScreen(api: Record<string, unknown>) {
  mockUseAuth.mockReturnValue({ api, signOut: jest.fn() });
  const client = new QueryClient({
    defaultOptions: { queries: { gcTime: 0, retry: false }, mutations: { gcTime: 0, retry: false } },
  });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return render(<TaskDetailScreen taskId="t1" />, { wrapper });
}

describe("TaskDetailScreen complete-task command identity and recovery", () => {
  beforeEach(() => {
    mockRouterBack.mockReset();
  });

  it(
    mobileAllure.tasks("completing a task sends one idempotent command and navigates back").title,
    async () => {
      await withAllure(
        mobileAllure.tasks("completing a task sends one idempotent command and navigates back"),
        async () => {
          const task = makeTask();
          const transition = jest.fn().mockResolvedValueOnce({ ...task, state: "completed" });
          const api = { task: jest.fn().mockResolvedValue(task), transition };
          const screen = await renderScreen(api);

          await waitFor(() => expect(screen.getByText("Call the plumber")).toBeTruthy());
          await fireEvent.press(screen.getByText("Complete task"));

          await waitFor(() => expect(mockRouterBack).toHaveBeenCalledTimes(1));
          await flushMutationNotify();
          expect(transition).toHaveBeenCalledTimes(1);
          expect(transition).toHaveBeenCalledWith(
            "t1",
            { action: "complete", expected_revision: 1 },
            expect.any(String),
          );
        },
      );
    },
  );

  it(
    mobileAllure.tasks("a failed completion shows a recoverable error and retries with the same command key").title,
    async () => {
      await withAllure(
        mobileAllure.tasks("a failed completion shows a recoverable error and retries with the same command key"),
        async () => {
          const task = makeTask();
          const transition = jest.fn()
            .mockRejectedValueOnce(new MobileApiError(500, "corr-1", true))
            .mockResolvedValueOnce({ ...task, state: "completed" });
          const api = { task: jest.fn().mockResolvedValue(task), transition };
          const screen = await renderScreen(api);

          await waitFor(() => expect(screen.getByText("Call the plumber")).toBeTruthy());
          await fireEvent.press(screen.getByText("Complete task"));

          await waitFor(() => expect(screen.getByText("Complete failed.")).toBeTruthy());
          await fireEvent.press(screen.getByLabelText("Retry complete task"));

          await waitFor(() => expect(transition).toHaveBeenCalledTimes(2));
          await flushMutationNotify();
          const [, , firstKey] = transition.mock.calls[0];
          const [, , secondKey] = transition.mock.calls[1];
          expect(secondKey).toBe(firstKey);
          expect(typeof firstKey).toBe("string");
        },
      );
    },
  );

  it(
    mobileAllure.tasks("a stale revision conflict refreshes the task instead of silently retrying").title,
    async () => {
      await withAllure(
        mobileAllure.tasks("a stale revision conflict refreshes the task instead of silently retrying"),
        async () => {
          const staleTask = makeTask({ revision: 1 });
          const freshTask = makeTask({ revision: 2 });
          const taskFetch = jest.fn()
            .mockResolvedValueOnce(staleTask)
            .mockResolvedValueOnce(freshTask);
          const transition = jest.fn().mockRejectedValueOnce(new MobileApiError(409, "corr-2", false));
          const api = { task: taskFetch, transition };
          const screen = await renderScreen(api);

          await waitFor(() => expect(screen.getByText("Revision: 1")).toBeTruthy());
          await fireEvent.press(screen.getByText("Complete task"));

          await waitFor(() =>
            expect(screen.getByText("This task changed elsewhere. Refreshed — try again.")).toBeTruthy(),
          );
          await waitFor(() => expect(taskFetch).toHaveBeenCalledTimes(2));
          await waitFor(() => expect(screen.getByText("Revision: 2")).toBeTruthy());

          await fireEvent.press(screen.getByLabelText("Retry complete task"));
          await waitFor(() => expect(transition).toHaveBeenCalledTimes(2));
          await flushMutationNotify();
          const [, secondBody] = transition.mock.calls[1];
          expect(secondBody).toEqual({ action: "complete", expected_revision: 2 });
        },
      );
    },
  );
});
