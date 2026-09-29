import Foundation
import Testing
@testable import BrainBuddyCore

private typealias F = SmartAddFixtures

private func existing(_ name: String) -> ClassificationPreview { ClassificationPreview(name: name, isNew: false) }
private func new(_ name: String) -> ClassificationPreview { ClassificationPreview(name: name, isNew: true) }

private func preview(
    _ text: String, in state: GTDState = F.webState, list: OpenList = .inbox, waitingFor: String = "",
    details: String = "", contextProjectID: ProjectID? = nil, contextTagID: TagID? = nil
) -> CapturePreview {
    CapturePlanner.preview(
        CaptureDraft(
            text: text, list: list, waitingFor: waitingFor, details: details, contextProjectID: contextProjectID,
            contextTagID: contextTagID
        ),
        in: state
    )
}

/// Plans with predictable ids: `task-1`, `project-new-1…`, `tag-new-1…`.
private func planCapture(
    _ draft: CaptureDraft, in state: GTDState = F.webState
) throws(GTDValidationError) -> CapturePlan {
    var projects = 0
    var tags = 0
    return try CapturePlanner.plan(
        draft, in: state, makeTaskID: { "task-1" },
        makeProjectID: {
            projects += 1
            return ProjectID("project-new-\(projects)")
        },
        makeTagID: {
            tags += 1
            return TagID("tag-new-\(tags)")
        }
    )
}

private func createdTask(_ plan: CapturePlan) -> GTDCommand.CreateTask? {
    guard case .createTask(let task) = plan.commands.last else { return nil }
    return task
}

// MARK: - Resolution

@Suite("Capture planner — resolving projects and tags")
struct CapturePlannerResolutionTests {
    @Test func resolvesCyrillicNamesCaseInsensitively() {
        let state = F.state(projects: [F.project("p-home", "Дом")], tags: [F.tag("t-urgent", "Срочно")])

        let result = preview("Купить молоко @дом #СРОЧНО", in: state)

        #expect(result.title == "Купить молоко")
        #expect(result.project == existing("Дом"))
        #expect(result.tags == [existing("Срочно")])
        #expect(result.problem == nil)
    }

    @Test func createsUnknownCyrillicNamesWithTheirTypedSpelling() {
        let result = preview("Купить молоко @Дом #срочно", in: .empty)

        #expect(result.project == new("Дом"))
        #expect(result.tags == [new("срочно")])
        #expect(result.isValid)
    }

    @Test func matchesThroughNFKC() {
        // Full-width letters and a stored ligature both fold to plain ASCII.
        let state = F.state(projects: [F.project("p-fin", "ﬁnance")], tags: [F.tag("t-work", "work")])

        let result = preview("Pay @FINANCE #ｗｏｒｋ", in: state)

        #expect(result.project == existing("ﬁnance"))
        #expect(result.tags == [existing("work")])
    }

    @Test func aNewNameIsDisplayNormalized() {
        let result = preview("Plan @\"  Ремонт \t кухни \" #\"Deep\u{3000}Work\"", in: .empty)

        #expect(result.project == new("Ремонт кухни"))
        #expect(result.tags == [new("Deep Work")])
    }

    @Test func onlyTheLastProjectTokenIsResolved() {
        let result = preview("Draft @old @Admin @brand-new")

        #expect(result.project == new("brand-new"))
        #expect(result.tokens.count == 3)
    }

    @Test func tagsAreDeduplicatedByRecordAndByNormalizedNewName() {
        let result = preview("Plan #work #new #WORK #\"NEW\" #\"#work\" #calls")

        #expect(result.tags == [existing("work"), new("new"), existing("calls")])
    }

    @Test func aLegacySigilIsDroppedFromANewName() {
        #expect(preview("Plan #\"#fresh\" @\"@Garden\"", in: .empty).tags == [new("fresh")])
        #expect(preview("Plan @\"@Garden\"", in: .empty).project == new("Garden"))
    }

    @Test func storedNamesWithALegacySigilStillAnswerTheirName() {
        let state = F.state(projects: [F.project("p-home", "@Home")], tags: [F.tag("t-hash", "#errands")])

        let result = preview("Plan @home #errands", in: state)

        #expect(result.project == existing("@Home"))
        #expect(result.tags == [existing("#errands")])
    }

    @Test func anExactNameBeatsALegacySigilMatch() {
        // "#work" (legacy spelling, created first) and "work" are both active;
        // `#work` resolves to the exact name the reducer would call a duplicate.
        let state = F.state(
            tags: [F.tag("t-legacy", "#work", createdAfter: 0), F.tag("t-exact", "work", createdAfter: 60)]
        )

        let plan = try? planCapture(CaptureDraft(text: "Plan #work"), in: state)

        #expect(plan.flatMap(createdTask)?.tagIDs == ["t-exact"])
    }

    @Test func legacyOnlyTiesGoToTheOldestRecord() {
        let state = F.state(
            tags: [F.tag("t-newer", "#@focus", createdAfter: 60), F.tag("t-older", "#focus", createdAfter: 0)]
        )

        let plan = try? planCapture(CaptureDraft(text: "Plan #focus"), in: state)

        #expect(plan.flatMap(createdTask)?.tagIDs == ["t-older"])
    }

    @Test func sharpSFoldsToSSLikeTheServer() {
        // See SmartAddWebParityTests.foldsCaseLikeTheServerSoSharpSMatchesSS.
        let state = F.state(tags: [F.tag("t-strasse", "Strasse"), F.tag("t-ss", "ss")])

        #expect(preview("Plan #ß #STRAßE", in: state).tags == [existing("ss"), existing("Strasse")])
    }

    @Test func aNameThatIsEmptyAfterItsLegacySigilIsAProblem() {
        #expect(preview("Plan #\"#\"").problem == .emptyName)
        #expect(preview("Plan #\"#@\"").problem == .emptyName)
        #expect(preview("Plan @\"@\"").problem == .emptyName)
    }
}

// MARK: - Archived projects and deleted tags

@Suite("Capture planner — inactive records")
struct CapturePlannerInactiveRecordTests {
    private let state = F.state(
        projects: [F.project("p-old", "Переезд", state: .archived), F.project("p-live", "Launch")],
        tags: [F.tag("t-gone", "someday", state: .deleted)]
    )

    @Test func anArchivedProjectNameBlocksCapture() {
        let result = preview("Pack boxes @переезд", in: state)

        #expect(result.project == existing("Переезд"))
        #expect(result.problem == .projectNotActive)
        #expect(throws: GTDValidationError.projectNotActive) {
            try planCapture(CaptureDraft(text: "Pack boxes @переезд"), in: state)
        }
    }

    @Test func anActiveProjectWinsOverAnArchivedOneWithTheSameName() {
        let state = F.state(
            projects: [
                F.project("p-archived", "Launch", state: .archived, createdAfter: 0),
                F.project("p-active", "launch", createdAfter: 60),
            ]
        )

        let result = preview("Ship @LAUNCH", in: state)

        #expect(result.project == existing("launch"))
        #expect(result.problem == nil)
    }

    @Test func aSupersededArchivedNameDoesNotBlock() {
        let result = preview("Pack @Переезд @Launch", in: state)

        #expect(result.project == existing("Launch"))
        #expect(result.problem == nil)
    }

    @Test func aDeletedTagNameCreatesANewTag() throws {
        #expect(preview("Read #Someday", in: state).tags == [new("Someday")])

        let plan = try planCapture(CaptureDraft(text: "Read #Someday"), in: state)
        #expect(plan.commands.first == .createTag(.init(tagID: "tag-new-1", name: "Someday")))
    }
}

// MARK: - Context

@Suite("Capture planner — project and tag screens")
struct CapturePlannerContextTests {
    @Test func theContextProjectAppliesWithoutAProjectToken() {
        let result = preview("Plan #work", contextProjectID: "project-launch")

        #expect(result.project == existing("Launch v2"))
    }

    @Test func aProjectTokenOverridesTheContextProject() {
        let result = preview("Plan @Admin", contextProjectID: "project-launch")

        #expect(result.project == existing("Admin"))
    }

    @Test func anArchivedContextProjectBlocksUnlessATokenOverridesIt() {
        let state = F.state(projects: [F.project("p-old", "Old", state: .archived), F.project("p-new", "New")])

        #expect(preview("Plan", in: state, contextProjectID: "p-old").problem == .projectNotActive)
        #expect(preview("Plan", in: state, contextProjectID: "p-old").project == existing("Old"))
        #expect(preview("Plan @New", in: state, contextProjectID: "p-old").problem == nil)
    }

    @Test func aMissingContextProjectBlocks() {
        let result = preview("Plan", contextProjectID: "project-gone")

        #expect(result.project == nil)
        #expect(result.problem == .projectNotFound)
    }

    @Test func theContextTagComesFirstAndIsNotRepeated() {
        let result = preview("Plan #calls #work #new", contextTagID: "tag-work")

        #expect(result.tags == [existing("work"), existing("calls"), new("new")])
    }

    @Test func anInactiveOrMissingContextTagIsSkipped() {
        let state = F.state(tags: [F.tag("t-gone", "gone", state: .deleted)])

        #expect(preview("Plan #new", in: state, contextTagID: "t-gone").tags == [new("new")])
        #expect(preview("Plan", in: state, contextTagID: "t-missing").tags == [])
        #expect(preview("Plan", in: state, contextTagID: "t-gone").problem == nil)
    }
}

// MARK: - Validation

@Suite("Capture planner — validation")
struct CapturePlannerValidationTests {
    @Test func anEmptyTitleIsAProblem() {
        #expect(preview("").problem == .emptyTitle)
        #expect(preview("  #work  ").problem == .emptyTitle)
        #expect(throws: GTDValidationError.emptyTitle) { try planCapture(CaptureDraft(text: "@Admin")) }
    }

    @Test func titleLengthIsCountedInUnicodeScalarsLikePythonLen() {
        // 500 emoji: 500 scalars (the server's len), 1 000 UTF-16 units (the web's length).
        #expect(preview(String(repeating: "😀", count: 500)).problem == nil)
        #expect(preview(String(repeating: "😀", count: 501)).problem == .titleTooLong)
        // 251 "é" written as e + U+0301: 251 characters but 502 scalars.
        #expect(preview(String(repeating: "e\u{301}", count: 250)).problem == nil)
        #expect(preview(String(repeating: "e\u{301}", count: 251)).problem == .titleTooLong)
    }

    @Test func aNewNameOverTheLimitIsAProblemButAnExistingOneIsNot() {
        let long = String(repeating: "я", count: 501)
        let state = F.state(projects: [F.project("p-long", long)])

        #expect(preview("Plan @\(long)", in: .empty).problem == .nameTooLong)
        #expect(preview("Plan #\(long)", in: .empty).problem == .nameTooLong)
        #expect(preview("Plan #\(String(repeating: "я", count: 500))", in: .empty).problem == nil)
        #expect(preview("Plan @\(long)", in: state).problem == nil)
    }

    @Test func waitingNeedsWhoOrWhat() {
        #expect(preview("Invoice", list: .waiting).problem == .waitingForRequired)
        #expect(preview("Invoice", list: .waiting, waitingFor: " \n\u{3000}").problem == .waitingForRequired)
        #expect(preview("Invoice", list: .waiting, waitingFor: "  Анна  ").problem == nil)
    }

    @Test func theWaitingNoteIsMeasuredAfterTrimming() {
        let note = String(repeating: "w", count: 500)

        #expect(preview("Invoice", list: .waiting, waitingFor: "  \(note)  ").problem == nil)
        #expect(preview("Invoice", list: .waiting, waitingFor: note + "w").problem == .waitingForTooLong)
    }

    @Test func aWaitingNoteOutsideWaitingIsIgnored() {
        #expect(preview("Invoice", list: .next, waitingFor: String(repeating: "w", count: 900)).problem == nil)
    }

    @Test func notesAreLimited() {
        #expect(preview("Plan", details: String(repeating: "n", count: 20_000)).problem == nil)
        #expect(preview("Plan", details: String(repeating: "n", count: 20_001)).problem == .detailsTooLong)
    }

    @Test func problemsAreReportedInReadingOrder() {
        let long = String(repeating: "x", count: 501)
        let archived = F.state(projects: [F.project("p-a", "Archive", state: .archived)])

        #expect(preview("@\(long)", list: .waiting, details: long + long).problem == .emptyTitle)
        #expect(
            preview("Plan @Archive #\(long)", in: archived, list: .waiting).problem == .projectNotActive)
        #expect(preview("Plan #\(long)", list: .waiting).problem == .nameTooLong)
        #expect(
            preview("Plan", list: .waiting, details: String(repeating: "n", count: 20_001)).problem
                == .waitingForRequired)
    }

    @Test func planThrowsWhatPreviewReports() {
        let drafts = [
            CaptureDraft(text: ""),
            CaptureDraft(text: "Plan", list: .waiting),
            CaptureDraft(text: "Plan", details: String(repeating: "n", count: 20_001)),
            CaptureDraft(text: "Plan #\(String(repeating: "x", count: 501))"),
            CaptureDraft(text: "Plan", contextProjectID: "project-gone"),
        ]
        for draft in drafts {
            let problem = CapturePlanner.preview(draft, in: F.webState).problem
            #expect(problem != nil)
            #expect(throws: problem!) { try planCapture(draft) }
        }
    }
}

// MARK: - Plan

@Suite("Capture planner — commands")
struct CapturePlannerCommandTests {
    @Test func createsTheProjectThenEachNewTagThenTheTask() throws {
        let due = try #require(CalendarDay(year: 2026, month: 10, day: 1))
        let draft = CaptureDraft(
            text: "Купить молоко @Дом #срочно #work #магазин #СРОЧНО", list: .next, details: "  2 л  ",
            dueDate: due, priority: .high
        )

        let plan = try planCapture(draft)

        #expect(plan.taskID == "task-1")
        #expect(
            plan.commands == [
                .createProject(.init(projectID: "project-new-1", name: "Дом")),
                .createTag(.init(tagID: "tag-new-1", name: "срочно")),
                .createTag(.init(tagID: "tag-new-2", name: "магазин")),
                .createTask(
                    .init(
                        taskID: "task-1", title: "Купить молоко", details: "  2 л  ", list: .next, waitingFor: nil,
                        dueDate: due, priority: .high,
                        projectID: "project-new-1", tagIDs: ["tag-new-1", "tag-work", "tag-new-2"]
                    )),
            ])
    }

    @Test func existingRecordsNeedOnlyTheTask() throws {
        var mintedProjects = 0
        var mintedTags = 0

        let plan = try CapturePlanner.plan(
            CaptureDraft(text: "Call @\"vendor launch\" #calls"), in: F.webState, makeTaskID: { "task-9" },
            makeProjectID: {
                mintedProjects += 1
                return "unused"
            },
            makeTagID: {
                mintedTags += 1
                return "unused"
            }
        )

        #expect(mintedProjects == 0)
        #expect(mintedTags == 0)
        #expect(
            plan.commands == [
                .createTask(
                    .init(
                        taskID: "task-9", title: "Call", list: .inbox, projectID: "project-vendor",
                        tagIDs: ["tag-calls"]))
            ])
    }

    @Test func aSupersededProjectIsNeverCreated() throws {
        let plan = try planCapture(CaptureDraft(text: "Draft @old @new"))

        #expect(plan.commands.first == .createProject(.init(projectID: "project-new-1", name: "new")))
        #expect(plan.commands.count == 2)
    }

    @Test func contextIdsAreUsedAndTheContextTagComesFirst() throws {
        let plan = try planCapture(
            CaptureDraft(text: "Plan #calls", contextProjectID: "project-admin", contextTagID: "tag-deep")
        )

        #expect(createdTask(plan)?.projectID == "project-admin")
        #expect(createdTask(plan)?.tagIDs == ["tag-deep", "tag-calls"])
    }

    @Test func waitingCarriesTheTrimmedNote() throws {
        let plan = try planCapture(CaptureDraft(text: "Invoice", list: .waiting, waitingFor: "\t Анна из бухгалтерии \n"))

        #expect(createdTask(plan)?.list == .waiting)
        #expect(createdTask(plan)?.waitingFor == "Анна из бухгалтерии")
    }

    @Test func otherListsDropTheWaitingNote() throws {
        let plan = try planCapture(CaptureDraft(text: "Invoice", list: .someday, waitingFor: "Анна"))

        #expect(createdTask(plan)?.list == .someday)
        #expect(createdTask(plan)?.waitingFor == nil)
    }

    @Test func blankNotesAreNil() throws {
        #expect(createdTask(try planCapture(CaptureDraft(text: "Plan", details: " \n\t ")))?.details == nil)
        #expect(createdTask(try planCapture(CaptureDraft(text: "Plan", details: "")))?.details == nil)
    }

    @Test func theTitleHasTokensAndEscapesRemoved() throws {
        let plan = try planCapture(CaptureDraft(text: "Ask about \\#42 (#work) today, @Admin!"))

        #expect(createdTask(plan)?.title == "Ask about #42 today,!")
    }

    @Test func thePreviewDescribesThePlan() throws {
        let drafts = [
            CaptureDraft(text: "Plan @Дом #срочно #work"),
            CaptureDraft(text: "Plan @Admin #new", contextTagID: "tag-calls"),
            CaptureDraft(text: "Plan", contextProjectID: "project-launch", contextTagID: "tag-work"),
        ]
        for draft in drafts {
            let described = CapturePlanner.preview(draft, in: F.webState)
            let planned = try planCapture(draft)
            let task = try #require(createdTask(planned))
            let newProjects = planned.commands.filter { if case .createProject = $0 { true } else { false } }
            let newTags = planned.commands.filter { if case .createTag = $0 { true } else { false } }

            #expect(described.title == task.title)
            #expect((described.project != nil) == (task.projectID != nil))
            #expect((described.project?.isNew ?? false) == !newProjects.isEmpty)
            #expect(described.tags.count == task.tagIDs.count)
            #expect(described.tags.filter(\.isNew).count == newTags.count)
        }
    }
}
