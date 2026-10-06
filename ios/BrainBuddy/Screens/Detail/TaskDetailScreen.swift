import BrainBuddyCore
import BrainBuddyWorkspace
import SwiftUI

/// Task detail, pushed from any list.
///
/// **Saving model (iOS): immediate save per field.** Unlike the macOS editor,
/// which collects edits behind explicit Save and Cancel buttons, every
/// committed edit here is saved at once as one `Workspace.updateTask` call
/// with a single-field `TaskChanges`:
///
/// - pickers, menus, toggles and tag choices save on selection;
/// - text fields (title, notes, waiting for) save when you press Return or
///   leave the field — focus moves elsewhere, the screen closes, or the app
///   goes to the background.
///
/// The workspace applies each change in memory immediately and queues it for
/// sync, so nothing depends on the network and there is no unsaved state to
/// discard or warn about. A rejected edit (for example an empty title) keeps
/// the stored value and says why under the field.
///
/// Completed and cancelled tasks are read-only apart from Reopen.
struct TaskDetailScreen: View {
    private let taskID: TaskID

    @Environment(Workspace.self) private var workspace
    @Environment(AppRouter.self) private var router

    init(taskID: TaskID) {
        self.taskID = taskID
    }

    var body: some View {
        Group {
            if let task = workspace.task(taskID) {
                TaskDetailForm(task: task)
                    .id(task.id)
            } else {
                missingTask
            }
        }
        .task(id: taskID) {
            await workspace.refreshTaskDetails(taskID)
        }
    }

    private var missingTask: some View {
        VStack(spacing: 16) {
            EmptyStateView(
                title: "This task no longer exists",
                message: "It may have been removed while syncing. Your other tasks are unchanged.",
                systemImage: "questionmark.circle"
            )
            if !workspace.issues.isEmpty {
                Button("View sync issues") {
                    router.open(.syncIssues)
                }
                .buttonStyle(.bordered)
                .controlSize(.large)
            }
        }
        .padding()
        .navigationTitle("Task")
        .navigationBarTitleDisplayMode(.inline)
    }
}

private enum DetailField: Hashable {
    case title, notes, waitingFor, organize, tags
}

private struct DetailProblem: Equatable {
    var field: DetailField
    var message: String
}

private struct TaskDetailForm: View {
    let task: TaskRecord

    @Environment(Workspace.self) private var workspace
    @Environment(ToastCenter.self) private var toasts
    @Environment(\.scenePhase) private var scenePhase
    @State private var title: String
    @State private var notes: String
    @State private var waitingFor: String
    /// Picker selections mirror the stored values and save on change.
    @State private var priority: TaskPriority
    @State private var projectID: ProjectID?
    @State private var problem: DetailProblem?
    @State private var isMoving = false
    @State private var moveInitialList: OpenList?
    @State private var isReopening = false
    @State private var isEditingTags = false
    /// The decision card (M-03) opened from "This wording" (M-02).
    @State private var isDeciding = false
    @FocusState private var focus: DetailField?

    init(task: TaskRecord) {
        self.task = task
        _title = State(initialValue: task.title)
        _notes = State(initialValue: task.details ?? "")
        _waitingFor = State(initialValue: task.waitingFor ?? "")
        _priority = State(initialValue: task.priority)
        _projectID = State(initialValue: task.projectID)
    }

    private var isReadOnly: Bool { !task.isOpen }

    var body: some View {
        savingForm
            .sheet(isPresented: $isMoving) {
                MoveSheet(task: task, initialList: moveInitialList)
            }
            .sheet(isPresented: $isReopening) {
                ReopenSheet(task: task)
            }
            .sheet(isPresented: $isEditingTags) {
                TaskTagsSheet(taskID: task.id)
            }
            .sheet(isPresented: $isDeciding) {
                DecisionCardSheet(taskID: task.id)
            }
    }

    /// Saves edits: text fields when they lose focus (or the screen closes or
    /// the app backgrounds), pickers as soon as the selection changes.
    private var savingForm: some View {
        syncedForm
            .onChange(of: focus) { previous, _ in
                if let previous { commit(previous) }
            }
            .onChange(of: priority) { _, newValue in
                guard newValue != task.priority else { return }
                if !save(.organize, TaskChanges(priority: .set(newValue))) { priority = task.priority }
            }
            .onChange(of: projectID) { _, newValue in
                guard newValue != task.projectID else { return }
                if !save(.organize, TaskChanges(projectID: setOrClear(newValue))) { projectID = task.projectID }
            }
            .onChange(of: scenePhase) { _, phase in
                if phase != .active { commitAll() }
            }
            .onDisappear { commitAll() }
    }

    /// Keeps the drafts in step with changes made elsewhere (sync, widgets),
    /// except for the field being edited.
    private var syncedForm: some View {
        form
            .navigationTitle(navigationTitle)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { toolbarContent }
            .onChange(of: task.title) { _, newValue in
                if focus != .title { title = newValue }
            }
            .onChange(of: task.details) { _, newValue in
                if focus != .notes { notes = newValue ?? "" }
            }
            .onChange(of: task.waitingFor) { _, newValue in
                if focus != .waitingFor { waitingFor = newValue ?? "" }
            }
            .onChange(of: task.priority) { _, newValue in
                priority = newValue
            }
            .onChange(of: task.projectID) { _, newValue in
                projectID = newValue
            }
    }

    private var form: some View {
        Form {
            titleSection
            // Spec 020, M-02: the wording's age and "Decide" (only while exposed).
            FormulationSection(task: task) {
                commitAll()
                isDeciding = true
            }
            statusSection
            if task.state == .waiting {
                waitingSection
            }
            notesSection
            organizeSection
            tagsSection
            SubtasksSection(task: task, isReadOnly: isReadOnly)
            CommentsSection(task: task, isReadOnly: isReadOnly)
            metadataSection
        }
    }

    private var navigationTitle: String {
        if let list = task.openList { return list.title }
        return task.state == .cancelled ? "Cancelled" : "Completed"
    }

    @ToolbarContentBuilder private var toolbarContent: some ToolbarContent {
        ToolbarItem(placement: .primaryAction) {
            if task.isOpen {
                Button(action: complete) {
                    Label("Complete", systemImage: "checkmark.circle")
                }
            } else {
                Button {
                    isReopening = true
                } label: {
                    Label("Reopen", systemImage: "arrow.uturn.backward.circle")
                }
            }
        }
        ToolbarItemGroup(placement: .keyboard) {
            Spacer()
            Button("Done") { focus = nil }
        }
    }

    // MARK: Sections

    private var titleSection: some View {
        Section {
            if isReadOnly {
                Text(task.title)
                    .font(.title3.weight(.semibold))
                    .accessibilityAddTraits(.isHeader)
            } else {
                TextField("Title", text: $title, axis: .vertical)
                    .font(.title3.weight(.semibold))
                    .focused($focus, equals: .title)
                    .submitLabel(.done)
                    .onSubmit { focus = nil }
                    .onChange(of: title) { _, newValue in
                        // A title is one line: Return (or a pasted line break) ends the edit.
                        if newValue.contains(where: \.isNewline) {
                            title = newValue.split(whereSeparator: \.isNewline).joined(separator: " ")
                            focus = nil
                        }
                    }
                    .accessibilityLabel("Title")
            }
        } footer: {
            problemText(for: .title)
        }
    }

    @ViewBuilder private var statusSection: some View {
        if let list = task.openList {
            Section("List") {
                Label(list.title, systemImage: list.symbolName)
                    .accessibilityLabel("In \(list.title)")
                Menu {
                    ForEach(OpenList.allCases.filter { $0 != list }) { target in
                        Button {
                            requestMove(target)
                        } label: {
                            Label(target == .waiting ? "\(target.title)…" : target.title, systemImage: target.symbolName)
                        }
                    }
                } label: {
                    Label("Move to…", systemImage: "arrow.right.circle")
                }
                Button(action: complete) {
                    Label("Complete", systemImage: "checkmark.circle")
                }
                Button(action: cancel) {
                    Label("Cancel task", systemImage: "xmark.circle")
                }
            }
        } else {
            Section("Status") {
                Label(terminalLine, systemImage: terminalSymbol)
                if let previous = task.lastOpenList {
                    Text("Previously in \(previous.title)")
                        .foregroundStyle(.secondary)
                }
                Button {
                    isReopening = true
                } label: {
                    Label("Reopen…", systemImage: "arrow.uturn.backward.circle")
                }
            }
        }
    }

    private var waitingSection: some View {
        Section {
            TextField("Who or what are you waiting on?", text: $waitingFor, axis: .vertical)
                .lineLimit(1...4)
                .focused($focus, equals: .waitingFor)
                .submitLabel(.done)
                .onSubmit { focus = nil }
                .onChange(of: waitingFor) { _, newValue in
                    if newValue.contains(where: \.isNewline) {
                        waitingFor = newValue.split(whereSeparator: \.isNewline).joined(separator: " ")
                        focus = nil
                    }
                }
                .accessibilityLabel("Waiting for")
        } header: {
            Text("Waiting for")
        } footer: {
            if let message = message(for: .waitingFor) {
                InlineProblemText(message: message)
            } else if let since = task.waitingSince {
                Text("Waiting since \(since.formatted(date: .abbreviated, time: .omitted))")
            }
        }
    }

    private var notesSection: some View {
        Section {
            if isReadOnly {
                if let details = task.details, !details.isEmpty {
                    Text(details)
                        .textSelection(.enabled)
                } else {
                    Text("No notes")
                        .foregroundStyle(.secondary)
                }
            } else {
                TextField("Notes, links, details…", text: $notes, axis: .vertical)
                    .lineLimit(3...)
                    .focused($focus, equals: .notes)
                    .accessibilityLabel("Notes")
            }
        } header: {
            Text("Notes")
        } footer: {
            problemText(for: .notes)
        }
    }

    private var organizeSection: some View {
        Section {
            DueDateQuickPicker(day: task.dueDate, today: workspace.today, isDisabled: isReadOnly) { day in
                guard day != task.dueDate else { return }
                save(.organize, TaskChanges(dueDate: setOrClear(day)))
            }
            Picker(selection: $priority) {
                ForEach(TaskPriority.allCases, id: \.self) { priority in
                    Text(priority.title).tag(priority)
                }
            } label: {
                Label("Priority", systemImage: "flag")
            }
            .disabled(isReadOnly)
            Picker(selection: $projectID) {
                Text("No project").tag(ProjectID?.none)
                ForEach(workspace.projects()) { summary in
                    Text(summary.project.name).tag(Optional(summary.id))
                }
                if let archived = archivedProject {
                    // Shown so the current value reads correctly; it cannot be
                    // chosen again because archived projects take no tasks.
                    Text("\(archived.name) (archived)").tag(Optional(archived.id))
                }
            } label: {
                Label("Project", systemImage: "folder")
            }
            .disabled(isReadOnly)
        } footer: {
            problemText(for: .organize)
        }
    }

    private var tagsSection: some View {
        Section {
            if task.tagIDs.isEmpty {
                Text("No tags")
                    .foregroundStyle(.secondary)
            } else {
                WrappingChipLayout(spacing: 6) {
                    ForEach(task.tagIDs, id: \.self) { tagID in
                        if let tag = workspace.tag(tagID) {
                            TagPill(name: tag.name)
                        }
                    }
                }
                .padding(.vertical, 4)
                .accessibilityElement(children: .combine)
                .accessibilityLabel("Tags: \(tagNames.joined(separator: ", "))")
            }
            if !isReadOnly {
                Button {
                    isEditingTags = true
                } label: {
                    Label("Edit tags", systemImage: "tag")
                }
            }
        } header: {
            Text("Tags")
        } footer: {
            problemText(for: .tags)
        }
    }

    private var metadataSection: some View {
        Section {
            LabeledContent("Created", value: task.createdAt.formatted(date: .abbreviated, time: .shortened))
            LabeledContent("Updated", value: task.updatedAt.formatted(.relative(presentation: .named)))
            if task.serverID == nil {
                Label(
                    workspace.account == nil ? "Saved on this device" : "Not synced yet",
                    systemImage: "arrow.triangle.2.circlepath"
                )
                .foregroundStyle(.secondary)
            }
        }
        .font(.footnote)
    }

    // MARK: Derived values

    private var terminalLine: String {
        let state = task.state == .cancelled ? "Cancelled" : "Completed"
        guard let date = task.state == .cancelled ? task.cancelledAt : task.completedAt else { return state }
        return "\(state) \(date.formatted(date: .abbreviated, time: .shortened))"
    }

    private var terminalSymbol: String {
        task.state == .cancelled ? HistoryKind.cancelled.symbolName : HistoryKind.completed.symbolName
    }

    private var tagNames: [String] {
        task.tagIDs.compactMap { workspace.tag($0)?.name }
    }

    private var archivedProject: ProjectRecord? {
        guard let id = task.projectID, let project = workspace.project(id), project.state == .archived else {
            return nil
        }
        return project
    }

    @ViewBuilder private func problemText(for field: DetailField) -> some View {
        if let message = message(for: field) {
            InlineProblemText(message: message)
        }
    }

    private func message(for field: DetailField) -> String? {
        problem?.field == field ? problem?.message : nil
    }

    // MARK: Saving

    private func commit(_ field: DetailField) {
        switch field {
        case .title: commitTitle()
        case .notes: commitNotes()
        case .waitingFor: commitWaitingFor()
        case .organize, .tags: break
        }
    }

    private func commitAll() {
        commitTitle()
        commitNotes()
        commitWaitingFor()
    }

    private func commitTitle() {
        guard task.isOpen else { return }
        let trimmed = title.trimmingCharacters(in: .whitespacesAndNewlines)
        if trimmed == task.title {
            title = task.title
            return
        }
        if trimmed.isEmpty {
            title = task.title
            problem = DetailProblem(field: .title, message: "A task needs a title, so the previous one was kept.")
            return
        }
        if save(.title, TaskChanges(title: .set(trimmed))) { title = trimmed }
    }

    private func commitNotes() {
        guard task.isOpen, notes != (task.details ?? "") else { return }
        if notes.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            if task.details == nil {
                notes = ""
            } else if save(.notes, TaskChanges(details: .clear)) {
                notes = ""
            }
        } else {
            save(.notes, TaskChanges(details: .set(notes)))
        }
    }

    private func commitWaitingFor() {
        guard task.state == .waiting else { return }
        let stored = task.waitingFor ?? ""
        let trimmed = waitingFor.trimmingCharacters(in: .whitespacesAndNewlines)
        if trimmed == stored {
            waitingFor = stored
            return
        }
        if trimmed.isEmpty {
            waitingFor = stored
            problem = DetailProblem(field: .waitingFor, message: GTDValidationError.waitingForRequired.message)
            return
        }
        if save(.waitingFor, TaskChanges(waitingFor: .set(trimmed))) { waitingFor = trimmed }
    }

    @discardableResult
    private func save(_ field: DetailField, _ changes: TaskChanges) -> Bool {
        do {
            try workspace.updateTask(task.id, changes)
            if problem?.field == field { problem = nil }
            return true
        } catch {
            problem = DetailProblem(field: field, message: error.message)
            return false
        }
    }

    // MARK: Transitions

    /// The task as stored right now, after any pending text edit was saved.
    private func committedTask() -> TaskRecord {
        commitAll()
        return workspace.task(task.id) ?? task
    }

    private func requestMove(_ list: OpenList) {
        if list == .waiting {
            commitAll()
            moveInitialList = .waiting
            isMoving = true
            return
        }
        let current = committedTask()
        _ = TaskCommandRunner.run(toasts) { () throws(GTDValidationError) in
            try TaskListMover.move(current, to: list, waitingFor: nil, workspace: workspace, toasts: toasts)
        }
    }

    private func complete() {
        TaskCommandRunner.complete(committedTask(), workspace: workspace, toasts: toasts)
    }

    private func cancel() {
        TaskCommandRunner.cancel(committedTask(), workspace: workspace, toasts: toasts)
    }
}

private func setOrClear<Value: Hashable & Sendable & Codable>(_ value: Value?) -> FieldChange<Value> {
    if let value { return .set(value) }
    return .clear
}

// MARK: - Shared controls

/// Due date quick picks shared by task detail and capture: Today, Tomorrow,
/// Next week, a calendar, and clear. The chosen day is reported through
/// `onChange`; nil clears the due date. Disabled (a completed or cancelled
/// task), the date is history rather than a deadline, so it is never shown
/// as overdue.
struct DueDateQuickPicker: View {
    private let day: CalendarDay?
    private let today: CalendarDay
    private let isDisabled: Bool
    private let onChange: (CalendarDay?) -> Void
    @State private var isShowingCalendar = false

    init(
        day: CalendarDay?, today: CalendarDay, isDisabled: Bool = false,
        onChange: @escaping (CalendarDay?) -> Void
    ) {
        self.day = day
        self.today = today
        self.isDisabled = isDisabled
        self.onChange = onChange
    }

    var body: some View {
        LabeledContent {
            Menu {
                Button("Today") { choose(today) }
                Button("Tomorrow") { choose(today.adding(days: 1)) }
                Button("Next week") { choose(today.adding(days: 7)) }
                Button("Pick a date…") { isShowingCalendar = true }
                if day != nil {
                    Divider()
                    Button("Clear due date", role: .destructive) { choose(nil) }
                }
            } label: {
                if let day {
                    DueChip(day: day, today: today, isDeadlineActive: !isDisabled)
                } else {
                    Text("Add date")
                }
            }
            .frame(minHeight: 44)
            .disabled(isDisabled)
            .accessibilityLabel("Due date")
            .accessibilityValue(day.map(Self.spokenDay) ?? "None")
        } label: {
            Label("Due date", systemImage: "calendar")
        }
        if isShowingCalendar && !isDisabled {
            DueDateCalendar(initialDate: (day ?? today).startDate()) { picked in
                choose(picked)
            }
        }
    }

    private func choose(_ newDay: CalendarDay?) {
        isShowingCalendar = false
        onChange(newDay)
    }

    private static func spokenDay(_ day: CalendarDay) -> String {
        day.startDate().formatted(date: .complete, time: .omitted)
    }
}

/// A calendar that reports the day the person taps. It owns its selection
/// (seeded when it appears), so only a real choice is reported.
private struct DueDateCalendar: View {
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

/// Multi-select of active tags for one task, with inline tag creation.
/// Every choice saves at once, like the rest of task detail.
struct TaskTagsSheet: View {
    private let taskID: TaskID

    @Environment(Workspace.self) private var workspace
    @Environment(\.dismiss) private var dismiss
    @State private var newTagName = ""
    @State private var errorMessage: String?

    init(taskID: TaskID) {
        self.taskID = taskID
    }

    var body: some View {
        NavigationStack {
            List {
                Section {
                    HStack {
                        TextField("New tag", text: $newTagName)
                            .textInputAutocapitalization(.never)
                            .autocorrectionDisabled()
                            .submitLabel(.done)
                            .onSubmit(createTag)
                        Button("Add", action: createTag)
                            .buttonStyle(.borderless)
                            .frame(minWidth: 44, minHeight: 44)
                            .disabled(trimmedNewName.isEmpty)
                    }
                } footer: {
                    if let errorMessage {
                        InlineProblemText(message: errorMessage)
                    } else {
                        Text("Tags group tasks by where or how you do them, like calls or errands.")
                    }
                }
                Section("Tags") {
                    ForEach(workspace.tags()) { summary in
                        tagRow(summary.tag)
                    }
                }
            }
            .navigationTitle("Tags")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Done") { dismiss() }
                }
            }
        }
        .presentationDetents([.medium, .large])
    }

    private var trimmedNewName: String {
        newTagName.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private var selectedIDs: [TagID] {
        workspace.task(taskID)?.tagIDs ?? []
    }

    private func tagRow(_ tag: TagRecord) -> some View {
        let isSelected = selectedIDs.contains(tag.id)
        return Button {
            toggle(tag.id)
        } label: {
            HStack {
                Text(tag.name)
                    .foregroundStyle(Color.primary)
                Spacer()
                if isSelected {
                    Image(systemName: "checkmark")
                        .foregroundStyle(.tint)
                        .accessibilityHidden(true)
                }
            }
            .frame(minHeight: 44)
            .contentShape(Rectangle())
        }
        .accessibilityAddTraits(isSelected ? .isSelected : [])
    }

    private func toggle(_ id: TagID) {
        var ids = selectedIDs
        if let index = ids.firstIndex(of: id) {
            ids.remove(at: index)
        } else {
            ids.append(id)
        }
        apply(ids)
    }

    private func apply(_ ids: [TagID]) {
        do {
            try workspace.updateTask(taskID, TaskChanges(tagIDs: .set(ids)))
            errorMessage = nil
        } catch {
            errorMessage = error.message
        }
    }

    /// Adds the typed tag, reusing an active tag with the same name.
    private func createTag() {
        let name = trimmedNewName
        guard !name.isEmpty else { return }
        let key = NameNormalizer.tag(name)
        if let existing = workspace.tags().first(where: { NameNormalizer.tag($0.tag.name) == key }) {
            if !selectedIDs.contains(existing.id) { apply(selectedIDs + [existing.id]) }
            newTagName = ""
            return
        }
        do {
            let id = try workspace.createTag(name: name)
            newTagName = ""
            apply(selectedIDs + [id])
        } catch {
            errorMessage = error.message
        }
    }
}

/// Lays chips out in rows, wrapping to the next row when one is full. Used for
/// tag pills and capture preview chips so they grow with Dynamic Type.
struct WrappingChipLayout: Layout {
    var spacing: CGFloat = 6

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        arrange(maxWidth: proposal.width ?? .infinity, subviews: subviews).size
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        let arrangement = arrange(maxWidth: bounds.width, subviews: subviews)
        for (index, subview) in subviews.enumerated() {
            let origin = arrangement.origins[index]
            subview.place(
                at: CGPoint(x: bounds.minX + origin.x, y: bounds.minY + origin.y),
                proposal: ProposedViewSize(arrangement.sizes[index])
            )
        }
    }

    private func arrange(maxWidth: CGFloat, subviews: Subviews) -> (size: CGSize, origins: [CGPoint], sizes: [CGSize]) {
        var origins: [CGPoint] = []
        var sizes: [CGSize] = []
        var x: CGFloat = 0
        var y: CGFloat = 0
        var rowHeight: CGFloat = 0
        var widest: CGFloat = 0
        for subview in subviews {
            var size = subview.sizeThatFits(.unspecified)
            size.width = min(size.width, maxWidth)
            if x > 0, x + size.width > maxWidth {
                x = 0
                y += rowHeight + spacing
                rowHeight = 0
            }
            origins.append(CGPoint(x: x, y: y))
            sizes.append(size)
            x += size.width + spacing
            rowHeight = max(rowHeight, size.height)
            widest = max(widest, x - spacing)
        }
        return (CGSize(width: widest, height: y + rowHeight), origins, sizes)
    }
}
