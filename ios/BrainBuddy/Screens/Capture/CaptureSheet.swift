import BrainBuddyCore
import BrainBuddyDesign
import BrainBuddyWorkspace
import SwiftUI

/// Capture one task, offline, with Smart Add (Carry On board 10).
///
/// A large sheet with a grabber over the current list. From the top: a header
/// (Close, and "Added" after Return), the meta line ("New · goes to Inbox",
/// naming the list or project the task will really land in), the Smart Add
/// field, one wrapping row of chips (the project and tags capture will use,
/// then the outlined "+ Date" and "+ Note"), "Put it in" with one chip per
/// list, and a floating glass bar with Add.
///
/// - Type `@project` and `#tag` in the text; the chips show the project and
///   tags that will be used, marking the ones capture will create.
/// - Return adds the task and keeps the sheet open for the next one ("Added"
///   in the header); the Add button adds and closes; Close closes without
///   adding.
/// - Closing with unsaved text asks first ("Discard this task?"); swiping the
///   sheet away is disabled while there is text.
/// - Starting from a project or tag screen files the task there unless a
///   token says otherwise, and Today's "+" starts with today's date
///   (`CaptureContext`).
/// - Toasts show above the glass bar, never over it.
///
/// The content scrolls only when it cannot fit (large Dynamic Type sizes, the
/// keyboard up), so nothing is clipped.
struct CaptureSheet: View {
    private let context: CaptureContext

    @Environment(Workspace.self) private var workspace
    @Environment(ToastCenter.self) private var toasts
    @Environment(\.dismiss) private var dismiss
    @State private var draft: CaptureDraft
    @State private var errorMessage: String?
    @State private var confirmation: String?
    @State private var showsNotes = false
    @State private var isShowingCalendar = false
    @State private var isConfirmingDiscard = false
    @State private var isShowingVoice = false
    /// Set once Add has added the task and the sheet is closing, so a second
    /// tap during the dismissal can't add it again.
    @State private var isClosing = false
    @State private var isSaving = false
    @State private var editorID = UUID().uuidString
    /// The last preview the runtime answered, shown while the next one loads so the text field
    /// is never replaced mid-typing.
    @State private var previewHold = CapturePreviewHold()
    @FocusState private var isWaitingForFocused: Bool
    @FocusState private var isNotesFocused: Bool

    init(context: CaptureContext) {
        self.context = context
        _draft = State(initialValue: Self.freshDraft(list: context.list, context: context))
    }

    /// An empty draft for `list` with the context's project, tag and due date.
    private static func freshDraft(list: OpenList, context: CaptureContext) -> CaptureDraft {
        CaptureDraft(
            list: list,
            dueDate: context.dueDate,
            contextProjectID: context.projectID,
            contextTagID: context.tagID
        )
    }

    var body: some View {
        let readiness = workspace.capturePreviewReadiness(draft)
        let isReady = readiness == .ready
        let preview = previewHold.shown(isReady: isReady) { workspace.capturePreview(draft) }
        let failure = CapturePreviewGate.failureMessage(isFailed: Self.isFailed(readiness))
        VStack(spacing: 0) {
            header
            ScrollView {
                fields(preview, previewFailure: failure)
                    .padding(.top, CGFloat(CarryOnSpace.xs))
                    .padding(.bottom, CGFloat(CarryOnSpace.md))
            }
            .scrollBounceBehavior(.basedOnSize)
        }
        .safeAreaInset(edge: .bottom, spacing: 0) {
            // The toast sits above the glass bar, so it never covers Add.
            VStack(spacing: 0) {
                ToastHost()
                actionBar(preview)
            }
        }
        .bbScreenBackground()
        .toastMagicTap()
        .presentationDetents([.large])
        .presentationDragIndicator(.visible)
        .interactiveDismissDisabled(!draft.isBlank)
        // The sheet and its text field stay put whatever the preview is doing; only the chips and
        // the problem line follow it. Typing runs ahead of the runtime, so a burst of keystrokes
        // asks once for the settled draft.
        .task(id: draft) {
            if workspace.isRustSelected {
                try? await Task.sleep(for: .milliseconds(150))
                if Task.isCancelled { return }
            }
            await workspace.prepareCapturePreview(draft)
            if Task.isCancelled { return }
            previewHold.record(workspace.capturePreview(draft), isReady: workspace.capturePreviewReadiness(draft) == .ready)
        }
        .sheet(isPresented: $isShowingVoice) {
            // Added steps already carry the toast; closing this sheet too ends the capture.
            VoiceCaptureSheet(workspace: workspace) { dismiss() }
        }
        .confirmationDialog("Discard this task?", isPresented: $isConfirmingDiscard, titleVisibility: .visible) {
            Button("Discard", role: .destructive) { dismiss() }
            Button("Keep editing", role: .cancel) {}
        } message: {
            Text("What you typed hasn't been added.")
        }
        .onChange(of: draft) { _, _ in
            errorMessage = nil
        }
        // Previews are ephemeral queries: drop them with the sheet so they are not kept in the cache.
        .onDisappear { workspace.discardCapturePreviews() }
        .onChange(of: draft.list) { _, list in
            // Choosing Waiting for asks who or what at once (opening capture
            // on Waiting for keeps the focus on the task text). The field
            // appears with this change, so focus it once it is there.
            guard list == .waiting else { return }
            Task { isWaitingForFocused = true }
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

    private static func isFailed(_ readiness: WorkspaceQueryReadiness) -> Bool {
        if case .failed = readiness { return true }
        return false
    }

    // MARK: Header

    /// Close on the leading edge and the transient "Added" confirmation on the
    /// trailing edge. The sheet has no title: the meta line below says what
    /// this is and where it goes.
    private var header: some View {
        HStack {
            Button("Close", action: close)
                .keyboardShortcut(.cancelAction)
                .frame(minWidth: BBMetrics.hitTarget, minHeight: BBMetrics.hitTarget, alignment: .leading)
                .contentShape(Rectangle())
            Spacer(minLength: CGFloat(CarryOnSpace.xs))
            if let confirmation {
                Label("Added", systemImage: "checkmark.circle")
                    .carryOnFont(CarryOnTypeScale.metaStrong)
                    .foregroundStyle(.coTextPrimary)
                    .lineLimit(1)
                    .minimumScaleFactor(0.7)
                    .accessibilityLabel(confirmation)
            }
        }
        .padding(.horizontal, CGFloat(CarryOnSpace.lg))
        .padding(.top, CGFloat(CarryOnSpace.sm))
    }

    // MARK: Fields

    /// The meta line, the Smart Add field and what hangs off it: a problem,
    /// the chips, the Notes field, the list choices and the Waiting for field.
    private func fields(_ preview: CapturePreview, previewFailure: String?) -> some View {
        VStack(alignment: .leading, spacing: CGFloat(CarryOnSpace.sm)) {
            Text("New · goes to \(destinationName(preview))")
                .carryOnFont(CarryOnTypeScale.meta)
                .foregroundStyle(.coTextSecondary)
                .accessibilityAddTraits(.isHeader)
            SmartAddTextField(
                text: $draft.text,
                tokens: preview.tokens,
                placeholder: "Task · @project · #tag"
            ) {
                add(keepOpen: true)
            }
            if let problem = errorMessage ?? visibleProblem(preview) ?? previewFailure {
                InlineProblemText(message: problem)
            }
            if previewFailure != nil {
                Button("Try again") { Task { await workspace.prepareCapturePreview(draft) } }
                    .carryOnFont(CarryOnTypeScale.meta)
                    .frame(minHeight: BBMetrics.hitTarget, alignment: .leading)
            }
            CaptureChipRow(preview: preview) {
                dueChip
                notesChip
            }
            if showsNotes {
                TextField("Notes, links, details…", text: $draft.details, axis: .vertical)
                    .lineLimit(2...5)
                    .focused($isNotesFocused)
                    .accessibilityLabel("Notes")
                    .captureFieldStyle()
            }
            listChoices
            if draft.list == .inbox, let project = preview.project {
                Text("With a project, it goes to \(project.name) rather than the Inbox.")
                    .carryOnFont(CarryOnTypeScale.meta)
                    .foregroundStyle(.coTextSecondary)
            }
            if draft.list == .waiting {
                TextField("Who or what are you waiting on?", text: $draft.waitingFor, axis: .vertical)
                    .lineLimit(1...3)
                    .focused($isWaitingForFocused)
                    .accessibilityLabel("Waiting for")
                    .captureFieldStyle()
                WaitingForFooter(text: draft.waitingFor)
                    .carryOnFont(CarryOnTypeScale.meta)
                    .foregroundStyle(.coTextSecondary)
            }
        }
        .disabled(isSaving)
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.horizontal, CGFloat(CarryOnSpace.lg))
    }

    // MARK: Chips

    /// "Put it in": one chip per list; the chosen one is the filled chip and
    /// is announced as selected, so the choice never rests on colour.
    private var listChoices: some View {
        VStack(alignment: .leading, spacing: CGFloat(CarryOnSpace.xs)) {
            Text("Put it in")
                .carryOnFont(CarryOnTypeScale.metaStrong)
                .foregroundStyle(.coTextSecondary)
                .accessibilityAddTraits(.isHeader)
            BBFlowLayout(spacing: CGFloat(CarryOnSpace.xs), lineSpacing: CGFloat(CarryOnSpace.xs)) {
                ForEach(OpenList.allCases) { list in
                    let isChosen = draft.list == list
                    Button {
                        draft.list = list
                    } label: {
                        CarryOnChip(list.title, size: .quick, isSelected: isChosen)
                            .frame(minHeight: BBMetrics.hitTarget)
                            .contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                    .accessibilityLabel(list.title)
                    .accessibilityAddTraits(isChosen ? .isSelected : [])
                }
            }
        }
    }

    private var dueChip: some View {
        Menu {
            Button("Today") { draft.dueDate = workspace.today }
            Button("Tomorrow") { draft.dueDate = workspace.today.adding(days: 1) }
            Button("Next week") { draft.dueDate = workspace.today.adding(days: 7) }
            Button("Pick a date…") {
                // After the menu has closed, or the popover can lose the race.
                Task { isShowingCalendar = true }
            }
            if draft.dueDate != nil {
                Divider()
                Button("Clear due date", role: .destructive) { draft.dueDate = nil }
            }
        } label: {
            Group {
                if let dueDate = draft.dueDate {
                    CarryOnChip(DueChip.label(for: dueDate, today: workspace.today))
                } else {
                    CarryOnChip("+ Date", variant: .outlined)
                }
            }
            .frame(minHeight: BBMetrics.hitTarget)
            .contentShape(Rectangle())
        }
        .accessibilityLabel("Due date")
        .accessibilityValue(
            draft.dueDate.map { $0.startDate().formatted(date: .complete, time: .omitted) } ?? "None"
        )
        .popover(isPresented: $isShowingCalendar) {
            CaptureDueDateCalendar(initialDate: (draft.dueDate ?? workspace.today).startDate()) { picked in
                draft.dueDate = picked
                isShowingCalendar = false
            }
            .padding(BBSpacing.s2)
            .frame(width: 336)
            .presentationCompactAdaptation(.popover)
        }
    }

    private var notesChip: some View {
        Button {
            showsNotes.toggle()
            if showsNotes {
                Task { isNotesFocused = true }
            }
        } label: {
            Group {
                if draft.details.isEmpty {
                    CarryOnChip("+ Note", variant: .outlined)
                } else {
                    CarryOnChip("Note · added")
                }
            }
            .frame(minHeight: BBMetrics.hitTarget)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityLabel(draft.details.isEmpty ? "Notes" : "Notes · added")
        .accessibilityValue(showsNotes ? "Shown" : "Hidden")
        .accessibilityHint("Shows or hides the notes field.")
    }

    // MARK: Add

    /// The floating glass bar. Add is on the trailing side; the voice button
    /// on the leading side opens the on-device voice brain dump.
    private func actionBar(_ preview: CapturePreview) -> some View {
        let isEnabled = preview.isValid && !isClosing && !isSaving
        return BBGlassActionBar {
            Button {
                isShowingVoice = true
            } label: {
                VoiceButtonFace(live: false, size: 50)
            }
            .buttonStyle(.plain)
            .disabled(isClosing || isSaving)
            .accessibilityLabel("Talk")
            .accessibilityHint("Opens voice capture. What you say becomes steps for your Inbox.")
            Spacer(minLength: 0)
            Button {
                add(keepOpen: false)
            } label: {
                Text("Add")
            }
            .buttonStyle(.carryOnStrong)
            .disabled(!isEnabled)
            .accessibilityHint(visibleProblem(preview) ?? "Adds the task and closes.")
        }
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
        guard !isSaving, !isClosing else { return }
        isSaving = true
        let submittedDraft = draft
        let submittedEditorID = editorID
        Task { await addDurably(keepOpen: keepOpen, draft: submittedDraft, editorID: submittedEditorID) }
    }

    @MainActor private func addDurably(keepOpen: Bool, draft submittedDraft: CaptureDraft, editorID submittedEditorID: String) async {
        // A second tap while the sheet is closing would add the same task again.
        defer { isSaving = false }
        let preview = workspace.capturePreview(submittedDraft)
        if let problem = preview.problem {
            errorMessage = problem.message
            return
        }
        let destination = destinationName(preview)
        do {
            try await workspace.capture(submittedDraft, editorID: submittedEditorID)
        } catch {
            errorMessage = TaskCommandRunner.message(for: error)
            return
        }
        let message = "Added to \(destination)"
        if keepOpen {
            draft = Self.freshDraft(list: draft.list, context: context)
            editorID = UUID().uuidString
            showsNotes = false
            confirmation = message
            AccessibilityNotification.Announcement(message).post()
        } else {
            isClosing = true
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
        if draft.isBlank || isClosing {
            dismiss()
        } else {
            isConfirmingDiscard = true
        }
    }
}

/// A calendar that reports the day the person taps. It owns its selection
/// (seeded when it appears), so only a real choice is reported.
private struct CaptureDueDateCalendar: View {
    private let onPick: (CalendarDay) -> Void
    @State private var date: Date

    init(initialDate: Date, onPick: @escaping (CalendarDay) -> Void) {
        self.onPick = onPick
        _date = State(initialValue: initialDate)
    }

    var body: some View {
        DatePicker("Due date", selection: $date, displayedComponents: .date)
            .datePickerStyle(.graphical)
            .onChange(of: date) { _, newValue in
                onPick(CalendarDay(date: newValue))
            }
    }
}

private extension View {
    /// A text field on a sunken rounded surface, at least one hit target tall.
    func captureFieldStyle() -> some View {
        padding(.horizontal, BBSpacing.s3)
            .frame(minHeight: BBMetrics.hitTarget)
            .background(
                BBColor.surfaceSunken,
                in: RoundedRectangle(cornerRadius: BBRadius.input, style: .continuous)
            )
    }
}

/// The chips under the field: the project and tags capture will use, in words
/// for VoiceOver ("Project Errands, new") and with "· new" on screen when
/// capture will create them, then the screen's own add-chips (`trailing`).
private struct CaptureChipRow<Trailing: View>: View {
    let preview: CapturePreview
    private let trailing: Trailing

    @Environment(\.colorScheme) private var scheme

    init(preview: CapturePreview, @ViewBuilder trailing: () -> Trailing) {
        self.preview = preview
        self.trailing = trailing()
    }

    /// The preview carries no project colour, so the dot is the neutral
    /// mark-open, as for a project without a colour elsewhere.
    private var neutralDot: RGBColor {
        scheme == .dark ? CarryOnRole.markOpen.dark : CarryOnRole.markOpen.light
    }

    var body: some View {
        BBFlowLayout(spacing: CGFloat(CarryOnSpace.xs), lineSpacing: 0) {
            if let project = preview.project {
                CarryOnChip(project.isNew ? "\(project.name) · new" : project.name, dot: neutralDot)
                    .accessibilityElement(children: .ignore)
                    .accessibilityLabel(project.isNew ? "Project \(project.name), new" : "Project \(project.name)")
            }
            ForEach(preview.tags, id: \.self) { tag in
                CarryOnChip(tag.isNew ? "\(tag.name) · new" : tag.name)
                    .accessibilityElement(children: .ignore)
                    .accessibilityLabel(tag.isNew ? "Tag \(tag.name), new" : "Tag \(tag.name)")
            }
            trailing
        }
    }
}
