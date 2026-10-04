import Foundation
import Synchronization

/// A clock that only moves when a test moves it. Share one between the fake
/// server and the sync engine (`now: clock.provider`) so "24 hours later" is
/// one call, not a wait.
public final class ManualClock: Sendable {
    private let current: Mutex<Date>

    /// Starts at `start`; the default is a fixed instant in September 2026.
    public init(_ start: Date = Date(timeIntervalSince1970: 1_790_000_000)) {
        current = Mutex(start)
    }

    public func now() -> Date { current.withLock { $0 } }

    public func advance(by interval: TimeInterval) {
        current.withLock { $0 = $0.addingTimeInterval(interval) }
    }

    public func set(_ date: Date) {
        current.withLock { $0 = date }
    }

    /// The closure form the engine and the server take.
    public var provider: @Sendable () -> Date {
        { [self] in now() }
    }
}
