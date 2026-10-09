import Foundation

/// `ProcessInfo.ThermalState` in a form the package can store and test on
/// Linux, where that API does not exist.
public enum ThermalLevel: String, Codable, Sendable, CaseIterable, Comparable {
    case nominal, fair, serious, critical

    public static func < (lhs: ThermalLevel, rhs: ThermalLevel) -> Bool {
        allCases.firstIndex(of: lhs)! < allCases.firstIndex(of: rhs)!
    }
}

/// How busy the process was over one sampling window.
public struct CPUSample: Codable, Sendable, Equatable {
    /// The end of the window.
    public var at: Date
    /// The length of the window.
    public var seconds: Double
    /// Process CPU time over wall time; 100 means one core busy for the
    /// whole window, so a multithreaded burst can exceed 100.
    public var cpuPercent: Double
    /// The screen on top when the window ended (`PerformanceDiagnostics`
    /// names screens by kind, never by user content).
    public var screen: String
    public var thermal: ThermalLevel
    public var lowPowerMode: Bool

    public init(at: Date, seconds: Double, cpuPercent: Double, screen: String, thermal: ThermalLevel, lowPowerMode: Bool) {
        self.at = at
        self.seconds = seconds
        self.cpuPercent = cpuPercent
        self.screen = screen
        self.thermal = thermal
        self.lowPowerMode = lowPowerMode
    }
}

/// The thermal state the system reported, when it changed.
public struct ThermalEvent: Codable, Sendable, Equatable {
    public var at: Date
    public var level: ThermalLevel
    public var screen: String

    public init(at: Date, level: ThermalLevel, screen: String) {
        self.at = at
        self.level = level
        self.screen = screen
    }
}

/// What the app recorded about its own performance, newest last. Bounded, so
/// it can stay on the device indefinitely: the oldest entries go first.
public struct DiagnosticsLog: Codable, Sendable, Equatable {
    /// Six hours of foreground time at one sample every 10 s.
    public static let sampleLimit = 2_160
    public static let thermalEventLimit = 500
    public static let launchLimit = 200

    public private(set) var samples: [CPUSample]
    public private(set) var thermalEvents: [ThermalEvent]
    /// Process starts, so samples can be told apart by session.
    public private(set) var launches: [Date]

    public init(samples: [CPUSample] = [], thermalEvents: [ThermalEvent] = [], launches: [Date] = []) {
        self.samples = Array(samples.suffix(Self.sampleLimit))
        self.thermalEvents = Array(thermalEvents.suffix(Self.thermalEventLimit))
        self.launches = Array(launches.suffix(Self.launchLimit))
    }

    public var isEmpty: Bool { samples.isEmpty && thermalEvents.isEmpty && launches.isEmpty }

    public mutating func append(_ sample: CPUSample) {
        samples.append(sample)
        Self.trim(&samples, to: Self.sampleLimit)
    }

    public mutating func append(_ event: ThermalEvent) {
        thermalEvents.append(event)
        Self.trim(&thermalEvents, to: Self.thermalEventLimit)
    }

    public mutating func recordLaunch(at date: Date) {
        launches.append(date)
        Self.trim(&launches, to: Self.launchLimit)
    }

    private static func trim<Element>(_ array: inout [Element], to limit: Int) {
        if array.count > limit { array.removeFirst(array.count - limit) }
    }
}
