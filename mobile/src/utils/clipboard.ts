/**
 * Copying text to the system clipboard, in one place.
 *
 * Isolated behind this module for two reasons. React Native's own `Clipboard`
 * export is deprecated and will eventually move to a community package, and
 * when it does this file is the only edit — rather than every surface that
 * offers a copy control. And the surfaces that need it are the ones showing
 * something Brain Buddy deliberately refuses to make tappable: an address an
 * agent reported (M-03-S10). Copying is what the product offers *instead* of
 * opening, so it has to actually copy — a control labelled "Copy link" that
 * quietly did nothing would be exactly the kind of fabricated affordance the
 * relay's honesty rules exist to prevent.
 */

import { Clipboard } from "react-native";

export async function copyToClipboard(value: string): Promise<void> {
  Clipboard.setString(value);
}
