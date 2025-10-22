import { render, screen } from "@testing-library/react";
import { act } from "react";
import { describe, expect, it, beforeEach } from "vitest";

import { useTreeStore } from "../../../stores/treeStore";
import { useUiStore } from "../../../stores/uiStore";
import { InspectorTabs } from "../InspectorTabs";

describe("InspectorTabs", () => {
  beforeEach(() => {
    act(() => {
      useTreeStore.getState().reset();
      useUiStore.setState({ inspectorTab: "node" });
    });
  });

  it("disables node and relation tabs when nothing is selected", async () => {
    await act(async () => {
      render(<InspectorTabs />);
    });

    expect(screen.getByRole("button", { name: /node/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: /relation/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: /versions/i })).toBeEnabled();
  });

  it("enables node tab when a node is selected", async () => {
    act(() => {
      useTreeStore.getState().select({ type: "node", id: "node-1" });
    });

    await act(async () => {
      render(<InspectorTabs />);
    });

    expect(screen.getByRole("button", { name: /node/i })).toBeEnabled();
    expect(screen.getByRole("button", { name: /relation/i })).toBeDisabled();
  });
});
