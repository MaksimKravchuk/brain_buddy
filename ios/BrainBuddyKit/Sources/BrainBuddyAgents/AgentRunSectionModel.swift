import BrainBuddyAPI
import Foundation
import Observation

public protocol AgentRunSectionRemote: AgentRunActionsRemote {
    func agentRuns(taskID: String) async throws(APIError) -> [AgentRunDTO]
}

extension BrainBuddyAPIClient: AgentRunSectionRemote {}

/// What one run shows in the inspector (G-05): its label and only the blocks and controls its state and
/// the server's `controls` allow (030-FR-020 – 030-FR-023). Agent text is carried as plain strings and
/// content past its expiry is replaced by the expired label alone (030-FR-027).
public struct AgentRunBlock: Equatable, Sendable {
    public enum Tone: Sendable { case plain, accent, warning, danger }

    public var label: String
    public var tone = Tone.plain
    public var isExpired = false
    public var question: String?
    public var detail: String?
    public var contact: String?
    public var showsResult = false
    public var result: String?
    public var resultLink: String?
    public var reply = false, stop = false, check = false, markDone = false, handOffAgain = false

    public init(_ run: AgentRunDTO, now: Date, relay: Bool) {
        let state = run.primaryState
        label = state.label
        if run.contentExpired || state == .contentExpired || now >= run.contentExpiresAt {
            (label, isExpired) = (AgentsCopy.expired, true)
            return
        }
        let time = run.lastContactAt.map { $0.formatted(date: .omitted, time: .shortened) }
        switch state {
        case .needsYou:
            (tone, question, reply, stop) = (.accent, run.questionText, run.controls.reply, run.controls.cancel)
        case .sent, .accepted, .running:
            (detail, stop, contact) = (run.progressText, run.controls.cancel, time.map(AgentsCopy.lastContact))
        case .queued:
            (detail, stop) = (AgentsCopy.queued, run.controls.cancel)
        case .deliveryUnconfirmed:
            check = true
        case .agentReportedComplete:
            label = time.map { "\(AgentsCopy.reportedComplete) · \($0)" } ?? label
            let tooLarge = run.resultAvailability == "too_large"
            (showsResult, markDone, handOffAgain) = (true, true, relay)
            (result, resultLink) = (tooLarge ? AgentsCopy.resultTooLarge : run.resultText, run.resultLink)
        case .failed:
            (tone, detail, handOffAgain) = (.danger, run.failureReason, relay)
        case .stoppedReporting:
            let ago = AgentRunItem.elapsed(since: run.lastContactAt, now: now).map(AgentsCopy.stoppedAgo)
            label = ago.map { "\(AgentsCopy.stoppedReporting) · \($0)" } ?? label
            (tone, stop, handOffAgain) = (.warning, run.controls.cancel, relay)
        case .cancelled, .agentNoLongerReportsThisRun, .connectionDisconnected:
            handOffAgain = relay
        case .notSent, .cancellationRequested, .contentExpired, .unknown:
            break
        }
    }
}

/// One line of the timeline: the state word and "10:02 · Guaranteed single start".
public struct AgentTimelineRow: Equatable, Sendable {
    public var word: String
    public var meta: String

    public static func rows(_ run: AgentRunDTO) -> [AgentTimelineRow] {
        func time(_ date: Date) -> String { date.formatted(date: .omitted, time: .shortened) }
        let tier: String? = switch run.guaranteeTier {
        case .guaranteed: AgentsCopy.guaranteed
        case .bestEffort: AgentsCopy.bestEffort
        default: nil
        }
        let first = AgentTimelineRow(word: AgentPrimaryState.sent.label, meta: ([time(run.createdAt)] + [tier].compactMap { $0 }).joined(separator: " · "))
        let words = ["accepted": "Accepted", "running": "Running", "blocked": "Needs you", "completed": AgentsCopy.reportedComplete, "failed": "Failed"]
        return [first] + run.events.sorted { $0.receivedAt < $1.receivedAt }.map { event in
            AgentTimelineRow(word: event.kind == "task_succession" ? AgentsCopy.succession : words[event.type] ?? "Cancelled", meta: time(event.receivedAt))
        }
    }
}

/// The state behind one step's run section: its runs (newest first), the drafts and the run actions. Memory only.
@MainActor
@Observable
public final class AgentRunSectionModel {
    public private(set) var runs: [AgentRunDTO] = []
    public private(set) var asksPassword = false
    /// The last read of this step's runs failed: what shows is the last known state, read-only (030-FR-025).
    public private(set) var isStale = false
    public var selectedRunID: String?
    public var answer = ""
    public var nextStep = ""
    public var password = ""

    public let taskServerID: String
    public let projectID: String?
    @ObservationIgnored private let remote: any AgentRunSectionRemote
    @ObservationIgnored private let availability: AgentAvailability
    @ObservationIgnored private let steps: any StepCommands
    @ObservationIgnored private let refreshStore: @MainActor () async -> Void
    @ObservationIgnored public let now: @MainActor () -> Date
    @ObservationIgnored private let cachedRun: @MainActor () -> AgentRunDTO?
    @ObservationIgnored public private(set) lazy var actions = AgentRunActions(
        remote: remote, availability: availability, steps: steps, refresh: { [weak self] in await self?.refreshAll() })

    public init(
        taskServerID: String, projectID: String?, remote: any AgentRunSectionRemote, availability: AgentAvailability,
        steps: any StepCommands, now: @escaping @MainActor () -> Date = { Date() },
        refreshStore: @escaping @MainActor () async -> Void = {},
        cachedRun: @escaping @MainActor () -> AgentRunDTO? = { nil }
    ) {
        (self.taskServerID, self.projectID, self.remote) = (taskServerID, projectID, remote)
        (self.availability, self.steps, self.now, self.refreshStore) = (availability, steps, now, refreshStore)
        self.cachedRun = cachedRun
    }

    public var shown: AgentRunDTO? { runs.first { $0.id == selectedRunID } ?? runs.first }

    /// Choosing the shown earlier run again goes back to the latest.
    public func choose(_ run: AgentRunDTO) { selectedRunID = selectedRunID == run.id ? nil : run.id }

    public func load() async {
        guard let all = try? await remote.agentRuns(taskID: taskServerID) else {
            isStale = true
            if runs.isEmpty, let cached = cachedRun() { runs = [cached] }
            return
        }
        isStale = false
        runs = all.sorted { $0.createdAt > $1.createdAt }
        if let selectedRunID, !runs.contains(where: { $0.id == selectedRunID }) { self.selectedRunID = nil }
    }

    private func refreshAll() async {
        await refreshStore()
        await load()
    }

    public func sendReply() async {
        guard !isStale, let run = shown else { return }
        await actions.reply(to: run, message: answer)
        if actions.phase == .done { answer = "" }
    }

    /// The password field appears only after the server refused a check for want of it, and is cleared after each try.
    public func checkAgain() async {
        guard !isStale, let run = shown else { return }
        await actions.checkAgain(run, password: password)
        password = ""
        asksPassword = actions.phase == .failed(.wrongPassword)
    }
}
