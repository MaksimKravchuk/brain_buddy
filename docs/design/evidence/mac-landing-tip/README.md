# M04 Landing Tip evidence

The before image is the supplied native app capture `M04-current-native.png`. It shows the tip in a separate white outlined card with a secondary pill on the next line.

The after images are native SwiftUI `ImageRenderer` snapshots of the shipped `LandingTip` tip row at 1030 pt, rendered at 2x in light and dark appearance. They show the unchanged copy in a single control-quiet stone row with a plain trailing “Got it” action. The upper step card is intentionally outside these focused snapshots.

The corresponding assertions are `FirstRunLandingTipSnapshotTests` and compare both appearances pixel by pixel against the approved PNGs beside the test source.

Parent native replay at product commit `aa86a6a5cde6471553a95c65d69272d4a260a747`: [actual app](m04-after-native.png) shows the quiet horizontal tip with plain trailing Got it. Return dismisses it through the retained default action. No extra click was needed. Baseline main-window chrome and upper card remain excluded.

After dismissal the normal list row showed the original captured title while Quick Open and the inspector showed the rewritten first-step title. This is a separate remaining presentation finding; the tip-only markup does not change task state or queries, and this receipt does not claim full M04 journey acceptance.
