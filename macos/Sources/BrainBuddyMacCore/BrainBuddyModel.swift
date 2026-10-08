import BrainBuddyCore
import BrainBuddyWorkspace
import Foundation
import Observation

/// What Quick Open can jump to.
package enum QuickOpenTarget: Hashable, Sendable {
    case list(TaskList)
    case history(HistoryState)
    case project(ProjectID)
    case tag(TagID)
    case task(TaskID)
}

package struct QuickOpenResult: Identifiable, Hashable, Sendable {
    package let id: String
    package let title: String
    package let subtitle: String
    package let symbol: String
    package let target: QuickOpenTarget
}

package enum PriorityFilter: String, CaseIterable, Identifiable, Sendable {
    case all, high, medium, low, none

    package var id: String { rawValue }
    package var title: String { rawValue.capitalized }
    package var priority: TaskPriority? { self == .all ? nil : TaskPriority(rawValue: rawValue) }
}

/// One project in the Project review, with the keyed signature of its tasks taken when the review
/// opened: a decision is refused once the tasks changed since (data-model E7.2).
package struct ProjectReviewItem: Identifiable, Sendable {
    package let project: ProjectRecord
    package let tasks: [TaskRecord]
    package let signature: String
    /// The last review, valid or not.
    package let lastReview: ProjectReviewMark?
    /// A review exists but the project's tasks changed since.
    package let hasChanges: Bool

    package var id: ProjectID { project.id }
    package var openTasks: [TaskRecord] { tasks.filter(\.isOpen) }
    package var nextCount: Int { openTasks.filter { $0.state == .next }.count }
    package var waitingCount: Int { openTasks.filter { $0.state == .waiting }.count }
    package var somedayCount: Int { openTasks.filter { $0.state == .someday }.count }
}

/// The project header: what it is and what to do next, whatever the list filters.
package struct ProjectOverview: Sendable {
    package var project: ProjectRecord
    package var display: ProjectDisplay
    package var nextAction: TaskRecord?
    package var openCounts: [TaskList: Int]
    package var openCount: Int { openCounts.values.reduce(0, +) }
}

/// The limits the Mac's editors show and enforce: the kit's, so a value the editor accepts is one
/// the reducer and the server accept (XCTest ledger, `testLocalCollectionAndCommentLengthsMatchEditorLimits`).
package enum EditorLimits {
    package static let title = GTDLimits.title
    package static let details = GTDLimits.details
    package static let waitingFor = GTDLimits.waitingFor
    package static let name = GTDLimits.name
    package static let comment = GTDLimits.comment
    package static let outcome = GTDLimits.outcome

    /// Lengths count Unicode scalars, as the reducer and the server do.
    package static func fits(_ text: String, _ limit: Int) -> Bool { text.unicodeScalars.count <= limit }
}

/// X-06 "unarchive refused: name in use": the inline refusal under the project title.
package struct UnarchiveRefusal: Hashable, Sendable {
    package var projectID: ProjectID
    package var message: String
}

/// The Mac window's model over the kit `Workspace` (T106, T107): navigation, the capture draft and
/// the list filters live here; every rule is the kit's (`GTDReducer`, `GTDQueries`, Smart Add), and
/// the Waiting, Someday and Project review marks live in `mac-local.json`, never in the document
/// (FR-023). Every write applies at once on this Mac and never waits for the network (FR-010).
@MainActor
@Observable
package final class BrainBuddyModel {
    package let workspace: Workspace
    @ObservationIgnored package let localStateStore: MacLocalStateStore
    @ObservationIgnored private let now: @Sendable () -> Date
    /// The sidecar as last read or written.
    package private(set) var localState: MacLocalState

    package var destination: WorkspaceDestination = .list(.next)
    /// The list a capture from this screen goes to.
    package var selectedList: TaskList = .next
    package var searchText = ""
    package var groupByProject = true
    package var showCancelled = false
    package var priorityFilter: PriorityFilter = .all
    package var sort: TaskSort = .manual
    package var error: String?
    package var draft = "" {
        didSet { if draft != oldValue { captureNotice = nil } }
    }
    package var captureNotice: String?
    package var waitingForDraft = ""
    /// A task edit is open with unsaved fields (the File-menu archive is disabled meanwhile).
    package var taskEditInProgress = false
    package private(set) var unarchiveRefusal: UnarchiveRefusal?
    /// Counts archives and unarchives done here, so the open project's title can take focus after
    /// one (design X-06 "archived (just now)", "unarchived").
    package private(set) var projectStateChanges = 0
    /// The search and priority the list shows: applied on submit, as before 021.
    package private(set) var appliedSearch: String?
    package private(set) var appliedPriority: TaskPriority?

    package init(workspace: Workspace, localStateStore: MacLocalStateStore, now: @escaping @Sendable () -> Date = { Date() }) {
        self.workspace = workspace
        self.localStateStore = localStateStore
        self.now = now
        localState = localStateStore.load() ?? (try? localStateStore.update { _ in }) ?? .fresh()
    }

    package convenience init(host: WorkspaceHost) {
        self.init(workspace: host.workspace, localStateStore: host.localState)
    }

    private var state: GTDState { workspace.state }

    // MARK: Collections

    package var projects: [ProjectRecord] { workspace.projects().map(\.project) }
    package var archivedProjects: [ProjectRecord] { workspace.projects(archived: true).map(\.project) }
    package var tags: [TagRecord] { workspace.tags().map(\.tag) }
    package var sidebarCounts: ListCounts { workspace.counts() }

    package func task(_ id: TaskID) -> TaskRecord? { workspace.task(id) }
    package func project(_ id: ProjectID) -> ProjectRecord? { workspace.project(id) }
    package func tag(_ id: TagID) -> TagRecord? { workspace.tag(id) }
    package func projectDisplay(_ id: ProjectID) -> ProjectDisplay? { GTDQueries.projectDisplay(id, in: state) }
    package func isArchived(_ id: ProjectID?) -> Bool { id.flatMap { projectDisplay($0)?.isArchived } ?? false }

    /// The project's name as every list shows it: "<name> · archived" for an archived one.
    package func projectLabel(_ id: ProjectID) -> String { projectDisplay(id)?.label ?? "Project" }

    package var hasAppliedTaskFilter: Bool { appliedSearch != nil || appliedPriority != nil }

    package var isArchivedProjectDestination: Bool {
        if case .project(let id) = destination { return isArchived(id) }
        return false
    }

    // MARK: The list on screen

    /// The screen's sections from `GTDQueries`: open ones first (by project in Next when grouped;
    /// by list in a project), then Completed and Cancelled; the applied search and priority narrow
    /// every section.
    package var sections: [TaskSection] {
        let options = ListOptions(
            sort: sort, groupByProject: destination == .list(.next) && groupByProject,
            showCompleted: !destination.isHistory, showCancelled: !destination.isHistory && showCancelled,
            priorities: appliedPriority.map { [$0] } ?? []
        )
        var sections = workspace.list(destination.query, options: options).sections
        if let search = appliedSearch {
            let matches = Set(
                workspace.list(.search(search), options: ListOptions(priorities: options.priorities)).sections
                    .flatMap(\.tasks).map(\.id)
            )
            sections = sections.compactMap { section in
                var narrowed = section
                narrowed.tasks = section.tasks.filter { matches.contains($0.id) }
                return narrowed.tasks.isEmpty ? nil : narrowed
            }
        }
        return sections
    }

    /// Every task on screen, in order.
    package var tasks: [TaskRecord] { sections.flatMap(\.tasks) }
    package var openTaskCount: Int { tasks.filter(\.isOpen).count }

    package func projectOverview(_ id: ProjectID) -> ProjectOverview? {
        guard let project = workspace.project(id), let display = projectDisplay(id) else { return nil }
        let result = workspace.list(.project(id), options: ListOptions())
        var counts: [TaskList: Int] = [:]
        var next: TaskRecord?
        for section in result.sections {
            guard case .list(let list) = section.kind else { continue }
            counts[list] = section.tasks.count
            if list == .next { next = section.tasks.first }
        }
        return ProjectOverview(project: project, display: display, nextAction: next, openCounts: counts)
    }

    // MARK: Navigation

    package func choose(_ destination: WorkspaceDestination) {
        if self.destination != destination { unarchiveRefusal = nil }
        self.destination = destination
        switch destination {
        case .list(let list): selectedList = list
        case .project, .tag: selectedList = .inbox
        case .date, .history: selectedList = .next
        }
        reload()
    }

    /// Applies the typed search and the priority filter (search applies on submit).
    package func reload() {
        captureNotice = nil
        error = nil
        let search = searchText.trimmingCharacters(in: .whitespacesAndNewlines)
        appliedSearch = search.isEmpty ? nil : search
        appliedPriority = priorityFilter.priority
    }

    package func clearTaskFilters() {
        searchText = ""
        priorityFilter = .all
        reload()
    }

    package func quickOpenResults(_ input: String) -> [QuickOpenResult] {
        let term = input.trimmingCharacters(in: .whitespacesAndNewlines)
        func matches(_ value: String) -> Bool { term.isEmpty || value.localizedStandardContains(term) }
        var results: [QuickOpenResult] = []
        for list in TaskList.allCases where matches(list.title) {
            results.append(.init(id: "list:\(list.rawValue)", title: list.title, subtitle: "GTD list", symbol: list.symbol, target: .list(list)))
        }
        for history in [HistoryState.completed, .cancelled] where matches(history.title) {
            results.append(
                .init(id: "history:\(history.rawValue)", title: history.title, subtitle: "History", symbol: history.symbol, target: .history(history))
            )
        }
        for project in projects + archivedProjects where matches(project.name) {
            results.append(
                .init(
                    id: "project:\(project.id.rawValue)", title: project.name,
                    subtitle: project.state == .archived ? "Archived project" : "Project", symbol: "square.stack",
                    target: .project(project.id)
                )
            )
        }
        for tag in tags where matches(tag.name) {
            results.append(.init(id: "tag:\(tag.id.rawValue)", title: "#\(tag.name)", subtitle: "Tag", symbol: "tag", target: .tag(tag.id)))
        }
        guard !term.isEmpty else { return results }
        for task in workspace.list(.search(term), options: ListOptions()).sections.flatMap(\.tasks) {
            let list = task.state.openList?.title ?? task.state.rawValue.capitalized
            let project = task.projectID.map(projectLabel)
            results.append(
                .init(
                    id: "task:\(task.id.rawValue)", title: task.title,
                    subtitle: (["Task", list] + [project].compactMap { $0 }).joined(separator: " · "),
                    symbol: "checkmark.circle", target: .task(task.id)
                )
            )
        }
        return results
    }

    /// Where a task opened from Quick Open is shown.
    package func destination(showing task: TaskRecord) -> WorkspaceDestination {
        switch task.state {
        case .completed: .history(.completed)
        case .cancelled: .history(.cancelled)
        case .inbox where task.projectID != nil: .project(task.projectID!)
        case .inbox: .list(.inbox)
        case .next: .list(.next)
        case .waiting: .list(.waiting)
        case .someday: .list(.someday)
        }
    }

    // MARK: Capture

    /// Smart Add in the main window, through the kit's capture (FR-010).
    package var captureDraft: CaptureDraft {
        var draft = CaptureDraft(text: self.draft, list: selectedList, waitingFor: waitingForDraft)
        if case .project(let id) = destination { draft.contextProjectID = id }
        if case .tag(let id) = destination { draft.contextTagID = id }
        return draft
    }

    package var capturePreview: CapturePreview { workspace.capturePreview(captureDraft) }

    package func createTask() {
        let captureList = selectedList
        let preview = capturePreview
        if let message = preview.problemMessage, preview.problem != nil {
            error = message
            return
        }
        do {
            let id = try workspace.capture(captureDraft)
            error = nil
            draft = ""
            waitingForDraft = ""
            let created = workspace.task(id)
            if captureList == .inbox, let projectID = created?.projectID, destination != .project(projectID) {
                choose(.project(projectID))
            } else if captureList != selectedList {
                choose(.list(captureList))
            }
            if !tasks.contains(where: { $0.id == id }) {
                captureNotice = "Saved to \(captureList.title). Search or priority filters may hide it from these results."
            }
        } catch {
            self.error = error.message
        }
    }

    /// Quick Capture (⌃⌥⇧B): to Inbox, never touching the main window's draft or screen.
    package func quickCaptureInbox(_ title: String) throws(GTDValidationError) {
        try workspace.capture(CaptureDraft(text: title, list: .inbox))
    }

    // MARK: Tasks

    /// Runs a write: on a refusal the kit's words become `error` and nothing changed.
    @discardableResult
    private func run(_ body: () throws -> Void) -> Bool {
        lastUnarchivedName = nil
        do {
            try body()
            error = nil
            return true
        } catch let refusal as GTDValidationError {
            error = refusal.message
            return false
        } catch {
            self.error = "Brain Buddy couldn't save this change. Try again."
            return false
        }
    }

    @discardableResult
    package func completeTask(_ id: TaskID) -> Bool { run { try workspace.completeTask(id) } }

    @discardableResult
    package func cancelTask(_ id: TaskID) -> Bool { run { try workspace.cancelTask(id) } }

    @discardableResult
    package func reopenTask(_ id: TaskID, to list: TaskList, waitingFor: String?) -> Bool {
        run { try workspace.reopenTask(id, to: list, waitingFor: list == .waiting ? waitingFor : nil) }
    }

    @discardableResult
    package func moveTask(_ id: TaskID, to list: TaskList, waitingFor: String? = nil) -> Bool {
        guard let task = workspace.task(id), task.state != list.taskState else { return false }
        return run { try workspace.moveTask(id, to: list, waitingFor: list == .waiting ? waitingFor : nil) }
    }

    /// The inline editor's save: the changed fields first, then the move, as one change
    /// (`Workspace.apply`, T047). Only touched fields are sent (FR-009).
    @discardableResult
    package func saveTask(_ id: TaskID, changes: TaskChanges, moveTo list: TaskList? = nil) -> Bool {
        guard let task = workspace.task(id) else {
            error = GTDValidationError.taskNotFound.message
            return false
        }
        var commands: [GTDCommand] = []
        var edit = changes
        let moving = list.map { $0.taskState != task.state } ?? false
        var waitingFor: String?
        if moving {
            if case .set(let value) = changes.waitingFor { waitingFor = value } else { waitingFor = task.waitingFor }
            edit.waitingFor = .unchanged
        }
        if edit.hasChanges { commands.append(.updateTask(.init(taskID: id, changes: edit))) }
        if moving, let list {
            commands.append(
                .transitionTask(.init(taskID: id, action: .move, toList: list, waitingFor: list == .waiting ? waitingFor : nil))
            )
        }
        guard !commands.isEmpty else { return true }
        guard run({ try workspace.apply(commands) }) else { return false }
        if destination == .list(.inbox), let updated = workspace.task(id), updated.state == .inbox, let projectID = updated.projectID {
            choose(.project(projectID))
        }
        return true
    }

    /// The Waiting review's "Create follow-up…": a separate Next action in the same project, and the
    /// Waiting item marked reviewed in the sidecar (it returns after 7 days or a change).
    @discardableResult
    package func createFollowUp(for id: TaskID, title: String) -> Bool {
        guard let task = workspace.task(id), task.state == .waiting else {
            error = "This task is no longer in Waiting for. Refresh the review."
            return false
        }
        if isArchived(task.projectID) {
            error = "Unarchive this project before creating a follow-up in it."
            return false
        }
        let command = GTDCommand.createTask(.init(taskID: .random(), title: title, list: .next, projectID: task.projectID))
        guard run({ try workspace.apply([command]) }) else { return false }
        markReviewed { $0.markWaitingReviewed(task, in: workspace.state, at: now()) }
        return true
    }

    // MARK: Reviews (marks in mac-local.json)

    private var reviewNow: Date { now() }

    package func loadWaitingReviewTasks() -> [TaskRecord] {
        let state = self.state
        return workspace.list(.list(.waiting), options: ListOptions()).sections.flatMap(\.tasks)
            .filter { localState.waitingReviewDue($0, in: state, now: reviewNow) }
    }

    @discardableResult
    package func keepWaiting(_ id: TaskID) -> Bool {
        guard let task = workspace.task(id), task.state == .waiting else {
            error = "This Waiting task changed. Reopen the review to inspect it."
            return false
        }
        return markReviewed { $0.markWaitingReviewed(task, in: workspace.state, at: now()) }
    }

    package func loadSomedayReviewTasks() -> [TaskRecord] {
        let state = self.state
        return workspace.list(.list(.someday), options: ListOptions()).sections.flatMap(\.tasks)
            .filter { localState.somedayReviewDue($0, in: state, now: reviewNow) }
    }

    @discardableResult
    package func keepSomeday(_ id: TaskID) -> Bool {
        guard let task = workspace.task(id), task.state == .someday else {
            error = "This Someday task changed. Reopen the review to inspect it."
            return false
        }
        return markReviewed { $0.markSomedayReviewed(task, in: workspace.state, at: now()) }
    }

    /// "Make it a Next action…": the new title and the move, as one change.
    @discardableResult
    package func activateSomeday(_ id: TaskID, title: String) -> Bool {
        guard let task = workspace.task(id), task.state == .someday else {
            error = "This Someday task changed. Reopen the review to inspect it."
            return false
        }
        var commands: [GTDCommand] = []
        if title != task.title { commands.append(.updateTask(.init(taskID: id, changes: TaskChanges(title: .set(title))))) }
        commands.append(.transitionTask(.init(taskID: id, action: .move, toList: .next)))
        return run { try workspace.apply(commands) }
    }

    package func loadInboxClarificationTasks() -> [TaskRecord] {
        workspace.list(.list(.inbox), options: ListOptions()).sections.flatMap(\.tasks)
    }

    /// Inbox → a new project with its outcome and the item as its first Next action, as one change.
    @discardableResult
    package func clarifyInboxAsProject(_ id: TaskID, projectName: String, outcome: String, firstAction: String) -> Bool {
        guard let task = workspace.task(id), task.state == .inbox, task.projectID == nil else {
            error = "Only an unassigned Inbox item can start a new project."
            return false
        }
        let projectID = ProjectID.random()
        var changes = TaskChanges(projectID: .set(projectID))
        if firstAction != task.title { changes.title = .set(firstAction) }
        return run {
            try workspace.apply([
                .createProject(.init(projectID: projectID, name: projectName, desiredOutcome: outcome)),
                .updateTask(.init(taskID: id, changes: changes)),
                .transitionTask(.init(taskID: id, action: .move, toList: .next)),
            ])
        }
    }

    /// The projects to review: active ones without a valid review mark, changed ones first.
    package func loadProjectReview() -> [ProjectReviewItem] {
        let state = self.state
        let now = reviewNow
        let items = projects.compactMap { project -> ProjectReviewItem? in
            guard localState.validProjectMark(for: project, in: state, now: now) == nil else { return nil }
            let tasks = state.tasks.values.filter { $0.projectID == project.id }
                .sorted { ($0.orderKey, $0.createdAt, $0.id) < ($1.orderKey, $1.createdAt, $1.id) }
            return ProjectReviewItem(
                project: project, tasks: tasks, signature: localState.signature(ofProject: project.id, in: state),
                lastReview: localState.projectMark(for: project), hasChanges: localState.projectChangedSinceReview(project, in: state)
            )
        }
        return items.sorted { lhs, rhs in
            if lhs.hasChanges != rhs.hasChanges { return lhs.hasChanges }
            let left = lhs.lastReview?.reviewedAt ?? .distantPast
            let right = rhs.lastReview?.reviewedAt ?? .distantPast
            if left != right { return left < right }
            return lhs.project.name.localizedStandardCompare(rhs.project.name) == .orderedAscending
        }
    }

    /// Records the decision, unless the project's tasks changed since the review opened.
    @discardableResult
    package func markProjectReviewed(_ item: ProjectReviewItem, decision: ProjectReviewDecision) -> Bool {
        guard let project = workspace.project(item.id), project.state == .active,
            localState.signature(ofProject: item.id, in: state) == item.signature
        else {
            error = "Project changed elsewhere. Reopen the review to inspect its current actions."
            return false
        }
        let signature = item.signature
        return markReviewed { $0.markProjectReviewed(project, decision: decision, signature: signature, at: now()) }
    }

    /// A sidecar write; marks never touch the document, so they are never an outbox operation.
    @discardableResult
    private func markReviewed(_ change: (inout MacLocalState) -> Void) -> Bool {
        updateLocalState(change)
    }

    @discardableResult
    private func updateLocalState(_ change: (inout MacLocalState) -> Void) -> Bool {
        let state = self.state
        do {
            localState = try localStateStore.update { local in
                local.rekey(in: state)
                change(&local)
            }
            error = nil
            return true
        } catch {
            self.error = "Brain Buddy couldn't save this on this Mac. Try again."
            return false
        }
    }

    // MARK: Projects and tags

    package func createProject(_ name: String) -> ProjectID? {
        do {
            let id = try workspace.createProject(name: name)
            error = nil
            return id
        } catch {
            self.error = error.message
            return nil
        }
    }

    package func createTag(_ name: String) -> TagID? {
        do {
            let id = try workspace.createTag(name: name)
            error = nil
            return id
        } catch {
            self.error = error.message
            return nil
        }
    }

    /// Rename, allowed on archived projects too (X-06 "rename archived project").
    @discardableResult
    package func renameProject(_ id: ProjectID, to name: String) -> Bool {
        guard let project = workspace.project(id) else { return false }
        if NameNormalizer.display(name) == project.name { return true }
        let renamed = run { try workspace.renameProject(id, to: name) }
        if renamed, unarchiveRefusal?.projectID == id { unarchiveRefusal = nil }
        return renamed
    }

    /// Sets or clears (blank) the desired outcome; the project's review mark goes with it, as before 021.
    @discardableResult
    package func saveProjectOutcome(_ id: ProjectID, to outcome: String) -> Bool {
        guard let project = workspace.project(id) else { return false }
        let trimmed = outcome.trimmingCharacters(in: .whitespacesAndNewlines)
        if trimmed == (project.desiredOutcome ?? "") { return true }
        guard run({ try workspace.setProjectOutcome(id, outcome: trimmed) }) else { return false }
        updateLocalState { $0.clearProjectReview(project) }
        return true
    }

    /// The File-menu and context-menu guard: no archive while a task edit is unsaved or the capture
    /// draft is not empty, so a draft's project can never change under it.
    package var canArchiveProject: Bool {
        !taskEditInProgress && draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    /// Archives, keeping every task's project (ADR-0020). On the open project the screen stays and
    /// becomes the archived view; the Archived section opens to show its row (X-06 "archived (just now)").
    @discardableResult
    package func archiveProject(_ id: ProjectID) -> Bool {
        guard canArchiveProject else {
            error = "Add or clear the current task draft before archiving a project."
            return false
        }
        guard run({ try workspace.archiveProject(id) }) else { return false }
        if destination == .project(id) { selectedList = .inbox }
        projectStateChanges += 1
        if !localState.sidebar.archivedProjectsExpanded { setArchivedProjectsExpanded(true) }
        return true
    }

    /// Unarchives with every task. A name another active project has is refused at once, with
    /// "Rename…" and no Retry (X-06 "unarchive refused: name in use").
    @discardableResult
    package func unarchiveProject(_ id: ProjectID) -> Bool {
        guard let project = workspace.project(id) else { return false }
        do {
            try workspace.unarchiveProject(id)
            error = nil
            unarchiveRefusal = nil
            lastUnarchivedName = project.name
            projectStateChanges += 1
            updateLocalState { $0.clearProjectReview(project) }
            return true
        } catch {
            if case .unarchiveNameInUse = error {
                unarchiveRefusal = UnarchiveRefusal(projectID: id, message: error.message)
            } else {
                self.error = error.message
            }
            return false
        }
    }

    package func setArchivedProjectsExpanded(_ expanded: Bool) {
        updateLocalState { $0.sidebar.archivedProjectsExpanded = expanded }
    }

    @discardableResult
    package func renameTag(_ id: TagID, to name: String) -> Bool {
        guard let tag = workspace.tag(id) else { return false }
        if NameNormalizer.tagDisplay(name) == tag.name { return true }
        return run { try workspace.renameTag(id, to: name) }
    }

    @discardableResult
    package func deleteTag(_ id: TagID) -> Bool {
        guard run({ try workspace.deleteTag(id) }) else { return false }
        if destination == .tag(id) { choose(.list(.next)) }
        return true
    }

    // MARK: Subtasks and comments

    package func loadTaskDetail(_ id: TaskID) async {
        await workspace.refreshTaskDetails(id)
    }

    @discardableResult
    package func addSubtask(to id: TaskID, title: String) -> Bool {
        run { _ = try workspace.addSubtask(to: id, title: title) }
    }

    @discardableResult
    package func renameSubtask(_ subtaskID: SubtaskID, in id: TaskID, title: String) -> Bool {
        run { try workspace.renameSubtask(subtaskID, in: id, to: title) }
    }

    package func toggleSubtask(_ subtask: SubtaskRecord, in id: TaskID) {
        run { try workspace.transitionSubtask(subtask.id, in: id, subtask.state == .open ? .complete : .reopen) }
    }

    @discardableResult
    package func addComment(to id: TaskID, body: String) -> Bool {
        run { _ = try workspace.addComment(to: id, body: body) }
    }

    @discardableResult
    package func editComment(_ commentID: CommentID, in id: TaskID, body: String) -> Bool {
        run { try workspace.editComment(commentID, in: id, body: body) }
    }

    package func isOwnComment(_ comment: CommentRecord) -> Bool { workspace.isOwnComment(comment) }

    // MARK: Saving on this Mac

    /// The name of the project unarchived by the last change, for the X-06 error copy.
    @ObservationIgnored private var lastUnarchivedName: String?

    /// A failed write of `store.json`: the changes stay applied here and are written again with
    /// the next change or "Retry" (X-06 "error": "Couldn't unarchive “Old flat”. Try again.").
    package var storageFailureMessage: String? {
        guard let message = workspace.storageError else { return nil }
        if let name = lastUnarchivedName { return "Couldn't unarchive “\(name)”. Try again." }
        return message
    }

    /// "Retry" after a failed write.
    package func retrySaving() async {
        await workspace.flush()
        if workspace.storageError == nil { lastUnarchivedName = nil }
    }

    // MARK: Footer

    /// The sidebar footer's line from the kit's describer: "On this Mac · Sign in to sync" while
    /// account-less (its "Sign in to sync" action arrives with X-03 in PR-09).
    package var syncLine: SyncStatusDescription {
        SyncStatusDescriber.describe(workspace.syncSnapshot, now: now(), device: .mac, calendar: .current)
    }
}
