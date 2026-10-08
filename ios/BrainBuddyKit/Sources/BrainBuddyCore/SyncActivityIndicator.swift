import Foundation

/// When the small "syncing" indicator shows (FR-013): only for a sync running at least
/// `SyncTiming.indicatorDelay`, then at least `SyncTiming.indicatorMinimum`, and across
/// back-to-back cycles as one span. A value with no timers: the app asks `isVisible(at:)`
/// and sets one timer for `nextChange(after:)`.
public struct SyncActivityIndicator: Equatable, Sendable {
    /// The running cycle's start; nil when idle.
    private var runningSince: Date?
    /// When the current visible span began; nil until a cycle has run long enough.
    private var spanStart: Date?
    /// While idle, when the span ends.
    private var heldUntil: Date?

    public init() {}

    public mutating func started(at date: Date) {
        guard runningSince == nil else { return }
        if !isVisible(at: date) {
            spanStart = nil
            heldUntil = nil
        }
        runningSince = date
    }

    public mutating func finished(at date: Date) {
        guard let start = runningSince else { return }
        runningSince = nil
        if spanStart == nil, date.timeIntervalSince(start) >= SyncTiming.indicatorDelay {
            spanStart = start.addingTimeInterval(SyncTiming.indicatorDelay)
        }
        heldUntil = spanStart.map { max(date, $0.addingTimeInterval(SyncTiming.indicatorMinimum)) }
    }

    public func isVisible(at date: Date) -> Bool {
        if let start = runningSince {
            return spanStart != nil || date.timeIntervalSince(start) >= SyncTiming.indicatorDelay
        }
        guard let spanStart, let heldUntil else { return false }
        return date >= spanStart && date < heldUntil
    }

    /// The next instant the answer can change, for the app's one timer; nil when it cannot.
    public func nextChange(after date: Date) -> Date? {
        if let start = runningSince {
            let appears = start.addingTimeInterval(SyncTiming.indicatorDelay)
            return spanStart == nil && date < appears ? appears : nil
        }
        guard let heldUntil, date < heldUntil else { return nil }
        return heldUntil
    }
}
