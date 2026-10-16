import BrainBuddyCore
import BrainBuddyDesign
import BrainBuddyWorkspace
import SwiftUI

private func taskIdentityReads(_ task: TaskRecord) -> [WorkspaceRecordRead] {
    var reads: [WorkspaceRecordRead] = []
    if let id = task.projectID { reads.append(.project(id)) }
    for id in task.tagIDs where !reads.contains(.tag(id)) { reads.append(.tag(id)) }
    return reads
}

/// Task detail, the content of the task sheet (`TaskSheet`, boards 13 to 20).
///
/// **Layout.** An Inbox item keeps the detail it always had. Every other task
/// is a Carry On card: "Project · List" (or when it was done), the title, its
/// chips (project, due day, tags), the note ("Why" for a next action), the
/// steps inside (subtasks) and, below the medium detent, the properties,
/// comments and history. Waiting for leads with who it waits on and since
/// when; Someday / maybe says how to start it; a finished task is read-only.
///
/// **Bar.** A floating glass bar offers the board's actions for the task's
/// list, each an action the app already has: a next action's Done (complete)
/// and Not now (board 15: pick a day, move to Waiting for or Someday / maybe,
/// or change the step); Waiting for's Got it and Someday's Start it (move to
/// Next actions); Someday's Not needed (cancel); a finished task's Reopen…
/// (which asks where). The toolbar's menu keeps every other move, Complete
/// and Cancel task. Inbox items have no bar, as before.
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
    /// The sheet is at its large detent, so everything below the card shows.
    private let isExpanded: Bool

    @Environment(Workspace.self) private var workspace
    @Environment(AppRouter.self) private var router

    init(taskID: TaskID, isExpanded: Bool = true) {
        self.taskID = taskID
        self.isExpanded = isExpanded
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
                    TaskDetailForm(task: task, isExpanded: isExpanded)
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
                    // Sync issues is pushed on the tab under the sheet.
                    router.closeTask()
                    router.open(.syncIssues)
                }
                .buttonStyle(.bordered)
                .controlSize(.large)
            }
        }
        .padding()
        .navigationTitle("Task")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .cancellationAction) {
                TaskSheetCloseButton()
            }
        }
    }

    private func readiness(page: WorkspaceQueryPageState, catalog: WorkspaceQueryReadiness, reads: [WorkspaceRecordRead]) -> WorkspaceQueryReadiness {
        if page.readiness != .ready { return page.readiness }
        if workspace.isRustSelected && catalog != .ready { return catalog }
        if !reads.isEmpty && workspace.isRustSelected { return workspace.recordsReadiness(reads) }
        return .ready
    }
}

private enum DetailField: String, Hashable {
    case title, notes, waitingFor, project, dueDate, tags
}

private struct TaskDetailForm: View {
    let task: TaskRecord
    let isExpanded: Bool

    @Environment(Workspace.self) private var workspace
    @Environment(ToastCenter.self) private var toasts
    @Environment(\.scenePhase) private var scenePhase
    @State private var title: String
    @State private var notes: String
    @State private var waitingFor: String
    /// Picker selections mirror the stored values and save on change.
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
    /// Board 14, the due date picker.
    @State private var isPickingDate = false
    /// Board 15, "Not now", and what it chose; acted on once it has closed.
    @State private var isChoosingNotNow = false
    @State private var notNowChoice: NotNowChoice?
    @FocusState private var focus: DetailField?

    init(task: TaskRecord, isExpanded: Bool) {
        self.task = task
        self.isExpanded = isExpanded
        _title = State(initialValue: task.title)
        _notes = State(initialValue: task.details ?? "")
        _waitingFor = State(initialValue: task.waitingFor ?? "")
        _projectID = State(initialValue: task.projectID)
    }

    private var isReadOnly: Bool { !task.isOpen }

    /// Inbox items keep the detail they always had; every other task is the
    /// Carry On card.
    private var usesCard: Bool { task.state != .inbox }

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
            .sheet(isPresented: $isPickingDate) {
                DueDateSheet(taskTitle: task.title, day: task.dueDate, today: workspace.today) { day in
                    guard day != task.dueDate else { return }
                    Task { await save(.dueDate, TaskChanges(dueDate: setOrClear(day))) }
                }
            }
            .sheet(isPresented: $isChoosingNotNow, onDismiss: runNotNowChoice) {
                NotNowSheet(taskTitle: task.title) { choice in
                    notNowChoice = choice
                }
            }
    }

    /// Saves edits: text fields when they lose focus (or the screen closes or
    /// the app backgrounds), pickers as soon as the selection changes.
    private var savingForm: some View {
        syncedForm
            .onChange(of: focus) { previous, _ in
                if let previous { Task { await commit(previous) } }
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
            .onChange(of: task.projectID) { oldValue, newValue in
                if projectID == oldValue && problems[.project] == nil { projectID = newValue }
            }
    }

    private var form: some View {
        let projectPage = workspace.projectsPageState()
        return Form {
            if usesCard {
                cardSections
            } else {
                inboxSections
            }
        }
        .bbDenseList()
        .bbListBackground()
        .safeAreaInset(edge: .bottom) {
            WorkspaceQueryPageControls(page: projectPage,
                previous: { await workspace.previousProjectsPage() },
                next: { await workspace.nextProjectsPage() })
        }
        // Outermost, so the bar sits at the very bottom with the toasts just
        // above it, never over its buttons.
        .safeAreaInset(edge: .bottom, spacing: 0) {
            VStack(spacing: 0) {
                ToastHost()
                actionBar
            }
        }
    }

    /// The Inbox item's detail, as it has always been.
    @ViewBuilder private var inboxSections: some View {
        titleSection
            .disabled(isSaving || isTransitioning)
        formulationSection
        propertiesSection
            .disabled(isSaving || isTransitioning)
        SubtasksSection(task: task, isReadOnly: isReadOnly)
        CommentsSection(task: task, isReadOnly: isReadOnly)
        metadataSection
    }

    /// Spec 020, M-02: the wording's age and "Decide" (only while exposed).
    private var formulationSection: some View {
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
    }

    /// The Inbox keeps its list name as the title; the card names its list in
    /// its own first line, so the bar above it carries only the buttons.
    private var navigationTitle: String {
        task.state == .inbox ? OpenList.inbox.title : ""
    }

    /// Close, then Complete where the bar has no Done (Inbox, Waiting for,
    /// Someday / maybe) and the menu with every move and Cancel task. A
    /// finished task's only action, Reopen…, is in its bar.
    @ToolbarContentBuilder private var toolbarContent: some ToolbarContent {
        ToolbarItem(placement: .cancellationAction) {
            TaskSheetCloseButton()
        }
        if task.isOpen && task.state != .next {
            ToolbarItem(placement: .primaryAction) {
                Button(action: complete) {
                    Label("Complete", systemImage: "checkmark.circle")
                }
                .disabled(isSaving || isTransitioning)
            }
        }
        if task.isOpen {
            ToolbarItem(placement: .primaryAction) {
                Menu {
                    moreMenuContent
                } label: {
                    Label("More", systemImage: "ellipsis.circle")
                }
                .accessibilityLabel("More actions")
                .disabled(isSaving || isTransitioning)
            }
        }
        ToolbarItemGroup(placement: .keyboard) {
            Spacer()
            Button("Done") { focus = nil }
        }
    }

    // MARK: Bar

    /// The board's actions for the task's list, in a floating glass bar. Only
    /// what the row's own actions (`taskActions`) offer for this state: a move
    /// to a different open list, Complete or Cancel task while open, Reopen…
    /// once finished. The Inbox has no bar.
    @ViewBuilder private var actionBar: some View {
        switch task.state {
        case .next:
            BBGlassActionBar {
                barButton("Done", .primary, action: complete)
                barButton("Not now", .quiet) {
                    focus = nil
                    isChoosingNotNow = true
                }
            }
        case .waiting:
            BBGlassActionBar {
                barButton("Got it", .primary) { requestMove(.next) }
            }
        case .someday:
            BBGlassActionBar {
                barButton("Start it", .primary) { requestMove(.next) }
                barButton("Not needed", .quiet, action: cancel)
            }
        case .completed, .cancelled:
            BBGlassActionBar {
                barButton("Reopen…", .quiet) { isReopening = true }
            }
        case .inbox:
            EmptyView()
        }
    }

    private func barButton(
        _ title: String, _ kind: CarryOnButtonStyle.Kind, action: @escaping () -> Void
    ) -> some View {
        Button(action: action) {
            Text(title)
                .frame(maxWidth: .infinity)
        }
        .buttonStyle(CarryOnButtonStyle(kind))
        .disabled(isSaving || isTransitioning)
    }

    /// Acts on what "Not now" chose, once its sheet has gone.
    private func runNotNowChoice() {
        guard let choice = notNowChoice else { return }
        notNowChoice = nil
        switch choice {
        case .pickDay: isPickingDate = true
        case .waiting: requestMove(.waiting)
        case .someday: requestMove(.someday)
        case .changeStep: focus = .title
        }
    }

    // MARK: Card (boards 13, 18, 19, 20)

    @ViewBuilder private var cardSections: some View {
        cardHeaderSection
            .disabled(isSaving || isTransitioning)
        formulationSection
        noteSection
            .disabled(isSaving || isTransitioning)
        if task.state == .someday {
            cardTextRow("Ready to start? Start it and it moves to Next actions.", isQuiet: false)
        }
        if !chipsFollowTitle {
            chipsSection
        }
        SubtasksSection(task: task, isReadOnly: isReadOnly, title: "Steps inside")
        if isReadOnly {
            cardTextRow("Finished steps are read-only.", isQuiet: true)
        }
        if !isExpanded {
            cardTextRow("Pull up for notes and comments", isQuiet: true)
        }
        propertiesSection
            .disabled(isSaving || isTransitioning)
        CommentsSection(task: task, isReadOnly: isReadOnly)
        metadataSection
    }

    /// Next actions and finished tasks show their chips under the title;
    /// Waiting for and Someday / maybe under the note (boards 18, 19).
    private var chipsFollowTitle: Bool {
        task.state != .waiting && task.state != .someday
    }

    /// "Project · List", the title, who a waiting task waits on, and the chips
    /// where they follow the title. Flat on the sheet, no card behind it.
    private var cardHeaderSection: some View {
        Section {
            VStack(alignment: .leading, spacing: CGFloat(CarryOnSpace.xs)) {
                contextLine
                cardTitle
                if task.state == .waiting {
                    waitingCard
                        .padding(.top, CGFloat(CarryOnSpace.xs))
                }
                if chipsFollowTitle {
                    chipsRow
                        .padding(.top, CGFloat(CarryOnSpace.xxs))
                }
            }
            .listRowBackground(Color.clear)
            .listRowSeparator(.hidden)
        } footer: {
            problemFooter(.title, .waitingFor)
        }
    }

    /// Board 13's first line: the project's dot and name, then where the task
    /// is ("Next actions", "Waiting for", "Someday", "Done on Monday").
    private var contextLine: some View {
        let project = task.projectID.flatMap { projectRecord($0) }
        let parts = [project?.name, stateWords].compactMap { $0 }
        return HStack(spacing: CGFloat(CarryOnSpace.xs)) {
            if let project {
                CarryOnProjectDot(BBColor.projectRGB(project.color))
                    .accessibilityHidden(true)
            }
            Text(parts.joined(separator: " · "))
        }
        .carryOnText(CarryOnTypeScale.meta)
        .foregroundStyle(.coTextSecondary)
        .accessibilityElement(children: .combine)
        .accessibilityAddTraits(.isHeader)
    }

    /// Where the task is, in the card's first line.
    private var stateWords: String {
        switch task.state {
        case .inbox: OpenList.inbox.title
        case .next: OpenList.next.title
        case .waiting: OpenList.waiting.title
        case .someday: "Someday"
        case .completed: terminalPhrase(word: "Done", at: task.completedAt)
        case .cancelled: terminalPhrase(word: "Cancelled", at: task.cancelledAt)
        }
    }

    /// "Done today", "Done yesterday", "Done on Monday", "Done on October 3";
    /// the word alone when the time is unknown.
    private func terminalPhrase(word: String, at date: Date?) -> String {
        guard let date else { return word }
        switch BBDayMath.offset(from: CalendarDay(date: date), to: workspace.today) {
        case ...0: return "\(word) today"
        case 1: return "\(word) yesterday"
        case 2...6: return "\(word) on \(date.formatted(.dateTime.weekday(.wide)))"
        default: return "\(word) on \(date.formatted(.dateTime.month(.wide).day()))"
        }
    }

    /// The step in the board's 24 pt step type (Someday's idea in the serif
    /// title); struck through once finished.
    @ViewBuilder private var cardTitle: some View {
        let style = task.state == .someday ? CarryOnTypeScale.title : CarryOnTypeScale.step
        if isReadOnly {
            Text(task.title)
                .strikethrough(true, color: BBColor.stepTextDone)
                .carryOnText(style)
                .foregroundStyle(BBColor.stepTextDone)
                .textSelection(.enabled)
        } else {
            titleTextField
                .carryOnFont(style)
                .foregroundStyle(.coTextPrimary)
        }
    }

    /// Board 18: who the task waits on, editable, and since when.
    private var waitingCard: some View {
        HStack(spacing: CGFloat(CarryOnLayout.Row.gap)) {
            CarryOnStepMark(.waiting)
                .accessibilityHidden(true)
            VStack(alignment: .leading, spacing: CGFloat(CarryOnLayout.Row.metaGap)) {
                waitingForTextField
                    .carryOnFont(CarryOnTypeScale.bodyStrong)
                    .foregroundStyle(.coTextPrimary)
                if let asked = askedLine {
                    Text(asked)
                        .carryOnText(CarryOnTypeScale.meta)
                        .foregroundStyle(.coTextSecondary)
                }
            }
        }
        .padding(CGFloat(CarryOnSpace.md))
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(.coSurfaceCard, in: RoundedRectangle(cornerRadius: CGFloat(CarryOnRadius.md), style: .continuous))
    }

    /// "Asked 3 days ago", from when the task entered Waiting for.
    private var askedLine: String? {
        guard let since = task.waitingSince else { return nil }
        let days = BBDayMath.offset(from: CalendarDay(date: since), to: workspace.today)
        switch days {
        case ...0: return "Asked today"
        case 1: return "Asked yesterday"
        default: return "Asked \(days) days ago"
        }
    }

    /// The note: "Why" for a next action, "Note" elsewhere. Editable while
    /// open; a finished task's note is quiet text, and none is shown when
    /// there is no note.
    @ViewBuilder private var noteSection: some View {
        let header = task.state == .next ? "Why" : "Note"
        if isReadOnly {
            if let details = task.details, !details.isEmpty {
                Section {
                    Text(details)
                        .carryOnText(CarryOnTypeScale.body)
                        .foregroundStyle(.coTextSecondary)
                        .textSelection(.enabled)
                } header: {
                    BBSectionHeader(header)
                }
            }
        } else {
            Section {
                TextField("Notes, links, details…", text: $notes, axis: .vertical)
                    .carryOnFont(CarryOnTypeScale.body)
                    .lineLimit(1...)
                    .focused($focus, equals: .notes)
                    .accessibilityLabel(header)
            } header: {
                BBSectionHeader(header)
            } footer: {
                problemFooter(.notes)
            }
        }
    }

    /// The chips as their own flat row (Waiting for, Someday / maybe).
    @ViewBuilder private var chipsSection: some View {
        if !chipItems.isEmpty {
            Section {
                chipsRow
                    .listRowBackground(Color.clear)
                    .listRowSeparator(.hidden)
            }
        }
    }

    /// Project, due day and tags as Carry On chips; read as one line by
    /// VoiceOver. They show what the property rows below edit.
    @ViewBuilder private var chipsRow: some View {
        let chips = chipItems
        if !chips.isEmpty {
            BBFlowLayout(spacing: CGFloat(CarryOnSpace.xs), lineSpacing: CGFloat(CarryOnSpace.xs)) {
                ForEach(chips) { chip in
                    CarryOnChip(chip.text, tone: chip.tone, dot: chip.dot)
                }
            }
            .accessibilityElement(children: .ignore)
            .accessibilityLabel(chips.map(\.spoken).joined(separator: ", "))
        }
    }

    private struct ChipItem: Identifiable {
        let id: String
        let text: String
        let spoken: String
        var tone: CarryOnChip.Tone = .plain
        var dot: RGBColor? = nil
    }

    private var chipItems: [ChipItem] {
        var chips: [ChipItem] = []
        if let id = task.projectID, let project = projectRecord(id) {
            chips.append(
                ChipItem(
                    id: "project", text: project.name, spoken: "Project \(project.name)",
                    dot: BBColor.projectRGB(project.color)
                )
            )
        }
        if let day = task.dueDate {
            chips.append(dueChip(day))
        }
        for tagID in task.tagIDs {
            if let tag = tagRecord(tagID) {
                chips.append(ChipItem(id: "tag-\(tagID.rawValue)", text: tag.name, spoken: "Tag \(tag.name)"))
            }
        }
        return chips
    }

    /// "Due Friday", "Due today" (due colour), "Overdue · Sep 22" (overdue
    /// colour); the words carry the state, the colour only repeats it. A
    /// finished task's day is history and stays plain.
    private func dueChip(_ day: CalendarDay) -> ChipItem {
        let today = workspace.today
        let offset = BBDayMath.offset(from: today, to: day)
        let words: String
        switch offset {
        case 0: words = "today"
        case 1: words = "tomorrow"
        case -1: words = "yesterday"
        default: words = DueChip.label(for: day, today: today)
        }
        let spoken = DueChip.accessibilityText(for: day, today: today, isDeadlineActive: task.isOpen)
        if task.isOpen && offset < 0 {
            return ChipItem(id: "due", text: "Overdue · \(words)", spoken: spoken, tone: .overdue)
        }
        return ChipItem(id: "due", text: "Due \(words)", spoken: spoken, tone: task.isOpen && offset == 0 ? .dueSoon : .plain)
    }

    /// A line of copy on the sheet itself: body text, or a quiet meta line.
    private func cardTextRow(_ text: String, isQuiet: Bool) -> some View {
        Section {
            Text(text)
                .carryOnText(isQuiet ? CarryOnTypeScale.meta : CarryOnTypeScale.body)
                .foregroundStyle(isQuiet ? CarryOnColorStyle.coTextSecondary : .coTextPrimary)
                .fixedSize(horizontal: false, vertical: true)
                .listRowBackground(Color.clear)
                .listRowSeparator(.hidden)
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
            titleTextField
                .font(.title3.weight(.semibold))
        }
    }

    /// The title editor; the caller sets its type.
    private var titleTextField: some View {
        TextField("Title", text: $title, axis: .vertical)
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

    /// Every property on its own 44 pt row: list, project, due date and tags.
    /// Waiting for's note is edited in the card's header (board 18).
    private var propertiesSection: some View {
        Section {
            listRow
            projectRow
            dueDateRow
            tagsRow
        } footer: {
            propertiesFooter
        }
    }

    /// The due day trailing in the row; tapping it opens the date picker
    /// (board 14) while the task is open.
    private var dueDateRow: some View {
        Button {
            focus = nil
            isPickingDate = true
        } label: {
            LabeledContent {
                if let day = task.dueDate {
                    DueChip(day: day, today: workspace.today, isDeadlineActive: !isReadOnly)
                } else {
                    Text("Add date")
                        .foregroundStyle(.secondary)
                }
            } label: {
                Label("Due date", systemImage: BBSymbol.dueDate)
                    .labelStyle(.bbRow)
                    .foregroundStyle(Color.primary)
            }
            .frame(minHeight: BBMetrics.rowMinHeight)
            .contentShape(Rectangle())
        }
        .disabled(isReadOnly)
        .accessibilityLabel("Due date")
        .accessibilityValue(task.dueDate.map { $0.startDate().formatted(date: .complete, time: .omitted) } ?? "None")
        .accessibilityHint("Opens the date picker.")
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

    /// Who or what a waiting task waits on; saved like the title.
    private var waitingForTextField: some View {
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

    /// Any rejected property change, under the section. (Waiting for's
    /// problem and its "Asked …" line are in the card's header.)
    @ViewBuilder private var propertiesFooter: some View {
        problemFooter(.project, .dueDate, .tags)
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
        case .project, .dueDate, .tags: break
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
        if projectID != (workspace.taskDetail(task.id) ?? task).projectID {
            return await save(.project, TaskChanges(projectID: setOrClear(projectID)))
        }
        return true
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
