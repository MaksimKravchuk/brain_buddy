import BrainBuddyCore
import BrainBuddyWorkspace
import SwiftUI

/// Process inbox — the GTD *clarify* step, one inbox item at a time, fully
/// offline. Presented as a full-screen cover while `router.isProcessingInbox`;
/// the item view itself is `InboxClarifier`, which the weekly review's Inbox
/// step (M-15) reuses.
struct ProcessInboxScreen: View {
    @Environment(AppRouter.self) private var router
    @Environment(\.dismiss) private var dismiss

    init() {}

    var body: some View {
        NavigationStack {
            InboxClarifier(onClose: close)
                .navigationTitle("Process inbox")
                .navigationBarTitleDisplayMode(.inline)
                .toolbar {
                    ToolbarItem(placement: .cancellationAction) {
                        Button("Close", action: close)
                    }
                }
        }
        .toastMagicTap()
    }

    private func close() {
        router.isProcessingInbox = false
        dismiss()
    }
}

/// The inbox is snapshotted when the view appears; items that leave the
/// inbox meanwhile (processed elsewhere, given a project on another device)
/// are passed over. For each item you can first add a project (an existing
/// one or a new one), tags or a due date, then decide: Next action, Waiting
/// for… (asks who or what), Someday / maybe, Make it a project (names the
/// project, optionally its desired outcome, and asks for its first next
/// action, which the item becomes), Done
/// — under 2 minutes (complete), Not needed (cancel), or Skip. Every decision
/// is one change with an Undo toast that puts the item back in the Inbox
/// exactly as it was (a project made from it is archived again). The toast
/// shows above the decision buttons, never over them, and taps on the buttons
/// are ignored for a moment after each decision so a double tap can't decide
/// the next item too. At accessibility text sizes the buttons scroll with the item
/// instead of being pinned, so the item stays readable.
///
/// In the weekly review (M-15) it is given the items to go through, reports
/// every processed item and every Undo (`onProcessed(+1)` / `(-1)`, the run's
/// "Inbox processed" count), and calls `onDone` instead of showing its own
/// finished screen.
struct InboxClarifier: View {
    @Environment(Workspace.self) private var workspace
    @Environment(ToastCenter.self) private var toasts
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var queue: [TaskID] = []
    @State private var cursor = 0
    @State private var skipped: [TaskID] = []
    @State private var hasSnapshot = false
    @State private var stage = ClarifyStage()
    @State private var isAskingWaitingFor = false
    @State private var isChoosingTags = false
    @State private var isCreatingProject = false
    @State private var isMakingProject = false
    /// True for a moment after each decision (the double-tap guard).
    @State private var isSettling = false
    @AccessibilityFocusState private var isTitleFocused: Bool

    private let fixedQueue: [TaskID]?
    private let onProcessed: ((Int) -> Void)?
    private let onDone: (() -> Void)?
    private let onClose: () -> Void
    /// Process inbox puts Skip in its toolbar. The weekly review's Inbox step
    /// passes false: its toolbar already has the review's own Skip (the
    /// step), so this one stays in the decision panel.
    private let showsSkipInToolbar: Bool

    /// How long taps on the decision buttons are ignored after a decision.
    private static let settleDelay: Duration = .milliseconds(300)

    init(
        queue: [TaskID]? = nil, onProcessed: ((Int) -> Void)? = nil, onDone: (() -> Void)? = nil,
        showsSkipInToolbar: Bool = true, onClose: @escaping () -> Void
    ) {
        fixedQueue = queue
        self.onProcessed = onProcessed
        self.onDone = onDone
        self.showsSkipInToolbar = showsSkipInToolbar
        self.onClose = onClose
    }

    var body: some View {
        Group {
            if !hasSnapshot {
                Color.clear
            } else if let item = current {
                clarifyView(item)
            } else if onDone != nil {
                Color.clear
            } else {
                finishedView
                    .safeAreaInset(edge: .bottom) {
                        ToastHost()
                    }
            }
        }
        .onAppear(perform: takeSnapshot)
        .onChange(of: hasSnapshot && current == nil) { _, isDone in
            if isDone { onDone?() }
        }
        .onChange(of: current?.task.id, initial: true) { _, _ in
            // A new item starts from what it already has; nothing is staged.
            stage = current.map { ClarifyStage(task: $0.task) } ?? ClarifyStage()
            isTitleFocused = true
        }
        .sheet(isPresented: $isAskingWaitingFor) {
            if let item = current {
                WaitingForPromptSheet(taskTitle: item.task.title) { note in
                    apply(.waiting(note), to: item)
                }
            }
        }
        .sheet(isPresented: $isChoosingTags) {
            StagedTagsSheet(selection: $stage.tags)
        }
        .sheet(isPresented: $isCreatingProject) {
            // Created at once (a project alone changes no task); the item gets it with the decision.
            ProjectEditorSheet(mode: .create) { id in
                stage.project = .set(id)
            }
        }
        .sheet(isPresented: $isMakingProject) {
            if let item = current {
                MakeProjectSheet(taskTitle: item.task.title) { name, outcome, firstAction in
                    try makeProject(of: item, name: name, outcome: outcome, firstAction: firstAction)
                }
            }
        }
    }

    // MARK: Queue

    private struct InboxItem {
        let index: Int
        let task: TaskRecord
    }

    /// The first snapshotted item at or after the cursor that is still in the Inbox.
    private var current: InboxItem? {
        var index = cursor
        while index < queue.count {
            if let task = workspace.task(queue[index]), Self.isInInbox(task) {
                return InboxItem(index: index, task: task)
            }
            index += 1
        }
        return nil
    }

    /// Inbox shows projectless inbox tasks only (docs/projectless-inbox-contract.md).
    private static func isInInbox(_ task: TaskRecord) -> Bool {
        task.state == .inbox && task.projectID == nil
    }

    private func takeSnapshot() {
        guard !hasSnapshot else { return }
        queue = fixedQueue ?? workspace.list(.list(.inbox)).sections.flatMap(\.tasks).filter(Self.isInInbox).map(\.id)
        cursor = 0
        hasSnapshot = true
    }

    private static let arrival = Animation.timingCurve(0.22, 1, 0.36, 1, duration: 0.2)

    private func moveCursor(to index: Int) {
        withAnimation(reduceMotion ? nil : Self.arrival) {
            cursor = index
        }
    }

    // MARK: Clarify

    private func clarifyView(_ item: InboxItem) -> some View {
        // At accessibility sizes six pinned buttons would fill the screen and
        // hide the item, so they scroll with it instead.
        let pinsActions = !dynamicTypeSize.isAccessibilitySize
        return ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                progressHeader(item)
                itemCard(item)
                organizeControls(item.task)
                if !pinsActions {
                    // The toast sits above the buttons, so Undo never covers a decision.
                    VStack(spacing: 0) {
                        ToastHost()
                            .padding(.horizontal, -16)
                        actionCluster(item, isFloating: false)
                    }
                }
            }
            .padding(.horizontal, 16)
            .padding(.top, 8)
            .padding(.bottom, 16)
            .frame(maxWidth: .infinity, alignment: .leading)
            .id(item.task.id)
            .transition(.opacity)
        }
        .toolbar {
            if showsSkipInToolbar {
                ToolbarItem(placement: .primaryAction) {
                    Button {
                        skip(item)
                    } label: {
                        Label("Skip", systemImage: "arrow.forward")
                            .labelStyle(.titleAndIcon)
                    }
                }
            }
        }
        .safeAreaInset(edge: .bottom) {
            if pinsActions {
                // The toast sits above the buttons, so Undo never covers a decision.
                VStack(spacing: 0) {
                    ToastHost()
                    actionCluster(item, isFloating: true)
                        .padding(.horizontal, 16)
                        .padding(.bottom, 8)
                }
            }
        }
    }

    private func itemCard(_ item: InboxItem) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(item.task.title)
                .font(BBFont.title)
                .fixedSize(horizontal: false, vertical: true)
                .accessibilityAddTraits(.isHeader)
                .accessibilityFocused($isTitleFocused)
            if let details = item.task.details, !details.isEmpty {
                Text(details)
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
                    .textSelection(.enabled)
            }
            Text("Captured \(item.task.createdAt.formatted(.relative(presentation: .named)))")
                .font(.caption)
                .foregroundStyle(BBColor.textTertiary)
        }
        .padding(16)
        .frame(maxWidth: .infinity, alignment: .leading)
        .bbCard(cornerRadius: BBRadius.card)
    }

    private func progressHeader(_ item: InboxItem) -> some View {
        HStack(spacing: 10) {
            Text("\(item.index + 1) of \(queue.count)")
                .font(.footnote.monospacedDigit())
                .foregroundStyle(.secondary)
                .fixedSize()
            ProgressView(value: Double(item.index), total: Double(max(queue.count, 1)))
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("Item \(item.index + 1) of \(queue.count)")
    }

    private func organizeControls(_ task: TaskRecord) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text("Organize · optional")
                .bbSectionLabel()
            WrappingChipLayout(spacing: 8) {
                projectMenu(task)
                tagsButton()
                dueMenu(task)
            }
        }
    }

    private func projectMenu(_ task: TaskRecord) -> some View {
        let selected = stage.projectID(for: task)
        let name = selected.flatMap { workspace.project($0)?.name }
        return Menu {
            Button("New project…", systemImage: "folder.badge.plus") { isCreatingProject = true }
            Divider()
            Button("No project") { stage.project = .clear }
            ForEach(workspace.projects()) { summary in
                Button {
                    stage.project = .set(summary.id)
                } label: {
                    if selected == summary.id {
                        Label(summary.project.name, systemImage: "checkmark")
                    } else {
                        Text(summary.project.name)
                    }
                }
            }
        } label: {
            Label(name ?? "Project", systemImage: "folder")
                .lineLimit(1)
        }
        .menuStyle(.button)
        .buttonStyle(.bordered)
        .buttonBorderShape(.capsule)
        .controlSize(.regular)
        .frame(minHeight: BBMetrics.hitTarget)
        .accessibilityLabel("Project")
        .accessibilityValue(name ?? "None")
    }

    private func tagsButton() -> some View {
        let names = stage.tags.compactMap { workspace.tag($0)?.name }
        return Button {
            isChoosingTags = true
        } label: {
            Label(names.isEmpty ? "Tags" : names.joined(separator: ", "), systemImage: "tag")
                .lineLimit(1)
        }
        .buttonStyle(.bordered)
        .buttonBorderShape(.capsule)
        .controlSize(.regular)
        .frame(minHeight: BBMetrics.hitTarget)
        .accessibilityLabel("Tags")
        .accessibilityValue(names.isEmpty ? "None" : names.joined(separator: ", "))
    }

    private func dueMenu(_ task: TaskRecord) -> some View {
        let today = workspace.today
        let due = stage.dueDate(for: task)
        let label = due.map(Self.shortDay) ?? "Due date"
        return Menu {
            Button("Today") { stage.due = .set(today) }
            Button("Tomorrow") { stage.due = .set(today.adding(days: 1)) }
            Button("Next week") { stage.due = .set(today.adding(days: 7)) }
            if due != nil {
                Divider()
                Button("No due date", role: .destructive) { stage.due = .clear }
            }
        } label: {
            Label(label, systemImage: "calendar")
                .lineLimit(1)
        }
        .menuStyle(.button)
        .buttonStyle(.bordered)
        .buttonBorderShape(.capsule)
        .controlSize(.regular)
        .frame(minHeight: BBMetrics.hitTarget)
        .accessibilityLabel("Due date")
        .accessibilityValue(due.map(Self.shortDay) ?? "None")
    }

    private static func shortDay(_ day: CalendarDay) -> String {
        day.startDate().formatted(.dateTime.weekday(.abbreviated).day().month(.abbreviated))
    }

    // MARK: Actions

    /// The decision panel: the prompt, then six decisions in four rows.
    /// Floating (pinned at the bottom) they are a glass cluster; inline
    /// (scrolling with the item) they are flat content. Skip is in the toolbar.
    @ViewBuilder
    private func actionCluster(_ item: InboxItem, isFloating: Bool) -> some View {
        let panel = decisionPanel(item, isFloating: isFloating)
        if isFloating {
            GlassEffectContainer(spacing: 10) { panel }
        } else {
            panel
        }
    }

    private func decisionPanel(_ item: InboxItem, isFloating: Bool) -> some View {
        let pair =
            dynamicTypeSize.isAccessibilitySize
            ? AnyLayout(VStackLayout(spacing: 10)) : AnyLayout(HStackLayout(spacing: 10))
        return VStack(spacing: 10) {
            Text("Is it actionable? Choose where it belongs.")
                .font(.subheadline)
                .foregroundStyle(.secondary)
                .frame(maxWidth: .infinity, alignment: .leading)
            pair {
                actionButton("Next action", systemImage: OpenList.next.symbolName, isFloating: isFloating, prominent: true) {
                    apply(.move(.next), to: item)
                }
                actionButton("Waiting for…", systemImage: OpenList.waiting.symbolName, isFloating: isFloating) {
                    guard !isSettling else { return }
                    isAskingWaitingFor = true
                }
            }
            pair {
                actionButton("Someday / maybe", systemImage: OpenList.someday.symbolName, isFloating: isFloating) {
                    apply(.move(.someday), to: item)
                }
                actionButton("Not needed", systemImage: "xmark.circle", isFloating: isFloating) {
                    apply(.cancel, to: item)
                }
            }
            actionButton("Make it a project", systemImage: "folder.badge.plus", isFloating: isFloating) {
                guard !isSettling else { return }
                isMakingProject = true
            }
            actionButton("Done — under 2 minutes", systemImage: "checkmark.circle", isFloating: isFloating) {
                apply(.complete, to: item)
            }
            if !showsSkipInToolbar {
                actionButton("Skip", systemImage: "arrow.forward", isFloating: isFloating) {
                    skip(item)
                }
            }
        }
    }

    @ViewBuilder
    private func actionButton(
        _ title: String, systemImage: String, isFloating: Bool, prominent: Bool = false,
        action: @escaping () -> Void
    ) -> some View {
        // Labels stay on one line (shrinking a little if needed) so every
        // button is the same 48 pt; accessibility sizes stack and may wrap.
        let wraps = dynamicTypeSize.isAccessibilitySize
        let button = Button(action: action) {
            Label(title, systemImage: systemImage)
                .lineLimit(wraps ? nil : 1)
                .minimumScaleFactor(wraps ? 1 : 0.85)
                .multilineTextAlignment(.center)
                .frame(maxWidth: .infinity, minHeight: 48)
        }
        switch (isFloating, prominent) {
        case (true, true):
            button.buttonStyle(.glassProminent).tint(BBColor.brandFill)
        case (true, false):
            button.buttonStyle(.glass)
        case (false, true):
            button.buttonStyle(.borderedProminent).tint(BBColor.brandFill)
        case (false, false):
            button.buttonStyle(.bordered)
        }
    }

    /// Ignores decision taps for `settleDelay`, so a double tap decides one
    /// item, not the next one as well.
    private func beginSettling() {
        isSettling = true
        Task {
            try? await Task.sleep(for: Self.settleDelay)
            isSettling = false
        }
    }

    private func apply(_ action: ClarifyAction, to item: InboxItem) {
        guard !isSettling else { return }
        let original = item.task
        let changes = stage.changes(for: original)
        let succeeded = TaskCommandRunner.run(toasts) { () throws(GTDValidationError) in
            if changes.hasChanges {
                try workspace.updateTask(original.id, changes)
            }
            switch action {
            case .move(let list):
                try workspace.moveTask(original.id, to: list)
            case .waiting(let note):
                try workspace.moveTask(original.id, to: .waiting, waitingFor: note)
            case .complete:
                try workspace.completeTask(original.id)
            case .cancel:
                try workspace.cancelTask(original.id)
            }
        }
        guard succeeded else { return }
        onProcessed?(1)
        beginSettling()
        moveCursor(to: item.index + 1)
        toasts.show(action.confirmation, actionTitle: "Undo") {
            undo(original: original, changes: changes, index: item.index)
        }
    }

    /// "Make it a project": a new project whose first Next action is the item,
    /// titled `firstAction`, with the staged tags and due date. Throws, and
    /// changes nothing, when the workspace refuses it (the sheet shows why).
    private func makeProject(of item: InboxItem, name: String, outcome: String?, firstAction: String) throws {
        let original = item.task
        var staged = stage.changes(for: original)
        staged.projectID = .unchanged
        let projectID = try workspace.clarifyAsProject(
            original.id, projectName: name, outcome: outcome, firstAction: firstAction, changes: staged
        )
        var changes = staged
        changes.projectID = .set(projectID)
        changes.title = firstAction == original.title ? .unchanged : .set(firstAction)
        onProcessed?(1)
        beginSettling()
        moveCursor(to: item.index + 1)
        toasts.show("Project created", actionTitle: "Undo") {
            undo(original: original, changes: changes, index: item.index, createdProject: projectID)
        }
    }

    private func skip(_ item: InboxItem) {
        guard !isSettling else { return }
        beginSettling()
        if !skipped.contains(item.task.id) { skipped.append(item.task.id) }
        moveCursor(to: item.index + 1)
    }

    /// Puts the item back in the Inbox as it was — list, title, project, tags
    /// and due date — and back in front of the cursor if this screen is still
    /// open. A project made from the item is archived again unless it has
    /// other open tasks by now.
    private func undo(original: TaskRecord, changes: TaskChanges, index: Int, createdProject: ProjectID? = nil) {
        let restored = TaskCommandRunner.run(toasts) { () throws(GTDValidationError) in
            guard let latest = workspace.task(original.id) else { throw .taskNotFound }
            if latest.state.isTerminal {
                try workspace.reopenTask(original.id, to: .inbox)
            } else if latest.state != .inbox {
                try workspace.moveTask(original.id, to: .inbox)
            }
            let revert = TaskChanges(
                title: changes.title.isChanged ? .set(original.title) : .unchanged,
                projectID: changes.projectID.isChanged ? setOrClear(original.projectID) : .unchanged,
                tagIDs: changes.tagIDs.isChanged ? .set(original.tagIDs) : .unchanged,
                dueDate: changes.dueDate.isChanged ? setOrClear(original.dueDate) : .unchanged
            )
            if revert.hasChanges {
                try workspace.updateTask(original.id, revert)
            }
            if let createdProject,
                workspace.projects().first(where: { $0.id == createdProject })?.openTaskCount == 0
            {
                try workspace.archiveProject(createdProject)
            }
        }
        guard restored else { return }
        onProcessed?(-1)
        skipped.removeAll { $0 == original.id }
        moveCursor(to: min(cursor, index))
    }

    // MARK: Finish

    private var finishedView: some View {
        let stillSkipped = skipped.filter { id in workspace.task(id).map(Self.isInInbox) ?? false }
        let copy = finishCopy(skippedCount: stillSkipped.count, inboxCount: workspace.counts().inbox)
        return VStack(spacing: 20) {
            EmptyStateView(title: copy.title, message: copy.message, systemImage: copy.systemImage)
            Button {
                close()
            } label: {
                Text("Close")
                    .frame(minWidth: 120, minHeight: 44)
            }
            .buttonStyle(.borderedProminent)
            .tint(BBColor.brandFill)
            if !stillSkipped.isEmpty {
                Button {
                    restart(with: stillSkipped)
                } label: {
                    Text("Go through skipped items")
                        .frame(minHeight: 44)
                }
                .buttonStyle(.bordered)
            }
        }
        .padding()
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    private func finishCopy(skippedCount: Int, inboxCount: Int) -> (title: String, message: String, systemImage: String) {
        if skippedCount > 0 {
            return ("\(skippedCount) skipped", "Skipped items stay in your Inbox for next time.", OpenList.inbox.symbolName)
        }
        if inboxCount == 0 {
            return ("Inbox zero", "Everything you captured has a place.", "checkmark.circle")
        }
        return ("All done for now", "New items reached your Inbox while you were processing.", OpenList.inbox.symbolName)
    }

    private func restart(with ids: [TaskID]) {
        queue = ids
        skipped = []
        moveCursor(to: 0)
    }

    private func close() {
        onClose()
    }
}

private enum ClarifyAction {
    case move(OpenList)
    case waiting(String)
    case complete
    case cancel

    var confirmation: String {
        switch self {
        case .move(let list): "Moved to \(list.title)"
        case .waiting: "Moved to \(OpenList.waiting.title)"
        case .complete: "Completed"
        case .cancel: "Marked not needed"
        }
    }
}

/// Project, tags and due date chosen for the current item, applied together
/// with the decision. Staged rather than saved at once because giving an
/// inbox task a project takes it out of the Inbox before it is clarified.
private struct ClarifyStage: Equatable {
    var project: FieldChange<ProjectID> = .unchanged
    /// The item's tags as they will be; starts as the tags it already has.
    var tags: [TagID] = []
    var due: FieldChange<CalendarDay> = .unchanged

    init() {}

    init(task: TaskRecord) {
        tags = task.tagIDs
    }

    func projectID(for task: TaskRecord) -> ProjectID? {
        switch project {
        case .unchanged: return task.projectID
        case .clear: return nil
        case .set(let id): return id
        }
    }

    func dueDate(for task: TaskRecord) -> CalendarDay? {
        switch due {
        case .unchanged: return task.dueDate
        case .clear: return nil
        case .set(let day): return day
        }
    }

    func changes(for task: TaskRecord) -> TaskChanges {
        let newProject = projectID(for: task)
        let newDue = dueDate(for: task)
        return TaskChanges(
            projectID: newProject == task.projectID ? .unchanged : setOrClear(newProject),
            tagIDs: tags == task.tagIDs ? .unchanged : .set(tags),
            dueDate: newDue == task.dueDate ? .unchanged : setOrClear(newDue)
        )
    }
}

/// Chooses tags for the item being clarified. Choices are staged and saved
/// with the decision, like the project and due date.
private struct StagedTagsSheet: View {
    @Binding var selection: [TagID]

    @Environment(Workspace.self) private var workspace
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            List {
                ForEach(workspace.tags()) { summary in
                    tagRow(summary.tag)
                }
            }
            .overlay {
                if workspace.tags().isEmpty {
                    EmptyStateView(
                        title: "No tags yet",
                        message: "Add tags with # when you capture, or from a task's details.",
                        systemImage: "tag"
                    )
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

    private func tagRow(_ tag: TagRecord) -> some View {
        let isSelected = selection.contains(tag.id)
        return Button {
            if let index = selection.firstIndex(of: tag.id) {
                selection.remove(at: index)
            } else {
                selection.append(tag.id)
            }
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
}

/// "Make it a project": the project's name (the item's title to start with),
/// optionally its desired outcome, and its first next action, which the item
/// becomes in Next actions.
private struct MakeProjectSheet: View {
    let taskTitle: String
    let onCreate: (_ name: String, _ outcome: String?, _ firstAction: String) throws -> Void

    @Environment(\.dismiss) private var dismiss
    @State private var name: String
    @State private var outcome = ""
    @State private var firstAction = ""
    @State private var message: String?
    @FocusState private var focus: Field?

    private enum Field { case name, outcome, firstAction }

    init(
        taskTitle: String,
        onCreate: @escaping (_ name: String, _ outcome: String?, _ firstAction: String) throws -> Void
    ) {
        self.taskTitle = taskTitle
        self.onCreate = onCreate
        _name = State(initialValue: taskTitle)
    }

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    TextField("Project name", text: $name)
                        .submitLabel(.next)
                        .focused($focus, equals: .name)
                        .onSubmit { focus = .outcome }
                } header: {
                    Text("Project")
                }
                Section {
                    TextField("What will be true when it's done?", text: $outcome, axis: .vertical)
                        .lineLimit(1...4)
                        .textInputAutocapitalization(.sentences)
                        .focused($focus, equals: .outcome)
                        .accessibilityLabel("Desired outcome")
                } header: {
                    Text("Desired outcome · optional")
                }
                Section {
                    TextField("What's the very next step?", text: $firstAction)
                        .textInputAutocapitalization(.sentences)
                        .submitLabel(.done)
                        .focused($focus, equals: .firstAction)
                        .onSubmit(create)
                        .accessibilityLabel("First next action")
                } header: {
                    Text("First next action")
                } footer: {
                    if let message {
                        EditorValidationMessage(text: message)
                    } else {
                        Text("It goes to Next actions, in this project.")
                    }
                }
            }
            .navigationTitle("Make it a project")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Create", action: create)
                        .disabled(trimmed(name).isEmpty || trimmed(firstAction).isEmpty)
                }
            }
            .onChange(of: name) { message = nil }
            .onChange(of: outcome) { message = nil }
            .onChange(of: firstAction) { message = nil }
            // The name is already there; the next step is what is missing.
            .onAppear { focus = .firstAction }
        }
        .presentationDetents([.medium, .large])
    }

    private func trimmed(_ text: String) -> String {
        text.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private func create() {
        let projectName = trimmed(name)
        let action = trimmed(firstAction)
        let desiredOutcome = trimmed(outcome)
        guard !projectName.isEmpty, !action.isEmpty else { return }
        do {
            try onCreate(projectName, desiredOutcome.isEmpty ? nil : desiredOutcome, action)
            dismiss()
        } catch {
            message = TaskCommandRunner.message(for: error)
        }
    }
}

/// Asks who or what the item is waiting on before it moves to Waiting for.
private struct WaitingForPromptSheet: View {
    let taskTitle: String
    let onConfirm: (String) -> Void

    @Environment(\.dismiss) private var dismiss
    @State private var text = ""

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    Text(taskTitle)
                        .font(.headline)
                        .lineLimit(3)
                }
                WaitingForSection(text: $text)
            }
            .navigationTitle("Waiting for")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Move") {
                        let note = text.trimmingCharacters(in: .whitespacesAndNewlines)
                        dismiss()
                        onConfirm(note)
                    }
                    .disabled(WaitingForInput.problem(text) != nil)
                }
            }
        }
        // The field takes focus at once; large leaves room for the keyboard
        // and for larger text.
        .presentationDetents([.medium, .large])
    }
}

private func setOrClear<Value: Hashable & Sendable & Codable>(_ value: Value?) -> FieldChange<Value> {
    if let value { return .set(value) }
    return .clear
}
