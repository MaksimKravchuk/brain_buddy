import { fireEvent, render, screen } from "@testing-library/react-native";

import type { TaskResponse } from "@/api/types";

import { dueLabel, TaskRow } from "../TaskRow";

function makeTask(overrides: Partial<TaskResponse> = {}): TaskResponse {
  return {
    id: "t1",
    title: "Call the notary",
    state: "next",
    priority: "none",
    details: null,
    due_date: null,
    waiting_for: null,
    project_id: null,
    tag_ids: [],
    revision: 1,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  } as TaskResponse;
}

/** Local date `days` from today, formatted as the API's YYYY-MM-DD. */
function isoDaysFromToday(days: number): string {
  const now = new Date();
  const target = new Date(now.getFullYear(), now.getMonth(), now.getDate() + days);
  const month = String(target.getMonth() + 1).padStart(2, "0");
  const day = String(target.getDate()).padStart(2, "0");
  return `${target.getFullYear()}-${month}-${day}`;
}

describe("dueLabel", () => {
  it("names the days either side of today", () => {
    expect(dueLabel(isoDaysFromToday(0))).toBe("today");
    expect(dueLabel(isoDaysFromToday(1))).toBe("tomorrow");
    expect(dueLabel(isoDaysFromToday(-1))).toBe("yesterday");
  });

  it("calls anything further in the past overdue", () => {
    expect(dueLabel(isoDaysFromToday(-2))).toBe("overdue");
    expect(dueLabel(isoDaysFromToday(-400))).toBe("overdue");
  });

  it("uses a weekday inside the coming week", () => {
    for (const days of [2, 3, 4, 5, 6]) {
      expect(dueLabel(isoDaysFromToday(days))).toMatch(/^before \w+/);
    }
  });

  it("switches to a calendar date from a week out", () => {
    expect(dueLabel(isoDaysFromToday(7))).not.toMatch(/^before /);
    expect(dueLabel(isoDaysFromToday(30))).not.toMatch(/^before /);
  });

  it("echoes an unparseable date rather than inventing one", () => {
    expect(dueLabel("not-a-date")).toBe("not-a-date");
  });
});

describe("TaskRow", () => {
  it("renders the title and opens the task when pressed", async () => {
    const onPress = jest.fn();
    await render(<TaskRow task={makeTask()} onPress={onPress} />);

    await fireEvent.press(screen.getByLabelText("Call the notary"));

    expect(onPress).toHaveBeenCalledTimes(1);
  });

  it("offers Complete on an open task and Reopen on a completed one", async () => {
    await render(<TaskRow task={makeTask()} onToggleComplete={jest.fn()} />);
    expect(screen.getByLabelText("Complete task")).toBeOnTheScreen();

    await render(
      <TaskRow task={makeTask({ state: "completed" })} onToggleComplete={jest.fn()} />,
    );
    expect(screen.getByLabelText("Reopen task")).toBeOnTheScreen();
  });

  it("marks the checkbox checked exactly when the task is completed", async () => {
    await render(<TaskRow task={makeTask({ state: "completed" })} />);
    expect(screen.getByRole("checkbox")).toBeChecked();

    await render(<TaskRow task={makeTask()} />);
    expect(screen.getByRole("checkbox")).not.toBeChecked();
  });

  it("does not toggle while a completion is in flight", async () => {
    const onToggleComplete = jest.fn();
    await render(
      <TaskRow task={makeTask()} onToggleComplete={onToggleComplete} completing />,
    );

    await fireEvent.press(screen.getByLabelText("Complete task"));

    expect(onToggleComplete).not.toHaveBeenCalled();
  });

  it("renders due, tag, waiting and project metadata", async () => {
    await render(
      <TaskRow
        task={makeTask({
          state: "waiting",
          waiting_for: "Dana",
          due_date: isoDaysFromToday(0),
          priority: "high",
        })}
        projectName="Wedding"
        tagNames={["errand", "calls"]}
      />,
    );

    expect(screen.getByText("today")).toBeOnTheScreen();
    expect(screen.getByText("Dana")).toBeOnTheScreen();
    expect(screen.getByText("Wedding")).toBeOnTheScreen();
    expect(screen.getByText("errand")).toBeOnTheScreen();
    expect(screen.getByText("calls")).toBeOnTheScreen();
  });

  it("shows the waiting note only in the waiting state", async () => {
    await render(<TaskRow task={makeTask({ state: "next", waiting_for: "Dana" })} />);

    expect(screen.queryByText("Dana")).toBeNull();
  });

  it("renders nothing but the title when the task has no metadata", async () => {
    await render(<TaskRow task={makeTask()} />);

    expect(screen.getByText("Call the notary")).toBeOnTheScreen();
    expect(screen.queryByText(/today|tomorrow|overdue/)).toBeNull();
  });
});
