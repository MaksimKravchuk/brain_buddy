import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, waitFor } from "@testing-library/react-native";
import type { ReactNode } from "react";

import { TaskListScreen } from "../TaskListScreen";
import type { Task, TaskList } from "@/api/types";
import { mobileAllure, withAllure } from "@/test/allureTaxonomy";

jest.mock("expo-router", () => ({
  router: { back: jest.fn(), push: jest.fn(), replace: jest.fn() },
}));

const mockUseAuth = jest.fn();
jest.mock("@/auth/AuthProvider", () => ({
  useAuth: () => mockUseAuth(),
}));

const counts = { inbox: 0, next: 0, waiting: 0, someday: 0 };

function makeTask(id: string, overrides: Partial<Task> = {}): Task {
  return {
    id,
    title: `Task ${id}`,
    state: "next",
    priority: "none",
    order_key: 0,
    created_at: "2026-07-20T00:00:00Z",
    updated_at: "2026-07-20T00:00:00Z",
    revision: 1,
    ...overrides,
  };
}

async function renderScreen(state: "inbox" | "next" | "waiting" | "someday", api: Record<string, unknown>) {
  mockUseAuth.mockReturnValue({ api, signOut: jest.fn() });
  const client = new QueryClient({ defaultOptions: { queries: { gcTime: 0, retry: false } } });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return render(<TaskListScreen state={state} />, { wrapper });
}

describe("TaskListScreen quick capture", () => {
  it(
    mobileAllure.tasks("capture from Waiting sends a plain Inbox task with no lifecycle metadata").title,
    async () => {
      await withAllure(
        mobileAllure.tasks("capture from Waiting sends a plain Inbox task with no lifecycle metadata"),
        async () => {
          const emptyPage: TaskList = { items: [], next_cursor: null, has_more: false, counts_by_state: counts };
          const createTask = jest.fn().mockResolvedValue(makeTask("t1", { state: "inbox" }));
          const api = { tasks: jest.fn().mockResolvedValue(emptyPage), createTask };
          const screen = await renderScreen("waiting", api);

          await fireEvent.changeText(screen.getByLabelText("Capture a task"), "Call the plumber");
          await waitFor(() => expect(screen.getByLabelText("Capture a task").props.value).toBe("Call the plumber"));
          await fireEvent.press(screen.getByLabelText("Add task"));

          await waitFor(() => expect(createTask).toHaveBeenCalledTimes(1));
          expect(createTask).toHaveBeenCalledWith({ title: "Call the plumber", state: "inbox" });
        },
      );
    },
  );
});

describe("TaskListScreen pagination", () => {
  it(
    mobileAllure.tasks("continuation requests page 2 with the returned cursor and appends without duplicate ids").title,
    async () => {
      await withAllure(
        mobileAllure.tasks("continuation requests page 2 with the returned cursor and appends without duplicate ids"),
        async () => {
          const pageOne: TaskList = {
            items: [makeTask("t1"), makeTask("t2")],
            next_cursor: "cursor-2",
            has_more: true,
            counts_by_state: counts,
          };
          const pageTwo: TaskList = {
            items: [makeTask("t2"), makeTask("t3")],
            next_cursor: null,
            has_more: false,
            counts_by_state: counts,
          };
          const tasks = jest.fn((_state: string, cursor?: string) => Promise.resolve(cursor ? pageTwo : pageOne));
          const api = { tasks, createTask: jest.fn() };
          const screen = await renderScreen("next", api);

          await waitFor(() => expect(screen.getByText("Task t1")).toBeTruthy());

          const list = screen.getByTestId("task-list");
          await fireEvent(list, "onEndReached");

          await waitFor(() => expect(tasks).toHaveBeenCalledWith("next", "cursor-2"));
          await waitFor(() => expect(screen.getByText("Task t3")).toBeTruthy());

          expect(screen.getAllByText("Task t2")).toHaveLength(1);
        },
      );
    },
  );

  it(
    mobileAllure.tasks("failed continuation remains retryable without discarding the first page").title,
    async () => {
      await withAllure(
        mobileAllure.tasks("failed continuation remains retryable without discarding the first page"),
        async () => {
          const pageOne: TaskList = {
            items: [makeTask("t1")],
            next_cursor: "cursor-2",
            has_more: true,
            counts_by_state: counts,
          };
          const pageTwo: TaskList = {
            items: [makeTask("t2")],
            next_cursor: null,
            has_more: false,
            counts_by_state: counts,
          };
          const tasks = jest.fn()
            .mockResolvedValueOnce(pageOne)
            .mockRejectedValueOnce(new Error("temporary failure"))
            .mockResolvedValueOnce(pageTwo);
          const api = { tasks, createTask: jest.fn() };
          const screen = await renderScreen("next", api);

          await waitFor(() => expect(screen.getByText("Task t1")).toBeTruthy());
          await fireEvent(screen.getByTestId("task-list"), "onEndReached");
          await waitFor(() => expect(screen.getByLabelText("Retry loading more tasks")).toBeTruthy());
          expect(screen.getByText("Task t1")).toBeTruthy();

          await fireEvent.press(screen.getByLabelText("Retry loading more tasks"));
          await waitFor(() => expect(screen.getByText("Task t2")).toBeTruthy());
          expect(tasks).toHaveBeenNthCalledWith(2, "next", "cursor-2");
          expect(tasks).toHaveBeenNthCalledWith(3, "next", "cursor-2");
        },
      );
    },
  );
});
