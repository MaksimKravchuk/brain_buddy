#if canImport(Darwin)
    import Darwin
#elseif canImport(Glibc)
    import Glibc
#endif

/// The CPU time this process has used so far, from `clock_gettime`
/// (not a required-reason API, and the same call on Darwin and Linux).
public enum ProcessCPUTime {
    public static func seconds() -> Double? {
        var time = timespec()
        guard clock_gettime(CLOCK_PROCESS_CPUTIME_ID, &time) == 0 else { return nil }
        return Double(time.tv_sec) + Double(time.tv_nsec) / 1_000_000_000
    }
}

/// Turns successive readings of process CPU time into the share of one core
/// used between them.
public struct CPUMeter: Sendable {
    public struct Measurement: Sendable, Equatable {
        /// Wall time since the previous reading.
        public var seconds: Double
        /// 100 means one core busy for the whole interval.
        public var cpuPercent: Double

        public init(seconds: Double, cpuPercent: Double) {
            self.seconds = seconds
            self.cpuPercent = cpuPercent
        }
    }

    private var last: (cpuSeconds: Double, at: ContinuousClock.Instant)?

    public init() {}

    /// The usage since the previous reading; nil for the first reading and
    /// when no time has passed. A clock that went backwards reads as 0 %.
    public mutating func reading(cpuSeconds: Double, at instant: ContinuousClock.Instant) -> Measurement? {
        defer { last = (cpuSeconds, instant) }
        guard let last else { return nil }
        let elapsed = last.at.duration(to: instant)
        let seconds = Double(elapsed.components.seconds) + Double(elapsed.components.attoseconds) / 1e18
        guard seconds > 0 else { return nil }
        let used = max(0, cpuSeconds - last.cpuSeconds)
        return Measurement(seconds: seconds, cpuPercent: used / seconds * 100)
    }
}
