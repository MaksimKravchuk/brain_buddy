import type { ComponentProps } from "react";

import { Overlay, OverlayHeader } from "../../components/ui/Overlay";

/** Brain-dump-flavored wrapper over the shared `Overlay` primitive. */
export function BrainDumpOverlay(
  props: Omit<ComponentProps<typeof Overlay>, "scrimTestId">
): JSX.Element {
  return <Overlay scrimTestId="brain-dump-scrim" {...props} />;
}

/** Header shared by every brain-dump panel: title, optional meta, optional close. */
export function BrainDumpOverlayHeader(
  props: Omit<ComponentProps<typeof OverlayHeader>, "closeLabel">
): JSX.Element {
  return <OverlayHeader closeLabel="Close brain dump" {...props} />;
}
