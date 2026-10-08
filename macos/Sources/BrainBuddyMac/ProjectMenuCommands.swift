import BrainBuddyCore
import BrainBuddyMacCore
import SwiftUI

/// File › "Archive project" and "Unarchive project" for the project open in the window: the
/// keyboard path of X-06 (no shortcut). Archive is disabled, with the sidebar's help text, while a
/// task edit is unsaved or the capture draft is not empty (FR-024, FR-026).
struct ProjectMenuCommands: Commands {
    @FocusedValue(\.workspaceModel) private var model

    var body: some Commands {
        CommandGroup(after: .newItem) {
            Divider()
            Button("Archive project") {
                if let model, let id = activeProject(model) { model.archiveProject(id) }
            }
            .disabled(!canArchive)
            .help("Add or clear the current task draft before archiving")
            Button("Unarchive project") {
                if let model, let id = archivedProject(model) { model.unarchiveProject(id) }
            }
            .disabled(model.flatMap { archivedProject($0) } == nil)
        }
    }

    private var canArchive: Bool {
        guard let model, activeProject(model) != nil else { return false }
        return model.canArchiveProject
    }

    private func activeProject(_ model: BrainBuddyModel) -> ProjectID? {
        guard case .project(let id) = model.destination, !model.isArchived(id), model.project(id) != nil else { return nil }
        return id
    }

    private func archivedProject(_ model: BrainBuddyModel) -> ProjectID? {
        guard case .project(let id) = model.destination, model.isArchived(id) else { return nil }
        return id
    }
}
