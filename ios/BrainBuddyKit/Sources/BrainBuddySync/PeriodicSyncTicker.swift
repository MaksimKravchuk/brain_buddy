import BrainBuddyCore
import Foundation
import Synchronization

/// Calls `fire` every `interval` while active: the Mac's `.periodic` tick for the whole
/// run, the iPhone's while its scene is active (spec 021, FR-006, FR-032). Inactive, it
/// schedules nothing. Both apps share this one implementation, so the cadence is tested here.
public final class PeriodicSyncTicker: Sendable {
    private struct State {
        var active = false
        /// Bumped on every change of `active`, so a tick that was already on its way is dropped.
        var generation = 0
        var work: SyncScheduledWork?
    }

    private let interval: Duration
    private let scheduler: any SyncScheduler
    private let fire: @Sendable () async -> Void
    private let state = Mutex(State())

    public init(
        interval: TimeInterval = SyncTiming.periodicTick, scheduler: any SyncScheduler,
        fire: @escaping @Sendable () async -> Void
    ) {
        self.interval = .seconds(interval)
        self.scheduler = scheduler
        self.fire = fire
    }

    /// Starts (or stops) the repeating tick. Asking for the state it is already in changes nothing.
    public func setActive(_ active: Bool) {
        state.withLock { state in
            guard state.active != active else { return }
            state.active = active
            state.generation += 1
            state.work?.cancel()
            state.work = active ? arm(state.generation) : nil
        }
    }

    private func arm(_ generation: Int) -> SyncScheduledWork {
        scheduler.schedule(after: interval) { [weak self] in await self?.tick(generation) }
    }

    private func tick(_ generation: Int) async {
        let current = state.withLock { state -> Bool in
            guard state.active, state.generation == generation else { return false }
            state.work = arm(generation)
            return true
        }
        if current { await fire() }
    }
}
