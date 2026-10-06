import Foundation
import Testing

@testable import BrainBuddyCore

/// The compactor's contract, checked over generated histories:
/// `replay(appending(op, to: outbox), onto: base).state` equals the state after
/// applying every accepted command one by one, apart from the server-assigned
/// fields listed on `GTDState.ignoringServerAssignedFields` — while pushes
/// mark operations as sent and acknowledgements move them into the base.
@Suite("OutboxCompactor: replay equivalence")
struct CompactionPropertyTests {
    static let seeds: [UInt64] = Array(1...1000)
    static let steps = 80

    @Test("Compacted outboxes replay to the sequential state", arguments: seeds)
    func replayEquivalence(seed: UInt64) throws {
        try run(seed: seed, clockAware: false)
    }

    /// Spec 020: once the review is exposed the compactor is clock-aware, and
    /// then the formulation clock fields match too (020-FR-001, T051).
    @Test("020-FR-001 clock-aware compacted outboxes replay to the sequential state, clocks included", arguments: seeds.prefix(300))
    func clockAwareReplayEquivalence(seed: UInt64) throws {
        try run(seed: seed, clockAware: true)
    }

    /// With decisions and their Undo, bulk releases and their Undo and review
    /// runs in the histories, the cancel rules and "a review command blocks a
    /// fold" keep replay equivalent (020-FR-048, 020-FR-017, 020-FR-029).
    @Test("020-FR-048 020-FR-017 020-FR-029 review commands in generated histories replay to the sequential state", arguments: seeds.prefix(300))
    func reviewCommandReplayEquivalence(seed: UInt64) throws {
        try run(seed: seed, clockAware: true, includeReview: true)
    }

    @Test("020-FR-048 the generated review histories exercise the cancel rules")
    func exercisesReviewCancels() {
        var cancelled: Set<String> = []
        for seed in Self.seeds.prefix(300) {
            var generator = CommandGenerator(seed: seed, includeReview: true)
            var state = GTDState.empty
            var outbox: [PendingOperation] = []
            for step in 0..<Self.steps {
                let command = generator.next(for: state)
                guard (try? GTDReducer.apply(command, at: Fixture.at(step), to: &state)) != nil else { continue }
                let count = outbox.count
                outbox = OutboxCompactor.appending(
                    PendingOperation(command: command, issuedAt: Fixture.at(step)), to: outbox, clockAware: true
                )
                if outbox.count < count + 1 {
                    switch command {
                    case .undoDecision: cancelled.insert("decision")
                    case .undoBulkRelease: cancelled.insert("bulk")
                    default: break
                    }
                }
            }
        }
        #expect(cancelled == ["decision", "bulk"])
    }

    /// Before exposure the compactor folds as it always did; the clock fields
    /// it shifts are a local projection that activation clamps and the server
    /// recomputes, so they count as server-assigned there.
    private func normalized(_ state: GTDState, clockAware: Bool) -> GTDState {
        var copy = state.ignoringServerAssignedFields
        guard !clockAware else { return copy }
        for id in copy.tasks.keys {
            copy.tasks[id]!.formulation = nil
            copy.tasks[id]!.consecutiveStalledFormulations = 0
            copy.tasks[id]!.parked = nil
        }
        return copy
    }

    /// Where two states differ, briefly, so a failing seed is readable.
    static func differences(_ lhs: GTDState, _ rhs: GTDState) -> [String] {
        var found: [String] = []
        for id in Set(lhs.tasks.keys).union(rhs.tasks.keys).sorted() where lhs.tasks[id] != rhs.tasks[id] {
            found.append("task \(id): \(String(describing: lhs.tasks[id])) vs \(String(describing: rhs.tasks[id]))")
        }
        if lhs.projects != rhs.projects { found.append("projects") }
        if lhs.tags != rhs.tags { found.append("tags") }
        for id in Set(lhs.review.decisions.keys).union(rhs.review.decisions.keys) where lhs.review.decisions[id] != rhs.review.decisions[id] {
            found.append("decision \(id): \(String(describing: lhs.review.decisions[id])) vs \(String(describing: rhs.review.decisions[id]))")
        }
        for id in Set(lhs.review.sessions.keys).union(rhs.review.sessions.keys) where lhs.review.sessions[id] != rhs.review.sessions[id] {
            found.append("session \(id): \(String(describing: lhs.review.sessions[id])) vs \(String(describing: rhs.review.sessions[id]))")
        }
        if lhs.review.receipts.sorted(by: { $0.taskID < $1.taskID }) != rhs.review.receipts.sorted(by: { $0.taskID < $1.taskID }) {
            found.append("receipts \(lhs.review.receipts) vs \(rhs.review.receipts)")
        }
        if lhs.review.bulkReleases != rhs.review.bulkReleases { found.append("bulk \(lhs.review.bulkReleases) vs \(rhs.review.bulkReleases)") }
        if lhs.review.navigatorConsents != rhs.review.navigatorConsents { found.append("consents") }
        if lhs.review.settings != rhs.review.settings { found.append("settings") }
        if lhs.review.parkAcks != rhs.review.parkAcks { found.append("parkAcks") }
        if lhs.review.receipts != rhs.review.receipts { found.append("receipt order \(lhs.review.receipts) vs \(rhs.review.receipts)") }
        return Array(found.prefix(3))
    }

    private func run(seed: UInt64, clockAware: Bool, includeReview: Bool = false) throws {
        var generator = CommandGenerator(seed: seed, includeReview: includeReview)
        // Even seeds start with no account (the outbox is all the data), odd
        // ones from server-confirmed records.
        var base = seed.isMultiple(of: 2) ? GTDState.empty : Self.randomBase(&generator)
        var sequential = base
        var outbox: [PendingOperation] = []
        var accepted = 0
        for step in 0..<Self.steps {
            let command = generator.next(for: sequential)
            let date = Fixture.at(step)
            guard (try? GTDReducer.apply(command, at: date, to: &sequential)) != nil else { continue }
            accepted += 1
            let before = outbox
            outbox = OutboxCompactor.appending(
                PendingOperation(command: command, issuedAt: date), to: outbox, clockAware: clockAware
            )
            #expect(
                outbox.filter(\.hasBeenSent) == before.filter(\.hasBeenSent),
                "seed \(seed), step \(step): sent operations must not change"
            )

            let replayed = OutboxReplayer.replay(outbox, onto: base)
            #expect(replayed.rejected.isEmpty, "seed \(seed), step \(step): \(replayed.rejected) after \(command)")
            #expect(
                normalized(replayed.state, clockAware: clockAware) == normalized(sequential, clockAware: clockAware),
                "seed \(seed), step \(step): replay diverged after \(command): \(Self.differences(normalized(replayed.state, clockAware: clockAware), normalized(sequential, clockAware: clockAware)))"
            )
            if normalized(replayed.state, clockAware: clockAware) != normalized(sequential, clockAware: clockAware)
                || !replayed.rejected.isEmpty
            {
                return
            }

            // A push attempt marks the first unsent operation as sent; an
            // acknowledgement moves the first operation into the base.
            switch Int.random(in: 0..<10, using: &generator.rng) {
            case 0:
                if let index = outbox.firstIndex(where: { !$0.hasBeenSent }) { outbox[index].attempts = 1 }
            case 1:
                guard let first = outbox.first, first.hasBeenSent else { break }
                _ = try GTDReducer.apply(first.command, at: first.issuedAt, to: &base, mode: .replay)
                outbox.removeFirst()
            default:
                break
            }
        }
        #expect(accepted > Self.steps / 3, "seed \(seed): the generator should mostly produce valid commands")
    }

    @Test("The generated histories exercise every folding rule")
    func exercisesEveryRule() {
        var appended = 0
        var kept = 0
        var folded: Set<String> = []
        for seed in Self.seeds {
            var generator = CommandGenerator(seed: seed)
            var state = GTDState.empty
            var outbox: [PendingOperation] = []
            for step in 0..<Self.steps {
                let command = generator.next(for: state)
                guard (try? GTDReducer.apply(command, at: Fixture.at(step), to: &state)) != nil else { continue }
                appended += 1
                let count = outbox.count
                outbox = OutboxCompactor.appending(PendingOperation(command: command, issuedAt: Fixture.at(step)), to: outbox)
                if outbox.count <= count { folded.insert(Self.rule(command)) }
            }
            kept += outbox.count
        }
        let rules: Set = ["updateTask", "move", "reopen", "updateSubtask", "updateComment", "updateProject", "renameTag"]
        #expect(folded == rules)
        #expect(kept < appended * 17 / 20, "kept \(kept) of \(appended) operations")
    }

    private static func rule(_ command: GTDCommand) -> String {
        switch command {
        case .updateTask: "updateTask"
        case .transitionTask(let transition): transition.action.rawValue
        case .updateSubtask: "updateSubtask"
        case .updateComment: "updateComment"
        case .updateProject: "updateProject"
        case .renameTag: "renameTag"
        default: "unexpected: \(command)"
        }
    }

    /// A server-confirmed starting point built from the same generator.
    static func randomBase(_ generator: inout CommandGenerator) -> GTDState {
        var state = GTDState.empty
        for step in 0..<25 {
            _ = try? GTDReducer.apply(generator.next(for: state), at: Fixture.at(step - 100), to: &state)
        }
        for id in state.tasks.keys {
            state.tasks[id]?.serverID = "task_\(id)"
            state.tasks[id]?.serverRevision = 1
        }
        for id in state.projects.keys { state.projects[id]?.serverID = "project_\(id)" }
        for id in state.tags.keys { state.tags[id]?.serverID = "tag_\(id)" }
        return state
    }
}
