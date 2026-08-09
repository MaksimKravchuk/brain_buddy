/**
 * The compact list is the cheapest place to mislead someone: a chip is small
 * enough that nobody reads it twice. So the row shows the server's own label
 * verbatim, marks "needs you" as a state the user must act on, dates the last
 * contact, and — for a task nobody handed to an agent — changes nothing at all.
 */

import type { AgentRunSummaryResponse } from "@/api/types";
import { TaskRow } from "@/components/TaskRow";
import { makeTask } from "@/test/agentFixtures";
import { getByLabel, press, queryByText, renderWithProviders, visibleText } from "@/test/render";
import { colors } from "@/theme/tokens";

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
    expect(text).toContain("Draft the launch note");
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
    await press(getByLabel(plain.renderer, "Draft the launch note"));
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
    await press(getByLabel(chipped.renderer, "Draft the launch note"));
    expect(withRun).toHaveBeenCalledTimes(1);
    await chipped.unmount();
  });
});
