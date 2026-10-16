import BrainBuddyMacCore
import SwiftUI

/// Design S-04: the unchanged sync popover content (021 X-02) at its own width and scroll (028-FR-020).
struct SyncSettingsTab: View {
    let controller: MacSyncController

    var body: some View { SyncStatusPopover(controller: controller).frame(maxWidth: .infinity).padding(.vertical, 22) }
}
