import BrainBuddyAPI
import BrainBuddyCore
import BrainBuddyFakeServer
import Foundation
import Testing

@testable import BrainBuddySync

/// Two devices on one account edit offline, sync in random order through
/// lost responses, timeouts, 5xx, 429 and expired sessions, and must end up
/// showing exactly what the server has.
@Suite("SyncEngine: two devices converge")
struct SyncEngineConvergenceTests {
    static let seeds: [UInt64] = Array(1...40)
    static let steps = 70

    /// What one run went through, from the devices' request logs.
    struct Run {
        var accepted = 0
        var staleRevisions = 0
        var duplicateNames = 0
        var idempotencyConflicts = 0
        var rejections = 0
        var lostResponses = 0
        var issues = 0
        var expiredKeys = false
        var tasks = 0
    }

    @Test("Random offline edits on two devices converge to the server's state", arguments: seeds)
    func converges(seed: UInt64) async throws {
        let run = try await Self.run(seed: seed)
        #expect(run.accepted > Self.steps / 3, "seed \(seed): the generator should mostly produce valid commands")
        #expect(run.idempotencyConflicts == 0, "seed \(seed): a key was reused for another body")
    }

    @Test("The random runs go through every recovery path")
    func exercisesRecoveryPaths() async throws {
        var total = Run()
        for seed in Self.seeds.prefix(12) {
            let run = try await Self.run(seed: seed)
            total.staleRevisions += run.staleRevisions
            total.duplicateNames += run.duplicateNames
            total.rejections += run.rejections
            total.lostResponses += run.lostResponses
            total.issues += run.issues
            total.expiredKeys = total.expiredKeys || run.expiredKeys
        }
        #expect(total.staleRevisions > 0)
        #expect(total.duplicateNames > 0)
        #expect(total.rejections > 0)
        #expect(total.lostResponses > 0)
        #expect(total.issues > 0)
        #expect(total.expiredKeys)
    }

    /// The scenario; every convergence expectation is checked inside.
    static func run(seed: UInt64) async throws -> Run {
        let harness = SyncHarness()
        // Detail reads one at a time, so an injected fault always hits the
        // same request and a seed replays exactly (concurrent reads are
        // covered by the pull tests).
        let sequential: (inout SyncConfiguration) -> Void = { $0.hydrationConcurrency = 1 }
        let devices = [await harness.device(sequential), await harness.device(sequential)]
        for device in devices { try await device.signIn() }
        var rng = SeededGenerator(seed: seed &* 0x9E37_79B9)
        var generators = [RandomCommands(seed: seed, device: "a"), RandomCommands(seed: seed ^ 0xB0B, device: "b")]
        var run = Run()

        for _ in 0..<steps {
            harness.clock.advance(by: TimeInterval(Int.random(in: 1...90, using: &rng)))
            let index = Int.random(in: 0..<2, using: &rng)
            let device = devices[index]
            switch Int.random(in: 0..<100, using: &rng) {
            case 0..<50:
                for _ in 0..<Int.random(in: 1...3, using: &rng) {
                    let command = generators[index].next(for: try await device.current())
                    if (try? await device.apply(command)) != nil { run.accepted += 1 }
                }
            case 50..<72:
                try await sync(device)
            case 72..<88:
                injectFault(into: device, using: &rng)
                try await sync(device)
            case 88..<94:
                let tasks = try await device.document().base.tasks.values.sorted { $0.replayKey < $1.replayKey }
                if let task = tasks.randomElement(using: &rng) {
                    await device.engine.refreshTask(task.id)
                }
            case 94..<96 where seed.isMultiple(of: 4) && !run.expiredKeys:
                // A day offline: every idempotency key the server held expires.
                harness.clock.advance(by: 25 * 3600)
                run.expiredKeys = true
            default:
                for device in devices { try await sync(device) }
            }
        }

        // Back to a healthy network: both devices sync twice.
        for device in devices { device.transport.clearFaults() }
        for _ in 0..<2 {
            for device in devices {
                harness.clock.advance(by: 5)
                try await sync(device)
            }
        }
        for (index, device) in devices.enumerated() {
            let document = try await device.document()
            #expect(document.outbox.isEmpty, "seed \(seed): device \(index) still has \(document.outbox.map(\.command))")
            let status = await device.status
            #expect(status.isIdle, "seed \(seed): device \(index) is \(status)")
            run.issues += document.issues.count
        }

        // Every record matches the server, compared by server id.
        let server = CanonicalState(harness.snapshot, children: false)
        let a = try CanonicalState(await devices[0].current(), children: false)
        let b = try CanonicalState(await devices[1].current(), children: false)
        #expect(a == server.restrictingInactive(to: a), "seed \(seed), a: \(a.differences(from: server.restrictingInactive(to: a)))")
        #expect(b == server.restrictingInactive(to: b), "seed \(seed), b: \(b.differences(from: server.restrictingInactive(to: b)))")
        #expect(a.tasks == b.tasks, "seed \(seed): \(a.differences(from: b))")

        // Subtask and comment edits do not bump the task, so children match
        // once every task has been opened (hydrated) on both devices.
        for device in devices {
            for task in try await device.document().base.tasks.values.sorted(by: { $0.replayKey < $1.replayKey }) {
                await device.engine.refreshTask(task.id)
            }
        }
        let serverWithChildren = CanonicalState(harness.snapshot, children: true)
        for (index, device) in devices.enumerated() {
            let state = try CanonicalState(await device.current(), children: true)
            let expected = serverWithChildren.restrictingInactive(to: state)
            #expect(state == expected, "seed \(seed), device \(index): \(state.differences(from: expected))")
        }

        // No create was applied twice (titles and bodies are unique per command).
        // After keys expire a lost create can be sent again when its record
        // changed beyond recognition elsewhere, a documented limitation.
        let snapshot = harness.snapshot
        run.tasks = snapshot.tasks.count
        if !run.expiredKeys {
            let titles = snapshot.tasks.values.map(\.title)
            #expect(Set(titles).count == titles.count, "seed \(seed): duplicated task")
            let subtasks = snapshot.tasks.values.flatMap(\.subtasks).map(\.title)
            #expect(Set(subtasks).count == subtasks.count, "seed \(seed): duplicated subtask")
            let comments = snapshot.tasks.values.flatMap(\.comments).map(\.body)
            #expect(Set(comments).count == comments.count, "seed \(seed): duplicated comment")
        }

        for exchange in devices.flatMap(\.transport.exchanges) {
            if exchange.fault == .dropResponse { run.lostResponses += 1 }
            guard exchange.fault == nil, let status = exchange.statusCode, let message = exchange.errorMessage else { continue }
            switch status {
            case 409 where message.hasSuffix("has newer changes; reload before saving."): run.staleRevisions += 1
            case 409 where message.hasPrefix("Idempotency-Key"): run.idempotencyConflicts += 1
            case 409: run.duplicateNames += 1
            case 400, 404, 422: run.rejections += 1
            default: break
            }
        }
        return run
    }

    /// Syncs, signing in again first when the session expired (faults left
    /// over from earlier steps are cleared first).
    static func sync(_ device: Device) async throws {
        if await device.status == .needsSignIn {
            device.transport.clearFaults()
            try await device.signIn()
        } else {
            await device.sync()
        }
    }

    static func injectFault(into device: Device, using rng: inout SeededGenerator) {
        let faults: [FakeServerTransport.Fault] = [.offline, .timeout, .dropResponse, .status(500), .status(503), .status(429)]
        let fault = faults.randomElement(using: &rng)!
        let anyRequest: FakeServerTransport.Matcher = { _ in true }
        let matching = Bool.random(using: &rng) ? FakeServerTransport.isMutation : anyRequest
        device.transport.inject(fault, times: Int.random(in: 1...2, using: &rng), matching: matching)
        if Int.random(in: 0..<8, using: &rng) == 0 { device.transport.inject(.status(401)) }
    }
}
