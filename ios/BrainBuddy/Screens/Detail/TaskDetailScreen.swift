import BrainBuddyCore
import BrainBuddyWorkspace
import SwiftUI

private func taskIdentityReads(_ task: TaskRecord) -> [WorkspaceRecordRead] {
    var reads: [WorkspaceRecordRead] = []
    if let id = task.projectID { reads.append(.project(id)) }
    for id in task.tagIDs where !reads.contains(.tag(id)) { reads.append(.tag(id)) }
    return reads
}

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
        let page = workspace.taskDetailPageState(taskID)
        let task = workspace.taskDetail(taskID)
        let reads = task.map(taskIdentityReads) ?? []
        let projectReadiness = workspace.projectsReadiness()
        let catalogReadiness = projectReadiness == .ready ? workspace.tagsReadiness() : projectReadiness
        let detailReadiness = readiness(page: page, catalog: catalogReadiness, reads: reads)
        Group {
            WorkspaceQueryContent(readiness: detailReadiness, retry: {
                Task {
                    await workspace.prepareTaskDetail(taskID)
                    await workspace.prepareProjects()
                    await workspace.prepareTags()
                    if let task = workspace.taskDetail(taskID) {
                        let reads = taskIdentityReads(task)
                        if !reads.isEmpty { _ = try? await workspace.prepareRecords(reads) }
                    }
                }
            }) {
                if let task {
                    TaskDetailForm(task: task)
                        .id(task.id)
                } else {
                    missingTask
                }
            }
        }
        .task(id: taskID) {
            await workspace.prepareTaskDetail(taskID)
            await workspace.prepareProjects()
            await workspace.prepareTags()
        }
        .task(id: reads) { if !reads.isEmpty { _ = try? await workspace.prepareRecords(reads) } }
        .safeAreaInset(edge: .bottom) {
            WorkspaceQueryPageControls(page: page,
                previous: { await workspace.previousTaskDetailPage(taskID) },
                next: { await workspace.nextTaskDetailPage(taskID) })
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

    private func readiness(page: WorkspaceQueryPageState, catalog: WorkspaceQueryReadiness, reads: [WorkspaceRecordRead]) -> WorkspaceQueryReadiness {
        if page.readiness != .ready { return page.readiness }
        if workspace.isRustSelected && catalog != .ready { return catalog }
        if !reads.isEmpty && workspace.isRustSelected { return workspace.recordsReadiness(reads) }
        return .ready
    }
}

private enum DetailField: String, Hashable {
    case title, notes, waitingFor, priority, project, dueDate, tags
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
    @State private var problems: [DetailField: String] = [:]
    @State private var editorID = UUID().uuidString
    @State private var isSaving = false
    @State private var saveTail: Task<Bool, Never>?
    @State private var saveToken = UUID()
    @State private var pendingSaves: [TaskChanges: Task<Bool, Never>] = [:]
    @State private var isTransitioning = false
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
                if let previous { Task { await commit(previous) } }
            }
            .onChange(of: priority) { _, newValue in
                guard newValue != task.priority else { return }
                Task { await save(.priority, TaskChanges(priority: .set(newValue))) }
            }
            .onChange(of: projectID) { _, newValue in
                guard newValue != task.projectID else { return }
                Task { await save(.project, TaskChanges(projectID: setOrClear(newValue))) }
            }
            .onChange(of: scenePhase) { _, phase in
                if phase != .active { Task { await commitAll() } }
            }
            .onDisappear { Task { await commitAll() } }
    }

    /// Follows changes elsewhere only when they do not replace an authored draft.
    private var syncedForm: some View {
        form
            .navigationTitle(navigationTitle)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { toolbarContent }
            .onChange(of: task.title) { oldValue, newValue in
                if focus != .title && title == oldValue && problems[.title] == nil { title = newValue }
            }
            .onChange(of: task.details) { oldValue, newValue in
                if focus != .notes && notes == (oldValue ?? "") && problems[.notes] == nil { notes = newValue ?? "" }
            }
            .onChange(of: task.waitingFor) { oldValue, newValue in
                if focus != .waitingFor && waitingFor == (oldValue ?? "") && problems[.waitingFor] == nil { waitingFor = newValue ?? "" }
            }
            .onChange(of: task.priority) { oldValue, newValue in
                if priority == oldValue && problems[.priority] == nil { priority = newValue }
            }
            .onChange(of: task.projectID) { oldValue, newValue in
                if projectID == oldValue && problems[.project] == nil { projectID = newValue }
            }
    }

    private var form: some View {
        let projectPage = workspace.projectsPageState()
        return Form {
            titleSection
                .disabled(isSaving || isTransitioning)
            // Spec 020, M-02: the wording's age and "Decide" (only while exposed).
            FormulationSection(task: task) {
                // Leave the field first: a title still focused under the card
                // would be committed later with its old text and overwrite
                // the card's new wording (the field only follows the stored
                // title while it is not being edited).
                focus = nil
                Task {
                    if await commitAll() { isDeciding = true }
                }
            }
            .disabled(isSaving || isTransitioning)
            propertiesSection
                .disabled(isSaving || isTransitioning)
            SubtasksSection(task: task, isReadOnly: isReadOnly)
            CommentsSection(task: task, isReadOnly: isReadOnly)
            metadataSection
        }
        .bbDenseList()
        .safeAreaInset(edge: .bottom) {
            WorkspaceQueryPageControls(page: projectPage,
                previous: { await workspace.previousProjectsPage() },
                next: { await workspace.nextProjectsPage() })
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
                .disabled(isSaving || isTransitioning)
            } else {
                Button {
                    isReopening = true
                } label: {
                    Label("Reopen", systemImage: "arrow.uturn.backward.circle")
                }
            }
        }
        ToolbarItem(placement: .primaryAction) {
            Menu {
                moreMenuContent
            } label: {
                Label("More", systemImage: "ellipsis.circle")
            }
            .accessibilityLabel("More actions")
            .disabled(isSaving || isTransitioning)
        }
        ToolbarItemGroup(placement: .keyboard) {
            Spacer()
            Button("Done") { focus = nil }
        }
    }

    // MARK: Sections

    /// Title and notes together, as one card.
    private var titleSection: some View {
        Section {
            titleField
            notesField
        } footer: {
            problemFooter(.title, .notes)
        }
    }

    @ViewBuilder private var titleField: some View {
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
    }

    @ViewBuilder private var notesField: some View {
        if isReadOnly {
            if let details = task.details, !details.isEmpty {
                Text(details)
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
                    .textSelection(.enabled)
            } else {
                Text("No notes")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
            }
        } else {
            TextField("Notes, links, details…", text: $notes, axis: .vertical)
                .font(.subheadline)
                .foregroundStyle(.secondary)
                .lineLimit(1...)
                .focused($focus, equals: .notes)
                .accessibilityLabel("Notes")
        }
    }

    // MARK: Properties

    /// Every property on its own 44 pt row: list, waiting for, project, due
    /// date, priority and tags.
    private var propertiesSection: some View {
        Section {
            listRow
            if task.state == .waiting {
                waitingRow
            }
            projectRow
            DueDateQuickPicker(day: task.dueDate, today: workspace.today, isDisabled: isReadOnly) { day in
                guard day != task.dueDate else { return }
                Task { await save(.dueDate, TaskChanges(dueDate: setOrClear(day))) }
            }
            .labelStyle(.bbRow)
            priorityRow
            tagsRow
        } footer: {
            propertiesFooter
        }
    }

    /// The current list with a menu to move the task, or for a finished task
    /// the read-only status line.
    @ViewBuilder private var listRow: some View {
        if let list = task.openList {
            LabeledContent {
                Menu {
                    moveMenuItems(from: list)
                } label: {
                    HStack(spacing: 4) {
                        Text(list.title)
                        Image(systemName: "chevron.up.chevron.down")
                            .font(.caption2)
                            .accessibilityHidden(true)
                    }
                }
                .frame(minHeight: BBMetrics.rowMinHeight)
                .accessibilityLabel("List")
                .accessibilityValue(list.title)
                .accessibilityHint("Moves the task to another list.")
            } label: {
                Label("List", systemImage: list.symbolName)
                    .labelStyle(.bbRow)
            }
        } else {
            Label {
                VStack(alignment: .leading, spacing: 2) {
                    Text(terminalLine)
                    if let previous = task.lastOpenList {
                        Text("Previously in \(previous.title)")
                            .font(.footnote)
                            .foregroundStyle(.secondary)
                    }
                }
            } icon: {
                Image(systemName: terminalSymbol)
            }
            .labelStyle(.bbRow)
            .accessibilityElement(children: .combine)
        }
    }

    private var waitingRow: some View {
        Label {
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
        } icon: {
            Image(systemName: "clock")
                .accessibilityHidden(true)
        }
        .labelStyle(.bbRow)
    }

    private var projectRow: some View {
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
                .labelStyle(.bbRow)
        }
        .disabled(isReadOnly)
    }

    private var priorityRow: some View {
        Picker(selection: $priority) {
            ForEach(TaskPriority.allCases, id: \.self) { priority in
                Text(priority.title).tag(priority)
            }
        } label: {
            Label("Priority", systemImage: "flag")
                .labelStyle(.bbRow)
        }
        .disabled(isReadOnly)
    }

    /// Tag pills trailing in the row; tapping it opens the tag sheet while the
    /// task is editable.
    @ViewBuilder private var tagsRow: some View {
        if isReadOnly {
            tagsRowContent
                .accessibilityElement(children: .ignore)
                .accessibilityLabel("Tags")
                .accessibilityValue(tagsSpokenValue)
        } else {
            Button {
                isEditingTags = true
            } label: {
                tagsRowContent
                    .contentShape(Rectangle())
            }
            .accessibilityLabel("Tags")
            .accessibilityValue(tagsSpokenValue)
            .accessibilityHint("Opens the tag picker.")
        }
    }

    private var tagsRowContent: some View {
        HStack(alignment: .center, spacing: BBSpacing.s3) {
            Label("Tags", systemImage: "tag")
                .labelStyle(.bbRow)
                .foregroundStyle(Color.primary)
                .fixedSize(horizontal: true, vertical: false)
            Group {
                if task.tagIDs.isEmpty {
                    Text("No tags")
                        .foregroundStyle(.secondary)
                } else {
                    WrappingChipLayout(spacing: 6) {
                        ForEach(task.tagIDs, id: \.self) { tagID in
                            if let tag = tagRecord(tagID) {
                                TagPill(name: tag.name)
                            }
                        }
                    }
                }
            }
            .frame(maxWidth: .infinity, alignment: .trailing)
        }
        .frame(minHeight: BBMetrics.rowMinHeight)
    }

    /// The waiting-since line and any rejected property change, under the section.
    @ViewBuilder private var propertiesFooter: some View {
        let isWaiting = task.state == .waiting
        let propertyFields: [DetailField] = [.project, .dueDate, .priority, .tags]
        let fields: [DetailField] = isWaiting ? [.waitingFor] + propertyFields : propertyFields
        let messages = fields.compactMap { message(for: $0) }
        let since = isWaiting && message(for: .waitingFor) == nil ? task.waitingSince : nil
        if !messages.isEmpty || since != nil {
            VStack(alignment: .leading, spacing: 4) {
                ForEach(fields, id: \.self) { field in
                    if let message = message(for: field) {
                        InlineProblemText(message: message)
                    }
                }
                if let since {
                    Text("Waiting since \(since.formatted(date: .abbreviated, time: .omitted))")
                }
            }
        }
    }

    // MARK: Actions menu

    /// Everything the toolbar's primary button does not cover: moving, cancelling
    /// and (for a finished task) reopening.
    @ViewBuilder private var moreMenuContent: some View {
        if let list = task.openList {
            Menu {
                moveMenuItems(from: list)
            } label: {
                Label("Move to…", systemImage: "arrow.right.circle")
            }
            Button(action: cancel) {
                Label("Cancel task", systemImage: "xmark.circle")
            }
        } else {
            Button {
                isReopening = true
            } label: {
                Label("Reopen…", systemImage: "arrow.uturn.backward.circle")
            }
        }
    }

    /// The lists a task can move to from `list`; Waiting asks who or what first.
    @ViewBuilder private func moveMenuItems(from list: OpenList) -> some View {
        ForEach(OpenList.allCases.filter { $0 != list }) { target in
            Button {
                requestMove(target)
            } label: {
                Label(target == .waiting ? "\(target.title)…" : target.title, systemImage: target.symbolName)
            }
        }
    }

    // MARK: Metadata

    /// One quiet line instead of a Created and an Updated row.
    private var metadataSection: some View {
        Section {
            Text(metadataLine)
                .font(.footnote)
                .foregroundStyle(.secondary)
                .listRowBackground(Color.clear)
                .listRowSeparator(.hidden)
        }
    }

    private var metadataLine: String {
        var parts = [
            "Created \(task.createdAt.formatted(date: .abbreviated, time: .shortened))",
            "Updated \(task.updatedAt.formatted(.relative(presentation: .named)))",
        ]
        if task.serverID == nil {
            parts.append(workspace.account == nil ? "Saved on this device" : "Not synced yet")
        }
        return parts.joined(separator: " · ")
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

    private var tagsSpokenValue: String {
        let names = task.tagIDs.compactMap { tagRecord($0)?.name }
        return names.isEmpty ? "None" : names.joined(separator: ", ")
    }

    private var archivedProject: ProjectRecord? {
        guard let id = task.projectID, let project = projectRecord(id), project.state == .archived else {
            return nil
        }
        return project
    }

    private var exactRecords: WorkspaceRecordPage? {
        guard workspace.isRustSelected else { return nil }
        return workspace.records(taskIdentityReads(task))
    }

    private func tagRecord(_ id: TagID) -> TagRecord? {
        workspace.isRustSelected ? exactRecords?.tags[id] : workspace.tag(id)
    }

    private func projectRecord(_ id: ProjectID) -> ProjectRecord? {
        workspace.isRustSelected ? exactRecords?.projects[id] : workspace.project(id)
    }

    /// The rejected-change messages for `fields`, stacked; nothing when there are none.
    @ViewBuilder private func problemFooter(_ fields: DetailField...) -> some View {
        let messages = fields.compactMap { message(for: $0) }
        if !messages.isEmpty {
            VStack(alignment: .leading, spacing: 4) {
                ForEach(fields, id: \.self) { field in
                    if let text = message(for: field) {
                        InlineProblemText(message: text)
                    }
                }
            }
        }
    }

    private func message(for field: DetailField) -> String? {
        problems[field]
    }

    // MARK: Saving

    @MainActor private func commit(_ field: DetailField) async {
        switch field {
        case .title: _ = await commitTitle()
        case .notes: _ = await commitNotes()
        case .waitingFor: _ = await commitWaitingFor()
        case .priority, .project, .dueDate, .tags: break
        }
    }

    @MainActor private func commitAll() async -> Bool {
        if let saveTail, !(await saveTail.value) { return false }
        let titleSaved = await commitTitle()
        let notesSaved = await commitNotes()
        let waitingSaved = await commitWaitingFor()
        let propertiesSaved = await commitProperties()
        return titleSaved && notesSaved && waitingSaved && propertiesSaved
    }

    @MainActor private func commitTitle() async -> Bool {
        let task = workspace.taskDetail(self.task.id) ?? self.task
        guard task.isOpen else { return true }
        let trimmed = title.trimmingCharacters(in: .whitespacesAndNewlines)
        if trimmed == task.title {
            title = task.title
            return true
        }
        if trimmed.isEmpty {
            title = task.title
            problems[.title] = "A task needs a title, so the previous one was kept."
            return false
        }
        return await save(.title, TaskChanges(title: .set(trimmed)))
    }

    @MainActor private func commitNotes() async -> Bool {
        let task = workspace.taskDetail(self.task.id) ?? self.task
        guard task.isOpen, notes != (task.details ?? "") else { return true }
        if notes.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            if task.details == nil {
                notes = ""
            } else if await save(.notes, TaskChanges(details: .clear)) {
                notes = ""
            } else { return false }
        } else {
            return await save(.notes, TaskChanges(details: .set(notes)))
        }
        return true
    }

    @MainActor private func commitWaitingFor() async -> Bool {
        let task = workspace.taskDetail(self.task.id) ?? self.task
        guard task.state == .waiting else { return true }
        let stored = task.waitingFor ?? ""
        let trimmed = waitingFor.trimmingCharacters(in: .whitespacesAndNewlines)
        if trimmed == stored {
            waitingFor = stored
            return true
        }
        if trimmed.isEmpty {
            waitingFor = stored
            problems[.waitingFor] = GTDValidationError.waitingForRequired.message
            return false
        }
        return await save(.waitingFor, TaskChanges(waitingFor: .set(trimmed)))
    }

    @MainActor private func commitProperties() async -> Bool {
        guard task.isOpen else { return true }
        var prioritySaved = true
        if priority != (workspace.taskDetail(task.id) ?? task).priority {
            prioritySaved = await save(.priority, TaskChanges(priority: .set(priority)))
        }
        var projectSaved = true
        if projectID != (workspace.taskDetail(task.id) ?? task).projectID {
            projectSaved = await save(.project, TaskChanges(projectID: setOrClear(projectID)))
        }
        return prioritySaved && projectSaved
    }

    @discardableResult
    @MainActor private func save(_ field: DetailField, _ changes: TaskChanges) async -> Bool {
        if let pending = pendingSaves[changes] { return await pending.value }
        // Focus loss and a picker selection can both arrive before busy UI renders.
        // Retain those accepted edits and write them in order, sharing exact retries.
        let previous = saveTail
        let submittedTaskID = task.id
        let submittedEditorID = editorID + ":" + field.rawValue
        let token = UUID()
        saveToken = token
        isSaving = true
        let saving = Task { @MainActor in
            if let previous { _ = await previous.value }
            do {
                try await workspace.updateTask(submittedTaskID, changes, editorID: submittedEditorID)
                problems[field] = nil
                return true
            } catch {
                problems[field] = TaskCommandRunner.message(for: error)
                return false
            }
        }
        pendingSaves[changes] = saving
        saveTail = saving
        let saved = await saving.value
        pendingSaves[changes] = nil
        if saveToken == token {
            saveTail = nil
            isSaving = false
        }
        return saved
    }

    // MARK: Transitions

    /// The task as stored right now, after any pending text edit was saved.
    private func requestMove(_ list: OpenList) {
        Task {
            guard !isTransitioning else { return }
            isTransitioning = true
            defer { isTransitioning = false }
            guard await commitAll() else { return }
            if list == .waiting { moveInitialList = .waiting; isMoving = true; return }
            _ = await TaskCommandRunner.run(toasts) { try await TaskListMover.move(task, to: list, waitingFor: nil, workspace: workspace, toasts: toasts, editorID: editorID) }
        }
    }

    private func complete() {
        Task {
            guard !isTransitioning else { return }
            isTransitioning = true
            defer { isTransitioning = false }
            guard await commitAll() else { return }
            _ = await TaskCommandRunner.complete(task, workspace: workspace, toasts: toasts, editorID: editorID)
        }
    }

    private func cancel() {
        Task {
            guard !isTransitioning else { return }
            isTransitioning = true
            defer { isTransitioning = false }
            guard await commitAll() else { return }
            _ = await TaskCommandRunner.cancel(task, workspace: workspace, toasts: toasts, editorID: editorID)
        }
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
    @State private var editorID = UUID().uuidString
    @State private var isSaving = false
    @State private var stagedIDs: [TagID]?

    init(taskID: TaskID) {
        self.taskID = taskID
    }

    var body: some View {
        let tagPage = workspace.tagsPageState()
        let taskReadiness = workspace.taskDetailReadiness(taskID)
        let readiness = taskReadiness == .ready ? tagPage.readiness : taskReadiness
        WorkspaceQueryContent(readiness: readiness, retry: {
            Task { await workspace.prepareTaskDetail(taskID); await workspace.prepareTags() }
        }) {
        NavigationStack {
            List {
                Section {
                    HStack {
                        TextField("New tag", text: $newTagName)
                            .disabled(isSaving)
                            .textInputAutocapitalization(.never)
                            .autocorrectionDisabled()
                            .submitLabel(.done)
                            .onSubmit { Task { await createTag() } }
                        Button("Add") { Task { await createTag() } }
                            .buttonStyle(.borderless)
                            .frame(minWidth: 44, minHeight: 44)
                            .disabled(trimmedNewName.isEmpty || isSaving)
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
        }
        .presentationDetents([.medium, .large])
        .safeAreaInset(edge: .bottom) {
            WorkspaceQueryPageControls(page: tagPage,
                previous: { await workspace.previousTagsPage() }, next: { await workspace.nextTagsPage() })
        }
        .task { await workspace.prepareTaskDetail(taskID); await workspace.prepareTags() }
    }

    private var trimmedNewName: String {
        newTagName.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private var selectedIDs: [TagID] {
        stagedIDs ?? (workspace.task(taskID)?.tagIDs ?? [])
    }

    private func tagRow(_ tag: TagRecord) -> some View {
        let isSelected = selectedIDs.contains(tag.id)
        return Button {
            Task { await toggle(tag.id) }
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
        .disabled(isSaving)
        .accessibilityAddTraits(isSelected ? .isSelected : [])
    }

    @MainActor private func toggle(_ id: TagID) async {
        guard !isSaving else { return }
        var ids = selectedIDs
        if let index = ids.firstIndex(of: id) {
            ids.remove(at: index)
        } else {
            ids.append(id)
        }
        await apply(ids)
    }

    @MainActor private func apply(_ ids: [TagID]) async -> Bool {
        guard !isSaving else { return false }
        stagedIDs = ids
        isSaving = true
        defer { isSaving = false }
        do {
            try await workspace.updateTask(taskID, TaskChanges(tagIDs: .set(ids)), editorID: editorID)
            errorMessage = nil
            return true
        } catch {
            errorMessage = TaskCommandRunner.message(for: error)
            return false
        }
    }

    /// Adds the typed tag, reusing an active tag with the same name.
    @MainActor private func createTag() async {
        let name = trimmedNewName
        guard !name.isEmpty, !isSaving else { return }
        let key = NameNormalizer.tag(name)
        if let existing = workspace.tags().first(where: { NameNormalizer.tag($0.tag.name) == key }) {
            if !selectedIDs.contains(existing.id), await apply(selectedIDs + [existing.id]) { newTagName = "" }
            return
        }
        isSaving = true
        defer { isSaving = false }
        do {
            let id = try await workspace.createTag(name: name, editorID: editorID)
            let submittedIDs = selectedIDs + [id]
            stagedIDs = submittedIDs
            try await workspace.updateTask(taskID, TaskChanges(tagIDs: .set(submittedIDs)), editorID: editorID)
            newTagName = ""
            errorMessage = nil
        } catch {
            errorMessage = TaskCommandRunner.message(for: error)
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
