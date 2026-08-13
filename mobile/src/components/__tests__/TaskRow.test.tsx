import { fireEvent, render, screen } from "@testing-library/react-native";

import type { AgentRunSummaryResponse, TaskResponse } from "@/api/types";
import { getByLabel, press, queryByText, renderWithProviders, visibleText } from "@/test/render";
import { colors } from "@/theme/tokens";

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

/**
 * The compact list is the cheapest place to mislead someone: a chip is small
 * enough that nobody reads it twice. So the row shows the server's own label
 * verbatim, marks "needs you" as a state the user must act on, dates the last
 * contact, and — for a task nobody handed to an agent — changes nothing at all.
 */


// Lucide ships ESM that jest-expo's transform does not cover, and the icons
// carry no meaning a test can assert — the chip's text and colour role do.
jest.mock("lucide-react-native", () => ({
  Bot: () => null,
  Calendar: () => null,
  Check: () => null,
}));

const NOW = Date.parse("2026-08-09T09:10:00Z");

function makeSummary(overrides: Partial<AgentRunSummaryResponse> = {}): AgentRunSummaryResponse {
  return {
    id: "run_1",
    task_id: "task_1",
    agent_name: "My Claude Code box",
    primary_state_label: "Running",
    needs_user: false,
    stopped_reporting: false,
    last_contact_at: "2026-08-09T09:05:00Z",
    ...overrides,
  };
}

/** The chip's own View — the one carrying the pill background. */
function agentChipStyle(renderer: Parameters<typeof visibleText>[0]) {
  const chip = renderer.root.findAll(
    (node) => {
      const style = node.props?.style;
      if (!Array.isArray(style)) {
        return false;
      }
      return style.some(
        (entry: unknown) =>
          !!entry &&
          typeof entry === "object" &&
          "backgroundColor" in (entry as Record<string, unknown>) &&
          ((entry as Record<string, unknown>).backgroundColor === colors.infoBg ||
            (entry as Record<string, unknown>).backgroundColor === colors.warningBg),
      );
    },
    { deep: true },
  );
  const style = (chip[0]?.props.style ?? []) as (Record<string, unknown> | null)[];
  return Object.assign({}, ...style.filter(Boolean)) as Record<string, unknown>;
}

beforeEach(() => {
  jest.spyOn(Date, "now").mockReturnValue(NOW);
});

afterEach(() => {
  jest.restoreAllMocks();
});

describe("TaskRow agent summary", () => {
  it("names the agent, repeats the server's label, and dates the last contact", async () => {
    const { renderer, unmount } = await renderWithProviders(
      <TaskRow task={makeTask()} agentRun={makeSummary()} />,
    );

    const text = visibleText(renderer);
    expect(text).toContain("My Claude Code box · Running");
    expect(text).toContain("Last contact 5 minutes");

    await unmount();
  });

  it("marks a run that needs the user with the needs-you treatment, not the neutral one", async () => {
    const calm = await renderWithProviders(<TaskRow task={makeTask()} agentRun={makeSummary()} />);
    expect(agentChipStyle(calm.renderer).backgroundColor).toBe(colors.infoBg);
    expect(
      calm.renderer.root.findAll((node) => node.props?.color === colors.warningFg).length,
    ).toBe(0);
    await calm.unmount();

    const needsYou = await renderWithProviders(
      <TaskRow
        task={makeTask()}
        agentRun={makeSummary({ needs_user: true, primary_state_label: "Needs you" })}
      />,
    );

    // Both the pill and its text move to the warning role, so the state is
    // legible without colour alone carrying it — the label says "Needs you".
    expect(agentChipStyle(needsYou.renderer).backgroundColor).toBe(colors.warningBg);
    expect(agentChipStyle(needsYou.renderer).borderColor).toBe(colors.warningBorder);
    expect(
      needsYou.renderer.root.findAll((node) => node.props?.color === colors.warningFg).length,
    ).toBeGreaterThan(0);
    expect(visibleText(needsYou.renderer)).toContain("My Claude Code box · Needs you");

    await needsYou.unmount();
  });

  it("passes a completion claim through as a claim rather than as a fact", async () => {
    const { renderer, unmount } = await renderWithProviders(
      <TaskRow
        task={makeTask()}
        agentRun={makeSummary({
          primary_state_label: "Agent reported complete — Brain Buddy did not verify it",
        })}
      />,
    );

    const text = visibleText(renderer);
    expect(text).toContain("Agent reported complete — Brain Buddy did not verify it");
    // The row never upgrades the claim into the task's own completion.
    expect(text).not.toContain("Completed");

    await unmount();
  });

  it("says nothing about agents on a task that was never handed to one", async () => {
    const { renderer, unmount } = await renderWithProviders(
      <TaskRow task={makeTask({ priority: "none", due_date: null })} />,
    );

    const text = visibleText(renderer);
    expect(text).toContain("Call the notary");
    expect(text).not.toContain("Last contact");
    expect(text).not.toContain("·");
    expect(queryByText(renderer, "Running")).toBeNull();

    await unmount();
  });

  it("still opens the task when pressed, with or without a run chip", async () => {
    const withoutRun = jest.fn();
    const plain = await renderWithProviders(
      <TaskRow task={makeTask()} onPress={withoutRun} />,
    );
    await press(getByLabel(plain.renderer, "Call the notary"));
    expect(withoutRun).toHaveBeenCalledTimes(1);
    await plain.unmount();

    const withRun = jest.fn();
    const chipped = await renderWithProviders(
      <TaskRow
        task={makeTask()}
        agentRun={makeSummary({ needs_user: true, primary_state_label: "Needs you" })}
        onPress={withRun}
      />,
    );
    await press(getByLabel(chipped.renderer, "Call the notary"));
    expect(withRun).toHaveBeenCalledTimes(1);
    await chipped.unmount();
  });
});
