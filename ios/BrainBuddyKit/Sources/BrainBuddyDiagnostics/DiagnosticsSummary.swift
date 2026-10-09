import Foundation

/// The figures the Performance screen shows and the export leads with,
/// computed over the samples and thermal events of one time window.
public struct DiagnosticsSummary: Codable, Sendable, Equatable {
    public struct ScreenLoad: Codable, Sendable, Equatable {
        public var screen: String
        /// Time-weighted, like `averageCPUPercent`.
        public var averageCPUPercent: Double
        public var sampledSeconds: Double

        public init(screen: String, averageCPUPercent: Double, sampledSeconds: Double) {
            self.screen = screen
            self.averageCPUPercent = averageCPUPercent
            self.sampledSeconds = sampledSeconds
        }
    }

    /// The window's length; it ends at `now`.
    public var windowSeconds: Double
    /// Foreground time the samples cover (the app is not sampled in the background).
    public var sampledSeconds: Double
    /// Time-weighted over the samples; nil without samples.
    public var averageCPUPercent: Double?
    public var peak: CPUSample?
    /// Busiest first.
    public var byScreen: [ScreenLoad]
    /// The hottest state reported in the window, by sample or event.
    public var hottestThermal: ThermalLevel?
    /// Thermal events at serious or critical.
    public var seriousThermalEvents: Int

    public init(log: DiagnosticsLog, now: Date, windowSeconds: Double) {
        let start = now.addingTimeInterval(-windowSeconds)
        let samples = log.samples.filter { $0.at > start && $0.at <= now }
        let events = log.thermalEvents.filter { $0.at > start && $0.at <= now }

        self.windowSeconds = windowSeconds
        sampledSeconds = samples.reduce(0) { $0 + $1.seconds }
        averageCPUPercent = Self.weightedAverage(samples)
        peak = samples.max { $0.cpuPercent < $1.cpuPercent }

        var screens: [String: [CPUSample]] = [:]
        for sample in samples { screens[sample.screen, default: []].append(sample) }
        byScreen = screens.compactMap { screen, samples in
            Self.weightedAverage(samples).map {
                ScreenLoad(screen: screen, averageCPUPercent: $0, sampledSeconds: samples.reduce(0) { $0 + $1.seconds })
            }
        }
        .sorted { ($0.averageCPUPercent, $1.screen) > ($1.averageCPUPercent, $0.screen) }

        hottestThermal = (samples.map(\.thermal) + events.map(\.level)).max()
        seriousThermalEvents = events.filter { $0.level >= .serious }.count
    }

    private static func weightedAverage(_ samples: [CPUSample]) -> Double? {
        let seconds = samples.reduce(0) { $0 + $1.seconds }
        guard seconds > 0 else { return nil }
        return samples.reduce(0) { $0 + $1.cpuPercent * $1.seconds } / seconds
    }
}
