import { render, screen } from "@testing-library/react-native";

import { DueChip, PriorityDot, TagPill, WaitingChip } from "../Chip";

describe("chips", () => {
  it("renders a due chip label verbatim", async () => {
    await render(<DueChip label="before Sat" />);
    expect(screen.getByText("before Sat")).toBeOnTheScreen();
  });

  it("renders a tag pill name verbatim", async () => {
    await render(<TagPill name="errand" />);
    expect(screen.getByText("errand")).toBeOnTheScreen();
  });

  it("prefixes the waiting chip with the Waiting label", async () => {
    await render(<WaitingChip waitingFor="Dana" />);
    expect(screen.getByText("Waiting · Dana")).toBeOnTheScreen();
  });
});

describe("PriorityDot", () => {
  it.each(["high", "medium", "low"] as const)("renders a dot for %s priority", async (priority) => {
    const { toJSON } = await render(<PriorityDot priority={priority} />);
    expect(toJSON()).not.toBeNull();
  });

  it.each(["none", "", "unknown"])("renders nothing for %p", async (priority) => {
    const { toJSON } = await render(<PriorityDot priority={priority} />);
    expect(toJSON()).toBeNull();
  });
});
