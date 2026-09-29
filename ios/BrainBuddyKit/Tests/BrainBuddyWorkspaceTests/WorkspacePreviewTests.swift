import BrainBuddyCore
import Foundation
import Testing

@testable import BrainBuddyWorkspace

/// `Workspace.preview()`: loaded at once, with something on every screen.
@MainActor
@Suite struct WorkspacePreviewTests {
    @Test func previewIsLoadedSynchronouslyAndLocalOnly() {
        let workspace = Workspace.preview()

        #expect(workspace.isLoaded)
        #expect(workspace.loadError == nil)
        #expect(workspace.account == nil)
        #expect(workspace.syncStatus == .localOnly)
        #expect(workspace.pendingChangeCount == workspace.document.outbox.count)
        #expect(workspace.state == workspace.replayedState)
    }

    @Test(arguments: [
        Destination.list(.inbox), .list(.next), .list(.waiting), .list(.someday), .dateView(.overdue),
        .dateView(.today), .dateView(.upcoming), .agenda, .history(.completed), .history(.cancelled),
    ])
    func everyListHasSampleTasks(_ destination: Destination) {
        let workspace = Workspace.preview()

        #expect(!workspace.list(destination).isEmpty)
    }

    @Test func previewHasProjectsTagsSubtasksAndComments() throws {
        let workspace = Workspace.preview()

        let projects = workspace.projects()
        #expect(projects.count >= 3)
        #expect(projects.contains { $0.needsNextAction })
        #expect(projects.contains { !$0.needsNextAction })
        #expect(!workspace.projects(archived: true).isEmpty)
        let tagNames = Set(workspace.tags().map(\.tag.name))
        #expect(tagNames.isSuperset(of: ["home", "calls", "errands"]))
        #expect(workspace.state.tasks.values.contains { !$0.subtasks.isEmpty && !$0.comments.isEmpty })
        #expect(workspace.state.tasks.values.contains { $0.state == .waiting && $0.waitingFor != nil })
        for project in projects {
            #expect(!workspace.list(.project(project.id)).isEmpty || project.needsNextAction)
        }
        let counts = workspace.counts()
        #expect(counts.inbox > 0 && counts.next > 0 && counts.overdue > 0 && counts.today > 0)
    }

    @Test func previewAcceptsCommands() async throws {
        let workspace = Workspace.preview()
        let before = workspace.counts().inbox

        let id = try workspace.capture(CaptureDraft(text: "Try the preview #calls"))
        await workspace.flush()

        #expect(workspace.counts().inbox == before + 1)
        #expect(workspace.storageError == nil)
        #expect(workspace.task(id)?.tagIDs.count == 1)
    }
}
