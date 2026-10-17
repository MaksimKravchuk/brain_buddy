# M04 Landing Tip evidence

The before image is the supplied native app capture `M04-current-native.png`. It shows the tip in a separate white outlined card with a secondary pill on the next line.

The after images are native SwiftUI `ImageRenderer` snapshots of the shipped `LandingTip` tip row at 1030 pt, rendered at 2x in light and dark appearance. They show the unchanged copy in a single control-quiet stone row with a plain trailing “Got it” action. The upper step card is intentionally outside these focused snapshots.

The corresponding assertions are `FirstRunLandingTipSnapshotTests` and compare both appearances pixel by pixel against the approved PNGs beside the test source.
