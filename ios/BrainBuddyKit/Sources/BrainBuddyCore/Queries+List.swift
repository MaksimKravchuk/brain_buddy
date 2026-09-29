import Foundation

extension GTDQueries {
    /// Section order inside a project view: what can be done now, what is
    /// being tracked, what still needs clarifying, then what is parked.
    /// Unclarified inbox items need a decision sooner than someday / maybe ones.
    public static let projectListOrder: [OpenList] = [.next, .waiting, .inbox, .someday]

    /// Title of the group-by-project section for tasks without a (known) project.
    public static let noProjectTitle = "No project"
}

/// Builds one `TaskListResult`. Every destination is a single pass over the
/// tasks (filters first, then membership), followed by sorting and sectioning,
/// so a call is O(n log n) in the number of tasks.
struct TaskListBuilder {
    let state: GTDState
    let options: ListOptions
    let today: CalendarDay

    func build(_ destination: Destination) -> TaskListResult {
        switch destination {
        case .list(let list):
            // Inbox is the projectless projection, for its history too.
            let projectless = list == .inbox
            return standard(
                sort: options.sort, groupable: !projectless,
                open: { $0.state == list.taskState && (!projectless || $0.projectID == nil) },
                ended: { $0.lastOpenList == list && (!projectless || $0.projectID == nil) }
            )
        case .agenda:
            return agenda()
        case .dateView(let view):
            let inView: (TaskRecord) -> Bool = { DateView(due: $0.dueDate, today: today) == view }
            return standard(sort: dateSort, groupable: true, open: inView, ended: inView)
        case .project(let id):
            return project(id)
        case .tag(let id):
            let tagged: (TaskRecord) -> Bool = { $0.tagIDs.contains(id) }
            return standard(sort: options.sort, groupable: true, open: tagged, ended: tagged)
        case .history(let kind):
            return history(kind)
        case .search(let text):
            return search(text)
        }
    }

    // MARK: Destinations

    private func agenda() -> TaskListResult {
        let dated: (TaskRecord) -> Bool = { $0.dueDate != nil }
        let parts = partition(open: dated, ended: dated)
        var byView: [DateView: [TaskRecord]] = [:]
        for task in parts.open {
            if let view = DateView(due: task.dueDate, today: today) { byView[view, default: []].append(task) }
        }
        let sections = DateView.allCases.compactMap { view in
            byView[view].map {
                TaskSection(
                    id: "date:\(view.rawValue)", title: view.title, kind: .dateView(view),
                    tasks: TaskOrdering.sorted($0, by: dateSort))
            }
        }
        return TaskListResult(
            sections: sections + endedSections(parts, sort: dateSort), openCount: parts.open.count)
    }

    private func project(_ id: ProjectID) -> TaskListResult {
        let member: (TaskRecord) -> Bool = { $0.projectID == id }
        let parts = partition(open: member, ended: member)
        let byState = Dictionary(grouping: parts.open, by: \.state)
        let sections = GTDQueries.projectListOrder.compactMap { list in
            byState[list.taskState].map {
                TaskSection(
                    id: "list:\(list.rawValue)", title: list.title, kind: .list(list),
                    tasks: TaskOrdering.sorted($0, by: options.sort))
            }
        }
        return TaskListResult(
            sections: sections + endedSections(parts, sort: options.sort), openCount: parts.open.count)
    }

    private func history(_ kind: HistoryKind) -> TaskListResult {
        let target: TaskState = kind == .completed ? .completed : .cancelled
        let tasks = state.tasks.values.filter { $0.state == target && passesFilters($0) }
        let ordered =
            options.sort == .manual ? TaskOrdering.byRecency(tasks) : TaskOrdering.sorted(tasks, by: options.sort)
        let sections: [TaskSection]
        if options.groupByProject {
            sections = projectSections(ordered)
        } else {
            let sectionKind: TaskSection.Kind = kind == .completed ? .completed : .cancelled
            sections = ordered.isEmpty ? [] : [TaskSection(id: kind.rawValue, title: nil, kind: sectionKind, tasks: ordered)]
        }
        return TaskListResult(sections: sections, openCount: 0)
    }

    private func search(_ text: String) -> TaskListResult {
        guard let query = QueryText.searchQuery(text) else { return TaskListResult(sections: [], openCount: 0) }
        let matches: (TaskRecord) -> Bool = { QueryText.searchHaystack(of: $0).contains(query) }
        let parts = partition(open: matches, ended: matches, includeCompleted: true, includeCancelled: true)
        return assemble(parts, sort: options.sort, grouped: options.groupByProject)
    }

    // MARK: Building blocks

    /// Date views read best in date order, so `.manual` means `.due` there.
    private var dateSort: TaskSort { options.sort == .manual ? .due : options.sort }

    private struct Partition {
        var open: [TaskRecord] = []
        var completed: [TaskRecord] = []
        var cancelled: [TaskRecord] = []
    }

    private func standard(
        sort: TaskSort, groupable: Bool, open: (TaskRecord) -> Bool, ended: (TaskRecord) -> Bool
    ) -> TaskListResult {
        assemble(partition(open: open, ended: ended), sort: sort, grouped: groupable && options.groupByProject)
    }

    /// Splits the tasks that pass the screen's filters into open members and
    /// the terminal tasks the options ask to show.
    private func partition(
        open isOpenMember: (TaskRecord) -> Bool, ended isEndedMember: (TaskRecord) -> Bool,
        includeCompleted: Bool? = nil, includeCancelled: Bool? = nil
    ) -> Partition {
        let showCompleted = includeCompleted ?? options.showCompleted
        let showCancelled = includeCancelled ?? options.showCancelled
        var result = Partition()
        for task in state.tasks.values where passesFilters(task) {
            switch task.state {
            case .inbox, .next, .waiting, .someday:
                if isOpenMember(task) { result.open.append(task) }
            case .completed:
                if showCompleted && isEndedMember(task) { result.completed.append(task) }
            case .cancelled:
                if showCancelled && isEndedMember(task) { result.cancelled.append(task) }
            }
        }
        return result
    }

    private func passesFilters(_ task: TaskRecord) -> Bool {
        if !options.priorities.isEmpty && !options.priorities.contains(task.priority) { return false }
        if let tag = options.tagFilter, !task.tagIDs.contains(tag) { return false }
        return true
    }

    private func assemble(_ parts: Partition, sort: TaskSort, grouped: Bool) -> TaskListResult {
        let open = TaskOrdering.sorted(parts.open, by: sort)
        let openSections: [TaskSection]
        if grouped {
            openSections = projectSections(open)
        } else {
            openSections = open.isEmpty ? [] : [TaskSection(id: "open", title: nil, kind: .open, tasks: open)]
        }
        return TaskListResult(sections: openSections + endedSections(parts, sort: sort), openCount: open.count)
    }

    /// "Completed" then "Cancelled", each in the screen's sort.
    private func endedSections(_ parts: Partition, sort: TaskSort) -> [TaskSection] {
        var sections: [TaskSection] = []
        if !parts.completed.isEmpty {
            sections.append(
                TaskSection(
                    id: "completed", title: HistoryKind.completed.title, kind: .completed,
                    tasks: TaskOrdering.sorted(parts.completed, by: sort)))
        }
        if !parts.cancelled.isEmpty {
            sections.append(
                TaskSection(
                    id: "cancelled", title: HistoryKind.cancelled.title, kind: .cancelled,
                    tasks: TaskOrdering.sorted(parts.cancelled, by: sort)))
        }
        return sections
    }

    /// One section per project in name order (active before archived), then
    /// "No project" for tasks without one or whose project is unknown. Each
    /// section keeps the order of `sortedTasks`.
    private func projectSections(_ sortedTasks: [TaskRecord]) -> [TaskSection] {
        var byProject: [ProjectID: [TaskRecord]] = [:]
        var loose: [TaskRecord] = []
        for task in sortedTasks {
            if let id = task.projectID, state.projects[id] != nil {
                byProject[id, default: []].append(task)
            } else {
                loose.append(task)
            }
        }
        var sections = byProject.keys.compactMap { state.projects[$0] }
            .map { (rank: ($0.state == .archived ? 1 : 0, $0.nameSortKey), project: $0) }
            .sorted { $0.rank < $1.rank }
            .map { entry in
                TaskSection(
                    id: "project:\(entry.project.id.rawValue)", title: entry.project.name,
                    kind: .project(entry.project.id), tasks: byProject[entry.project.id] ?? [])
            }
        if !loose.isEmpty {
            sections.append(TaskSection(id: "none", title: GTDQueries.noProjectTitle, kind: .project(nil), tasks: loose))
        }
        return sections
    }
}
