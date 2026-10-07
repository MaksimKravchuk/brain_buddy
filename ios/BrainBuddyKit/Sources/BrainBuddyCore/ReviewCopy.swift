import Foundation

/// Every review-surface string the app and the widget show (spec 020, design
/// M-01 – M-26), so a Linux test checks each against the banned terms of
/// FR-004, FR-038 and US5-6: no "overdue", no streak wording, no word for a
/// missed deadline. Views read their copy from here. English, sentence case,
/// calm second person.
public enum ReviewCopy {
    // MARK: Banned terms

    /// Whole words or phrases no review string may contain (case-insensitive).
    public static let bannedTerms = ["overdue", "streak", "streaks", "missed", "late", "behind", "failed", "lazy"]

    /// The banned terms `text` contains, as whole words.
    public static func bannedTerms(in text: String) -> [String] {
        let words = text.lowercased().split { !$0.isLetter }.map(String.init)
        let joined = " " + words.joined(separator: " ") + " "
        return bannedTerms.filter { joined.contains(" \($0) ") }
    }

    // MARK: Markers (M-01, M-02)

    public static let markerAsks = "Asks for a decision"
    public static let markerMovesTomorrow = "Moves to Someday tomorrow"
    public static let markerAgeing = "Ageing"
    public static let markerPaused = "Paused until the due date"

    // MARK: "This wording" (M-02)

    public static let thisWordingAsks =
        "The wording hasn't moved for a while. That's feedback on the wording, not on you. Changing notes, Tags, project or priority doesn't restart the clock."

    public static func thisWordingWillAsk(on day: String) -> String {
        "Asks for a decision from \(day) if the wording stays the same."
    }

    public static func thisWordingPaused(until day: String) -> String {
        "The clock starts on \(day). Until then this task won't ask for a decision or move to Someday."
    }

    public static func thisWordingMovesTomorrow(day: String, time: String) -> String {
        "If nothing is decided, it moves to Someday / maybe on \(day) at \(time). Nothing is lost, and you can bring it back in one tap."
    }

    public static func thisWordingKept(on kept: String, asksAgain: String, moves: String) -> String {
        "Kept on \(kept). Asks again on \(asksAgain); moves to Someday on \(moves) if still undecided."
    }

    public static func thisWordingParked(on day: String, at time: String, afterDays days: Int) -> String {
        "Moved here on \(day) at \(time), after \(days) days in Next without a decision. Project, Tags, notes and due date were kept."
    }

    public static func thisWordingParkedProjectArchived(project: String) -> String {
        "Its project \"\(project)\" is archived, so restore the project before moving this back to Next actions."
    }

    /// A park whose clock this device does not hold (pulled from the server):
    /// the facts without a guessed number of days.
    public static func thisWordingParked(on day: String, at time: String) -> String {
        "Moved here on \(day) at \(time) without a decision. Project, Tags, notes and due date were kept."
    }

    public static func ageInDays(_ days: Int) -> String { days == 1 ? "1 day" : "\(days) days" }

    /// "15 days in Next": whole days since the wording started, never negative.
    public static func daysInNext(since start: Date, now: Date) -> String {
        let days = max(0, Int((now.timeIntervalSince(start) / FormulationRule.day).rounded(.down)))
        return "\(ageInDays(days)) in Next"
    }

    public static let thisWordingHeader = "This wording"
    public static let markerParked = "Parked automatically"
    public static let cannotExtendAgain = "This wording can't be extended again."
    public static let decide = "Decide"

    // MARK: Decision card (M-03, M-04)

    public static let cardFraming = "This wording hasn't moved. That usually means the wording needs work, not you."
    public static let recommended = "Recommended"
    public static let extensionUsed = "You've already kept this wording 7 more days once."
    public static let thirdStall =
        "This is the third wording in a row that has stalled. Sometimes the task isn't the problem…"
    public static let stale = "This task changed on another device, so nothing was applied. Here's the current version."
    public static let decisionNotAllowed =
        "This decision isn't available for this task's current list. Nothing was changed."
    public static let reformulatePrompt = "What will you actually do?"
    public static let reformulateHint = "A new wording starts a fresh clock."
    public static let cosmeticEdit =
        "Only capitals or punctuation changed, so this is still the same wording and the clock keeps running."
    public static let saveAnyway = "Save anyway"
    public static let firstStepPrompt = "What's the very first thing you'd do?"
    public static let waitingPrompt = "Who or what are you waiting for?"
    public static let extendPrompt = "Why does this wording still fit?"
    public static let extendNeedsReason = "Add a reason to continue"

    public static let cardReasonsHeading = "What got in the way? · optional"
    public static let cardDecisionsHeading = "What now?"
    public static let decideAgain = "Decide again"
    public static let decideAgainHint = "Decide again if it still needs it."
    public static let noLongerAsks = "This task no longer asks for a decision. You can close the card."
    public static let staleWas = "Was"
    public static let staleNow = "Now"
    public static let noProject = "no project"

    /// "kept 7 more days on Mon 5 Oct", in the card's meta line.
    public static func keptMoreDays(on day: String) -> String { "kept 7 more days on \(day)" }

    /// The stall reasons in the order of design M-03.
    public static let stallReasonOrder: [StallReason] = [
        .unclear, .tooBig, .missingInfo, .waitingOnSomeone, .noLongerMatters, .noEnergy,
    ]

    public static func stallReasonLabel(_ reason: StallReason) -> String {
        switch reason {
        case .unclear: "Unclear"
        case .tooBig: "Too big"
        case .missingInfo: "Missing information"
        case .waitingOnSomeone: "Waiting on someone"
        case .noLongerMatters: "No longer matters"
        case .noEnergy: "Unpleasant / no energy"
        }
    }

    /// A decision as the card (M-03) lists it.
    public static func cardTitle(_ decision: DecisionType) -> String {
        switch decision {
        case .complete: "Done"
        case .reformulate: "Reformulate"
        case .firstStep: "Find a first step"
        case .waiting: "Move to Waiting for…"
        case .someday: "Release to Someday"
        case .cancel: "Cancel task"
        case .extend: "Keep 7 more days"
        case .keepWaiting, .followUp, .returnToNext, .keepSomeday: name(of: decision)
        }
    }

    public static func cardSubtitle(_ decision: DecisionType) -> String? {
        switch decision {
        case .reformulate: "Say what you'll actually do"
        case .firstStep: "Something you could start in 10 minutes"
        case .someday: "Not now. You can bring it back any time"
        case .cancel: "Stays findable under Cancelled"
        case .extend: "Once for this wording, with a reason"
        case .complete, .waiting, .keepWaiting, .followUp, .returnToNext, .keepSomeday: nil
        }
    }

    // MARK: Decision forms (M-04)

    public static func formTitle(_ decision: DecisionType) -> String {
        switch decision {
        case .firstStep: "First step"
        case .waiting: "Waiting for"
        case .reformulate, .extend, .complete, .someday, .cancel, .keepWaiting, .followUp, .returnToNext, .keepSomeday:
            name(of: decision)
        }
    }

    public static func formPlaceholder(_ decision: DecisionType) -> String {
        switch decision {
        case .reformulate: "New wording"
        case .firstStep: "Something you could start in 10 minutes"
        case .waiting: "A person, an event or a reply"
        case .extend: "One line is enough"
        case .complete, .someday, .cancel, .keepWaiting, .followUp, .returnToNext, .keepSomeday: ""
        }
    }

    public static let reformulateFooter = "Name a visible action. " + reformulateHint
    public static let waitingFooter = "It moves to Waiting for. The review checks in on it after 7 days."
    public static let saveNewWording = "Save new wording"
    public static let saveFirstStep = "Save first step"
    public static let moveToWaitingFor = "Move to Waiting for"
    public static let clearDraft = "Clear"

    public static func firstStepFooter(oldTitle: String) -> String {
        "The old wording stays in this task's notes as \"" + was(oldTitle) + "\"."
    }

    public static func extendFooter(asksAgain: String, moves: String) -> String {
        "Asks again on \(asksAgain). If still undecided, it moves to Someday on \(moves). "
            + "You can do this once for this wording."
    }

    /// "reason: too big", after the title in the first-step form.
    public static func reasonMeta(_ reason: StallReason) -> String { "reason: \(stallReasonLabel(reason).lowercased())" }

    public static func was(_ title: String) -> String { "Was: \(title)" }
    public static func keepUntil(_ day: String) -> String { "Keep until \(day)" }

    public static let unsavedTitle = "Discard your new wording? It hasn't been saved."
    public static let keepEditing = "Keep editing"
    public static let discard = "Discard"
    public static let draftRestored = "Your unsaved text is back."
    public static let offlineDecisions = "Offline. Decisions are saved on this iPhone and sync later."

    public static func name(of decision: DecisionType) -> String {
        switch decision {
        case .reformulate: "Reformulate"
        case .firstStep: "Find a first step"
        case .waiting: "Move to Waiting for"
        case .someday: "Release to Someday"
        case .complete: "Complete"
        case .cancel: "Cancel"
        case .extend: "Keep 7 more days"
        case .keepWaiting: "Keep waiting"
        case .followUp: "Create a follow-up"
        case .returnToNext: "Return to Next"
        case .keepSomeday: "Keep in Someday"
        }
    }

    /// The toast after a decision (with "Undo").
    public static func decisionToast(_ decision: DecisionType, title: String) -> String {
        switch decision {
        case .reformulate: "\"\(title)\" has a new wording"
        case .firstStep: "\"\(title)\" is the first step now"
        case .waiting: "\"\(title)\" moved to Waiting for"
        case .someday: "\"\(title)\" released to Someday"
        case .complete: "\"\(title)\" done"
        case .cancel: "\"\(title)\" cancelled"
        case .extend: "\"\(title)\" kept 7 more days"
        case .keepWaiting: "\"\(title)\" kept waiting · checks in again in 7 days"
        case .followUp: "Follow-up \"\(title)\" added to Next actions"
        case .returnToNext: "\"\(title)\" moved to Next actions"
        case .keepSomeday: "\"\(title)\" kept in Someday · looks again in 30 days"
        }
    }

    /// What VoiceOver announces with the toast.
    public static func decisionAnnouncement(_ decision: DecisionType) -> String {
        switch decision {
        case .someday: "Released to Someday. Undo available."
        default: "\(name(of: decision)) saved. Undo available."
        }
    }

    public static let undo = "Undo"

    public static func undoUnavailable(title: String, list: OpenList?) -> String {
        "Couldn't undo: \"\(title)\" changed on another device. It's in \(listName(list)) now."
    }

    // MARK: Sync issues (contracts/ios-commands.md §4, design M-03 error rows)

    public static func decisionNotSaved(_ decision: DecisionType, title: String, list: TaskState) -> String {
        "Your decision \"\(name(of: decision))\" on \"\(title)\" couldn't be saved to your account. It's in \(listName(list.openList, state: list)) now."
    }

    public static func decisionNotSavedParked(title: String) -> String {
        "Your decision on \"\(title)\" couldn't be saved: it moved to Someday / maybe automatically before your decision synced. You can bring it back from While you were away."
    }

    static func listName(_ list: OpenList?, state: TaskState? = nil) -> String {
        if let list { return list.title }
        switch state {
        case .completed?: return "Completed"
        case .cancelled?: return "Cancelled"
        default: return "another list"
        }
    }

    // MARK: While you were away (M-09)

    public static let whileAwayTitle = "While you were away"

    public static func whileAwayIntro(count: Int) -> String {
        count == 1
            ? "This task stayed undecided, so it moved to Someday / maybe to keep Next honest. Nothing was deleted."
            : "These \(count) tasks stayed undecided, so they moved to Someday / maybe to keep Next honest. Nothing was deleted."
    }

    public static let returnToNext = "Return to Next"
    public static let returnedOne = "Back in Next with a fresh start"

    /// "Return all 4 to Next"; once a row was returned, "Return the other 3 to Next".
    public static func returnAll(_ count: Int, othersReturned: Bool = false) -> String {
        othersReturned ? "Return the other \(count) to Next" : "Return all \(count) to Next"
    }

    /// The lead of a partial-failure summary.
    public static func backInNext(_ count: Int) -> String {
        count == 1 ? "1 task is back in Next." : "\(count) tasks are back in Next."
    }

    public static let restoreProjectFirst = "Restore the project first to bring it back."
    public static let offlineWhileAway = "Offline. Changes are saved on this iPhone and sync later."
    public static let rowReturned = "Returned"
    public static let rowProjectArchived = "Project archived"
    public static let rowChangedElsewhere = "Changed elsewhere"

    public static func returnUnavailable(project: String) -> String { "Return unavailable: project \(project) is archived" }
    public static func returnTask(title: String) -> String { "Return \(title) to Next" }
    /// "Old flat (archived)".
    public static func archivedPlace(_ project: String) -> String { "\(project) (archived)" }
    /// "Parked Thu 8 Oct · Home".
    public static func parkedRow(day: String, place: String) -> String { "Parked \(day) · \(place)" }
    public static func allReturned(_ count: Int) -> String { "All \(count) are back in Next with a fresh start." }
    public static let continueLabel = "Continue"
    public static let moreParksFollow = "More will follow after you continue."

    public static func extensionRestarted(title: String) -> String {
        "\"\(title)\" stays in Next. Its clock restarted when you signed in, so it has at least the 7 days you asked for."
    }

    public static func returnBlockedArchived(title: String, project: String) -> String {
        "\"\(title)\" stayed in Someday because its project \"\(project)\" is archived."
    }

    public static func returnChangedElsewhere(title: String) -> String {
        "\"\(title)\" changed on another device, so it was left as it is there."
    }

    // MARK: Explainer (M-26)

    public static let explainerTitle = "How Next stays fresh"

    public static func explainerRule(thresholdDays: Int) -> String {
        "If a next action keeps the same wording for \(thresholdDays) days, it asks for a decision."
    }

    public static let explainerPark =
        "If it's still undecided 7 days later, it moves to Someday / maybe. Nothing is deleted, and you can bring it back in one tap. It's the only thing the app moves on its own."

    public static func explainerGrace(until day: String) -> String { "Tasks already in Next won't move before \(day)." }
    public static let gotIt = "Got it"
    public static let changeDays = "Change the number of days"

    // MARK: Restart (M-10)

    public static func restartWelcome(daysSinceLastReview days: Int) -> String {
        "Your last review was \(days) days ago. Gaps happen. Let's make Next fit the week ahead."
    }

    public static let restartFirstReview = "Your first review"
    public static let restartFitWeek = "Let's make Next fit the week ahead."

    public static func restartOlderThanFourWeeks(_ count: Int) -> String {
        "\(count) next actions are older than 4 weeks"
    }

    public static func restartReleased(_ count: Int, nextNow: Int) -> String {
        "\(count) tasks released to Someday / maybe. Next now holds \(nextNow) tasks."
    }

    public static func restartUndone(_ count: Int) -> String { "Undone. All \(count) are back in Next as they were." }
    public static let restartNothingOld = "Nothing in Next is older than 4 weeks, so let's go straight in."

    // MARK: Entry, steps and summary (M-11, M-13, M-22)

    public static let weeklyReview = "Weekly review"
    public static let setUpInAMinute = "Set up in a minute"

    public static func lastReview(daysAgo days: Int?) -> String {
        guard let days else { return "Last review: Not yet" }
        switch days {
        case 0: return "Last review: today"
        case 1: return "Last review: yesterday"
        default: return "Last review: \(days) days ago"
        }
    }

    public static let modePickerQuestion = "How much time do you have?"

    public static func wins(_ count: Int) -> String {
        count == 1 ? "This week you finished 1 thing" : "This week you finished \(count) things"
    }

    public static let quietWeek = "A quiet week… Taking a few minutes now is how next week gets easier."
    public static let reviewEndedElsewhere =
        "This review was finished or replaced on another device. Decisions you made here are kept."
    public static let reviewClosedIdle = "This review was closed after a week without activity. Its decisions are kept."

    public static func reviewMovedOn(toStep step: Int) -> String {
        "You continued this review on another device, so it's at step \(step) now."
    }

    public static let reviewDone = "Review done"

    public static func nextReview(day: String, time: String) -> String { "Next review: \(day), \(time)" }

    public static let clearStartQuestion = "Clear how to start the week?"
    public static let clearStartThanks = "Thanks. Noted for this review."
    public static let nothingNeededChanging = "Nothing needed changing this time."

    public static func counterLabel(_ counter: SessionCounter) -> String {
        switch counter {
        case .done: "Done"
        case .reformulated: "Reformulated"
        case .firstStep: "First step"
        case .waiting: "Waiting for"
        case .someday: "Someday / maybe"
        case .cancelled: "Cancelled"
        case .extended: "Kept 7 more days"
        case .inboxProcessed: "Inbox processed"
        case .kept: "Kept as is"
        case .movedToNext: "Moved to Next"
        }
    }

    // MARK: Notification and widget (M-24, M-25)

    public static let notificationTitle = "Weekly review"
    public static let notificationBody = "Your review time. The quick one takes about 5 minutes."

    public static func widgetChip(_ count: Int) -> String { "\(count) ask ›" }

    public static func widgetChipVoiceOver(_ count: Int) -> String {
        count == 1
            ? "1 task asks for a decision. Open the review's decision step"
            : "\(count) tasks ask for a decision. Open the review's decision step"
    }

    // MARK: Dates as the review shows them

    private static let weekdays = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    private static let months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

    /// "Fri 16 Oct", in `zone`.
    public static func day(_ date: Date, in zone: TimeZone) -> String {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = zone
        let day = CalendarDay(date: date, calendar: calendar)
        let isoWeekday = ((day.dayNumber % 7 + 7) % 7 + 3) % 7
        return "\(weekdays[isoWeekday]) \(day.day) \(months[day.month - 1])"
    }

    /// "09:14", in `zone`.
    public static func time(_ date: Date, in zone: TimeZone) -> String {
        let local = Int(date.timeIntervalSince1970.rounded(.down)) + zone.secondsFromGMT(for: date)
        let minutes = ((local % 86_400) + 86_400) % 86_400 / 60
        let hour = String(minutes / 60)
        let minute = String(minutes % 60)
        return (hour.count == 1 ? "0" + hour : hour) + ":" + (minute.count == 1 ? "0" + minute : minute)
    }

    // MARK: Catalog

    /// Every entry, with sample values filled in (for the banned-term test).
    public static var catalog: [String] {
        let title = "Renovate the bathroom"
        var entries = [
            markerAsks, markerMovesTomorrow, markerAgeing, markerPaused, thisWordingAsks,
            thisWordingWillAsk(on: "Wed 14 Oct"), thisWordingPaused(until: "Fri 16 Oct"),
            thisWordingMovesTomorrow(day: "Sat 10 Oct", time: "09:14"),
            thisWordingKept(on: "Mon 5 Oct", asksAgain: "Mon 12 Oct", moves: "Mon 19 Oct"),
            thisWordingParked(on: "Thu 8 Oct", at: "09:14", afterDays: 21), thisWordingParkedProjectArchived(project: "Old flat"),
            ageInDays(1), ageInDays(9), cardFraming, recommended, extensionUsed, thirdStall, stale, decisionNotAllowed,
            reformulatePrompt, reformulateHint, cosmeticEdit, saveAnyway, firstStepPrompt, waitingPrompt, extendPrompt,
            extendNeedsReason, was(title), keepUntil("Fri 16 Oct"), unsavedTitle, keepEditing, discard, draftRestored,
            offlineDecisions, undo, undoUnavailable(title: title, list: .someday),
            decisionNotSavedParked(title: title), whileAwayTitle, whileAwayIntro(count: 1), whileAwayIntro(count: 4),
            returnToNext, returnedOne, returnAll(4), allReturned(4), continueLabel, moreParksFollow,
            extensionRestarted(title: "Call the landlord"), returnBlockedArchived(title: "Return the old router", project: "Old flat"),
            returnChangedElsewhere(title: "Update the CV"), explainerTitle, explainerRule(thresholdDays: 14), explainerPark,
            explainerGrace(until: "Fri 23 Oct"), gotIt, changeDays, restartWelcome(daysSinceLastReview: 26),
            restartFirstReview, restartFitWeek, restartOlderThanFourWeeks(17), restartReleased(17, nextNow: 12),
            restartUndone(17), restartNothingOld, weeklyReview, setUpInAMinute, lastReview(daysAgo: nil),
            lastReview(daysAgo: 0), lastReview(daysAgo: 1), lastReview(daysAgo: 9), modePickerQuestion, wins(1), wins(12),
            quietWeek, reviewEndedElsewhere, reviewClosedIdle, reviewMovedOn(toStep: 6), reviewDone,
            nextReview(day: "Fri 16 Oct", time: "16:00"), clearStartQuestion, clearStartThanks, nothingNeededChanging,
            notificationTitle, notificationBody, widgetChip(3), widgetChipVoiceOver(1), widgetChipVoiceOver(3),
        ]
        entries += [
            thisWordingParked(on: "Thu 8 Oct", at: "09:14"), daysInNext(since: .distantPast, now: .distantPast),
            thisWordingHeader, markerParked, cannotExtendAgain, decide, cardReasonsHeading, cardDecisionsHeading,
            decideAgain, decideAgainHint, noLongerAsks, staleWas, staleNow, noProject, keptMoreDays(on: "Mon 5 Oct"),
            reformulateFooter, waitingFooter, saveNewWording, saveFirstStep, moveToWaitingFor, clearDraft,
            firstStepFooter(oldTitle: title), extendFooter(asksAgain: "Fri 16 Oct", moves: "Fri 23 Oct"),
            returnAll(3, othersReturned: true), backInNext(1), backInNext(3), restoreProjectFirst, offlineWhileAway,
            rowReturned, rowProjectArchived, rowChangedElsewhere, returnUnavailable(project: "Old flat"),
            returnTask(title: title), archivedPlace("Old flat"), parkedRow(day: "Thu 8 Oct", place: "Home"),
        ]
        entries += stallReasonOrder.map(stallReasonLabel) + stallReasonOrder.map(reasonMeta)
        for decision in DecisionType.allCases {
            entries += [
                name(of: decision), decisionToast(decision, title: title), decisionAnnouncement(decision),
                decisionNotSaved(decision, title: title, list: .next), cardTitle(decision), formTitle(decision),
            ]
            entries += [cardSubtitle(decision)].compactMap { $0 }
            if !formPlaceholder(decision).isEmpty { entries.append(formPlaceholder(decision)) }
        }
        entries += SessionCounter.allCases.map(counterLabel)
        entries += FormulationClass.allCases.compactMap { MarkerStyle.for($0).text }
        return entries
    }
}
