import { render } from "@testing-library/react";
import { Position } from "reactflow";
import { describe, expect, it, beforeEach } from "vitest";

import { VerticalZoneBezierEdge } from "../VerticalZoneBezierEdge";

const baseProps = {
  id: "edge-1",
  source: "a",
  target: "b",
  sourceX: 10,
  sourceY: 20,
  targetX: 110,
  targetY: 220,
  style: undefined,
  markerEnd: undefined
} as const;

describe("VerticalZoneBezierEdge", () => {
  beforeEach(() => {
    delete (window as { __BB_VERTICAL_ZONE_PX?: unknown }).__BB_VERTICAL_ZONE_PX;
  });

  it("applies default 120px vertical band based on handle sides", () => {
    const { container } = render(
      <svg>
        <VerticalZoneBezierEdge
          {...baseProps}
          sourcePosition={Position.Bottom}
          targetPosition={Position.Top}
        />
      </svg>
    );

    const path = container.querySelector("path");
    expect(path?.getAttribute("d")).toBe("M 10 20 C 10 140 110 100 110 220");
  });

  it("honors runtime override via window.__BB_VERTICAL_ZONE_PX", () => {
    (window as { __BB_VERTICAL_ZONE_PX?: number }).__BB_VERTICAL_ZONE_PX = 60;

    const { container } = render(
      <svg>
        <VerticalZoneBezierEdge
          {...baseProps}
          sourcePosition={Position.Top}
          targetPosition={Position.Bottom}
        />
      </svg>
    );

    const path = container.querySelector("path");
    expect(path?.getAttribute("d")).toBe("M 10 20 C 10 -40 110 280 110 220");
  });
});
