import BrainBuddyCore
import Foundation

/// A realistic local-only dataset for SwiftUI previews and UI tests
/// (`Workspace.preview()`). It is built the way a person builds theirs: each
/// command goes through `GTDReducer` and into the outbox through
/// `OutboxCompactor`, so the preview exercises the same paths as the app.
///
/// It covers every screen: projectless Inbox items, Next actions with
/// contexts ("home", "calls", "errands", "computer"), Waiting for, Someday /
/// maybe, tasks due yesterday, today and next week, completed and cancelled
/// history, subtasks and comments, a project that needs a next action and an
/// archived project.
enum SampleData {
    static func document(now: Date, calendar: Calendar = .current) -> StoreDocument {
        let today = CalendarDay(date: now, calendar: calendar)
        // Commands are issued a few minutes apart over the last three days.
        var data = Builder(clock: now.addingTimeInterval(-3 * 24 * 60 * 60))

        let kitchen = data.project("Kitchen renovation", color: "#0EA5E9")
        let offsite = data.project("Team offsite in May", color: "#8B5CF6")
        let taxes = data.project("File the 2026 tax return", color: "#F59E0B")
        let garden = data.project("Spring garden cleanup", color: "#22C55E")

        let home = data.tag("home")
        let calls = data.tag("calls")
        let errands = data.tag("errands")
        let computer = data.tag("computer")

        // Inbox: captured, not clarified yet.
        data.task("Book a dentist check-up", tags: [calls])
        data.task("Look into standing desks")
        data.task("Reply to Maya about the book club", due: today)

        // Next actions.
        data.task(
            "Call the tiler for a quote", in: .next, project: kitchen, tags: [calls], due: today, priority: .high
        )
        data.task(
            "Pick up paint samples", in: .next, project: kitchen, tags: [errands], due: today.adding(days: -1),
            priority: .medium
        )
        let agenda = data.task(
            "Draft the offsite agenda", in: .next, project: offsite, tags: [computer], due: today.adding(days: 7),
            priority: .medium, notes: "Two days, one of them outdoors. Keep the sessions short."
        )
        data.task("Buy light bulbs for the hallway", in: .next, tags: [errands, home])
        data.task("Renew the car insurance", in: .next, tags: [computer], due: today.adding(days: 3), priority: .low)

        // Waiting for.
        data.task(
            "Venue quote for the offsite", in: .waiting, project: offsite, due: today.adding(days: 5),
            waitingFor: "Harbour Hall events team"
        )
        data.task("Refund for the broken kettle", in: .waiting, tags: [home], waitingFor: "Online store support")

        // Someday / maybe. The tax project has no next action yet.
        data.task("Learn to bake sourdough", in: .someday, tags: [home])
        data.task("Collect receipts for deductible expenses", in: .someday, project: taxes)
        data.task("Plan a long weekend in Lisbon", in: .someday)

        // Subtasks and comments.
        let sessions = data.subtask("List possible sessions", of: agenda)
        data.subtask("Ask each team lead for one topic", of: agenda)
        data.subtask("Share the draft with Priya", of: agenda)
        data.completeSubtask(sessions, of: agenda)
        data.comment("Priya prefers the workshop on the first day.", on: agenda)
        data.comment("Keep Friday afternoon free for the hike.", on: agenda)

        // History.
        let measured = data.task("Measure the kitchen walls", in: .next, project: kitchen)
        data.complete(measured)
        let poll = data.task("Send the offsite date poll", in: .next, project: offsite, tags: [computer])
        data.complete(poll)
        let tiles = data.task("Order the blue wall tiles", in: .someday, project: kitchen)
        data.cancel(tiles)
        let beds = data.task("Clear the flower beds", in: .next, project: garden, tags: [home])
        data.complete(beds)
        data.archive(garden)

        return StoreDocument(generation: 1, outbox: data.outbox)
    }
}

extension SampleData {
    /// Applies commands with readable, stable ids ("sample-task-7"), so
    /// previews look the same on every run.
    fileprivate struct Builder {
        var state = GTDState.empty
        var outbox: [PendingOperation] = []
        var clock: Date
        var counter = 0

        init(clock: Date) {
            self.clock = clock
        }

        mutating func project(_ name: String, color: String) -> ProjectID {
            let id: ProjectID = nextID("project")
            run(.createProject(.init(projectID: id, name: name, color: color)))
            return id
        }

        mutating func tag(_ name: String) -> TagID {
            let id: TagID = nextID("tag")
            run(.createTag(.init(tagID: id, name: name)))
            return id
        }

        @discardableResult
        mutating func task(
            _ title: String, in list: OpenList = .inbox, project: ProjectID? = nil, tags: [TagID] = [],
            due: CalendarDay? = nil, priority: TaskPriority = .none, waitingFor: String? = nil, notes: String? = nil
        ) -> TaskID {
            let id: TaskID = nextID("task")
            run(
                .createTask(
                    .init(
                        taskID: id, title: title, details: notes, list: list, waitingFor: waitingFor, dueDate: due,
                        priority: priority, projectID: project, tagIDs: tags
                    )
                )
            )
            return id
        }

        @discardableResult
        mutating func subtask(_ title: String, of task: TaskID) -> SubtaskID {
            let id: SubtaskID = nextID("subtask")
            run(.createSubtask(.init(taskID: task, subtaskID: id, title: title)))
            return id
        }

        mutating func completeSubtask(_ subtask: SubtaskID, of task: TaskID) {
            run(.transitionSubtask(.init(taskID: task, subtaskID: subtask, action: .complete)))
        }

        mutating func comment(_ body: String, on task: TaskID) {
            let id: CommentID = nextID("comment")
            run(.createComment(.init(taskID: task, commentID: id, body: body)))
        }

        mutating func complete(_ task: TaskID) {
            run(.transitionTask(.init(taskID: task, action: .complete)))
        }

        mutating func cancel(_ task: TaskID) {
            run(.transitionTask(.init(taskID: task, action: .cancel)))
        }

        mutating func archive(_ project: ProjectID) {
            run(.archiveProject(project))
        }

        private mutating func nextID<Kind>(_ kind: String) -> EntityID<Kind> {
            counter += 1
            return EntityID("sample-\(kind)-\(counter)")
        }

        private mutating func run(_ command: GTDCommand) {
            clock = Workspace.storedPrecision(clock.addingTimeInterval(7 * 60))
            do throws(GTDValidationError) {
                try GTDReducer.apply(command, at: clock, to: &state, mode: .interactive)
            } catch {
                assertionFailure("Sample data command was rejected: \(error.message)")
                return
            }
            let operation = PendingOperation(command: command, issuedAt: clock)
            outbox = OutboxCompactor.appending(operation, to: outbox)
        }
    }
}
