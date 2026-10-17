import Testing

@testable import BrainBuddyMac

@Suite("Workspace menu modal protection")
@MainActor
struct WorkspaceMenuCommandsTests {
    enum Collection: CaseIterable { case project, tag }

    @Test("021-FR-009 stale creation commands preserve an unsaved modal draft", arguments: Collection.allCases)
    func staleCreationPreservesDraft(first: Collection) {
        var presented: Collection?
        var name = ""
        var busy = false
        let other: Collection = first == .project ? .tag : .project
        let staleCommand = {
            WorkspaceCommandsAction.beginCollection(other, presented: &presented, name: &name, isBusy: busy)
        }
        WorkspaceCommandsAction.beginCollection(first, presented: &presented, name: &name, isBusy: busy)
        name = "Unsaved board fixture"
        staleCommand()
        #expect(presented == first)
        #expect(name == "Unsaved board fixture")

        presented = nil // The person dismisses the existing sheet.
        busy = true
        staleCommand()
        #expect(presented == nil)
        #expect(name == "Unsaved board fixture")
        busy = false
        staleCommand()
        #expect(presented == other)
        #expect(name.isEmpty)
    }
}
