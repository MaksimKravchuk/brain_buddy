import BrainBuddyCore
import BrainBuddyWorkspace
import SwiftUI

/// Capture one task, offline, with Smart Add.
///
/// - Type `@project` and `#tag` in the text; chips below the field show the
///   project and tags that will be used, marking the ones capture will create.
/// - Return adds the task and keeps the sheet open for the next one ("Added
///   to Inbox"); the Add button adds and closes; Done closes without adding.
/// - Closing with unsaved text asks first ("Discard this task?"); swiping the
///   sheet away is disabled while there is text.
/// - Starting from a project or tag screen files the task there unless a
///   token says otherwise (`CaptureContext`).
struct CaptureSheet: View {
    private let context: CaptureContext

    @Environment(Workspace.self) private var workspace
    @Environment(ToastCenter.self) private var toasts
    @Environment(\.dismiss) private var dismiss
    @State private var draft: CaptureDraft
    @State private var errorMessage: String?
    @State private var confirmation: String?
    @State private var showsNotes = false
    @State private var isConfirmingDiscard = false

    init(context: CaptureContext) {
        self.context = context
        _draft = State(
            initialValue: CaptureDraft(
                list: context.list ?? .inbox,
                contextProjectID: context.projectID,
                contextTagID: context.tagID
            )
        )
    }

    var body: some View {
        let preview = workspace.capturePreview(draft)
        NavigationStack {
            Form {
                textSection(preview)
                listSection(preview)
                planningSection
                notesSection
            }
            .navigationTitle("New task")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Done", action: close)
                }
            }
            .safeAreaInset(edge: .bottom) {
                addButton(preview)
            }
        }
        .presentationDetents([.medium, .large])
        .interactiveDismissDisabled(!draft.isBlank)
        .confirmationDialog("Discard this task?", isPresented: $isConfirmingDiscard, titleVisibility: .visible) {
            Button("Discard", role: .destructive) { dismiss() }
            Button("Keep editing", role: .cancel) {}
        } message: {
            Text("What you typed hasn't been added.")
        }
        .onChange(of: draft) { _, _ in
            errorMessage = nil
        }
        .task(id: confirmation) {
            guard confirmation != nil else { return }
            do {
                try await Task.sleep(for: .seconds(4))
                confirmation = nil
            } catch {
                // A newer confirmation replaced this one.
            }
        }
    }

    // MARK: Sections

    private func textSection(_ preview: CapturePreview) -> some View {
        Section {
            SmartAddTextField(text: $draft.text, tokens: preview.tokens) {
                add(keepOpen: true)
            }
            if preview.project != nil || !preview.tags.isEmpty {
                CapturePreviewChips(preview: preview)
            }
        } footer: {
            textFooter(preview)
        }
    }

    @ViewBuilder private func textFooter(_ preview: CapturePreview) -> some View {
        if let errorMessage {
            InlineProblemText(message: errorMessage)
        } else if let problem = visibleProblem(preview) {
            InlineProblemText(message: problem)
        } else if let confirmation {
            Label(confirmation, systemImage: "checkmark.circle")
        } else {
            Text("Type @ for a project and # for a tag. Return adds the task and keeps this open.")
        }
    }

    private func listSection(_ preview: CapturePreview) -> some View {
        Section {
            Picker(selection: $draft.list) {
                ForEach(OpenList.allCases) { list in
                    Label(list.title, systemImage: list.symbolName)
                        .tag(list)
                }
            } label: {
                Label("List", systemImage: "tray.full")
            }
            if draft.list == .waiting {
                TextField("Who or what are you waiting on?", text: $draft.waitingFor, axis: .vertical)
                    .lineLimit(1...3)
                    .accessibilityLabel("Waiting for")
            }
        } footer: {
            if draft.list == .waiting {
                WaitingForFooter(text: draft.waitingFor)
            } else if draft.list == .inbox, let project = preview.project {
                Text("With a project, it goes to \(project.name) rather than the Inbox.")
            }
        }
    }

    private var planningSection: some View {
        Section {
            DueDateQuickPicker(day: draft.dueDate, today: workspace.today) { day in
                draft.dueDate = day
            }
            Picker(selection: $draft.priority) {
                ForEach(TaskPriority.allCases, id: \.self) { priority in
                    Text(priority.title).tag(priority)
                }
            } label: {
                Label("Priority", systemImage: "flag")
            }
        }
    }

    private var notesSection: some View {
        Section {
            DisclosureGroup(isExpanded: $showsNotes) {
                TextField("Notes, links, context…", text: $draft.details, axis: .vertical)
                    .lineLimit(3...8)
                    .accessibilityLabel("Notes")
            } label: {
                Label(draft.details.isEmpty ? "Notes" : "Notes · added", systemImage: "note.text")
            }
        }
    }

    private func addButton(_ preview: CapturePreview) -> some View {
        Button {
            add(keepOpen: false)
        } label: {
            Text("Add")
                .font(.headline)
                .frame(maxWidth: .infinity, minHeight: 44)
        }
        .buttonStyle(.glassProminent)
        .controlSize(.large)
        .disabled(!preview.isValid)
        .accessibilityHint(visibleProblem(preview) ?? "Adds the task and closes.")
        .padding(.horizontal, 16)
        .padding(.bottom, 8)
    }

    // MARK: Behaviour

    /// The preview's problem, once there is something to complain about.
    /// Waiting-for problems are explained next to that field instead.
    private func visibleProblem(_ preview: CapturePreview) -> String? {
        guard let problem = preview.problem else { return nil }
        switch problem {
        case .emptyTitle where draft.text.allSatisfy(\.isWhitespace):
            return nil
        case .waitingForRequired, .waitingForTooLong:
            return nil
        default:
            return problem.message
        }
    }

    private func add(keepOpen: Bool) {
        let preview = workspace.capturePreview(draft)
        if let problem = preview.problem {
            errorMessage = problem.message
            return
        }
        let destination = destinationName(preview)
        do {
            try workspace.capture(draft)
        } catch {
            errorMessage = error.message
            return
        }
        let message = "Added to \(destination)"
        if keepOpen {
            draft = CaptureDraft(
                list: draft.list, contextProjectID: draft.contextProjectID, contextTagID: draft.contextTagID)
            showsNotes = false
            confirmation = message
            AccessibilityNotification.Announcement(message).post()
        } else {
            toasts.show(message)
            dismiss()
        }
    }

    /// Where the task will show up: Inbox holds projectless tasks only, so an
    /// Inbox capture with a project lands in that project.
    private func destinationName(_ preview: CapturePreview) -> String {
        if draft.list == .inbox, let project = preview.project { return project.name }
        return draft.list.title
    }

    private func close() {
        if draft.isBlank {
            dismiss()
        } else {
            isConfirmingDiscard = true
        }
    }
}

/// The project and tags capture will use, in words for VoiceOver
/// ("Project Errands, new") and with a dashed "New" marker on screen.
private struct CapturePreviewChips: View {
    let preview: CapturePreview

    var body: some View {
        WrappingChipLayout(spacing: 6) {
            if let project = preview.project {
                chip(isNew: project.isNew) {
                    ProjectLabel(name: project.name, color: nil)
                }
                .accessibilityElement(children: .ignore)
                .accessibilityLabel(project.isNew ? "Project \(project.name), new" : "Project \(project.name)")
            }
            ForEach(preview.tags, id: \.self) { tag in
                chip(isNew: tag.isNew) {
                    TagPill(name: tag.name)
                }
                .accessibilityElement(children: .ignore)
                .accessibilityLabel(tag.isNew ? "Tag \(tag.name), new" : "Tag \(tag.name)")
            }
        }
        .padding(.vertical, 4)
    }

    private func chip<Content: View>(isNew: Bool, @ViewBuilder content: () -> Content) -> some View {
        HStack(spacing: 4) {
            content()
            if isNew {
                Text("New")
                    .font(.caption2.weight(.semibold))
                    .foregroundStyle(.secondary)
                    .padding(.horizontal, 6)
                    .padding(.vertical, 2)
                    .overlay {
                        Capsule().strokeBorder(Color.secondary, style: StrokeStyle(lineWidth: 1, dash: [3, 2]))
                    }
            }
        }
    }
}
