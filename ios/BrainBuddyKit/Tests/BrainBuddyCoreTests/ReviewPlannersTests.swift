import BrainBuddyCore
import Foundation
import Testing

/// The pure Core planners behind the app and widget (contracts/ios-commands.md
/// §6; tasks.md T053, T087, T133, T151) and the flow-vector sections they own.
@Suite("Review planners and copy (spec 020)")
struct ReviewPlannersTests {
    static let flow = ReviewVectors.flow

    // MARK: Markers and copy (FR-004, FR-038, US5-6)

    @Test("020-FR-004 020-FR-038 MarkerStyle never maps an age class to an error role; lists show only asks and moves tomorrow")
    func markerStyle() {
        for formulationClass in FormulationClass.allCases {
            let style = MarkerStyle.for(formulationClass)
            #expect(style.role != .destructive, "\(formulationClass) uses rose")
            #expect(style.text.map(ReviewCopy.bannedTerms(in:)) ?? [] == [])
        }
        let listed = FormulationClass.allCases.filter { MarkerStyle.for($0).showsInLists }
        #expect(Set(listed) == [.asks, .movesTomorrow, .parkDue])
        #expect(MarkerStyle.for(.ageing).text == "Ageing" && !MarkerStyle.for(.ageing).showsInLists)
        #expect(MarkerStyle.for(.parkDue).text == "Moves to Someday tomorrow", "until the park is applied")
    }

    @Test("020-FR-004 020-FR-038 every ReviewCopy entry is free of overdue and streak wording")
    func copyHasNoBannedTerms() {
        #expect(ReviewCopy.bannedTerms(in: "Three tasks are overdue") == ["overdue"], "the guard itself works")
        #expect(ReviewCopy.bannedTerms(in: "Your 5-week streak!") == ["streak"])
        #expect(ReviewCopy.bannedTerms(in: "It syncs later.").isEmpty, "whole words only")
        let catalog = ReviewCopy.catalog
        #expect(catalog.count > 80)
        for entry in catalog {
            #expect(ReviewCopy.bannedTerms(in: entry).isEmpty, "\(entry)")
            #expect(!entry.isEmpty)
        }
    }

    @Test("020-FR-037 020-FR-036 notification and widget strings come from ReviewCopy")
    func notificationAndWidgetCopy() {
        #expect(ReviewCopy.notificationTitle == "Weekly review")
        #expect(ReviewCopy.notificationBody == "Your review time. The quick one takes about 5 minutes.")
        #expect(ReviewCopy.widgetChip(3) == "3 ask ›")
        #expect(ReviewCopy.widgetChipVoiceOver(3) == "3 tasks ask for a decision. Open the review's decision step")
    }

    // MARK: Decision card (FR-007, FR-047, FR-048)

    @Test(
        "020-FR-007 a stall reason recommends one decision; no reason recommends none",
        arguments: ReviewVectors.section(flow, "stall_recommendation")
    )
    func stallRecommendation(_ vector: Vector) {
        let reason = vector["stall_reason"]?.string.flatMap(StallReason.init(rawValue:))
        #expect(StallReasonRecommendation.decision(for: reason)?.rawValue == vector["expect"]?.string)
    }

    @Test("020-FR-007 every decision stays enabled whatever the reason; clearing the reason clears the recommendation")
    func recommendationNeverLimits() {
        for reason in StallReason.allCases {
            let recommended = StallReasonRecommendation.decision(for: reason)
            #expect(recommended.map(StallReasonRecommendation.cardDecisions(extensionUsed: false).contains) == true)
            #expect(StallReasonRecommendation.cardDecisions(extensionUsed: false).count == 7)
        }
        #expect(StallReasonRecommendation.decision(for: nil) == nil)
        #expect(!StallReasonRecommendation.cardDecisions(extensionUsed: true).contains(.extend), "FR-009")
    }

    @Test("020-FR-006 the card's decisions come in the M-03 order, Done first and Keep 7 more days last")
    func cardDecisionOrder() {
        #expect(
            StallReasonRecommendation.cardDecisions(extensionUsed: false)
                == [.complete, .reformulate, .firstStep, .waiting, .someday, .cancel, .extend]
        )
        #expect(
            StallReasonRecommendation.cardDecisions(extensionUsed: true)
                == [.complete, .reformulate, .firstStep, .waiting, .someday, .cancel],
            "the order holds without Keep 7 more days"
        )
    }

    @Test("020-FR-006 the card's words: decision titles, subtitles, reasons and the days in Next")
    func cardCopy() {
        #expect(
            StallReasonRecommendation.cardDecisions(extensionUsed: false).map(ReviewCopy.cardTitle)
                == [
                    "Done", "Reformulate", "Find a first step", "Move to Waiting for…", "Release to Someday",
                    "Cancel task", "Keep 7 more days",
                ]
        )
        #expect(ReviewCopy.cardSubtitle(.complete) == nil)
        #expect(ReviewCopy.cardSubtitle(.extend) == "Once for this wording, with a reason")
        #expect(ReviewCopy.stallReasonOrder == [.unclear, .tooBig, .missingInfo, .waitingOnSomeone, .noLongerMatters, .noEnergy])
        #expect(Set(ReviewCopy.stallReasonOrder) == Set(StallReason.allCases), "every reason is offered")
        #expect(
            ReviewCopy.stallReasonOrder.map(ReviewCopy.stallReasonLabel)
                == [
                    "Unclear", "Too big", "Missing information", "Waiting on someone", "No longer matters",
                    "Unpleasant / no energy",
                ]
        )
        let start = Review.now
        #expect(ReviewCopy.daysInNext(since: start, now: start.addingTimeInterval(15 * Review.day + 3_600)) == "15 days in Next")
        #expect(ReviewCopy.daysInNext(since: start, now: start.addingTimeInterval(Review.day)) == "1 day in Next")
        #expect(ReviewCopy.daysInNext(since: start, now: start.addingTimeInterval(-60)) == "0 days in Next", "never negative")
    }

    @Test("020-FR-015 M-09 counts the returns left: Return all 4 to Next, then Return the other 3 to Next")
    func whileAwayReturnAllCopy() {
        #expect(ReviewCopy.returnAll(4) == "Return all 4 to Next")
        #expect(ReviewCopy.returnAll(3, othersReturned: true) == "Return the other 3 to Next")
        #expect(ReviewCopy.backInNext(1) == "1 task is back in Next.")
        #expect(ReviewCopy.backInNext(3) == "3 tasks are back in Next.")
    }

    @Test("020-FR-048 the Undo window is about 5 s, at least 10 s with VoiceOver or Switch Control")
    func undoWindow() {
        #expect(UndoWindowPolicy.duration(voiceOver: false, switchControl: false) == 5)
        #expect(UndoWindowPolicy.duration(voiceOver: true, switchControl: false) >= 10)
        #expect(UndoWindowPolicy.duration(voiceOver: false, switchControl: true) >= 10)
    }

    @Test("020-FR-047 the decision card is a large sheet outside a review and full screen inside")
    func cardPresentation() {
        #expect(ReviewPresentation.decisionCard(inReview: false) == .largeSheet)
        #expect(ReviewPresentation.decisionCard(inReview: true) == .fullScreen)
    }

    // MARK: While you were away (FR-015)

    @Test(
        "020-FR-015 at app open at most once a calendar day; always first in a review",
        arguments: ReviewVectors.section(flow, "while_away")
    )
    func whileAway(_ vector: Vector) throws {
        let context = try #require(vector["context"]?.string.flatMap(WhileAwayPresentation.Context.init(rawValue:)))
        let shown = WhileAwayPresentation.shouldShow(
            context: context, hasUnseen: vector["has_unseen"]?.bool ?? false, lastShownDay: ReviewVectors.day(vector["last_shown_day"]),
            today: try #require(ReviewVectors.day(vector["today"]))
        )
        #expect(shown == vector["expect"]?.bool)
    }

    @Test("020-FR-015 dismissed today → not again today, shown tomorrow")
    func whileAwayOncePerDay() {
        let today = CalendarDay(year: 2026, month: 10, day: 9)!
        #expect(WhileAwayPresentation.shouldShowAtAppOpen(lastShownDay: nil, today: today, hasUnseen: true))
        #expect(!WhileAwayPresentation.shouldShowAtAppOpen(lastShownDay: today, today: today, hasUnseen: true))
        #expect(WhileAwayPresentation.shouldShowAtAppOpen(lastShownDay: today, today: today.adding(days: 1), hasUnseen: true))
        #expect(WhileAwayPresentation.shouldShow(context: .reviewStart, hasUnseen: true, lastShownDay: today, today: today))
    }

    // MARK: App-open sheets (M-26, M-09; T092, T093)

    @Test("020-FR-051 the explainer comes before anything else, a capture deep link that is not on screen yet included")
    func startupExplainerFirst() {
        let coldCaptureLink = ReviewStartupPlanner.Context(
            reviewExposed: true, explainerNeeded: true, whileAwayDue: true, captureRequested: true, screenBusy: false
        )
        #expect(ReviewStartupPlanner.sheetToPresent(coldCaptureLink) == .explainer)
        #expect(
            !ReviewStartupPlanner.captureMayPresent(
                startupSheet: nil, captureOnScreen: false, reviewExposed: true, explainerNeeded: true
            ),
            "the capture waits for the explainer"
        )
        #expect(
            !ReviewStartupPlanner.captureMayPresent(
                startupSheet: .explainer, captureOnScreen: false, reviewExposed: true, explainerNeeded: true
            )
        )
        // Acknowledged: the explainer is gone and the waiting capture shows.
        #expect(
            ReviewStartupPlanner.captureMayPresent(
                startupSheet: nil, captureOnScreen: false, reviewExposed: true, explainerNeeded: false
            )
        )
        // Not exposed: nothing of the review shows, the capture is not held.
        #expect(
            ReviewStartupPlanner.captureMayPresent(
                startupSheet: nil, captureOnScreen: false, reviewExposed: false, explainerNeeded: true
            )
        )
        var hidden = coldCaptureLink
        hidden.reviewExposed = false
        #expect(ReviewStartupPlanner.sheetToPresent(hidden) == nil)
    }

    @Test("020-FR-015 While you were away follows the explainer and yields to a requested capture")
    func startupWhileAway() {
        var context = ReviewStartupPlanner.Context(
            reviewExposed: true, explainerNeeded: false, whileAwayDue: true, captureRequested: false, screenBusy: false
        )
        #expect(ReviewStartupPlanner.sheetToPresent(context) == .whileAway)
        context.captureRequested = true
        #expect(ReviewStartupPlanner.sheetToPresent(context) == nil, "the capture first, M-09 after it closes")
        context.captureRequested = false
        context.whileAwayDue = false
        #expect(ReviewStartupPlanner.sheetToPresent(context) == nil)
    }

    @Test("020-FR-051 020-FR-015 nothing is presented over another sheet; a capture already on screen is never taken away")
    func startupNeverOverAnotherSheet() {
        let busy = ReviewStartupPlanner.Context(
            reviewExposed: true, explainerNeeded: true, whileAwayDue: true, captureRequested: false, screenBusy: true
        )
        #expect(ReviewStartupPlanner.sheetToPresent(busy) == nil, "UIKit presents one sheet at a time")
        // The flag arrives while a capture is on screen: it stays.
        #expect(
            ReviewStartupPlanner.captureMayPresent(
                startupSheet: nil, captureOnScreen: true, reviewExposed: true, explainerNeeded: true
            )
        )
        #expect(
            !ReviewStartupPlanner.captureMayPresent(
                startupSheet: .whileAway, captureOnScreen: false, reviewExposed: true, explainerNeeded: false
            ),
            "a capture asked for meanwhile waits until M-09 closes"
        )
    }

    @Test("020-FR-042 020-FR-051 020-FR-015 an open startup sheet goes when the review stops being exposed")
    func startupSheetGoesWhenHidden() {
        for sheet in [ReviewStartupSheet.explainer, .whileAway] {
            #expect(ReviewStartupPlanner.sheetToKeep(sheet, reviewExposed: true) == sheet, "exposed: it stays")
            #expect(ReviewStartupPlanner.sheetToKeep(sheet, reviewExposed: false) == nil, "\(sheet) is taken away")
        }
        #expect(ReviewStartupPlanner.sheetToKeep(nil, reviewExposed: false) == nil)
        #expect(ReviewStartupPlanner.sheetToKeep(nil, reviewExposed: true) == nil)
        // Taken away, the waiting capture is no longer held back, and nothing re-presents.
        #expect(
            ReviewStartupPlanner.captureMayPresent(
                startupSheet: ReviewStartupPlanner.sheetToKeep(.explainer, reviewExposed: false), captureOnScreen: false,
                reviewExposed: false, explainerNeeded: true
            )
        )
        let hidden = ReviewStartupPlanner.Context(
            reviewExposed: false, explainerNeeded: true, whileAwayDue: true, captureRequested: false, screenBusy: false
        )
        #expect(ReviewStartupPlanner.sheetToPresent(hidden) == nil)
    }

    @Test("020-FR-039 the threshold note shows after a change until dismissed for it or until its floor date passes")
    func thresholdChangeNote() {
        let changedAt = Date(timeIntervalSince1970: 1_791_000_000)
        let floor = changedAt.addingTimeInterval(7 * 86_400)
        let settings = ReviewSettings(thresholdDays: 7, ownerParkFloorAt: floor, thresholdChangedAt: changedAt)
        #expect(ThresholdChangeNote.change(settings: settings, dismissedChange: nil, now: changedAt) == changedAt)
        #expect(ThresholdChangeNote.change(settings: settings, dismissedChange: 0, now: changedAt) == changedAt)
        #expect(
            ThresholdChangeNote.change(settings: settings, dismissedChange: changedAt.timeIntervalSince1970, now: changedAt)
                == nil,
            "dismissed for this change"
        )
        let earlier = changedAt.addingTimeInterval(-86_400).timeIntervalSince1970
        #expect(
            ThresholdChangeNote.change(settings: settings, dismissedChange: earlier, now: changedAt) == changedAt,
            "a dismissal of an earlier change does not hide a new one"
        )
        #expect(ThresholdChangeNote.change(settings: settings, dismissedChange: nil, now: floor) == nil, "the date passed")
        var unchanged = settings
        unchanged.thresholdChangedAt = nil
        #expect(ThresholdChangeNote.change(settings: unchanged, dismissedChange: nil, now: changedAt) == nil)
        var noFloor = settings
        noFloor.ownerParkFloorAt = nil
        #expect(ThresholdChangeNote.change(settings: noFloor, dismissedChange: nil, now: changedAt) == nil)
    }

    // MARK: Active time (SC-004)

    @Test(
        "020-SC-004 active seconds per step: idle gaps over 2 minutes and background count 0",
        arguments: ReviewVectors.section(flow, "active_time")
    )
    func activeTime(_ vector: Vector) throws {
        var accumulator = ActiveTimeAccumulator()
        for event in vector["events"]?.array ?? [] {
            let at = try #require(ReviewVectors.instant(event["at"]))
            let step = event["step"]?.string.flatMap(ReviewStep.init(rawValue:))
            let kind: ActiveTimeAccumulator.Event
            switch event["kind"]?.string {
            case "enter_step": kind = .enterStep(try #require(step))
            case "resume": kind = .resume(try #require(step))
            case "interaction": kind = .interaction
            case "background": kind = .background
            case "foreground": kind = .foreground
            case "leave": kind = .leave
            case let other:
                Issue.record("unknown active-time event \(other ?? "nil")")
                return
            }
            accumulator.record(kind, at: at)
        }
        let expected = (vector["expect"]?.object ?? [:]).reduce(into: [ReviewStep: Int]()) { result, entry in
            if let step = ReviewStep(rawValue: entry.key) { result[step] = entry.value.int }
        }
        #expect(accumulator.secondsByStep == expected)
    }

    // MARK: Layout (FR-033, design "Mobile viability")

    @Test("020-FR-033 one summary column and a scrolling step bar exactly at accessibility sizes")
    func layout() {
        #expect(ReviewLayout.summaryColumns(isAccessibilitySize: true) == 1)
        #expect(ReviewLayout.summaryColumns(isAccessibilitySize: false) == 2)
        #expect(ReviewLayout.stepBarScrolls(isAccessibilitySize: true))
        #expect(!ReviewLayout.stepBarScrolls(isAccessibilitySize: false))
    }

    // MARK: Schedule (FR-036)

    @Test(
        "020-FR-036 the weekly slot in the zone, skipped after a review in the 6 days before (gap and fold included)",
        arguments: ReviewVectors.section(flow, "next_review")
    )
    func nextReview(_ vector: Vector) throws {
        let raw = try #require(vector["settings"])
        let zone = try #require(raw["time_zone"]?.string.flatMap(TimeZone.init(identifier:)))
        let settings = ReviewSettings(reviewWeekday: raw["review_weekday"]?.int ?? 5, reviewTime: raw["review_time"]?.string ?? "")
        let fire = ReviewReminderPlanner.nextFireDate(
            settings: settings, lastCountedReview: ReviewVectors.instant(vector["last_counted_review_at"]),
            now: try #require(ReviewVectors.instant(vector["now"])), timeZone: zone
        )
        #expect(ReviewVectors.iso(fire) == vector["expect"])
    }

    @Test("020-FR-036 two zones: the planner fires at Friday 16:00 where the device is, ignoring the stored zone")
    func reminderFollowsTheDevice() throws {
        let stored = ReviewSettings(reviewWeekday: 5, reviewTime: "16:00", timeZone: "Europe/Berlin")
        let now = Review.instant("2026-10-07T12:00:00Z")
        let newYork = try #require(TimeZone(identifier: "America/New_York"))
        let berlin = try #require(TimeZone(identifier: "Europe/Berlin"))
        let inNewYork = ReviewReminderPlanner.nextFireDate(settings: stored, lastCountedReview: nil, now: now, timeZone: newYork)
        #expect(inNewYork == Review.instant("2026-10-09T20:00:00Z"), "Friday 16:00 New York time")
        let inBerlin = ReviewReminderPlanner.nextFireDate(settings: stored, lastCountedReview: nil, now: now, timeZone: berlin)
        #expect(inBerlin == Review.instant("2026-10-09T14:00:00Z"), "equals the server's next_review_at in the stored zone")
        var otherZone = stored
        otherZone.timeZone = "Asia/Tokyo"
        #expect(ReviewReminderPlanner.nextFireDate(settings: otherZone, lastCountedReview: nil, now: now, timeZone: newYork) == inNewYork)
    }

    @Test("020-FR-036 a counted review in the 6 days before skips the slot; a review done without any step does not")
    func reminderSkipsAfterACountedReview() throws {
        let settings = ReviewSettings(reviewWeekday: 5, reviewTime: "16:00")
        let utc = try #require(TimeZone(identifier: "UTC"))
        let now = Review.instant("2026-10-07T12:00:00Z")
        var sessions = [
            ReviewSession(
                id: Review.session(1), mode: .quick, entry: .list, origin: .web, status: .completedEmpty,
                startedAt: Review.instant("2026-10-06T10:00:00Z"), endedAt: Review.instant("2026-10-06T10:05:00Z")
            )
        ]
        let notCounted = ReviewReminderPlanner.nextFireDate(
            settings: settings, lastCountedReview: ReviewSession.lastCountedReviewAt(sessions), now: now, timeZone: utc
        )
        #expect(notCounted == Review.instant("2026-10-09T16:00:00Z"))
        sessions[0].status = .completed
        let counted = ReviewReminderPlanner.nextFireDate(
            settings: settings, lastCountedReview: ReviewSession.lastCountedReviewAt(sessions), now: now, timeZone: utc
        )
        #expect(counted == Review.instant("2026-10-16T16:00:00Z"))
    }

    @Test("020-FR-035 020-FR-046 DeviceZoneTracker: a change only when the device's own zone changed")
    func deviceZone() throws {
        let berlin = try #require(TimeZone(identifier: "Europe/Berlin"))
        #expect(DeviceZoneTracker.change(lastObserved: "Europe/Berlin", current: berlin) == nil)
        #expect(DeviceZoneTracker.change(lastObserved: "America/New_York", current: berlin)?.identifier == "Europe/Berlin")
        #expect(DeviceZoneTracker.change(lastObserved: nil, current: berlin) == nil, "the first observation is recorded, not sent")
    }

    // MARK: Entry (FR-037)

    @Test("020-FR-037 review routes: brainbuddy://review and brainbuddy://review/decisions")
    func routes() throws {
        #expect(ReviewRoute.parse(try #require(URL(string: "brainbuddy://review"))) == .review)
        #expect(ReviewRoute.parse(try #require(URL(string: "brainbuddy://review/decisions"))) == .decisions)
        #expect(ReviewRoute.parse(try #require(URL(string: "brainbuddy://review/other"))) == nil)
        #expect(ReviewRoute.parse(try #require(URL(string: "brainbuddy://tasks/next"))) == nil)
        #expect(ReviewRoute.parse(try #require(URL(string: "https://review/decisions"))) == nil)
    }

    @Test("020-FR-037 020-FR-027 the widget chip: explainer, onboarding, While you were away, restart before the decision step")
    func entryOrder() {
        let everything = ReviewEntryState(
            explainerNeeded: true, onboarded: false, hasUnseenParks: true, restartMode: true, openSession: nil
        )
        #expect(
            ReviewEntryPlanner.start(for: .widgetDecisions, state: everything)
                == [.explainer, .onboarding, .whileAway, .restart, .quickReview(start: .decisions, skipping: [.wins, .inbox])]
        )
        let open = ReviewSession(
            id: Review.session(1), mode: .full, entry: .list, origin: .web, startedAt: Review.now, currentStep: .waiting
        )
        let ready = ReviewEntryState(explainerNeeded: false, onboarded: true, hasUnseenParks: false, restartMode: false, openSession: open)
        #expect(ReviewEntryPlanner.start(for: .widgetDecisions, state: ready) == [.resume(Review.session(1), step: .decisions)])
        #expect(ReviewEntryPlanner.start(for: .list, state: ready) == [.resume(Review.session(1), step: .waiting)])
        var fresh = ready
        fresh.openSession = nil
        #expect(ReviewEntryPlanner.start(for: .notification, state: fresh) == [.modePicker])
    }

    // MARK: Navigator proposals

    @Test(
        "020-FR-019 proposals equal to any open title of the project are dropped, sent or not",
        arguments: ReviewVectors.section(flow, "duplicate_filter")
    )
    func duplicateFilter(_ vector: Vector) {
        let kept = NavigatorProposalFilter.dropDuplicates(
            vector["proposals"]?.array.compactMap(\.string) ?? [], currentTitle: vector["current_title"]?.string ?? "",
            projectOpenTitles: vector["project_open_titles"]?.array.compactMap(\.string) ?? []
        )
        #expect(kept == vector["expect"]?.array.compactMap(\.string))
    }

    @Test("020-FR-028 every flow-vector section runs in Swift")
    func everyFlowSectionRuns() {
        let sections = Set(Self.flow.object.filter { if case .array = $0.value { true } else { false } }.keys)
        #expect(Self.flow["schema"]?.string == "brainbuddy-review-flow-vectors/v1")
        #expect(
            sections == [
                "steps", "wins", "capacity", "waiting_queue", "someday_queue", "restart", "session_status", "idle_close",
                "qualifying_activity", "counted_review", "regularity", "next_review", "decision_queue",
                "stall_recommendation", "active_time", "while_away", "duplicate_filter",
            ]
        )
        #expect(sections.allSatisfy { !ReviewVectors.section(Self.flow, $0).isEmpty })
    }
}
