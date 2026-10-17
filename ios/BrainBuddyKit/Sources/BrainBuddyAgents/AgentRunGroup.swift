import BrainBuddyAPI
import Foundation

/// The five groups of All runs, in the order they show (030-FR-006). A pure function of the server's label.
public enum AgentRunGroup: Int, CaseIterable, Sendable {
    case needsYou, running, queued, toReview, lostContact

    public var title: String { AgentsCopy.groups[rawValue] }

    /// The 030-FR-006 table. A label this build does not know is an ended-looking row that shows verbatim,
    /// so it sits under To review rather than claiming the person's attention.
    public init(_ state: AgentPrimaryState) {
        switch state {
        case .needsYou, .deliveryUnconfirmed: self = .needsYou
        case .sent, .accepted, .running, .cancellationRequested: self = .running
        case .queued, .notSent: self = .queued
        case .stoppedReporting: self = .lostContact
        case .agentReportedComplete, .failed, .cancelled, .agentNoLongerReportsThisRun,
            .connectionDisconnected, .contentExpired, .unknown:
            self = .toReview
        }
    }
}

extension AgentPrimaryState {
    /// The server's words for this label, as the run shows them.
    public var label: String {
        switch self {
        case .notSent: "Not sent"
        case .queued: "Queued"
        case .sent: "Sent"
        case .deliveryUnconfirmed: "Delivery unconfirmed"
        case .accepted: "Accepted"
        case .running: "Running"
        case .needsYou: "Needs you"
        case .cancellationRequested: "Cancellation requested"
        case .agentReportedComplete: AgentsCopy.reportedComplete
        case .failed: "Failed"
        case .cancelled: "Cancelled"
        case .stoppedReporting: AgentsCopy.stoppedReporting
        case .agentNoLongerReportsThisRun: "Agent no longer reports this run"
        case .connectionDisconnected: "Connection disconnected"
        case .contentExpired: AgentsCopy.expired
        case .unknown(let raw): raw
        }
    }

    /// An ended run no longer changes, so it is read once and not polled (030-FR-024).
    public var isEnded: Bool {
        switch self {
        case .agentReportedComplete, .failed, .cancelled, .agentNoLongerReportsThisRun,
            .connectionDisconnected, .contentExpired:
            true
        default: false
        }
    }
}

/// One listed run with its step: what a row of All runs or Waiting for needs (030-FR-007, 030-FR-010).
public struct AgentRunItem: Equatable, Sendable, Identifiable {
    public var id: String { runID }
    public var stepTitle: String
    public var taskServerID: String
    public var runID: String
    public var connectionID: String?
    public var agentName: String
    public var state: AgentPrimaryState
    public var questionText: String?
    public var sentAt: Date?
    public var lastContactAt: Date?

    public init(
        stepTitle: String, taskServerID: String, runID: String, connectionID: String? = nil, agentName: String,
        state: AgentPrimaryState, questionText: String? = nil, sentAt: Date? = nil, lastContactAt: Date? = nil
    ) {
        (self.stepTitle, self.taskServerID, self.runID) = (stepTitle, taskServerID, runID)
        (self.connectionID, self.agentName, self.state) = (connectionID, agentName, state)
        (self.questionText, self.sentAt, self.lastContactAt) = (questionText, sentAt, lastContactAt)
    }

    public var group: AgentRunGroup { AgentRunGroup(state) }

    /// The canvas detail after "<agent> · " (030-FR-007). Any other label shows verbatim.
    public func detail(now: Date) -> String {
        switch state {
        case .needsYou:
            questionText?.split(whereSeparator: \.isNewline).first.map(String.init) ?? state.label
        case .running: Self.elapsed(since: sentAt, now: now) ?? state.label
        case .queued: AgentsCopy.queued
        case .stoppedReporting: lost(AgentsCopy.stoppedReporting, now: now)
        default: state.label
        }
    }

    /// The compact state of an Agents row in Waiting for (030-FR-010).
    public func compactState(now: Date, calendar: Calendar = .current) -> String {
        switch state {
        case .running: Self.elapsed(since: sentAt, now: now).map { "\(state.label) · \($0)" } ?? state.label
        case .agentReportedComplete:
            (lastContactAt ?? sentAt).map { "Reported · \(Self.day($0, now: now, calendar: calendar))" } ?? "Reported"
        case .stoppedReporting: lost(AgentsCopy.lostContact, now: now)
        default: state.label
        }
    }

    /// "<agent> · <detail>", the second line of a canvas row.
    public func subtitle(now: Date) -> String { "\(agentName) · \(detail(now: now))" }

    /// "<prefix> · <time since last contact>", the prefix alone when the time is unknown.
    private func lost(_ prefix: String, now: Date) -> String {
        Self.elapsed(since: lastContactAt ?? sentAt, now: now).map { "\(prefix) · \($0)" } ?? prefix
    }

    /// "4 min", "3 h", "2 days": whole units, rounded down, never under a minute.
    public static func elapsed(since start: Date?, now: Date) -> String? {
        guard let start else { return nil }
        let seconds = max(0, now.timeIntervalSince(start))
        if seconds < 3600 { return "\(max(1, Int(seconds / 60))) min" }
        if seconds < 86_400 { return "\(Int(seconds / 3600)) h" }
        let days = Int(seconds / 86_400)
        return days == 1 ? "1 day" : "\(days) days"
    }

    private static func day(_ date: Date, now: Date, calendar: Calendar) -> String {
        if calendar.isDate(date, inSameDayAs: now) { return "today" }
        if let yesterday = calendar.date(byAdding: .day, value: -1, to: now), calendar.isDate(date, inSameDayAs: yesterday) {
            return "yesterday"
        }
        return calendar.shortWeekdaySymbols[calendar.component(.weekday, from: date) - 1]
    }
}
