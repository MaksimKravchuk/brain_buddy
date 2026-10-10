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
    /// One bounded project query page; counts/signature cover the complete canonical project.
    package var tasks: [TaskRecord]
    package let signature: String
    package let canonicalProjectID: ProjectID
    package let recordKeys: [String]
    package let primaryRecordKey: String
    package let countsByState: [TaskState: Int]?
    package var taskPageState: WorkspaceQueryPageState
    /// The last review, valid or not.
    package let lastReview: ProjectReviewMark?
    /// A review exists but the project's tasks changed since.
    package let hasChanges: Bool

    package var id: ProjectID { project.id }
    package var openTasks: [TaskRecord] { tasks.filter(\.isOpen) }
    package func count(_ state: TaskState) -> Int {
        if let countsByState { return countsByState[state] ?? 0 }
        return openTasks.filter { $0.state == state }.count
    }
    package var nextCount: Int { count(.next) }
    package var waitingCount: Int { count(.waiting) }
    package var somedayCount: Int { count(.someday) }
    package var openTaskCount: Int {
        if let countsByState { return OpenList.allCases.reduce(0) { $0 + (countsByState[$1.taskState] ?? 0) } }
        return openTasks.count
    }
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
    package private(set) var isSaving = false
    package private(set) var captureEditorID = UUID().uuidString

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
    /// Invalidates SwiftUI after a prepared Workspace answer publishes.
    package private(set) var queryRevision = 0
    package private(set) var waitingReviewStamps: [TaskID: RustWorkspaceTaskContentStamp] = [:]
    package private(set) var somedayReviewStamps: [TaskID: RustWorkspaceTaskContentStamp] = [:]
    package private(set) var waitingReviewStampReadiness: WorkspaceQueryReadiness = .notRequested
    package private(set) var somedayReviewStampReadiness: WorkspaceQueryReadiness = .notRequested
    package private(set) var waitingReviewStampGeneration: UInt64?
    package private(set) var somedayReviewStampGeneration: UInt64?
    package private(set) var projectReviewStamps: [ProjectID: RustWorkspaceProjectContentStamp] = [:]
    package private(set) var projectReviewStampReadiness: WorkspaceQueryReadiness = .notRequested
    package private(set) var projectReviewStampGeneration: UInt64?
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

    private var currentListOptions: ListOptions {
        ListOptions(
            sort: sort, groupByProject: destination == .list(.next) && groupByProject,
            showCompleted: !destination.isHistory, showCancelled: !destination.isHistory && showCancelled,
            priorities: appliedPriority.map { [$0] } ?? [], search: appliedSearch
        )
    }
    package var listReadiness: WorkspaceQueryReadiness {
        _ = queryRevision
        return workspace.listReadiness(destination.query, options: currentListOptions)
    }
    package var listPageState: WorkspaceQueryPageState {
        _ = queryRevision
        return workspace.listPageState(destination.query, options: currentListOptions)
    }
    package var visibleListOptions: ListOptions { currentListOptions }
    package var countsReadiness: WorkspaceQueryReadiness {
        _ = queryRevision
        return workspace.countsReadiness()
    }
    package var projectsReadiness: WorkspaceQueryReadiness {
        _ = queryRevision
        return workspace.projectsReadiness()
    }
    package var archivedProjectsReadiness: WorkspaceQueryReadiness {
        _ = queryRevision
        return workspace.projectsReadiness(archived: true)
    }
    package var tagsReadiness: WorkspaceQueryReadiness {
        _ = queryRevision
        return workspace.tagsReadiness()
    }
    package var projectsPageState: WorkspaceQueryPageState {
        _ = queryRevision
        return workspace.projectsPageState()
    }
    package var archivedProjectsPageState: WorkspaceQueryPageState {
        _ = queryRevision
        return workspace.projectsPageState(archived: true)
    }
    package var projectReviewReadiness: WorkspaceQueryReadiness {
        _ = queryRevision
        let readiness = workspace.projectsReadiness()
        guard readiness == .ready, workspace.isRustSelected else { return readiness }
        let ids = workspace.projects().map(\.project).filter { $0.state == .active }.map(\.id)
        let stampReadiness = workspace.reviewContentStampsReadiness(key: localState.installSalt, projects: ids)
        if case .failed = projectReviewStampReadiness, stampReadiness == .ready { return projectReviewStampReadiness }
        guard stampReadiness == .ready, let answer = workspace.reviewContentStamps(key: localState.installSalt, projects: ids) else { return stampReadiness }
        if let projectReviewStampGeneration, projectReviewStampGeneration != answer.generation {
            return .failed("REVIEW_PAGE_CHANGED")
        }
        return stampReadiness
    }
    package var tagsPageState: WorkspaceQueryPageState {
        _ = queryRevision
        return workspace.tagsPageState()
    }
    package var projectReadiness: WorkspaceQueryReadiness {
        guard case .project(let id) = destination else { return .ready }
        _ = queryRevision
        return workspace.projectSummaryReadiness(id)
    }
    package var visibleReadiness: WorkspaceQueryReadiness {
        if listReadiness != .ready { return listReadiness }
        if let result = listResult {
            for id in Set(result.sections.flatMap(\.tasks).compactMap(\.projectID)) {
                let readiness = workspace.projectDisplayReadiness(id)
                if readiness != .ready { return readiness }
            }
        }
        guard case .project(let id) = destination else { return .ready }
        let summary = workspace.projectSummaryReadiness(id)
        if summary != .ready { return summary }
        let next = workspace.firstNextActionReadiness(id)
        if next != .ready { return next }
        return workspace.projectDisplayReadiness(id)
    }

    /// Prepare exactly the reads used by the visible native surfaces. Legacy workspaces keep the
    /// synchronous accessors as their source of truth; Rust workspaces publish a revision only
    /// after each bounded answer has settled.
    package func prepareVisibleQueries() async {
        await workspace.prepareCounts()
        await workspace.prepareList(destination.query, options: currentListOptions)
        if workspace.listReadiness(destination.query, options: currentListOptions) == .ready {
            await prepareProjectDisplays(for: workspace.list(destination.query, options: currentListOptions))
        }
        if case .project(let id) = destination {
            await workspace.prepareProjectSummary(id)
            await workspace.prepareFirstNextAction(id)
            await workspace.prepareProjectDisplay(id)
        }
        await workspace.prepareProjects()
        await workspace.prepareProjects(archived: true)
        await workspace.prepareTags()
        await workspace.prepareCapturePreview(captureDraft)
        queryRevision &+= 1
    }

    private func prepareProjectDisplays(for result: TaskListResult) async {
        let projectIDs = Set(result.sections.flatMap(\.tasks).compactMap(\.projectID))
        for id in projectIDs { await workspace.prepareProjectDisplay(id) }
    }

    package func prepareCapturePreview(_ draft: CaptureDraft) async {
        await workspace.prepareCapturePreview(draft)
        queryRevision &+= 1
    }

    package func prepareQuickOpen(_ input: String) async {
        let term = input.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !term.isEmpty else { await prepareVisibleQueries(); return }
        await workspace.prepareProjects(search: term)
        await workspace.prepareProjects(archived: true, search: term)
        await workspace.prepareTags(search: term)
        await workspace.prepareList(.search(term), options: ListOptions(search: term))
        if workspace.listReadiness(.search(term), options: ListOptions(search: term)) == .ready {
            await prepareProjectDisplays(for: workspace.list(.search(term), options: ListOptions(search: term)))
        }
        queryRevision &+= 1
    }

    package func quickOpenReadiness(_ input: String) -> WorkspaceQueryReadiness {
        _ = queryRevision
        let term = input.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !term.isEmpty else {
            let states = [workspace.projectsReadiness(), workspace.projectsReadiness(archived: true), workspace.tagsReadiness()]
            return states.first(where: { if case .failed = $0 { return true }; return false })
                ?? (states.allSatisfy { $0 == .ready } ? .ready : .loading)
        }
        let states = [
            workspace.projectsReadiness(search: term), workspace.projectsReadiness(archived: true, search: term),
            workspace.tagsReadiness(search: term), workspace.listReadiness(.search(term), options: ListOptions(search: term))
        ]
        return states.first(where: { if case .failed = $0 { return true }; return false })
            ?? (states.allSatisfy { $0 == .ready } ? .ready : .loading)
    }

    package func refreshQueryPresentation() { queryRevision &+= 1 }

    // MARK: Collections

    package var projects: [ProjectRecord] {
        _ = queryRevision
        guard workspace.projectsReadiness() == .ready else { return [] }
        return workspace.projects().map(\.project)
    }
    package var archivedProjects: [ProjectRecord] {
        _ = queryRevision
        guard workspace.projectsReadiness(archived: true) == .ready else { return [] }
        return workspace.projects(archived: true).map(\.project)
    }
    package var tags: [TagRecord] {
        _ = queryRevision
        guard workspace.tagsReadiness() == .ready else { return [] }
        return workspace.tags().map(\.tag)
    }
    package var sidebarCounts: ListCounts {
        _ = queryRevision
        guard workspace.countsReadiness() == .ready else { return ListCounts() }
        return workspace.counts()
    }

    package func task(_ id: TaskID) -> TaskRecord? { workspace.task(id) }
    package func project(_ id: ProjectID) -> ProjectRecord? { workspace.project(id) }
    package func tag(_ id: TagID) -> TagRecord? { workspace.tag(id) }
    package func projectDisplay(_ id: ProjectID) -> ProjectDisplay? {
        _ = queryRevision
        guard workspace.projectDisplayReadiness(id) == .ready else { return nil }
        return workspace.projectDisplay(id)
    }
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
        _ = queryRevision
        guard listReadiness == .ready else { return [] }
        return workspace.list(destination.query, options: currentListOptions).sections
    }

    package var listResult: TaskListResult? {
        _ = queryRevision
        guard listReadiness == .ready else { return nil }
        return workspace.list(destination.query, options: currentListOptions)
    }

    /// Every task on screen, in order.
    package var tasks: [TaskRecord] { sections.flatMap(\.tasks) }
    package var openTaskCount: Int { listResult?.openCount ?? 0 }

    package func projectOverview(_ id: ProjectID) -> ProjectOverview? {
        guard workspace.projectSummaryReadiness(id) == .ready,
              workspace.firstNextActionReadiness(id) == .ready,
              let summary = workspace.projectSummary(id), let display = projectDisplay(id) else { return nil }
        let project = summary.project
        let counts: [TaskList: Int] = Dictionary(uniqueKeysWithValues: OpenList.allCases.map { ($0, summary.countsByState?[$0] ?? 0) })
        let next = workspace.firstNextAction(id)
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
        _ = queryRevision
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
        let activeProjects = term.isEmpty || workspace.projectsReadiness(search: term) == .ready
            ? workspace.projects(search: term).map(\.project) : []
        let oldProjects = term.isEmpty || workspace.projectsReadiness(archived: true, search: term) == .ready
            ? workspace.projects(archived: true, search: term).map(\.project) : []
        for project in activeProjects + oldProjects {
            results.append(
                .init(
                    id: "project:\(project.id.rawValue)", title: project.name,
                    subtitle: project.state == .archived ? "Archived project" : "Project", symbol: "square.stack",
                    target: .project(project.id)
                )
            )
        }
        let matchingTags = term.isEmpty || workspace.tagsReadiness(search: term) == .ready
            ? workspace.tags(search: term).map(\.tag) : []
        for tag in matchingTags {
            results.append(.init(id: "tag:\(tag.id.rawValue)", title: "#\(tag.name)", subtitle: "Tag", symbol: "tag", target: .tag(tag.id)))
        }
        guard !term.isEmpty else { return results }
        let options = ListOptions(search: term)
        guard workspace.listReadiness(.search(term), options: options) == .ready else { return results }
        for task in workspace.list(.search(term), options: options).sections.flatMap(\.tasks) {
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

    package var capturePreview: CapturePreview {
        _ = queryRevision
        return workspace.capturePreview(captureDraft)
    }
    package var capturePreviewReadiness: WorkspaceQueryReadiness {
        _ = queryRevision
        return workspace.capturePreviewReadiness(captureDraft)
    }

    package func createTask() async {
        guard !isSaving else { return }
        let captureList = selectedList
        let authoredDraft = captureDraft
        await workspace.prepareCapturePreview(authoredDraft)
        queryRevision &+= 1
        guard workspace.capturePreviewReadiness(authoredDraft) == .ready else {
            error = "Brain Buddy couldn't prepare this task. Try again."
            return
        }
        let preview = workspace.capturePreview(authoredDraft)
        if let message = preview.problemMessage, preview.problem != nil {
            error = message
            return
        }
        do {
            let id = try await durableSave(editorID: captureEditorID) {
                try await workspace.capture(authoredDraft, editorID: $0)
            }
            error = nil
            captureEditorID = UUID().uuidString
            guard captureDraft == authoredDraft else { return }
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
            self.error = (error as? GTDValidationError)?.message ?? "Brain Buddy couldn't save this change. Try again."
        }
    }

    /// Quick Capture (⌃⌥⇧B): to Inbox, never touching the main window's draft or screen.
    package func quickCaptureInbox(_ title: String, editorID: String = UUID().uuidString) async throws {
        try await durableSave(editorID: editorID) {
            try await workspace.capture(CaptureDraft(text: title, list: .inbox), editorID: $0)
        }
    }

    // MARK: Tasks

    /// Runs a write: on a refusal the kit's words become `error` and nothing changed.
    @discardableResult
    private func durableSave<Value>(editorID: String, _ body: (String) async throws -> Value) async throws -> Value {
        guard !isSaving else { throw RustBridgeError(code: "STORE_BUSY") }
        isSaving = true
        defer { isSaving = false }
        return try await body(editorID)
    }

    @discardableResult
    private func run(editorID: String = UUID().uuidString, _ body: (String) async throws -> Void) async -> Bool {
        lastUnarchivedName = nil
        do {
            try await durableSave(editorID: editorID, body)
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
    package func completeTask(_ id: TaskID, editorID: String = UUID().uuidString) async -> Bool {
        await run(editorID: editorID) { try await workspace.completeTask(id, editorID: $0) }
    }

    @discardableResult
    package func cancelTask(_ id: TaskID, editorID: String = UUID().uuidString) async -> Bool {
        await run(editorID: editorID) { try await workspace.cancelTask(id, editorID: $0) }
    }

    @discardableResult
    package func reopenTask(_ id: TaskID, to list: TaskList, waitingFor: String?, editorID: String = UUID().uuidString) async -> Bool {
        let reason = list == .waiting ? waitingFor : nil
        return await run(editorID: editorID) {
            try await workspace.reopenTask(id, to: list, waitingFor: reason, editorID: $0)
        }
    }

    @discardableResult
    package func moveTask(_ id: TaskID, to list: TaskList, waitingFor: String? = nil, editorID: String = UUID().uuidString) async -> Bool {
        guard let task = workspace.task(id), task.state != list.taskState else { return false }
        let reason = list == .waiting ? waitingFor : nil
        return await run(editorID: editorID) {
            try await workspace.moveTask(id, to: list, waitingFor: reason, editorID: $0)
        }
    }

    /// The inline editor's save: the changed fields first, then the move, as one change
    /// (`Workspace.apply`, T047). Only touched fields are sent (FR-009).
    @discardableResult
    package func saveTask(_ id: TaskID, changes: TaskChanges, moveTo list: TaskList? = nil, editorID: String = UUID().uuidString) async -> Bool {
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
        guard await run(editorID: editorID, { try await workspace.apply(commands, editorID: $0) }) else { return false }
        if destination == .list(.inbox), let updated = workspace.task(id), updated.state == .inbox, let projectID = updated.projectID {
            choose(.project(projectID))
        }
        return true
    }

    /// The Waiting review's "Create follow-up…": a separate Next action in the same project, and the
    /// Waiting item marked reviewed in the sidecar (it returns after 7 days or a change).
    @discardableResult
    package func createFollowUp(for id: TaskID, title: String, taskID: TaskID = .random(), editorID: String = UUID().uuidString, shownTask: TaskRecord? = nil) async -> Bool {
        let task = workspace.isRustSelected ? shownTask : workspace.task(id)
        guard let task, task.id == id, task.state == .waiting else {
            error = "This task is no longer in Waiting for. Refresh the review."
            return false
        }
        if isArchived(task.projectID) {
            error = "Unarchive this project before creating a follow-up in it."
            return false
        }
        let shownStamp = waitingReviewStamps[id]
        if workspace.isRustSelected {
            guard let shownStamp else {
                error = "This Waiting review is no longer ready. Reopen it to inspect the task."
                return false
            }
            do {
                let current = try await workspace.prepareReviewContentStamps(key: localState.installSalt, tasks: [id])
                guard let latest = Self.reviewStamp(for: id, in: current), latest.taskID == shownStamp.taskID, latest.stamp == shownStamp.stamp else {
                    error = "This Waiting task changed. Reopen the review to inspect it."
                    return false
                }
            } catch {
                self.error = "This Waiting task could not be checked. Reopen the review to try again."
                return false
            }
        }
        let command = GTDCommand.createTask(.init(taskID: taskID, title: title, list: .next, projectID: task.projectID))
        guard await run(editorID: editorID, { try await workspace.apply([command], editorID: $0) }) else { return false }
        if workspace.isRustSelected, let shownStamp {
            markReviewed { $0.markWaitingReviewed(shownStamp.stamp, recordKeys: shownStamp.recordKeys, primaryRecordKey: shownStamp.primaryRecordKey, at: now()) }
        } else {
            markReviewed { $0.markWaitingReviewed(task, in: workspace.state, at: now()) }
        }
        return true
    }

    // MARK: Reviews (marks in mac-local.json)

    private var reviewNow: Date { now() }

    private static func reviewStamp(for requestedID: TaskID, in answer: RustWorkspaceReviewContentStamps) -> RustWorkspaceTaskContentStamp? {
        answer.tasks.values.first { stamp in
            stamp.taskID == requestedID || stamp.recordKeys.contains("c:\(requestedID.rawValue)")
        }
    }

    package func loadWaitingReviewTasks() async -> [TaskRecord] {
        waitingReviewStampReadiness = .loading
        await workspace.prepareList(.list(.waiting), options: ListOptions())
        guard workspace.listReadiness(.list(.waiting), options: ListOptions()) == .ready else {
            waitingReviewStampReadiness = workspace.listReadiness(.list(.waiting), options: ListOptions())
            queryRevision &+= 1
            return []
        }
        let result = workspace.list(.list(.waiting), options: ListOptions())
        await prepareProjectDisplays(for: result)
        let tasks = result.sections.flatMap(\.tasks)
        if workspace.isRustSelected {
            do {
                let answer = try await workspace.prepareReviewContentStamps(key: localState.installSalt, tasks: tasks.map(\.id))
                let mappedStamps = tasks.compactMap { task in Self.reviewStamp(for: task.id, in: answer).map { (task.id, $0) } }
                guard mappedStamps.count == tasks.count else {
                    waitingReviewStampReadiness = .failed("CANONICAL_RECORD_UNAVAILABLE")
                    waitingReviewStamps = [:]
                    queryRevision &+= 1
                    return []
                }
                waitingReviewStamps = Dictionary(uniqueKeysWithValues: mappedStamps)
                waitingReviewStampGeneration = answer.generation
                waitingReviewStampReadiness = .ready
                queryRevision &+= 1
                let reviewNow = self.reviewNow
                return tasks.filter { task in
                    guard let stamp = Self.reviewStamp(for: task.id, in: answer) else { return false }
                    return localState.waitingReviewDue(task, stamp: stamp.stamp, recordKeys: stamp.recordKeys, now: reviewNow)
                }
            } catch {
                waitingReviewStampReadiness = .failed((error as? RustBridgeError)?.code ?? "WORKSPACE_NOT_READY")
                waitingReviewStamps = [:]
                queryRevision &+= 1
                return []
            }
        }
        waitingReviewStampReadiness = .ready
        queryRevision &+= 1
        let state = self.state
        return tasks.filter { localState.waitingReviewDue($0, in: state, now: reviewNow) }
    }
    package func reviewListReadiness(_ list: TaskList) -> WorkspaceQueryReadiness {
        _ = queryRevision
        let readiness = workspace.listReadiness(.list(list), options: ListOptions())
        guard readiness == .ready else { return readiness }
        let result = workspace.list(.list(list), options: ListOptions())
        for id in Set(result.sections.flatMap(\.tasks).compactMap(\.projectID)) {
            let projectReadiness = workspace.projectDisplayReadiness(id)
            if projectReadiness != .ready { return projectReadiness }
        }
        if workspace.isRustSelected, list == .waiting {
            let ids = result.sections.flatMap(\.tasks).map(\.id)
            let readiness = workspace.reviewContentStampsReadiness(key: localState.installSalt, tasks: ids)
            if case .failed = waitingReviewStampReadiness, readiness == .ready { return waitingReviewStampReadiness }
            guard readiness == .ready, let answer = workspace.reviewContentStamps(key: localState.installSalt, tasks: ids) else { return readiness }
            if let waitingReviewStampGeneration, waitingReviewStampGeneration != answer.generation { return .failed("REVIEW_PAGE_CHANGED") }
            return readiness
        }
        if workspace.isRustSelected, list == .someday {
            let ids = result.sections.flatMap(\.tasks).map(\.id)
            let readiness = workspace.reviewContentStampsReadiness(key: localState.installSalt, tasks: ids)
            if case .failed = somedayReviewStampReadiness, readiness == .ready { return somedayReviewStampReadiness }
            guard readiness == .ready, let answer = workspace.reviewContentStamps(key: localState.installSalt, tasks: ids) else { return readiness }
            if let somedayReviewStampGeneration, somedayReviewStampGeneration != answer.generation { return .failed("REVIEW_PAGE_CHANGED") }
            return readiness
        }
        return .ready
    }
    package func reviewListPageState(_ list: TaskList) -> WorkspaceQueryPageState {
        _ = queryRevision
        return workspace.listPageState(.list(list), options: ListOptions())
    }
    package func nextReviewListPage(_ list: TaskList) async {
        await workspace.nextListPage(.list(list), options: ListOptions())
        queryRevision &+= 1
    }

    @discardableResult
    package func keepWaiting(_ id: TaskID) -> Bool {
        guard !workspace.isRustSelected, let task = workspace.task(id), task.state == .waiting else {
            error = "This Waiting task changed. Reopen the review to inspect it."
            return false
        }
        return markReviewed { $0.markWaitingReviewed(task, in: workspace.state, at: now()) }
    }

    @discardableResult
    package func keepWaiting(_ shownTask: TaskRecord) async -> Bool {
        guard shownTask.state == .waiting, workspace.isRustSelected,
              let shown = waitingReviewStamps[shownTask.id] else {
            error = "This Waiting review is no longer ready. Reopen it to inspect the task."
            return false
        }
        do {
            let current = try await workspace.prepareReviewContentStamps(key: localState.installSalt, tasks: [shownTask.id])
            guard let latest = Self.reviewStamp(for: shownTask.id, in: current), latest.taskID == shown.taskID,
                  latest.stamp == shown.stamp else {
                error = "This Waiting task changed. Reopen the review to inspect it."
                return false
            }
            return markReviewed { $0.markWaitingReviewed(shown.stamp, recordKeys: shown.recordKeys, primaryRecordKey: shown.primaryRecordKey, at: now()) }
        } catch {
            self.error = "This Waiting task could not be checked. Reopen the review to try again."
            return false
        }
    }

    package func loadSomedayReviewTasks() async -> [TaskRecord] {
        somedayReviewStampReadiness = .loading
        await workspace.prepareList(.list(.someday), options: ListOptions())
        guard workspace.listReadiness(.list(.someday), options: ListOptions()) == .ready else {
            somedayReviewStampReadiness = workspace.listReadiness(.list(.someday), options: ListOptions())
            queryRevision &+= 1
            return []
        }
        let result = workspace.list(.list(.someday), options: ListOptions())
        await prepareProjectDisplays(for: result)
        let tasks = result.sections.flatMap(\.tasks)
        if workspace.isRustSelected {
            do {
                let answer = try await workspace.prepareReviewContentStamps(key: localState.installSalt, tasks: tasks.map(\.id))
                let mappedStamps = tasks.compactMap { task in Self.reviewStamp(for: task.id, in: answer).map { (task.id, $0) } }
                guard mappedStamps.count == tasks.count else {
                    somedayReviewStampReadiness = .failed("CANONICAL_RECORD_UNAVAILABLE")
                    somedayReviewStamps = [:]
                    queryRevision &+= 1
                    return []
                }
                somedayReviewStamps = Dictionary(uniqueKeysWithValues: mappedStamps)
                somedayReviewStampGeneration = answer.generation
                somedayReviewStampReadiness = .ready
                queryRevision &+= 1
                let reviewNow = self.reviewNow
                return tasks.filter { task in
                    guard let stamp = Self.reviewStamp(for: task.id, in: answer) else { return false }
                    return localState.somedayReviewDue(task, stamp: stamp.stamp, recordKeys: stamp.recordKeys, now: reviewNow)
                }
            } catch {
                somedayReviewStampReadiness = .failed((error as? RustBridgeError)?.code ?? "WORKSPACE_NOT_READY")
                somedayReviewStamps = [:]
                queryRevision &+= 1
                return []
            }
        }
        somedayReviewStampReadiness = .ready
        queryRevision &+= 1
        let state = self.state
        return tasks.filter { localState.somedayReviewDue($0, in: state, now: reviewNow) }
    }

    @discardableResult
    package func keepSomeday(_ id: TaskID) -> Bool {
        guard !workspace.isRustSelected, let task = workspace.task(id), task.state == .someday else {
            error = "This Someday task changed. Reopen the review to inspect it."
            return false
        }
        return markReviewed { $0.markSomedayReviewed(task, in: workspace.state, at: now()) }
    }

    @discardableResult
    package func keepSomeday(_ shownTask: TaskRecord) async -> Bool {
        guard shownTask.state == .someday, workspace.isRustSelected,
              let shown = somedayReviewStamps[shownTask.id] else {
            error = "This Someday review is no longer ready. Reopen it to inspect the task."
            return false
        }
        do {
            let current = try await workspace.prepareReviewContentStamps(key: localState.installSalt, tasks: [shownTask.id])
            guard let latest = Self.reviewStamp(for: shownTask.id, in: current), latest.taskID == shown.taskID,
                  latest.stamp == shown.stamp else {
                error = "This Someday task changed. Reopen the review to inspect it."
                return false
            }
            return markReviewed { $0.markSomedayReviewed(shown.stamp, recordKeys: shown.recordKeys, primaryRecordKey: shown.primaryRecordKey, at: now()) }
        } catch {
            self.error = "This Someday task could not be checked. Reopen the review to try again."
            return false
        }
    }

    /// "Make it a Next action…": the new title and the move, as one change.
    @discardableResult
    package func activateSomeday(_ id: TaskID, title: String, editorID: String = UUID().uuidString) async -> Bool {
        guard let task = workspace.task(id), task.state == .someday else {
            error = "This Someday task changed. Reopen the review to inspect it."
            return false
        }
        var commands: [GTDCommand] = []
        if title != task.title { commands.append(.updateTask(.init(taskID: id, changes: TaskChanges(title: .set(title))))) }
        commands.append(.transitionTask(.init(taskID: id, action: .move, toList: .next)))
        return await run(editorID: editorID) {
            try await workspace.apply(commands, editorID: $0)
        }
    }

    package func loadInboxClarificationTasks() async -> [TaskRecord] {
        await workspace.prepareList(.list(.inbox), options: ListOptions())
        guard workspace.listReadiness(.list(.inbox), options: ListOptions()) == .ready else {
            queryRevision &+= 1
            return []
        }
        queryRevision &+= 1
        workspace.list(.list(.inbox), options: ListOptions()).sections.flatMap(\.tasks)
    }

    /// Inbox → a new project with its outcome (optional; blank is none) and the item as its first
    /// Next action, as one change.
    @discardableResult
    package func clarifyInboxAsProject(_ id: TaskID, projectName: String, outcome: String?, firstAction: String,
        projectID: ProjectID = .random(), editorID: String = UUID().uuidString) async -> Bool {
        guard let task = workspace.task(id), task.state == .inbox, task.projectID == nil else {
            error = "Only an unassigned Inbox item can start a new project."
            return false
        }
        let trimmedOutcome = outcome?.trimmingCharacters(in: .whitespacesAndNewlines)
        let desiredOutcome = trimmedOutcome?.isEmpty == false ? trimmedOutcome : nil
        var changes = TaskChanges(projectID: .set(projectID))
        if firstAction != task.title { changes.title = .set(firstAction) }
        return await run(editorID: editorID) {
            try await workspace.clarifyAsProject(id, projectName: projectName, outcome: desiredOutcome,
                firstAction: firstAction, changes: changes, editorID: $0)
        }
    }

    /// The projects to review: active ones without a valid review mark, changed ones first.
    package func loadProjectReview() async -> [ProjectReviewItem] {
        projectReviewStampReadiness = .loading
        await workspace.prepareProjects()
        queryRevision &+= 1
        guard workspace.projectsReadiness() == .ready else { return [] }
        let activeProjects = projects.filter { $0.state == .active }
        if workspace.isRustSelected {
            do {
                let answer = try await workspace.prepareReviewContentStamps(key: localState.installSalt, projects: activeProjects.map(\.id))
                let mappedStamps = activeProjects.compactMap { project in Self.projectStamp(for: project.id, in: answer).map { (project.id, $0) } }
                guard mappedStamps.count == activeProjects.count else {
                    projectReviewStampReadiness = .failed("CANONICAL_RECORD_UNAVAILABLE")
                    projectReviewStamps = [:]
                    queryRevision &+= 1
                    return []
                }
                projectReviewStamps = Dictionary(uniqueKeysWithValues: mappedStamps)
                projectReviewStampGeneration = answer.generation
                projectReviewStampReadiness = .ready
                queryRevision &+= 1
                var items: [ProjectReviewItem] = []
                for project in activeProjects {
                    guard let stamp = Self.projectStamp(for: project.id, in: answer) else {
                        projectReviewStampReadiness = .failed("CANONICAL_RECORD_UNAVAILABLE")
                        continue
                    }
                    let mark = localState.projectMark(recordKeys: stamp.recordKeys)
                    if localState.validProjectMark(for: project, signature: stamp.signature, recordKeys: stamp.recordKeys, now: reviewNow) != nil { continue }
                    let options = projectReviewTaskOptions
                    await workspace.prepareList(.project(project.id), options: options)
                    let pageState = workspace.listPageState(.project(project.id), options: options)
                    let taskPage = pageState.readiness == .ready
                        ? workspace.list(.project(project.id), options: options).sections.flatMap(\.tasks) : []
                    items.append(ProjectReviewItem(
                        project: project, tasks: taskPage, signature: stamp.signature,
                        canonicalProjectID: stamp.projectID, recordKeys: stamp.recordKeys, primaryRecordKey: stamp.primaryRecordKey,
                        countsByState: stamp.countsByState, taskPageState: pageState,
                        lastReview: mark,
                        hasChanges: localState.projectChangedSinceReview(project, signature: stamp.signature, recordKeys: stamp.recordKeys)
                    ))
                }
                return sortProjectReviewItems(items)
            } catch {
                projectReviewStampReadiness = .failed((error as? RustBridgeError)?.code ?? "WORKSPACE_NOT_READY")
                projectReviewStamps = [:]
                queryRevision &+= 1
                return []
            }
        }
        projectReviewStampReadiness = .ready
        let state = self.state
        let items = activeProjects.compactMap { project -> ProjectReviewItem? in
            guard localState.validProjectMark(for: project, in: state, now: reviewNow) == nil else { return nil }
            let tasks = state.tasks.values.filter { $0.projectID == project.id }
                .sorted { ($0.orderKey, $0.createdAt, $0.id) < ($1.orderKey, $1.createdAt, $1.id) }
            let options = projectReviewTaskOptions
            let pageState = WorkspaceQueryPageState(readiness: .ready)
            return ProjectReviewItem(
                project: project, tasks: tasks, signature: localState.signature(ofProject: project.id, in: state),
                canonicalProjectID: project.id, recordKeys: RecordKey.candidates(serverID: project.serverID, clientID: project.id.rawValue),
                primaryRecordKey: RecordKey.of(project), countsByState: nil, taskPageState: pageState,
                lastReview: localState.projectMark(for: project), hasChanges: localState.projectChangedSinceReview(project, in: state)
            )
        }
        return sortProjectReviewItems(items)
    }

    private var projectReviewTaskOptions: ListOptions {
        ListOptions(showCompleted: true, showCancelled: true)
    }

    private static func projectStamp(for requestedID: ProjectID, in answer: RustWorkspaceReviewContentStamps) -> RustWorkspaceProjectContentStamp? {
        answer.projects.values.first { stamp in
            stamp.projectID == requestedID || stamp.recordKeys.contains("c:\(requestedID.rawValue)")
        }
    }

    private func sortProjectReviewItems(_ items: [ProjectReviewItem]) -> [ProjectReviewItem] {
        items.sorted { lhs, rhs in
            if lhs.hasChanges != rhs.hasChanges { return lhs.hasChanges }
            let left = lhs.lastReview?.reviewedAt ?? .distantPast
            let right = rhs.lastReview?.reviewedAt ?? .distantPast
            if left != right { return left < right }
            return lhs.project.name.localizedStandardCompare(rhs.project.name) == .orderedAscending
        }
    }

    package func projectReviewTaskPageState(_ item: ProjectReviewItem) -> WorkspaceQueryPageState {
        guard workspace.isRustSelected else { return WorkspaceQueryPageState(readiness: .ready) }
        return workspace.listPageState(.project(item.id), options: projectReviewTaskOptions)
    }

    package func nextProjectReviewTaskPage(_ item: ProjectReviewItem) async -> [TaskRecord] {
        await workspace.nextListPage(.project(item.id), options: projectReviewTaskOptions)
        queryRevision &+= 1
        guard workspace.listReadiness(.project(item.id), options: projectReviewTaskOptions) == .ready else { return [] }
        return workspace.list(.project(item.id), options: projectReviewTaskOptions).sections.flatMap(\.tasks)
    }

    package func previousProjectReviewTaskPage(_ item: ProjectReviewItem) async -> [TaskRecord] {
        await workspace.previousListPage(.project(item.id), options: projectReviewTaskOptions)
        queryRevision &+= 1
        guard workspace.listReadiness(.project(item.id), options: projectReviewTaskOptions) == .ready else { return [] }
        return workspace.list(.project(item.id), options: projectReviewTaskOptions).sections.flatMap(\.tasks)
    }

    package func reloadProjectReviewTaskPage(_ item: ProjectReviewItem) async -> [TaskRecord] {
        await workspace.prepareList(.project(item.id), options: projectReviewTaskOptions)
        queryRevision &+= 1
        guard workspace.listReadiness(.project(item.id), options: projectReviewTaskOptions) == .ready else { return [] }
        return workspace.list(.project(item.id), options: projectReviewTaskOptions).sections.flatMap(\.tasks)
    }

    /// Records a decision against the exact displayed signature. Legacy compatibility remains synchronous.
    @discardableResult
    package func markProjectReviewed(_ item: ProjectReviewItem, decision: ProjectReviewDecision) -> Bool {
        guard !workspace.isRustSelected, let project = workspace.project(item.id), project.state == .active,
            localState.signature(ofProject: item.id, in: state) == item.signature
        else {
            error = "Project changed elsewhere. Reopen the review to inspect its current actions."
            return false
        }
        let signature = item.signature
        return markReviewed { $0.markProjectReviewed(project, decision: decision, signature: signature, at: now()) }
    }

    @discardableResult
    private func clearNativeProjectReview(_ id: ProjectID) async {
        do {
            let answer = try await workspace.prepareReviewContentStamps(key: localState.installSalt, projects: [id])
            guard let stamp = Self.projectStamp(for: id, in: answer) else { return }
            updateLocalState { $0.clearProjectReview(recordKeys: stamp.recordKeys) }
        } catch {
            // The durable document write already succeeded; never fabricate sidecar identity keys.
        }
    }

    package func markNativeProjectReviewed(_ item: ProjectReviewItem, decision: ProjectReviewDecision) async -> Bool {
        guard workspace.isRustSelected else {
            error = "Project review is no longer ready. Reopen it to inspect current actions."
            return false
        }
        do {
            let records = try await workspace.prepareRecords([.project(item.id)])
            guard let project = records.projects[item.id], project.state == .active else {
                error = "Project changed elsewhere. Reopen the review to inspect its current actions."
                return false
            }
            let current = try await workspace.prepareReviewContentStamps(key: localState.installSalt, projects: [item.id])
            guard let latest = Self.projectStamp(for: item.id, in: current), latest.projectID == item.canonicalProjectID,
                  latest.signature == item.signature else {
                error = "Project actions changed elsewhere. Reopen the review to inspect current actions."
                return false
            }
            return markReviewed { $0.markProjectReviewed(
                decision: decision, signature: item.signature, recordKeys: item.recordKeys,
                primaryRecordKey: item.primaryRecordKey, at: now()
            ) }
        } catch {
            self.error = "This project could not be checked. Reopen the review to try again."
            return false
        }
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
                if !workspace.isRustSelected { local.rekey(in: state) }
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

    package func createProject(_ name: String, editorID: String = UUID().uuidString) async -> ProjectID? {
        do {
            let id = try await durableSave(editorID: editorID) {
                try await workspace.createProject(name: name, editorID: $0)
            }
            error = nil
            return id
        } catch {
            self.error = (error as? GTDValidationError)?.message ?? "Brain Buddy couldn't save this change. Try again."
            return nil
        }
    }

    package func createTag(_ name: String, editorID: String = UUID().uuidString) async -> TagID? {
        do {
            let id = try await durableSave(editorID: editorID) {
                try await workspace.createTag(name: name, editorID: $0)
            }
            error = nil
            return id
        } catch {
            self.error = (error as? GTDValidationError)?.message ?? "Brain Buddy couldn't save this change. Try again."
            return nil
        }
    }

    /// Rename, allowed on archived projects too (X-06 "rename archived project").
    @discardableResult
    package func renameProject(_ id: ProjectID, to name: String, editorID: String = UUID().uuidString) async -> Bool {
        guard let project = workspace.project(id) else { return false }
        if NameNormalizer.display(name) == project.name { return true }
        let renamed = await run(editorID: editorID) {
            try await workspace.renameProject(id, to: name, editorID: $0)
        }
        if renamed, unarchiveRefusal?.projectID == id { unarchiveRefusal = nil }
        return renamed
    }

    /// Sets or clears (blank) the desired outcome; the project's review mark goes with it, as before 021.
    @discardableResult
    package func saveProjectOutcome(_ id: ProjectID, to outcome: String, editorID: String = UUID().uuidString) async -> Bool {
        guard let project = workspace.project(id) else { return false }
        let trimmed = outcome.trimmingCharacters(in: .whitespacesAndNewlines)
        if trimmed == (project.desiredOutcome ?? "") { return true }
        guard await run(editorID: editorID, {
            try await workspace.setProjectOutcome(id, outcome: trimmed.isEmpty ? nil : trimmed, editorID: $0)
        }) else { return false }
        if workspace.isRustSelected { await clearNativeProjectReview(id) }
        else { updateLocalState { $0.clearProjectReview(project) } }
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
    package func archiveProject(_ id: ProjectID, editorID: String = UUID().uuidString) async -> Bool {
        guard canArchiveProject else {
            error = "Add or clear the current task draft before archiving a project."
            return false
        }
        guard await run(editorID: editorID, { try await workspace.archiveProject(id, editorID: $0) }) else { return false }
        if destination == .project(id) { selectedList = .inbox }
        projectStateChanges += 1
        if !localState.sidebar.archivedProjectsExpanded { setArchivedProjectsExpanded(true) }
        return true
    }

    /// Unarchives with every task. A name another active project has is refused at once, with
    /// "Rename…" and no Retry (X-06 "unarchive refused: name in use").
    @discardableResult
    package func unarchiveProject(_ id: ProjectID, editorID: String = UUID().uuidString) async -> Bool {
        guard let project = workspace.project(id) else { return false }
        do {
            try await durableSave(editorID: editorID) {
                try await workspace.unarchiveProject(id, editorID: $0)
            }
            error = nil
            unarchiveRefusal = nil
            lastUnarchivedName = project.name
            projectStateChanges += 1
            if workspace.isRustSelected { await clearNativeProjectReview(id) }
            else { updateLocalState { $0.clearProjectReview(project) } }
            return true
        } catch {
            if let refusal = error as? GTDValidationError, case .unarchiveNameInUse = refusal {
                unarchiveRefusal = UnarchiveRefusal(projectID: id, message: refusal.message)
            } else {
                self.error = (error as? GTDValidationError)?.message ?? "Brain Buddy couldn't save this change. Try again."
            }
            return false
        }
    }

    package func setArchivedProjectsExpanded(_ expanded: Bool) {
        updateLocalState { $0.sidebar.archivedProjectsExpanded = expanded }
    }

    @discardableResult
    package func renameTag(_ id: TagID, to name: String, editorID: String = UUID().uuidString) async -> Bool {
        guard let tag = workspace.tag(id) else { return false }
        if NameNormalizer.tagDisplay(name) == tag.name { return true }
        return await run(editorID: editorID) { try await workspace.renameTag(id, to: name, editorID: $0) }
    }

    @discardableResult
    package func deleteTag(_ id: TagID, editorID: String = UUID().uuidString) async -> Bool {
        guard await run(editorID: editorID, { try await workspace.deleteTag(id, editorID: $0) }) else { return false }
        if destination == .tag(id) { choose(.list(.next)) }
        return true
    }

    // MARK: Subtasks and comments

    package func loadTaskDetail(_ id: TaskID) async {
        await workspace.refreshTaskDetails(id)
    }

    @discardableResult
    package func addSubtask(to id: TaskID, title: String, editorID: String = UUID().uuidString) async -> Bool {
        await run(editorID: editorID) { _ = try await workspace.addSubtask(to: id, title: title, editorID: $0) }
    }

    @discardableResult
    package func renameSubtask(_ subtaskID: SubtaskID, in id: TaskID, title: String, editorID: String = UUID().uuidString) async -> Bool {
        await run(editorID: editorID) { try await workspace.renameSubtask(subtaskID, in: id, to: title, editorID: $0) }
    }

    package func toggleSubtask(_ subtask: SubtaskRecord, in id: TaskID, editorID: String = UUID().uuidString) async -> Bool {
        await run(editorID: editorID) {
            try await workspace.transitionSubtask(subtask.id, in: id, subtask.state == .open ? .complete : .reopen, editorID: $0)
        }
    }

    @discardableResult
    package func addComment(to id: TaskID, body: String, editorID: String = UUID().uuidString) async -> Bool {
        await run(editorID: editorID) { _ = try await workspace.addComment(to: id, body: body, editorID: $0) }
    }

    @discardableResult
    package func editComment(_ commentID: CommentID, in id: TaskID, body: String, editorID: String = UUID().uuidString) async -> Bool {
        await run(editorID: editorID) { try await workspace.editComment(commentID, in: id, body: body, editorID: $0) }
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

    /// The kit's describer over this workspace: "On this Mac · Sign in to sync" while account-less.
    /// The window's footer is `SyncStatusLine` over `MacSyncController.line` (PR-09).
    package var syncLine: SyncStatusDescription {
        SyncStatusDescriber.describe(workspace.syncSnapshot, now: now(), device: .mac, calendar: .current)
    }

    // MARK: Sign-out

    /// After a sign-out (design X-04 "empty (first run) after sign-out"): the workspace is empty and
    /// account-less, the selection goes to Inbox, and the drafts the person chose to discard go.
    /// Review marks in the sidecar are kept.
    package func didSignOut() {
        draft = ""
        waitingForDraft = ""
        taskEditInProgress = false
        unarchiveRefusal = nil
        choose(.list(.inbox))
    }
}
