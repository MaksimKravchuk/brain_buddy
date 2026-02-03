import type { EdgeProps } from "reactflow";
import { BaseEdge, Position } from "reactflow";

// BrainNode height is fixed at 132px (see BrainNode component). We keep a small
// vertical "launch/landing" zone so arrows always leave and enter nodes
// vertically, even when nodes sit at the same y-position.
const NODE_HEIGHT_PX = 132;
const VERTICAL_ZONE_RATIO = 0.2;
const VERTICAL_ZONE_PX = NODE_HEIGHT_PX * VERTICAL_ZONE_RATIO;

export function VerticalZoneBezierEdge(props: EdgeProps): JSX.Element {
  const { sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, markerEnd, style } = props;

  const sourceDir = sourcePosition === Position.Bottom ? 1 : sourcePosition === Position.Top ? -1 : 0;
  const targetDir = targetPosition === Position.Bottom ? 1 : targetPosition === Position.Top ? -1 : 0;

  const path = `M ${sourceX} ${sourceY} C ${sourceX} ${sourceY + sourceDir * VERTICAL_ZONE_PX} ${targetX} ${
    targetY + targetDir * VERTICAL_ZONE_PX
  } ${targetX} ${targetY}`;

  return <BaseEdge path={path} markerEnd={markerEnd} style={style} />;
}
