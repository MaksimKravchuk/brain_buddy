import Foundation
import Testing

@testable import BrainBuddyMacCore

/// The launch's stopped state (contracts/mac-app-host.md §1): when the runtime cannot be opened
/// the launch opens nothing. The runtime selection itself is in `MacRustSelectionTests`.
@Suite("Launch")
@MainActor
struct MacLaunchTests {
    @Test("021-FR-020 the import-failed panel's words")
    func importFailedCopy() {
        #expect(LegacyImportFailedCopy.title == "Brain Buddy couldn't finish the update")
        #expect(LegacyImportFailedCopy.message.contains("The file from the previous version was left exactly as it was."))
        #expect(LegacyImportFailedCopy.tryAgain == "Try again" && LegacyImportFailedCopy.tryingAgain == "Trying again…")
    }
}
