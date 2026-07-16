import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { VerticalZoneBezierEdge } from "../VerticalZoneBezierEdge";
import type { EdgeProps } from "reactflow";
import { Position } from "reactflow";

vi.mock("reactflow", () => ({
  BaseEdge: ({ path }: { path: string }) => <div data-testid="base-edge" data-path={path} />,
  Position: { Top: "top", Bottom: "bottom", Left: "left", Right: "right" }
}));

function makeProps(overrides: Partial<EdgeProps> = {}): EdgeProps {
  return {
    id: "edge-1",
    source: "node-1",
    target: "node-2",
    sourceX: 100,
    sourceY: 200,
    targetX: 300,
    targetY: 400,
    sourcePosition: Position.Bottom,
    targetPosition: Position.Top,
    markerEnd: "arrow",
    style: { stroke: "#000" },
    ...overrides
  } as EdgeProps;
}

describe("VerticalZoneBezierEdge branch coverage", () => {
  it("computes path for bottom-to-top direction", () => {
    const { container } = render(<VerticalZoneBezierEdge {...makeProps()} />);
    const edge = container.querySelector('[data-testid="base-edge"]');
    expect(edge).toBeTruthy();
    const path = edge?.getAttribute("data-path") ?? "";
    // sourceDir for Bottom = 1, targetDir for Top = -1
    expect(path).toContain("M 100 200");
    expect(path).toContain("320"); // sourceY + 120 (1 * 120)
    expect(path).toContain("280"); // targetY - 120 (-1 * 120)
  });

  it("computes path for top-to-bottom direction", () => {
    const { container } = render(
      <VerticalZoneBezierEdge
        {...makeProps({ sourcePosition: Position.Top, targetPosition: Position.Bottom })}
      />
    );
    const edge = container.querySelector('[data-testid="base-edge"]');
    const path = edge?.getAttribute("data-path") ?? "";
    // sourceDir for Top = -1, targetDir for Bottom = 1
    expect(path).toContain("80"); // sourceY - 120
    expect(path).toContain("520"); // targetY + 120
  });

  it("uses zero direction for non-top/bottom positions", () => {
    const { container } = render(
      <VerticalZoneBezierEdge
        {...makeProps({ sourcePosition: Position.Left, targetPosition: Position.Right })}
      />
    );
    const edge = container.querySelector('[data-testid="base-edge"]');
    const path = edge?.getAttribute("data-path") ?? "";
    // sourceDir = 0, targetDir = 0 — no offset applied
    expect(path).toContain("C 100 200 300 400");
  });
});
