import SwiftUI

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
        didSet { if draft != oldValue { pendingCreate = nil } }
    }
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
        tags = []
        nextCursor = nil
        loading = false
        draft = ""
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

    func reload() async {
        listRequestSerial += 1
        let serial = listRequestSerial
        let query = query()
        let previousRows = tasks
        let previousCounts = openCounts
        let previousSidebarCounts = sidebarCounts
        let previousCursor = nextCursor
        let previousQuery = displayedQuery
        if displayedQuery != nil && displayedQuery != query {
            tasks = []
            openCounts = nil
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
            guard serial == listRequestSerial else { return }
            tasks = page.items
            openCounts = page.counts_by_state
            sidebarCounts = globalCounts
            nextCursor = page.next_cursor
            displayedQuery = query
        } catch {
            if serial == listRequestSerial {
                if let apiError = error as? APIError, apiError.statusCode == 401 {
                    tasks = previousRows
                    openCounts = previousCounts
                    sidebarCounts = previousSidebarCounts
                    nextCursor = previousCursor
                    displayedQuery = previousQuery
                }
                handleRequestFailure(error)
            }
        }
        if serial == listRequestSerial { loading = false }
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
            contextProjectId: contextProjectID, contextTagId: contextTagID
        )
        let captureState = selectedList
        let waitingFor = waitingForDraft.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !busy else { return }
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

    func cancelTask(_ task: BrainBuddyTask) async {
        guard !busy else { return }
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
        } catch {
            handleRequestFailure(error)
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
            if destination == .project(id) { destination = .list(.next) }
            await reload()
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
            if destination == .tag(id) { destination = .list(.next) }
            await reload()
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
    case task(String?)
    case complete(BrainBuddyTask)
    case reopen(BrainBuddyTask)
    case cancel(BrainBuddyTask)
    case newTask
    case reload
    case signOut
    case createTask
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
    @State private var tagToDelete: BrainBuddyTag?
    @State private var confirmingTagDeletion = false
    @State private var reopeningTask: BrainBuddyTask?
    @State private var reopenDestination: TaskList = .next
    @State private var reopenWaitingFor = ""
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
        .onChange(of: model.account?.id) { previousID, accountID in
            if accountID != nil {
                password = ""
                if previousID != nil && previousID != accountID {
                    selectedTaskID = nil
                    editorDirty = false
                }
            } else {
                voicePresented = false
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
                Button("Save changes") { editorSaveRequest += 1 }
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
            Text("The current task or new task draft has changes that have not been saved.")
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
            Task { await model.choose(destination) }
        case .task(let id):
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
            Task { await model.completeTask(task) }
        case .reopen(let task):
            selectedTaskID = nil
            model.error = nil
            reopenDestination = .next
            reopenWaitingFor = ""
            reopeningTask = task
        case .cancel(let task):
            selectedTaskID = nil
            Task { await model.cancelTask(task) }
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
        case .signOut:
            selectedTaskID = nil
            Task { await model.signOut() }
        case .createTask:
            selectedTaskID = nil
            Task { await model.createTask() }
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

    private var taskCanvas: some View {
        VStack(alignment: .leading, spacing: 0) {
            VStack(alignment: .leading, spacing: 12) {
                Text(destinationTitle).font(.largeTitle.bold())
                Text(taskCountCaption)
                    .foregroundStyle(.secondary)
                    .font(.subheadline)
                HStack(spacing: 16) {
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
        model.tasks.filter { $0.state != "completed" && $0.state != "cancelled" }
    }

    private var completedTasks: [BrainBuddyTask] {
        model.tasks.filter { $0.state == "completed" }
    }

    private var cancelledTasks: [BrainBuddyTask] {
        model.tasks.filter { $0.state == "cancelled" }
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
        .id("\(task.id):\(task.revision):\(task.state)")
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
                    if let projectName = smartDraft.previewProjectName(in: model.projects) {
                        Text("◈ \(projectName)")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                            .lineLimit(1)
                    }
                    let tagNames = smartDraft.previewTagNames(in: model.tags)
                    if !tagNames.isEmpty {
                        Text(tagNames.map { "#\($0)" }.joined(separator: "  "))
                            .font(.caption)
                            .foregroundStyle(.secondary)
                            .lineLimit(1)
                    }
                    Spacer()
                    Button("Add task") { requestNavigation(.createTask) }
                        .buttonStyle(.borderedProminent)
                        .disabled(addDisabled)
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
            contextProjectId: projectID, contextTagId: tagID
        )
    }

    private var smartCaptureState: TaskList {
        model.selectedList
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
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(alignment: .top, spacing: 12) {
                TextEditor(text: $details)
                    .font(.body)
                    .frame(minHeight: 90)
                    .border(Color.primary.opacity(0.15))
                    .accessibilityLabel("Description")
                VStack(spacing: 8) {
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
                    Picker("State", selection: $state) {
                        ForEach(TaskList.allCases) { value in
                            Text(value.title).tag(value)
                        }
                    }
                    Picker("Project", selection: $projectID) {
                        Text("No project").tag("")
                        if let archived = projects.first(where: { $0.id == projectID && $0.state == "archived" }) {
                            Text("\(archived.name) (archived)").tag(archived.id)
                        }
                        ForEach(projects.filter { $0.state == "active" }) { project in
                            Text(project.name).tag(project.id)
                        }
                    }
                    Button("New project…") { showingProjectCreator = true }
                        .disabled(busy)
                }
                .frame(width: 220)
            }
            if state == .waiting {
                TextField("Waiting for person, event, or condition", text: $waitingFor)
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
            extras { extrasDirty = $0 }
            if extrasDirty {
                Text("Finish the pending subtask or comment edit before saving the task.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            HStack {
                Button("Save changes", action: saveChanges)
                .buttonStyle(.borderedProminent)
                .keyboardShortcut("s", modifiers: [.command])
                .disabled(saveDisabled)
                Button("Cancel", action: onCancel)
                    .keyboardShortcut(.cancelAction)
                    .disabled(busy)
                Menu("More") {
                    Button("Cancel task", role: .destructive, action: onCancelTask)
                }
                .disabled(busy)
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
        guard isDirty, !saveDisabled else { return }
        Task { await onSave(changes, state.rawValue == baseline.state ? nil : state) }
    }

    private var isDirty: Bool {
        changes.hasChanges || state.rawValue != baseline.state || extrasDirty
    }

    private var saveDisabled: Bool {
        let trimmed = title.trimmingCharacters(in: .whitespacesAndNewlines)
        return busy || requiresCurrentTask || extrasDirty || trimmed.isEmpty || trimmed.count > 500 || details.count > 20_000
            || (!dueDate.isEmpty && !Self.validDay(dueDate))
            || (state == .waiting && waitingFor.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
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
            Text("Subtask and comment changes save immediately.")
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
