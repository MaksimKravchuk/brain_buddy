import type { EdgeProps } from "reactflow";
import { BaseEdge, Position } from "reactflow";

// BrainNode height is fixed at 132px (see BrainNode component). We keep a small
// vertical "launch/landing" zone so arrows always leave and enter nodes
// vertically, even when nodes sit at the same y-position.
const NODE_HEIGHT_PX = 132;
// Default: 30% of node height, but can be overridden at runtime for quick tuning:
//   window.__BB_VERTICAL_ZONE_PX = 50; // in Chrome console, then jiggle a node to re-render
const VERTICAL_ZONE_RATIO = 0.3;

const getVerticalZonePx = () => {
  const override = (window as { __BB_VERTICAL_ZONE_PX?: unknown } | undefined)?.__BB_VERTICAL_ZONE_PX;
  if (typeof override === "number" && Number.isFinite(override) && override > 0) {
    return override;
  }
  return NODE_HEIGHT_PX * VERTICAL_ZONE_RATIO;
};

export function VerticalZoneBezierEdge(props: EdgeProps): JSX.Element {
  const { sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, markerEnd, style } = props;

  const verticalZonePx = getVerticalZonePx();
  const sourceDir = sourcePosition === Position.Bottom ? 1 : sourcePosition === Position.Top ? -1 : 0;
  const targetDir = targetPosition === Position.Bottom ? 1 : targetPosition === Position.Top ? -1 : 0;

  const path = `M ${sourceX} ${sourceY} C ${sourceX} ${sourceY + sourceDir * verticalZonePx} ${targetX} ${
    targetY + targetDir * verticalZonePx
  } ${targetX} ${targetY}`;

  return <BaseEdge path={path} markerEnd={markerEnd} style={style} />;
}
