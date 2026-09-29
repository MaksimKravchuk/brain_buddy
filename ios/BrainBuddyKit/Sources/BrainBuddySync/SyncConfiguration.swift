import BrainBuddyAPI
import Foundation

/// Tunables for `SyncEngine`. The defaults are the documented protocol
/// (`docs/native-ios-app.md` › Sync); tests swap the scheduler and jitter.
public struct SyncConfiguration: Sendable {
    /// Runs the debounce and retry timers.
    public var scheduler: any SyncScheduler
    /// A number in `0..<1` that spreads retries (0.5 means no jitter).
    public var jitter: @Sendable () -> Double
    /// Wait after the last local change before syncing.
    public var localChangeDelay: Duration
    /// First retry delay; it doubles per consecutive failure up to `maximumRetryDelay`.
    public var initialRetryDelay: TimeInterval
    public var maximumRetryDelay: TimeInterval
    /// A cycle pulls when the last pull is older than this, even without changes.
    public var pullInterval: TimeInterval
    /// Parallel `GET /tasks/{id}` while hydrating subtasks and comments.
    public var hydrationConcurrency: Int
    /// Tasks hydrated per cycle at most.
    public var hydrationBudget: Int
    /// A create whose first uncertain attempt is older than this is not resent
    /// blindly: the engine pulls and adopts a matching server record first
    /// (the server forgets idempotency keys after 24 hours).
    public var uncertainCreateAge: TimeInterval
    /// Tolerated difference between this device's clock and the server's
    /// when matching a server record to an uncertain create.
    public var clockSkewTolerance: TimeInterval
    /// Consecutive failed cycles with server errors before the status says `.failing`.
    public var failingThreshold: Int
    /// The server failing the operation at the front of the outbox this many
    /// times in a row (5xx, or a success it cannot be read from) sets it
    /// aside as a sync issue, so the changes behind it go out.
    public var rejectionLimit: Int
    /// The same once the operation has been failing this long (and at least
    /// twice in a row), measured from its first attempt with the current key.
    public var rejectionAge: TimeInterval
    /// Sent as `X-Client: brainbuddy-ios/<version>`.
    public var clientVersion: String

    public init(
        scheduler: any SyncScheduler = TaskSyncScheduler(),
        jitter: @escaping @Sendable () -> Double = { Double.random(in: 0..<1) },
        localChangeDelay: Duration = .seconds(2),
        initialRetryDelay: TimeInterval = 2,
        maximumRetryDelay: TimeInterval = 300,
        pullInterval: TimeInterval = 60,
        hydrationConcurrency: Int = 4,
        hydrationBudget: Int = 50,
        uncertainCreateAge: TimeInterval = 23 * 3600,
        clockSkewTolerance: TimeInterval = 300,
        failingThreshold: Int = 2,
        rejectionLimit: Int = 8,
        rejectionAge: TimeInterval = 24 * 3600,
        clientVersion: String = BrainBuddyAPI.bundleVersion
    ) {
        self.scheduler = scheduler
        self.jitter = jitter
        self.localChangeDelay = localChangeDelay
        self.initialRetryDelay = initialRetryDelay
        self.maximumRetryDelay = maximumRetryDelay
        self.pullInterval = pullInterval
        self.hydrationConcurrency = max(1, hydrationConcurrency)
        self.hydrationBudget = max(0, hydrationBudget)
        self.uncertainCreateAge = uncertainCreateAge
        self.clockSkewTolerance = clockSkewTolerance
        self.failingThreshold = max(1, failingThreshold)
        self.rejectionLimit = max(1, rejectionLimit)
        self.rejectionAge = rejectionAge
        self.clientVersion = clientVersion
    }

    /// The retry delay after `failures` consecutive failed cycles (1 or more):
    /// 2 s, 4 s, 8 s … spread by ±20 % with `jitter`, never over 5 minutes.
    public func retryDelay(afterFailures failures: Int) -> TimeInterval {
        let exponent = Double(max(0, failures - 1))
        let base = min(maximumRetryDelay, initialRetryDelay * pow(2, min(exponent, 30)))
        return min(maximumRetryDelay, base * (0.8 + 0.4 * min(max(jitter(), 0), 1)))
    }
}
