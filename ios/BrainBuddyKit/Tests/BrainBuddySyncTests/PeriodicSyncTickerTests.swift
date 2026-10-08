import BrainBuddyCore
import Foundation
import Synchronization
import Testing

@testable import BrainBuddySync

@Suite("PeriodicSyncTicker")
struct PeriodicSyncTickerTests {
    private final class Ticks: Sendable {
        private let count = Mutex(0)
        var value: Int { count.withLock { $0 } }
        func record() { count.withLock { $0 += 1 } }
    }

    private func makeTicker(_ scheduler: ManualSyncScheduler, _ ticks: Ticks) -> PeriodicSyncTicker {
        PeriodicSyncTicker(interval: SyncTiming.periodicTick, scheduler: scheduler) { ticks.record() }
    }

    @Test("021-FR-006 021-FR-032 while active it fires every 15 s")
    func firesEveryFifteenSecondsWhileActive() async {
        let scheduler = ManualSyncScheduler()
        let ticks = Ticks()
        let ticker = makeTicker(scheduler, ticks)
        #expect(scheduler.pendingDelays.isEmpty, "nothing runs until it is made active")

        ticker.setActive(true)
        for expected in 1...3 {
            #expect(scheduler.pendingDelays == [.seconds(15)])
            await scheduler.runNext()
            #expect(ticks.value == expected)
        }
        ticker.setActive(true)
        #expect(scheduler.pendingDelays == [.seconds(15)], "asking again does not schedule a second timer")
    }

    @Test("021-FR-032 inactive it fires nothing, and it starts again when reactivated")
    func stopsWhenInactiveAndRestarts() async {
        let scheduler = ManualSyncScheduler()
        let ticks = Ticks()
        let ticker = makeTicker(scheduler, ticks)
        ticker.setActive(true)
        await scheduler.runNext()
        #expect(ticks.value == 1)

        ticker.setActive(false)
        ticker.setActive(false)
        #expect(scheduler.pendingDelays.isEmpty)
        #expect(await scheduler.runNext() == false)
        #expect(ticks.value == 1)

        ticker.setActive(true)
        #expect(scheduler.pendingDelays == [.seconds(15)], "a new 15 s wait, not the old one's remainder")
        await scheduler.runNext()
        #expect(ticks.value == 2)
    }

    @Test("021-FR-006 a tick reaches the engine as .periodic, and runs a cycle once the last pull is old enough")
    func tickReachesTheEngine() async throws {
        #expect(SyncTrigger.periodic.rawValue == "periodic")
        let harness = SyncHarness()
        let device = await harness.device { $0.pullInterval = SyncTiming.pullAge }
        try await device.signIn()
        device.transport.clearLog()
        let engine = device.engine
        let scheduler = ManualSyncScheduler()
        let ticker = PeriodicSyncTicker(interval: SyncTiming.periodicTick, scheduler: scheduler) {
            await engine.request(.periodic)
        }
        ticker.setActive(true)

        harness.clock.advance(by: 15)
        await scheduler.runNext()
        await engine.waitUntilIdle()
        #expect(device.transport.requests.isEmpty, "15 s after a pull is too soon")

        harness.clock.advance(by: 15)
        await scheduler.runNext()
        await engine.waitUntilIdle()
        #expect(device.transport.requests.contains { $0.route.hasPrefix("GET /tasks") }, "30 s after it, the tick pulls")
    }
}
