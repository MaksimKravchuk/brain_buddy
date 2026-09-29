import BrainBuddyCore
import BrainBuddyWorkspace
import SwiftUI

/// Creates or renames a tag. Validation runs in the workspace (offline).
struct TagEditorSheet: View {
    enum Mode: Identifiable, Hashable {
        case create
        case rename(TagRecord)

        var id: String {
            switch self {
            case .create: return "create"
            case .rename(let tag): return "rename-\(tag.id.rawValue)"
            }
        }
    }

    @Environment(Workspace.self) private var workspace
    @Environment(\.dismiss) private var dismiss

    private let mode: Mode
    @State private var name: String
    @State private var message: String?
    @FocusState private var isNameFocused: Bool

    init(mode: Mode) {
        self.mode = mode
        switch mode {
        case .create: _name = State(initialValue: "")
        case .rename(let tag): _name = State(initialValue: tag.name)
        }
    }

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    HStack(spacing: 2) {
                        Text(verbatim: "#")
                            .foregroundStyle(.secondary)
                            .accessibilityHidden(true)
                        TextField("Tag name", text: $name)
                            .textInputAutocapitalization(.never)
                            .autocorrectionDisabled()
                            .submitLabel(.done)
                            .focused($isNameFocused)
                            .onSubmit { save() }
                    }
                } footer: {
                    if let message {
                        EditorValidationMessage(text: message)
                    } else {
                        Text("Tags group tasks by where or how you do them, like calls or errands.")
                    }
                }
            }
            .navigationTitle(isCreating ? "New tag" : "Rename tag")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button(isCreating ? "Add" : "Save") { save() }
                        .disabled(cleanedName.isEmpty)
                }
            }
            .onChange(of: name) { message = nil }
            .onAppear { isNameFocused = true }
        }
        .presentationDetents([.medium])
    }

    private var isCreating: Bool {
        if case .create = mode { return true }
        return false
    }

    /// Trimmed, without the `#` people type out of Smart Add habit.
    private var cleanedName: String {
        var value = name.trimmingCharacters(in: .whitespacesAndNewlines)
        while value.hasPrefix("#") { value.removeFirst() }
        return value.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private func save() {
        let newName = cleanedName
        guard !newName.isEmpty else {
            message = GTDValidationError.emptyName.message
            return
        }
        do {
            switch mode {
            case .create:
                try workspace.createTag(name: newName)
            case .rename(let original):
                guard let current = workspace.tag(original.id) else {
                    throw GTDValidationError.tagNotFound
                }
                if newName != current.name {
                    try workspace.renameTag(current.id, to: newName)
                }
            }
            dismiss()
        } catch let error as GTDValidationError {
            message = error.message
        } catch {
            message = error.localizedDescription
        }
    }
}
