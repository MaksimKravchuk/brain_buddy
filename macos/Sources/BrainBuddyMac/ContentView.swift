import SwiftUI

struct ProjectReviewItem: Identifiable {
    let project: BrainBuddyProject
    let tasks: [BrainBuddyTask]

    var id: String { project.id }
    var openTasks: [BrainBuddyTask] { tasks.filter { TaskList(rawValue: $0.state) != nil } }
    var nextCount: Int { openTasks.filter { $0.state == TaskList.next.rawValue }.count }
    var waitingCount: Int { openTasks.filter { $0.state == TaskList.waiting.rawValue }.count }
    var somedayCount: Int { openTasks.filter { $0.state == TaskList.someday.rawValue }.count }
}

@MainActor
final class BrainBuddyModel: ObservableObject {
    static let defaultURL = "https://brain-buddy-frontend.fly.dev/api"

    @Published var serverURL = UserDefaults.standard.string(forKey: "BrainBuddyAPIURL") ?? defaultURL
    @Published var account: Account?
    @Published var selectedList: TaskList = .next
    @Published var destination: WorkspaceDestination = .list(.next)
    @Published var searchText = ""
    @Published var groupByProject = true
    @Published var showCancelled = false
    @Published var priorityFilter: PriorityFilter = .all
    @Published var sort: TaskSort = .manual
    @Published var projects: [BrainBuddyProject] = []
    @Published var archivedProjects: [BrainBuddyProject] = []
    @Published var projectNextAction: BrainBuddyTask?
    @Published var projectOverviewCounts: TaskCounts?
    @Published var tags: [BrainBuddyTag] = []
    @Published var tasks: [BrainBuddyTask] = []
    @Published var openCounts: TaskCounts?
    @Published var sidebarCounts: TaskCounts?
    @Published var taskDetails: [String: BrainBuddyTask] = [:]
    @Published var detailLoadingID: String?
    @Published var nextCursor: String?
    @Published var loading = false
    @Published var busy = false
    @Published var error: String?
    @Published var sessionExpired = false
    @Published var syncConflictTaskID: String?
    @Published var syncConflictCurrentLoaded = false
    @Published var syncConflictRetryApproved = false
    @Published var draft = "" {
        didSet {
            if draft != oldValue {
                pendingCreate = nil
                captureNotice = nil
            }
        }
    }
    @Published var captureNotice: String?
    @Published var waitingForDraft = "" {
        didSet { if waitingForDraft != oldValue { pendingCreate = nil } }
    }

    private let api: APIClient
    private let store: any GTDStore
    let isLocalWorkspace: Bool
    private struct CaptureSignature: Encodable {
        let title: String
        let state: String
        let waitingFor: String?
        let project: ClassificationRef?
        let tags: [ClassificationRef]
    }
    private var pendingCreate: (signature: Data, key: UUID)?
    private var pendingCompleteKeys: [String: UUID] = [:]
    private var pendingTerminalKeys: [String: (signature: String, key: UUID)] = [:]
    private var pendingUpdateKeys: [String: (signature: String, key: UUID)] = [:]
    private var pendingMoveKeys: [String: (signature: String, key: UUID)] = [:]
    private var pendingSubtaskCreate: [String: (title: String, key: UUID)] = [:]
    private var pendingCommentCreate: [String: (body: String, key: UUID)] = [:]
    private var pendingFollowUpCreate: [String: (title: String, key: UUID)] = [:]
    private var pendingInboxProject: [String: (signature: String, key: UUID)] = [:]
    private var pendingCollectionCreate: [String: (name: String, key: UUID)] = [:]
    private var pendingCollectionChange: [String: (signature: String, key: UUID)] = [:]
    private var pendingSubtaskUpdate: [String: (signature: String, key: UUID)] = [:]
    private var pendingCommentUpdate: [String: (signature: String, key: UUID)] = [:]
    private var displayedQuery: TaskQuery?

    var hasAppliedTaskFilter: Bool {
        displayedQuery?.q != nil || displayedQuery?.priority != nil
    }
    private var listRequestSerial = 0
    private var authRequestSerial = 0
    private var suspendedDraft: (ownerID: String, apiIdentity: String, title: String, waitingFor: String)?

    private var apiIdentity: String {
        api.baseURL.absoluteString.trimmingCharacters(in: CharacterSet(charactersIn: "/"))
    }

    init(api: APIClient? = nil, store: (any GTDStore)? = nil) {
        let remote = api ?? APIClient(baseURL: URL(string: Self.defaultURL)!)
        self.api = remote
        if let store {
            self.store = store
            isLocalWorkspace = true
        } else if api != nil {
            self.store = remote
            isLocalWorkspace = false
        } else {
            self.store = LocalGTDStore(fileURL: LocalGTDStore.defaultFileURL())
            isLocalWorkspace = true
        }
        if isLocalWorkspace {
            account = Account(id: "local", email: "", display_name: "On this Mac")
        }
    }

    private func clearSession(preservingDraft: Bool = false) {
        if preservingDraft, let ownerID = account?.id,
           !draft.isEmpty || !waitingForDraft.isEmpty {
            suspendedDraft = (ownerID, apiIdentity, draft, waitingForDraft)
        } else if !preservingDraft {
            suspendedDraft = nil
        }
        authRequestSerial += 1
        listRequestSerial += 1
        account = nil
        tasks = []
        openCounts = nil
        sidebarCounts = nil
        taskDetails = [:]
        detailLoadingID = nil
        projects = []
        archivedProjects = []
        projectNextAction = nil
        projectOverviewCounts = nil
        tags = []
        nextCursor = nil
        loading = false
        draft = ""
        captureNotice = nil
        waitingForDraft = ""
        pendingCreate = nil
        pendingCompleteKeys.removeAll()
        pendingTerminalKeys.removeAll()
        pendingUpdateKeys.removeAll()
        pendingMoveKeys.removeAll()
        syncConflictTaskID = nil
        syncConflictCurrentLoaded = false
        syncConflictRetryApproved = false
        pendingSubtaskCreate.removeAll()
        pendingCommentCreate.removeAll()
        pendingFollowUpCreate.removeAll()
        pendingInboxProject.removeAll()
        pendingCollectionCreate.removeAll()
        pendingCollectionChange.removeAll()
        pendingSubtaskUpdate.removeAll()
        pendingCommentUpdate.removeAll()
        displayedQuery = nil
        sessionExpired = false
    }

    private func handleRequestFailure(_ failure: Error) {
        if let apiError = failure as? APIError, apiError.statusCode == 401 {
            if account == nil { clearSession(preservingDraft: true) }
            else { sessionExpired = true }
            error = "Session expired. Sign in again."
        } else {
            error = failure.localizedDescription
        }
    }

    func restore() async {
        if isLocalWorkspace {
            await loadCollections()
            await reload()
            return
        }
        guard !busy else { return }
        authRequestSerial += 1
        listRequestSerial += 1
        let serial = authRequestSerial
        do {
            try api.setBaseURL(serverURL)
            let restored = try await api.me()
            guard serial == authRequestSerial else { return }
            account = restored
            await reload()
        } catch {
            guard serial == authRequestSerial else { return }
            clearSession(preservingDraft: true)
            if let apiError = error as? APIError, apiError.statusCode == 401 {
                self.error = nil
            } else {
                self.error = error.localizedDescription
            }
        }
    }

    func signIn(email: String, password: String) async {
        guard !busy else { return }
        authRequestSerial += 1
        listRequestSerial += 1
        loading = false
        let serial = authRequestSerial
        let requestedURL = serverURL
        let priorAPIIdentity = apiIdentity
        busy = true
        error = nil
        defer { busy = false }
        do {
            try api.setBaseURL(requestedURL)
            let signedIn = try await api.login(email: email, password: password)
            guard serial == authRequestSerial else { return }
            let previousOwnerID = account?.id
            let continuingSession = sessionExpired && previousOwnerID == signedIn.id
                && requestedURL.trimmingCharacters(in: CharacterSet(charactersIn: "/")) == priorAPIIdentity
            serverURL = requestedURL
            UserDefaults.standard.set(requestedURL, forKey: "BrainBuddyAPIURL")
            account = signedIn
            sessionExpired = false
            if previousOwnerID != nil && !continuingSession {
                tasks = []
                openCounts = nil
                sidebarCounts = nil
                taskDetails = [:]
                nextCursor = nil
            }
            let retainedDraft = suspendedDraft
            suspendedDraft = nil
            if continuingSession {
                // The editor and capture draft stay mounted while the account reauthenticates.
            } else if let retainedDraft,
               retainedDraft.ownerID == signedIn.id,
               retainedDraft.apiIdentity == apiIdentity {
                draft = retainedDraft.title
                waitingForDraft = retainedDraft.waitingFor
            } else {
                draft = ""
                waitingForDraft = ""
            }
            if continuingSession { await loadCollections() }
            else { await reload() }
        } catch {
            if serial == authRequestSerial { self.error = error.localizedDescription }
        }
    }

    func signOut() async {
        guard !isLocalWorkspace else { return }
        guard !busy else { return }
        authRequestSerial += 1
        listRequestSerial += 1
        let serial = authRequestSerial
        busy = true
        defer { busy = false }
        do {
            try await api.logout()
            guard serial == authRequestSerial else { return }
            clearSession()
            error = nil
        } catch {
            guard serial == authRequestSerial else { return }
            if let apiError = error as? APIError, apiError.statusCode == 401 {
                clearSession()
                self.error = nil
            } else {
                handleRequestFailure(error)
            }
        }
    }

    func choose(_ list: TaskList) async {
        destination = .list(list)
        selectedList = list
        await reload()
    }

    func choose(_ destination: WorkspaceDestination) async {
        self.destination = destination
        switch destination {
        case .list(let list): selectedList = list
        case .project, .tag: selectedList = .inbox
        case .date, .history: selectedList = .next
        }
        await reload()
    }

    private func query() -> TaskQuery {
        let search = searchText.trimmingCharacters(in: .whitespacesAndNewlines)
        var query: TaskQuery
        switch destination {
        case .list(let list):
            query = TaskQuery(state: list, unassignedProject: list == .inbox, includeCompleted: true)
        case .date(.overdue):
            query = TaskQuery(includeCompleted: true, dueBefore: Self.isoDay(Date()), sort: .due)
        case .date(.today):
            query = TaskQuery(includeCompleted: true, dueOn: Self.isoDay(Date()), sort: .due)
        case .date(.upcoming):
            query = TaskQuery(includeCompleted: true, dueAfter: Self.isoDay(Date()), sort: .due)
        case .project(let id):
            query = TaskQuery(projectID: id, includeCompleted: true)
        case .tag(let id):
            query = TaskQuery(tagID: id, includeCompleted: true)
        case .history(let state):
            query = TaskQuery(terminalState: state)
        }
        if !destination.isHistory { query.includeCancelled = showCancelled }
        if case .date = destination, sort == .manual { query.sort = .due }
        else { query.sort = sort }
        query.q = search.isEmpty ? nil : search
        query.priority = priorityFilter.priority
        return query
    }

    private static func isoDay(_ date: Date) -> String {
        let formatter = DateFormatter()
        formatter.dateFormat = "yyyy-MM-dd"
        formatter.locale = Locale(identifier: "en_US_POSIX")
        return formatter.string(from: date)
    }

    func loadCollections() async {
        do {
            async let fetchedProjects = store.listProjects()
            async let fetchedArchivedProjects = store.listArchivedProjects()
            async let fetchedTags = store.listTags()
            projects = try await fetchedProjects
            archivedProjects = try await fetchedArchivedProjects
            tags = try await fetchedTags
        } catch {
            handleRequestFailure(error)
        }
    }

    func quickOpenResults(_ input: String) async throws -> [QuickOpenResult] {
        let term = input.trimmingCharacters(in: .whitespacesAndNewlines)
        func matches(_ value: String) -> Bool {
            term.isEmpty || value.localizedStandardContains(term)
        }
        var results: [QuickOpenResult] = []
        for list in TaskList.allCases where matches(list.title) {
            results.append(QuickOpenResult(
                id: "list:\(list.rawValue)", title: list.title,
                subtitle: "GTD list", symbol: list.symbol, target: .list(list)
            ))
        }
        for state in [HistoryState.completed, .cancelled] where matches(state.title) {
            results.append(QuickOpenResult(
                id: "history:\(state.rawValue)", title: state.title,
                subtitle: "History", symbol: state.symbol, target: .history(state)
            ))
        }
        let allProjects = projects + archivedProjects
        for project in allProjects where matches(project.name) {
            results.append(QuickOpenResult(
                id: "project:\(project.id)", title: project.name,
                subtitle: project.state == "archived" ? "Archived project" : "Project",
                symbol: "square.stack", target: .project(project.id)
            ))
        }
        for tag in tags where matches(tag.name) {
            results.append(QuickOpenResult(
                id: "tag:\(tag.id)", title: "#\(tag.name)",
                subtitle: "Tag", symbol: "tag", target: .tag(tag.id)
            ))
        }
        guard !term.isEmpty else { return results }
        var cursor: String?
        var seenTaskIDs: Set<String> = []
        repeat {
            try Task.checkCancellation()
            let page = try await store.listTasks(
                query: TaskQuery(includeCompleted: true, includeCancelled: true, q: term),
                cursor: cursor
            )
            for task in page.items where seenTaskIDs.insert(task.id).inserted {
                let state = TaskList(rawValue: task.state)?.title ?? task.state.capitalized
                let project = allProjects.first(where: { $0.id == task.project_id })?.name
                let subtitle = (["Task", state] + [project].compactMap { $0 }).joined(separator: " · ")
                results.append(QuickOpenResult(
                    id: "task:\(task.id)", title: task.title,
                    subtitle: subtitle, symbol: "checkmark.circle", target: .task(task.id)
                ))
            }
            cursor = page.next_cursor
        } while cursor != nil
        return results
    }

    func quickOpenTask(_ id: String) async -> BrainBuddyTask? {
        do { return try await store.getTask(id) }
        catch {
            handleRequestFailure(error)
            return nil
        }
    }

    func loadProjectReview() async -> [ProjectReviewItem]? {
        error = nil
        do {
            let cutoff = Date().addingTimeInterval(-7 * 24 * 60 * 60)
            let projects = try await store.listProjects()
                .filter { project in
                    guard project.state == "active" else { return false }
                    guard let timestamp = project.last_reviewed_at,
                          let reviewed = ISO8601DateFormatter().date(from: timestamp) else { return true }
                    return project.review_has_changes == true || reviewed < cutoff
                }
                .sorted { lhs, rhs in
                    if lhs.review_has_changes != rhs.review_has_changes {
                        return lhs.review_has_changes == true
                    }
                    let left = lhs.last_reviewed_at ?? ""
                    let right = rhs.last_reviewed_at ?? ""
                    return left == right
                        ? lhs.name.localizedStandardCompare(rhs.name) == .orderedAscending
                        : left < right
                }
            var result: [ProjectReviewItem] = []
            for project in projects {
                var rows: [BrainBuddyTask] = []
                var cursor: String?
                repeat {
                    let page = try await store.listTasks(
                        query: TaskQuery(projectID: project.id, includeCompleted: true, includeCancelled: true),
                        cursor: cursor
                    )
                    rows.append(contentsOf: page.items)
                    cursor = page.next_cursor
                } while cursor != nil
                result.append(ProjectReviewItem(project: project, tasks: rows))
            }
            return result
        } catch {
            handleRequestFailure(error)
            return nil
        }
    }

    func markProjectReviewed(_ project: BrainBuddyProject, decision: ProjectReviewDecision) async -> Bool {
        guard !busy, let localStore = store as? LocalGTDStore else { return false }
        let operation = "review-project:\(project.id)"
        let signature = "\(project.revision)|\(decision.rawValue)"
        let pending = pendingCollectionChange[operation]
        let key = pending?.signature == signature ? pending!.key : UUID()
        pendingCollectionChange[operation] = (signature, key)
        busy = true
        error = nil
        defer { busy = false }
        do {
            _ = try await localStore.markProjectReviewed(project, decision: decision, idempotencyKey: key)
            pendingCollectionChange.removeValue(forKey: operation)
            await loadCollections()
            return true
        } catch {
            if let apiError = error as? APIError, apiError.statusCode == 409 {
                pendingCollectionChange.removeValue(forKey: operation)
                await loadCollections()
                self.error = "Project changed elsewhere. Reopen the review to inspect its current actions."
            } else { handleRequestFailure(error) }
            return false
        }
    }

    func reload() async {
        captureNotice = nil
        listRequestSerial += 1
        let serial = listRequestSerial
        let query = query()
        let previousRows = tasks
        let previousCounts = openCounts
        let previousSidebarCounts = sidebarCounts
        let previousProjectNextAction = projectNextAction
        let previousProjectOverviewCounts = projectOverviewCounts
        let previousCursor = nextCursor
        let previousQuery = displayedQuery
        if displayedQuery != nil && displayedQuery != query {
            tasks = []
            openCounts = nil
            projectNextAction = nil
            projectOverviewCounts = nil
            nextCursor = nil
            displayedQuery = nil
        }
        loading = true
        error = nil
        do {
            let page = try await store.listTasks(query: query)
            let globalCounts: TaskCounts?
            if isLocalWorkspace {
                let allPage = try await store.listTasks(query: TaskQuery())
                let inboxPage = try await store.listTasks(query: TaskQuery(
                    state: .inbox, unassignedProject: true
                ))
                guard let all = allPage.counts_by_state,
                      let inbox = inboxPage.counts_by_state?.inbox else {
                    throw APIError(message: "Local task counts are unavailable.")
                }
                globalCounts = TaskCounts(
                    inbox: inbox, next: all.next, waiting: all.waiting, someday: all.someday
                )
            } else {
                globalCounts = page.counts_by_state
            }
            var projectNext: BrainBuddyTask?
            var projectCounts: TaskCounts?
            if case .project(let id) = destination {
                let overview = try await store.listTasks(query: TaskQuery(projectID: id))
                let next = try await store.listTasks(query: TaskQuery(state: .next, projectID: id))
                projectCounts = overview.counts_by_state
                projectNext = next.items.first
            }
            guard serial == listRequestSerial else { return }
            tasks = page.items
            openCounts = page.counts_by_state
            sidebarCounts = globalCounts
            projectNextAction = projectNext
            projectOverviewCounts = projectCounts
            nextCursor = page.next_cursor
            displayedQuery = query
        } catch {
            if serial == listRequestSerial {
                if let apiError = error as? APIError, apiError.statusCode == 401 {
                    tasks = previousRows
                    openCounts = previousCounts
                    sidebarCounts = previousSidebarCounts
                    projectNextAction = previousProjectNextAction
                    projectOverviewCounts = previousProjectOverviewCounts
                    nextCursor = previousCursor
                    displayedQuery = previousQuery
                }
                handleRequestFailure(error)
            }
        }
        if serial == listRequestSerial { loading = false }
    }

    func clearTaskFilters() async {
        searchText = ""
        priorityFilter = .all
        await reload()
    }

    func loadMore() async {
        guard let cursor = nextCursor, let displayedQuery, !loading else { return }
        let serial = listRequestSerial
        loading = true
        do {
            let page = try await store.listTasks(query: displayedQuery, cursor: cursor)
            guard serial == listRequestSerial else { return }
            let loadedIDs = Set(tasks.map(\.id))
            tasks.append(contentsOf: page.items.filter { !loadedIDs.contains($0.id) })
            if let counts = page.counts_by_state { openCounts = counts }
            nextCursor = page.next_cursor
        } catch {
            if serial == listRequestSerial { handleRequestFailure(error) }
        }
        if serial == listRequestSerial { loading = false }
    }

    func loadWaitingReviewTasks() async -> [BrainBuddyTask]? {
        error = nil
        do {
            var result: [BrainBuddyTask] = []
            var cursor: String?
            repeat {
                let page = try await store.listTasks(query: TaskQuery(state: .waiting), cursor: cursor)
                result.append(contentsOf: page.items.filter { $0.state == TaskList.waiting.rawValue })
                cursor = page.next_cursor
            } while cursor != nil
            return result
        } catch {
            handleRequestFailure(error)
            return nil
        }
    }

    func loadInboxClarificationTasks() async -> [BrainBuddyTask]? {
        error = nil
        do {
            var result: [BrainBuddyTask] = []
            var cursor: String?
            repeat {
                let page = try await store.listTasks(
                    query: TaskQuery(state: .inbox, unassignedProject: true), cursor: cursor
                )
                result.append(contentsOf: page.items.filter {
                    $0.state == TaskList.inbox.rawValue && $0.project_id == nil
                })
                cursor = page.next_cursor
            } while cursor != nil
            return result
        } catch {
            handleRequestFailure(error)
            return nil
        }
    }

    func clarifyInboxAsProject(
        _ task: BrainBuddyTask, projectName: String, outcome: String, firstAction: String
    ) async -> Bool {
        guard !busy, let localStore = store as? LocalGTDStore else {
            error = "Project clarification is available in the local workspace."
            return false
        }
        let name = projectName.trimmingCharacters(in: .whitespacesAndNewlines)
        let desired = outcome.trimmingCharacters(in: .whitespacesAndNewlines)
        let action = firstAction.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !name.isEmpty, name.count <= 500,
              !desired.isEmpty, desired.count <= 1_000,
              !action.isEmpty, action.count <= 500 else {
            error = "Enter a project name, desired outcome, and first Next action within their limits."
            return false
        }
        let signature = "\(task.revision)|\(name)|\(desired)|\(action)"
        let pending = pendingInboxProject[task.id]
        let key = pending?.signature == signature ? pending!.key : UUID()
        pendingInboxProject[task.id] = (signature, key)
        busy = true
        error = nil
        defer { busy = false }
        do {
            let result = try await localStore.clarifyInboxAsProject(
                task, projectName: name, desiredOutcome: desired,
                firstAction: action, idempotencyKey: key
            )
            pendingInboxProject.removeValue(forKey: task.id)
            taskDetails[result.action.id] = result.action
            await loadCollections()
            await reload()
            return true
        } catch {
            handleRequestFailure(error)
            return false
        }
    }

    @discardableResult
    func loadTaskDetail(_ id: String) async -> Bool {
        detailLoadingID = id
        error = nil
        var loaded = false
        do {
            let detail = try await store.getTask(id)
            if detailLoadingID == id {
                taskDetails[id] = detail
                if syncConflictTaskID == id { syncConflictCurrentLoaded = true }
                loaded = true
            }
        } catch {
            if detailLoadingID == id { handleRequestFailure(error) }
        }
        if detailLoadingID == id { detailLoadingID = nil }
        return loaded
    }

    func clearSyncConflict(for taskID: String) {
        if syncConflictTaskID == taskID {
            syncConflictTaskID = nil
            syncConflictCurrentLoaded = false
            syncConflictRetryApproved = false
        }
    }

    func addSubtask(to taskID: String, title: String) async -> Bool {
        let trimmed = title.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty, trimmed.count <= 500, !busy else { return false }
        let pending = pendingSubtaskCreate[taskID]
        let key = pending?.title == trimmed ? pending!.key : UUID()
        pendingSubtaskCreate[taskID] = (trimmed, key)
        busy = true
        error = nil
        defer { busy = false }
        do {
            _ = try await store.createSubtask(taskID: taskID, title: trimmed, idempotencyKey: key)
            pendingSubtaskCreate.removeValue(forKey: taskID)
            await loadTaskDetail(taskID)
            return true
        } catch {
            handleRequestFailure(error)
            return false
        }
    }

    func renameSubtask(_ subtask: BrainBuddySubtask, in taskID: String, title: String) async -> Bool {
        let trimmed = title.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty, trimmed.count <= 500, !busy else { return false }
        let signature = "rename|\(subtask.revision)|\(trimmed)"
        let pending = pendingSubtaskUpdate[subtask.id]
        let key = pending?.signature == signature ? pending!.key : UUID()
        pendingSubtaskUpdate[subtask.id] = (signature, key)
        busy = true
        error = nil
        defer { busy = false }
        do {
            _ = try await store.updateSubtask(taskID: taskID, subtask: subtask, title: trimmed, idempotencyKey: key)
            pendingSubtaskUpdate.removeValue(forKey: subtask.id)
            await loadTaskDetail(taskID)
            return true
        } catch {
            if let apiError = error as? APIError, apiError.statusCode == 409 {
                pendingSubtaskUpdate.removeValue(forKey: subtask.id)
                if await loadTaskDetail(taskID),
                   let current = taskDetails[taskID]?.subtasks.first(where: { $0.id == subtask.id }) {
                    if current.title == trimmed { return true }
                    self.error = "Subtask changed elsewhere. Review its latest version, then save again."
                }
            } else { handleRequestFailure(error) }
            return false
        }
    }

    func toggleSubtask(_ subtask: BrainBuddySubtask, in taskID: String) async {
        guard !busy else { return }
        let action: SubtaskTransitionAction = subtask.state == "open" ? .complete : .reopen
        let signature = "transition|\(subtask.revision)|\(subtask.state)"
        let pending = pendingSubtaskUpdate[subtask.id]
        let key = pending?.signature == signature ? pending!.key : UUID()
        pendingSubtaskUpdate[subtask.id] = (signature, key)
        busy = true
        error = nil
        defer { busy = false }
        do {
            _ = try await store.transitionSubtask(
                taskID: taskID, subtask: subtask, action: action, idempotencyKey: key
            )
            pendingSubtaskUpdate.removeValue(forKey: subtask.id)
            await loadTaskDetail(taskID)
        } catch {
            if let apiError = error as? APIError, apiError.statusCode == 409 {
                pendingSubtaskUpdate.removeValue(forKey: subtask.id)
                if await loadTaskDetail(taskID) {
                    let target = action == .complete ? "completed" : "open"
                    if taskDetails[taskID]?.subtasks.first(where: { $0.id == subtask.id })?.state != target {
                        self.error = "Subtask changed elsewhere. Review its latest state, then try again."
                    }
                }
            } else { handleRequestFailure(error) }
        }
    }

    func addComment(to taskID: String, body: String) async -> Bool {
        let trimmed = body.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty, trimmed.count <= 20_000, !busy else { return false }
        let pending = pendingCommentCreate[taskID]
        let key = pending?.body == trimmed ? pending!.key : UUID()
        pendingCommentCreate[taskID] = (trimmed, key)
        busy = true
        error = nil
        defer { busy = false }
        do {
            _ = try await store.createComment(taskID: taskID, body: trimmed, idempotencyKey: key)
            pendingCommentCreate.removeValue(forKey: taskID)
            await loadTaskDetail(taskID)
            return true
        } catch {
            handleRequestFailure(error)
            return false
        }
    }

    func editComment(_ comment: BrainBuddyComment, in taskID: String, body: String) async -> Bool {
        let trimmed = body.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty, trimmed.count <= 20_000, !busy else { return false }
        let signature = "edit|\(comment.revision)|\(trimmed)"
        let pending = pendingCommentUpdate[comment.id]
        let key = pending?.signature == signature ? pending!.key : UUID()
        pendingCommentUpdate[comment.id] = (signature, key)
        busy = true
        error = nil
        defer { busy = false }
        do {
            _ = try await store.updateComment(taskID: taskID, comment: comment, body: trimmed, idempotencyKey: key)
            pendingCommentUpdate.removeValue(forKey: comment.id)
            await loadTaskDetail(taskID)
            return true
        } catch {
            if let apiError = error as? APIError, apiError.statusCode == 409 {
                pendingCommentUpdate.removeValue(forKey: comment.id)
                if await loadTaskDetail(taskID),
                   let current = taskDetails[taskID]?.comments.first(where: { $0.id == comment.id }) {
                    if current.body == trimmed { return true }
                    self.error = "Comment changed elsewhere. Review its latest version, then save again."
                }
            } else { handleRequestFailure(error) }
            return false
        }
    }

    func createTask() async {
        let contextProjectID: String?
        let contextTagID: String?
        if case .project(let id) = destination { contextProjectID = id }
        else { contextProjectID = nil }
        if case .tag(let id) = destination { contextTagID = id }
        else { contextTagID = nil }
        let interpreted = SmartAddParser.parse(
            draft, projects: projects, tags: tags,
            archivedProjects: archivedProjects,
            contextProjectId: contextProjectID, contextTagId: contextTagID
        )
        let captureState = selectedList
        let waitingFor = waitingForDraft.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !busy else { return }
        if let archivedProjectName = interpreted.archivedProjectName {
            error = "Restore the archived project \"\(archivedProjectName)\" before adding a task to it."
            return
        }
        guard interpreted.isValid else {
            error = "Enter a task title of 500 characters or fewer."
            return
        }
        if selectedList == .waiting && (waitingFor.isEmpty || waitingFor.count > 500) {
            error = "Enter who or what you are waiting for (up to 500 characters)."
            return
        }
        let signature: Data
        do {
            let encoder = JSONEncoder()
            encoder.outputFormatting = .sortedKeys
            signature = try encoder.encode(CaptureSignature(
                title: interpreted.cleanTitle, state: captureState.rawValue,
                waitingFor: captureState == .waiting ? waitingFor : nil,
                project: interpreted.project, tags: interpreted.tags
            ))
        } catch {
            self.error = error.localizedDescription
            return
        }
        let key = pendingCreate?.signature == signature ? pendingCreate!.key : UUID()
        pendingCreate = (signature, key)
        busy = true
        error = nil
        defer { busy = false }
        do {
            let created = try await store.smartAddTask(
                title: interpreted.cleanTitle,
                state: captureState,
                waitingFor: captureState == .waiting ? waitingFor : nil,
                project: interpreted.project,
                tags: interpreted.tags,
                idempotencyKey: key
            )
            draft = ""
            waitingForDraft = ""
            pendingCreate = nil
            await loadCollections()
            if captureState == .inbox, let projectID = created.task.project_id {
                await choose(.project(projectID))
            } else if captureState == selectedList {
                await reload()
            } else {
                await choose(.list(captureState))
            }
            if !tasks.contains(where: { $0.id == created.task.id }) {
                captureNotice = "Saved to \(captureState.title). Search, priority filters, or another page may hide it from these results."
            }
        } catch {
            handleRequestFailure(error)
        }
    }

    func completeTask(_ task: BrainBuddyTask) async {
        guard !busy else { return }
        let key = pendingCompleteKeys[task.id] ?? UUID()
        pendingCompleteKeys[task.id] = key
        busy = true
        error = nil
        defer { busy = false }
        do {
            _ = try await store.completeTask(task, idempotencyKey: key)
            pendingCompleteKeys.removeValue(forKey: task.id)
            await reload()
        } catch {
            handleRequestFailure(error)
        }
    }

    func reopenTask(_ task: BrainBuddyTask, to destination: TaskList, waitingFor: String?) async -> Bool {
        guard !busy else { return false }
        let trimmedWaitingFor = waitingFor?.trimmingCharacters(in: .whitespacesAndNewlines)
        if destination == .waiting && ((trimmedWaitingFor?.isEmpty ?? true) || (trimmedWaitingFor?.count ?? 0) > 500) {
            error = "Enter who or what you are waiting for (up to 500 characters)."
            return false
        }
        let signature = "reopen|\(task.revision)|\(destination.rawValue)|\(trimmedWaitingFor ?? "")"
        let pending = pendingTerminalKeys[task.id]
        let key = pending?.signature == signature ? pending!.key : UUID()
        pendingTerminalKeys[task.id] = (signature, key)
        busy = true
        error = nil
        defer { busy = false }
        do {
            _ = try await store.transitionTask(
                task, action: .reopen, toState: destination,
                waitingFor: destination == .waiting ? trimmedWaitingFor : nil,
                idempotencyKey: key
            )
            pendingTerminalKeys.removeValue(forKey: task.id)
            await reload()
            return true
        } catch {
            handleRequestFailure(error)
            return false
        }
    }

    @discardableResult
    func cancelTask(_ task: BrainBuddyTask) async -> Bool {
        guard !busy else { return false }
        let signature = "cancel|\(task.revision)"
        let pending = pendingTerminalKeys[task.id]
        let key = pending?.signature == signature ? pending!.key : UUID()
        pendingTerminalKeys[task.id] = (signature, key)
        busy = true
        error = nil
        defer { busy = false }
        do {
            _ = try await store.transitionTask(
                task, action: .cancel, toState: nil, waitingFor: nil, idempotencyKey: key
            )
            pendingTerminalKeys.removeValue(forKey: task.id)
            await reload()
            return true
        } catch {
            handleRequestFailure(error)
            return false
        }
    }

    func createFollowUp(for task: BrainBuddyTask, title: String) async -> Bool {
        let trimmed = title.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !busy else { return false }
        guard !trimmed.isEmpty, trimmed.count <= 500 else {
            error = "Enter a follow-up action of 500 characters or fewer."
            return false
        }
        guard task.state == TaskList.waiting.rawValue else {
            error = "This task is no longer in Waiting for. Refresh the review."
            return false
        }
        let pending = pendingFollowUpCreate[task.id]
        let key = pending?.title == trimmed ? pending!.key : UUID()
        pendingFollowUpCreate[task.id] = (trimmed, key)
        busy = true
        error = nil
        defer { busy = false }
        do {
            let current = try await store.getTask(task.id)
            guard current.state == TaskList.waiting.rawValue else {
                pendingFollowUpCreate.removeValue(forKey: task.id)
                self.error = "This task is no longer in Waiting for. Refresh the review."
                return false
            }
            if let projectID = current.project_id,
               archivedProjects.contains(where: { $0.id == projectID }) {
                pendingFollowUpCreate.removeValue(forKey: task.id)
                self.error = "Restore this project before creating a follow-up in it."
                return false
            }
            _ = try await store.smartAddTask(
                title: trimmed, state: .next, waitingFor: nil,
                project: current.project_id.map { .id($0) }, tags: [], idempotencyKey: key
            )
            pendingFollowUpCreate.removeValue(forKey: task.id)
            await loadCollections()
            await reload()
            return true
        } catch {
            handleRequestFailure(error)
            return false
        }
    }

    func saveTask(_ task: BrainBuddyTask, changes: TaskChanges, destinationState: TaskList?) async -> Bool {
        guard !busy else { return false }
        let signature = "\(task.revision)|\(String(reflecting: changes))|\(destinationState?.rawValue ?? "-")"
        let pendingUpdate = pendingUpdateKeys[task.id]
        let key = pendingUpdate?.signature == signature ? pendingUpdate!.key : UUID()
        pendingUpdateKeys[task.id] = (signature, key)
        let pendingMove = pendingMoveKeys[task.id]
        let moveKey = pendingMove?.signature == signature ? pendingMove!.key : UUID()
        pendingMoveKeys[task.id] = (signature, moveKey)
        busy = true
        error = nil
        defer { busy = false }
        do {
            var updated = task
            var applicableChanges = changes
            if destinationState?.rawValue != task.state {
                applicableChanges.waitingFor = .unchanged
            }
            if applicableChanges.hasChanges {
                updated = try await store.updateTask(updated, changes: applicableChanges, idempotencyKey: key)
            }
            if let destinationState, destinationState.rawValue != task.state {
                let waitingFor: String?
                if case .set(let value) = changes.waitingFor { waitingFor = value }
                else { waitingFor = task.waiting_for }
                updated = try await store.transitionTask(
                    updated, action: .move, toState: destinationState,
                    waitingFor: destinationState == .waiting ? waitingFor : nil,
                    idempotencyKey: moveKey
                )
            }
            pendingUpdateKeys.removeValue(forKey: task.id)
            pendingMoveKeys.removeValue(forKey: task.id)
            clearSyncConflict(for: task.id)
            taskDetails[task.id] = updated
            if case .list(.inbox) = destination,
               updated.state == TaskList.inbox.rawValue,
               let projectID = updated.project_id {
                await choose(.project(projectID))
            } else {
                await reload()
            }
            return true
        } catch {
            if let apiError = error as? APIError, apiError.statusCode == 409 {
                pendingUpdateKeys.removeValue(forKey: task.id)
                pendingMoveKeys.removeValue(forKey: task.id)
                syncConflictTaskID = task.id
                syncConflictCurrentLoaded = false
                syncConflictRetryApproved = false
                await loadTaskDetail(task.id)
            } else {
                handleRequestFailure(error)
            }
            return false
        }
    }

    func moveTask(_ task: BrainBuddyTask, to destination: TaskList, waitingFor: String? = nil) async -> Bool {
        guard task.state != destination.rawValue else { return false }
        let reason = waitingFor?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        if destination == .waiting && (reason.isEmpty || reason.count > 500) {
            error = "Enter who or what you are waiting for (up to 500 characters)."
            return false
        }
        let changes = destination == .waiting
            ? TaskChanges(waitingFor: .set(reason)) : TaskChanges()
        return await saveTask(task, changes: changes, destinationState: destination)
    }

    func createProject(_ name: String) async -> BrainBuddyProject? {
        let trimmed = name.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty, !busy else { return nil }
        let pending = pendingCollectionCreate["project"]
        let key = pending?.name == trimmed ? pending!.key : UUID()
        pendingCollectionCreate["project"] = (trimmed, key)
        busy = true
        error = nil
        defer { busy = false }
        do {
            let project = try await store.createProject(name: trimmed, idempotencyKey: key)
            pendingCollectionCreate.removeValue(forKey: "project")
            await loadCollections()
            return project
        } catch {
            handleRequestFailure(error)
            return nil
        }
    }

    func createTag(_ name: String) async -> BrainBuddyTag? {
        let trimmed = name.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty, !busy else { return nil }
        let pending = pendingCollectionCreate["tag"]
        let key = pending?.name == trimmed ? pending!.key : UUID()
        pendingCollectionCreate["tag"] = (trimmed, key)
        busy = true
        error = nil
        defer { busy = false }
        do {
            let tag = try await store.createTag(name: trimmed, idempotencyKey: key)
            pendingCollectionCreate.removeValue(forKey: "tag")
            await loadCollections()
            return tag
        } catch {
            handleRequestFailure(error)
            return nil
        }
    }

    func renameProject(_ id: String, to name: String) async -> Bool {
        let trimmed = name.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !busy, let project = projects.first(where: { $0.id == id }) else { return false }
        guard !trimmed.isEmpty, trimmed.count <= 500 else {
            error = "Project name must be 1–500 characters."
            return false
        }
        if trimmed == project.name { return true }
        let operation = "project:\(id)"
        let signature = "\(project.revision)|\(trimmed)"
        let pending = pendingCollectionChange[operation]
        let key = pending?.signature == signature ? pending!.key : UUID()
        pendingCollectionChange[operation] = (signature, key)
        busy = true
        error = nil
        defer { busy = false }
        do {
            _ = try await store.renameProject(project, to: trimmed, idempotencyKey: key)
            pendingCollectionChange.removeValue(forKey: operation)
            await loadCollections()
            return true
        } catch {
            if let apiError = error as? APIError, apiError.statusCode == 409 {
                pendingCollectionChange.removeValue(forKey: operation)
                await loadCollections()
                self.error = "Project changed elsewhere. Review its current name and try again."
            } else { handleRequestFailure(error) }
            return false
        }
    }

    func saveProjectOutcome(_ id: String, to outcome: String) async -> Bool {
        guard !busy, let project = projects.first(where: { $0.id == id }),
              let localStore = store as? LocalGTDStore else { return false }
        let trimmed = outcome.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty, trimmed.count <= 1_000 else {
            error = "Desired outcome must be 1–1,000 characters."
            return false
        }
        if trimmed == project.desired_outcome { return true }
        let operation = "outcome-project:\(id)"
        let signature = "\(project.revision)|\(trimmed)"
        let pending = pendingCollectionChange[operation]
        let key = pending?.signature == signature ? pending!.key : UUID()
        pendingCollectionChange[operation] = (signature, key)
        busy = true
        error = nil
        defer { busy = false }
        do {
            _ = try await localStore.updateProjectOutcome(project, to: trimmed, idempotencyKey: key)
            pendingCollectionChange.removeValue(forKey: operation)
            await loadCollections()
            return true
        } catch {
            if let apiError = error as? APIError, apiError.statusCode == 409 {
                pendingCollectionChange.removeValue(forKey: operation)
                await loadCollections()
                self.error = "Project changed elsewhere. Review its current outcome and try again."
            } else { handleRequestFailure(error) }
            return false
        }
    }

    func archiveProject(_ id: String) async -> Bool {
        guard !busy, let project = projects.first(where: { $0.id == id }) else { return false }
        guard draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            error = "Add or clear the current task draft before archiving a project."
            return false
        }
        let operation = "archive-project:\(id)"
        let signature = String(project.revision)
        let pending = pendingCollectionChange[operation]
        let key = pending?.signature == signature ? pending!.key : UUID()
        pendingCollectionChange[operation] = (signature, key)
        busy = true
        error = nil
        defer { busy = false }
        do {
            _ = try await store.archiveProject(project, idempotencyKey: key)
            pendingCollectionChange.removeValue(forKey: operation)
            await loadCollections()
            if destination == .project(id) { await choose(.list(.next)) }
            else { await reload() }
            return true
        } catch {
            handleRequestFailure(error)
            return false
        }
    }

    func unarchiveProject(_ id: String) async -> Bool {
        guard !busy, let project = archivedProjects.first(where: { $0.id == id }) else { return false }
        let operation = "unarchive-project:\(id)"
        let signature = String(project.revision)
        let pending = pendingCollectionChange[operation]
        let key = pending?.signature == signature ? pending!.key : UUID()
        pendingCollectionChange[operation] = (signature, key)
        busy = true
        error = nil
        defer { busy = false }
        do {
            _ = try await store.unarchiveProject(project, idempotencyKey: key)
            pendingCollectionChange.removeValue(forKey: operation)
            await loadCollections()
            await reload()
            return true
        } catch {
            handleRequestFailure(error)
            return false
        }
    }

    func renameTag(_ id: String, to name: String) async -> Bool {
        let trimmed = name.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !busy, let tag = tags.first(where: { $0.id == id }) else { return false }
        guard !trimmed.isEmpty, trimmed.count <= 500 else {
            error = "Tag name must be 1–500 characters."
            return false
        }
        if trimmed == tag.name { return true }
        let operation = "tag:\(id)"
        let signature = "\(tag.revision)|\(trimmed)"
        let pending = pendingCollectionChange[operation]
        let key = pending?.signature == signature ? pending!.key : UUID()
        pendingCollectionChange[operation] = (signature, key)
        busy = true
        error = nil
        defer { busy = false }
        do {
            _ = try await store.renameTag(tag, to: trimmed, idempotencyKey: key)
            pendingCollectionChange.removeValue(forKey: operation)
            await loadCollections()
            return true
        } catch {
            if let apiError = error as? APIError, apiError.statusCode == 409 {
                pendingCollectionChange.removeValue(forKey: operation)
                await loadCollections()
                self.error = "Tag changed elsewhere. Review its current name and try again."
            } else { handleRequestFailure(error) }
            return false
        }
    }

    func deleteTag(_ id: String) async -> Bool {
        guard !busy, let tag = tags.first(where: { $0.id == id }) else { return false }
        let operation = "delete-tag:\(id)"
        let signature = String(tag.revision)
        let pending = pendingCollectionChange[operation]
        let key = pending?.signature == signature ? pending!.key : UUID()
        pendingCollectionChange[operation] = (signature, key)
        busy = true
        error = nil
        defer { busy = false }
        do {
            _ = try await store.deleteTag(tag, idempotencyKey: key)
            pendingCollectionChange.removeValue(forKey: operation)
            await loadCollections()
            if destination == .tag(id) { await choose(.list(.next)) }
            else { await reload() }
            return true
        } catch {
            if let apiError = error as? APIError, apiError.statusCode == 409 {
                pendingCollectionChange.removeValue(forKey: operation)
                await loadCollections()
                self.error = "Tag changed elsewhere. Review it before deleting."
            } else { handleRequestFailure(error) }
            return false
        }
    }
}

enum DateDestination: String, Hashable {
    case overdue, today, upcoming

    var title: String { rawValue.capitalized }
    var symbol: String {
        switch self {
        case .overdue: "exclamationmark.triangle"
        case .today: "calendar"
        case .upcoming: "arrow.up.right"
        }
    }
}

enum WorkspaceDestination: Hashable {
    case list(TaskList)
    case date(DateDestination)
    case project(String)
    case tag(String)
    case history(HistoryState)

    var isHistory: Bool {
        if case .history = self { return true }
        return false
    }
}

enum HistoryState: String, Hashable {
    case completed, cancelled

    var title: String { rawValue.capitalized }
    var symbol: String { self == .completed ? "checkmark.circle" : "xmark.circle" }
}

private enum PendingEditorNavigation {
    case destination(WorkspaceDestination)
    case quickOpen(QuickOpenTarget)
    case task(String?)
    case complete(BrainBuddyTask)
    case move(BrainBuddyTask, TaskList)
    case reopen(BrainBuddyTask)
    case cancel(BrainBuddyTask)
    case newTask
    case reload
    case clearTaskFilters
    case signOut
    case createTask
    case reviewWaiting
    case reviewProjects
    case clarifyInbox
    case groupByProject(Bool)
    case showCancelled(Bool)
    case priorityFilter(PriorityFilter)
    case sort(TaskSort)

}

private func tagTint(_ id: String) -> Color {
    let palette: [Color] = [.purple, .teal, .green, .orange, .pink]
    let hash = id.utf8.reduce(UInt(0)) { ($0 &* 31) &+ UInt($1) }
    return palette[Int(hash % UInt(palette.count))]
}

private extension FieldChange {
    var isChanged: Bool {
        if case .unchanged = self { return false }
        return true
    }
}

private extension TaskChanges {
    var hasChanges: Bool {
        title.isChanged || details.isChanged || projectID.isChanged
            || tagIDs.isChanged || dueDate.isChanged || priority.isChanged
            || waitingFor.isChanged
    }
}

struct ContentView: View {
    @StateObject private var model = BrainBuddyModel()
    @State private var email = ""
    @State private var password = ""
    @State private var voicePresented = false
    @State private var selectedTaskID: String?
    @State private var editorTitle = ""
    @State private var editorDirty = false
    @State private var editorCanSave = false
    @State private var editorSaveRequest = 0
    @State private var pendingEditorNavigation: PendingEditorNavigation?
    @State private var confirmingDiscard = false
    @State private var pendingVoiceTranscript: String?
    @State private var confirmingReplaceDraft = false
    @State private var choosingCaptureList = false
    @State private var focusCaptureAfterChoice = false
    @State private var captureListChoice: TaskList = .next
    @State private var addingCollection: NewCollection?
    @State private var collectionName = ""
    @State private var editingCollection: CollectionToEdit?
    @State private var editedCollectionName = ""
    @State private var editingOutcomeProject: BrainBuddyProject?
    @State private var outcomeDraft = ""
    @State private var tagToDelete: BrainBuddyTag?
    @State private var confirmingTagDeletion = false
    @State private var reopeningTask: BrainBuddyTask?
    @State private var reopenDestination: TaskList = .next
    @State private var reopenWaitingFor = ""
    @State private var movingTask: BrainBuddyTask?
    @State private var moveWaitingFor = ""
    @State private var reviewingWaiting = false
    @State private var reviewingProjects = false
    @State private var clarifyingInbox = false
    @State private var quickOpenPresented = false
    @State private var pendingQuickOpenTarget: QuickOpenTarget?
    @State private var quickOpenedTask: BrainBuddyTask?
    @FocusState private var addFocused: Bool

    var body: some View {
        Group {
            if let account = model.account {
                NavigationSplitView {
                    sidebar(account: account)
                        .navigationSplitViewColumnWidth(min: 310, ideal: 340, max: 400)
                } detail: {
                    taskCanvas
                }
                .toolbar {
                    ToolbarItemGroup(placement: .primaryAction) {
                        Button {
                            requestNavigation(.newTask)
                        } label: {
                            Label("New task", systemImage: "plus")
                        }
                        .keyboardShortcut("n", modifiers: [.command])
                        Button {
                            quickOpenPresented = true
                        } label: {
                            Label("Quick Open", systemImage: "magnifyingglass.circle")
                        }
                        .keyboardShortcut("o", modifiers: [.command])
                        Button {
                            voicePresented = true
                        } label: {
                            Label("Voice to task draft", systemImage: "mic")
                        }
                        Button {
                            requestNavigation(.reload)
                        } label: {
                            Label("Refresh", systemImage: "arrow.clockwise")
                        }
                        .disabled(model.loading)
                        Picker("Priority", selection: Binding(
                            get: { model.priorityFilter },
                            set: { requestNavigation(.priorityFilter($0)) }
                        )) {
                            ForEach(PriorityFilter.allCases) { option in
                                Text(option.title).tag(option)
                            }
                        }
                        .pickerStyle(.menu)
                        .accessibilityLabel("Filter by priority")
                    }
                }
                .searchable(text: $model.searchText, placement: .toolbar, prompt: "Search tasks")
                .onSubmit(of: .search) { requestNavigation(.reload) }
                .onChange(of: model.searchText) { _, value in
                    if value.isEmpty { requestNavigation(.reload) }
                }
                .task { await model.loadCollections() }
            } else {
                signIn
            }
        }
        .opacity(model.sessionExpired ? 0 : 1)
        .allowsHitTesting(!model.sessionExpired)
        .overlay {
            if model.sessionExpired {
                signIn
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                    .background(Color(nsColor: .windowBackgroundColor))
            }
        }
        .task { await model.restore() }
        .sheet(isPresented: $quickOpenPresented, onDismiss: {
            if let target = pendingQuickOpenTarget {
                pendingQuickOpenTarget = nil
                requestNavigation(.quickOpen(target))
            }
        }) {
            QuickOpenView(model: model) { target in
                pendingQuickOpenTarget = target
                quickOpenPresented = false
            } onClose: {
                quickOpenPresented = false
            }
        }
        .onChange(of: model.account?.id) { previousID, accountID in
            if accountID != nil {
                password = ""
                if previousID != nil && previousID != accountID {
                    selectedTaskID = nil
                    editorDirty = false
                }
            } else {
                voicePresented = false
                quickOpenPresented = false
                pendingQuickOpenTarget = nil
                selectedTaskID = nil
            }
        }
        .sheet(isPresented: $voicePresented) {
            VoiceCaptureView(onUseAsTask: model.account == nil ? nil : { transcript in
                if model.draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                    model.draft = transcript
                    addFocused = true
                } else {
                    pendingVoiceTranscript = transcript
                    confirmingReplaceDraft = true
                }
            })
        }
        .confirmationDialog("Discard unsaved changes?", isPresented: $confirmingDiscard) {
            if selectedTaskID != nil && editorDirty {
                Button("Save task") { editorSaveRequest += 1 }
                    .disabled(!editorCanSave)
            }
            Button("Discard changes", role: .destructive) {
                if let pendingEditorNavigation {
                    if changesCaptureContext(pendingEditorNavigation) {
                        model.draft = ""
                        model.waitingForDraft = ""
                    }
                    applyNavigation(pendingEditorNavigation)
                }
            }
            Button("Keep editing", role: .cancel) { pendingEditorNavigation = nil }
        } message: {
            Text(selectedTaskID == nil
                 ? "The new task draft has not been saved."
                 : "Unsaved task fields and unfinished drafts will be discarded. Subtasks and comments already saved will stay saved.")
        }
        .confirmationDialog("Replace the current task draft?", isPresented: $confirmingReplaceDraft) {
            Button("Replace draft", role: .destructive) {
                if let transcript = pendingVoiceTranscript { model.draft = transcript }
                pendingVoiceTranscript = nil
                addFocused = true
            }
            Button("Keep draft", role: .cancel) { pendingVoiceTranscript = nil }
        } message: {
            Text("The existing draft will be replaced by the voice transcript.")
        }
        .sheet(isPresented: $choosingCaptureList, onDismiss: {
            if focusCaptureAfterChoice {
                focusCaptureAfterChoice = false
                addFocused = true
            }
        }) {
            VStack(alignment: .leading, spacing: 16) {
                Text("Add task to").font(.title2.bold())
                Picker("GTD list", selection: $captureListChoice) {
                    ForEach(TaskList.allCases) { list in
                        Text(list.title).tag(list)
                    }
                }
                .pickerStyle(.radioGroup)
                HStack {
                    Spacer()
                    Button("Cancel") { choosingCaptureList = false }
                        .keyboardShortcut(.cancelAction)
                    Button("Continue") {
                        Task {
                            await model.choose(.list(captureListChoice))
                            focusCaptureAfterChoice = true
                            choosingCaptureList = false
                        }
                    }
                    .buttonStyle(.borderedProminent)
                    .keyboardShortcut(.defaultAction)
                }
            }
            .padding(24)
            .frame(width: 360)
        }
        .confirmationDialog("Delete tag?", isPresented: $confirmingTagDeletion) {
            Button("Delete tag", role: .destructive) {
                guard let tag = tagToDelete, !editorDirty else { return }
                Task {
                    if await model.deleteTag(tag.id) {
                        selectedTaskID = nil
                        editorDirty = false
                    }
                }
            }
            Button("Cancel", role: .cancel) { tagToDelete = nil }
        } message: {
            Text("This removes #\(tagToDelete?.name ?? "tag") from every task. The tasks stay.")
        }
        .sheet(item: $addingCollection) { kind in
            VStack(alignment: .leading, spacing: 16) {
                Text(kind == .project ? "New project" : "New tag").font(.title2.bold())
                TextField("Name", text: $collectionName)
                    .onSubmit { createCollection(kind) }
                HStack {
                    Spacer()
                    Button("Cancel") { addingCollection = nil }
                    Button("Add") { createCollection(kind) }
                        .buttonStyle(.borderedProminent)
                        .disabled(collectionName.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || model.busy)
                }
            }
            .padding(24)
            .frame(width: 340)
        }
        .sheet(item: $editingCollection) { kind in
            VStack(alignment: .leading, spacing: 16) {
                Text(kind.isProject ? "Rename project" : "Rename tag").font(.title2.bold())
                TextField("Name", text: $editedCollectionName)
                    .onSubmit { renameCollection(kind) }
                if let error = model.error {
                    Text(error).font(.caption).foregroundStyle(.red)
                }
                HStack {
                    Spacer()
                    Button("Cancel") { editingCollection = nil }
                        .keyboardShortcut(.cancelAction)
                    Button("Save") { renameCollection(kind) }
                        .buttonStyle(.borderedProminent)
                        .keyboardShortcut(.defaultAction)
                        .disabled(editedCollectionName.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                                  || editedCollectionName.count > 500 || model.busy)
                }
            }
            .padding(24)
            .frame(width: 340)
        }
        .sheet(item: $editingOutcomeProject) { project in
            VStack(alignment: .leading, spacing: 14) {
                Text("Desired outcome").font(.title2.bold())
                Text(project.name).foregroundStyle(.secondary)
                Text("What will be true when this project is done?")
                    .font(.subheadline)
                TextEditor(text: $outcomeDraft)
                    .scrollContentBackground(.hidden)
                    .frame(height: 110)
                    .padding(8)
                    .background(.quaternary.opacity(0.6), in: RoundedRectangle(cornerRadius: 8))
                    .accessibilityLabel("Desired project outcome")
                if let error = model.error {
                    Text(error).font(.caption).foregroundStyle(.red)
                }
                HStack {
                    Spacer()
                    Button("Cancel") { editingOutcomeProject = nil }
                        .keyboardShortcut(.cancelAction)
                    Button("Save outcome") {
                        Task {
                            if await model.saveProjectOutcome(project.id, to: outcomeDraft) {
                                editingOutcomeProject = nil
                            }
                        }
                    }
                    .buttonStyle(.borderedProminent)
                    .keyboardShortcut(.defaultAction)
                    .disabled(model.busy || outcomeDraft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                              || outcomeDraft.count > 1_000
                              || outcomeDraft.trimmingCharacters(in: .whitespacesAndNewlines) == project.desired_outcome)
                }
            }
            .padding(24)
            .frame(width: 480)
        }
        .sheet(item: $reopeningTask) { task in
            VStack(alignment: .leading, spacing: 16) {
                Text("Reopen task").font(.title2.bold())
                Text(task.title)
                    .foregroundStyle(.secondary)
                    .lineLimit(2)
                Picker("Destination", selection: $reopenDestination) {
                    ForEach(TaskList.allCases) { list in
                        Text(list.title).tag(list)
                    }
                }
                if reopenDestination == .waiting {
                    TextField("Waiting for person, event, or condition", text: $reopenWaitingFor)
                        .textFieldStyle(.roundedBorder)
                }
                if let error = model.error {
                    Text(error).font(.caption).foregroundStyle(.red)
                }
                HStack {
                    Spacer()
                    Button("Cancel") { reopeningTask = nil }
                        .keyboardShortcut(.cancelAction)
                    Button("Reopen task") {
                        Task {
                            let reopened = await model.reopenTask(
                                task, to: reopenDestination, waitingFor: reopenWaitingFor
                            )
                            if reopened { reopeningTask = nil }
                        }
                    }
                    .buttonStyle(.borderedProminent)
                    .keyboardShortcut(.defaultAction)
                    .disabled(model.busy || (reopenDestination == .waiting &&
                               (reopenWaitingFor.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                                || reopenWaitingFor.count > 500)))
                }
            }
            .padding(24)
            .frame(width: 380)
        }
        .sheet(item: $movingTask) { task in
            VStack(alignment: .leading, spacing: 16) {
                Text("Move to Waiting for").font(.title2.bold())
                Text(task.title)
                    .foregroundStyle(.secondary)
                    .lineLimit(2)
                TextField("Who or what are you waiting for?", text: $moveWaitingFor)
                    .textFieldStyle(.roundedBorder)
                    .accessibilityLabel("Waiting for person, event, or condition")
                if let error = model.error {
                    Text(error).font(.caption).foregroundStyle(.red)
                }
                HStack {
                    Spacer()
                    Button("Keep in \(TaskList(rawValue: task.state)?.title ?? "current list")") {
                        movingTask = nil
                    }
                    .keyboardShortcut(.cancelAction)
                    Button("Move to Waiting for") {
                        Task {
                            if await model.moveTask(task, to: .waiting, waitingFor: moveWaitingFor) {
                                movingTask = nil
                            }
                        }
                    }
                    .buttonStyle(.borderedProminent)
                    .keyboardShortcut(.defaultAction)
                    .disabled(model.busy || moveWaitingFor.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                              || moveWaitingFor.count > 500)
                }
            }
            .padding(24)
            .frame(width: 390)
        }
        .sheet(isPresented: $reviewingWaiting) {
            WaitingReviewView(model: model)
        }
        .sheet(isPresented: $reviewingProjects) {
            ProjectReviewView(model: model) { id in
                reviewingProjects = false
                requestNavigation(.destination(.project(id)))
            }
        }
        .sheet(isPresented: $clarifyingInbox) {
            InboxClarifyView(model: model)
        }
    }

    private func createCollection(_ kind: NewCollection) {
        let name = collectionName
        Task {
            if kind == .project, let project = await model.createProject(name) {
                addingCollection = nil
                collectionName = ""
                requestNavigation(.destination(.project(project.id)))
            } else if kind == .tag, let tag = await model.createTag(name) {
                addingCollection = nil
                collectionName = ""
                requestNavigation(.destination(.tag(tag.id)))
            }
        }
    }

    private func renameCollection(_ kind: CollectionToEdit) {
        let name = editedCollectionName
        Task {
            let saved: Bool
            switch kind {
            case .project(let id): saved = await model.renameProject(id, to: name)
            case .tag(let id): saved = await model.renameTag(id, to: name)
            }
            if saved { editingCollection = nil }
        }
    }

    private var signIn: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text("Brain Buddy").font(.largeTitle.bold())
            Text("Sign in to your Brain Buddy account")
                .foregroundStyle(.secondary)
            TextField("Email", text: $email)
                .textContentType(.username)
                .disabled(model.busy)
            SecureField("Password", text: $password)
                .textContentType(.password)
                .onSubmit { Task { await model.signIn(email: email, password: password) } }
                .disabled(model.busy)
            TextField("API URL", text: $model.serverURL)
                .textContentType(.URL)
                .font(.caption)
                .disabled(model.busy)
            if let error = model.error {
                Text(error).foregroundStyle(.red).font(.caption)
            }
            Button("Sign in") {
                Task { await model.signIn(email: email, password: password) }
            }
            .buttonStyle(.borderedProminent)
            .disabled(model.busy || email.isEmpty || password.isEmpty)
            Button("Try local voice capture") { voicePresented = true }
        }
        .textFieldStyle(.roundedBorder)
        .frame(width: 360)
        .padding(40)
    }

    private func sidebar(account: Account) -> some View {
        List {
            Section("Lists") {
                ForEach(TaskList.allCases) { list in
                    sidebarButton(list.title, symbol: list.symbol, destination: .list(list))
                }
            }
            Section("Dates") {
                ForEach([DateDestination.overdue, .today, .upcoming], id: \.self) { day in
                    sidebarButton(day.title, symbol: day.symbol, destination: .date(day))
                }
            }
            Section("History") {
                sidebarButton("Completed", symbol: HistoryState.completed.symbol, destination: .history(.completed))
                sidebarButton("Cancelled", symbol: HistoryState.cancelled.symbol, destination: .history(.cancelled))
            }
            Section {
                ForEach(model.projects.filter { $0.state == "active" }) { project in
                    sidebarButton(project.name, symbol: "circle.fill", destination: .project(project.id), tint: projectTint(project.color))
                        .contextMenu {
                            Button("Rename…") {
                                model.error = nil
                                editedCollectionName = project.name
                                editingCollection = .project(project.id)
                            }
                            Button("Archive project") {
                                Task {
                                    if await model.archiveProject(project.id) { selectedTaskID = nil }
                                }
                            }
                            .disabled(editorDirty || !model.draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                            .help("Add or clear the current task draft before archiving")
                        }
                }
            } header: {
                HStack {
                    Text("Projects")
                    Spacer()
                    if model.isLocalWorkspace {
                        Button("Review") { requestNavigation(.reviewProjects) }
                            .buttonStyle(.plain)
                            .accessibilityLabel("Review projects")
                    }
                    Button {
                        collectionName = ""
                        addingCollection = .project
                    } label: { Image(systemName: "plus") }
                    .buttonStyle(.plain)
                    .accessibilityLabel("Add project")
                }
            }
            if model.isLocalWorkspace && !model.archivedProjects.isEmpty {
                Section("Archived projects") {
                    ForEach(model.archivedProjects) { project in
                        sidebarButton(project.name, symbol: "archivebox", destination: .project(project.id))
                            .contextMenu {
                                Button("Restore project") {
                                    Task { _ = await model.unarchiveProject(project.id) }
                                }
                            }
                    }
                }
            }
            Section {
                ForEach(model.tags.filter { $0.state == "active" }) { tag in
                    Button {
                        requestNavigation(.destination(.tag(tag.id)))
                    } label: {
                        Text("#\(tag.name)")
                            .font(.caption.weight(.medium))
                            .foregroundStyle(tagTint(tag.id))
                            .padding(.horizontal, 9)
                            .padding(.vertical, 5)
                            .background(tagTint(tag.id).opacity(0.16), in: Capsule())
                            .frame(maxWidth: .infinity, alignment: .leading)
                    }
                    .buttonStyle(.plain)
                    .listRowBackground(model.destination == .tag(tag.id) ? Color.accentColor.opacity(0.22) : Color.clear)
                    .disabled(model.busy)
                    .contextMenu {
                        Button("Rename…") {
                            model.error = nil
                            editedCollectionName = tag.name
                            editingCollection = .tag(tag.id)
                        }
                        Button("Delete tag…", role: .destructive) {
                            tagToDelete = tag
                            confirmingTagDeletion = true
                        }
                        .disabled(editorDirty)
                    }
                }
                Button {
                    collectionName = ""
                    addingCollection = .tag
                } label: {
                    Label("New tag", systemImage: "plus")
                        .font(.caption)
                        .padding(.horizontal, 8)
                        .padding(.vertical, 4)
                        .background(.quaternary, in: Capsule())
                }
                .buttonStyle(.plain)
            } header: {
                Text("Tags")
            }
        }
        .listStyle(.sidebar)
        .navigationTitle("BrainBuddy")
        .safeAreaInset(edge: .bottom) {
            HStack {
                Text(account.display_name ?? account.email)
                    .font(.caption)
                    .lineLimit(1)
                Spacer()
                if model.isLocalWorkspace {
                    Image(systemName: "internaldrive")
                        .accessibilityLabel("Stored on this Mac")
                } else {
                    Button("Sign out") { requestNavigation(.signOut) }
                        .disabled(model.busy)
                }
            }
            .padding(12)
        }
    }

    private func sidebarButton(
        _ title: String, symbol: String, destination: WorkspaceDestination, tint: Color? = nil
    ) -> some View {
        let count: Int? = {
            guard case .list(let list) = destination else { return nil }
            return model.sidebarCounts?.count(for: list)
        }()
        return Button {
            requestNavigation(.destination(destination))
        } label: {
            HStack(spacing: 10) {
                Image(systemName: symbol)
                    .foregroundStyle(tint ?? .secondary)
                    .font(.system(size: 14, weight: .semibold))
                    .frame(width: 20)
                    .accessibilityHidden(true)
                Text(title)
                    .lineLimit(1)
                    .layoutPriority(1)
                Spacer(minLength: 0)
                if let count {
                    Text("\(count)")
                        .font(.caption.monospacedDigit())
                        .foregroundStyle(.secondary)
                        .padding(.horizontal, 7)
                        .padding(.vertical, 2)
                        .background(.quaternary, in: Capsule())
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .contentShape(Rectangle())
        }
        .accessibilityLabel(count.map { "\(title), \($0) open tasks" } ?? title)
        .buttonStyle(.plain)
        .padding(.vertical, 3)
        .listRowBackground(model.destination == destination ? Color.accentColor.opacity(0.22) : Color.clear)
        .disabled(model.busy)
    }

    private func requestNavigation(_ next: PendingEditorNavigation) {
        let hasTaskEdits = selectedTaskID != nil && editorDirty
        let hasCaptureDraft = !model.draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            || !model.waitingForDraft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        if hasTaskEdits || (hasCaptureDraft && changesCaptureContext(next)) {
            pendingEditorNavigation = next
            confirmingDiscard = true
        } else {
            applyNavigation(next)
        }
    }

    private func changesCaptureContext(_ next: PendingEditorNavigation) -> Bool {
        switch next {
        case .destination(let destination): destination != model.destination
        case .quickOpen: true
        case .newTask: isDateDestination || model.destination.isHistory || isArchivedProjectDestination
        case .signOut: true
        default: false
        }
    }

    private func applyNavigation(_ pendingEditorNavigation: PendingEditorNavigation) {
        self.pendingEditorNavigation = nil
        editorDirty = false
        editorCanSave = false
        if let selectedTaskID { model.clearSyncConflict(for: selectedTaskID) }
        switch pendingEditorNavigation {
        case .destination(let destination):
            selectedTaskID = nil
            quickOpenedTask = nil
            Task { await model.choose(destination) }
        case .quickOpen(let target):
            selectedTaskID = nil
            quickOpenedTask = nil
            Task { await openQuickOpenTarget(target) }
        case .task(let id):
            if id != quickOpenedTask?.id { quickOpenedTask = nil }
            selectedTaskID = id
            if let id {
                model.taskDetails.removeValue(forKey: id)
                editorTitle = model.tasks.first(where: { $0.id == id })?.title ?? ""
                Task {
                    await model.loadTaskDetail(id)
                    if selectedTaskID == id, let detail = model.taskDetails[id] {
                        editorTitle = detail.title
                    }
                }
            }
        case .complete(let task):
            selectedTaskID = nil
            let current = currentTask(for: task)
            Task { await model.completeTask(current) }
        case .move(let task, let destination):
            selectedTaskID = nil
            let current = currentTask(for: task)
            if destination == .waiting {
                model.error = nil
                moveWaitingFor = ""
                movingTask = current
            } else {
                Task { _ = await model.moveTask(current, to: destination) }
            }
        case .reopen(let task):
            selectedTaskID = nil
            model.error = nil
            reopenDestination = .next
            reopenWaitingFor = ""
            reopeningTask = currentTask(for: task)
        case .cancel(let task):
            selectedTaskID = nil
            let current = currentTask(for: task)
            Task { await model.cancelTask(current) }
        case .newTask:
            selectedTaskID = nil
            if isArchivedProjectDestination {
                Task {
                    await model.choose(.list(.next))
                    addFocused = true
                }
            } else if isDateDestination || model.destination.isHistory {
                addFocused = false
                captureListChoice = .next
                choosingCaptureList = true
            } else {
                addFocused = true
            }
        case .reload:
            selectedTaskID = nil
            Task { await model.reload() }
        case .clearTaskFilters:
            selectedTaskID = nil
            Task { await model.clearTaskFilters() }
        case .signOut:
            selectedTaskID = nil
            Task { await model.signOut() }
        case .createTask:
            selectedTaskID = nil
            Task { await model.createTask() }
        case .reviewWaiting:
            selectedTaskID = nil
            reviewingWaiting = true
        case .reviewProjects:
            selectedTaskID = nil
            reviewingProjects = true
        case .clarifyInbox:
            selectedTaskID = nil
            clarifyingInbox = true
        case .groupByProject(let value):
            selectedTaskID = nil
            model.groupByProject = value
        case .showCancelled(let value):
            selectedTaskID = nil
            model.showCancelled = value
        case .priorityFilter(let value):
            selectedTaskID = nil
            model.priorityFilter = value
        case .sort(let value):
            selectedTaskID = nil
            model.sort = value
        }
    }

    private func openQuickOpenTarget(_ target: QuickOpenTarget) async {
        guard model.account != nil else { return }
        model.searchText = ""
        model.priorityFilter = .all
        switch target {
        case .list(let list):
            await model.choose(.list(list))
        case .history(let state):
            await model.choose(.history(state))
        case .project(let id):
            await model.choose(.project(id))
        case .tag(let id):
            await model.choose(.tag(id))
        case .task(let id):
            guard let task = await model.quickOpenTask(id) else { return }
            let destination: WorkspaceDestination
            if task.state == HistoryState.completed.rawValue {
                destination = .history(.completed)
            } else if task.state == HistoryState.cancelled.rawValue {
                destination = .history(.cancelled)
            } else if task.state == TaskList.inbox.rawValue, let projectID = task.project_id {
                destination = .project(projectID)
            } else if let list = TaskList(rawValue: task.state) {
                destination = .list(list)
            } else {
                model.error = "This task has an unknown GTD state."
                return
            }
            await model.choose(destination)
            quickOpenedTask = task
            applyNavigation(.task(id))
        }
    }

    private func currentTask(for task: BrainBuddyTask) -> BrainBuddyTask {
        let candidates = [task, model.tasks.first(where: { $0.id == task.id }), model.taskDetails[task.id]]
            .compactMap { $0 }
        return candidates.max(by: { $0.revision < $1.revision }) ?? task
    }

    private var taskCanvas: some View {
        VStack(alignment: .leading, spacing: 0) {
            VStack(alignment: .leading, spacing: 12) {
                Text(destinationTitle).font(.largeTitle.bold())
                Text(taskCountCaption)
                    .foregroundStyle(.secondary)
                    .font(.subheadline)
                HStack(spacing: 16) {
                    if model.destination == .list(.inbox) {
                        Button("Clarify Inbox") {
                            requestNavigation(.clarifyInbox)
                        }
                        .buttonStyle(.borderedProminent)
                        .disabled(model.busy)
                    }
                    if model.destination == .list(.waiting) {
                        Button("Review Waiting for") {
                            requestNavigation(.reviewWaiting)
                        }
                        .buttonStyle(.borderedProminent)
                        .disabled(model.busy)
                    }
                    if model.destination == .list(.next) {
                        Toggle("Group by project", isOn: Binding(
                            get: { model.groupByProject },
                            set: { requestNavigation(.groupByProject($0)) }
                        ))
                            .fixedSize()
                    }
                    if !model.destination.isHistory {
                        Toggle("Show cancelled", isOn: Binding(
                            get: { model.showCancelled },
                            set: { requestNavigation(.showCancelled($0)) }
                        ))
                            .fixedSize()
                    }
                    Picker("Sort", selection: Binding(
                        get: { model.sort },
                        set: { requestNavigation(.sort($0)) }
                    )) {
                        ForEach(TaskSort.allCases) { value in
                            Text(value.title).tag(value)
                        }
                    }
                    .frame(maxWidth: 170)
                }
                .font(.subheadline)
                .onChange(of: model.showCancelled) { _, _ in Task { await model.reload() } }
                .onChange(of: model.priorityFilter) { _, _ in Task { await model.reload() } }
                .onChange(of: model.sort) { _, _ in Task { await model.reload() } }
            }
            .padding(.horizontal, 28)
            .padding(.top, 28)
            .padding(.bottom, 20)

            if let error = model.error {
                HStack {
                    Text(error).foregroundStyle(.red)
                    Spacer()
                    Button("Retry") { requestNavigation(.reload) }
                }
                .padding(.horizontal, 28)
                .padding(.bottom, 12)
            }

            if let taskID = model.syncConflictTaskID {
                HStack(spacing: 12) {
                    Image(systemName: "arrow.triangle.2.circlepath")
                        .foregroundStyle(.blue)
                    VStack(alignment: .leading, spacing: 2) {
                        Text("Sync needs attention").font(.subheadline.bold())
                        Text(model.syncConflictCurrentLoaded
                             ? "The latest task is loaded. Your edited fields remain in the editor. Retry will apply them to it."
                             : "Your edits remain in the editor. Load the current task before saving again.")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                    Spacer()
                    if !model.syncConflictCurrentLoaded {
                        Button("Load current task") { Task { await model.loadTaskDetail(taskID) } }
                    } else if !model.syncConflictRetryApproved {
                        Button("Retry my edits") { model.syncConflictRetryApproved = true }
                    }
                }
                .padding(10)
                .background(Color.blue.opacity(0.10), in: RoundedRectangle(cornerRadius: 9))
                .padding(.horizontal, 28)
                .padding(.bottom, 12)
            }

            ScrollView {
                LazyVStack(alignment: .leading, spacing: 12) {
                    if case .project(let id) = model.destination {
                        projectOverviewCard(id)
                    }
                    if let quickOpenedTask, selectedTaskID == quickOpenedTask.id {
                        Text("OPENED FROM QUICK OPEN")
                            .font(.caption.bold())
                            .tracking(1.5)
                            .foregroundStyle(.secondary)
                        taskCard(model.taskDetails[quickOpenedTask.id] ?? quickOpenedTask)
                    }
                    ForEach(taskSections, id: \.name) { section in
                        if !section.name.isEmpty {
                            Text(section.name.uppercased())
                                .font(.caption.bold())
                                .tracking(1.5)
                                .foregroundStyle(.secondary)
                                .padding(.top, 8)
                        }
                        ForEach(section.tasks) { task in
                            taskCard(task)
                        }
                    }
                    if !isDateDestination && !model.destination.isHistory && !isArchivedProjectDestination {
                        smartAdd
                    }
                    if !completedTasks.isEmpty {
                        Text("COMPLETED")
                            .font(.caption.bold())
                            .tracking(1.5)
                            .foregroundStyle(.secondary)
                            .padding(.top, 16)
                        ForEach(completedTasks) { task in taskCard(task) }
                    }
                    if !cancelledTasks.isEmpty {
                        Text("CANCELLED")
                            .font(.caption.bold())
                            .tracking(1.5)
                            .foregroundStyle(.secondary)
                            .padding(.top, 16)
                        ForEach(cancelledTasks) { task in taskCard(task) }
                    }
                    if model.nextCursor != nil {
                        Button("Load more") { Task { await model.loadMore() } }
                            .disabled(model.loading)
                            .padding(.top, 10)
                    }
                }
                .frame(maxWidth: 860)
                .frame(maxWidth: .infinity)
                .padding(.horizontal, 28)
                .padding(.bottom, 28)
            }
            .overlay {
                if model.loading && model.tasks.isEmpty { ProgressView() }
                else if !model.loading && model.tasks.isEmpty && isArchivedProjectDestination {
                    if model.hasAppliedTaskFilter {
                        ContentUnavailableView("No matching tasks", systemImage: "magnifyingglass")
                    } else {
                        ContentUnavailableView("Archived project", systemImage: "archivebox",
                                               description: Text("Restore this project to add tasks."))
                    }
                } else if !model.loading && model.tasks.isEmpty && (isDateDestination || model.destination.isHistory) {
                    ContentUnavailableView(model.destination.isHistory ? "No history" : "No tasks", systemImage: "checkmark.circle")
                }
            }
        }
        .frame(minWidth: 560, minHeight: 480)
    }

    @ViewBuilder
    private func projectOverviewCard(_ id: String) -> some View {
        if let project = (model.projects + model.archivedProjects).first(where: { $0.id == id }) {
            VStack(alignment: .leading, spacing: 12) {
                HStack {
                    Text("PROJECT OUTCOME")
                        .font(.caption.bold())
                        .tracking(1.5)
                        .foregroundStyle(.secondary)
                    Spacer()
                    if model.isLocalWorkspace && project.state == "active" {
                        Button(project.desired_outcome == nil ? "Set outcome" : "Edit outcome") {
                            model.error = nil
                            outcomeDraft = project.desired_outcome ?? ""
                            editingOutcomeProject = project
                        }
                    }
                }
                if let outcome = project.desired_outcome, !outcome.isEmpty {
                    Text(outcome)
                        .font(.body.weight(.medium))
                        .frame(maxWidth: .infinity, alignment: .leading)
                } else {
                    Text(model.isLocalWorkspace
                         ? "Define what will be true when this project is done."
                         : "Desired outcome is not available in this workspace yet.")
                        .foregroundStyle(.secondary)
                }
                Divider()
                if let next = model.projectNextAction {
                    Label("First Next action", systemImage: "arrow.right.circle")
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(.secondary)
                    Text(next.title)
                        .frame(maxWidth: .infinity, alignment: .leading)
                } else {
                    Text(projectNextExplanation)
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                }
            }
            .padding(16)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(Color.accentColor.opacity(0.08), in: RoundedRectangle(cornerRadius: 13))
            .overlay {
                RoundedRectangle(cornerRadius: 13)
                    .strokeBorder(Color.accentColor.opacity(0.25))
                    .allowsHitTesting(false)
            }
        }
    }

    private var projectNextExplanation: String {
        guard let counts = model.projectOverviewCounts else { return "Loading project actions…" }
        if counts.next > 0 { return "A Next action exists but could not be shown. Refresh this project." }
        if counts.inbox > 0 { return "No Next action yet · clarify an Inbox item in this project." }
        if counts.waiting > 0 { return "No Next action yet · this project is waiting on a dependency." }
        if counts.someday > 0 { return "No Next action yet · its open work is in Someday." }
        return "No open actions · review whether this project is complete."
    }

    private var destinationTitle: String {
        switch model.destination {
        case .list(let list): return list == .someday ? "Someday / maybe" : list.title
        case .date(let date): return date.title
        case .project(let id): return projectName(id)
        case .tag(let id): return "#" + (model.tags.first(where: { $0.id == id })?.name ?? "Tag")
        case .history(let state): return state.title
        }
    }

    private var taskCountCaption: String {
        if model.destination.isHistory {
            return "\(model.tasks.count) history rows loaded\(model.nextCursor == nil ? "" : " · more available")"
        }
        if let counts = model.openCounts {
            let total: Int
            if case .list(let list) = model.destination { total = counts.count(for: list) }
            else { total = counts.total }
            return "\(total) open tasks\(model.nextCursor == nil ? "" : " · \(model.tasks.count) rows loaded · more available")"
        }
        return "\(openTasks.count) tasks loaded\(model.nextCursor == nil ? "" : " · more available")"
    }

    private var isDateDestination: Bool {
        if case .date = model.destination { return true }
        return false
    }

    private var isArchivedProjectDestination: Bool {
        guard model.isLocalWorkspace, case .project(let id) = model.destination else { return false }
        return model.archivedProjects.contains { $0.id == id }
    }

    private var openTasks: [BrainBuddyTask] {
        visibleTasks.filter { $0.state != "completed" && $0.state != "cancelled" }
    }

    private var completedTasks: [BrainBuddyTask] {
        visibleTasks.filter { $0.state == "completed" }
    }

    private var cancelledTasks: [BrainBuddyTask] {
        visibleTasks.filter { $0.state == "cancelled" }
    }

    private var visibleTasks: [BrainBuddyTask] {
        guard let pinned = quickOpenedTask, selectedTaskID == pinned.id else { return model.tasks }
        return model.tasks.filter { $0.id != pinned.id }
    }

    private var taskSections: [(name: String, tasks: [BrainBuddyTask])] {
        if model.destination != .list(.next) || !model.groupByProject { return [("", openTasks)] }
        let grouped = Dictionary(grouping: openTasks, by: { $0.project_id ?? "" })
        return grouped.keys.sorted { left, right in
            if left.isEmpty { return false }
            if right.isEmpty { return true }
            return projectName(left) < projectName(right)
        }.map { id in
            (id.isEmpty ? "Other" : projectName(id), grouped[id] ?? [])
        }
    }

    private func projectName(_ id: String) -> String {
        (model.projects + model.archivedProjects).first(where: { $0.id == id })?.name ?? "Project"
    }

    private func projectTint(_ hex: String?) -> Color {
        guard let hex, hex.hasPrefix("#"), hex.count == 7,
              let value = UInt32(hex.dropFirst(), radix: 16) else { return .accentColor }
        return Color(
            .sRGB,
            red: Double((value >> 16) & 0xff) / 255,
            green: Double((value >> 8) & 0xff) / 255,
            blue: Double(value & 0xff) / 255,
            opacity: 1
        )
    }

    private func taskCard(_ task: BrainBuddyTask) -> some View {
        let terminal = task.state == "completed" || task.state == "cancelled"
        return VStack(spacing: 0) {
            HStack(spacing: 12) {
                if terminal {
                    Image(systemName: task.state == "completed" ? "checkmark.circle.fill" : "xmark.circle")
                        .font(.title3)
                        .foregroundStyle(.secondary)
                    Button {
                        requestNavigation(.task(selectedTaskID == task.id ? nil : task.id))
                    } label: {
                        Text(task.title)
                            .font(.body.weight(.semibold))
                            .lineLimit(1)
                            .contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                    .accessibilityLabel("View \(task.title)")
                    .accessibilityValue(selectedTaskID == task.id ? "Expanded" : "Collapsed")
                } else {
                    Button {
                        requestNavigation(.complete(task))
                    } label: {
                        Image(systemName: "circle").font(.title3)
                    }
                    .buttonStyle(.plain)
                    .accessibilityLabel("Complete \(task.title)")
                    .disabled(model.busy)
                    if selectedTaskID == task.id && model.taskDetails[task.id] != nil {
                        TextField("Task title", text: $editorTitle)
                            .font(.body.weight(.semibold))
                            .textFieldStyle(.plain)
                            .disabled(model.busy)
                    } else {
                        Button {
                            requestNavigation(.task(selectedTaskID == task.id ? nil : task.id))
                        } label: {
                            Text(task.title)
                                .font(.body.weight(.semibold))
                                .lineLimit(1)
                                .contentShape(Rectangle())
                        }
                        .buttonStyle(.plain)
                        .accessibilityLabel("Edit \(task.title)")
                        .accessibilityValue(selectedTaskID == task.id ? "Expanded" : "Collapsed")
                    }
                }
                Spacer(minLength: 8)
                if let id = task.tag_ids.first,
                   let tag = model.tags.first(where: { $0.id == id }) {
                    Text("#\(tag.name)")
                        .font(.caption)
                        .lineLimit(1)
                        .foregroundStyle(tagTint(id))
                        .padding(.horizontal, 8)
                        .padding(.vertical, 3)
                        .background(tagTint(id).opacity(0.15), in: Capsule())
                }
                if task.tag_ids.count > 1 {
                    Text("+\(task.tag_ids.count - 1)")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                if let due = task.due_date {
                    Text(due).font(.caption).foregroundStyle(.secondary)
                }
                if !terminal {
                    Menu {
                        ForEach(TaskList.allCases.filter { $0.rawValue != task.state }) { list in
                            Button {
                                requestNavigation(.move(task, list))
                            } label: {
                                Label(list.title, systemImage: list.symbol)
                            }
                        }
                    } label: {
                        Image(systemName: "arrowshape.turn.up.right")
                    }
                    .menuStyle(.borderlessButton)
                    .accessibilityLabel("Move \(task.title) to another GTD list")
                    .help("Move to another GTD list")
                    .disabled(model.busy)
                }
                if terminal {
                    Button("Reopen…") { requestNavigation(.reopen(task)) }
                        .fixedSize(horizontal: true, vertical: false)
                        .accessibilityLabel("Reopen \(task.title)")
                        .disabled(model.busy)
                }
            }
            .padding(.horizontal, 13)
            .frame(minHeight: 42)
            if task.state == "waiting",
               let waitingFor = task.waiting_for?.trimmingCharacters(in: .whitespacesAndNewlines),
               !waitingFor.isEmpty {
                HStack(spacing: 4) {
                    Text("Waiting for \(waitingFor)")
                        .lineLimit(1)
                    if let since = task.waiting_since.flatMap(Self.waitingDate) {
                        Text("· since")
                        Text(since, style: .date)
                    }
                    Spacer(minLength: 0)
                }
                .font(.caption)
                .foregroundStyle(.secondary)
                .padding(.leading, 45)
                .padding(.trailing, 13)
                .padding(.bottom, 8)
            }
            if selectedTaskID == task.id {
                if let detail = model.taskDetails[task.id] {
                    if terminal {
                        terminalDetail(detail)
                            .padding(.horizontal, 18)
                            .padding(.bottom, 16)
                    } else {
                        TaskInlineEditor(
                            task: detail, title: $editorTitle,
                            projects: model.projects + model.archivedProjects,
                            tags: model.tags, busy: model.busy,
                            requiresCurrentTask: model.syncConflictTaskID == task.id && !model.syncConflictRetryApproved,
                            saveRequest: editorSaveRequest
                        ) { changes, state in
                            let saved = await model.saveTask(detail, changes: changes, destinationState: state)
                            if saved {
                                editorDirty = false
                                editorCanSave = false
                                if let pendingEditorNavigation {
                                    self.pendingEditorNavigation = nil
                                    requestNavigation(pendingEditorNavigation)
                                } else {
                                    selectedTaskID = nil
                                }
                            } else {
                                pendingEditorNavigation = nil
                            }
                        } onCancel: {
                            editorDirty = false
                            editorCanSave = false
                            model.clearSyncConflict(for: task.id)
                            selectedTaskID = nil
                        } onCreateProject: { name in
                            await model.createProject(name)
                        } onEditorStateChange: { dirty, canSave in
                            editorDirty = dirty
                            editorCanSave = canSave
                        } onCancelTask: {
                            requestNavigation(.cancel(detail))
                        } extras: { onExtrasDirtyChange in
                            TaskDetailExtras(task: detail, model: model, onDirtyChange: onExtrasDirtyChange)
                        }
                        .padding(.horizontal, 18)
                        .padding(.bottom, 16)
                    }
                } else if model.detailLoadingID == task.id {
                    HStack {
                        ProgressView()
                        Text("Loading task details…").foregroundStyle(.secondary)
                        Spacer()
                        Button("Close") { selectedTaskID = nil }
                    }
                    .padding(16)
                } else {
                    HStack {
                        Text("Task details could not be loaded.").foregroundStyle(.secondary)
                        Spacer()
                        Button("Retry") { Task { await model.loadTaskDetail(task.id) } }
                        Button("Close") { selectedTaskID = nil }
                    }
                    .padding(16)
                }
            }
        }
        .background(.quaternary.opacity(0.6), in: RoundedRectangle(cornerRadius: 13))
        .overlay {
            RoundedRectangle(cornerRadius: 13)
                .strokeBorder(selectedTaskID == task.id ? Color.accentColor.opacity(0.7) : Color.primary.opacity(0.12))
                .allowsHitTesting(false)
        }
        .id("\(task.id):\(task.revision):\(task.state):\(selectedTaskID == task.id)")
    }

    private func terminalDetail(_ detail: BrainBuddyTask) -> some View {
        let statusDate = detail.state == "completed" ? detail.completed_at : detail.cancelled_at
        return VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 6) {
                Text(detail.state == "completed" ? "Completed" : "Cancelled")
                    .fontWeight(.semibold)
                if let statusDate, let date = Self.waitingDate(statusDate) {
                    Text("·")
                    Text(date, style: .date)
                }
                Spacer()
                Button("Close details") { selectedTaskID = nil }
                    .buttonStyle(.plain)
            }
            .foregroundStyle(.secondary)

            Text(detail.last_open_state.map { "Previously in \($0.title)" } ?? "Previous list unknown")
                .font(.caption)
                .foregroundStyle(.secondary)
            if let description = detail.details, !description.isEmpty {
                Text(description)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
            if let projectID = detail.project_id {
                Text("Project · \(projectName(projectID))")
                    .font(.caption)
            }
            if !detail.tag_ids.isEmpty {
                let names = detail.tag_ids.map { id in
                    model.tags.first(where: { $0.id == id }).map { "#\($0.name)" } ?? id
                }
                Text("Tags · \(names.joined(separator: "  "))")
                    .font(.caption)
            }
            if let due = detail.due_date {
                Text("Due · \(due)").font(.caption)
            }
            if detail.priority != .none {
                Text("Priority · \(detail.priority.rawValue.capitalized)").font(.caption)
            }
            if !detail.subtasks.isEmpty {
                DisclosureGroup("Subtasks · \(detail.subtasks.count)") {
                    VStack(alignment: .leading, spacing: 5) {
                        ForEach(detail.subtasks.sorted { $0.order_key < $1.order_key }) { subtask in
                            Label(subtask.title, systemImage: subtask.state == "completed" ? "checkmark.circle.fill" : "circle")
                                .font(.subheadline)
                        }
                    }
                }
            }
            if !detail.comments.isEmpty {
                DisclosureGroup("Comments · \(detail.comments.count)") {
                    VStack(alignment: .leading, spacing: 6) {
                        ForEach(detail.comments) { comment in
                            Text(comment.body)
                                .font(.subheadline)
                                .frame(maxWidth: .infinity, alignment: .leading)
                        }
                    }
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private static func waitingDate(_ value: String) -> Date? {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if let date = formatter.date(from: value) { return date }
        formatter.formatOptions = [.withInternetDateTime]
        return formatter.date(from: value)
    }

    private var smartAdd: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 12) {
                Image(systemName: "plus.circle")
                    .font(.title3)
                    .foregroundStyle(.secondary)
                TextField("Add a task", text: $model.draft)
                    .textFieldStyle(.plain)
                    .focused($addFocused)
                    .onSubmit { requestNavigation(.createTask) }
                    .disabled(model.busy)
            }
            if model.selectedList == .waiting {
                TextField("Waiting for person, event, or condition", text: $model.waitingForDraft)
                    .onSubmit { requestNavigation(.createTask) }
                    .disabled(model.busy)
            }
            if !model.draft.isEmpty || model.selectedList == .waiting {
                HStack {
                    if smartDraft.hasCompletedTokens {
                        Text("“\(smartDraft.cleanTitle)”")
                            .font(.caption.weight(.semibold))
                            .lineLimit(1)
                    }
                    Text("↪ \(smartCaptureState.title)")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    Spacer()
                    Button("Add task") { requestNavigation(.createTask) }
                        .buttonStyle(.borderedProminent)
                        .disabled(addDisabled)
                }
                let projectLabel = smartDraft.previewProjectLabel(in: model.projects)
                let tagLabels = smartDraft.previewTagLabels(in: model.tags)
                if projectLabel != nil || !tagLabels.isEmpty {
                    Text(([projectLabel].compactMap { $0 } + tagLabels).joined(separator: " · "))
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
            if let notice = model.captureNotice {
                Text(notice)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
                if model.hasAppliedTaskFilter {
                    Button("Clear search and priority filter") {
                        requestNavigation(.clearTaskFilters)
                    }
                    .font(.caption)
                    .disabled(model.busy)
                }
            }
        }
        .textFieldStyle(.roundedBorder)
        .padding(13)
        .background(.quaternary.opacity(0.6), in: RoundedRectangle(cornerRadius: 13))
        .overlay {
            RoundedRectangle(cornerRadius: 13)
                .strokeBorder(Color.primary.opacity(0.12))
                .allowsHitTesting(false)
        }
    }

    private var addDisabled: Bool {
        let waiting = model.waitingForDraft.trimmingCharacters(in: .whitespacesAndNewlines)
        return model.busy || !smartDraft.isValid
            || (model.selectedList == .waiting && (waiting.isEmpty || waiting.count > 500))
    }

    private var smartDraft: SmartAddDraft {
        let projectID: String?
        let tagID: String?
        if case .project(let id) = model.destination { projectID = id }
        else { projectID = nil }
        if case .tag(let id) = model.destination { tagID = id }
        else { tagID = nil }
        return SmartAddParser.parse(
            model.draft, projects: model.projects, tags: model.tags,
            archivedProjects: model.archivedProjects,
            contextProjectId: projectID, contextTagId: tagID
        )
    }

    private var smartCaptureState: TaskList {
        model.selectedList
    }
}

private enum InboxClarificationStep {
    case decision, nextTitle, waitingReason, waitingTitle
    case projectName, projectOutcome, projectAction
}

private struct InboxClarifyView: View {
    @ObservedObject var model: BrainBuddyModel
    @Environment(\.dismiss) private var dismiss
    @State private var items: [BrainBuddyTask] = []
    @State private var index = 0
    @State private var loading = true
    @State private var loaded = false
    @State private var step: InboxClarificationStep = .decision
    @State private var proposedTitle = ""
    @State private var waitingReason = ""
    @State private var projectName = ""
    @State private var desiredOutcome = ""
    @State private var firstAction = ""
    @State private var confirmingCancel = false
    @State private var confirmingClose = false

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            HStack {
                VStack(alignment: .leading, spacing: 3) {
                    Text("Clarify Inbox").font(.title2.bold())
                    Text(loaded ? (items.isEmpty ? "No items" : "\(min(index + 1, items.count)) of \(items.count)") : "One item at a time")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                }
                Spacer()
                Button("Close clarification") {
                    if step == .decision { dismiss() }
                    else { confirmingClose = true }
                }
                .keyboardShortcut(.cancelAction)
                .disabled(model.busy)
            }

            if loading {
                ProgressView("Loading Inbox…")
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else if !loaded {
                ContentUnavailableView("Could not load Inbox", systemImage: "arrow.clockwise",
                                       description: Text(model.error ?? "Try again."))
                Button("Retry") { Task { await load() } }
            } else if items.isEmpty {
                ContentUnavailableView("Inbox is clear", systemImage: "tray",
                                       description: Text("Capture new items without classifying them first."))
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else if index >= items.count {
                ContentUnavailableView("Clarification pass complete", systemImage: "checkmark.circle",
                                       description: Text("Items left in Inbox can be revisited later."))
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else {
                let item = items[index]
                ScrollView {
                    VStack(alignment: .leading, spacing: 16) {
                        VStack(alignment: .leading, spacing: 8) {
                            Text("CAPTURED ITEM")
                                .font(.caption.bold())
                                .tracking(1.5)
                                .foregroundStyle(.secondary)
                            Text(item.title).font(.title3.weight(.semibold))
                            if let details = item.details, !details.isEmpty {
                                Text(details).foregroundStyle(.secondary).lineLimit(4)
                            }
                            if let due = item.due_date {
                                Text("Due · \(due)").font(.caption).foregroundStyle(.secondary)
                            }
                            if item.priority != .none {
                                Text("Priority · \(item.priority.rawValue.capitalized)")
                                    .font(.caption).foregroundStyle(.secondary)
                            }
                            if !item.tag_ids.isEmpty {
                                let names = item.tag_ids.map { id in
                                    model.tags.first(where: { $0.id == id })?.name ?? id
                                }
                                Text("Tags · \(names.map { "#\($0)" }.joined(separator: "  "))")
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                            }
                        }
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(16)
                        .background(.quaternary.opacity(0.6), in: RoundedRectangle(cornerRadius: 12))

                        if step == .decision {
                            Text("What is this?").font(.headline)
                            VStack(alignment: .leading, spacing: 9) {
                                Button("Already a concrete action → Next") {
                                    Task { if await model.moveTask(item, to: .next) { advance() } }
                                }
                                Button("Rewrite as a Next action…") {
                                    proposedTitle = item.title
                                    step = .nextTitle
                                }
                                Button("Waiting on someone or something…") {
                                    waitingReason = ""
                                    proposedTitle = item.title
                                    step = .waitingReason
                                }
                                Button("A project with several steps…") {
                                    projectName = item.title
                                    desiredOutcome = ""
                                    firstAction = ""
                                    step = .projectName
                                }
                                .disabled(!model.isLocalWorkspace)
                                Button("Someday / maybe") {
                                    Task { if await model.moveTask(item, to: .someday) { advance() } }
                                }
                                Button("No longer relevant…", role: .destructive) { confirmingCancel = true }
                                Button("Leave in Inbox for now") { advance() }
                            }
                            .buttonStyle(.bordered)
                            .disabled(model.busy)
                            Text("Reference-only material stays in Inbox until there is a dedicated place for it.")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        } else {
                            clarificationQuestion(for: item)
                        }
                        if let error = model.error {
                            Text(error).font(.caption).foregroundStyle(.red)
                        }
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                }
            }
        }
        .padding(24)
        .frame(width: 640, height: loaded && index < items.count && step == .decision ? 570 : 430)
        .task { await load() }
        .interactiveDismissDisabled(step != .decision)
        .confirmationDialog("Cancel this Inbox item?", isPresented: $confirmingCancel) {
            Button("Cancel task", role: .destructive) {
                guard index < items.count else { return }
                let item = items[index]
                Task { if await model.cancelTask(item) { advance() } }
            }
            Button("Keep in Inbox", role: .cancel) {}
        } message: {
            Text("This moves the item to history. No project or action is created.")
        }
        .confirmationDialog("Discard clarification draft?", isPresented: $confirmingClose) {
            Button("Discard draft", role: .destructive) { dismiss() }
            Button("Keep editing", role: .cancel) {}
        } message: {
            Text("The Inbox item remains unchanged. Unsaved answers will be lost.")
        }
    }

    @ViewBuilder
    private func clarificationQuestion(for item: BrainBuddyTask) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            Text(question).font(.headline)
            switch step {
            case .nextTitle, .waitingTitle:
                TextField("Concrete action", text: $proposedTitle)
                    .textFieldStyle(.roundedBorder)
                    .accessibilityLabel("Concrete action")
            case .waitingReason:
                TextField("Person, event, or condition", text: $waitingReason)
                    .textFieldStyle(.roundedBorder)
                    .accessibilityLabel("Waiting for person, event, or condition")
            case .projectName:
                TextField("Project name", text: $projectName)
                    .textFieldStyle(.roundedBorder)
            case .projectOutcome:
                TextEditor(text: $desiredOutcome)
                    .scrollContentBackground(.hidden)
                    .frame(height: 95)
                    .padding(8)
                    .background(.quaternary.opacity(0.6), in: RoundedRectangle(cornerRadius: 8))
                    .accessibilityLabel("Desired project outcome")
            case .projectAction:
                TextField("First Next action", text: $firstAction)
                    .textFieldStyle(.roundedBorder)
                    .accessibilityLabel("First Next action")
            case .decision:
                EmptyView()
            }
            if step == .projectAction {
                Text("\(projectName) → \(desiredOutcome)")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                Text("Existing notes, tags, date, and priority stay on the resulting Next action.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            HStack {
                Button("Back") { step = previousStep }
                Spacer()
                Button(step == .projectAction ? "Create project and Next action" :
                       (step == .nextTitle || step == .waitingTitle ? "Save decision" : "Continue")) {
                    Task { await submit(item) }
                }
                .buttonStyle(.borderedProminent)
                .disabled(model.busy || !validAnswer)
            }
        }
    }

    private var question: String {
        switch step {
        case .decision: "What is this?"
        case .nextTitle: "What is the concrete next action?"
        case .waitingReason: "Who or what are you waiting for?"
        case .waitingTitle: "What is the waiting item?"
        case .projectName: "What will you call this project?"
        case .projectOutcome: "What will be true when it is done?"
        case .projectAction: "What is the first concrete action?"
        }
    }

    private var previousStep: InboxClarificationStep {
        switch step {
        case .decision, .nextTitle, .waitingReason, .projectName: .decision
        case .waitingTitle: .waitingReason
        case .projectOutcome: .projectName
        case .projectAction: .projectOutcome
        }
    }

    private var validAnswer: Bool {
        func valid(_ value: String, max: Int) -> Bool {
            let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
            return !trimmed.isEmpty && trimmed.count <= max
        }
        switch step {
        case .decision: return false
        case .nextTitle, .waitingTitle: return valid(proposedTitle, max: 500)
        case .waitingReason: return valid(waitingReason, max: 500)
        case .projectName: return valid(projectName, max: 500)
        case .projectOutcome: return valid(desiredOutcome, max: 1_000)
        case .projectAction: return valid(firstAction, max: 500)
        }
    }

    private func load() async {
        loading = true
        if let fetched = await model.loadInboxClarificationTasks() {
            items = fetched
            index = 0
            loaded = true
            step = .decision
        } else {
            loaded = false
        }
        loading = false
    }

    private func submit(_ item: BrainBuddyTask) async {
        guard validAnswer else { return }
        switch step {
        case .decision:
            break
        case .nextTitle:
            let title = proposedTitle.trimmingCharacters(in: .whitespacesAndNewlines)
            let changes = title == item.title ? TaskChanges() : TaskChanges(title: .set(title))
            if await model.saveTask(item, changes: changes, destinationState: .next) { advance() }
        case .waitingReason:
            step = .waitingTitle
        case .waitingTitle:
            let title = proposedTitle.trimmingCharacters(in: .whitespacesAndNewlines)
            let reason = waitingReason.trimmingCharacters(in: .whitespacesAndNewlines)
            let changes = TaskChanges(
                title: title == item.title ? .unchanged : .set(title), waitingFor: .set(reason)
            )
            if await model.saveTask(item, changes: changes, destinationState: .waiting) { advance() }
        case .projectName:
            step = .projectOutcome
        case .projectOutcome:
            step = .projectAction
        case .projectAction:
            if await model.clarifyInboxAsProject(
                item, projectName: projectName,
                outcome: desiredOutcome, firstAction: firstAction
            ) { advance() }
        }
    }

    private func advance() {
        index += 1
        step = .decision
        model.error = nil
    }
}

private enum WaitingReviewDecision {
    case followUp, returnToNext
}

private struct WaitingReviewView: View {
    @ObservedObject var model: BrainBuddyModel
    @Environment(\.dismiss) private var dismiss
    @State private var items: [BrainBuddyTask] = []
    @State private var index = 0
    @State private var loading = true
    @State private var loaded = false
    @State private var decision: WaitingReviewDecision?
    @State private var actionTitle = ""
    @State private var confirmingCancel = false

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            HStack {
                VStack(alignment: .leading, spacing: 3) {
                    Text("Review Waiting for").font(.title2.bold())
                    Text(loaded ? (items.isEmpty ? "No items" : "\(min(index + 1, items.count)) of \(items.count)") : "One item at a time")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                }
                Spacer()
                Button("Close review") { dismiss() }
                    .keyboardShortcut(.cancelAction)
                    .disabled(model.busy)
            }

            if loading {
                ProgressView("Loading Waiting for tasks…")
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else if !loaded {
                ContentUnavailableView("Could not load review", systemImage: "arrow.clockwise",
                                       description: Text(model.error ?? "Try again."))
                Button("Retry") { Task { await load() } }
            } else if items.isEmpty {
                ContentUnavailableView("Nothing is waiting", systemImage: "hourglass",
                                       description: Text("Waiting for tasks will appear here for review."))
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else if index >= items.count {
                ContentUnavailableView("Waiting review complete", systemImage: "checkmark.circle",
                                       description: Text("The items you checked remain in their chosen GTD lists."))
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else {
                let item = items[index]
                VStack(alignment: .leading, spacing: 12) {
                    Text(item.title).font(.title3.weight(.semibold))
                        .frame(maxWidth: .infinity, alignment: .leading)
                    if let details = item.details, !details.isEmpty {
                        Text(details)
                            .foregroundStyle(.secondary)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .lineLimit(4)
                    }
                    Label("Waiting for \(item.waiting_for ?? "an unspecified response")", systemImage: "hourglass")
                        .font(.subheadline.weight(.medium))
                    if let date = item.waiting_since.flatMap(Self.waitingDate) {
                        Text("Since \(date.formatted(date: .abbreviated, time: .omitted))")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                    if let projectID = item.project_id {
                        Text("Project · \((model.projects + model.archivedProjects).first(where: { $0.id == projectID })?.name ?? "Unknown project")")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }
                .padding(18)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(.quaternary.opacity(0.6), in: RoundedRectangle(cornerRadius: 12))

                if let decision {
                    VStack(alignment: .leading, spacing: 10) {
                        Text(decision == .followUp ? "What will you do to follow up?" : "What is the next action now?")
                            .font(.headline)
                        TextField("Concrete next action", text: $actionTitle)
                            .textFieldStyle(.roundedBorder)
                            .accessibilityLabel("Concrete next action")
                            .onSubmit { Task { await submit(item, decision: decision) } }
                        Text(decision == .followUp
                             ? (isArchivedProject(item)
                                ? "Restore this archived project before creating a follow-up in it."
                                : "Creates a separate Next action in the same project. This item stays in Waiting for.")
                             : "Moves this item to Next actions and clears its active waiting details.")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                        HStack {
                            Button("Back") { self.decision = nil }
                            Spacer()
                            Button(decision == .followUp ? "Create follow-up" : "Move to Next actions") {
                                Task { await submit(item, decision: decision) }
                            }
                            .buttonStyle(.borderedProminent)
                            .disabled(model.busy || !validActionTitle ||
                                      (decision == .followUp && isArchivedProject(item)))
                        }
                    }
                } else {
                    Text("What should happen next?")
                        .font(.headline)
                    HStack(spacing: 10) {
                        Button("Keep waiting") { advance() }
                            .help("Skip for this review; no reminder or review date is set")
                        Button("Create follow-up…") {
                            actionTitle = ""
                            decision = .followUp
                        }
                        .disabled(isArchivedProject(item))
                        Button("Returned to me…") {
                            actionTitle = item.title
                            decision = .returnToNext
                        }
                        Button("No longer relevant…", role: .destructive) { confirmingCancel = true }
                    }
                    .disabled(model.busy)
                    if isArchivedProject(item) {
                        Text("Restore the archived project to add a follow-up there.")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }
                if let error = model.error {
                    Text(error).font(.caption).foregroundStyle(.red)
                }
            }
            Spacer(minLength: 0)
        }
        .padding(24)
        .frame(width: 640, height: 480)
        .task { await load() }
        .confirmationDialog("Cancel this task?", isPresented: $confirmingCancel) {
            Button("Cancel task", role: .destructive) {
                guard index < items.count else { return }
                let item = items[index]
                Task { if await model.cancelTask(item) { advance() } }
            }
            Button("Keep task", role: .cancel) {}
        } message: {
            Text("The task will move to history. No message will be sent.")
        }
    }

    private var validActionTitle: Bool {
        let title = actionTitle.trimmingCharacters(in: .whitespacesAndNewlines)
        return !title.isEmpty && title.count <= 500
    }

    private func isArchivedProject(_ task: BrainBuddyTask) -> Bool {
        guard let projectID = task.project_id else { return false }
        return model.archivedProjects.contains { $0.id == projectID }
    }

    private func load() async {
        loading = true
        if let fetched = await model.loadWaitingReviewTasks() {
            items = fetched
            index = 0
            loaded = true
            decision = nil
        } else {
            loaded = false
        }
        loading = false
    }

    private func submit(_ item: BrainBuddyTask, decision: WaitingReviewDecision) async {
        guard validActionTitle else { return }
        let title = actionTitle.trimmingCharacters(in: .whitespacesAndNewlines)
        let saved: Bool
        switch decision {
        case .followUp:
            saved = await model.createFollowUp(for: item, title: title)
        case .returnToNext:
            let changes = title == item.title ? TaskChanges() : TaskChanges(title: .set(title))
            saved = await model.saveTask(item, changes: changes, destinationState: .next)
        }
        if saved { advance() }
    }

    private func advance() {
        index += 1
        decision = nil
        actionTitle = ""
        model.error = nil
    }

    private static func waitingDate(_ value: String) -> Date? {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if let date = formatter.date(from: value) { return date }
        formatter.formatOptions = [.withInternetDateTime]
        return formatter.date(from: value)
    }
}

private enum NewCollection: String, Identifiable {
    case project, tag
    var id: String { rawValue }
}

private enum CollectionToEdit: Identifiable {
    case project(String), tag(String)

    var id: String {
        switch self {
        case .project(let id): "project:\(id)"
        case .tag(let id): "tag:\(id)"
        }
    }

    var isProject: Bool {
        if case .project = self { return true }
        return false
    }
}

private struct TaskInlineEditor<Extras: View>: View {
    let task: BrainBuddyTask
    @Binding var title: String
    let projects: [BrainBuddyProject]
    let tags: [BrainBuddyTag]
    let busy: Bool
    let requiresCurrentTask: Bool
    let saveRequest: Int
    let onSave: (TaskChanges, TaskList?) async -> Void
    let onCancel: () -> Void
    let onCreateProject: (String) async -> BrainBuddyProject?
    let onEditorStateChange: (Bool, Bool) -> Void
    let onCancelTask: () -> Void
    let extras: (@escaping (Bool) -> Void) -> Extras

    @State private var baseline: BrainBuddyTask
    @State private var extrasDirty = false
    @State private var details: String
    @State private var projectID: String
    @State private var tagIDs: Set<String>
    @State private var dueDate: String
    @State private var dueEnabled: Bool
    @State private var priority: TaskPriority
    @State private var state: TaskList
    @State private var waitingFor: String
    @State private var showingProjectCreator = false
    @State private var newProjectName = ""
    @State private var showProperties: Bool

    init(
        task: BrainBuddyTask, title: Binding<String>,
        projects: [BrainBuddyProject], tags: [BrainBuddyTag], busy: Bool,
        requiresCurrentTask: Bool, saveRequest: Int,
        onSave: @escaping (TaskChanges, TaskList?) async -> Void,
        onCancel: @escaping () -> Void,
        onCreateProject: @escaping (String) async -> BrainBuddyProject?,
        onEditorStateChange: @escaping (Bool, Bool) -> Void,
        onCancelTask: @escaping () -> Void,
        @ViewBuilder extras: @escaping (@escaping (Bool) -> Void) -> Extras
    ) {
        self.task = task
        _title = title
        self.projects = projects
        self.tags = tags
        self.busy = busy
        self.requiresCurrentTask = requiresCurrentTask
        self.saveRequest = saveRequest
        self.onSave = onSave
        self.onCancel = onCancel
        self.onCreateProject = onCreateProject
        self.onEditorStateChange = onEditorStateChange
        self.onCancelTask = onCancelTask
        self.extras = extras
        _baseline = State(initialValue: task)
        _details = State(initialValue: task.details ?? "")
        _projectID = State(initialValue: task.project_id ?? "")
        _tagIDs = State(initialValue: Set(task.tag_ids))
        _dueDate = State(initialValue: task.due_date ?? "")
        _dueEnabled = State(initialValue: task.due_date != nil)
        _priority = State(initialValue: task.priority)
        _state = State(initialValue: TaskList(rawValue: task.state) ?? .next)
        _waitingFor = State(initialValue: task.waiting_for ?? "")
        _showProperties = State(initialValue: task.due_date != nil || task.priority != .none || !task.tag_ids.isEmpty)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Button("Save task", action: saveChanges)
                    .buttonStyle(.borderedProminent)
                    .keyboardShortcut("s", modifiers: [.command])
                    .disabled(saveDisabled)
                Button(isDirty ? "Discard task edits" : "Close", action: onCancel)
                    .keyboardShortcut(.cancelAction)
                    .disabled(busy)
                Spacer()
                Menu("More") {
                    Button("Cancel task", role: .destructive, action: onCancelTask)
                }
                .disabled(busy)
            }
            Text("Notes and context")
                .font(.caption)
                .foregroundStyle(.secondary)
            TextEditor(text: $details)
                .font(.body)
                .scrollContentBackground(.hidden)
                .frame(height: 120)
                .padding(5)
                .background(.quaternary.opacity(0.45), in: RoundedRectangle(cornerRadius: 8))
                .accessibilityLabel("Notes and context")
            HStack(alignment: .top, spacing: 16) {
                Picker("GTD list", selection: $state) {
                    ForEach(TaskList.allCases) { value in
                        Text(value.title).tag(value)
                    }
                }
                .pickerStyle(.menu)
                .frame(maxWidth: .infinity, alignment: .leading)
                VStack(alignment: .leading, spacing: 4) {
                    Picker("Project", selection: $projectID) {
                        Text("No project").tag("")
                        if let archived = projects.first(where: { $0.id == projectID && $0.state == "archived" }) {
                            Text("\(archived.name) (archived)").tag(archived.id)
                        }
                        ForEach(projects.filter { $0.state == "active" }) { project in
                            Text(project.name).tag(project.id)
                        }
                    }
                    .pickerStyle(.menu)
                    Button("New project…") { showingProjectCreator = true }
                        .font(.caption)
                        .disabled(busy)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            if state == .waiting {
                TextField("Waiting for person, event, or condition", text: $waitingFor)
                    .accessibilityLabel("Waiting for person, event, or condition")
            }
            DisclosureGroup(isExpanded: $showProperties) {
                VStack(alignment: .leading, spacing: 10) {
                    Toggle("Due date", isOn: $dueEnabled)
                        .onChange(of: dueEnabled) { _, enabled in
                            dueDate = enabled ? Self.dayFormatter.string(from: Date()) : ""
                        }
                    if dueEnabled {
                        DatePicker(
                            "Choose date",
                            selection: Binding(
                                get: { Self.dayFormatter.date(from: dueDate) ?? Date() },
                                set: { dueDate = Self.dayFormatter.string(from: $0) }
                            ),
                            displayedComponents: .date
                        )
                        .datePickerStyle(.compact)
                    }
                    Picker("Priority", selection: $priority) {
                        ForEach(TaskPriority.allCases, id: \.self) { value in
                            Text(value.rawValue.capitalized).tag(value)
                        }
                    }
                    if !tags.isEmpty {
                        VStack(alignment: .leading, spacing: 5) {
                            Text("Tags").font(.caption).foregroundStyle(.secondary)
                            ChipFlowLayout(spacing: 6) {
                                ForEach(tags.filter { tagIDs.contains($0.id) && $0.state == "active" }) { tag in
                                    Button { tagIDs.remove(tag.id) } label: {
                                        Label("#\(tag.name)", systemImage: "xmark")
                                            .font(.caption)
                                            .foregroundStyle(tagTint(tag.id))
                                            .padding(.horizontal, 8)
                                            .padding(.vertical, 4)
                                            .background(tagTint(tag.id).opacity(0.16), in: Capsule())
                                    }
                                    .buttonStyle(.plain)
                                    .accessibilityLabel("Remove \(tag.name) tag")
                                }
                                Menu {
                                    ForEach(tags.filter { !tagIDs.contains($0.id) && $0.state == "active" }) { tag in
                                        Button("#\(tag.name)") { tagIDs.insert(tag.id) }
                                    }
                                } label: {
                                    Label("Add tag", systemImage: "plus")
                                        .font(.caption)
                                        .padding(.horizontal, 8)
                                        .padding(.vertical, 4)
                                        .background(.quaternary, in: Capsule())
                                }
                                .menuStyle(.borderlessButton)
                            }
                        }
                    }
                }
                .padding(.top, 8)
            } label: {
                HStack {
                    Text("Date, priority, and tags")
                    Spacer()
                    Text(propertySummary)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }
            extras { extrasDirty = $0 }
            if extrasDirty {
                Text("Finish the pending subtask or comment edit before saving the task.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
        .textFieldStyle(.roundedBorder)
        .padding(.top, 12)
        .sheet(isPresented: $showingProjectCreator) {
            VStack(alignment: .leading, spacing: 14) {
                Text("New project").font(.title2.bold())
                TextField("Project name", text: $newProjectName)
                HStack {
                    Spacer()
                    Button("Cancel") { showingProjectCreator = false }
                    Button("Add project") {
                        Task {
                            if let project = await onCreateProject(newProjectName) {
                                projectID = project.id
                                newProjectName = ""
                                showingProjectCreator = false
                            }
                        }
                    }
                    .buttonStyle(.borderedProminent)
                    .disabled(newProjectName.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || busy)
                }
            }
            .padding(22)
            .frame(width: 340)
        }
        .onAppear { onEditorStateChange(isDirty, !saveDisabled) }
        .onChange(of: isDirty) { _, _ in onEditorStateChange(isDirty, !saveDisabled) }
        .onChange(of: saveDisabled) { _, _ in onEditorStateChange(isDirty, !saveDisabled) }
        .onChange(of: saveRequest) { _, _ in saveChanges() }
    }

    private func saveChanges() {
        guard taskFieldsDirty, !saveDisabled else { return }
        Task { await onSave(changes, state.rawValue == baseline.state ? nil : state) }
    }

    private var taskFieldsDirty: Bool {
        changes.hasChanges || state.rawValue != baseline.state
    }

    private var isDirty: Bool {
        taskFieldsDirty || extrasDirty
    }

    private var saveDisabled: Bool {
        let trimmed = title.trimmingCharacters(in: .whitespacesAndNewlines)
        return !taskFieldsDirty || busy || requiresCurrentTask || extrasDirty || trimmed.isEmpty || trimmed.count > 500 || details.count > 20_000
            || (!dueDate.isEmpty && !Self.validDay(dueDate))
            || (state == .waiting && waitingFor.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
    }

    private var propertySummary: String {
        var parts: [String] = []
        if dueEnabled { parts.append("Due") }
        if priority != .none { parts.append(priority.rawValue.capitalized) }
        if !tagIDs.isEmpty { parts.append("\(tagIDs.count) tags") }
        return parts.isEmpty ? "Optional" : parts.joined(separator: " · ")
    }

    private static func validDay(_ value: String) -> Bool {
        dayFormatter.date(from: value).map { dayFormatter.string(from: $0) == value } ?? false
    }

    private static var dayFormatter: DateFormatter {
        let formatter = DateFormatter()
        formatter.dateFormat = "yyyy-MM-dd"
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.isLenient = false
        return formatter
    }

    private var changes: TaskChanges {
        TaskChanges(
            title: title == baseline.title ? .unchanged : .set(title.trimmingCharacters(in: .whitespacesAndNewlines)),
            details: details == (baseline.details ?? "") ? .unchanged : (details.isEmpty ? .clear : .set(details)),
            projectID: projectID == (baseline.project_id ?? "") ? .unchanged : (projectID.isEmpty ? .clear : .set(projectID)),
            tagIDs: tagIDs == Set(baseline.tag_ids) ? .unchanged : .set(tagIDs.sorted()),
            dueDate: dueDate == (baseline.due_date ?? "") ? .unchanged : (dueDate.isEmpty ? .clear : .set(dueDate)),
            priority: priority == baseline.priority ? .unchanged : .set(priority),
            waitingFor: waitingFor == (baseline.waiting_for ?? "") ? .unchanged : (waitingFor.isEmpty ? .clear : .set(waitingFor))
        )
    }
}

private struct ChipFlowLayout: Layout {
    let spacing: CGFloat

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        arrange(subviews, width: proposal.width ?? 500).size
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        let arranged = arrange(subviews, width: bounds.width)
        for (index, subview) in subviews.enumerated() {
            subview.place(
                at: CGPoint(x: bounds.minX + arranged.positions[index].x,
                            y: bounds.minY + arranged.positions[index].y),
                proposal: .unspecified
            )
        }
    }

    private func arrange(_ subviews: Subviews, width: CGFloat) -> (positions: [CGPoint], size: CGSize) {
        var positions: [CGPoint] = []
        var x: CGFloat = 0
        var y: CGFloat = 0
        var rowHeight: CGFloat = 0
        for subview in subviews {
            let size = subview.sizeThatFits(.unspecified)
            if x > 0 && x + size.width > width {
                x = 0
                y += rowHeight + spacing
                rowHeight = 0
            }
            positions.append(CGPoint(x: x, y: y))
            x += size.width + spacing
            rowHeight = max(rowHeight, size.height)
        }
        return (positions, CGSize(width: width, height: y + rowHeight))
    }
}

private struct TaskDetailExtras: View {
    let task: BrainBuddyTask
    @ObservedObject var model: BrainBuddyModel
    let onDirtyChange: (Bool) -> Void
    @State private var newSubtask = ""
    @State private var newComment = ""
    @State private var modifiedIDs: Set<String> = []
    @State private var subtaskTitles: [String: String] = [:]
    @State private var commentBodies: [String: String] = [:]
    @State private var editingCommentIDs: Set<String> = []

    private var completedSubtasks: Int {
        task.subtasks.filter { $0.state == "completed" }.count
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            DisclosureGroup("Subtasks · \(completedSubtasks) / \(task.subtasks.count)") {
                VStack(alignment: .leading, spacing: 8) {
                    ForEach(task.subtasks.sorted { $0.order_key < $1.order_key }) { subtask in
                        SubtaskLine(
                            taskID: task.id, subtask: subtask, model: model,
                            title: subtaskTitle(for: subtask),
                            onSaved: {
                                subtaskTitles.removeValue(forKey: subtask.id)
                                setModified("subtask-\(subtask.id)", dirty: false)
                            }
                        )
                    }
                    HStack {
                        TextField("New subtask", text: $newSubtask)
                            .onSubmit { addSubtask() }
                        Button("Add subtask") { addSubtask() }
                            .disabled(
                                newSubtask.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                                    || newSubtask.count > 500 || model.busy
                            )
                    }
                }
                .padding(.top, 6)
            }
            DisclosureGroup("Comments · \(task.comments.count)") {
                VStack(alignment: .leading, spacing: 8) {
                    ForEach(task.comments) { comment in
                        CommentLine(
                            taskID: task.id, comment: comment, model: model,
                            canEdit: comment.actor_id == model.account?.id,
                            editing: commentEditing(for: comment),
                            draftBody: commentBody(for: comment),
                            onFinished: {
                                commentBodies.removeValue(forKey: comment.id)
                                setModified("comment-\(comment.id)", dirty: false)
                            }
                        )
                    }
                    TextField("Write a comment", text: $newComment, axis: .vertical)
                        .lineLimit(2...4)
                    Button("Add comment") {
                        let body = newComment
                        Task {
                            if await model.addComment(to: task.id, body: body) { newComment = "" }
                        }
                    }
                    .disabled(newComment.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                              || newComment.count > 20_000 || model.busy)
                }
                .padding(.top, 6)
            }
            Text("Subtasks and comments save immediately. Discard keeps those saved changes.")
                .font(.caption)
                .foregroundStyle(.secondary)
        }
        .font(.subheadline)
        .onChange(of: newSubtask) { _, _ in reportDirty() }
        .onChange(of: newComment) { _, _ in reportDirty() }
    }

    private func setModified(_ id: String, dirty: Bool) {
        if dirty { modifiedIDs.insert(id) }
        else { modifiedIDs.remove(id) }
        reportDirty()
    }

    private func subtaskTitle(for subtask: BrainBuddySubtask) -> Binding<String> {
        Binding(
            get: { subtaskTitles[subtask.id] ?? subtask.title },
            set: { value in
                subtaskTitles[subtask.id] = value
                setModified("subtask-\(subtask.id)", dirty: value != subtask.title)
            }
        )
    }

    private func commentEditing(for comment: BrainBuddyComment) -> Binding<Bool> {
        Binding(
            get: { editingCommentIDs.contains(comment.id) },
            set: { editing in
                if editing { editingCommentIDs.insert(comment.id) }
                else { editingCommentIDs.remove(comment.id) }
                setModified(
                    "comment-\(comment.id)",
                    dirty: editing && (commentBodies[comment.id] ?? comment.body) != comment.body
                )
            }
        )
    }

    private func commentBody(for comment: BrainBuddyComment) -> Binding<String> {
        Binding(
            get: { commentBodies[comment.id] ?? comment.body },
            set: { value in
                commentBodies[comment.id] = value
                setModified("comment-\(comment.id)", dirty: editingCommentIDs.contains(comment.id) && value != comment.body)
            }
        )
    }

    private func reportDirty() {
        onDirtyChange(
            !newSubtask.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                || !newComment.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                || !modifiedIDs.isEmpty
        )
    }

    private func addSubtask() {
        let title = newSubtask
        Task {
            if await model.addSubtask(to: task.id, title: title) { newSubtask = "" }
        }
    }
}

private struct SubtaskLine: View {
    let taskID: String
    let subtask: BrainBuddySubtask
    @ObservedObject var model: BrainBuddyModel
    @Binding var title: String
    let onSaved: () -> Void

    var body: some View {
        HStack {
            Button {
                Task { await model.toggleSubtask(subtask, in: taskID) }
            } label: {
                Image(systemName: subtask.state == "completed" ? "checkmark.circle.fill" : "circle")
            }
            .buttonStyle(.plain)
            .accessibilityLabel("\(subtask.state == "completed" ? "Reopen" : "Complete") \(subtask.title)")
            .disabled(model.busy)
            TextField("Subtask title", text: $title)
                .onSubmit { saveTitle() }
                .disabled(model.busy)
            if title != subtask.title {
                Button("Save") { saveTitle() }
                    .disabled(model.busy || title.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                              || title.count > 500)
            }
        }
    }

    private func saveTitle() {
        guard title != subtask.title else { return }
        Task {
            if await model.renameSubtask(subtask, in: taskID, title: title) { onSaved() }
        }
    }
}

private struct CommentLine: View {
    let taskID: String
    let comment: BrainBuddyComment
    @ObservedObject var model: BrainBuddyModel
    let canEdit: Bool
    @Binding var editing: Bool
    @Binding var draftBody: String
    let onFinished: () -> Void

    var bodyView: some View {
        VStack(alignment: .leading, spacing: 5) {
            if editing {
                TextField("Comment", text: $draftBody, axis: .vertical)
                    .lineLimit(2...4)
                HStack {
                    Button("Save") {
                        Task {
                            if await model.editComment(comment, in: taskID, body: draftBody) {
                                editing = false
                                onFinished()
                            }
                        }
                    }
                    .disabled(draftBody.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                              || draftBody.count > 20_000 || model.busy)
                    Button("Cancel") {
                        editing = false
                        onFinished()
                    }
                }
            } else {
                Text(comment.body)
                    .frame(maxWidth: .infinity, alignment: .leading)
                if canEdit {
                    Button("Edit comment") { editing = true }
                        .font(.caption)
                }
            }
        }
        .padding(8)
        .background(.quinary, in: RoundedRectangle(cornerRadius: 8))
    }

    var body: some View { bodyView }
}
