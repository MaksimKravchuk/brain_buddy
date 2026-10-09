import BrainBuddyCore
import BrainBuddyWorkspace
import SwiftUI

/// Capture one task, offline, with Smart Add.
///
/// A compact panel that sits right above the keyboard: a header (Close, the
/// title, and "Added" after Return), the Smart Add field, and one scrolling
/// row of chips (list, due date, priority, notes) next to a round Add button.
///
/// - Type `@project` and `#tag` in the text; chips below the field show the
///   project and tags that will be used, marking the ones capture will create.
/// - Return adds the task and keeps the sheet open for the next one ("Added"
///   in the header); the Add button adds and closes; Close closes without
///   adding.
/// - Closing with unsaved text asks first ("Discard this task?"); swiping the
///   sheet away is disabled while there is text.
/// - Starting from a project or tag screen files the task there unless a
///   token says otherwise, and Today's "+" starts with today's date
///   (`CaptureContext`).
/// - Toasts show above the chip row and Add button, never over them.
///
/// The sheet has one detent, `.height(...)`, equal to the measured height of
/// its content, so it stays exactly as tall as what is on screen (the bare
/// panel, plus the project line, a problem, or the Waiting for and Notes
/// fields when present) at every Dynamic Type size. The content sits in a
/// `ScrollView` that only scrolls when it cannot fit, so nothing is clipped
/// if the system caps the sheet's height.
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
    /// Set once Add has added the task and the sheet is closing, so a second
    /// tap during the dismissal can't add it again.
    @State private var isClosing = false
    /// The measured height of the panel's content; zero until first layout.
    @State private var contentHeight: CGFloat = 0
    /// The sheet's height until the content has been measured.
    @ScaledMetric(relativeTo: .body) private var fallbackHeight: CGFloat = 170
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
        let preview = workspace.capturePreview(draft)
        ScrollView {
            VStack(spacing: 0) {
                header
                fields(preview)
                // Above the chip row, so a toast never covers the Add button.
                ToastHost()
                controlsRow(preview)
            }
            .padding(.bottom, BBSpacing.s2)
            .onGeometryChange(for: CGFloat.self) { proxy in
                proxy.size.height
            } action: { height in
                contentHeight = height
            }
        }
        .scrollBounceBehavior(.basedOnSize)
        .toastMagicTap()
        .presentationDetents([.height(contentHeight > 0 ? contentHeight : fallbackHeight)])
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

    // MARK: Header

    /// Close on the leading edge, the title centred, and the transient
    /// "Added" confirmation on the trailing edge.
    private var header: some View {
        ZStack {
            Text("New task")
                .font(.headline)
                .lineLimit(1)
                .accessibilityAddTraits(.isHeader)
            HStack {
                Button("Close", action: close)
                    .keyboardShortcut(.cancelAction)
                    .frame(minWidth: BBMetrics.hitTarget, minHeight: BBMetrics.hitTarget, alignment: .leading)
                    .contentShape(Rectangle())
                Spacer(minLength: BBSpacing.s2)
                if let confirmation {
                    Label("Added", systemImage: "checkmark.circle")
                        .font(.subheadline.weight(.medium))
                        .foregroundStyle(BBColor.successText)
                        .lineLimit(1)
                        .minimumScaleFactor(0.7)
                        .accessibilityLabel(confirmation)
                }
            }
        }
        .padding(.horizontal, BBSpacing.s4)
        .padding(.top, BBSpacing.s1)
    }

    // MARK: Fields

    /// The Smart Add field and what hangs off it: a problem, the project and
    /// tags capture will use, and the Waiting for and Notes fields.
    private func fields(_ preview: CapturePreview) -> some View {
        VStack(alignment: .leading, spacing: BBSpacing.s1) {
            SmartAddTextField(
                text: $draft.text,
                tokens: preview.tokens,
                placeholder: "Task — type @ for a project, # for a tag"
            ) {
                add(keepOpen: true)
            }
            if let problem = errorMessage ?? visibleProblem(preview) {
                InlineProblemText(message: problem)
            }
            if preview.project != nil || !preview.tags.isEmpty {
                CapturePreviewChips(preview: preview)
            }
            if draft.list == .inbox, let project = preview.project {
                Text("With a project, it goes to \(project.name) rather than the Inbox.")
                    .font(.footnote)
                    .foregroundStyle(.secondary)
            }
            if draft.list == .waiting {
                TextField("Who or what are you waiting on?", text: $draft.waitingFor, axis: .vertical)
                    .lineLimit(1...3)
                    .focused($isWaitingForFocused)
                    .accessibilityLabel("Waiting for")
                    .captureFieldStyle()
                WaitingForFooter(text: draft.waitingFor)
                    .font(.footnote)
                    .foregroundStyle(.secondary)
            }
            if showsNotes {
                TextField("Notes, links, details…", text: $draft.details, axis: .vertical)
                    .lineLimit(2...5)
                    .focused($isNotesFocused)
                    .accessibilityLabel("Notes")
                    .captureFieldStyle()
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.horizontal, BBSpacing.s4)
    }

    // MARK: Chips and Add

    /// The chips scroll sideways; the Add button stays put at the trailing end.
    private func controlsRow(_ preview: CapturePreview) -> some View {
        HStack(spacing: BBSpacing.s2) {
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: BBSpacing.s2) {
                    listChip
                    dueChip
                    priorityChip
                    notesChip
                }
            }
            addButton(preview)
        }
        .padding(.horizontal, BBSpacing.s4)
    }

    private var listChip: some View {
        Menu {
            Picker("List", selection: $draft.list) {
                ForEach(OpenList.allCases) { list in
                    Label(list.title, systemImage: list.symbolName)
                        .tag(list)
                }
            }
        } label: {
            // A list is always chosen, so this chip is always highlighted.
            CaptureChipLabel(systemImage: draft.list.symbolName, title: draft.list.title, isHighlighted: true)
        }
        .accessibilityLabel("List")
        .accessibilityValue(draft.list.title)
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
            CaptureChipLabel(
                systemImage: "calendar",
                title: draft.dueDate.map { DueChip.label(for: $0, today: workspace.today) } ?? "Date"
            )
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

    private var priorityChip: some View {
        Menu {
            Picker("Priority", selection: $draft.priority) {
                ForEach(TaskPriority.allCases, id: \.self) { priority in
                    Label(priority.title, systemImage: priority.symbolName)
                        .tag(priority)
                }
            }
        } label: {
            CaptureChipLabel(
                systemImage: "flag",
                title: draft.priority == .none ? "Priority" : draft.priority.title
            )
        }
        .accessibilityLabel("Priority")
        .accessibilityValue(draft.priority.title)
    }

    private var notesChip: some View {
        Button {
            showsNotes.toggle()
            if showsNotes {
                Task { isNotesFocused = true }
            }
        } label: {
            CaptureChipLabel(
                systemImage: "note.text",
                title: draft.details.isEmpty ? "Notes" : "Notes · added"
            )
        }
        .buttonStyle(.plain)
        .accessibilityLabel(draft.details.isEmpty ? "Notes" : "Notes · added")
        .accessibilityValue(showsNotes ? "Shown" : "Hidden")
        .accessibilityHint("Shows or hides the notes field.")
    }

    private func addButton(_ preview: CapturePreview) -> some View {
        let isEnabled = preview.isValid && !isClosing
        return Button {
            add(keepOpen: false)
        } label: {
            Image(systemName: "arrow.up")
                .font(.headline.weight(.semibold))
                .foregroundStyle(BBColor.onBrand)
                .frame(width: BBMetrics.hitTarget, height: BBMetrics.hitTarget)
                .background(BBColor.brandFill.opacity(isEnabled ? 1 : 0.4), in: Circle())
                .contentShape(Circle())
        }
        .buttonStyle(.plain)
        .disabled(!isEnabled)
        .accessibilityLabel("Add")
        .accessibilityHint(visibleProblem(preview) ?? "Adds the task and closes.")
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
        // A second tap while the sheet is closing would add the same task again.
        guard !isClosing else { return }
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
            draft = Self.freshDraft(list: draft.list, context: context)
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

/// One compact chip in the control row: a brand-coloured symbol and a short
/// title in a hairline capsule about 34 pt tall, inside a 44 pt hit area.
/// `isHighlighted` fills it with the soft brand tint.
private struct CaptureChipLabel: View {
    let systemImage: String
    let title: String
    var isHighlighted = false

    var body: some View {
        HStack(spacing: 6) {
            Image(systemName: systemImage)
                .imageScale(.small)
                .foregroundStyle(BBColor.brandText)
                .accessibilityHidden(true)
            Text(title)
                .foregroundStyle(BBColor.textPrimary)
        }
        .font(.subheadline)
        .lineLimit(1)
        .padding(.horizontal, BBSpacing.s3)
        .frame(minHeight: 34)
        .background(isHighlighted ? BBColor.brandSoft : Color.clear, in: Capsule())
        .overlay {
            Capsule().strokeBorder(BBColor.hairline, lineWidth: 1)
        }
        .frame(minHeight: BBMetrics.hitTarget)
        .contentShape(Rectangle())
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
