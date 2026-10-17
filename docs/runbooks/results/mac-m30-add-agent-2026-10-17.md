# M30 Add agent board correction — 2026-10-17

## Accepted outcome

Match the authoritative [M30 Mac board](../../design/board/mac/M30-Mac.png) on the existing Add new agent surface. This bounded SHOW correction uses existing design colors, type, radii and buttons. Its measured 420 pt width, 22 pt padding and local control geometry live in one generated `layout.mac-agent-add` token group. Other operations and unrelated sheets retain their appearance.

The initial form now has white fields, a stone credential selector with a white selected segment, an ink Add and test action, and a warm native regular-material surface over the existing `bg-ground` role. The local selector retains accessible names, selected traits, visible focus and arrow-key operation.

The screenshot's absent initial Current password field is resolved with a separate proof stage. The first Add and test action opens that stage without a create request. Confirmation retains the existing required server password, API, editor submission, cancellation and secret-wiping behavior. A rejected request clears both secrets and returns to the agent form, retaining name, address, credential type and error. A retry requires fresh secret entry and proof confirmation. Passwordless and unavailable accounts cannot advance.

## Before / after evidence

- Before: `/private/tmp/bb-mac-board-521/M30-before.png` — white sheet, stone fields, native blue credential selection and terracotta action.
- Initial form after: `/private/tmp/bb-mac-board-521/M30-after.png` — corrected geometry, fields, selector, action and absence of the initial password field. This capture predates the final native-material refinement.
- Final material and proof focus: `/private/tmp/bb-mac-board-521/M30-password-proof-focused.png` — accepted warm material, focused Current password and successful typing without clicking the field. The active/key native sheet's content-free diagnostic sequence ends with Password focus and `NSSecureTextView` first responder. All diagnostic code was removed before final checks.
- Final initial/proof appearances: six reviewed real-host `mac-agent-add-{empty,filled,confirmation}-{light,dark}-native2x.png` baselines under `macos/Tests/BrainBuddyMacTests/__Snapshots__/`.

Native manual checks confirmed that Tab from Address reaches credential selection; Right/Left selects API key/Bearer token with matching accessibility selected state. Add and test opens proof, and Escape closes to the manager. Proof focus is requested on the next main queue after SwiftUI inserts the new secure field and resizes the sheet; no timer or duplicate native text field was added.

## Checks

| Check | Result | Local log |
| --- | --- | --- |
| Focused snapshots and sheet workflow replay | PASS — 10 tests / 2 suites | `/private/tmp/bb-m30-final-material-replay.log` |
| Complete native Mac suite after material/focus cleanup | PASS — 460 tests / 48 suites, 35.839 seconds | `/private/tmp/bb-m30-final-focus-mac.log` |
| Complete native kit suite | PASS — 1508 tests / 154 suites; kit source unchanged since this run | `/private/tmp/bb-m30-kit-final.log` |
| Generated tokens, spec integrity, diff whitespace | PASS | `/private/tmp/bb-m30-final-spec-check.log` |

Focused workflow coverage verifies zero create calls before proof, unchanged password gating, failure secret clearing and form return, safe empty-proof retry, and disabled/passwordless guards. The snapshot record run intentionally emitted six record issues before the reviewed replay passed; tolerances were not weakened. Only the native2x profile was available locally; CI's native1x profile remains a parent-owned exact-candidate gate.

Source was prepared from `bae38ea826ec069778ea0f9558e082e98ec7ff0a` on `codex/mac-add-agent-board`. Checks above ran on the final source before the freeze commit. Independent exact-SHA QA, CI, integration and delivery remain parent-owned; this receipt does not claim those gates have passed. No production, account/auth policy, API, persistence, workflow or paid-provider change was made.

## CI-native1x baseline receipt

CI run `39024550988`, Mac job `117372897005`, ran all 460 tests and reported exactly six missing `native1x` references in the new M30 suite. The complete uploaded `macos-swift-test.log` contains all six begin/end image records; the abbreviated job log does not. The actual emitted images were decoded from that artifact, reviewed in both appearances and imported byte-for-byte. Geometry and controls match the accepted native2x states; native rasterization remains a separate baseline. No product code or comparison tolerance changed. This failed first run is not a pass; the revised exact head still requires CI and renewed independent QA.
