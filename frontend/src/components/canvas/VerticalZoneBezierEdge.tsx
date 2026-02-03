import type { EdgeProps } from "reactflow";
import { BaseEdge } from "reactflow";

// BrainNode height is fixed at 132px (see BrainNode component). We keep a small
// vertical "launch/landing" zone so arrows always leave and enter nodes
// vertically, even when nodes sit at the same y-position.
const NODE_HEIGHT_PX = 132;
const VERTICAL_ZONE_RATIO = 0.2;
const VERTICAL_ZONE_PX = NODE_HEIGHT_PX * VERTICAL_ZONE_RATIO;

export function VerticalZoneBezierEdge(props: EdgeProps): JSX.Element {
  const { sourceX, sourceY, targetX, targetY, markerEnd, style, selected } = props;

  const direction = targetY >= sourceY ? 1 : -1;

  const path = `M ${sourceX} ${sourceY} C ${sourceX} ${sourceY + direction * VERTICAL_ZONE_PX} ${targetX} ${
    targetY - direction * VERTICAL_ZONE_PX
  } ${targetX} ${targetY}`;

  return <BaseEdge path={path} markerEnd={markerEnd} style={style} selected={selected} />;
}
